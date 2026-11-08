"""Grant brief: one page per recommendation, as text (copy) or PDF (download)."""
from datetime import date, timedelta

from data_retrieval.normalize import today
from eligibility.classify import APPEARS, PARTNER, VERIFY


def money(v) -> str:
    return f"${v:,.0f}" if v else "Not specified"


def funding_range(r: dict) -> str:
    lo, hi = r.get("award_floor"), r.get("award_ceiling")
    if lo and hi:
        rng = f"{money(lo)} – {money(hi)} per award"
    elif hi:
        rng = f"Up to {money(hi)} per award"
    else:
        rng = "Not specified"
    if r.get("total_funding"):
        rng += f" (total program funding {money(r['total_funding'])})"
    return rng


def next_action(result: dict) -> str:
    r, elig, feas = result["record"], result["eligibility"], result["feasibility"]
    close = r.get("close_date")
    if r.get("status") == "expired":
        return ("Closed. Note this program for the next cycle: subscribe to Grants.gov alerts for its assistance "
                "listing and prepare materials before the next notice posts.")
    if r.get("status") == "forecasted":
        return "Forecasted: set a reminder for posting, confirm eligibility early, and line up partners now."
    if elig["label"] == PARTNER:
        return "Identify an eligible partner to lead the application, with the agency as a partner."
    if elig["label"] == VERIFY:
        return "Email the federal program officer to confirm a state agency can apply (cite the eligibility text below)."
    if feas["status"] == "not_enough":
        return "Probably too little time this cycle. Decide today whether a partner could lead, or plan for the next cycle."
    if feas["status"] == "tight" and close and feas.get("need_days"):
        go = date.fromisoformat(close) - timedelta(days=feas["need_days"])
        return f"Make a go/no-go decision by {max(go, today()).isoformat()} and confirm SAM.gov/UEI registration now."
    return "Assign a lead, confirm SAM.gov/UEI registration, and start the budget and narrative."


def what_to_gather(result: dict) -> list[str]:
    keys = {d["key"] for d in result["estimate"]["drivers"]}
    items = ["Budget and budget justification", "Active SAM.gov registration and UEI; Grants.gov workspace access"]
    if "letters" in keys or result["eligibility"]["conditions"]["partnership"]:
        items.append("Letters of support / partner commitments")
    if result["record"].get("cost_sharing") or result["eligibility"]["conditions"]["matching"]:
        items.append("Match / cost-share documentation")
    if "evaluation" in keys:
        items.append("Evaluation plan, logic model or data management plan")
    if "loi" in keys:
        items.append("Letter of intent / pre-application")
    return items


def build(result: dict, explanation: dict, profile: dict, data_label: str, notes: str = "") -> dict:
    r, elig, est = result["record"], result["eligibility"], result["estimate"]
    flags = list(result["flags"])
    if r.get("cost_sharing"):
        flags.append("Matching funds required")
    if elig["conditions"]["partnership"]:
        flags.append("Partnerships / letters mentioned")
    if elig["conditions"]["other"]:
        flags.append("Other conditions (see eligibility notes)")
    return {
        "title": r["title"], "issuing_agency": r.get("agency") or "Not specified", "number": r.get("number"),
        "status": r.get("status"), "data_label": data_label,
        "funding": funding_range(r),
        "deadline": (f"{r['close_date']} ({r['days_left']} days remaining)" if r.get("close_date") and r.get("days_left") is not None
                     and r["days_left"] >= 0 else (f"{r['close_date']} (closed)" if r.get("close_date") else "Not specified")),
        "score": result["score"], "components": result["components"],
        "objective": explanation.get("matched_label"), "objective_citation": explanation.get("objective_citation"),
        "objective_url": explanation.get("objective_url"),
        "plan_text": result["matched_target"]["label"],
        "program": (result["matched_program"]["label"] if result.get("matched_program")
                    and (result.get("program_alignment") or 0) >= 0.5 else None),
        "program_source": ((result.get("matched_program") or {}).get("citation") or {}).get("url"),
        "grant_quote": explanation.get("grant_evidence_quote"), "reasons": explanation.get("reasons", []),
        "confidence": explanation.get("confidence"), "explanation_source": explanation.get("source"),
        "eligibility_label": elig["label"], "eligibility_reasons": elig["reasons"],
        "eligibility_citations": elig["citations"], "open_questions": elig["open_questions"],
        "complexity": est["level"], "time_estimate": est["summary"], "time_label": est["label"],
        "drivers": est["top_drivers"], "feasibility": result["feasibility"]["text"],
        "flags": flags, "gather": what_to_gather(result), "next_action": next_action(result),
        "url": r.get("url"), "profile": profile["name"], "notes": notes,
    }


def to_text(b: dict) -> str:
    L = [f"GRANT BRIEF: {b['title']}", f"For: {b['profile']}   |   Data: {b['data_label']}", "",
         f"Issuing agency: {b['issuing_agency']}   Opportunity #: {b['number']}   Status: {b['status']}",
         f"Funding: {b['funding']}", f"Deadline: {b['deadline']}", "",
         f"PRIORITIZATION SCORE: {b['score']:.0f}/100 (not a probability of winning; confidence: {b['confidence']})"]
    for name, c in b["components"].items():
        L.append(f"  - {name.replace('_', ' ').title()}: {c['points']}/{c['max']}  ({c['why']})")
    L += ["", "NC STRATEGIC OBJECTIVE SUPPORTED", f"  {b['objective']}", f"  Source: {b['objective_citation']} {b['objective_url'] or ''}",
          ] + ([f"  Related agency program: {b['program']} ({b['program_source']})"] if b.get("program") else []) + [
          "", "EVIDENCE", f"  Plan: \"{b['plan_text']}\" (summary of plan wording; verify in cited section)",
          f"  Notice: \"{b['grant_quote']}\"", "", "WHY IT MATCHES"] + [f"  - {x}" for x in b["reasons"]]
    L += ["", f"ELIGIBILITY: {b['eligibility_label']} (rules-based; not a legal determination)"]
    L += [f"  - {x}" for x in b["eligibility_reasons"]]
    L += [f"  Cited: \"{c['quote']}\" ({c['source']})" for c in b["eligibility_citations"]]
    if b["open_questions"]:
        L += ["  Open questions:"] + [f"   ? {q}" for q in b["open_questions"]]
    L += ["", f"COMPLEXITY: {b['complexity']}   ({b['time_label']})", f"  {b['time_estimate']}", f"  {b['feasibility']}"]
    L += [f"  - {d['detail']}: \"{d['quote'][:160]}\" ({d['source']})" for d in b["drivers"]]
    if b["flags"]:
        L += ["", "FLAGS"] + [f"  ! {f}" for f in b["flags"]]
    L += ["", "WHAT TO GATHER"] + [f"  [ ] {g}" for g in b["gather"]]
    L += ["", f"RECOMMENDED NEXT ACTION: {b['next_action']}", f"OFFICIAL LISTING: {b['url']}"]
    if b.get("notes"):
        L += ["", "STAFF NOTES (privacy-filtered)", f"  {b['notes']}"]
    L += ["", "Prepared by the Federal Funds Matchmaker prototype. Humans make the final decision."]
    return "\n".join(L)


def to_pdf(b: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)

    def safe(s):  # core PDF fonts are latin-1 only
        return (s.replace("–", "-").replace("—", "-").replace("’", "'").replace("“", '"').replace("”", '"')
                .replace("≤", "<=").replace("✅", "[ok]").replace("⚠️", "[!]").replace("❌", "[x]").replace("❔", "[?]")
                .encode("latin-1", "replace").decode("latin-1"))
    for line in to_text(b).split("\n"):
        if line.isupper() or line.startswith(("GRANT BRIEF", "PRIORITIZATION", "ELIGIBILITY:", "COMPLEXITY:",
                                               "RECOMMENDED", "OFFICIAL")):
            pdf.set_font("Helvetica", "B", 9)
        else:
            pdf.set_font("Helvetica", size=9)
        pdf.multi_cell(0, 4.5, safe(line) or " ", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
