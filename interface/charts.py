"""Two at-a-glance charts (Altair, ships with Streamlit). Single series each, so one ink hue; recessive axes;
hover tooltips on every mark; a labeled reference line instead of color-coding urgency."""
import altair as alt
import pandas as pd

INK, MUTED, RULE, CORAL = "#0E1A2B", "#5F6B7A", "#E3DFD5", "#E5484D"
FONT = "Public Sans, Segoe UI, system-ui, sans-serif"


def _config(chart):
    return (chart.configure_view(stroke=None)
            .configure(background="transparent", font=FONT)
            .configure_axis(labelColor=MUTED, titleColor=MUTED, labelFontSize=11, titleFontSize=11, titleFontWeight=600,
                            gridColor="#ECE8DE", domain=False, tickColor=RULE)
            .configure_title(font=FONT, fontSize=13, color=INK, anchor="start", fontWeight=700))


def by_goal(out: dict, profile: dict):
    goals = {o["id"]: f"Goal {o['goal_id']}: {o['goal_title']}" for o in profile["objectives"]}
    rows = []
    for x in out["shortlist"]:
        t = x["matched_target"]
        label = goals.get(t["id"]) or ("Your priority" if t["kind"] == "user" else t["label"][:40])
        rows.append({"goal": label, "funding": x["record"].get("award_ceiling") or 0})
    if not rows:
        return None
    df = pd.DataFrame(rows).groupby("goal").agg(matches=("goal", "size"), top_award=("funding", "max")).reset_index()
    df = df.sort_values("matches", ascending=False).head(8)
    bars = alt.Chart(df).mark_bar(color=INK, cornerRadiusEnd=4, height=16).encode(
        x=alt.X("matches:Q", title="Shortlisted notices", axis=alt.Axis(tickMinStep=1, format="d")),
        y=alt.Y("goal:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
        tooltip=[alt.Tooltip("goal:N", title="Plan goal"), alt.Tooltip("matches:Q", title="Shortlisted"),
                 alt.Tooltip("top_award:Q", title="Largest award ceiling", format="$,.0f")])
    labels = bars.mark_text(align="left", dx=6, color=INK, fontWeight=700, fontSize=12).encode(text="matches:Q")
    return _config((bars + labels).properties(height=max(120, 34 * len(df)),
                                              title="Where your matches land in the strategic plan"))


def runway(out: dict):
    rows = [{"title": x["record"]["title"][:80], "days": x["record"]["days_left"], "score": round(x["score"]),
             "funder": x["record"].get("agency", "")}
            for x in out["shortlist"] if x["record"].get("days_left") is not None and x["record"]["days_left"] >= 0]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["days_plot"] = df["days"].clip(upper=180)
    base = alt.Chart(df)
    zone = alt.Chart(pd.DataFrame({"x0": [0], "x1": [14]})).mark_rect(color=CORAL, opacity=0.07).encode(x="x0:Q", x2="x1:Q")
    rule = alt.Chart(pd.DataFrame({"x": [14]})).mark_rule(color=CORAL, strokeDash=[4, 4], strokeWidth=1.5).encode(x="x:Q")
    note = alt.Chart(pd.DataFrame({"x": [14], "y": [100], "t": ["due within 14 days"]})).mark_text(
        align="left", dx=6, dy=4, color=CORAL, fontSize=11, fontWeight=600).encode(x="x:Q", y="y:Q", text="t:N")
    dots = base.mark_circle(size=90, color=INK, opacity=0.85, stroke="#F6F4EE", strokeWidth=2).encode(
        x=alt.X("days_plot:Q", title="Days left to apply (capped at 180)", scale=alt.Scale(domain=[0, 180])),
        y=alt.Y("score:Q", title="Fit score", scale=alt.Scale(domain=[0, 100])),
        tooltip=[alt.Tooltip("title:N", title="Notice"), alt.Tooltip("funder:N", title="Funder"),
                 alt.Tooltip("days:Q", title="Days left"), alt.Tooltip("score:Q", title="Fit score")])
    return _config((zone + rule + note + dots).properties(height=280, title="Deadline runway: fit vs. time left"))
