"""Sensitive-info filter for anything a user TYPES (grant data is already public).

Runs before: any AI call, saving feedback, copying/downloading a brief.
  Layer 1 (optional): Azure AI Language PII detection (stays in the Azure tenant) — set LANGUAGE_ENDPOINT/KEY
  Layer 2 (always):   local regex — emails, phone numbers, SSNs, card numbers, street addresses, titled names
  Layer 3 (always):   internal-information keywords → BLOCK and ask the user to edit
Original unredacted text is never stored; only counts and types of redactions are logged."""
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from common import config

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
# "jane [at] example [dot] com" / "jane at example dot org"
OBFUSCATED_EMAIL = re.compile(
    r"\b[\w.+-]+\s*(?:[\[(]\s*at\s*[\])]|\s+at\s+)\s*[\w-]+(?:\s*(?:[\[(]\s*dot\s*[\])]|\s+dot\s+|\.)\s*[\w-]+)*"
    r"\s*(?:[\[(]\s*dot\s*[\])]|\s+dot\s+|\.)\s*(?:com|org|net|gov|edu|us|io|co|info|biz)\b", re.I)
INTL_PHONE = re.compile(r"(?<![\w+])\+(?!1\b)\d{1,3}[\s.-]?(?:\(?\d{1,4}\)?[\s.-]?){2,4}\d{2,4}(?![\d-])")
# words after a label that introduces a person ("Contact: Jane Smith", "Prepared by: …", "Point of contact is …")
CUED_NAME = re.compile(r"\b((?i:contact|point of contact(?: is)?|prepared by|submitted by|reviewer|reviewed by|applicant name|"
                       r"(?:applicant|contact|full|your|staff) name|ask|call|email|signed|attn|attention))\s*[:\-]?\s+((?:Dr\.|Mr\.|Ms\.|Mrs\.)?\s*"
                       r"[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z'-]+){1,2})\b")
# capitalised words that are places, programs or organisations, not people
NOT_A_NAME = {"north", "south", "carolina", "state", "states", "university", "college", "county", "city", "department",
              "office", "program", "programs", "agency", "hurricane", "water", "clean", "act", "fund", "federal",
              "national", "the", "division", "center", "council", "commission", "board", "services", "service",
              "united", "america", "american", "public", "health", "education", "environmental", "quality", "deq",
              "dpi", "dncr", "epa", "fema", "noaa", "usda", "grants", "grant", "monday", "tuesday", "wednesday",
              "thursday", "friday", "january", "february", "march", "april", "may", "june", "july", "august",
              "september", "october", "november", "december"}
EMPLOYEE_ID = re.compile(r"\b(employee|staff|badge|personnel|member) (?:id|number|no\.?|#)\s*[:#]?\s*[A-Z0-9-]{4,}\b", re.I)
# an ID number right after a cue word: "ssn 123456789", "DL# A1234567", "passport X12345678"
CUED_ID = re.compile(r"\b(ssn|social security(?: number| no\.?)?|driver'?s licen[cs]e(?: number| no\.?)?|dl|"
                     r"passport(?: number| no\.?)?|tax ?id|itin)\s*[#:]?\s*([A-Z]?\d[\d -]{5,12}\d)\b", re.I)
DOB = re.compile(r"\b(?:dob|d\.o\.b\.|date of birth|born on|birthdate)\s*[:#]?\s*"
                 r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})", re.I)
PO_BOX = re.compile(r"\bP\.?\s?O\.?\s?Box\s+\d+\b", re.I)
DASHES = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe63\uff0d"})
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b\d{3} \d{2} \d{4}\b")
PHONE = re.compile(r"(?<![\d-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\d-])")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
ADDRESS = re.compile(r"\b\d{1,6}\s+(?:(?:[A-Z][a-zA-Z]*|\d{1,3}(?:st|nd|rd|th))\.?\s){1,4}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|"
                     r"Lane|Ln|Way|Court|Ct|Highway|Hwy|Parkway|Pkwy|Place|Pl|Circle|Cir)\b\.?", re.I)
TITLED_NAME = re.compile(r"\b(?:Mr|Ms|Mrs|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?")
CONTACT_NAME = re.compile(r"\b([Cc]ontact|[Cc]all|[Ee]mail|[Aa]sk)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\b")

INTERNAL = re.compile(r"\b(confidential|internal only|internal use only|draft budget|personnel (matter|file|action)s?|"
                      r"do not distribute|not for distribution|not for public release|pre-?decisional|privileged|attorney[- ]client|"
                      r"for official use only|fouo|sensitive but unclassified|controlled unclassified|cui|embargoed|under embargo)\b", re.I)
SHORTFALL = re.compile(r"\b(shortfall|deficit|budget gap|funding gap)\b[^.]{0,40}\$\s?\d", re.I)


def _luhn(digits: str) -> bool:
    d = [int(c) for c in digits][::-1]
    total = sum(d[0::2]) + sum(sum(divmod(2 * x, 10)) for x in d[1::2])
    return total % 10 == 0


@dataclass
class PrivacyResult:
    text: str
    redactions: Counter = field(default_factory=Counter)
    blocked: bool = False
    flags: list = field(default_factory=list)
    layers: list = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.redactions)

    def summary(self) -> str:
        if not self.redactions and not self.flags:
            return "No sensitive information detected."
        parts = [f"{n} {k.lower()}" for k, n in self.redactions.items()]
        msg = ("Redacted: " + ", ".join(parts) + ".") if parts else ""
        if self.flags:
            msg += " Possible internal information: " + ", ".join(self.flags) + ". Please edit before continuing."
        return msg.strip()


def _azure_pii(text: str) -> tuple[str, Counter] | None:
    if not (config.LANGUAGE_ENDPOINT and config.LANGUAGE_KEY) or not text.strip():
        return None
    try:
        r = requests.post(config.LANGUAGE_ENDPOINT.rstrip("/") + "/language/:analyze-text?api-version=2023-04-01",
                          headers={"Ocp-Apim-Subscription-Key": config.LANGUAGE_KEY},
                          json={"kind": "PiiEntityRecognition",
                                "analysisInput": {"documents": [{"id": "1", "language": "en", "text": text[:5000]}]}},
                          timeout=15)
        r.raise_for_status()
        doc = r.json()["results"]["documents"][0]
        counts = Counter()
        out = text
        for ent in sorted(doc.get("entities", []), key=lambda e: -e["offset"]):
            cat = "NAME" if ent["category"] == "Person" else ent["category"].upper()
            out = out[: ent["offset"]] + f"[{cat}]" + out[ent["offset"] + ent["length"]:]
            counts[cat] += 1
        return out, counts
    except Exception:
        return None  # fall back to the local layer


# A bare "First Last" name with no cue word ("Jordan Lee approved the plan") is caught when the first word is a common
# first name and the second looks like a surname. Place / program words after it ("Jordan Lake", "Grace Church") are
# not treated as surnames.
FIRST_NAMES = set("""
    aaron abigail adam ahmed aisha alan albert alex alexander alexis ali alice amanda amber amy ana andre andrea
    andrew angela ann anna anthony arjun arthur ashley austin ava avery barbara ben benjamin beth betty beverly
    bill billy bob bobby brandon brenda brian brittany bruce bryan camila carl carlos carol carolyn casey
    catherine charles charlotte chen cheryl chloe chris christian christina christine christopher cynthia dan
    daniel danielle darnell dave david deb deborah debra denise dennis derrick diana diane diego donald donna
    doris dorothy douglas dylan edward elena elijah elizabeth ella emily emma eric ethan eugene evelyn fatima
    frances frank gabriel gary george gerald gloria grace greg gregory hannah harold heather helen henry hiroshi
    imani isabella jack jacob jacqueline jamal james jamie jane janet janice jason jean jeff jeffrey jen jennifer
    jeremy jerry jesse jessica jim jin joan joe john jon jonathan jordan jorge jose joseph joshua joyce juan
    judith judy julie justin karen kate katherine kathleen kathryn kayla keisha keith kelly ken kenneth kevin kim
    kimberly kyle larry latoya laura lauren lawrence leah li linda lisa liz logan lori louis lucia luis madison
    malik marcus margaret maria marie marilyn mark martha mary mason matt matthew meg megan melissa mia michael
    michelle miguel mike min mohammed morgan muhammad nancy natalie nathan nicholas nick nicole noah olivia omar
    pamela pat patricia patrick paul peter philip priya quinn rachel raj ralph randy raymond rebecca richard rick
    riley robert roger ronald rosa roy russell ruth ryan sam samantha samuel sandra sara sarah scott sean sharon
    shirley sofia sophia sophie stephanie stephen steve steven sue susan taylor teresa terry theresa thomas tim
    timothy tom tony tyler tyrone valentina victoria vincent virginia walter wayne wei william willie yuki zachary
    zoe
""".split())
NOT_A_SURNAME = NOT_A_NAME | {"lake", "river", "creek", "park", "street", "road", "avenue", "hall", "church", "school",
                              "high", "middle", "elementary", "bridge", "beach", "island", "mountain", "forest", "valley",
                              "foundation", "institute", "hospital", "library", "museum", "airport", "station", "plan",
                              "act", "award", "awards", "project", "initiative", "dam", "falls", "county", "township",
                              # NC places that follow a first-name-like word ("Charlotte Mecklenburg", "Austin Peay")
                              "mecklenburg", "wake", "durham", "guilford", "forsyth", "cumberland", "buncombe", "raleigh",
                              "asheville", "wilmington", "greensboro", "fayetteville", "peay", "regional", "metro",
                              "area", "valley", "coast", "coastal", "region", "district", "schools", "public"}
# public people that federal programs are named after ("Ryan White HIV/AIDS Program", "Paul Coverdell grants")
PROGRAM_NAMESAKES = {"ryan white", "paul coverdell", "john lewis", "edward byrne", "rosa parks", "martin luther",
                     "john glenn", "harry truman", "robert noyce", "thomas jefferson", "james madison", "mark hatfield",
                     "patsy mink", "carl perkins", "george washington", "abraham lincoln", "john mccain", "ted stevens",
                     "daniel inouye", "barbara jordan", "james webb", "grace hopper", "jacob javits", "paul douglas"}
# an organisation word right after the pair means it is a place or institution, not a person
ORG_AFTER = re.compile(r"\s+(University|College|State|Schools?|County|City|Hospital|Center|Institute|Foundation|"
                       r"Library|Museum|Airport|District|Community|Regional|Medical|Health|Housing|Authority)\b")
BARE_NAME = re.compile(r"\b([A-Z][a-z]+)\s+(?:[A-Z]\.\s+)?([A-Z][a-z]+(?:[-'][A-Z][a-z]+)?)\b")


def scan(text: str | None) -> PrivacyResult:
    # normalise look-alike characters first so "919‑555‑0101" (non-breaking hyphens) can't slip past the patterns
    text = unicodedata.normalize("NFKC", str(text or ""))[:5000].translate(DASHES).replace("\x00", "")
    res = PrivacyResult(text=text)
    # Layer 3 first: internal information is blocked BEFORE anything (even the in-tenant detector) sees it
    res.flags = _internal_flags(text)
    if res.flags:
        res.blocked = True
        res.layers.append("internal-info keywords")
        return res
    az = _azure_pii(text)
    if az:
        res.text, res.redactions = az[0], az[1]
        res.layers.append("Azure AI Language PII")
    t = res.text

    def sub(rx, tag, s, check=None):
        def repl(m):
            if check and not check(m.group(0)):
                return m.group(0)
            res.redactions[tag] += 1
            return f"[{tag}]"
        return rx.sub(repl, s)

    t = sub(EMAIL, "EMAIL", t)
    t = sub(OBFUSCATED_EMAIL, "EMAIL", t)
    t = sub(INTL_PHONE, "PHONE", t)
    t = sub(EMPLOYEE_ID, "ID NUMBER", t)
    t = sub(DOB, "DATE OF BIRTH", t)

    def cued(m):
        res.redactions["ID NUMBER"] += 1
        return f"{m.group(1)} [ID NUMBER]"
    t = CUED_ID.sub(cued, t)
    t = sub(SSN, "SSN", t)
    t = sub(CARD, "CARD", t, check=lambda s: 13 <= len(re.sub(r"\D", "", s)) <= 19 and _luhn(re.sub(r"\D", "", s)))
    t = sub(PHONE, "PHONE", t)
    t = sub(ADDRESS, "ADDRESS", t)
    t = sub(PO_BOX, "ADDRESS", t)
    t = sub(TITLED_NAME, "NAME", t)

    def name_repl(m):
        if any(w.lower() in NOT_A_NAME for w in m.group(2).split()):
            return m.group(0)
        res.redactions["NAME"] += 1
        return f"{m.group(1)} [NAME]"
    t = CONTACT_NAME.sub(name_repl, t)

    def cued_name(m):
        if any(w.lower().strip(".") in NOT_A_NAME for w in m.group(2).split()):
            return m.group(0)
        res.redactions["NAME"] += 1
        return m.group(0)[: m.start(2) - m.start(0)] + "[NAME]"
    t = CUED_NAME.sub(cued_name, t)

    def bare_name(m):
        if m.group(1).lower() not in FIRST_NAMES or m.group(2).lower() in NOT_A_SURNAME \
                or ORG_AFTER.match(m.string, m.end()) \
                or f"{m.group(1)} {m.group(2)}".lower() in PROGRAM_NAMESAKES \
                or re.match(r"\s+[A-Z][A-Za-z/]+", m.string[m.end():]):   # part of a longer Proper Name / program title
            return m.group(0)
        res.redactions["NAME"] += 1
        return "[NAME]"
    t = BARE_NAME.sub(bare_name, t)
    res.text = t
    res.layers.append("local regex")

    res.layers.append("internal-info keywords")
    return res


def _internal_flags(t: str) -> list[str]:
    flags = [m.group(0).lower() for m in INTERNAL.finditer(t)]
    # catch letter-spaced words too: "C O N F I D E N T I A L"
    squeezed = re.sub(r"\b(\w) (?=\w\b)", r"\1", t)
    if squeezed != t:
        flags += [m.group(0).lower() for m in INTERNAL.finditer(squeezed)]
    if SHORTFALL.search(t):
        flags.append("shortfall amount")
    return list(dict.fromkeys(flags))


def log_event(storage, purpose: str, res: PrivacyResult) -> None:
    """Log only counts and types (never the original text)."""
    if not res.redactions and not res.flags or storage is None:
        return
    event = {"at": datetime.now(timezone.utc).isoformat(), "purpose": purpose,
             "redactions": dict(res.redactions), "flag_count": len(res.flags), "blocked": res.blocked}
    try:
        storage.update_json("privacy/log.json", lambda log: ((log or []) + [event])[-1000:], default=[])
    except Exception:  # the audit counter must never block the user's action
        pass
