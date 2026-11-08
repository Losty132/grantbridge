"""Rule-based eligibility classification. AI is never used to decide eligibility.

Labels: Appears Eligible / Needs Human Verification / Partnership Opportunity / Not Eligible for Direct Application.
Every restriction and condition is cited to the notice text (or to the Grants.gov eligibility field)."""
import re

from common.text import sentences
from data_retrieval.normalize import ELIGIBILITY_LABELS

APPEARS = "Appears Eligible"
VERIFY = "Needs Human Verification"
PARTNER = "Partnership Opportunity"
NOT_ELIGIBLE = "Not Eligible for Direct Application"

STATE_OK = {"00", "99"}
PARTNER_CODES = {"01", "02", "04", "05", "06", "07", "08", "11", "12", "13", "20"}

RESTRICT = re.compile(r"\b(only|(?:limited|restricted) (?:exclusively |solely |strictly )?to|exclusively|solely|must be an?|not eligible|ineligible|is open to|are open to|"
                      r"eligible applicants? (are|is|include))\b", re.I)
OTHER_ENTITIES = re.compile(r"tribal|tribe|institutions? of higher education|universit|college|nonprofit|non-profit|"
                            r"local government|count(y|ies)|municipal|school district|individual|for-profit|"
                            r"small business|territor", re.I)
MENTIONS_STATE = re.compile(r"\bstates?\b|state agenc|state government", re.I)
# the notice text explicitly shuts states out, even if the Grants.gov field lists them
STATE_EXCLUDED = re.compile(r"\bstates?(?: governments?| agenc(?:y|ies))?\s+(?:are|is)\s+(?:not\s+eligible|ineligible|excluded|"
                            r"not permitted|prohibited)|"
                            r"\bstates?(?: governments?| agenc(?:y|ies))?\s+(?:may|can|will)\s*not\s+(?:apply|be eligible)|"
                            r"\b(?:not\s+eligible|ineligible)(?: applicants?)?\s*(?:include|are|:)\s*(?:[^.]{0,60}\b)?states?\b(?! and local)|"
                            r"\bexclud(?:es|ing)\s+states?\b", re.I)
MATCH = re.compile(r"cost[- ]?shar|matching (funds|requirement|basis|share)|\bmatch requirement|non-federal share|"
                   r"1:1 match|\bmatch of\b|\bmatching\b", re.I)
NO_MATCH = re.compile(r"(no|not have a|not require a?|without) (cost[- ]?shar|match)", re.I)
PARTNERSHIP = re.compile(r"partner|consorti|collaborat|letters? of (support|commitment)|memorand(um|a) of "
                         r"understanding|\bMOU\b|sub-?award", re.I)
OTHER = re.compile(r"pre-?application|letter of intent|\bLOI\b|concept paper|SAM\.gov|unique entity identifier|\bUEI\b|"
                   r"two[- ]stage|invited to submit|maintenance of effort|supplant|single point of contact|"
                   r"executive order 12372|indirect cost", re.I)


def _cite(text: str, source: str) -> dict:
    return {"quote": text.strip()[:400], "source": source}


def _sources(record: dict, extra_text: str = "") -> list[tuple[str, str]]:
    out = []
    for s in sentences(record.get("eligibility_text", "")):
        out.append((s, "Grants.gov: Additional Information on Eligibility"))
    for s in sentences(record.get("description", "")):
        out.append((s, "Grants.gov synopsis"))
    for ex in record.get("nofo_excerpts") or []:
        out.append((ex["text"], f"NOFO p. {ex.get('page', '?')} (excerpt; verify)"))
    for s in sentences(extra_text)[:3000]:
        m = re.search(r"\[page (\d+)\]", s)
        out.append((re.sub(r"\[page \d+\]\s*", "", s), f"NOFO PDF{' p. ' + m.group(1) if m else ''}"))
    return out


def classify(record: dict, extra_text: str = "", agency_codes: list[str] | None = None) -> dict:
    """agency_codes: the Grants.gov applicant types THIS agency can apply as (its profile's eligible_applicant_codes).
    Most agencies apply as State government (00); the UNC System and community colleges also apply as public
    institutions of higher education (06). '25' (Others, see text) and '99' (unrestricted) are handled separately."""
    own = ((set(agency_codes) - {"25"}) if agency_codes else set(STATE_OK)) | {"99"}
    own_is_state = own <= STATE_OK
    codes = set(record.get("eligibility_codes") or [])
    labels = record.get("eligibility_labels") or []
    field_cite = _cite("Eligible applicants: " + "; ".join(labels), "Grants.gov eligible applicant field") if labels else None
    srcs = _sources(record, extra_text)

    restrictions = [_cite(s, src) for s, src in srcs
                    if (RESTRICT.search(s) and OTHER_ENTITIES.search(s) and not MENTIONS_STATE.search(s))
                    or STATE_EXCLUDED.search(s)]
    matching = [_cite(s, src) for s, src in srcs if MATCH.search(s)]
    partnership = [_cite(s, src) for s, src in srcs if PARTNERSHIP.search(s)]
    other = [_cite(s, src) for s, src in srcs if OTHER.search(s)]
    if record.get("cost_sharing") is True:
        matching.insert(0, _cite("Cost sharing or matching requirement: Yes", "Grants.gov cost sharing field"))
    no_match = [_cite(s, src) for s, src in srcs if NO_MATCH.search(s)]
    if record.get("cost_sharing") is False:
        no_match.insert(0, _cite("Cost sharing or matching requirement: No", "Grants.gov cost sharing field"))

    reasons, questions = [], []
    if not codes:
        label = VERIFY
        reasons.append("Grants.gov does not list eligible applicant types for this notice.")
        questions.append("Who is eligible to apply? Check the full notice.")
    elif codes & own:
        who = "State governments" if codes & own <= STATE_OK else \
            "; ".join(ELIGIBILITY_LABELS.get(c, c) for c in sorted(codes & own))
        if restrictions and (own_is_state or codes & own <= STATE_OK):
            label = VERIFY
            reasons.append(f"{who} are listed, but the notice text contains a restriction that may exclude "
                           "some agencies (see citations).")
            questions.append("Does the restriction in the notice exclude this agency?")
        else:
            label = APPEARS
            reasons.append(f"{who} (or unrestricted) are listed as eligible applicants." if who == "State governments"
                           else f"This agency's applicant type is listed: {who}.")
    elif "25" in codes:
        label = VERIFY
        reasons.append("Eligibility is 'Others (see text)'. A person must read the additional eligibility text.")
        questions.append("Does the 'Additional Information on Eligibility' text include state agencies?")
    elif codes & PARTNER_CODES:
        label = PARTNER
        partners = [l for c, l in zip(record.get("eligibility_codes") or [], labels) if c in PARTNER_CODES] \
            or [ELIGIBILITY_LABELS.get(c, c) for c in sorted(codes & PARTNER_CODES)]
        reasons.append(("State governments are not" if own_is_state else "This agency's applicant type is not")
                       + " eligible, but these are: " + "; ".join(partners[:4]) + ".")
        questions.append("Is there an eligible partner (for example a UNC System campus, county, or nonprofit) that "
                         "could apply with the agency as a partner?")
    else:
        label = NOT_ELIGIBLE
        reasons.append("Only individuals or private businesses are eligible.")

    if matching and not no_match:
        questions.append("Can the agency provide and document the required match / cost share?")
    if partnership:
        questions.append("Which partners would participate or provide letters of support?")
    if label != APPEARS:
        questions.append("Confirm eligibility with the federal program officer before investing staff time.")

    return {
        "label": label,
        "reasons": reasons,
        "citations": ([field_cite] if field_cite else []) + restrictions[:3],
        "conditions": {"matching": matching[:3], "no_match": no_match[:2], "partnership": partnership[:3],
                       "other": other[:4]},
        "open_questions": list(dict.fromkeys(questions)),
        "method": "rules (Grants.gov eligibility codes + cited notice text); not a legal determination",
    }
