"""'Why it matches' explanations: AI (structured JSON, verified against sources) with a rules fallback.

AI output contract: {matched_objective, objective_citation, grant_evidence_quote, reasons[], confidence,
                     effort_drivers[{driver_key, detail, quote}]}
Verification: the objective must exist in the profile; the evidence quote must appear in the notice text.
Anything that fails is replaced with the rules result and the confidence drops to 'low' (→ 'Needs review')."""
import json
import re
import logging

from common.ai import text_hash
from common.text import TfIdf, quote_in_source, sentences, sparse_cosine
from privacy.filter import scan
from time_estimate.estimate import DRIVERS

log = logging.getLogger(__name__)

SYSTEM = """You help North Carolina state grant staff decide which federal opportunities fit their agency.
Compare the funding notice with EACH listed agency objective and pick the single best match.
Return a JSON object with exactly these keys:
  "matched_objective": the id of the best objective from the list (copy it exactly),
  "objective_citation": the citation string given for that objective,
  "grant_evidence_quote": one sentence copied word-for-word from the notice that shows the connection,
  "reasons": 2-4 short plain-English reasons (no jargon),
  "confidence": "high", "medium" or "low",
  "effort_drivers": list of {"driver_key", "detail", "quote"} for application requirements you can quote word-for-word
      from the notice. driver_key must be one of: """ + ", ".join(DRIVERS) + """.
Rules: use only the provided text; never invent dollar amounts, dates, eligibility or requirements; if the fit is
weak or unclear say so and use "low" confidence. Eligibility is decided elsewhere; do not claim it."""


def notice_text(record: dict, nofo_text: str = "") -> str:
    parts = [record.get("title", ""), record.get("description", ""), record.get("eligibility_text", "")]
    parts += [e["text"] for e in record.get("nofo_excerpts") or []]
    if nofo_text:
        parts.append(nofo_text[:12000])
    return "\n".join(p for p in parts if p)


def rule_explanation(result: dict, nofo_text: str = "") -> dict:
    rec, t = result["record"], result["matched_target"]
    sents = sentences(rec.get("description", "")) or [rec.get("title", "")]
    sents += [e["text"] for e in rec.get("nofo_excerpts") or []]
    tf = TfIdf(sents + [t["text"]])
    tv = tf.vector(t["text"])
    quote = max(sents, key=lambda s: sparse_cosine(tf.vector(s), tv)) if sents else ""
    c = t["citation"]
    reasons = [f"Closest match to {t['label'][:140].rstrip('.')}.",
               result["components"]["applicant_fit"]["why"],
               result["components"]["deadline_feasibility"]["why"]]
    if result["keyword_hits"]:
        reasons.insert(1, "Shares program terms: " + ", ".join(result["keyword_hits"][:5]) + ".")
    prog = result.get("matched_program")
    if prog and (result.get("program_alignment") or 0) >= 0.5:
        reasons.insert(1, f"Related agency program: {prog['label']}.")
    return {"matched_objective": t["id"], "matched_label": t["label"],
            "objective_citation": f"{c.get('document', '')}, {c.get('section', '')}".strip(", "),
            "objective_url": c.get("url", ""), "grant_evidence_quote": quote, "reasons": reasons[:4],
            "confidence": result["rule_confidence"], "source": "rules + similarity (no AI)",
            "verification": {"objective_valid": True, "quote_verified": bool(quote), "notes": []},
            "effort_drivers": []}


EXPLAIN_VERSION = "v4"
# numbers in a reason ($ amounts, percentages, years, counts) must appear in the notice, or the reason is dropped
NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|million|billion|thousand|[kKmM]\b)?")


def grounded(reason: str, source: str) -> bool:
    src = re.sub(r"[\s,$]", "", source.lower())
    for m in NUMBER.finditer(reason):
        digits = re.sub(r"[^\d.]", "", m.group(0))
        if digits and digits.strip(".") and digits.strip(".") not in src:
            return False
    return True


def ai_explanation(ai, storage, profile: dict, targets: list[dict], result: dict, nofo_text: str = "") -> dict:
    """Returns a verified explanation; falls back to rules on any failure."""
    fallback = rule_explanation(result, nofo_text)
    if ai is None or not ai.available:
        return fallback
    rec = result["record"]
    text = notice_text(rec, nofo_text)
    key = text_hash(text + json.dumps([t["id"] + str(t["selected"]) + t["text"] for t in targets]))
    # EXPLAIN_VERSION is part of the key: explanations saved under older checking rules are regenerated, not reused
    path = f"explanations/{EXPLAIN_VERSION}/{profile['agency_id']}/{rec['id']}_{key}.json"
    cached = storage.read_json(path) if storage else None
    if cached:
        return cached
    objectives = "\n".join(f"- id: {t['id']} | {t['label'][:300]} | citation: "
                           f"{t['citation'].get('document', '')}, {t['citation'].get('section', '')}" for t in targets)
    # user-typed priority text is privacy-filtered before it reaches the model
    objectives = scan(objectives).text
    user = f"AGENCY: {profile['name']}\nOBJECTIVES:\n{objectives}\n\n<document>\n{text[:15000]}\n</document>"
    try:
        out = ai.chat_json(SYSTEM, user)
        if not isinstance(out, dict):
            raise ValueError("response was not a JSON object")
        for k, kind in (("matched_objective", str), ("grant_evidence_quote", str), ("confidence", str),
                        ("reasons", list), ("effort_drivers", list)):
            if out.get(k) is not None and not isinstance(out[k], kind):
                raise ValueError(f"'{k}' has the wrong type")
    except Exception as e:
        fallback["verification"]["notes"].append(f"AI unavailable or malformed, rules used: {str(e)[:120]}")
        return fallback
    by_id = {t["id"]: t for t in targets}
    notes = []
    obj = str(out.get("matched_objective", "")).strip()
    obj_ok = obj in by_id
    if not obj_ok:
        notes.append(f"AI named an objective that is not in the profile ('{obj[:40]}'); replaced with the rules match.")
        obj = fallback["matched_objective"]
    quote = str(out.get("grant_evidence_quote", "")).strip()
    quote_ok = quote_in_source(quote, text)
    if not quote_ok:
        notes.append("AI evidence quote was not found word-for-word in the notice; replaced with a verified sentence.")
        quote = fallback["grant_evidence_quote"]
    conf = str(out.get("confidence", "low")).lower()
    conf = {"med": "medium"}.get(conf, conf)
    if conf not in ("high", "medium", "low") or not (obj_ok and quote_ok):
        conf = "low"
    t = by_id[obj]
    c = t["citation"]
    if obj_ok and quote_ok:
        raw = [str(r)[:300] for r in (out.get("reasons") or []) if isinstance(r, str) and r.strip()][:4]
        known = text + " " + " ".join(f"{t['id']} {t['label']}" for t in targets)  # plan ids like DEQ-3.B are fine
        reasons = [r for r in raw if grounded(r, known)]
        if len(reasons) < len(raw):
            notes.append(f"{len(raw) - len(reasons)} AI reason(s) dropped: they cited numbers that are not in the notice.")
        reasons = reasons or fallback["reasons"]
    else:  # grounding failed: the AI's free-text reasons can't be trusted either, so use the rule-based ones
        reasons = fallback["reasons"]
        notes.append("AI reasons were discarded because its objective or quote could not be verified.")
    expl = {"matched_objective": obj, "matched_label": t["label"],
            "objective_citation": f"{c.get('document', '')}, {c.get('section', '')}".strip(", "),
            "objective_url": c.get("url", ""), "grant_evidence_quote": quote, "reasons": reasons,
            "confidence": conf, "source": "Azure OpenAI (verified against the notice and profile)",
            "verification": {"objective_valid": obj_ok, "quote_verified": quote_ok, "notes": notes},
            "effort_drivers": [d for d in (out.get("effort_drivers") or []) if isinstance(d, dict)]}
    if storage:
        storage.write_json(path, expl)
    return expl
