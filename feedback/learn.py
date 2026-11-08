"""Learn from the team's decisions (stretch goal 3).

Grants that look like ones the team pursued get a small boost; grants that look like ones the team marked as a poor
fit get a small penalty. "Looks like" = TF-IDF similarity of title + description. The nudge is capped at
+/- MAX_POINTS so feedback refines the ranking but never overrides the strategic-plan match, and every nudge is
explained on the grant ("+5: similar to 'Transit planning program 2079', which your team pursued").

What counts as feedback:
  good  = Pursue / Maybe, or relevance mark 'relevant'
  bad   = relevance mark 'irrelevant', or a Pass whose reason is about fit
  ignored = a Pass for capacity / timing / money (says nothing about whether the grant fits)
A grant is never nudged by its own decision (only by OTHER judged grants).
"""
import re

from common.text import TfIdf, sparse_cosine

MAX_POINTS = 8.0
SIM_FLOOR = 0.25      # below this two grants are not alike enough to learn from
SIM_FULL = 0.60       # at or above this the full nudge applies
NOT_ABOUT_FIT = re.compile(r"\b(capacity|bandwidth|busy|staff(ing)?|time|timing|deadline|too soon|too late|"
                           r"next (year|cycle|round)|later|already (applied|funded|have)|match|cost.?share|budget|"
                           r"money|funds?|workload|priorit)", re.I)


def label_of(review: dict) -> int | None:
    """1 good fit, 0 poor fit, None = not about fit."""
    mark = review.get("relevance") or ""
    if mark == "relevant":
        return 1
    if mark == "irrelevant":
        return 0
    if review.get("action") in ("Pursue", "Maybe"):
        return 1
    if review.get("action") == "Pass":
        return None if NOT_ABOUT_FIT.search(review.get("reason") or "") else 0
    return None


def labels(reviews: dict) -> dict:
    out = {}
    for oid, v in (reviews or {}).items():
        lab = label_of(v)
        if lab is not None:
            out[oid] = lab
    return out


def text_of(record: dict) -> str:
    return f"{record['title']}. {record['title']}. {(record.get('description') or '')[:2000]}"


class Learner:
    """Built once per ranking (vectors cached), then asked for nudges whenever the team's feedback changes."""

    def __init__(self, results: list[dict]):
        self.ids = [x["record"]["id"] for x in results]
        self.titles = {x["record"]["id"]: x["record"]["title"] for x in results}
        self._tf = TfIdf([text_of(x["record"]) for x in results]) if results else None
        self._vec = {}
        self._results = {x["record"]["id"]: x for x in results}

    def vec(self, oid: str):
        if oid not in self._vec:
            x = self._results.get(oid)
            self._vec[oid] = self._tf.vector(text_of(x["record"])) if (x and self._tf) else {}
        return self._vec[oid]

    def nudges(self, judged: dict) -> dict:
        """{opp_id: {"points": +/-x, "why": "...", "like": id}} for grants that resemble judged ones."""
        judged = {k: v for k, v in judged.items() if k in self._results}
        if not judged or self._tf is None:
            return {}
        good = [k for k, v in judged.items() if v == 1]
        bad = [k for k, v in judged.items() if v == 0]
        gv = [(k, self.vec(k)) for k in good]
        bv = [(k, self.vec(k)) for k in bad]
        out = {}
        for oid in self.ids:
            v = self.vec(oid)
            best_g = max(((sparse_cosine(v, w), k) for k, w in gv if k != oid), default=(0.0, None))
            best_b = max(((sparse_cosine(v, w), k) for k, w in bv if k != oid), default=(0.0, None))
            up = self._strength(best_g[0])
            down = self._strength(best_b[0])
            pts = round(MAX_POINTS * (up - down), 1)
            if abs(pts) < 0.5:
                continue
            like = best_g[1] if up >= down else best_b[1]
            title = self.titles.get(like, "")[:70]
            why = (f"+{pts:g}: similar to “{title}”, which your team marked as a good fit" if pts > 0 else
                   f"{pts:g}: similar to “{title}”, which your team marked as a poor fit")
            out[oid] = {"points": pts, "why": why, "like": like}
        return out

    @staticmethod
    def _strength(sim: float) -> float:
        if sim <= SIM_FLOOR:
            return 0.0
        return min(1.0, (sim - SIM_FLOOR) / (SIM_FULL - SIM_FLOOR))


def apply(results: list[dict], nudges: dict) -> list[dict]:
    """Copies of the results with the nudge added to the score (never below 0 or above 100), re-sorted."""
    out = []
    for x in results:
        n = nudges.get(x["record"]["id"])
        if n:
            y = dict(x, base_score=x["score"], feedback=n,
                     score=round(min(100.0, max(0.0, x["score"] + n["points"])), 1))
        else:
            y = dict(x, base_score=x["score"], feedback=None)
        out.append(y)
    out.sort(key=lambda x: (-x["score"], x["record"]["days_left"] if x["record"]["days_left"] is not None else 9999))
    return out


def agreement(before: list[dict], after: list[dict], judged: dict) -> tuple[float, float, int]:
    """Share of (good, poor-fit) pairs ranked the right way round, before and after the nudges."""
    def rate(order):
        pos = {x["record"]["id"]: i for i, x in enumerate(order)}
        goods = [k for k, v in judged.items() if v == 1 and k in pos]
        bads = [k for k, v in judged.items() if v == 0 and k in pos]
        pairs = [(g, b) for g in goods for b in bads]
        return (sum(pos[g] < pos[b] for g, b in pairs) / len(pairs) if pairs else 0.0), len(pairs)
    b, n = rate(before)
    a, _ = rate(after)
    return b, a, n
