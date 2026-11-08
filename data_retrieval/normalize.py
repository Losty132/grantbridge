"""Turn Grants.gov search hits + fetchOpportunity details into one clean record per opportunity."""
import os
from zoneinfo import ZoneInfo
import hashlib
import re
from datetime import date, datetime, timezone

from dateutil import parser as dateparser

from common.text import strip_html

ELIGIBILITY_LABELS = {
    "00": "State governments", "01": "County governments", "02": "City or township governments",
    "04": "Special district governments", "05": "Independent school districts",
    "06": "Public and State controlled institutions of higher education",
    "07": "Native American tribal governments (Federally recognized)",
    "08": "Public and Indian housing authorities", "11": "Native American tribal organizations (other than Federally recognized)",
    "12": "Nonprofits with 501(c)(3) status (other than institutions of higher education)",
    "13": "Nonprofits without 501(c)(3) status (other than institutions of higher education)",
    "20": "Private institutions of higher education", "21": "Individuals", "22": "For profit organizations other than small businesses",
    "23": "Small businesses", "25": "Others (see text field entitled \"Additional Information on Eligibility\")",
    "99": "Unrestricted (i.e., open to any type of entity)",
}


APP_TZ = ZoneInfo(os.getenv("APP_TZ", "America/New_York"))


def today() -> date:
    """Today in North Carolina. (UTC would roll over at 7-8 PM Eastern and mark grants closing today as expired.)"""
    return datetime.now(APP_TZ).date()


def parse_date(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(v / 1000, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    s = re.sub(r"\s+(EST|EDT|CST|CDT|MST|MDT|PST|PDT|ET)$", "", str(v).strip())
    try:
        return dateparser.parse(s, fuzzy=True).date()
    except (ValueError, OverflowError, TypeError):
        return None


def parse_money(v) -> float | None:
    if v in (None, "", "none", "None"):
        return None
    try:
        x = float(str(v).replace("$", "").replace(",", "").strip())
        return x if x > 0 else None
    except ValueError:
        return None


def _bool(v):
    """True / False only for explicit values; anything else ("unknown", "see NOFO", odd types) stays unknown (None),
    so it gets partial 'not stated' credit instead of the full 'no cost share required' points."""
    if isinstance(v, bool):
        return v
    t = str(v).strip().lower() if v is not None else ""
    if t in ("true", "y", "yes", "1"):
        return True
    if t in ("false", "n", "no", "0"):
        return False
    return None


def trim_detail(d: dict) -> dict:
    """Keep only the detail fields we use (keeps the cache small)."""
    syn, fc = d.get("synopsis") or {}, d.get("forecast") or {}
    keys = ("synopsisDesc", "forecastDesc", "awardCeiling", "awardFloor", "estimatedFunding", "numberOfAwards",
            "expectedNumberOfAwards", "costSharing", "applicantTypes", "applicantEligibilityDesc",
            "fundingActivityCategories", "responseDate", "responseDateStr", "responseDateDesc", "postingDate",
            "archiveDate", "estApplicationResponseDate", "estApplicationResponseDateStr", "agencyName",
            "fundingDescLinkUrl", "lastUpdatedDate")
    atts = []
    for folder in d.get("synopsisAttachmentFolders") or []:
        for a in folder.get("synopsisAttachments") or []:
            atts.append({"id": a.get("id"), "name": a.get("fileName"), "mime": a.get("mimeType"),
                         "description": a.get("fileDescription"), "folder": folder.get("folderName")})
    return {
        "id": str(d.get("id", "")), "opportunityNumber": d.get("opportunityNumber"),
        "opportunityTitle": d.get("opportunityTitle"), "docType": d.get("docType"),
        "owningAgencyCode": d.get("owningAgencyCode"),
        "agencyName": (d.get("agencyDetails") or {}).get("agencyName"),
        "alns": [a.get("alnNumber") for a in d.get("alns") or []],
        "synopsis": {k: syn.get(k) for k in keys if syn.get(k) not in (None, "", [])},
        "forecast": {k: fc.get(k) for k in keys if fc.get(k) not in (None, "", [])},
        "attachments": atts,
    }


def normalize_one(hit: dict, detail: dict | None, now: date | None = None) -> dict:
    now = now or today()
    detail = detail or {}
    syn, fc = detail.get("synopsis") or {}, detail.get("forecast") or {}
    src = syn or fc
    api_status = (hit.get("oppStatus") or detail.get("docType") or "").lower()
    is_forecast = api_status == "forecasted" or (not syn and bool(fc))

    close = parse_date(hit.get("closeDate"))
    close_src = "Grants.gov close date" if close else ""
    if not close:
        for k in ("responseDate", "responseDateStr"):
            close = close or parse_date(syn.get(k))
        close_src = "Grants.gov response date" if close else ""
    if not close and fc:
        close = parse_date(fc.get("estApplicationResponseDate")) or parse_date(fc.get("estApplicationResponseDateStr"))
        close_src = "Forecast: estimated due date" if close else ""
    archive = parse_date(syn.get("archiveDate") or fc.get("archiveDate"))

    if api_status in ("closed", "archived") or (close and close < now):
        status = "expired"
    elif is_forecast:
        status = "forecasted"
    else:
        status = "open"

    codes, labels = [], []
    for a in src.get("applicantTypes") or []:
        if isinstance(a, dict):
            c = str(a.get("id", "")).strip()
            codes.append(c)
            labels.append(a.get("description") or ELIGIBILITY_LABELS.get(c, c))
    description = strip_html(syn.get("synopsisDesc") or fc.get("forecastDesc") or "")
    record = {
        "id": str(hit.get("id") or detail.get("id")),
        "number": hit.get("number") or detail.get("opportunityNumber") or "",
        "title": strip_html(hit.get("title") or detail.get("opportunityTitle") or ""),
        "agency": hit.get("agencyName") or src.get("agencyName") or detail.get("agencyName") or hit.get("agencyCode") or "",
        "agency_code": hit.get("agencyCode") or detail.get("owningAgencyCode") or "",
        "status": status, "api_status": api_status or None,
        "open_date": (parse_date(hit.get("openDate")) or parse_date(src.get("postingDate")) or None),
        "close_date": close, "close_date_source": close_src or None, "archive_date": archive,
        "days_left": (close - now).days if close else None,
        "award_floor": parse_money(src.get("awardFloor")), "award_ceiling": parse_money(src.get("awardCeiling")),
        "total_funding": parse_money(src.get("estimatedFunding")),
        "expected_awards": src.get("numberOfAwards") or src.get("expectedNumberOfAwards"),
        "cost_sharing": _bool(src.get("costSharing")),
        "eligibility_codes": codes, "eligibility_labels": labels,
        "eligibility_text": strip_html(src.get("applicantEligibilityDesc") or "")[:3000],
        "description": description[:8000],
        "categories": [c.get("description") for c in src.get("fundingActivityCategories") or [] if isinstance(c, dict)],
        "aln": hit.get("alnist") or detail.get("alns") or [],
        "url": f"https://www.grants.gov/search-results-detail/{hit.get('id') or detail.get('id')}",
        "attachments": detail.get("attachments") or [],
        "found_by": hit.get("found_by", []),
        "details_fetched": bool(detail),
    }
    for k in ("open_date", "close_date", "archive_date"):
        record[k] = record[k].isoformat() if record[k] else None
    record["content_hash"] = hashlib.sha1(
        (record["title"] + record["description"] + str(record["close_date"]) + str(record["award_ceiling"])
         + record["eligibility_text"]).encode()).hexdigest()[:16]
    return record


def refresh_days_left(records: list[dict], now: date | None = None) -> list[dict]:
    """Recompute days_left/status at display time so cached data never shows a stale 'open'."""
    now = now or today()
    for r in records:
        c = parse_date(r.get("close_date"))
        r["days_left"] = (c - now).days if c else None
        if c and c < now:
            r["status"] = "expired"
    return records
