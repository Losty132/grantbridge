"""Draft a new agency profile from its strategic plan PDF with Azure OpenAI. A person must review
the draft against the PDF before copying it into agency_profiles/profiles/.

    python -m agency_profiles.extract_profile --pdf plan.pdf --agency-id doa --name "NC Department of Administration" \
        --plan-url "https://www.osbm.nc.gov/documents/files/strategic-plan-doa/open" --plan-title "DOA Strategic Plan" --years 2025-2029

Without Azure OpenAI: copy agency_profiles/profiles/deq.json and fill it in by hand from the plan.
"""
import argparse
import json
import sys
from pathlib import Path

from agency_profiles.loader import validate
from common.ai import AI

PROMPT = """Extract a structured profile from this North Carolina state agency strategic plan.
Return JSON with keys:
  "mission": the mission statement exactly as written,
  "responsibilities": list of short strings,
  "program_priorities": list of short strings,
  "operating_programs": list of {{"name","description","keywords":[...]}},
  "objectives": list of {{"goal_id","goal_title","objective_id","text","page","keywords":[3-6 specific terms]}},
  "search_terms": 5-8 short Grants.gov search terms.
Copy objective text exactly as written in the plan, keeping the plan's numbering; include the page number.
If something is not in the plan, leave it empty. Do not invent objectives.

<document>
{text}
</document>"""


def main():
    ap = argparse.ArgumentParser()
    for a in ("--pdf", "--agency-id", "--name", "--plan-url", "--plan-title", "--years"):
        ap.add_argument(a, required=True)
    a = ap.parse_args()
    ai = AI()
    if not ai.available:
        sys.exit("Set AOAI_ENDPOINT and AOAI_KEY first, or build the profile by hand.")
    from pypdf import PdfReader

    text = "\n".join(f"[page {i}] " + (p.extract_text() or "") for i, p in enumerate(PdfReader(a.pdf).pages, 1))
    d = ai.chat_json("You extract structured data for government analysts.", PROMPT.format(text=text[:90000]),
                     max_tokens=4000)
    prefix = a.agency_id.upper()
    prof = {
        "agency_id": a.agency_id, "name": a.name, "short_name": prefix,
        "plan": {"title": a.plan_title, "years": a.years, "url": a.plan_url},
        "mission": {"text": d.get("mission", ""), "citation": {"document": a.plan_title, "section": "Mission",
                                                                 "url": a.plan_url}},
        "responsibilities": d.get("responsibilities", []), "program_priorities": d.get("program_priorities", []),
        "operating_programs": [dict(p, sources=[{"title": a.plan_title, "url": a.plan_url}])
                               for p in d.get("operating_programs", [])],
        "objectives": [{"id": f"{prefix}-{o.get('objective_id')}", "goal_id": o.get("goal_id"),
                        "goal_title": o.get("goal_title"), "text": o.get("text"), "keywords": o.get("keywords", []),
                        "citation": {"document": a.plan_title,
                                     "section": f"Goal {o.get('goal_id')}, Objective {o.get('objective_id')}, "
                                                f"p. {o.get('page')}", "url": a.plan_url}}
                       for o in d.get("objectives", [])],
        "search_terms": d.get("search_terms", []), "eligible_applicant_codes": ["00", "25", "99"],
        "preferred_funders": [], "wording_note": "AI DRAFT: verify every objective against the PDF.",
        "reviewed_by": "", "profile_version": "draft"}
    out = Path("drafts") / f"{a.agency_id}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(prof, indent=2))
    print(f"Wrote {out}. Problems: {validate(prof) or 'none'}. Review it, then copy to agency_profiles/profiles/ "
          f"and add '{a.agency_id}' to the AGENCIES setting.")


if __name__ == "__main__":
    main()
