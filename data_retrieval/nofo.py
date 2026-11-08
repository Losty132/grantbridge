"""Best-effort download + text extraction of the full Notice of Funding Opportunity (NOFO) PDF attached
to a listing. Used only for the top results, to find application-effort drivers (page limits, letters, match).
Results are cached in storage; failures are recorded and the app falls back to the synopsis text."""
import io
import logging
import re
from datetime import datetime, timezone

from common import config
from data_retrieval import grants_client

log = logging.getLogger(__name__)
PREFER = re.compile(r"nofo|announcement|funding|solicitation|program|rfa|notice", re.I)


def pick_attachment(atts: list[dict]) -> dict | None:
    pdfs = [a for a in atts or [] if (a.get("mime") or "").endswith("pdf") or (a.get("name") or "").lower().endswith(".pdf")]
    if not pdfs:
        return None
    pdfs.sort(key=lambda a: (not PREFER.search(a.get("name") or ""), len(a.get("name") or "")))
    return pdfs[0]


def get_nofo_text(storage, record: dict) -> dict:
    """Returns {"text", "source", "error"}; text is '' when unavailable."""
    path = f"nofo/{record['id']}.json"
    att = pick_attachment(record.get("attachments"))
    cached = storage.read_json(path)
    # a cached extract is only reused while it came from the SAME attachment (an amended NOFO gets a new one)
    if cached is not None and str(cached.get("attachment_id")) != str((att or {}).get("id")):
        cached = None
    if cached is not None:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"])).total_seconds() / 3600
        except (KeyError, ValueError):
            age_h = 999
        if not cached.get("error") or age_h < 12:  # retry failed downloads after 12 hours
            return cached
    out = {"text": "", "source": "", "error": "", "fetched_at": datetime.now(timezone.utc).isoformat(),
           "attachment_id": (att or {}).get("id")}
    if not config.NOFO_FETCH:
        out["error"] = "NOFO download disabled"
    elif not att:
        out["error"] = "No PDF attachment listed on Grants.gov"
    else:
        try:
            from pypdf import PdfReader

            data = grants_client.download_attachment(att["id"])
            reader = PdfReader(io.BytesIO(data))
            pages = []
            for i, p in enumerate(reader.pages[:80], 1):
                pages.append(f"[page {i}] " + (p.extract_text() or ""))
            out["text"] = re.sub(r"[ \t]+", " ", "\n".join(pages))[:250_000]
            out["source"] = f"{att.get('name')} (Grants.gov attachment {att.get('id')})"
        except Exception as e:
            out["error"] = f"Could not read NOFO PDF: {e}"[:300]
    storage.write_json(path, out)
    return out
