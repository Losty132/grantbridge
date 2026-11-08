"""Run the full decision pipeline for one agency + survey: eligibility → time estimate → hard filters → score → rank."""
from agency_profiles import loader
from eligibility.classify import classify
from scoring import filters
from scoring.score import Similarity, score
from scoring.survey import normalize
from time_estimate.estimate import estimate, find_drivers, merge_ai_drivers


def urgency(days_left) -> str | None:
    if days_left is None or days_left < 0:
        return None
    if days_left <= 7:
        return "≤7 days"
    if days_left <= 14:
        return "≤14 days"
    if days_left <= 30:
        return "≤30 days"
    return None


def evaluate_record(record: dict, profile: dict, survey: dict, sim: Similarity, nofo_text: str = "",
                    ai_drivers: list | None = None) -> dict:
    elig = classify(record, nofo_text, profile.get("eligible_applicant_codes"))
    drivers = find_drivers(record, nofo_text)
    rejected = 0
    if ai_drivers:
        source = " ".join([record.get("description", ""), record.get("eligibility_text", ""), nofo_text,
                           " ".join(e["text"] for e in record.get("nofo_excerpts") or [])])
        drivers, rejected = merge_ai_drivers(drivers, ai_drivers, source)
    est = estimate(record, nofo_text, drivers)
    est["ai_drivers_rejected"] = rejected
    excluded, flags = filters.apply(record, survey, elig)
    sc = score(record, profile, survey, sim, elig, est)
    return {"record": record, "eligibility": elig, "estimate": est, "excluded": excluded, "flags": flags,
            "urgency": urgency(record.get("days_left")), **sc}


def rank(records: list[dict], profile: dict, survey: dict | None, storage=None, ai=None,
         reviews: dict | None = None) -> dict:
    survey = normalize(survey)
    targets = loader.match_targets(profile, survey)
    sim = Similarity(records, targets, profile["agency_id"], storage, ai)
    results = [evaluate_record(r, profile, survey, sim) for r in records]
    key = lambda x: (-x["score"], x["record"]["days_left"] if x["record"]["days_left"] is not None else 9999)
    shortlist = sorted([x for x in results if not x["excluded"]], key=key)
    filtered = sorted([x for x in results if x["excluded"]], key=key)
    dismissed = {oid for oid, rv in (reviews or {}).items() if rv.get("action") == "Pass"}
    top = [x for x in shortlist if x["record"]["id"] not in dismissed][: survey["top_n"]]
    for i, x in enumerate(shortlist, 1):
        x["rank"] = i
    return {"survey": survey, "targets": targets, "similarity_method": sim.method, "sim": sim,
            "top": top, "shortlist": shortlist, "filtered": filtered, "all": results}
