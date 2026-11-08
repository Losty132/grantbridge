"""Unit + workflow tests. Run: pytest -q
Synthetic records only (tests/fixtures/TEST_ONLY_raw.json)."""
from pathlib import Path

import pytest

from agency_profiles import loader
from common.storage import Storage
from common.text import quote_in_source, sentences
from data_retrieval import refresh
from data_retrieval.store import load_dataset
from eligibility.classify import APPEARS, NOT_ELIGIBLE, PARTNER, VERIFY, classify
from evaluation import run_eval
from feedback import store as fb
from privacy.filter import scan
from scoring.rank import rank
from summarization import brief
from summarization.explain import ai_explanation, rule_explanation
from time_estimate.estimate import estimate, feasibility, merge_ai_drivers

FIX = str(Path(__file__).parent / "fixtures" / "TEST_ONLY_raw.json")


class NoAI:
    available = False


@pytest.fixture()
def st(tmp_path):
    s = Storage(conn="", local_dir=str(tmp_path))
    refresh.run(s, NoAI(), snapshot_file=FIX)
    return s


def by_title(out, frag, key="all"):
    return next(x for x in out[key] if frag in x["record"]["title"])


def test_profiles_have_cited_objectives():
    for aid in ("deq", "dncr", "dpi"):
        p = loader.get(aid)
        assert len(p["objectives"]) >= 5
        assert all(o["citation"]["url"].startswith("https://www.osbm.nc.gov") for o in p["objectives"])


def test_snapshot_labeled_and_deduped(st):
    items, status = load_dataset(st)
    assert status["mode"] == "snapshot"
    assert len({i["id"] for i in items}) == len(items)
    assert all(i.get("first_seen") and i.get("last_modified") for i in items)


def test_hard_filters_and_ranking(st):
    items, _ = load_dataset(st)
    out = rank(items, loader.get("deq"), {"agency_id": "deq", "cost_share": "No", "min_award": "$50K+"}, st)
    reasons = {x["record"]["title"]: " ".join(x["excluded"]) for x in out["filtered"]}
    assert "Expired" in reasons["[TEST ONLY] Expired water grant"]
    assert "Partnership" in reasons["[TEST ONLY] University geologic mapping training"]
    assert "Not Eligible" in reasons["[TEST ONLY] Small business agriculture innovation"]
    assert "Cost share" in reasons["[TEST ONLY] Coastal resilience planning"]
    assert "below your minimum" in reasons["[TEST ONLY] Tiny planning award"]
    assert out["top"][0]["record"]["title"] == "[TEST ONLY] Drinking water PFAS reduction"
    assert all(x["record"]["status"] != "expired" for x in out["shortlist"])
    assert all(0 <= x["score"] <= 100 for x in out["all"])


def test_too_tight_flag(st):
    items, _ = load_dataset(st)
    out = rank(items, loader.get("deq"), {"agency_id": "deq", "prep_time": "60 days"}, st)
    x = by_title(out, "Coastal resilience")
    assert any("Too tight" in f for f in x["flags"])


def test_unknown_gets_partial_credit_never_full(st):
    items, _ = load_dataset(st)
    out = rank(items, loader.get("deq"), {"agency_id": "deq"}, st)
    x = by_title(out, "Others-eligibility")
    assert x["eligibility"]["label"] == VERIFY
    why = x["components"]["resource_feasibility"]["why"]
    assert "cost share not stated, check the notice (3)" in why and "complexity Unknown (3)" in why
    assert x["components"]["applicant_fit"]["points"] < 20


def test_scoring_v2_is_graded_and_ordered():
    from scoring.score import deadline_points
    est_known, est_unknown = {"weeks": [3, 5], "level": "Medium"}, {"weeks": None, "level": "Unknown"}
    sv = {"prep_days": 30}
    pts = lambda d, e=est_known: deadline_points({"days_left": d, "status": "open"}, sv, e)[0]
    # more time never scores lower; feasible beats tight beats not-enough; known effort beats unknown
    seq = [pts(d) for d in (5, 14, 22, 28, 35, 60)]
    assert seq == sorted(seq) and seq[-1] == 15 and seq[0] == 0
    assert pts(60, est_unknown) == 13 and pts(None) == 8
    assert deadline_points({"days_left": -1, "status": "expired"}, sv, est_known)[0] == 0


def test_keywords_strengthen_alignment_and_complete_beats_unknown(st):
    items, _ = load_dataset(st)
    out = rank(items, loader.get("deq"), {"agency_id": "deq"}, st)
    for x in out["all"]:
        a = x["components"]["strategic_alignment"]["points"]
        assert 0 <= a <= 50 and 0 <= x["score"] <= 100
        assert abs(sum(c["points"] for c in x["components"].values()) - x["score"]) < 0.11
    top = out["shortlist"][0]
    assert top["objective_keyword_hits"], "the best DEQ match should be backed by its objective's own keywords"


def test_restrictive_eligibility_decoy_is_flagged():
    decoy = {"id": "T-DECOY", "title": "University water research", "status": "open",
             "description": "Supports universities to reduce PFAS in drinking water. Only institutions of higher "
                            "education may apply. A 1:1 cost match is required.",
             "eligibility_codes": ["20"], "eligibility_labels": ["Private institutions of higher education"],
             "close_date": None, "days_left": None, "url": "", "agency": "", "found_by": []}
    e = classify(decoy)
    assert e["label"] in (PARTNER, NOT_ELIGIBLE)
    x = rank([decoy], loader.get("deq"), {"agency_id": "deq"})["all"][0]
    assert x["excluded"]


def test_brief_text_and_pdf(st):
    items, _ = load_dataset(st)
    x = rank(items, loader.get("deq"), {"agency_id": "deq"}, st)["top"][0]
    b = brief.build(x, rule_explanation(x), loader.get("deq"), "TEST")
    assert x["record"]["title"] in brief.to_text(b) and brief.to_pdf(b)[:4] == b"%PDF"


def test_time_estimate_unknown_and_drivers():
    assert estimate({"description": "Supports community projects."})["level"] == "Unknown"
    rec = {"description": "The project narrative may not exceed 20 pages. Two letters of support are required. "
                          "A 25 percent match is required.", "cost_sharing": True}
    est = estimate(rec)
    keys = {d["key"] for d in est["drivers"]}
    assert {"narrative", "letters", "cost_share"} <= keys and est["level"] in ("Medium", "High")
    assert feasibility(10, 30, est)["status"] == "not_enough"


def test_ai_driver_quotes_must_be_verifiable():
    drivers, rejected = merge_ai_drivers([], [{"driver_key": "loi", "detail": "LOI", "quote": "A letter of intent is due May 1."},
                                              {"driver_key": "evaluation", "detail": "eval", "quote": "An evaluation plan is required."}],
                                         "An evaluation plan is required. Other text.")
    assert rejected == 1 and [d["key"] for d in drivers] == ["evaluation"]


def test_ai_explanation_verification(st):
    items, _ = load_dataset(st)
    out = rank(items, loader.get("deq"), {"agency_id": "deq"}, st)
    x = out["top"][0]

    class LyingAI:
        available = True

        def chat_json(self, system, user):
            assert "<document>" in user
            return {"matched_objective": "DEQ-99.Z", "objective_citation": "x", "grant_evidence_quote":
                    "This grant pays $50 million to every state.", "reasons": ["made up"], "confidence": "high",
                    "effort_drivers": []}
    e = ai_explanation(LyingAI(), st, loader.get("deq"), out["targets"], x)
    assert e["confidence"] == "low"                       # → Needs review
    assert not e["verification"]["objective_valid"] and not e["verification"]["quote_verified"]
    assert quote_in_source(e["grant_evidence_quote"], x["record"]["description"] + x["record"]["title"])
    assert "made up" not in e["reasons"]                  # unverified AI reasons are discarded too

    class MalformedAI:
        available = True

        def chat_json(self, system, user):
            return {"matched_objective": "DEQ-3.B", "grant_evidence_quote": "x", "reasons": 42}
    e2 = ai_explanation(MalformedAI(), None, loader.get("deq"), out["targets"], x)
    assert e2["source"].startswith("rules") or "malformed" in " ".join(e2["verification"]["notes"])


def test_privacy_filter():
    r = scan("Contact Maria Lopez at maria@example.com or 919-555-0100, SSN 123-45-6789")
    assert "maria@example.com" not in r.text and "555-0100" not in r.text and "6789" not in r.text
    assert "Maria Lopez" not in r.text and r.redactions["EMAIL"] == 1
    assert scan("this is a draft budget, internal only").blocked
    for t in ("pre-decisional draft", "FOUO memo", "not for public release", "CUI//SP"):
        assert scan(t).blocked, t
    for t, tag in (("jane [at] example [dot] com", "[EMAIL]"), ("call 919\u2011555\u20110101", "[PHONE]"),
                   ("ssn 123456789", "[ID NUMBER]"), ("PO Box 1234", "[ADDRESS]"), ("DOB 01/02/1980", "[DATE OF BIRTH]"),
                   ("passport X12345678", "[ID NUMBER]")):
        assert tag in scan(t).text, t
    for t in ("circuit design grants", "security grants", "budget justification required", "water quality at coastal sites",
              "deadline 01/05/2027", "CFDA 66.468"):
        assert not scan(t).changed, t
        assert not scan(t).blocked, t
    assert not scan("water quality grants for coastal counties").blocked


def test_feedback_requires_reason_and_filters(st):
    items, _ = load_dataset(st)
    x = rank(items, loader.get("deq"), {"agency_id": "deq"}, st)["top"][0]
    with pytest.raises(ValueError):
        fb.record(st, "deq", x, "Pass", reason="")
    e = fb.record(st, "deq", x, "Pass", "irrelevant", reason="Not our program; ask bob@x.org", user="Ana")
    assert "bob@x.org" not in e["reason"] and fb.reviews(st, "deq")[x["record"]["id"]]["action"] == "Pass"
    with pytest.raises(fb.BlockedText):
        fb.record(st, "deq", x, "Pursue", note="confidential personnel matter")
    # decisions saved under the old names are read with the new ones
    assert fb.record(st, "deq", x, "Save")["action"] == "Pursue"


def test_survey_privacy(st):
    with pytest.raises(fb.BlockedText):
        fb.save_survey(st, "deq", {"other_priority": "draft budget shortfall of $2 million"})
    s = fb.save_survey(st, "deq", {"other_priority": "stream restoration; call 919-555-0100", "capacity": "1"})
    assert "555" not in s["other_priority"] and s["top_n"] == 3


def test_sentences_keep_abbreviations():
    assert sentences("The U.S. Geological Survey funds mapping work here. Second sentence is right here.")[0].startswith("The U.S. Geological")


def test_evaluation_runs_without_fabrication(st):
    r = run_eval.run(st, NoAI())
    assert all(isinstance(v, str) and v.startswith("not computed") for k, v in r["metrics"].items()
               if k in ("deq", "dncr", "dpi"))
    assert r["accuracy"]["top_picks"]["value"] is None and r["accuracy"]["top_picks"]["status"] == "wait"
    names = {t["test"]: t["result"] for t in r["tests"]}
    assert names["Expired grants are never recommended"] == "PASS"
    assert names["Effort is 'Unknown' rather than guessed"] == "PASS"
    assert names["Unverified AI explanations are never shown"] == "SKIPPED"
    assert names["Personal details are removed from what people type"] == "PASS"
    one = run_eval.run(st, NoAI(), agency="dot")
    assert one["agency"] == "dot" and set(one["metrics"]) <= {"dot"}


def test_bare_names_removed_but_places_kept():
    from privacy.filter import scan
    assert "Nguyen" not in scan("Kim Nguyen will draft it").text
    assert "Johnson" not in scan("talk to Sarah Johnson tomorrow").text
    for keep in ("Funding for Jordan Lake water quality", "Ryan White HIV/AIDS Program funding",
                 "Charlotte Mecklenburg schools", "North Carolina DEQ", "Mary Washington University"):
        assert scan(keep).text == keep, keep


def test_paused_evaluation_stops_itself():
    c = run_eval.Control(pause_limit=0.5)
    c.pause()
    import pytest as _p
    with _p.raises(run_eval.Stopped):
        c.checkpoint()
    assert c.timed_out


def test_changed_or_old_details_are_fetched_again():
    from datetime import datetime, timedelta, timezone
    from data_retrieval.refresh import details_to_fetch, hit_signature
    now = datetime.now(timezone.utc)
    hits = {"1": {"title": "A", "closeDate": "01/05/2027"}, "2": {"title": "B", "closeDate": "02/01/2027"},
            "3": {"title": "C", "closeDate": "03/01/2027"}, "4": {"title": "D", "closeDate": "04/01/2027"}}
    cache = {"2": {"_sig": "stale-signature", "_fetched": now.isoformat()},                       # deadline amended
             "3": {"_sig": hit_signature(hits["3"]), "_fetched": (now - timedelta(days=30)).isoformat()},  # old
             "4": {"_sig": hit_signature(hits["4"]), "_fetched": now.isoformat()}}               # fresh: skip
    assert details_to_fetch(hits, cache) == ["1", "2", "3"]


def test_text_that_excludes_states_overrides_the_field():
    def rec(t):
        return {"id": "x", "title": "t", "description": t, "eligibility_codes": ["00"], "eligibility_labels": [],
                "eligibility_text": "", "status": "open"}
    for t in ("State governments are not eligible to apply.", "States may not apply directly.",
              "Ineligible applicants include for-profit firms and states.", "This program excludes states."):
        assert classify(rec(t))["label"] == VERIFY, t
    for t in ("States and local governments are eligible.", "Funds support states in reducing PFAS."):
        assert classify(rec(t))["label"] == APPEARS, t



def test_review_round_fixes(tmp_path, monkeypatch):
    """Regressions for the external code review (Nov 7)."""
    from data_retrieval import nofo
    from data_retrieval.normalize import _bool
    from data_retrieval.refresh import carry_over_failed
    from privacy import filter as pf

    # privacy: new formats caught, normal grant text untouched
    for t in ("Reach out at staff[at]nc.gov", "+44 20 7946 0958", "123 4th Street", "Employee ID: EMP-448921",
              "Contact: John Smith", "Prepared by: Mary Jane Watson", "Point of contact is Elizabeth Montgomery"):
        assert scan(t).changed, t
    for t in ("C O N F I D E N T I A L draft note", "EMBARGOED until the announcement"):
        assert scan(t).blocked, t
    for t in ("Contact North Carolina DEQ", "From Hurricane Helene recovery", "Public Law 117-58 Section 40101",
              "Award ceiling is $2,500,000", "Contact Wake County"):
        assert not scan(t).changed and not scan(t).blocked, t
    # internal text is blocked before the optional Azure detector ever sees it
    seen = []
    monkeypatch.setattr(pf, "_azure_pii", lambda text: seen.append(text))
    assert scan("confidential draft budget").blocked and seen == []

    # eligibility phrasings
    def rec(c, t):
        return {"id": "x", "title": "t", "description": t, "eligibility_codes": c, "eligibility_labels": [],
                "eligibility_text": "", "status": "open"}
    assert classify(rec(["00"], "State governments are excluded from applying."))["label"] == VERIFY
    assert classify(rec(["99"], "Eligibility is restricted exclusively to 501(c)(3) nonprofits."))["label"] == VERIFY

    # unknown cost sharing stays unknown (scores 0, not 'no match required')
    assert [_bool(v) for v in ("unknown", "Yes", "No", None, "see NOFO")] == [None, True, False, None, None]

    # "not required" doesn't count as effort, per clause
    keys = lambda d: [x["key"] for x in estimate({"description": d})["drivers"]]  # noqa: E731
    assert keys("A letter of intent is not required. Letters of support are not required.") == []
    assert "narrative" in keys("Letters of support are optional; a 20-page narrative is required.")

    # NOFO text is re-read when the attachment changes
    s = Storage(conn="", local_dir=str(tmp_path))
    s.write_json("nofo/1.json", {"text": "old", "source": "a", "error": "", "fetched_at": "2026-01-01T00:00:00+00:00",
                                 "attachment_id": "A"})
    monkeypatch.setattr(nofo.config, "NOFO_FETCH", False)
    r = {"id": "1", "attachments": [{"id": "B", "name": "nofo.pdf", "mime": "application/pdf"}]}
    assert nofo.get_nofo_text(s, r)["text"] == ""
    r["attachments"][0]["id"] = "A"
    s.write_json("nofo/1.json", {"text": "old", "source": "a", "error": "", "fetched_at": "x", "attachment_id": "A"})
    assert nofo.get_nofo_text(s, r)["text"] == "old"

    # a failed search keeps the previous notices it used to find (instead of silently dropping them)
    s.write_json("opportunities/latest.json", {"items": [
        {"id": "9", "found_by": ["kw:deq"], "close_date": "2099-01-01"},
        {"id": "8", "found_by": ["broad"], "close_date": "2099-01-01"},
        {"id": "7", "found_by": ["kw:deq"], "close_date": "2000-01-01"}]})
    recs = [{"id": "1", "found_by": ["broad"]}]
    assert carry_over_failed(s, recs, ["kw:deq"]) == 1 and [r["id"] for r in recs] == ["1", "9"]


def test_ai_reasons_must_cite_real_numbers(st):
    from summarization.explain import grounded
    src = "Awards up to $2,000,000. A 25 percent match is required."
    assert grounded("Award ceiling is $2,000,000", src) and grounded("Requires a 25% match", src)
    assert not grounded("Guaranteed award of $50 million", src) and not grounded("Funds 40 projects", src)
