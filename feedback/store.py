"""Survey answers and human review (Pursue / Maybe / Pass + relevance), persisted as JSON in storage.
Everything typed is privacy-filtered before it is saved; blocked text is never stored."""
import re
import uuid
from datetime import datetime, timezone

from privacy.filter import log_event, scan
from scoring.survey import normalize

ACTIONS = ["Pursue", "Maybe", "Pass"]
# Older saved decisions used Save / Investigate / Dismiss; they are read as the new names.
LEGACY = {"Save": "Pursue", "Investigate": "Maybe", "Dismiss": "Pass"}


def _norm(e: dict) -> dict:
    a = e.get("action")
    return dict(e, action=LEGACY.get(a, a)) if a in LEGACY else e
RELEVANCE = ["", "relevant", "irrelevant", "needs investigation"]


class BlockedText(ValueError):
    pass


def get_survey(storage, agency_id: str) -> dict | None:
    return storage.read_json(f"surveys/{agency_id}.json")


def save_survey(storage, agency_id: str, survey: dict) -> dict:
    s = normalize(dict(survey, agency_id=agency_id))
    res = scan(s.get("other_priority", ""))
    log_event(storage, "survey other priority", res)
    if res.blocked:
        raise BlockedText(res.summary())
    s["other_priority"] = res.text
    s["saved_at"] = datetime.now(timezone.utc).isoformat()
    storage.write_json(f"surveys/{agency_id}.json", s)
    return s


def reviews(storage, agency_id: str) -> dict:
    """Latest review per opportunity id."""
    latest = {}
    for e in history(storage, agency_id):
        latest[e["opp_id"]] = e
    return latest


def history(storage, agency_id: str) -> list[dict]:
    return [_norm(e) for e in storage.read_json(f"feedback/{agency_id}.json", default=[]) or []]


def record(storage, agency_id: str, result: dict, action: str, relevance: str = "", reason: str = "",
           note: str = "", user: str = "") -> dict:
    action = LEGACY.get(action, action)
    if action not in ACTIONS:
        raise ValueError("Unknown action")
    if relevance not in RELEVANCE:
        raise ValueError("Unknown relevance value")
    if action == "Pass" and not reason.strip():
        raise ValueError("Pass requires a reason")
    cleaned = {}
    for field, text in (("reason", reason), ("note", note), ("user", user)):
        res = scan(text)
        log_event(storage, f"feedback {field}", res)
        if res.blocked:
            raise BlockedText(f"{field}: {res.summary()}")
        cleaned[field] = res.text[:1000]
    cleaned["user"] = initials(cleaned["user"])
    r = result["record"]
    entry = {"opp_id": r["id"], "number": r.get("number"), "title": r["title"], "action": action,
             "relevance": relevance, **cleaned, "at": datetime.now(timezone.utc).isoformat(),
             "score_at_review": result["score"], "eligibility_at_review": result["eligibility"]["label"],
             "close_date": r.get("close_date"), "url": r.get("url")}
    storage.update_json(f"feedback/{agency_id}.json", lambda log: (log or []) + [entry], default=[])
    return entry


def clear(storage, agency_id: str) -> int:
    """Empty the decision log for an agency. The old log is archived first (audit trail), never just deleted."""
    # microseconds + a random suffix: two clears in the same second can never overwrite each other's archive
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "_" + uuid.uuid4().hex[:6]
    cleared = {"n": 0}

    def change(log):
        log = log or []
        if log:
            storage.write_json(f"feedback/archive/{agency_id}_{stamp}.json", log)
        cleared["n"] = len(log)
        return []
    storage.update_json(f"feedback/{agency_id}.json", change, default=[])
    return cleared["n"]


def restore_last(storage, agency_id: str) -> int:
    """Undo the most recent clear: put the newest not-yet-restored archive back in front of anything
    recorded since. Archives are never deleted; a small ledger remembers which ones were restored."""
    ledger_path = f"feedback/archive/restored_{agency_id}.json"
    done = set(storage.read_json(ledger_path, default=[]) or [])
    archives = [p for p in storage.list(f"feedback/archive/{agency_id}_") if p not in done]
    if not archives:
        return 0
    latest = archives[-1]
    old = storage.read_json(latest, default=[]) or []
    storage.update_json(f"feedback/{agency_id}.json", lambda log: old + (log or []), default=[])
    storage.update_json(ledger_path, lambda d: sorted(set(d or []) | {latest}), default=[])
    return len(old)


def initials(name: str) -> str:
    """Decisions record initials, never a full name: 'Jane Q. Smith' -> 'JQS', 'Jane' -> 'J', 'JS' -> 'JS'."""
    name = re.sub(r"\[[^\]]*\]", " ", name or "")  # drop privacy-filter placeholders like [NAME]
    words = [w for w in re.split(r"[^A-Za-z]+", name) if w]
    if len(words) == 1 and len(words[0]) <= 3:
        return words[0].upper()
    return "".join(w[0].upper() for w in words)[:4]
