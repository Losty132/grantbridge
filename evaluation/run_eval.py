"""Reproducible evaluation. Run:  python -m evaluation.run_eval            (every agency)
                                python -m evaluation.run_eval dot        (one agency)
Writes evaluation/results/eval_<timestamp>.json and .md, and eval/latest[_<agency>].json in storage for the app.

What it answers, in plain language (the web page shows exactly these sentences):
  1. Are the top picks good?        Of the top 5 the team has judged, how many were Pursue / Maybe.
  2. Are good grants ranked higher?  For every (good, bad) pair the team judged, is the good one ranked higher?
  3. Do the safety rules hold?       Fixed tests that must never fail.
plus a short checklist about the current top 5 and a list of specific grants to look at.

Answer key: the team's own Pursue / Maybe / Pass decisions (plus evaluation/labels.csv, which overrides them).
A Pass counts as "bad match" only when it says so (relevance mark 'irrelevant', or a reason that isn't about
capacity / timing / money). A Pass for "no capacity this month" says nothing about the ranking, so it is left out.
Grants that have since closed or been filtered out by the survey are left out too. Nothing is filled in or estimated:
below the minimum number of judgments a question is answered "not enough decisions yet".
"""
import csv
import json
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from agency_profiles import loader
from common.ai import AI
from common.storage import Storage
from data_retrieval.normalize import refresh_days_left, today
from data_retrieval.store import load_dataset
from eligibility.classify import APPEARS, NOT_ELIGIBLE, PARTNER
from evaluation.pii_samples import INTERNAL_SAMPLES, PLACES_NOT_NAMES, SAMPLES
from feedback import learn
from feedback import store as fb
from privacy.filter import scan
from scoring.rank import rank
from summarization.explain import ai_explanation
from time_estimate.estimate import estimate

HERE = Path(__file__).resolve().parent
MIN_TOP5 = 3          # judged grants needed among the top 5 before the "top picks" answer is shown
MIN_PAIRS = 3         # (good, bad) pairs needed before the "ranked higher" answer is shown
PAUSE_LIMIT = 600     # a run left paused for 10 minutes stops itself so it never blocks everyone else
MINUTES_PER_GRANT = 3  # assumed time to skim one notice by hand (only for the time-saved estimate; shown on the page)


def load_labels(path: Path = HERE / "labels.csv") -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if (r.get("relevant") or "").strip() in ("0", "1")
                or (r.get("expected_eligibility") or "").strip()]


def _test(name, passed, detail, what):
    return {"test": name, "result": "PASS" if passed is True else "FAIL" if passed is False else "SKIPPED",
            "detail": detail, "what": what}


class Stopped(Exception):
    """Raised when the person presses Stop (or a pause runs too long); nothing is saved."""


class Control:
    """Pause / resume / stop for a running evaluation, checked between steps."""

    def __init__(self, pause_limit: float = PAUSE_LIMIT):
        self._go = threading.Event()
        self._go.set()
        self.stopped = False
        self.timed_out = False
        self.paused_at = None
        self.pause_limit = pause_limit

    def pause(self):
        self.paused_at = time.monotonic()
        self._go.clear()

    def resume(self):
        self.paused_at = None
        self._go.set()

    def stop(self):
        self.stopped = True
        self._go.set()

    @property
    def paused(self) -> bool:
        return not self._go.is_set() and not self.stopped

    def checkpoint(self):
        while not self._go.wait(1.0):
            if self.paused_at is not None and time.monotonic() - self.paused_at > self.pause_limit:
                self.timed_out = True
                self.stop()
        if self.stopped:
            raise Stopped()


def team_labels(storage, aid: str, labels: list[dict]) -> tuple[dict, int]:
    """{opp_id: 1 good / 0 bad} from the team's decisions (same rules as feedback/learn.py) and labels.csv, plus how
    many Passes were left out because their reason was about capacity / timing / money rather than fit."""
    gold, skipped = {}, 0
    for oid, v in fb.reviews(storage, aid).items():
        lab = learn.label_of(v)
        if lab is None:
            skipped += v.get("action") == "Pass"
        else:
            gold[oid] = lab
    for r in labels:
        if r["agency"].strip().lower() == aid and r.get("relevant", "").strip() in ("0", "1"):
            gold[r["opportunity_id"].strip()] = int(r["relevant"])
    return gold, skipped


def _rank_default(storage, ai):
    def ranker(aid, prof, items):
        survey = storage.read_json(f"surveys/{aid}.json") or {"agency_id": aid}
        out = rank(items, prof, survey, storage, ai)
        return out, out["shortlist"], out["shortlist"]
    return ranker


def run(storage=None, ai=None, labels_path: Path | None = None, agency: str | None = None,
        progress=None, control: Control | None = None, ranker=None) -> dict:
    """agency: evaluate only this agency (the one picked in the header); None = every agency.
    ranker(aid, profile, items) -> (ranked output, the list as the Matches page shows it (with feedback learning),
    the same list ranked on the plan alone (no feedback)). The web app passes its own so the evaluation checks exactly
    the lists people see; the default re-ranks with the rules. Accuracy is graded on the plan-only order (so the team's
    own decisions can't grade themselves); the learning effect compares the two.
    progress(done, total, text) reports steps; control pauses or stops the run."""
    storage = storage or Storage()
    ai = ai or AI()
    control = control or Control()
    ranker = ranker or _rank_default(storage, ai)
    items, status = load_dataset(storage)
    labels = load_labels(labels_path or HERE / "labels.csv")
    all_profiles = loader.load_all()
    profiles = {agency: all_profiles[agency]} if agency in all_profiles else all_profiles
    metrics, tests, problems = {}, [], []
    state = {"done": 0, "total": len(profiles) + 5}

    def step(text):
        control.checkpoint()
        state["done"] += 1
        if progress:
            progress(min(state["done"], state["total"]), state["total"], text)

    ranked, order, learned = {}, {}, {}
    for aid, prof in profiles.items():
        step(f"Ranking grants for {prof.get('short_name') or aid.upper()}")
        ranked[aid], learned[aid], order[aid] = ranker(aid, prof, items) if items else (None, [], [])
    ai_targets = {aid: [x for x in order[aid][:5]] for aid in profiles} if ai.available else {}
    state["total"] += sum(len(v) for v in ai_targets.values())   # the real number of AI checks, not a guess

    step("Comparing the ranking with your team's decisions")
    agencies, tot = [], {"good5": 0, "judged5": 0, "pairs": 0, "right": 0, "judged": 0, "skipped": 0,
                         "good": 0, "found": 0, "pos_sum": 0, "l_good5": 0, "l_judged5": 0, "l_right": 0}
    score_by = {"Pursue": [], "Maybe": [], "Pass": []}   # plan-based score at the time of each decision group
    for aid, prof in profiles.items():
        out, seen = ranked[aid], order[aid]
        if not out:
            metrics[aid] = "not computed: no data"
            continue
        gold, skipped = team_labels(storage, aid, labels)
        position = {x["record"]["id"]: i for i, x in enumerate(seen)}       # only grants that can still be shown
        by_id = {x["record"]["id"]: x for x in seen}
        usable = {i: v for i, v in gold.items() if i in position}            # closed / filtered-out grants left out
        if not usable:
            metrics[aid] = "not computed: no team decisions or labels for this agency"
            agencies.append({"agency": aid, "name": prof.get("short_name") or aid.upper(), "judged": 0,
                             "skipped_passes": skipped, "left_out": len(gold)})
            tot["skipped"] += skipped
            continue
        top5 = [x["record"]["id"] for x in seen[:5]]
        judged5 = [i for i in top5 if i in usable]
        good5 = sum(usable[i] for i in judged5)
        goods = [i for i, v in usable.items() if v == 1]
        bads = [i for i, v in usable.items() if v == 0]
        pairs = [(g, b) for g in goods for b in bads]
        right = sum(position[g] < position[b] for g, b in pairs)
        found = sum(position[g] < 25 for g in goods)
        # learning effect: the same two measures on the list WITH the feedback nudges (a grant is never nudged by
        # its own decision, so this is a fair before / after)
        lpos = {x["record"]["id"]: i for i, x in enumerate(learned[aid])}
        l5 = [x["record"]["id"] for x in learned[aid][:5] if x["record"]["id"] in usable]
        tot["l_good5"] += sum(usable[i] for i in l5)
        tot["l_judged5"] += len(l5)
        tot["l_right"] += sum(lpos.get(g, 9e9) < lpos.get(b, 9e9) for g, b in pairs)
        tot["pos_sum"] += sum(position[g] + 1 for g in goods)
        for oid, v in fb.reviews(storage, aid).items():
            if oid in by_id and v.get("action") in score_by and (v.get("action") != "Pass" or usable.get(oid) == 0):
                score_by[v["action"]].append(by_id[oid].get("base_score", by_id[oid]["score"]))
        elig_rows = [r for r in labels if r["agency"].strip().lower() == aid and r.get("expected_eligibility", "").strip()
                     and r["opportunity_id"].strip() in by_id]
        elig_ok = sum(by_id[r["opportunity_id"].strip()]["eligibility"]["label"].lower()
                      == r["expected_eligibility"].strip().lower() for r in elig_rows)
        m = {"agency": aid, "name": prof.get("short_name") or aid.upper(), "judged": len(usable),
             "skipped_passes": skipped, "left_out": len(gold) - len(usable),
             "top5_judged": len(judged5), "top5_good": good5,
             "top5_rate": round(good5 / len(judged5), 3) if len(judged5) >= MIN_TOP5 else None,
             "pairs": len(pairs), "pairs_right": right,
             "order_rate": round(right / len(pairs), 3) if len(pairs) >= MIN_PAIRS else None,
             "good": len(goods), "good_in_top25": found,
             "eligibility_rows": len(elig_rows),
             "eligibility_rate": round(elig_ok / len(elig_rows), 3) if elig_rows else None}
        metrics[aid] = m
        agencies.append(m)
        for k, v in (("good5", good5), ("judged5", len(judged5)), ("pairs", len(pairs)), ("right", right),
                     ("judged", len(usable)), ("skipped", skipped), ("good", len(goods)), ("found", found)):
            tot[k] += v
        # specific grants to look at, with titles and links
        for i in judged5:
            if usable[i] == 0:
                r = by_id[i]["record"]
                problems.append({"kind": "top_pick_passed", "agency": aid, "opp_id": i, "title": r["title"],
                                 "url": r.get("url"), "rank": position[i] + 1,
                                 "text": f"Ranked #{position[i] + 1}, but your team marked it as not a fit.",
                                 "advice": "Open it and check which plan objective it matched; if the match is wrong, "
                                           "remove or sharpen that objective's keywords."})
        for g in goods:
            if position[g] >= 25:
                r = by_id[g]["record"]
                problems.append({"kind": "good_ranked_low", "agency": aid, "opp_id": g, "title": r["title"],
                                 "url": r.get("url"), "rank": position[g] + 1,
                                 "text": f"Your team marked it as a good fit, but the app ranks it #{position[g] + 1}.",
                                 "advice": "Tick the plan objective it serves in the survey, or add its key terms to "
                                           "that objective's keywords, so similar grants rank higher."})

    def answer(rate, enough, good_text, need_text):
        if rate is None:
            return {"status": "wait", "value": None, "text": need_text}
        return {"status": "good" if rate >= 0.8 else "check" if rate >= 0.6 else "bad", "value": rate,
                "text": good_text}

    rate5 = round(tot["good5"] / tot["judged5"], 3) if tot["judged5"] >= MIN_TOP5 else None
    rate_order = round(tot["right"] / tot["pairs"], 3) if tot["pairs"] >= MIN_PAIRS else None
    accuracy = {
        "top_picks": answer(rate5, tot["judged5"],
                            f"{tot['good5']} of the {tot['judged5']} top-5 picks your team has judged were worth "
                            f"pursuing.",
                            f"Not enough decisions yet: {tot['judged5']} of the current top 5 judged, need {MIN_TOP5}. "
                            f"Mark Pursue, Maybe or Pass on the top matches."),
        "ordering": answer(rate_order, tot["pairs"],
                           f"When comparing a grant your team liked with one it passed on, the liked one was ranked "
                           f"higher {tot['right']} out of {tot['pairs']} times.",
                           f"Not enough decisions yet: this needs at least one Pursue/Maybe and a few Passes for "
                           f"grants that don't fit ({tot['pairs']} comparisons so far, need {MIN_PAIRS})."),
        "judged": tot["judged"], "skipped_passes": tot["skipped"], "good": tot["good"], "good_in_top25": tot["found"],
        "agencies": agencies,
    }

    # ---------------- scorecard: what a reviewer or a judge asks
    card = {}
    avg = {k: round(sum(v) / len(v), 1) for k, v in score_by.items() if v}
    if "Pursue" in avg and "Pass" in avg:
        gap = round(avg["Pursue"] - avg["Pass"], 1)
        card["score_by_decision"] = {"status": "good" if gap >= 15 else "check" if gap >= 5 else "bad",
                                     "value": f"{gap:+g} pts",
                                     "text": f"Grants your team pursued average {avg['Pursue']:g} / 100"
                                             + (f", Maybes {avg['Maybe']:g}" if "Maybe" in avg else "")
                                             + f", poor-fit Passes {avg['Pass']:g}. A clear gap means a higher score "
                                               f"really does mean a better grant."}
    else:
        card["score_by_decision"] = {"status": "wait", "value": "",
                                     "text": "Needs at least one Pursue and one Pass for a poor fit to compare scores."}
    card["top5"] = dict(accuracy["top_picks"], value=None if rate5 is None else f"{round(rate5 * 100)}%")
    if tot["good"]:
        avg_pos = round(tot["pos_sum"] / tot["good"], 1)
        card["position"] = {"status": "good" if avg_pos <= 5 else "check" if avg_pos <= 15 else "bad",
                            "value": f"#{avg_pos:g}",
                            "text": f"Grants your team marked Pursue or Maybe sit at #{avg_pos:g} on the list on "
                                    f"average (ranked on the plan alone, before any learning from feedback)."}
    else:
        card["position"] = {"status": "wait", "value": "", "text": "Needs at least one Pursue or Maybe."}
    card["ordering"] = dict(accuracy["ordering"], value=None if rate_order is None else f"{round(rate_order * 100)}%")
    learning = None
    if tot["judged5"] >= MIN_TOP5 or tot["pairs"] >= MIN_PAIRS:
        before = {"top5": rate5, "order": rate_order}
        after = {"top5": round(tot["l_good5"] / tot["l_judged5"], 3) if tot["l_judged5"] >= MIN_TOP5 else None,
                 "order": round(tot["l_right"] / tot["pairs"], 3) if tot["pairs"] >= MIN_PAIRS else None}
        nudged = sum((ranked[a] or {}).get("feedback_nudged", 0) for a in profiles)
        paused = any((ranked[a] or {}).get("feedback_paused") for a in profiles)
        if paused:   # the app switched learning off for this agency, so "after" = what people see = the plan order
            after = dict(before)
        learning = {"before": before, "after": after, "nudged": nudged, "paused": paused}

    # ---------------- reach (stretch goal 1): what manual monitoring would likely miss
    reach = None
    for aid, prof in profiles.items():
        out = ranked[aid]
        if not out:
            continue
        top25 = [x for x in order[aid][:25]]
        usual = [f.lower() for f in prof.get("preferred_funders", [])]

        def usual_funder(r):
            code, name = (r.get("agency_code") or "").lower(), (r.get("agency") or "").lower()
            return any(code.startswith(f) or (len(f) > 4 and f in name) for f in usual)

        def own_search(r):
            return any(t.startswith("kw:") and aid in t[3:].split(",") for t in r.get("found_by") or [])
        outside = [x for x in top25 if not usual_funder(x["record"])]
        not_own = [x for x in top25 if not own_search(x["record"])]
        # likely missed = BOTH from a funder outside the usual partners AND not found by the agency's own keywords
        # (someone watching either their usual funders or their own search words would have caught the rest)
        missed = [x for x in top25 if not usual_funder(x["record"]) and not own_search(x["record"])]
        reported = storage.read_json(f"feedback/missed_{aid}.json", default=[]) or []
        pos = {x["record"]["id"]: i for i, x in enumerate(order[aid])}
        rep = [dict(m, position=(pos[m["opp_id"]] + 1) if m.get("opp_id") in pos else None) for m in reported]
        caught = [m for m in rep if m["position"] is not None and m["position"] <= 25]
        reach = {"reviewed": len(out["all"]), "possible": len(out["shortlist"]), "set_aside": len(out["filtered"]),
                 "recommended": out["survey"]["top_n"], "top": len(top25),
                 "outside_usual": len(outside), "not_own_search": len(not_own), "likely_missed": len(missed),
                 "funders": sorted({x["record"].get("agency") or "" for x in outside if x["record"].get("agency")})[:6],
                 "reported_missed": rep, "reported_caught": len(caught),
                 "hours_saved": round(len(out["all"]) * MINUTES_PER_GRANT / 60, 1),
                 "minutes_per_grant": MINUTES_PER_GRANT}
        card["reach"] = {"status": "good" if missed else "check", "value": f"{len(missed)} of {len(top25)}",
                         "text": f"{len(missed)} of your top {len(top25)} grants would likely be missed by manual "
                                 f"monitoring: they come from federal agencies outside your usual partners AND were "
                                 f"found only by searches beyond your agency's own keywords."}
        card["screening"] = {"status": "good", "value": f"~{reach['hours_saved']:g} h",
                             "text": f"{len(out['all']):,} grants reviewed automatically → {len(out['shortlist']):,} "
                                     f"possible → top {out['survey']['top_n']} recommended; {len(out['filtered']):,} "
                                     f"set aside, each with a reason. Estimated reading time saved: about "
                                     f"{reach['hours_saved']:g} hours (assuming {MINUTES_PER_GRANT} minutes to skim "
                                     f"each notice by hand)."}
        break   # the page evaluates one agency; a whole-state run reports reach for the first agency only

    # ---------------- privacy filter in real use (counts only, never text)
    plog = storage.read_json("privacy/log.json", default=[]) or []
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    week = [e for e in plog if (e.get("at") or "") >= since and not str(e.get("purpose", "")).startswith("eval")]
    kinds = {}
    for e in week:
        for k, n in (e.get("redactions") or {}).items():
            kinds[k] = kinds.get(k, 0) + n
    blocked = sum(bool(e.get("blocked")) for e in week)
    card["privacy"] = {"status": "good", "value": f"{sum(kinds.values()) + blocked}",
                       "text": ("Last 7 days: " + ", ".join(f"{n} {k.lower()}{'s' if n != 1 else ''} removed"
                                                            for k, n in sorted(kinds.items()))
                                + (f"; {blocked} internal note{'s' if blocked != 1 else ''} blocked" if blocked else "")
                                + ". Only counts are kept, never the text.") if (kinds or blocked) else
                               "Last 7 days: nothing personal or internal was typed, so nothing needed removing."}

    # ---------------- the current top 5, checked without any labels
    tops = [x for aid in profiles for x in order[aid][:5]]
    checklist = []
    if tops:
        n = len(tops)

        def item(k, ok_at, text_ok, text_low):
            status = "good" if k / n >= ok_at else "check"
            return {"status": status, "count": k, "of": n, "text": (text_ok if status == "good" else text_low).format(k=k, n=n)}
        checklist = [
            item(sum(x["eligibility"]["label"] == APPEARS for x in tops), 0.6,
                 "{k} of {n} can be applied for directly by the state.",
                 "Only {k} of {n} can clearly be applied for directly; open the others and check who may apply."),
            item(sum(bool(x.get("objective_keyword_hits")) for x in tops), 0.6,
                 "{k} of {n} use the same key terms as your strategic plan.",
                 "Only {k} of {n} use your plan's key terms; the rest matched on general wording, so check the fit."),
            item(sum(x["feasibility"]["status"] == "feasible" for x in tops), 0.6,
                 "{k} of {n} leave enough time to apply, given the prep time in your survey.",
                 "Only {k} of {n} leave enough time to apply; look at the deadlines first."),
            item(sum(x["estimate"]["level"] != "Unknown" for x in tops), 0.6,
                 "{k} of {n} say enough to estimate the work needed to apply.",
                 "{k} of {n} say enough to estimate the work; for the rest, open the full notice to judge effort."),
        ]

    # ---------------- safety tests
    step("Checking expired grants and decoys")
    leaked = [x["record"]["id"] for aid in profiles for x in order[aid] if x["record"]["status"] == "expired"]
    synthetic = refresh_days_left([{"id": "TEST-EXPIRED", "title": "Test record", "description": "", "status": "open",
                                    "close_date": (today() - timedelta(days=1)).isoformat(), "eligibility_codes": ["00"],
                                    "eligibility_labels": ["State governments"], "url": "", "agency": "",
                                    "found_by": []}])[0]
    syn_out = rank([synthetic], all_profiles["deq"], {"agency_id": "deq"})
    tests.append(_test("Expired grants are never recommended", not leaked and not syn_out["shortlist"],
                       f"{len(leaked)} expired grants in the list; test grant that closed yesterday was set aside: "
                       f"{'yes' if not syn_out['shortlist'] else 'NO'}",
                       "A grant whose deadline has passed must never appear as something to apply for."))
    decoy = refresh_days_left([{"id": "TEST-DECOY", "title": "[TEST ONLY] University water quality research training",
                                "description": "Supports universities to protect drinking water and reduce PFAS "
                                               "pollution in public water systems. Only institutions of higher "
                                               "education may apply.",
                                "status": "open", "close_date": (today() + timedelta(days=60)).isoformat(),
                                "eligibility_codes": ["20"], "eligibility_labels": ["Private institutions of higher education"],
                                "url": "", "agency": "", "found_by": []}])[0]
    dx = rank([decoy], all_profiles["deq"], {"agency_id": "deq"})["all"][0]
    tests.append(_test("Look-alike grants the state can't apply for are set aside",
                       bool(dx["excluded"]) and dx["eligibility"]["label"] in (PARTNER, NOT_ELIGIBLE),
                       f"test grant (perfect topic, universities only) was labelled '{dx['eligibility']['label']}' "
                       f"and {'set aside' if dx['excluded'] else 'NOT set aside'}",
                       "A grant that sounds perfect but only universities can apply for must be set aside."))
    live = [x for aid in profiles if ranked[aid] for x in ranked[aid]["all"]
            if x["alignment"] >= 0.7 and x["eligibility"]["label"] in (PARTNER, NOT_ELIGIBLE)]
    tests.append(_test("Real look-alike grants are kept off the list", all(x["excluded"] for x in live),
                       f"{len(live)} found in today's data; {sum(bool(x['excluded']) for x in live)} set aside",
                       "In today's data, grants that match the plan well but the state can't apply for must all be "
                       "set aside."))

    if ai_targets:
        checked = verified = handled = 0
        for aid, xs in ai_targets.items():
            ids = {t["id"] for t in ranked[aid]["targets"]}
            for x in xs:
                step(f"Checking the AI explanation for “{x['record']['title'][:50]}”")
                e = ai_explanation(ai, storage, profiles[aid], ranked[aid]["targets"], x)
                if not e.get("source", "").startswith("Azure"):
                    continue
                checked += 1
                v = e["verification"]
                ok = v["quote_verified"] and v["objective_valid"]
                verified += ok
                # the safety rule: what is SHOWN must be checkable. A failed AI answer is shown only as the
                # rule-based replacement (real objective, verified sentence) and flagged low confidence.
                handled += ok or (e["matched_objective"] in ids and e["confidence"] == "low")
                if not ok:
                    r = x["record"]
                    problems.append({"kind": "ai_caught", "agency": aid, "opp_id": r["id"], "title": r["title"],
                                     "url": r.get("url"), "text": "The AI's explanation didn't check out against the "
                                     "grant text, so the app showed the rule-based explanation instead (marked "
                                     "“Needs a second look”).", "advice": "Nothing to fix; this is the safety check "
                                     "working. Read the grant yourself before deciding."})
        tests.append(_test("Unverified AI explanations are never shown", checked > 0 and handled == checked,
                           f"{checked} AI explanations checked: {verified} verified as written, "
                           f"{checked - verified} caught and replaced",
                           "Every AI-written reason must quote the grant exactly and name a real plan objective. "
                           "Anything that can't be verified is replaced by the rule-based explanation and flagged."))
        if checked:
            rate = verified / checked
            card["ai"] = {"status": "good" if rate >= 0.9 else "check" if rate >= 0.7 else "bad",
                          "value": f"{round(rate * 100)}%",
                          "text": f"{verified} of {checked} AI explanations were verified word for word against the "
                                  f"grant and your plan. The other {checked - verified} were caught and replaced "
                                  f"before anyone saw them."}
    else:
        tests.append(_test("Unverified AI explanations are never shown", None, "AI is turned off, so there was "
                           "nothing to check", "Every AI-written reason must quote the grant exactly and name a real "
                           "plan objective."))
        card["ai"] = {"status": "wait", "value": "", "text": "AI explanations are turned off; explanations come "
                                                             "from the rules only."}

    step("Checking effort estimates")
    est = estimate({"description": "This program supports community projects.", "eligibility_text": ""})
    tests.append(_test("Effort is 'Unknown' rather than guessed", est["level"] == "Unknown",
                       f"a notice with no effort clues was labelled '{est['level']}'",
                       "When a notice gives no clues about effort, the app must say 'Unknown' instead of guessing "
                       "'Low'."))

    step("Checking the privacy filter")
    caught = sum(all(s not in scan(t).text for s in secrets) for t, secrets, _ in SAMPLES)
    kinds_missed = sorted({k for t, secrets, k in SAMPLES if any(s in scan(t).text for s in secrets)})
    kept = sum(scan(t).text == t for t in PLACES_NOT_NAMES)
    n_pii = len(SAMPLES)
    tests.append(_test("Personal details are removed from what people type",
                       caught == n_pii and kept == len(PLACES_NOT_NAMES),
                       f"{caught} of {n_pii} test phrases cleaned; {kept} of {len(PLACES_NOT_NAMES)} place and program "
                       f"names correctly left alone" + (f"; missed: {', '.join(kinds_missed)}" if kinds_missed else ""),
                       "Names, emails, phone numbers and similar details must be removed before anything is saved or "
                       "sent to AI, without mangling place names like 'Jordan Lake'."))
    blocked_ok = all(scan(t).blocked == exp for t, exp in INTERNAL_SAMPLES)
    tests.append(_test("Internal information is blocked", blocked_ok,
                       f"{len(INTERNAL_SAMPLES)} test phrases checked",
                       "Text marked internal, confidential or draft budget must be blocked from being saved or sent."))

    step("Saving the results")
    passed = sum(t["result"] == "PASS" for t in tests)
    failed = sum(t["result"] == "FAIL" for t in tests)
    safety = {"status": "good" if not failed else "bad", "passed": passed, "failed": failed,
              "skipped": len(tests) - passed - failed,
              "text": (f"All {passed} safety checks passed." if not failed else
                       f"{failed} of {passed + failed} safety checks failed; see the list below.")
              + (" 1 check was skipped (AI is off)." if len(tests) - passed - failed == 1 else "")}

    run_at = datetime.now(timezone.utc).isoformat()
    try:
        last = datetime.fromisoformat(status["last_success"]).astimezone(ZoneInfo("America/New_York"))
        last = last.strftime("%b %d, %Y %I:%M %p %Z")
    except (KeyError, TypeError, ValueError):
        last = "never"
    mode = {"live": "Live Grants.gov data", "cached": "Saved copy of Grants.gov data", "snapshot": "Sample data"}.get(
        status.get("mode"), "No data")
    result = {"version": 4, "run_at": run_at, "data": f"{mode}, last updated {last}", "records": len(items),
              "agency": agency, "agencies": len(profiles), "labels_rows": len(labels),
              "accuracy": accuracy, "safety": safety, "checklist": checklist, "problems": problems,
              "scorecard": card, "reach": reach, "learning": learning,
              "tests": tests, "metrics": metrics,
              "failures": [f"{p['title']}: {p['text']}" for p in problems]}
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = run_at[:19].replace(":", "") + (f"_{agency}" if agency else "")
    (out_dir / f"eval_{stamp}.json").write_text(json.dumps(result, indent=2, default=str))
    md = [f"# Evaluation run {run_at}" + (f" ({agency})" if agency else ""), f"Data: {result['data']}.", "",
          "## Answers", f"- Top picks: {accuracy['top_picks']['text']}", f"- Ranking order: {accuracy['ordering']['text']}",
          f"- Safety: {safety['text']}", "", "## Top 5 checklist"] + [f"- {c['text']}" for c in checklist] + \
         ["", "## Safety tests", "", "| Test | Result | Detail |", "|---|---|---|"] + \
         [f"| {t['test']} | {t['result']} | {t['detail']} |" for t in tests] + \
         ["", "## Grants to look at"] + [f"- {p['title']}: {p['text']}" for p in problems or [{"title": "(none)", "text": ""}]]
    (out_dir / f"eval_{stamp}.md").write_text("\n".join(md))
    storage.write_json(f"eval/latest_{agency}.json" if agency else "eval/latest.json", result)
    if progress:
        progress(state["total"], state["total"], "Done")
    return result


def main():
    r = run(agency=sys.argv[1] if len(sys.argv) > 1 else None)
    a = r["accuracy"]
    print("Top picks:", a["top_picks"]["text"])
    print("Ordering: ", a["ordering"]["text"])
    print("Safety:   ", r["safety"]["text"])
    for c in r["checklist"]:
        print(" -", c["text"])
    for t in r["tests"]:
        print(f"[{t['result']}] {t['test']}: {t['detail']}")
    print(f"{len(r['problems'])} grant(s) to look at. Full report in evaluation/results/.")


if __name__ == "__main__":
    main()
