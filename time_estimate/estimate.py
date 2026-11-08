"""Application time estimate: find effort drivers in the notice (each with a verbatim quote), convert them to
points with transparent rules, and compare against days remaining. Missing information → 'Unknown', never 'Low'.
Always labeled: 'Estimate — based on notice requirements'."""
import re

from common.text import quote_in_source, sentences

LABEL = "Estimate — based on notice requirements"
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

DRIVERS = {
    "loi": ("Pre-application / letter of intent", 2,
            re.compile(r"letter of intent|pre-?application|concept paper|\bLOI\b|white paper|pre-?proposal", re.I)),
    "narrative": ("Narrative page limit", 0,
                  re.compile(r"(narrative|project description|technical proposal|proposal)[^.]{0,80}?(\d{1,3})[\s-]*pages?"
                             r"|(\d{1,3})[\s-]*pages?[^.]{0,40}(narrative|project description)", re.I)),
    "budget": ("Budget + justification", 1,
               re.compile(r"budget (justification|narrative)|justify (all )?(the )?(items and )?(proposed )?costs|"
                          r"detailed budget|sf-?424a", re.I)),
    "cost_share": ("Cost-share documentation", 2,
                   re.compile(r"cost[- ]?shar(e|ing) (is )?required|matching (funds|requirement|basis)|non-federal "
                              r"share|1:1 match|\bmatch of\b|(\d{1,3})\s?(%|percent) (cost share|match)", re.I)),
    "letters": ("Letters of support / partners", 1,
                re.compile(r"letters? of (support|commitment)|memorand(um|a) of understanding|partner(ship)? "
                           r"(is |are )?required|must partner|consortium", re.I)),
    "evaluation": ("Evaluation plan / logic model / data requirements", 2,
                   re.compile(r"evaluation plan|logic model|performance measures|data management plan|"
                              r"monitoring and evaluation|performance measurement", re.I)),
    "registrations": ("Registrations (SAM.gov, UEI, Grants.gov)", 1,
                      re.compile(r"SAM\.gov|unique entity identifier|\bUEI\b|Grants\.gov (registration|workspace)", re.I)),
    "multistage": ("Multi-stage review", 2,
                   re.compile(r"two[- ]stage|multi-?stage|invited to submit (a )?full|full (proposals?|applications?) "
                              r"(will be )?invited|phase (i|1)[^.]{0,60}phase (ii|2)", re.I)),
}
NEGATION = re.compile(r"\b(not|no|without|does not have)\b[^.]{0,30}(required|requirement|match|cost)", re.I)
BANDS = [("Low", 0, 3, (1, 2), (20, 60)), ("Medium", 4, 7, (3, 5), (60, 160)), ("High", 8, 99, (6, 10), (160, 320))]


def _source_sentences(record: dict, nofo_text: str = "") -> list[tuple[str, str]]:
    out = [(s, "Grants.gov synopsis") for s in sentences(record.get("description", ""))]
    out += [(s, "Grants.gov eligibility text") for s in sentences(record.get("eligibility_text", ""))]
    out += [(e["text"], f"NOFO p. {e.get('page', '?')} (excerpt; verify)") for e in record.get("nofo_excerpts") or []]
    page = None
    for s in sentences(nofo_text):
        m = re.search(r"\[page (\d+)\]", s)
        if m:
            page = m.group(1)
        out.append((re.sub(r"\[page \d+\]\s*", "", s), f"NOFO PDF p. {page}" if page else "NOFO PDF"))
    return out


NEAR_NEGATION = re.compile(r"\b(?:not|no|isn't|aren't|never)\b[^.;:]{0,25}\b(?:required|needed|necessary|mandatory|requested)\b|"
                           r"\boptional\b|\bnot (?:be )?(?:required|needed|necessary)|\bwaived\b|\bis not a requirement", re.I)


def negated(sent: str, m: re.Match) -> bool:
    """'A letter of intent is NOT required' must not count as effort. Looks just around the matched requirement."""
    # only the clause that holds the requirement ("…are optional; a 20-page narrative is required" has two clauses)
    start = max(sent.rfind(";", 0, m.start()), sent.rfind(":", 0, m.start())) + 1
    ends = [i for i in (sent.find(";", m.end()), sent.find(":", m.end())) if i != -1]
    clause = sent[max(start, m.start() - 25): min(ends) if ends else m.end() + 45]
    return bool(NEAR_NEGATION.search(clause))


def _narrative_points(n: int) -> int:
    return 3 if n >= 20 else 2 if n >= 11 else 1


def find_drivers(record: dict, nofo_text: str = "") -> list[dict]:
    found: dict[str, dict] = {}
    for sent, src in _source_sentences(record, nofo_text):
        for key, (label, pts, rx) in DRIVERS.items():
            if key in found:
                continue
            m = rx.search(sent)
            if not m:
                continue
            if (key == "cost_share" and NEGATION.search(sent)) or negated(sent, m):
                continue
            detail, points = label, pts
            if key == "narrative":
                n = next((int(g) for g in m.groups() if g and g.isdigit()), None)
                if not n or n > 200:
                    continue
                detail, points = f"{n}-page narrative", _narrative_points(n)
            elif key == "letters":
                c = re.search(r"(\d+|one|two|three|four|five|six)\s+letters?", sent, re.I)
                cnt = int(c.group(1)) if c and c.group(1).isdigit() else NUM_WORDS.get((c.group(1) if c else "").lower())
                if cnt:
                    detail, points = f"{cnt} letters of support", min(3, cnt)
            elif key == "cost_share":
                pct = re.search(r"(\d{1,3})\s?(%|percent)", sent)
                if pct:
                    detail = f"{pct.group(1)}% match"
                elif "1:1" in sent:
                    detail = "1:1 match"
            found[key] = {"key": key, "label": label, "detail": detail, "points": points,
                          "quote": sent.strip()[:400], "source": src}
    if record.get("cost_sharing") is True and "cost_share" not in found:
        found["cost_share"] = {"key": "cost_share", "label": DRIVERS["cost_share"][0], "detail": "Match required",
                               "points": 2, "quote": "Cost sharing or matching requirement: Yes",
                               "source": "Grants.gov cost sharing field"}
    return sorted(found.values(), key=lambda d: -d["points"])


def merge_ai_drivers(rule_drivers: list[dict], ai_drivers: list[dict], source_text: str) -> tuple[list[dict], int]:
    """Add AI-found drivers only when their quote is verifiably in the source text. Returns (drivers, rejected)."""
    have = {d["key"] for d in rule_drivers}
    out, rejected = list(rule_drivers), 0
    for d in ai_drivers or []:
        key = str(d.get("driver_key", "")).strip()
        quote = str(d.get("quote", ""))
        if key not in DRIVERS or key in have:
            continue
        if not quote_in_source(quote, source_text):
            rejected += 1
            continue
        pts = DRIVERS[key][1] or 2
        out.append({"key": key, "label": DRIVERS[key][0], "detail": str(d.get("detail", ""))[:120] or DRIVERS[key][0],
                    "points": pts, "quote": quote[:400], "source": "AI-extracted, quote verified in notice"})
        have.add(key)
    return sorted(out, key=lambda d: -d["points"]), rejected


def estimate(record: dict, nofo_text: str = "", drivers: list[dict] | None = None) -> dict:
    drivers = find_drivers(record, nofo_text) if drivers is None else drivers
    basis = "full NOFO PDF + synopsis" if nofo_text else (
        "synopsis + NOFO excerpts" if record.get("nofo_excerpts") else "synopsis only")
    if not drivers:
        return {"label": LABEL, "level": "Unknown", "points": None, "weeks": None, "staff_hours": None,
                "drivers": [], "top_drivers": [], "basis": basis,
                "summary": "Unknown — check notice (no effort drivers found in the text available)"}
    pts = sum(d["points"] for d in drivers)
    level, _, _, weeks, hours = next(b for b in BANDS if b[1] <= pts <= b[2])
    top = drivers[:3]
    why = ", ".join(d["detail"] for d in top)
    note = "" if nofo_text else " The full NOFO was not parsed, so the effort may be higher."
    return {"label": LABEL, "level": level, "points": pts, "weeks": weeks, "staff_hours": hours,
            "drivers": drivers, "top_drivers": top, "basis": basis,
            "summary": f"{level}: about {weeks[0]}–{weeks[1]} weeks ({hours[0]}–{hours[1]} staff hours). "
                       f"Takes longer because: {why}.{note}"}


def feasibility(days_left: int | None, prep_days: int, est: dict) -> dict:
    if days_left is None:
        return {"status": "unknown", "icon": "❔", "text": "No deadline listed. Check the notice", "need_days": None}
    need = prep_days
    if est.get("weeks"):
        need = max(prep_days, est["weeks"][1] * 7)
    suffix = "" if est.get("weeks") else " (effort unknown; compared with your prep time only)"
    if days_left >= need:
        return {"status": "feasible", "icon": "✅", "text": f"Feasible: {days_left} days left, ~{need} needed{suffix}",
                "need_days": need}
    if days_left >= 0.6 * need:
        return {"status": "tight", "icon": "⚠️", "text": f"Tight: {days_left} days left, ~{need} needed{suffix}",
                "need_days": need}
    return {"status": "not_enough", "icon": "❌", "text": f"Not enough time: {days_left} days left, ~{need} needed{suffix}",
            "need_days": need}
