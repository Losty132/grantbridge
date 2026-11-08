"""Load agency profiles (JSON in agency_profiles/profiles/) and build the list of things a grant is matched against."""
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from common import config

PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
TOPICS_FILE = Path(__file__).resolve().parent / "nc_topics.json"
REQUIRED = ["agency_id", "name", "plan", "mission", "objectives", "search_terms", "eligible_applicant_codes"]


def validate(p: dict) -> list[str]:
    problems = [f"missing '{k}'" for k in REQUIRED if not p.get(k)]
    for o in p.get("objectives", []):
        if not o.get("id") or not o.get("text") or not (o.get("citation") or {}).get("url"):
            problems.append(f"objective {o.get('id', '?')} needs id, text and citation url")
    return problems


@lru_cache(maxsize=1)
def load_all() -> dict:
    out = {}
    for f in sorted(PROFILE_DIR.glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        if not validate(p) and (config.AGENCIES is None or p["agency_id"] in config.AGENCIES):
            out[p["agency_id"]] = p
    return out


def get(agency_id: str) -> dict:
    return load_all()[agency_id]


def standard_topics() -> list[str]:
    return json.loads(TOPICS_FILE.read_text(encoding="utf-8"))["topics"]


def profile_strength(p: dict) -> tuple[str, list[str]]:
    """'strong' or 'weak' with reasons. Weak profiles get the standard NC topic list in the survey."""
    reasons = []
    if len(p.get("objectives", [])) < 5:
        reasons.append("fewer than 5 objectives extracted")
    try:
        end_year = int(str(p["plan"]["years"]).split("-")[-1])
        if end_year < date.today().year:
            reasons.append(f"plan period ended in {end_year}")
    except (KeyError, ValueError):
        reasons.append("plan years unknown")
    if sum(len(o.get("keywords", [])) for o in p.get("objectives", [])) < 15:
        reasons.append("few program keywords")
    return ("weak" if reasons else "strong"), reasons


def match_targets(p: dict, survey: dict | None = None) -> list[dict]:
    """Objectives + operating programs + the user's 'other priority' text, each a separate match target."""
    survey = survey or {}
    selected = set(survey.get("focus_objectives") or [])
    targets = []
    for o in p["objectives"]:
        targets.append({"id": o["id"], "kind": "objective", "label": f"{o['id']}: {o['text']}",
                        "text": f"{o['goal_title']}. {o['text']} {' '.join(o.get('keywords', []))}",
                        "keywords": o.get("keywords", []), "citation": o["citation"], "selected": o["id"] in selected})
    for i, prog in enumerate(p.get("operating_programs", []), 1):
        src = (prog.get("sources") or [{}])[0]
        targets.append({"id": f"{p['agency_id'].upper()}-PROG{i}", "kind": "program", "label": prog["name"],
                        "text": f"{prog['name']}. {prog['description']} {' '.join(prog.get('keywords', []))}",
                        "keywords": prog.get("keywords", []),
                        "citation": {"document": src.get("title", ""), "section": "Operating program",
                                     "url": src.get("url", "")},
                        "selected": False})
    for t in survey.get("focus_topics") or []:  # fallback topics for weak profiles
        targets.append({"id": f"TOPIC:{t}", "kind": "topic", "label": t, "text": t, "keywords": [t.lower()],
                        "citation": {"document": "Standard NC topic list (not from the plan)", "section": "", "url": ""},
                        "selected": True})
    other = (survey.get("other_priority") or "").strip()
    if other:
        targets.append({"id": "USER-PRIORITY", "kind": "user", "label": f"Your priority: {other}", "text": other,
                        "keywords": [], "citation": {"document": "Survey answer (Q2 other priority)", "section": "",
                                                     "url": ""}, "selected": True})
    return targets


def all_keywords(p: dict) -> list[str]:
    kws = list(p.get("search_terms", []))
    for o in p.get("objectives", []):
        kws += o.get("keywords", [])
    for prog in p.get("operating_programs", []):
        kws += prog.get("keywords", [])
    return list(dict.fromkeys(k for k in kws if k))
