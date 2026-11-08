"""Hard filters / disqualifiers. These override any score. Every exclusion is logged with its reason."""
from eligibility.classify import NOT_ELIGIBLE, PARTNER


def apply(record: dict, survey: dict, elig: dict) -> tuple[list[str], list[str]]:
    """Return (exclusion_reasons, flags). Any exclusion reason removes the item from the shortlist."""
    excl, flags = [], []
    if record.get("status") == "expired":
        excl.append(f"Expired (closed {record.get('close_date') or 'date not listed'})")
    if elig["label"] == NOT_ELIGIBLE:
        excl.append("Not Eligible for Direct Application: state government is not an eligible applicant")
    elif elig["label"] == PARTNER:
        excl.append("Partnership Opportunity only: state government is not an eligible applicant "
                    "(an eligible partner would have to apply)")
    if record.get("cost_sharing") is True and survey["cost_share"] == "No":
        excl.append("Cost share / match required, and the survey says the team cannot provide match")
    ceiling = record.get("award_ceiling")
    if survey["min_award_value"] and ceiling and ceiling < survey["min_award_value"]:
        excl.append(f"Award ceiling ${ceiling:,.0f} is below your minimum ({survey['min_award']})")
    if survey["min_award_value"] and not ceiling:
        flags.append("Award amount not specified")
    d = record.get("days_left")
    if d is not None and record.get("status") != "expired" and d < survey["prep_days"]:
        flags.append(f"Too tight: {d} days left vs. {survey['prep_days']} days prep")
    return excl, flags
