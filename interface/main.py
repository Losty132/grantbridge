"""App shell: top bar (wordmark, navigation, agency, settings), page header, routing."""
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from agency_profiles import loader
from data_retrieval.store import freshness_label
from interface import components as ui
from interface import dashboard, pages, state
from interface import survey as survey_page
from interface import theme as T

PAGES = ["Matches", "Decisions", "Evaluation", "Method"]
HEADLINES = {
    "Matches": ("Federal funding, <em>ranked</em> for your plan.",
                "Every open and forecasted federal notice, scored against your strategic objectives, screened for "
                "eligibility and timing, and explained with citations. You decide what to pursue."),
    "Decisions": ("What your team <em>decided</em>.", "Everything marked Pursue, Maybe or Pass, with reasons."),
    "Evaluation": ("Does it <em>actually</em> work?", "Precision, recall and safety tests, computed only from real "
                                                     "data and your team's labels."),
    "Method": ("How the <em>score</em> is made.", "Data sources, filters, scoring, eligibility, effort estimates and "
                                                  "privacy, in plain language."),
    "Setup": ("Sixty seconds to <em>better</em> matches.", "Six quick questions tell the matcher what matters to your "
                                                          "team right now. Change them any time."),
}


def run():
    T.inject()
    profiles = loader.load_all()
    ids = list(profiles)
    status = state.status()

    with st.container(key="topbar"):
        c1, c2, c3, c4 = st.columns([2.4, 4.6, 2.3, 1.0], vertical_alignment="center")
        with c1:
            T.render('<div class="ffm-wordmark"><span class="sq"></span><b>Federal Funds Matchmaker</b></div>')
        with c2:
            page = st.radio("Navigate", PAGES, key="page", horizontal=True, label_visibility="collapsed")
        with c3:
            agency_id = st.selectbox("Agency", ids, key="agency", label_visibility="collapsed",
                                     index=ids.index("deq") if "deq" in ids else 0,
                                     format_func=lambda a: f"{profiles[a]['short_name']} · "
                                                           f"{profiles[a]['name'].replace('NC Department of ', '').replace('Environmental', 'Env.')}")
        with c4:
            with st.popover("Settings", width="stretch"):
                st.text_input("Your name (recorded on decisions)", key="user_name", max_chars=60)
                if st.button("Edit survey answers", width="stretch"):
                    st.session_state["edit_survey"] = True
                    st.rerun()
                level, msg = freshness_label(status)
                st.caption(msg)
                if st.button("Refresh from Grants.gov now", width="stretch"):
                    from data_retrieval import refresh

                    with st.spinner("Pulling from Grants.gov…"):
                        try:
                            s = refresh.run(state.storage(), state.ai(), quick=True)
                            st.success(f"Refreshed {s['count']:,} opportunities.")
                        except Exception as e:
                            st.error(f"Refresh failed; still showing cached data. ({str(e)[:160]})")
                    state.data_changed()
                    st.rerun()

    profile = profiles[agency_id]
    saved = state.saved_survey(agency_id)
    editing = (page == "Matches" and saved is None) or st.session_state.get("edit_survey")
    view = (page, agency_id, bool(editing))
    T.inject_entrance(st.session_state.get("_last_view") != view)   # animate only when the view changes
    st.session_state["_last_view"] = view
    header(profile, status, "Setup" if editing else page)
    if st.session_state.get("survey_notice"):
        st.info(st.session_state.pop("survey_notice"))
    if editing:
        survey_page.render(agency_id)
        return
    survey = saved or {"agency_id": agency_id}
    if page == "Matches":
        dashboard.render(agency_id, survey)
    elif page == "Decisions":
        pages.reviewed(agency_id, survey)
    elif page == "Evaluation":
        pages.evaluation_page()
    else:
        pages.about()


def header(profile: dict, status: dict, page: str):
    level, msg = freshness_label(status)
    dot = {"live": "#0F8A4A", "cached": "#B26A00", "snapshot": "#1C3FE0"}.get(level, "#E5484D")
    dot_cls = "ffm-dot live" if level == "live" else "ffm-dot"
    when = ""
    try:
        when = datetime.fromisoformat(status["last_success"]).astimezone(ZoneInfo("America/New_York")).strftime("%b %d, %I:%M %p %Z")
    except (KeyError, TypeError, ValueError):
        pass
    label = {"live": f"Live from Grants.gov · updated {when}", "cached": f"Showing cached data from {when}; last refresh failed",
             "snapshot": "Snapshot replay (not live)"}.get(level, "No data yet")
    count = f" · {status['count']:,} notices" if status.get("count") else ""
    h1, lede = HEADLINES.get(page, HEADLINES["Matches"])
    plan = profile["plan"]
    T.render(f"""<div class="ffm-page">
<div class="ffm-eyebrow">{T.e(profile['name'])}</div>
<div class="ffm-h1">{h1}</div>
<div class="ffm-lede">{T.e(lede)} Matched against the <a href="{T.e(plan['url'])}" target="_blank"><b>{T.e(plan['title'])}</b></a>.</div>
<div class="ffm-status"><span class="{dot_cls}" style="background:{dot}"></span>{T.e(label)}{T.e(count)}</div>
<div class="ffm-privacy"><span class="ic">i</span><span><b>{T.e(ui.PUBLIC_BANNER)}</b> Anything you type is screened for
personal or internal information before it is saved or sent to an AI model.</span></div>
</div>""")
