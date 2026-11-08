"""Hybrid prioritization score (/100). NOT a probability of winning.  SCORING_VERSION 2.

  Strategic alignment   50  best-matching plan objective: semantic similarity combined (noisy-OR) with that
                            objective's own keywords found in the notice; a second strong objective adds a little
  Applicant/program fit 20  eligibility label (10) + program keywords, diminishing returns (6) + usual partner (4)
  Deadline feasibility  15  graded by days left vs. the time actually needed (Q6 prep time and effort estimate)
  Resource feasibility  15  cost share vs. Q5 (5) + award vs. Q4 (5) + complexity (5)

Unknown information gets PARTIAL neutral credit (never full credit) and is named in the explanation, so a notice
with missing fields is not buried below weaker but complete ones, and a complete, well-matched notice still wins.
"""
import numpy as np

from agency_profiles import loader
from common.text import TfIdf, keyword_hits, sparse_cosine
from eligibility.classify import APPEARS, VERIFY
from time_estimate.estimate import feasibility

SCORING_VERSION = 2
EMBED_LOW, EMBED_HIGH = 0.20, 0.48   # cosine → 0..1 calibration (tune with labeled data)
TFIDF_LOW, TFIDF_HIGH = 0.02, 0.20   # below the floor is word-overlap noise, not a match
KEYWORD_WEIGHT = 0.6                  # an objective's keywords alone can carry at most 60% alignment
BREADTH_BONUS = 0.05
WORD_OVERLAP_ONLY = 0.85              # TF-IDF with none of the agency's keywords is often one shared generic word                  # a second objective that also matches well (>= 0.6) adds 5%
NOT_SELECTED_FACTOR = 0.85            # Q2 boost: unselected objectives count a bit less when the user picked some
PROGRAM_FACTOR = 0.95                 # operating programs (not plan objectives) count slightly less


def opp_text(r: dict) -> str:
    return f"{r['title']}. {r['title']}. {r.get('description', '')[:3000]}"


class Similarity:
    """Similarity of every opportunity to every match target. Uses cached Azure OpenAI embeddings when available,
    otherwise TF-IDF. The method used is reported in each result."""

    def __init__(self, records, targets, agency_id, storage=None, ai=None):
        self.targets = targets
        self.method = "tfidf"
        opp_vecs = tgt_vecs = None
        if storage is not None:
            opp_cache = storage.read_json("cache/embeddings_opps.json", default={}) or {}
            tgt_cache = storage.read_json("cache/embeddings_targets.json", default={}) or {}
            if opp_cache and tgt_cache:
                tgt_vecs = {}
                for t in targets:
                    v = (tgt_cache.get(f"{agency_id}|{t['id']}") or {}).get("v")
                    if v is None and ai is not None and ai.available:
                        try:
                            v = ai.embed([t["text"]])[0]   # user priority / topic, embedded on the fly
                        except Exception:
                            v = None
                    tgt_vecs[t["id"]] = v
                if all(v is not None for v in tgt_vecs.values()):
                    opp_vecs = {r["id"]: (opp_cache.get(r["id"]) or {}).get("v") for r in records}
        if opp_vecs and tgt_vecs and sum(v is not None for v in opp_vecs.values()) >= 0.9 * len(records):
            self.method = "embeddings"
            T = np.array([tgt_vecs[t["id"]] for t in targets], dtype=float)
            T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-9
            self.matrix = {}
            for r in records:
                v = opp_vecs.get(r["id"])
                if v is None:
                    self.matrix[r["id"]] = None
                    continue
                v = np.array(v, dtype=float)
                v /= np.linalg.norm(v) + 1e-9
                self.matrix[r["id"]] = (T @ v).tolist()
            self._fallback = None
        else:
            self._tfidf = TfIdf([opp_text(r) for r in records] + [t["text"] for t in targets])
            self._tvecs = [self._tfidf.vector(t["text"]) for t in targets]
            self.matrix = {}
            for r in records:
                ov = self._tfidf.vector(opp_text(r))
                self.matrix[r["id"]] = [sparse_cosine(ov, tv) for tv in self._tvecs]

    def scaled(self, raw: float) -> float:
        if self.method == "embeddings":
            return float(min(1.0, max(0.0, (raw - EMBED_LOW) / (EMBED_HIGH - EMBED_LOW))))
        return float(min(1.0, max(0.0, (raw - TFIDF_LOW) / (TFIDF_HIGH - TFIDF_LOW))))

    def best(self, opp_id: str) -> dict:
        """Best plan objective (or user priority/topic) and best operating program, with adjusted 0..1 scores."""
        row = self.matrix.get(opp_id)
        if row is None:
            return {"objective": (self.targets[0], 0.0, 0.0), "program": None, "ranked": []}
        any_selected = any(t["selected"] for t in self.targets)
        scored = []
        for t, raw in zip(self.targets, row):
            s = self.scaled(raw)
            if t["kind"] == "program":
                s *= PROGRAM_FACTOR
            if any_selected and not t["selected"]:
                s *= NOT_SELECTED_FACTOR
            scored.append((t, s, raw))
        scored.sort(key=lambda x: -x[1])
        objective = next((x for x in scored if x[0]["kind"] != "program"), scored[0])
        program = next((x for x in scored if x[0]["kind"] == "program"), None)
        second = next((x for x in scored if x[0]["kind"] != "program" and x is not objective), None)
        return {"objective": objective, "program": program, "second": second[1] if second else 0.0,
                "ranked": [(x[0], round(x[1], 3)) for x in scored[:5] if x[0]["kind"] != "program"]}


def keyword_evidence(target: dict, record: dict) -> tuple[float, list[str]]:
    """How many of the matched objective's own keywords appear in the notice (a title hit counts double)."""
    kws = target.get("keywords") or []
    if not kws:
        return 0.0, []
    title, body = record.get("title", ""), record.get("description", "")
    in_title = set(keyword_hits(kws, title))
    hits = list(dict.fromkeys(list(in_title) + keyword_hits(kws, body)))
    weight = sum(2 if h in in_title else 1 for h in hits)
    return min(1.0, weight / 3), hits   # 3 weighted hits (e.g. one in the title + one in the text) = full evidence


def score(record: dict, profile: dict, survey: dict, sim: Similarity, elig: dict, est: dict) -> dict:
    b = sim.best(record["id"])
    target, s_obj, raw = b["objective"]
    prog = b["program"]
    kw_ev, kw_hits = keyword_evidence(target, record)
    s_obj_c = 1 - (1 - s_obj) * (1 - KEYWORD_WEIGHT * kw_ev)        # noisy-OR: either signal helps, both are best
    agency_hits = keyword_hits(loader.all_keywords(profile), f"{record['title']} {record.get('description', '')}")
    if sim.method == "tfidf" and not kw_hits and not agency_hits:
        s_obj_c *= WORD_OVERLAP_ONLY
    s = max(s_obj_c, prog[1] if prog else 0.0)  # an operating program can carry the alignment, but the brief
    if b.get("second", 0) >= 0.6:                # always names the best plan objective
        s = min(1.0, s + BREADTH_BONUS)
    comps = {}
    # 1. Strategic alignment (50)
    has_text = bool(record.get("description") or record.get("title"))
    align = round(50 * s, 1) if has_text else 0.0
    why = f"Best plan objective: {target['label'][:110]} ({sim.method} similarity {raw:.2f}"
    why += f"; its keywords in the notice: {', '.join(kw_hits[:4])})" if kw_hits else ")"
    if prog and prog[1] > s_obj_c:
        why += f"; strongest link is the agency program '{prog[0]['label'][:70]}'"
    if b.get("second", 0) >= 0.6:
        why += "; also matches a second objective"
    comps["strategic_alignment"] = {"points": align, "max": 50, "why": why}
    # 2. Applicant/program fit (20)
    e_pts = {APPEARS: 10, VERIFY: 5 if record.get("eligibility_codes") else 3}.get(elig["label"], 0)
    hits = agency_hits
    k_pts = round(6 * (1 - 0.5 ** len(hits)), 1)   # 1 hit 3, 2 hits 4.5, 3 hits 5.3, ... never more than 6
    code, name = (record.get("agency_code") or "").upper(), (record.get("agency") or "").lower()
    funder = any(code.startswith(f.upper()) or (len(f) > 4 and f.lower() in name)
                 for f in profile.get("preferred_funders", []))
    f_pts = 4 if funder else 0
    comps["applicant_fit"] = {"points": round(e_pts + k_pts + f_pts, 1), "max": 20,
                              "why": f"Eligibility: {elig['label']} ({e_pts}); program keywords: "
                                     f"{', '.join(hits[:5]) or 'none'} ({k_pts}); usual federal partner: "
                                     f"{'yes' if funder else 'no'} ({f_pts})"}
    # 3. Deadline feasibility (15)
    d_pts, feas = deadline_points(record, survey, est)
    comps["deadline_feasibility"] = {"points": d_pts, "max": 15, "why": feas["text"]}
    # 4. Resource feasibility (15)
    cs = record.get("cost_sharing")
    if cs is False:
        c_pts, c_why = 5, "no cost share required"
    elif cs is True:
        c_pts = {"Yes": 5, "Sometimes": 3}.get(survey["cost_share"], 0)
        c_why = f"cost share required; your answer: {survey['cost_share']}"
    else:
        c_pts, c_why = 3, "cost share not stated, check the notice"
    ceiling, floor, total_f = record.get("award_ceiling"), record.get("award_floor"), record.get("total_funding")
    need = survey["min_award_value"]
    if ceiling and ceiling >= need:
        a_pts, a_why = 5, f"award up to ${ceiling:,.0f}"
    elif ceiling:
        a_pts, a_why = 0, f"award ${ceiling:,.0f} below your minimum"
    elif (floor and floor >= need) or (total_f and total_f >= max(need, 1)):
        a_pts, a_why = 4, "award size not listed; program funding " + (f"${total_f:,.0f}" if total_f else f"from ${floor:,.0f}")
    else:
        a_pts, a_why = (3 if need == 0 else 2), "award size not listed, check the notice"
    x_pts = {"Low": 5, "Medium": 4, "High": 2}.get(est["level"], 3)
    comps["resource_feasibility"] = {"points": c_pts + a_pts + x_pts, "max": 15,
                                     "why": f"{c_why} ({c_pts}); {a_why} ({a_pts}); complexity {est['level']} ({x_pts})"}
    total = round(sum(c["points"] for c in comps.values()), 1)

    if s >= 0.7 and elig["label"] == APPEARS and record.get("description") and (kw_hits or s_obj >= 0.8):
        conf = "high"
    elif s < 0.45 or elig["label"] != APPEARS or not record.get("description"):
        conf = "low"
    else:
        conf = "medium"
    return {"score": total, "components": comps, "alignment": round(s, 3), "matched_target": target,
            "matched_program": prog[0] if prog else None, "program_alignment": round(prog[1], 3) if prog else None,
            "other_targets": b["ranked"][1:], "keyword_hits": hits, "objective_keyword_hits": kw_hits, "feasibility": feas, "rule_confidence": conf,
            "similarity_method": sim.method}


def deadline_points(record: dict, survey: dict, est: dict) -> tuple[float, dict]:
    """Deadline feasibility (15 points), graded rather than all-or-nothing. Depends on today's date, so it is
    recomputed whenever the day changes."""
    feas = feasibility(record.get("days_left"), survey["prep_days"], est)
    if record.get("status") == "expired":
        return 0, {"status": "expired", "icon": "⛔", "text": "Expired", "need_days": None}
    st, need, left = feas["status"], feas.get("need_days") or 0, record.get("days_left")
    if st == "feasible":
        return (15 if est.get("weeks") else 13), feas
    if st == "tight":            # 60%..100% of the time needed → 7..12 points
        ratio = left / need if need else 0.6
        return round(7 + 5 * (ratio - 0.6) / 0.4, 1), feas
    if st == "not_enough":       # a very short window is still worth a look if it is over a third of the need
        return (3 if need and left / need >= 0.35 else 0), feas
    # no close date: often rolling or a forecast; partial credit, and the text says to check the notice
    return 8, feas
