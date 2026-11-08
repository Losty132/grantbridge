"""Matches page: ledger stats, ranked top matches + side panel, project search, full list, filtered-out list."""
import pandas as pd
import streamlit as st

from agency_profiles import loader
from common.text import TfIdf, sparse_cosine
from interface import charts
from interface import components as ui
from interface import state
from interface import theme as T
from privacy.filter import log_event, scan
from scoring.score import opp_text
from summarization.brief import next_action


def render(agency_id: str, survey: dict):
    profile = loader.get(agency_id)
    with st.spinner("Scoring opportunities against your plan…"):
        out, reviews = state.get_ranked(agency_id, survey)
    if not out["all"]:
        T.render('<div class="ffm-empty"><b>No opportunities loaded yet.</b>Open <b>Settings → Refresh from '
                 'Grants.gov</b>, or wait for the scheduled 6 AM refresh.</div>')
        return
    s = out["survey"]
    urgent = sum(1 for x in out["shortlist"] if x["record"].get("days_left") is not None and x["record"]["days_left"] <= 14)
    elig = sum(1 for x in out["shortlist"] if x["eligibility"]["label"] == "Appears Eligible")
    T.render(f"""<div class="ffm-ledger">
<div><div class="v">{len(out['all']):,}</div><div class="l">federal notices reviewed</div></div>
<div><div class="v">{len(out['shortlist']):,}</div><div class="l">passed your filters · {elig:,} directly eligible</div></div>
<div><div class="v hot">{urgent}</div><div class="l">due within 14 days</div></div>
<div><div class="v">{len(out['filtered']):,}</div><div class="l">set aside, each with a reason</div></div>
</div>""")

    top = [state.light(x, out, agency_id) for x in out["top"]]
    top.sort(key=lambda x: (-x["score"], x["record"]["days_left"] if x["record"]["days_left"] is not None else 9999))

    left, right = st.columns([7.2, 3], gap="large")
    with left:
        T.h2(f"Best matches for {profile['short_name']}", f"top {len(top)} of {len(out['shortlist']):,}")
        if not top:
            T.render('<div class="ffm-empty"><b>Nothing passed your filters.</b>See “Set aside” below, or loosen '
                     'your answers in Settings → Edit survey answers.</div>')
        for i, x in enumerate(top, 1):
            ui.match_row(x, i, reviews.get(x["record"]["id"]), f"top_{x['record']['id']}", profile, agency_id)
    with right:
        soon = sorted([x for x in out["shortlist"] if x["record"].get("days_left") is not None
                       and 0 <= x["record"]["days_left"] <= 30], key=lambda x: x["record"]["days_left"])[:5]
        rows = "".join(
            f'<div class="ffm-due"><div class="d {"hot" if x["record"]["days_left"] <= 14 else ""}">'
            f'{x["record"]["days_left"]}<small>DAYS</small></div><div><div class="x">{T.e(x["record"]["title"][:90])}</div>'
            f'<div class="y">{T.e(next_action(x))}</div></div></div>' for x in soon) or \
            '<div class="ffm-due"><div class="d">0</div><div><div class="x">Nothing on your shortlist is due in the next 30 days.</div></div></div>'
        T.render(f'<div class="ffm-panel"><h4>Due soon</h4><div class="sub">Shortlisted items closing within 30 days</div>{rows}</div>')
        counts = {}
        for x in out["filtered"]:
            for reason in x["excluded"]:
                k = reason.split(":")[0].split("(")[0].strip()
                counts[k] = counts.get(k, 0) + 1
        crow = "".join(f'<div class="row"><span>{T.e(k)}</span><b>{v:,}</b></div>'
                       for k, v in sorted(counts.items(), key=lambda t: -t[1])[:6])
        T.render(f'<div class="ffm-panel2"><h4>Why items were set aside</h4>{crow or "<div class=row>None</div>"}</div>')
        T.render(f'<div class="ffm-panel2"><h4>Your settings</h4>'
                 f'<div class="row"><span>Applications this month</span><b>{T.e(s["capacity"])}</b></div>'
                 f'<div class="row"><span>Minimum award</span><b>{T.e(s["min_award"])}</b></div>'
                 f'<div class="row"><span>Can provide match</span><b>{T.e(s["cost_share"])}</b></div>'
                 f'<div class="row"><span>Prep time needed</span><b>{T.e(s["prep_time"])}</b></div>'
                 f'<div class="row"><span>Matching method</span><b>{T.e(out["similarity_method"])}</b></div></div>')

    # ---- at a glance
    T.h2("At a glance", "hover any bar or dot for details")
    c1, c2 = st.columns(2, gap="large")
    g = charts.by_goal(out, profile)
    r = charts.runway(out)
    if g is not None:
        c1.altair_chart(g, width="stretch")
    if r is not None:
        c2.altair_chart(r, width="stretch")

    # ---- project search
    T.h2("Search by project", "describe a project; we'll find the closest notices")
    q = st.text_input("Project", key=f"proj_{agency_id}", max_chars=300, label_visibility="collapsed",
                      placeholder="e.g. stream restoration and flood resilience in eastern North Carolina")
    if q:
        res = scan(q)
        log_event(state.storage(), "project search", res)
        if res.blocked:
            st.error(res.summary())
        else:
            if res.changed:
                st.info("Screened: " + res.summary())
            pool = out["shortlist"]
            tf = TfIdf([opp_text(x["record"]) for x in pool] + [res.text])
            qv = tf.vector(res.text)
            hits = [(sim, x) for sim, x in sorted(((sparse_cosine(tf.vector(opp_text(x["record"])), qv), x) for x in pool),
                                                  key=lambda t: -t[0])[:6] if sim > 0.03]
            if not hits:
                st.caption("No shortlisted notices match that description.")
            for _, x in hits:
                xx = state.light(x, out, agency_id)
                ui.match_row(xx, x.get("rank"), reviews.get(xx["record"]["id"]), f"ps_{xx['record']['id']}",
                             profile, agency_id, show_quote=False)

    # ---- full list
    T.h2("Everything on your shortlist", "filter, sort, export")
    f1, f2, f3, f4 = st.columns(4)
    min_score = f1.slider("Minimum score", 0, 100, 0, 5)
    within = f2.selectbox("Due within", ["Any time", "7 days", "14 days", "30 days", "60 days", "90 days"])
    min_fund = f3.selectbox("Award ceiling at least", ["Any", "$50K", "$250K", "$1M"])
    rstatus = f4.multiselect("Decision", ["None yet", "Pursue", "Maybe", "Pass"],
                             default=["None yet", "Pursue", "Maybe"])
    text = st.text_input("Filter by words in the title or description", key=f"txt_{agency_id}")
    fund_v = {"Any": 0, "$50K": 50_000, "$250K": 250_000, "$1M": 1_000_000}[min_fund]
    days_v = None if within == "Any time" else int(within.split()[0])
    rows = []
    for x in out["shortlist"]:
        r = x["record"]
        rv = reviews.get(r["id"], {}).get("action", "None yet")
        if x["score"] < min_score or rv not in rstatus:
            continue
        if days_v is not None and (r["days_left"] is None or r["days_left"] > days_v):
            continue
        if fund_v and (not r.get("award_ceiling") or r["award_ceiling"] < fund_v):
            continue
        if text and text.lower() not in (r["title"] + " " + r.get("description", "")).lower():
            continue
        rows.append({"#": x.get("rank"), "Score": round(x["score"]), "Title": r["title"], "Funder": r.get("agency"),
                     "Eligibility": ui.ELIG_SHORT.get(x["eligibility"]["label"]), "Due": r.get("close_date"),
                     "Days": r.get("days_left"), "Award ceiling": r.get("award_ceiling"), "Status": r.get("status"),
                     "Decision": rv, "Listing": r["url"], "_id": r["id"]})
    df = pd.DataFrame(rows)
    if df.empty:
        st.caption("No notices match these filters.")
    else:
        st.dataframe(df.drop(columns=["_id"]), hide_index=True, width="stretch", height=420,
                     column_config={"Listing": st.column_config.LinkColumn("Listing", display_text="Open"),
                                    "Award ceiling": st.column_config.NumberColumn(format="$%d"),
                                    "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d")})
        st.download_button("Export this list (CSV)", df.drop(columns=["_id"]).to_csv(index=False).encode(),
                           file_name=f"{agency_id}_shortlist.csv")
        by_id = {x["record"]["id"]: x for x in out["shortlist"]}
        pick = st.selectbox("Open any notice", ["—"] + [f"{r['#']}. {r['Title'][:100]}|{r['_id']}" for r in rows],
                            format_func=lambda v: v.split("|")[0])
        if pick != "—":
            x = state.light(by_id[pick.split("|")[1]], out, agency_id)
            ui.match_row(x, x.get("rank"), reviews.get(x["record"]["id"]), f"pick_{x['record']['id']}", profile, agency_id)

    # ---- filtered out
    T.h2("Set aside", f"{len(out['filtered']):,} notices, each with the rule that removed it")
    with st.expander("Show the list"):
        st.dataframe(pd.DataFrame([{
            "Score before rule": round(x["score"]), "Title": x["record"]["title"], "Why": " | ".join(x["excluded"]),
            "Eligibility": x["eligibility"]["label"], "Due": x["record"].get("close_date"), "Listing": x["record"]["url"]}
            for x in out["filtered"][:500]]), hide_index=True, width="stretch",
            column_config={"Listing": st.column_config.LinkColumn(display_text="Open")})
