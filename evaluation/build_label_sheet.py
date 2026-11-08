"""Create a labeling sheet from LIVE data: per agency, the top 10, 10 from the middle and 10 random items,
Labels are left BLANK for your team to fill in.

    python -m evaluation.build_label_sheet        # writes evaluation/labels_to_fill.csv
Fill 'relevant' (1/0) and 'expected_eligibility' (Appears Eligible / Needs Human Verification /
Partnership Opportunity / Not Eligible for Direct Application) WITHOUT looking at scores, then save the
file as evaluation/labels.csv and run python -m evaluation.run_eval."""
import csv
import random
from pathlib import Path

from agency_profiles import loader
from common import config
from common.storage import Storage
from data_retrieval.store import load_dataset
from scoring.rank import rank

OUT = Path(__file__).resolve().parent / "labels_to_fill.csv"


def main():
    st = Storage()
    items, status = load_dataset(st)
    if not items:
        raise SystemExit("No data yet. Run python -m data_retrieval.refresh first.")
    rng = random.Random(42)
    rows = []
    for aid, prof in loader.load_all().items():
        out = rank(items, prof, st.read_json(f"surveys/{aid}.json") or {"agency_id": aid}, st)
        pool = out["all"]
        pick = out["shortlist"][:10]
        mid = out["shortlist"][10:200]
        pick += rng.sample(mid, min(10, len(mid)))
        rest = [x for x in pool if x not in pick]
        pick += rng.sample(rest, min(10, len(rest)))
        rng.shuffle(pick)
        for x in pick:
            r = x["record"]
            rows.append({"agency": aid, "opportunity_id": r["id"], "opportunity_number": r["number"],
                         "title": r["title"], "relevant": "", "expected_eligibility": "", "labeler": "", "notes": ""})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT} from {status.get('mode')} data ({status.get('last_success')}).")


if __name__ == "__main__":
    main()
