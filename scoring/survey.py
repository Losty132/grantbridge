"""Survey answers: options, defaults and validation (all click-only except the optional 'other priority')."""

CAPACITY_OPTIONS = ["1", "2", "3", "4", "5+"]
TOP_N_BY_CAPACITY = {"1": 3, "2": 4, "3": 5, "4": 7, "5+": 10}   # default capacity "3" → Top 5
MIN_AWARD_OPTIONS = {"Any": 0, "$50K+": 50_000, "$250K+": 250_000, "$1M+": 1_000_000}
COST_SHARE_OPTIONS = ["Yes", "No", "Sometimes"]
PREP_OPTIONS = {"2 weeks": 14, "30 days": 30, "60 days": 60}

DEFAULT = {"agency_id": "deq", "focus_objectives": [], "focus_topics": [], "other_priority": "", "capacity": "3",
           "min_award": "Any", "cost_share": "Sometimes", "prep_time": "30 days"}


def normalize(s: dict | None) -> dict:
    s = dict(DEFAULT, **(s or {}))
    for k in ("capacity", "min_award", "cost_share", "prep_time"):  # anything but a string → default
        if not isinstance(s.get(k), str):
            s[k] = DEFAULT[k]
    if s["capacity"] not in CAPACITY_OPTIONS:
        s["capacity"] = DEFAULT["capacity"]
    if s["min_award"] not in MIN_AWARD_OPTIONS:
        s["min_award"] = DEFAULT["min_award"]
    if s["cost_share"] not in COST_SHARE_OPTIONS:
        s["cost_share"] = DEFAULT["cost_share"]
    if s["prep_time"] not in PREP_OPTIONS:
        s["prep_time"] = DEFAULT["prep_time"]
    s["other_priority"] = str(s.get("other_priority") or "")[:300]
    s["focus_objectives"] = [str(x) for x in s.get("focus_objectives") or []][:50]
    s["focus_topics"] = [str(x) for x in s.get("focus_topics") or []][:20]
    s["top_n"] = TOP_N_BY_CAPACITY[s["capacity"]]
    s["min_award_value"] = MIN_AWARD_OPTIONS[s["min_award"]]
    s["prep_days"] = PREP_OPTIONS[s["prep_time"]]
    return s
