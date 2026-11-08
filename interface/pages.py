"""Secondary pages: decisions, evaluation, method."""
import pandas as pd
import streamlit as st

from agency_profiles import loader
from common import config
from feedback import store as fb
from interface import components as ui
from interface import state
from interface import theme as T
from scoring.rank import rank
from scoring.survey import normalize


def reviewed(agency_id: str, survey: dict):
    profile = loader.get(agency_id)
    hist = fb.history(state.storage(), agency_id)
    if not hist:
        T.render('<div class="ffm-empty"><b>No decisions yet.</b>Open any match and record Pursue, Maybe or '
                 'Pass in the Decision tab.</div>')
        return
    latest = state.reviews(agency_id)
    counts = {a: sum(v["action"] == a for v in latest.values()) for a in fb.ACTIONS}
    T.render(f"""<div class="ffm-ledger">
<div><div class="v">{len(latest)}</div><div class="l">notices reviewed</div></div>
<div><div class="v">{counts['Pursue']}</div><div class="l">to pursue</div></div>
<div><div class="v">{counts['Maybe']}</div><div class="l">maybe</div></div>
<div><div class="v">{counts['Pass']}</div><div class="l">passed, with reasons</div></div></div>""")
    T.h2("Decision log", f"{len(hist)} actions recorded; full history is kept")
    df = pd.DataFrame([{"When": v["at"][:16].replace("T", " "), "Decision": v["action"], "Relevance": v.get("relevance"),
                        "Title": v["title"], "Reason": v.get("reason"), "Note": v.get("note"), "By": v.get("user"),
                        "Score then": v.get("score_at_review"), "Due": v.get("close_date"), "Listing": v.get("url")}
                       for v in sorted(latest.values(), key=lambda v: v["at"], reverse=True)])
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={"Listing": st.column_config.LinkColumn(display_text="Open")})
    out, reviews = state.get_ranked(agency_id, survey)
    by_id = {x["record"]["id"]: x for x in out["all"]}
    pick = st.selectbox("Revisit a notice", ["—"] + [f"{v['title'][:100]}|{k}" for k, v in latest.items() if k in by_id],
                        format_func=lambda v: v.split("|")[0])
    if pick != "—":
        x = state.light(by_id[pick.split("|")[1]], out, agency_id)
        ui.match_row(x, x.get("rank"), reviews.get(x["record"]["id"]), f"rv_{x['record']['id']}", profile, agency_id)


def evaluation_page():
    T.h2("Latest results", "run on demand; nothing is pre-filled")
    if st.button("Run the evaluation now", type="primary"):
        from evaluation import run_eval

        with st.spinner("Running the evaluation…"):
            run_eval.run(state.storage())
    res = state.storage().read_json("eval/latest.json")
    if not res:
        T.render('<div class="ffm-empty"><b>No evaluation has been run yet.</b>Click the button above. Precision and '
                 'recall need the team\'s hand labels in evaluation/labels.csv.</div>')
        return
    st.caption(f"Run at {res['run_at']} · {res['data']}")
    rows = "".join(f'<div><b>{T.e(t["result"])}</b>{T.e(t["test"])}<br><span style="font-size:.8rem">{T.e(t["detail"])}'
                   f'</span></div>' for t in res["tests"])
    T.render(f'<div class="ffm-kv">{rows}</div>')
    T.h2("Metrics", "from hand-labeled data")
    st.json(res["metrics"], expanded=True)
    if res.get("failures"):
        T.h2("Failures and limitations", "reported honestly")
        T.render('<ul class="ffm-list">' + "".join(f"<li>{T.e(f)}</li>" for f in res["failures"]) + "</ul>")


def about():
    st.markdown(open("docs/METHOD.md", encoding="utf-8").read())
