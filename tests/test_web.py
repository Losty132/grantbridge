"""API tests for the Flask web server. Synthetic TEST_ONLY records; no network.
Every route that accepts typed text is checked: personal info is redacted, internal info is blocked (422)."""
import pytest

from common.storage import Storage
from data_retrieval import refresh
from web import server
from web.service import Engine

from tests.test_core import FIX, NoAI


@pytest.fixture()
def client(tmp_path, monkeypatch):
    s = Storage(conn="", local_dir=str(tmp_path))
    refresh.run(s, NoAI(), snapshot_file=FIX)
    monkeypatch.setattr(server, "engine", Engine(storage=s, ai=NoAI()))
    server.app.testing = True
    server._writes.clear()  # each test starts with a fresh write allowance
    return server.app.test_client()


def first_id(c):
    m = c.get("/api/matches/deq").get_json()
    rows = m["top"] or m["shortlist"]
    assert rows, "fixture should produce at least one DEQ match"
    return rows[0]["id"]


def test_health_and_security_headers(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert "Content-Security-Policy" in r.headers and r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store" and r.headers["X-Content-Type-Options"] == "nosniff"


def test_pages_assets_and_404(client):
    for path in ("/", "/index.html", "/decisions.html", "/evaluation.html", "/method.html", "/decisions", "/method"):
        r = client.get(path)
        assert r.status_code == 200 and b"privacy filter screens everything" in r.data, path
        assert r.headers["Cache-Control"] == "no-cache"
    for asset in ("/script.js", "/stylesheet.css"):
        r = client.get(asset)
        assert r.status_code == 200 and r.headers["Cache-Control"] == "public, max-age=300"
    v = client.get("/script.js?v=abc")
    assert "immutable" in v.headers["Cache-Control"]
    html = client.get("/").data.decode()
    assert "stylesheet.css?v=" in html and "script.js?v=" in html
    assert client.get("/landslide.html").status_code == 404
    assert client.get("/nope").status_code == 404
    r = client.get("/../../etc/passwd")
    assert r.status_code == 404 and b"root:" not in r.data
    assert b"Landslide" not in client.get("/").data


def test_meta_and_matches(client):
    meta = client.get("/api/meta").get_json()
    assert {a["id"] for a in meta["agencies"]} >= {"deq", "dncr", "dpi"}
    assert meta["data"]["level"] in ("live", "cached", "snapshot", "none")
    assert "privacy filter" in meta["privacy"]["banner"].lower()
    m = client.get("/api/matches/deq").get_json()
    assert set(m["stats"]) == {"reviewed", "shortlist", "eligible", "due14", "set_aside"}
    assert m["stats"]["shortlist"] + m["stats"]["set_aside"] == m["stats"]["reviewed"]
    scores = [c["score"] for c in m["top"]]
    assert scores == sorted(scores, reverse=True) and all(0 <= s <= 100 for s in scores)


def test_bad_inputs_rejected(client):
    assert client.get("/api/matches/nope").status_code == 404
    assert client.get("/api/opportunity/deq/abc").status_code == 400
    assert client.get("/api/opportunity/deq/999999999").status_code == 404
    assert client.get("/api/does-not-exist").get_json()["message"] == "Unknown API endpoint"
    r = client.post("/api/survey/deq", data="not json", content_type="application/json")
    assert r.status_code == 400
    assert client.post("/api/survey/deq", json=["a", "list"]).status_code == 400
    big = client.post("/api/search/deq", json={"q": "x" * 70_000})
    assert big.status_code == 413


def test_detail_has_evidence(client):
    d = client.get(f"/api/opportunity/deq/{first_id(client)}").get_json()
    assert d["components"] and d["explanation"]["grant_evidence_quote"]
    assert sum(c["points"] for c in d["components"]) == pytest.approx(d["score"], abs=0.6)
    assert d["eligibility_detail"]["label"] and d["estimate"]["level"]


def test_survey_privacy(client):
    base = client.get("/api/survey/deq").get_json()["answers"]
    r = client.post("/api/survey/deq", json={**base, "other_priority": "stream work, call jane.doe@example.com"})
    assert r.status_code == 200 and "[EMAIL]" in r.get_json()["survey"]["other_priority"]
    r = client.post("/api/survey/deq", json={**base, "other_priority": "internal only draft budget"})
    assert r.status_code == 422 and r.get_json()["blocked"]
    assert "internal" not in client.get("/api/survey/deq").get_json()["answers"]["other_priority"]


def test_search_brief_decision_privacy(client):
    oid = first_id(client)
    r = client.post("/api/search/deq", json={"q": "drinking water, ssn 123-45-6789"})
    assert r.status_code == 200 and r.get_json()["privacy"]["changed"]
    assert client.post("/api/search/deq", json={"q": "confidential pre-decisional plan"}).status_code == 422

    r = client.post(f"/api/brief/deq/{oid}", json={"notes": "email bob@example.com", "format": "text"})
    assert r.status_code == 200 and "bob@example.com" not in r.get_json()["text"]
    r = client.post(f"/api/brief/deq/{oid}", json={"notes": "", "format": "pdf"})
    assert r.status_code == 200 and r.data[:4] == b"%PDF"
    assert client.post(f"/api/brief/deq/{oid}", json={"notes": "internal only", "format": "pdf"}).status_code == 422


def test_decisions_pursue_maybe_pass(client):
    oid = first_id(client)
    assert client.post(f"/api/decision/deq/{oid}", json={"action": "Pass", "reason": ""}).status_code == 400
    assert client.post(f"/api/decision/deq/{oid}", json={"action": "Bogus"}).status_code == 400
    r = client.post(f"/api/decision/deq/{oid}", json={"action": "Pursue", "relevance": "relevant", "reason": "fits",
                                                       "note": "ask 919-555-0101", "user": "Pat"})
    assert r.status_code == 200 and "919-555-0101" not in r.get_json()["entry"]["note"]
    assert r.get_json()["privacy"]["note"]["changed"]
    assert client.post(f"/api/decision/deq/{oid}", json={"action": "Maybe", "note": "internal only"}).status_code == 422
    d = client.get("/api/decisions/deq").get_json()
    assert d["counts"] == {"Pursue": 1, "Maybe": 0, "Pass": 0} and d["total_actions"] == 1
    # Pass removes it from the top list
    client.post(f"/api/decision/deq/{oid}", json={"action": "Pass", "reason": "not our program"})
    assert oid not in [c["id"] for c in client.get("/api/matches/deq").get_json()["top"]]


def wait_eval(client, aid="deq"):
    import time
    for _ in range(300):
        r = client.get(f"/api/evaluation/{aid}").get_json()
        if r["job"]["state"] not in ("running", "paused", "stopping"):
            return r
        time.sleep(0.1)
    raise AssertionError("evaluation did not finish")


def test_evaluation_runs_in_background_for_the_chosen_agency_only(client):
    assert client.get("/api/evaluation/deq").get_json()["job"]["state"] == "idle"
    assert client.post("/api/evaluation/deq/run", json={}).get_json()["job"]["agency"] == "deq"
    r = wait_eval(client)
    assert r["job"]["state"] == "finished"
    res = r["result"]
    assert res["agency"] == "deq" and set(k for k in res["metrics"] if k != "time_estimate_unknown_in_top_n") == {"deq"}
    names = [t["test"] for t in res["tests"]]
    assert any("look-alike" in n.lower() for n in names) and all(t.get("what") for t in res["tests"])
    assert res["accuracy"]["top_picks"]["status"] == "wait"            # no decisions yet → says so, no number
    assert "Jordan Lee" not in str(res) and res["safety"]["status"] == "good"
    assert client.get("/api/evaluation/dot").get_json()["result"] == {}   # other agencies are not evaluated


def test_evaluation_pause_resume_and_stop():
    import threading
    from evaluation import run_eval
    c = run_eval.Control()
    c.pause(); assert c.paused
    t = threading.Thread(target=c.checkpoint); t.start(); t.join(0.3); assert t.is_alive()   # waits while paused
    c.resume(); t.join(1); assert not t.is_alive()
    c.stop()
    import pytest as _p
    with _p.raises(run_eval.Stopped):
        c.checkpoint()


def test_concurrent_decisions_are_never_lost(client, tmp_path):
    """Regression: parallel decisions used to corrupt the decision log (shared temp file, no lock)."""
    from concurrent.futures import ThreadPoolExecutor
    oid = first_id(client)
    before = client.get("/api/decisions/deq").get_json()["total_actions"]

    def one(i):
        return client.post(f"/api/decision/deq/{oid}", json={"action": "Maybe", "note": f"n{i}"}).status_code

    with ThreadPoolExecutor(16) as pool:
        codes = list(pool.map(one, range(60)))
    assert codes == [200] * 60
    assert client.get("/api/decisions/deq").get_json()["total_actions"] == before + 60


def test_malformed_survey_never_errors(client):
    r = client.post("/api/survey/deq", json={"capacity": "999", "min_award": {"x": 1}, "focus_objectives": "DEQ-1.A",
                                            "other_priority": 123, "prep_time": None})
    assert r.status_code == 200
    s = r.get_json()["survey"]
    assert s["capacity"] == "3" and s["min_award"] == "Any" and s["focus_objectives"] == [] and s["other_priority"] == ""


def test_rankings_roll_over_at_midnight(client, monkeypatch):
    """Regression: cached rankings used to keep yesterday's days-left until the next morning refresh."""
    from datetime import date, timedelta
    from data_retrieval import normalize
    from web import service

    m = client.get("/api/matches/deq").get_json()
    row = next(r for r in m["shortlist"] if r["close_date"])
    after = date.fromisoformat(row["close_date"]) + timedelta(days=1)
    monkeypatch.setattr(normalize, "today", lambda: after)
    monkeypatch.setattr(service, "today", lambda: after)
    m2 = client.get("/api/matches/deq").get_json()
    assert row["id"] not in [r["id"] for r in m2["shortlist"]]
    gone = next(r for r in m2["set_aside"] if r["id"] == row["id"])
    assert "Expired" in gone["why_set_aside"] and gone["days_left"] == -1


def test_write_rate_limit_and_cooldowns(client, monkeypatch):
    monkeypatch.setattr(server, "WRITES_PER_MINUTE", 5)
    server._writes.clear()
    codes = [client.post("/api/search/deq", json={"q": "water"}, headers={"X-Forwarded-For": "203.0.113.9"}).status_code
             for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    assert client.post("/api/search/deq", json={"q": "water"}, headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 200
    server._writes.clear()
    client.post("/api/evaluation/deq/run", json={})
    wait_eval(client)
    again = client.post("/api/evaluation/deq/run", json={}).get_json()
    assert "just ran" in again["error"]


def test_full_lists_and_no_stale_cache(client):
    m = client.get("/api/matches/deq").get_json()
    assert len(m["shortlist"]) == m["stats"]["shortlist"] and len(m["set_aside"]) == m["stats"]["set_aside"]
    # a write during an in-flight read must not let the stale read be cached
    eng = server.engine
    eng._forget("reviews", "deq")
    stale = eng._cached("reviews", "deq", lambda: (eng._forget("reviews", "deq"), {"old": True})[1])
    assert stale == {"old": True}
    assert eng._cached("reviews", "deq", lambda: {"fresh": True}) == {"fresh": True}


def test_clear_decisions_archives_then_empties(client, tmp_path):
    oid = first_id(client)
    client.post(f"/api/decision/deq/{oid}", json={"action": "Pursue"})
    client.post(f"/api/decision/deq/{oid}", json={"action": "Pass", "reason": "not ours"})
    assert client.post("/api/decisions/deq/clear", json={}).status_code == 400          # needs explicit confirm
    r = client.post("/api/decisions/deq/clear", json={"confirm": "CLEAR"}).get_json()
    assert r["cleared"] == 2
    d = client.get("/api/decisions/deq").get_json()
    assert d["items"] == [] and d["total_actions"] == 0
    assert oid in [c["id"] for c in client.get("/api/matches/deq").get_json()["top"]]  # the Pass no longer hides it
    archived = server.engine.store.list("feedback/archive/")
    assert len(archived) == 1 and len(server.engine.store.read_json(archived[0])) == 2


def test_rate_limit_uses_ingress_address_not_client_header(client, monkeypatch):
    monkeypatch.setattr(server, "WRITES_PER_MINUTE", 3)
    server._writes.clear()
    # a client rotating a fake first address is still counted by the address the ingress appended (last)
    codes = [client.post("/api/search/deq", json={"q": "water"},
                         headers={"X-Forwarded-For": f"1.2.3.{i}, 203.0.113.50"}).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_two_clears_in_one_second_keep_both_archives_and_undo_restores(client):
    oid = first_id(client)
    client.post(f"/api/decision/deq/{oid}", json={"action": "Pursue"})
    client.post("/api/decisions/deq/clear", json={"confirm": "CLEAR"})
    client.post(f"/api/decision/deq/{oid}", json={"action": "Maybe"})
    client.post("/api/decisions/deq/clear", json={"confirm": "CLEAR"})        # same second as the first clear
    archives = [p for p in server.engine.store.list("feedback/archive/deq_")]
    assert len(archives) == 2                                                   # nothing overwritten
    r = client.post("/api/decisions/deq/restore", json={}).get_json()
    assert r["restored"] == 1
    assert client.get("/api/decisions/deq").get_json()["items"][0]["action"] == "Maybe"
    assert client.post("/api/decisions/deq/restore", json={}).get_json()["restored"] == 1   # older clear next
    assert client.get("/api/decisions/deq").get_json()["total_actions"] == 2
    assert client.post("/api/decisions/deq/restore", json={}).get_json()["restored"] == 0


def test_reviewer_saved_as_initials_never_full_name(client):
    oid = first_id(client)
    e = client.post(f"/api/decision/deq/{oid}", json={"action": "Pursue", "user": "Jane Quinn Smith"}).get_json()
    saved = client.get("/api/decisions/deq").get_json()["items"][0]["user"]
    assert saved in ("JQS", "") and "Smith" not in str(e) and "Smith" not in saved


def test_every_state_agency_profile_loads_and_is_offered():
    import glob, json
    from agency_profiles.loader import validate
    files = glob.glob("agency_profiles/profiles/*.json")
    assert len(files) >= 33
    for f in files:
        assert not validate(json.load(open(f))), f


def test_unc_eligibility_uses_its_own_applicant_codes():
    from eligibility.classify import classify
    rec = {"id": "x", "title": "Research", "eligibility_codes": ["06"],
           "eligibility_labels": ["Public and State controlled institutions of higher education"]}
    unc = classify(rec, "", ["06", "25"])
    deq = classify(rec, "", ["00", "25"])
    assert unc["label"] != deq["label"]


def test_survey_reset_clears_filters_and_returns_previous_for_undo(client):
    client.post("/api/survey/deq", json={"focus_objectives": ["DEQ-1.A"], "other_priority": "stream restoration",
                                         "min_award": "$1M+", "cost_share": "No", "capacity": "1", "prep_time": "60 days"})
    r = client.post("/api/survey/deq/reset", json={}).get_json()
    assert r["previous"]["min_award"] == "$1M+" and r["previous"]["other_priority"] == "stream restoration"
    a = client.get("/api/survey/deq").get_json()["answers"]
    assert a["focus_objectives"] == [] and a["other_priority"] == "" and a["min_award"] == "Any"
    assert a["cost_share"] == "Sometimes" and a["capacity"] == "3" and a["prep_time"] == "30 days"
    m = client.get("/api/matches/deq").get_json()
    assert m["survey"]["min_award"] == "Any"
    # undo = re-saving the previous answers (screened again)
    assert client.post("/api/survey/deq", json=r["previous"]).status_code == 200
    assert client.get("/api/survey/deq").get_json()["answers"]["min_award"] == "$1M+"


def test_evaluation_uses_team_decisions_fairly(client):
    m = client.get("/api/matches/deq").get_json()
    ids = [x["id"] for x in m["shortlist"]]
    assert len(ids) >= 4, "fixture needs a few DEQ grants"
    client.post(f"/api/decision/deq/{ids[0]}", json={"action": "Pursue"})
    client.post(f"/api/decision/deq/{ids[1]}", json={"action": "Maybe"})
    client.post(f"/api/decision/deq/{ids[2]}", json={"action": "Pass", "reason": "no staff capacity this month"})
    client.post(f"/api/decision/deq/{ids[3]}", json={"action": "Pass", "reason": "wrong program area"})
    client.post("/api/evaluation/deq/run", json={})
    res = wait_eval(client)["result"]
    a = res["accuracy"]
    assert a["skipped_passes"] == 1                # a Pass for capacity is not counted as a bad match
    assert a["judged"] == 3 and a["good"] == 2
    assert a["top_picks"]["status"] in ("good", "check", "bad")       # 3 judged in the top 5 → answered
    assert a["top_picks"]["value"] == round(2 / 3, 3)
    assert any(p["kind"] == "top_pick_passed" and p["title"] for p in res["problems"])


def test_feedback_learning_nudges_similar_grants(client):
    m = client.get("/api/matches/deq").get_json()
    ids = [x["id"] for x in m["shortlist"]]
    client.post(f"/api/decision/deq/{ids[0]}", json={"action": "Pursue"})
    client.post(f"/api/decision/deq/{ids[-1]}", json={"action": "Pass", "reason": "wrong program area"})
    out, _ = server.engine.ranked("deq")
    nudged = [x for x in out["shortlist"] if x.get("feedback")]
    for x in nudged:
        assert abs(x["score"] - x["base_score"]) <= 8.01 and x["feedback"]["why"]
        assert x["record"]["id"] not in (ids[0], ids[-1]) or x["feedback"]["like"] not in (x["record"]["id"],)
    # a Pass for capacity reasons teaches nothing
    from feedback import learn
    assert learn.label_of({"action": "Pass", "reason": "no staff capacity"}) is None
    assert learn.label_of({"action": "Pass", "reason": "not our mission"}) == 0
    assert learn.label_of({"action": "Maybe"}) == 1


def test_deadline_alerts_calendar_and_webhook(client, monkeypatch):
    from datetime import date, timedelta
    from alerts import deadlines
    m = client.get("/api/matches/deq").get_json()
    oid = m["shortlist"][0]["id"]
    client.post(f"/api/decision/deq/{oid}", json={"action": "Pursue"})
    a = client.get("/api/alerts/deq").get_json()
    assert a["webhook_configured"] is False and isinstance(a["items"], list)
    cal = client.get("/api/alerts/deq/calendar.ics")
    assert cal.status_code == 200 and cal.mimetype == "text/calendar" and b"BEGIN:VCALENDAR" in cal.data
    # webhook: one message per (grant, day), never repeated
    store = server.engine.store
    rec = {"id": "X1", "title": "Test grant", "status": "open", "close_date": (date.today() + timedelta(days=10)).isoformat(),
           "days_left": 10, "url": "https://example.gov"}
    sent = []
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://hooks.example.test/x")
    profs = {"deq": {"short_name": "DEQ"}}
    rv = lambda aid: {"X1": {"action": "Pursue"}}
    r1 = deadlines.notify(store, [rec], profs, rv, post=lambda u, p: sent.append(p["text"]))
    r2 = deadlines.notify(store, [rec], profs, rv, post=lambda u, p: sent.append(p["text"]))
    assert r1["sent"] == 1 and r2["sent"] == 0 and "closes in 10 days" in sent[0]


def test_report_missed_grant(client):
    m = client.get("/api/matches/deq").get_json()
    oid = m["shortlist"][0]["id"]
    r = client.post("/api/missed/deq", json={"grant": f"https://www.grants.gov/search-results-detail/{oid}"}).get_json()
    assert r["position"] == 1 and "already has" in r["message"]
    r = client.post("/api/missed/deq", json={"grant": "NOT-IN-DATA-123"}).get_json()
    assert r["entry"]["in_data"] is False
    assert client.post("/api/missed/deq", json={"grant": "call me at 919 555 0100"}).status_code == 400
    client.post("/api/evaluation/deq/run", json={})
    res = wait_eval(client)["result"]
    assert res["version"] == 4 and len(res["reach"]["reported_missed"]) == 2 and res["scorecard"]["screening"]["value"]
