"""Deadline-aware alerts (stretch goal 2): "This opportunity closes in 10 days."

Three ways an alert reaches people, from no setup to some:
  1. On the site: a banner on the Matches page and tags on the cards (always on).
  2. Calendar file: one .ics download per agency with every deadline the team is tracking, each with reminders
     14, 10, 7 and 1 day(s) before. Works in Outlook, Google Calendar and Apple Calendar. No setup.
  3. Teams / Slack / Power Automate message: the daily refresh job posts "closes in N days" alerts to the URL in
     ALERT_WEBHOOK_URL on days 14, 10, 7, 3 and 1. Off until that variable is set. Each alert is sent once
     (alerts/sent.json remembers what went out).

Which grants are tracked: every grant the team marked Pursue or Maybe, plus the agency's current top picks.
Grants that have closed are never alerted.
"""
import logging
import os
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger("alerts")
ALERT_DAYS = (14, 10, 7, 3, 1)          # days before the deadline that a message is sent
SITE_WINDOW = 14                        # the site banner lists tracked grants closing within this many days
REMINDERS = (14, 10, 7, 1)              # calendar reminders


def webhook_url() -> str:
    return os.getenv("ALERT_WEBHOOK_URL", "").strip()


def phrase(days: int) -> str:
    if days == 0:
        return "closes today"
    if days == 1:
        return "closes tomorrow"
    return f"closes in {days} days"


def tracked(records_by_id: dict, reviews: dict, top_ids: list[str] | None = None) -> list[dict]:
    """Grants the team is following: Pursue / Maybe decisions + the current top picks, still open, soonest first."""
    want = {oid: v.get("action") for oid, v in (reviews or {}).items() if v.get("action") in ("Pursue", "Maybe")}
    for oid in top_ids or []:
        want.setdefault(oid, "Top pick")
    out = []
    for oid, why in want.items():
        r = records_by_id.get(oid)
        if not r or r.get("status") == "expired" or r.get("days_left") is None or r["days_left"] < 0:
            continue
        out.append({"id": oid, "title": r["title"], "number": r.get("number"), "close_date": r.get("close_date"),
                    "days": r["days_left"], "url": r.get("url"), "because": why,
                    "text": f"This opportunity {phrase(r['days_left'])} ({r.get('close_date')})."})
    return sorted(out, key=lambda a: a["days"])


def ics(agency_name: str, items: list[dict]) -> str:
    """An iCalendar file: one all-day event per deadline, with reminders before it."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def esc(t: str) -> str:
        return str(t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", " ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//GrantBridge//Grant deadlines//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{esc('Grant deadlines · ' + agency_name)}"]
    for a in items:
        if not a.get("close_date"):
            continue
        d = date.fromisoformat(a["close_date"])
        lines += ["BEGIN:VEVENT", f"UID:grantbridge-{a['id']}@nc-osbm", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                  f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
                  f"SUMMARY:{esc('Grant deadline: ' + a['title'][:120])}",
                  f"DESCRIPTION:{esc((a.get('number') or '') + ' · ' + (a.get('because') or '') + ' · ' + (a.get('url') or ''))}",
                  f"URL:{a.get('url') or ''}"]
        for n in REMINDERS:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-P{n}D",
                      f"DESCRIPTION:{esc('This opportunity ' + phrase(n) + ': ' + a['title'][:100])}", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def due_messages(storage, records_by_id: dict, agencies: dict, reviews_for) -> list[dict]:
    """Alerts due today (a tracked grant is exactly 14, 10, 7, 3 or 1 days out) that were not sent before."""
    sent = set(storage.read_json("alerts/sent.json", default=[]) or [])
    out = []
    for aid, prof in agencies.items():
        for a in tracked(records_by_id, reviews_for(aid)):
            key = f"{aid}|{a['id']}|{a['close_date']}|{a['days']}"
            if a["days"] in ALERT_DAYS and key not in sent:
                out.append(dict(a, agency=aid, agency_name=prof.get("short_name") or aid.upper(), key=key))
    return out


def notify(storage, records: list[dict], agencies: dict, reviews_for, post=None) -> dict:
    """Run by the daily refresh job. Posts each due alert to ALERT_WEBHOOK_URL once. Returns what happened."""
    url = webhook_url()
    by_id = {r["id"]: r for r in records}
    msgs = due_messages(storage, by_id, agencies, reviews_for)
    if not url:
        return {"configured": False, "due": len(msgs), "sent": 0}
    if post is None:
        import requests

        def post(u, payload):
            requests.post(u, json=payload, timeout=15).raise_for_status()
    sent, failed = [], 0
    for m in msgs:
        text = (f"⏰ {m['agency_name']}: “{m['title']}” {phrase(m['days'])} ({m['close_date']}). "
                f"Your team marked it {m['because']}. {m.get('url') or ''}")
        try:
            post(url, {"text": text})
            sent.append(m["key"])
        except Exception as e:  # one failed message never stops the others or the refresh
            failed += 1
            log.warning("alert not sent: %s", type(e).__name__)
    if sent:
        storage.update_json("alerts/sent.json", lambda s: sorted(set(s or []) | set(sent))[-5000:], default=[])
    return {"configured": True, "due": len(msgs), "sent": len(sent), "failed": failed}
