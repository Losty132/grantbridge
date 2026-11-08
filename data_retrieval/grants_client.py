"""Grants.gov REST client (public, no key): search2 and fetchOpportunity, with retries and paging.
Docs: https://www.grants.gov/api/common/search2 , https://www.grants.gov/api/common/fetchopportunity"""
import logging
import time

import requests

from common.text import safe_keyword

log = logging.getLogger(__name__)
SEARCH_URL = "https://api.grants.gov/v1/api/search2"
FETCH_URL = "https://api.grants.gov/v1/api/fetchOpportunity"
ATTACHMENT_URLS = ["https://apply07.grants.gov/grantsws/rest/opportunity/att/download/{id}",
                   "https://www.grants.gov/grantsws/rest/opportunity/att/download/{id}"]
UA = {"User-Agent": "federal-funds-matchmaker/2.0 (NC OSBM prototype)"}
PAGE = 250
VALID_STATUSES = {"posted", "forecasted", "closed", "archived"}


class GrantsApiError(RuntimeError):
    pass


def _post(url: str, body: dict, retries: int = 3, timeout: int = 45) -> dict:
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(url, json=body, timeout=timeout, headers={"Content-Type": "application/json", **UA})
            if r.status_code == 429 or r.status_code >= 500:
                raise GrantsApiError(f"HTTP {r.status_code}")
            r.raise_for_status()
            data = r.json()
            if str(data.get("errorcode", 0)) not in ("0", "None"):
                raise GrantsApiError(f"API error {data.get('errorcode')}: {data.get('msg')}")
            return data
        except (requests.RequestException, ValueError, GrantsApiError) as e:
            last = e
            time.sleep(2 ** attempt)
    raise GrantsApiError(f"Grants.gov unavailable after {retries} tries: {last}")


def search_page(keyword: str = "", statuses: str = "forecasted|posted", eligibilities: str = "",
                rows: int = PAGE, start: int = 0) -> tuple[list[dict], int]:
    statuses = "|".join(s for s in statuses.split("|") if s in VALID_STATUSES) or "forecasted|posted"
    body = {"rows": max(1, min(int(rows), PAGE)), "startRecordNum": max(0, int(start)), "oppStatuses": statuses,
            "keyword": safe_keyword(keyword)}
    if eligibilities and eligibilities.isdigit() and len(eligibilities) == 2:
        body["eligibilities"] = eligibilities
    data = _post(SEARCH_URL, body).get("data") or {}
    return data.get("oppHits") or [], int(data.get("hitCount") or 0)


def search_all(keyword: str = "", cap: int = 1000, **kw) -> tuple[list[dict], int]:
    hits, start, total = [], 0, 0
    while len(hits) < cap:
        page, total = search_page(keyword=keyword, start=start, rows=min(PAGE, cap - len(hits)), **kw)
        hits.extend(page)
        start += len(page)
        if not page or start >= total:
            break
    return hits, total


def fetch_opportunity(opp_id, retries: int = 3, timeout: int = 45) -> dict:
    oid = int(str(opp_id).strip())  # validates the id
    return _post(FETCH_URL, {"opportunityId": oid}, retries=retries, timeout=timeout).get("data") or {}


def download_attachment(att_id, max_bytes: int = 15_000_000) -> bytes:
    att = int(str(att_id).strip())
    last = None
    for tmpl in ATTACHMENT_URLS:
        try:
            r = requests.get(tmpl.format(id=att), timeout=60, headers=UA, stream=True)
            r.raise_for_status()
            data = r.raw.read(max_bytes + 1, decode_content=True)
            if len(data) > max_bytes:
                raise GrantsApiError("attachment too large")
            return data
        except Exception as e:
            last = e
    raise GrantsApiError(f"attachment {att} download failed: {last}")
