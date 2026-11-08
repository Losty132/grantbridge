"""Refresh pipeline: Grants.gov → normalize → dedupe → registry (first-seen/last-modified) → embeddings → storage.

    python -m data_retrieval.refresh                    # full live refresh (scheduled job uses this)
    python -m data_retrieval.refresh --quick            # smaller pull (used by the in-app Refresh button)
    python -m data_retrieval.refresh --snapshot FILE    # replay a saved raw pull (labeled 'snapshot', not live)

On any API failure the previous dataset is kept and labeled CACHED, and the error is logged.
Exit code is non-zero on failure so an Azure Container Apps Job run shows as Failed.
"""
import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from agency_profiles import loader
from common import config
from common.ai import AI, embed_with_cache
from common.storage import Storage
from data_retrieval import grants_client
from data_retrieval.normalize import today, normalize_one, trim_detail

log = logging.getLogger("refresh")
DATASET = "opportunities/latest.json"
STATUS = "opportunities/status.json"
REGISTRY = "opportunities/registry.json"
DETAILS = "cache/details.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hit_signature(h: dict) -> str:
    """What the search listing says about a notice. If any of it changes, the full details are fetched again."""
    return "|".join(str(h.get(k) or "") for k in ("title", "closeDate", "oppStatus", "openDate", "docType"))


def details_to_fetch(hits: dict, cache: dict) -> list[str]:
    """New notices first, then ones whose listing changed (amended deadline, forecast → posted), then any detail
    older than DETAIL_MAX_AGE_DAYS (catches amendments that don't show in the listing, e.g. award amounts)."""
    now = datetime.now(timezone.utc)
    new, changed, old = [], [], []
    for oid, h in hits.items():
        c = cache.get(oid)
        if c is None:
            new.append(oid)
        elif c.get("_sig") != hit_signature(h):
            changed.append(oid)
        else:
            try:
                age = (now - datetime.fromisoformat(c["_fetched"])).days
            except (KeyError, TypeError, ValueError):
                age = 10_000
            if age >= config.DETAIL_MAX_AGE_DAYS:
                old.append((age, oid))
    return new + changed + [oid for _, oid in sorted(old, reverse=True)]


def pull(storage, profiles: dict, quick: bool, errors: list) -> dict:
    hits: dict[str, dict] = {}
    queries = []
    failed: set[str] = set()
    streak = 0
    broad_cap = 300 if quick else config.BROAD_PULL_CAP
    kw_cap = 50 if quick else config.KEYWORD_PULL_CAP

    def add(page, tag):
        for h in page:
            hid = str(h.get("id") or "")
            if hid:
                rec = hits.setdefault(hid, dict(h, found_by=[]))
                if tag not in rec["found_by"]:
                    rec["found_by"].append(tag)

    jobs = [("broad", "", e) for e in config.BROAD_ELIGIBILITIES]
    # one search per distinct term (33 agencies share many terms); results are tagged with every agency that uses it
    by_term: dict[str, list[str]] = {}
    for aid, p in profiles.items():
        for t in p.get("search_terms", []):
            by_term.setdefault(t.strip().lower(), []).append(aid)
    jobs += [("kw:" + ",".join(aids), t, "") for t, aids in by_term.items()]
    for tag, kw, elig in jobs:
        try:
            page, total = grants_client.search_all(keyword=kw, cap=kw_cap if kw else broad_cap, eligibilities=elig)
            add(page, tag)
            queries.append({"tag": tag, "keyword": kw, "eligibility": elig, "hitCount": total, "pulled": len(page)})
            streak = 0
        except Exception as e:
            errors.append(f"search {tag} '{kw or elig}': {e}")
            failed.add(tag)
            streak += 1
            if streak >= 4:
                raise RuntimeError("Grants.gov unreachable (4 failed searches in a row): " + str(e))
    if not hits:
        raise RuntimeError("Grants.gov returned no opportunities")

    cache = storage.read_json(DETAILS, default={}) or {}
    todo = details_to_fetch(hits, cache)[: config.DETAIL_FETCH_CAP]
    with ThreadPoolExecutor(max_workers=config.FETCH_WORKERS) as pool:
        futs = {pool.submit(grants_client.fetch_opportunity, i): i for i in todo}
        for f in as_completed(futs):
            oid = futs[f]
            try:
                cache[oid] = dict(trim_detail(f.result()), _fetched=_now(), _sig=hit_signature(hits[oid]))
            except Exception as e:  # keep the older copy if there is one; it is still better than nothing
                errors.append(f"detail {oid}: {e}")
    cache = {k: v for k, v in cache.items() if k in hits}
    storage.write_json(DETAILS, cache)
    return {"source": "grants.gov live API", "pulled_at": _now(), "queries": queries, "failed_searches": sorted(failed),
            "hits": list(hits.values()), "details": cache}


def build_records(raw: dict, storage) -> list[dict]:
    details = raw.get("details") or {}
    by_id = {}
    for h in raw.get("hits", []):
        r = normalize_one(h, details.get(str(h.get("id"))))
        by_id[r["id"]] = r
    by_number = {}
    for r in by_id.values():  # de-duplicate by opportunity number too (keeps the richer record)
        key = r["number"] or r["id"]
        prev = by_number.get(key)
        if not prev or len(r["description"]) > len(prev["description"]):
            if prev:
                r["found_by"] = sorted(set(prev["found_by"]) | set(r["found_by"]))
            by_number[key] = r
    records = list(by_number.values())

    reg = storage.read_json(REGISTRY, default={}) or {}
    now = _now()
    for r in records:
        e = reg.get(r["id"])
        if not e:
            e = reg[r["id"]] = {"first_seen": now, "last_modified": now, "hash": r["content_hash"]}
        elif e.get("hash") != r["content_hash"]:
            e.update(last_modified=now, hash=r["content_hash"])
        e["last_seen"] = now
        r.update(first_seen=e["first_seen"], last_seen=now, last_modified=e["last_modified"])
    storage.write_json(REGISTRY, reg)
    return records


def embed_all(ai: AI, storage, records: list[dict], profiles: dict, errors: list) -> bool:
    if not ai.available:
        return False
    try:
        embed_with_cache(ai, storage, {r["id"]: f"{r['title']}. {r['title']}. {r['description'][:3000]}"
                                       for r in records}, "cache/embeddings_opps.json")
        targets = {f"{aid}|{t['id']}": t["text"] for aid, p in profiles.items() for t in loader.match_targets(p)}
        embed_with_cache(ai, storage, targets, "cache/embeddings_targets.json")
        return True
    except Exception as e:
        errors.append(f"embeddings failed (similarity falls back to TF-IDF): {e}")
        return False


def carry_over_failed(storage, records: list[dict], failed: list[str]) -> int:
    """If some searches failed, the notices only THEY used to find would silently disappear. Keep those from the
    previous dataset (unless closed) so a hiccup never drops an agency's grants; the status is labeled partial."""
    if not failed:
        return 0
    prev = (storage.read_json(DATASET, default={}) or {}).get("items") or []
    have = {r["id"] for r in records}
    today_iso = today().isoformat()
    kept = 0
    for r in prev:
        if r["id"] in have or not set(r.get("found_by") or []) & set(failed):
            continue
        if r.get("close_date") and r["close_date"] < today_iso:
            continue
        records.append(dict(r, carried_over=True))
        kept += 1
    return kept


def run(storage=None, ai=None, snapshot_file: str | None = None, quick: bool = False) -> dict:
    t0 = time.time()
    storage = storage or Storage()
    ai = ai or AI()
    profiles = loader.load_all()
    prev = storage.read_json(STATUS, default={}) or {}
    errors: list[str] = []
    attempt = _now()
    try:
        if snapshot_file:
            with open(snapshot_file, encoding="utf-8") as f:
                raw = json.load(f)
            mode = "snapshot"
        else:
            raw = pull(storage, profiles, quick, errors)
            storage.write_json(f"raw/{attempt[:10]}/grants.json", raw)
            mode = "live"
        records = build_records(raw, storage)
        carried = carry_over_failed(storage, records, raw.get("failed_searches") or [])
        embedded = embed_all(ai, storage, records, profiles, errors)
        storage.write_json(DATASET, {"generated_at": attempt, "pulled_at": raw.get("pulled_at"), "mode": mode,
                                     "source": raw.get("source", ""), "count": len(records), "items": records})
        precomputed = {}
        if not quick:  # prepare the top results (NOFO + explanations) so the app only reads them
            try:
                from data_retrieval.normalize import refresh_days_left
                from scoring.enrich import precompute

                precomputed = precompute(storage, ai, refresh_days_left(records), attempt, errors)
            except Exception as e:
                errors.append(f"precompute skipped: {e}")
        status = {"mode": mode, "last_success": attempt, "last_attempt": attempt, "pulled_at": raw.get("pulled_at"),
                  "precomputed": precomputed,
                  "count": len(records), "open": sum(r["status"] == "open" for r in records),
                  "forecasted": sum(r["status"] == "forecasted" for r in records), "embeddings": embedded,
                  "partial": {"failed_searches": raw.get("failed_searches"), "carried_over": carried}
                  if raw.get("failed_searches") else None,
                  "errors": errors[:25], "duration_sec": round(time.time() - t0, 1), "quick": quick}
        try:  # stretch goal 2: "closes in N days" messages to Teams / Slack (only when ALERT_WEBHOOK_URL is set)
            from alerts.deadlines import notify
            from data_retrieval.normalize import refresh_days_left as _rdl
            from feedback import store as _fb
            status["alerts"] = notify(storage, _rdl(records), profiles, lambda aid: _fb.reviews(storage, aid))
        except Exception as e:
            errors.append(f"alerts skipped: {type(e).__name__}")
        storage.write_json(STATUS, status)
        storage.write_json(f"runs/{attempt.replace(':', '')}.json", status)
        return status
    except Exception as e:
        log.exception("Refresh failed; keeping cached data")
        status = dict(prev, mode="cached" if prev.get("last_success") else "none", last_attempt=attempt,
                      last_error=str(e)[:500], errors=(errors + [str(e)])[:25])
        storage.write_json(STATUS, status)
        storage.write_json(f"runs/{attempt.replace(':', '')}_FAILED.json", status)
        raise


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", help="replay a saved raw pull file (labeled 'snapshot')")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    try:
        s = run(snapshot_file=a.snapshot, quick=a.quick)
        log.info("Refresh OK: %s records (%s open, %s forecasted), %s errors", s["count"], s["open"],
                 s["forecasted"], len(s["errors"]))
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
