"""Full enrichment of one ranked result (NOFO PDF + verified explanation + AI-verified effort drivers),
and the overnight precompute that does this ahead of time so the app only reads results."""
import os
import hashlib
import json
import logging
import time

from agency_profiles import loader
from common import config
from data_retrieval.nofo import get_nofo_text
from scoring.rank import evaluate_record, rank
from scoring.survey import normalize
from summarization.explain import ai_explanation, rule_explanation

log = logging.getLogger(__name__)
PRECOMPUTE_TOP = int(os.getenv("PRECOMPUTE_TOP", "5"))   # per agency = the default Top 5; 33 x 5 = 165 grants prepared


def survey_key(survey: dict) -> str:
    s = normalize(survey)
    keep = {k: s[k] for k in ("focus_objectives", "focus_topics", "other_priority", "capacity", "min_award",
                              "cost_share", "prep_time")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:12]


def enrich_now(result: dict, out: dict, agency_id: str, store, ai_client) -> dict:
    profile = loader.get(agency_id)
    rec = result["record"]
    nofo = {"text": "", "error": "not attempted", "source": ""}
    if config.NOFO_FETCH and rec.get("attachments") and rec.get("status") != "expired":
        try:
            nofo = get_nofo_text(store, rec)
        except Exception as e:
            nofo = {"text": "", "error": str(e)[:200], "source": ""}
    expl = ai_explanation(ai_client, store, profile, out["targets"], result, nofo.get("text", ""))
    x = evaluate_record(rec, profile, out["survey"], out["sim"], nofo.get("text", ""), expl.get("effort_drivers"))
    x["rank"] = result.get("rank")
    if expl.get("source", "").startswith("rules"):
        expl = rule_explanation(x, nofo.get("text", ""))
    x["explanation"] = expl
    x["confidence"] = expl["confidence"]
    x["needs_review"] = expl["confidence"] == "low"
    x["nofo"] = {"source": nofo.get("source", ""), "error": nofo.get("error", ""), "chars": len(nofo.get("text", ""))}
    return x


def precompute(store, ai_client, items: list[dict], data_success: str, errors: list, budget_sec: int = 1800) -> dict:
    """For each agency (using its saved survey), enrich the top results and save them for the app.
    Works round-robin (every agency's #1, then every agency's #2, ...) so with 33 agencies a time limit never leaves
    the last agencies with nothing prepared; anything not reached is prepared on demand when first opened."""
    from feedback import store as fb

    t0, plans = time.time(), {}
    for aid, profile in loader.load_all().items():
        survey = fb.get_survey(store, aid) or {"agency_id": aid}
        dismissed = {k: {"action": "Pass"} for k, v in fb.reviews(store, aid).items() if v["action"] == "Pass"}
        out = rank(items, profile, survey, store, ai_client, dismissed)
        plans[aid] = (survey, out, {})
    stopped = False
    for i in range(PRECOMPUTE_TOP):
        for aid, (survey, out, done) in plans.items():
            if i >= len(out["shortlist"]):
                continue
            if time.time() - t0 > budget_sec:
                stopped = True
                break
            result = out["shortlist"][i]
            try:
                x = enrich_now(result, out, aid, store, ai_client)
                x.pop("record", None)
                done[result["record"]["id"]] = x
            except Exception as e:
                errors.append(f"precompute {aid}/{result['record']['id']}: {e}")
        if stopped:
            errors.append("precompute time budget reached; remaining items will be prepared on demand")
            break
    counts = {}
    for aid, (survey, out, done) in plans.items():
        store.write_json(f"precomputed/{aid}.json", {"survey_key": survey_key(survey), "data_success": data_success,
                                                     "items": json.loads(json.dumps(done, default=str))})
        counts[aid] = len(done)
    return counts
