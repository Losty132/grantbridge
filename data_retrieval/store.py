"""Read the current dataset and its freshness label for the app."""
from zoneinfo import ZoneInfo
from datetime import datetime, timezone

from data_retrieval.normalize import refresh_days_left
from data_retrieval.refresh import DATASET, STATUS


def load_dataset(storage) -> tuple[list[dict], dict]:
    data = storage.read_json(DATASET, default=None) or {}
    status = storage.read_json(STATUS, default=None) or {}
    items = refresh_days_left(data.get("items") or [])
    return items, status


def freshness_label(status: dict) -> tuple[str, str]:
    """Return (level, message). level is 'live', 'cached', 'snapshot' or 'none'."""
    def fmt(iso):
        try:
            return datetime.fromisoformat(iso).astimezone(ZoneInfo("America/New_York")).strftime("%b %d, %Y %I:%M %p %Z")
        except (TypeError, ValueError):
            return "unknown"

    mode = status.get("mode", "none")
    if mode == "live":
        age_h = None
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(status["last_success"])).total_seconds() / 3600
        except (KeyError, ValueError):
            pass
        stale = f" (data is {age_h:.0f} hours old)" if age_h and age_h > 26 else ""
        part = status.get("partial") or {}
        partial = (f" · partial: {len(part.get('failed_searches') or [])} search(es) failed, "
                   f"{part.get('carried_over', 0)} earlier notices kept") if part.get("failed_searches") else ""
        return "live", f"LIVE Grants.gov data · last successful refresh {fmt(status.get('last_success'))}{stale}{partial}"
    if mode == "cached":
        return "cached", (f"CACHED data from {fmt(status.get('last_success'))}. The last refresh attempt "
                          f"({fmt(status.get('last_attempt'))}) failed: {status.get('last_error', '')[:160]}")
    if mode == "snapshot":
        return "snapshot", f"SNAPSHOT replay (not live) of a pull from {fmt(status.get('pulled_at'))}"
    return "none", "No data yet. Click 'Refresh from Grants.gov' or run the refresh job."
