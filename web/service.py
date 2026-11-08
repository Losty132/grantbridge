"""Glue between the web API and the existing engine.

Responsibilities
  * cache the dataset, rankings, precomputed enrichments and on-demand enrichments (thread-safe)
  * turn engine results into small JSON payloads for the browser
  * run EVERY piece of user-typed text through the privacy filter on the server before it is used
"""
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
import time
from collections import OrderedDict

from agency_profiles import loader
from common import config
from common.ai import AI
from common.storage import Storage
from data_retrieval.normalize import today
from data_retrieval.store import freshness_label, load_dataset
from eligibility.classify import APPEARS, NOT_ELIGIBLE, PARTNER, VERIFY
from feedback import learn
from feedback import store as fb
from privacy.filter import log_event, scan
from scoring import survey as sv
from scoring.enrich import enrich_now, survey_key
from scoring.rank import rank, urgency
from scoring.score import deadline_points
from summarization import brief
from summarization.explain import rule_explanation

log = logging.getLogger("web")

# The prototype has no sign-in (pilot: Entra ID). These limits stop anyone from hammering the slow, costly actions.
REFRESH_COOLDOWN = int(os.getenv("REFRESH_COOLDOWN_SECONDS", "600"))
EVAL_COOLDOWN = int(os.getenv("EVAL_COOLDOWN_SECONDS", "60"))

ELIG = {APPEARS: ("Eligible to apply", "ok"), VERIFY: ("Verify eligibility", "warn"),
        PARTNER: ("Partner must apply", "info"), NOT_ELIGIBLE: ("Not eligible", "hot")}


class PrivacyBlocked(Exception):
    """Raised when typed text contains internal-information markers. Nothing is saved or sent."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field, self.message = field, message


def screen(text: str, purpose: str, store) -> dict:
    """Server-side privacy screen. Returns cleaned text + a summary the UI shows. Logs only counts."""
    res = scan(text or "")
    log_event(store, purpose, res)
    if res.blocked:
        raise PrivacyBlocked(purpose, res.summary())
    return {"text": res.text, "changed": res.changed, "summary": res.summary() if res.changed else "",
            "redactions": dict(res.redactions), "layers": res.layers}


def money_short(v) -> str:
    if not v:
        return "—"
    return f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"


def funding_text(r: dict) -> str:
    lo, hi = r.get("award_floor"), r.get("award_ceiling")
    if lo and hi:
        return f"{money_short(lo)}–{money_short(hi)}"
    return f"Up to {money_short(hi)}" if hi else "Not specified"


class Engine:
    def __init__(self, storage: Storage | None = None, ai: AI | None = None):
        self.store = storage or Storage()
        self.ai = ai or AI()
        self._lock = threading.RLock()
        self._status, self._status_at = {}, 0.0
        self._data_ver, self._items = None, []
        self._ranked: OrderedDict = OrderedDict()
        self._enriched: OrderedDict = OrderedDict()
        self._pre: dict = {}
        self._busy = {"refresh": threading.Lock(), "evaluation": threading.Lock()}
        self._rank_locks: dict = {}
        self._small: dict = {}
        self._gen: dict = {}
        self._last_run: dict = {}

    # ------------------------------------------------------------------ data + caches
    def status(self, max_age: float = 30) -> dict:
        with self._lock:
            if time.time() - self._status_at > max_age:
                self._status = self.store.read_json("opportunities/status.json", default={}) or {}
                self._status_at = time.time()
            return self._status

    def data_version(self) -> str:
        """Changes when new data lands AND at local midnight, so days-left, 'expired' and every cached ranking
        roll over with the calendar instead of waiting for the next morning's refresh."""
        s = self.status()
        return f"{s.get('mode')}|{s.get('last_success')}|{today().isoformat()}"

    def items(self) -> list[dict]:
        ver = self.data_version()
        with self._lock:
            if ver != self._data_ver:
                self._items, _ = load_dataset(self.store)
                self._data_ver = ver
                self._ranked.clear()
                self._enriched.clear()
                self._pre.clear()
            return self._items

    def invalidate(self, agency_id: str | None = None):
        with self._lock:
            self._status_at = 0
            if agency_id:
                for k in [k for k in self._ranked if k[0] == agency_id]:
                    self._ranked.pop(k, None)
            else:
                self._ranked.clear()
                self._enriched.clear()
                self._pre.clear()

    # Surveys and decisions are read on every page view. They only change through this app (one replica), so they
    # are kept in memory and updated on write; a 60 s expiry covers edits made outside the app.
    def _cached(self, kind: str, agency_id: str, load):
        key = (kind, agency_id)
        with self._lock:
            hit = self._small.get(key)
            if hit and time.time() - hit[0] < 60:
                return hit[1]
            gen = self._gen.get(key, 0)
        value = load()
        with self._lock:
            # a write that happened while we were reading bumps the generation: don't publish the stale read
            if self._gen.get(key, 0) == gen:
                self._small[key] = (time.time(), value)
        return value

    def _forget(self, kind: str, agency_id: str):
        with self._lock:
            self._small.pop((kind, agency_id), None)
            self._gen[(kind, agency_id)] = self._gen.get((kind, agency_id), 0) + 1

    def saved_survey(self, agency_id: str) -> dict | None:
        return self._cached("survey", agency_id, lambda: fb.get_survey(self.store, agency_id))

    def survey(self, agency_id: str) -> dict:
        return self.saved_survey(agency_id) or {"agency_id": agency_id}

    def reviews(self, agency_id: str) -> dict:
        return self._cached("reviews", agency_id, lambda: fb.reviews(self.store, agency_id))

    def ranked(self, agency_id: str) -> tuple[dict, dict]:
        """Score every notice for this agency + survey once, then cache it. Decisions never trigger a re-score:
        only the top list is re-derived (cheap) so a Pass drops out of the top N instantly."""
        items = self.items()
        survey = self.survey(agency_id)
        reviews = self.reviews(agency_id)
        key = (agency_id, survey_key(survey), self._data_ver)
        with self._lock:
            base = self._ranked.get(key)
            if base is not None:
                self._ranked.move_to_end(key)
        if base is None:
            with self._rank_locks.setdefault(key, threading.Lock()):  # one scoring run per key, even under load
                with self._lock:
                    base = self._ranked.get(key)
                if base is None:
                    base = rank(items, loader.get(agency_id), survey, self.store, self.ai)
                    base["_survey_key"] = key[1]
                    with self._lock:
                        self._ranked[key] = base
                        while len(self._ranked) > 48:  # 33 agencies + a few survey variants
                            self._ranked.popitem(last=False)
            self._rank_locks.pop(key, None)
        out = self._with_feedback(base, reviews)
        passed = {oid for oid, v in reviews.items() if v.get("action") == "Pass"}
        top = [x for x in out["shortlist"] if x["record"]["id"] not in passed][: out["survey"]["top_n"]]
        return dict(out, top=top), reviews

    def _with_feedback(self, base: dict, reviews: dict) -> dict:
        """Stretch goal 3: nudge scores by the team's own Pursue / Maybe / Pass (feedback/learn.py). The base
        ranking stays cached; only the small nudge is recomputed when the decisions change."""
        labs = learn.labels(reviews)
        if not labs:
            return dict(base, base_shortlist=base["shortlist"], feedback_nudged=0, feedback_labels=0,
                        feedback_paused=False)
        fbkey = tuple(sorted(labs.items()))
        with self._lock:
            cache = base.setdefault("_fb", {})
            adj = cache.get(fbkey)
        if adj is None:
            with self._lock:
                learner = base.get("_learner")
            if learner is None:
                learner = learn.Learner(base["shortlist"])
                with self._lock:
                    base["_learner"] = learner
            nudges = learner.nudges(labs)
            # safeguard: learning stays on only if it ranks the team's own judged grants at least as well as the
            # plan alone (a grant is never nudged by its own decision, so this is a fair check)
            before, after, pairs = learn.agreement(base["shortlist"], learn.apply(base["shortlist"], nudges), labs)
            paused = pairs >= 3 and after < before
            if paused:
                nudges = {}
            sl = learn.apply(base["shortlist"], nudges)
            for i, x in enumerate(sl, 1):
                x["rank"] = i
            by_id = {x["record"]["id"]: x for x in sl}
            adj = {"shortlist": sl, "all": [by_id.get(x["record"]["id"], x) for x in base["all"]],
                   "nudged": len(nudges), "paused": paused}
            with self._lock:
                if len(cache) > 8:
                    cache.clear()
                cache[fbkey] = adj
        return dict(base, shortlist=adj["shortlist"], all=adj["all"], base_shortlist=base["shortlist"],
                    feedback_nudged=adj["nudged"], feedback_labels=len(labs), feedback_paused=adj["paused"])

    def touch(self):
        """Called on every API request: the background warm-up pauses while people are using the site."""
        self._last_request = time.monotonic()

    def warm(self):
        """Score every agency in the background so later visitors never wait. Agencies people already use
        (saved answers or decisions) go first, and the warm-up steps aside while any request is being served,
        so it never slows down the page someone is actually looking at."""
        def order():
            ids = list(loader.load_all())
            used = set()
            try:
                used = {p.split("/")[-1].split(".")[0] for p in self.store.list("surveys/") + self.store.list("feedback/")
                        if p.endswith(".json") and "/archive/" not in p}
            except Exception:
                pass
            return sorted(ids, key=lambda a: (a not in used, a != "deq", a))

        def go():
            for aid in order():
                while time.monotonic() - getattr(self, "_last_request", 0) < 1.5:
                    time.sleep(0.3)
                try:
                    self.ranked(aid)
                except Exception:  # warm-up must never take the app down
                    pass
        threading.Thread(target=go, name="warm-rankings", daemon=True).start()

    def _precomputed(self, agency_id: str) -> dict:
        with self._lock:
            if agency_id not in self._pre:
                self._pre[agency_id] = self.store.read_json(f"precomputed/{agency_id}.json", default={}) or {}
            return self._pre[agency_id]

    def light(self, x: dict, out: dict, agency_id: str) -> dict:
        pre = self._precomputed(agency_id)
        if pre and pre.get("survey_key") == out.get("_survey_key") \
                and pre.get("data_success") == self.status().get("last_success"):
            item = (pre.get("items") or {}).get(x["record"]["id"])
            if item:
                y = dict(item, record=x["record"], rank=x.get("rank"))
                y["other_targets"] = [tuple(t) for t in y.get("other_targets", [])]
                y = self._roll_deadline(y, out)
                y["base_score"], y["feedback"] = y["score"], x.get("feedback")
                if x.get("feedback"):   # the team's feedback nudge applies to precomputed items too
                    y["score"] = round(min(100.0, max(0.0, y["score"] + x["feedback"]["points"])), 1)
                return y
        if "explanation" not in x:
            x["explanation"] = rule_explanation(x)
            x["confidence"] = x["explanation"]["confidence"]
            x["needs_review"] = x["confidence"] == "low"
        return x

    @staticmethod
    def _roll_deadline(y: dict, out: dict) -> dict:
        """Precomputed items were scored on the morning of the refresh. Re-apply today's days-left to the deadline
        part of the score (and the expired check) so the list order and the card always agree."""
        r = y["record"]
        pts, feas = deadline_points(r, out["survey"], y.get("estimate") or {})
        comp = dict((y.get("components") or {}).get("deadline_feasibility") or {"max": 15})
        y["score"] = round(y["score"] - comp.get("points", 0) + pts, 1)
        y["components"] = dict(y.get("components") or {}, deadline_feasibility=dict(comp, points=pts, why=feas["text"]))
        y["feasibility"], y["urgency"] = feas, urgency(r.get("days_left"))
        if r.get("status") == "expired" and not any(e.startswith("Expired") for e in y.get("excluded") or []):
            y["excluded"] = [*(y.get("excluded") or []), f"Expired (closed {r.get('close_date')})"]
        return y

    def full(self, x: dict, out: dict, agency_id: str) -> dict:
        y = self.light(x, out, agency_id)
        if y.get("nofo") is not None and y is not x:
            return y  # precomputed already includes NOFO + AI explanation
        key = (agency_id, x["record"]["id"], out.get("_survey_key"), self._data_ver)
        with self._lock:
            if key in self._enriched:
                return self._enriched[key]
            gate = self._rank_locks.setdefault(("enrich", key), threading.Lock())
        with gate:  # two people opening the same grant at once → one PDF download and one AI call, not two
            with self._lock:
                if key in self._enriched:
                    return self._enriched[key]
            y = enrich_now(x, out, agency_id, self.store, self.ai)
            with self._lock:
                self._enriched[key] = y
                while len(self._enriched) > 200:
                    self._enriched.popitem(last=False)
        self._rank_locks.pop(("enrich", key), None)
        return y

    # ------------------------------------------------------------------ serializers
    def card(self, x: dict, review: dict | None = None) -> dict:
        r, est = x["record"], x.get("estimate") or {}
        expl = x.get("explanation") or {}
        label = x["eligibility"]["label"]
        short, tone = ELIG.get(label, (label, ""))
        tags = [{"text": short, "tone": tone}]
        d = r.get("days_left")
        if r.get("status") == "forecasted":
            tags.append({"text": "Forecast · not open yet", "tone": "info"})
        elif r.get("status") == "expired":
            tags.append({"text": "Closed", "tone": ""})
        elif d is not None and d <= 14:
            tags.append({"text": "Closes today" if d == 0 else "Closes tomorrow" if d == 1 else f"Closes in {d} days",
                         "tone": "hot"})
        feas = x.get("feasibility") or {}
        if feas.get("status") == "not_enough":
            tags.append({"text": "Not enough time", "tone": "hot"})
        elif feas.get("status") == "tight":
            tags.append({"text": "Tight timeline", "tone": "warn"})
        if x.get("needs_review"):
            tags.append({"text": "Needs a second look", "tone": "warn"})
        fbk = x.get("feedback")
        if fbk:
            tags.append({"text": f"Learned from your team {'+' if fbk['points'] > 0 else ''}{fbk['points']:g}",
                         "tone": "info" if fbk["points"] > 0 else "warn"})
        if review:
            tags.append({"text": review["action"], "tone": "done"})
        tgt = x["matched_target"]
        sup_id, _, sup_text = tgt["label"].partition(": ")
        return {
            "id": r["id"], "rank": x.get("rank"), "title": r["title"], "agency": r.get("agency"),
            "number": r.get("number"), "status": r.get("status"), "url": r.get("url"),
            "funding": funding_text(r), "award_ceiling": r.get("award_ceiling"), "close_date": r.get("close_date"),
            "days_left": d, "effort": est.get("level", "Unknown"), "score": round(x["score"], 1),
            "eligibility": label, "eligibility_short": short, "eligibility_tone": tone,
            "supports": {"id": sup_id if sup_text else "", "text": sup_text or tgt["label"]},
            "quote": expl.get("grant_evidence_quote", ""), "needs_review": bool(x.get("needs_review")),
            "feasibility": feas.get("status"), "tags": tags, "decision": (review or {}).get("action"),
            "feedback": x.get("feedback"), "base_score": round(x.get("base_score", x["score"]), 1),
            "excluded": x.get("excluded", []),
        }

    def detail(self, x: dict, profile: dict, review: dict | None) -> dict:
        r, e, est, expl = x["record"], x["eligibility"], x["estimate"], x["explanation"]
        b = brief.build(x, expl, profile, freshness_label(self.status())[1])
        prog = x.get("matched_program") if (x.get("program_alignment") or 0) >= 0.5 else None
        return {
            **self.card(x, review),
            "components": [{"name": k.replace("_", " ").capitalize(), "points": c["points"], "max": c["max"],
                            "why": c["why"]} for k, c in x["components"].items()],
            "explanation": {k: expl.get(k) for k in ("matched_label", "objective_citation", "objective_url",
                                                      "grant_evidence_quote", "reasons", "confidence", "source")}
                           | {"notes": expl.get("verification", {}).get("notes", [])},
            "program": ({"label": prog["label"], "url": (prog.get("citation") or {}).get("url")} if prog else None),
            "plan_text": x["matched_target"]["label"],
            "other_objectives": [{"id": t["id"], "fit": round(s, 2)} for t, s in x.get("other_targets", [])],
            "eligibility_detail": {"label": e["label"], "reasons": e["reasons"], "citations": e["citations"],
                                   "conditions": e["conditions"], "open_questions": e["open_questions"],
                                   "method": e["method"]},
            "estimate": {"level": est["level"], "summary": est["summary"], "label": est["label"],
                         "basis": est["basis"], "drivers": est["drivers"],
                         "rejected": est.get("ai_drivers_rejected", 0)},
            "feasibility_detail": x["feasibility"], "nofo": x.get("nofo") or {},
            "facts": {"Funding": brief.funding_range(r), "Deadline": b["deadline"],
                      "Eligible applicants": ", ".join(r.get("eligibility_labels") or []) or "Not specified",
                      "Cost share": {True: "Required", False: "Not required"}.get(r.get("cost_sharing"), "Not specified"),
                      "Assistance listing": ", ".join(r.get("aln") or []) or "Not specified",
                      "First seen": (r.get("first_seen") or "")[:10] or "—",
                      "Last changed": (r.get("last_modified") or "")[:10] or "—"},
            "flags": b["flags"], "gather": b["gather"], "next_action": b["next_action"],
            "brief_text": brief.to_text(b), "data_label": b["data_label"],
            "review": review,
        }

    def row(self, x: dict, review: dict | None) -> dict:
        r = x["record"]
        return {"id": r["id"], "rank": x.get("rank"), "score": round(x["score"]), "title": r["title"],
                "agency": r.get("agency"), "eligibility": ELIG.get(x["eligibility"]["label"], ("", ""))[0],
                "close_date": r.get("close_date"), "days_left": r.get("days_left"),
                "award_ceiling": r.get("award_ceiling"), "status": r.get("status"),
                "decision": (review or {}).get("action") or "None yet", "url": r.get("url"),
                "why_set_aside": " | ".join(x.get("excluded", []))}

    # ------------------------------------------------------------------ page payloads
    def meta(self) -> dict:
        level, label = freshness_label(self.status())
        s = self.status()
        return {"agencies": [{"id": a, "short": p["short_name"], "name": p["name"], "plan": p["plan"]["title"],
                              "plan_url": p["plan"]["url"]} for a, p in loader.load_all().items()],
                "data": {"level": level, "label": label, "last_success": s.get("last_success"),
                         "count": s.get("count", 0), "open": s.get("open", 0), "forecasted": s.get("forecasted", 0)},
                "ai": self.ai.available,
                "privacy": {"azure_pii": bool(config.LANGUAGE_ENDPOINT and config.LANGUAGE_KEY),
                            "banner": "Public information only. Do not enter confidential data. A privacy filter screens everything users type before any AI call, save or download."}}

    def survey_payload(self, agency_id: str) -> dict:
        p = loader.get(agency_id)
        strength, why = loader.profile_strength(p)
        goals = {}
        for o in p["objectives"]:
            goals.setdefault(o["goal_id"], {"id": o["goal_id"], "title": o["goal_title"], "objectives": []})
            goals[o["goal_id"]]["objectives"].append({"id": o["id"], "text": o["text"]})
        saved = self.saved_survey(agency_id)
        return {"saved": saved, "answers": sv.normalize(saved or {"agency_id": agency_id}),
                "goals": list(goals.values()), "strength": strength, "strength_reasons": why,
                "topics": loader.standard_topics() if strength == "weak" else [],
                "options": {"capacity": sv.CAPACITY_OPTIONS, "min_award": list(sv.MIN_AWARD_OPTIONS),
                            "cost_share": sv.COST_SHARE_OPTIONS, "prep_time": list(sv.PREP_OPTIONS)},
                "plan": {"title": p["plan"]["title"], "url": p["plan"]["url"]}}

    def save_survey(self, agency_id: str, answers: dict) -> dict:
        typed = answers.get("other_priority")
        typed = typed[:300] if isinstance(typed, str) else ""
        privacy = screen(typed, "survey other priority", self.store)  # raises PrivacyBlocked
        valid_ids = {o["id"] for o in loader.get(agency_id)["objectives"]}

        def strings(v) -> list[str]:  # anything that isn't a list of strings is ignored, never an error
            return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

        def option(k):
            v = answers.get(k)
            return v if isinstance(v, str) else None  # unknown values fall back to defaults in normalize()

        clean = {"focus_objectives": [i for i in strings(answers.get("focus_objectives")) if i in valid_ids],
                 "focus_topics": [t for t in strings(answers.get("focus_topics")) if t in loader.standard_topics()],
                 "other_priority": privacy["text"], "capacity": option("capacity"), "min_award": option("min_award"),
                 "cost_share": option("cost_share"), "prep_time": option("prep_time")}
        saved = fb.save_survey(self.store, agency_id, clean)
        self._forget("survey", agency_id)
        threading.Thread(target=self.ranked, args=(agency_id,), daemon=True).start()  # ready before the page reloads
        return {"survey": saved, "privacy": privacy}

    def reset_survey(self, agency_id: str) -> dict:
        """Clear the survey (the 'filter'): no focus picks, no other priority, default capacity/award/match/prep."""
        previous = self.saved_survey(agency_id)
        saved = fb.save_survey(self.store, agency_id, {"focus_objectives": [], "focus_topics": [], "other_priority": ""})
        self._forget("survey", agency_id)
        threading.Thread(target=self.ranked, args=(agency_id,), daemon=True).start()
        return {"survey": saved, "previous": previous,
                "message": "Survey answers cleared: no focus areas, default capacity, any award size, standard prep time."}

    def report_missed(self, agency_id: str, text: str) -> dict:
        """Stretch goal 1: staff report a grant they found somewhere else. Accepts a Grants.gov link, opportunity
        ID or opportunity number (no free text, so nothing personal can be typed here)."""
        import re as _re
        t = str(text or "").strip()[:300]
        m = _re.search(r"(?:oppId=|search-results-detail/|view-opportunity\.html\?oppId=)(\d{4,9})", t)
        key = m.group(1) if m else t
        if not _re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-]{2,40}", key):
            raise ValueError("Paste a Grants.gov link, opportunity ID (e.g. 358123) or number (e.g. EPA-R-OW-24-01).")
        out, _ = self.ranked(agency_id)
        rec = next((x["record"] for x in out["all"]
                    if x["record"]["id"] == key or (x["record"].get("number") or "").lower() == key.lower()), None)
        pos = next((i + 1 for i, x in enumerate(out["shortlist"]) if rec and x["record"]["id"] == rec["id"]), None)
        entry = {"key": key, "opp_id": rec["id"] if rec else None, "title": rec["title"] if rec else None,
                 "at": datetime.now(timezone.utc).isoformat(), "in_data": bool(rec)}
        self.store.update_json(f"feedback/missed_{agency_id}.json",
                               lambda log: [e for e in (log or []) if e.get("key") != key] + [entry], default=[])
        if not rec:
            msg = ("GrantBridge doesn't have this grant in today's data. It may be closed, not on Grants.gov, or "
                   "outside every agency's search terms; it is recorded as a true miss.")
        elif pos is None:
            msg = f"GrantBridge has this grant but set it aside ({'; '.join(next(x for x in out['all'] if x['record']['id'] == rec['id'])['excluded'])})."
        else:
            msg = f"GrantBridge already has this grant: it is #{pos} on your list."
        return {"entry": entry, "position": pos, "message": msg}

    def alerts(self, agency_id: str) -> dict:
        from alerts import deadlines
        out, reviews = self.ranked(agency_id)
        by_id = {x["record"]["id"]: x["record"] for x in out["all"]}
        items = deadlines.tracked(by_id, reviews, [x["record"]["id"] for x in out["top"]])
        return {"items": items, "soon": [a for a in items if a["days"] <= deadlines.SITE_WINDOW],
                "window": deadlines.SITE_WINDOW, "webhook_configured": bool(deadlines.webhook_url()),
                "alert_days": list(deadlines.ALERT_DAYS)}

    def alerts_calendar(self, agency_id: str) -> str:
        from alerts import deadlines
        return deadlines.ics(loader.get(agency_id)["short_name"], self.alerts(agency_id)["items"])

    def final_order(self, agency_id: str, use_feedback: bool = True) -> tuple[dict, list]:
        """The shortlist in the order the Matches page shows it (top of the list re-sorted by final scores, as in
        matches()), INCLUDING grants the team passed on, so the evaluation checks what people actually saw."""
        out, _ = self.ranked(agency_id)
        sl = out["shortlist"] if use_feedback else out["base_shortlist"]
        n = out["survey"]["top_n"]
        head = [self.light(x, out, agency_id) for x in sl[: max(n * 3, 15)]]
        head.sort(key=lambda x: (-x["score"], x["record"]["days_left"] if x["record"]["days_left"] is not None else 9999))
        return out, head + sl[len(head):]

    def matches(self, agency_id: str) -> dict:
        profile = loader.get(agency_id)
        out, reviews = self.ranked(agency_id)
        s = out["survey"]
        # pick the top N from the FINAL scores: enrichment (full NOFO, verified AI) can move a grant up or down, so
        # look a little past the cut-off and re-sort before choosing
        passed = {k for k, v in reviews.items() if v.get("action") == "Pass"}
        n = s["top_n"]
        pool = [x for x in out["shortlist"] if x["record"]["id"] not in passed][: max(n * 3, 15)]
        pool = [self.light(x, out, agency_id) for x in pool]
        pool.sort(key=lambda x: (-x["score"], x["record"]["days_left"] if x["record"]["days_left"] is not None else 9999))
        top = pool[:n]
        soon = sorted([x for x in out["shortlist"] if x["record"].get("days_left") is not None
                       and 0 <= x["record"]["days_left"] <= 30], key=lambda x: x["record"]["days_left"])[:6]
        counts = {}
        for x in out["filtered"]:
            for reason in x["excluded"]:
                k = reason.split(":")[0].split("(")[0].strip()
                counts[k] = counts.get(k, 0) + 1
        goals = {o["id"]: f"Goal {o['goal_id']}: {o['goal_title']}" for o in profile["objectives"]}
        by_goal = {}
        for x in out["shortlist"]:
            g = goals.get(x["matched_target"]["id"]) or ("Your priority" if x["matched_target"]["kind"] == "user"
                                                         else "Other")
            by_goal[g] = by_goal.get(g, 0) + 1
        return {
            "agency": {"id": agency_id, "short": profile["short_name"], "name": profile["name"],
                       "plan": profile["plan"]["title"], "plan_url": profile["plan"]["url"]},
            "has_survey": self.saved_survey(agency_id) is not None,
            "survey": {k: s[k] for k in ("capacity", "min_award", "cost_share", "prep_time", "top_n")},
            "stats": {"reviewed": len(out["all"]), "shortlist": len(out["shortlist"]),
                      "eligible": sum(1 for x in out["shortlist"] if x["eligibility"]["label"] == APPEARS),
                      "due14": sum(1 for x in out["shortlist"] if x["record"].get("days_left") is not None
                                   and x["record"]["days_left"] <= 14),
                      "set_aside": len(out["filtered"])},
            "method": out["similarity_method"], "ai": self.ai.available,
            "top": [self.card(x, reviews.get(x["record"]["id"])) for x in top],
            "due_soon": [{"id": x["record"]["id"], "title": x["record"]["title"], "days": x["record"]["days_left"],
                          "next": brief.next_action(x)} for x in soon],
            "set_aside_counts": sorted(([k, v] for k, v in counts.items()), key=lambda t: -t[1]),
            "charts": {"by_goal": sorted(([k, v] for k, v in by_goal.items()), key=lambda t: -t[1])[:8],
                       "runway": [{"id": x["record"]["id"], "title": x["record"]["title"][:90],
                                   "days": x["record"]["days_left"], "score": round(x["score"])}
                                  for x in out["shortlist"] if x["record"].get("days_left") is not None
                                  and x["record"]["days_left"] >= 0][:400]},
            "shortlist": [self.row(x, reviews.get(x["record"]["id"])) for x in out["shortlist"]],
            "set_aside": [self.row(x, None) for x in out["filtered"]],
        }

    def _find(self, agency_id: str, opp_id: str):
        out, reviews = self.ranked(agency_id)
        for x in out["all"]:
            if x["record"]["id"] == str(opp_id):
                return x, out, reviews
        raise KeyError(opp_id)

    def opportunity(self, agency_id: str, opp_id: str) -> dict:
        x, out, reviews = self._find(agency_id, opp_id)
        y = self.full(x, out, agency_id)
        return self.detail(y, loader.get(agency_id), reviews.get(str(opp_id)))

    def brief_file(self, agency_id: str, opp_id: str, notes: str, fmt: str) -> tuple[bytes | str, dict]:
        privacy = screen(notes, "brief notes", self.store)
        x, out, _ = self._find(agency_id, opp_id)
        y = self.full(x, out, agency_id)
        b = brief.build(y, y["explanation"], loader.get(agency_id), freshness_label(self.status())[1], privacy["text"])
        return (brief.to_pdf(b) if fmt == "pdf" else brief.to_text(b)), privacy

    def decide(self, agency_id: str, opp_id: str, body: dict) -> dict:
        x, out, _ = self._find(agency_id, opp_id)
        typed = {f: str(body.get(f) or "") for f in ("reason", "note", "user")}
        privacy = {f: screen(t, f"decision {f}", self.store) for f, t in typed.items()}  # raises PrivacyBlocked
        entry = fb.record(self.store, agency_id, x, str(body.get("action")), str(body.get("relevance") or ""),
                          privacy["reason"]["text"], privacy["note"]["text"], privacy["user"]["text"])
        self._forget("reviews", agency_id)
        return {"entry": entry, "privacy": {f: p for f, p in privacy.items() if p["changed"]}}

    def decisions(self, agency_id: str) -> dict:
        latest = self.reviews(agency_id)
        hist = fb.history(self.store, agency_id)
        return {"counts": {a: sum(v["action"] == a for v in latest.values()) for a in fb.ACTIONS},
                "total_actions": len(hist),
                "items": sorted(latest.values(), key=lambda v: v["at"], reverse=True)}

    def clear_decisions(self, agency_id: str) -> dict:
        n = fb.clear(self.store, agency_id)
        self._forget("reviews", agency_id)
        return {"cleared": n, "message": f"Cleared {n} decision record(s). A copy was archived for audit and can be restored."}

    def restore_decisions(self, agency_id: str) -> dict:
        n = fb.restore_last(self.store, agency_id)
        self._forget("reviews", agency_id)
        return {"restored": n, "message": f"Restored {n} decision record(s) from the last clear." if n
                else "Nothing to restore: there is no earlier clear for this agency."}

    def search(self, agency_id: str, q: str) -> dict:
        from common.text import TfIdf, sparse_cosine
        from scoring.score import opp_text

        privacy = screen(q[:300], "project search", self.store)
        out, reviews = self.ranked(agency_id)
        pool = out["shortlist"]
        if not privacy["text"].strip() or not pool:
            return {"privacy": privacy, "results": []}
        tf = TfIdf([opp_text(x["record"]) for x in pool] + [privacy["text"]])
        qv = tf.vector(privacy["text"])
        hits = sorted(((sparse_cosine(tf.vector(opp_text(x["record"])), qv), x) for x in pool), key=lambda t: -t[0])
        results = [dict(self.card(self.light(x, out, agency_id), reviews.get(x["record"]["id"])), match=round(sim, 3))
                   for sim, x in hits[:8] if sim > 0.03]
        return {"privacy": privacy, "results": results}

    def run_refresh(self) -> dict:
        from data_retrieval import refresh

        if not self._busy["refresh"].acquire(blocking=False):
            return {"ok": False, "message": "A refresh is already running."}
        wait = REFRESH_COOLDOWN - (time.time() - self._last_run.get("refresh", 0))
        if wait > 0:
            self._busy["refresh"].release()
            return {"ok": False, "message": f"Data was refreshed moments ago. Try again in {int(wait // 60) + 1} min."}
        self._last_run["refresh"] = time.time()
        try:
            s = refresh.run(self.store, self.ai, quick=True)
            self.invalidate()
            self.warm()
            return {"ok": True, "message": f"Refreshed {s['count']:,} opportunities."}
        except Exception as e:
            self.invalidate()
            self._last_run["refresh"] = time.time() - REFRESH_COOLDOWN + 120  # after a failure, allow a retry in 2 min
            why = "Grants.gov couldn't be reached" if "unreachable" in str(e) or "unavailable" in str(e) else "an error occurred"
            log.warning("manual refresh failed: %s", e)  # full detail goes to the server log, not the browser
            return {"ok": False, "message": f"Refresh failed ({why}). Still showing the last good data; try again in 2 min."}
        finally:
            self._busy["refresh"].release()

    # ---------------- evaluation: one agency at a time, in the background, with pause / resume / stop
    def eval_status(self) -> dict:
        j = getattr(self, "_eval_job", None)
        if not j:
            return {"state": "idle"}
        st = dict(j["status"])
        if st["state"] in ("running", "paused"):
            c = j["control"]
            st["state"] = "stopping" if c.stopped else "paused" if c.paused else "running"
        return st

    def evaluation(self, agency_id: str) -> dict:
        res = self.store.read_json(f"eval/latest_{agency_id}.json") or {}
        return {"result": res, "job": self.eval_status()}

    def start_evaluation(self, agency_id: str) -> dict:
        from evaluation import run_eval

        cur = self.eval_status()
        if cur["state"] in ("running", "paused", "stopping"):
            return {"error": f"An evaluation for {cur.get('agency', '').upper()} is already {cur['state']}. "
                             "Pause, resume or stop it first.", "job": cur}
        wait = EVAL_COOLDOWN - (time.time() - self._last_run.get("evaluation", 0))
        if wait > 0:
            return {"error": f"An evaluation just ran. Try again in {int(wait) + 1} s.", "job": cur}
        self._last_run["evaluation"] = time.time()
        control = run_eval.Control()
        job = {"control": control, "status": {"state": "running", "agency": agency_id, "done": 0, "total": 1,
                                              "text": "Starting", "started_at": time.time()}}
        self._eval_job = job

        def progress(done, total, text):
            job["status"].update(done=done, total=total, text=text)

        def go():
            try:
                run_eval.run(self.store, self.ai, agency=agency_id, progress=progress, control=control,
                             ranker=lambda aid, prof, items: (*self.final_order(aid, True),
                                                              self.final_order(aid, False)[1]))
                job["status"].update(state="finished", text="Finished", finished_at=time.time())
            except run_eval.Stopped:
                job["status"].update(state="stopped", text=(
                    "Stopped automatically after 10 minutes paused. Nothing was saved; the last result is kept."
                    if control.timed_out else "Stopped. Nothing was saved; the last result is kept."))
                self._last_run["evaluation"] = 0  # a stopped run can be restarted right away
            except Exception as e:  # report, never crash the app
                log.exception("evaluation failed")
                job["status"].update(state="failed", text=f"The evaluation failed: {type(e).__name__}. See the server log.")
                self._last_run["evaluation"] = 0
        threading.Thread(target=go, name="evaluation", daemon=True).start()
        return {"job": self.eval_status()}

    def control_evaluation(self, action: str) -> dict:
        j = getattr(self, "_eval_job", None)
        if not j or self.eval_status()["state"] not in ("running", "paused"):
            return {"error": "No evaluation is running.", "job": self.eval_status()}
        {"pause": j["control"].pause, "resume": j["control"].resume, "stop": j["control"].stop}[action]()
        if action == "stop":
            j["status"]["text"] = "Stopping after the current step…"
        return {"job": self.eval_status()}
