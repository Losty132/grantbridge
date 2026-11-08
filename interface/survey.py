"""The 6-question survey (~60 seconds, click-only except the optional 'other priority')."""
import streamlit as st

from agency_profiles import loader
from common.text import md_safe
from feedback import store as fb
from interface import state
from interface import theme as T
from scoring import survey as sv


def render(agency_id: str):
    profile = loader.get(agency_id)
    saved = fb.get_survey(state.storage(), agency_id) or {}
    s = sv.normalize(saved)
    strength, why = loader.profile_strength(profile)
    def q(n, title, sub=""):
        T.render(f'<div class="ffm-qh"><span class="n">{n}</span><span class="t">{T.e(title)}</span>'
                 f'<span class="s">{T.e(sub)}</span></div>')

    q("01", f"Agency: {profile['name']}", "change it in the top bar")
    with st.form(f"survey_{agency_id}", border=False):
        q("02", "What is your team focused on right now?", "objectives from your strategic plan; picks get a boost")
        chosen = []
        goals = {}
        for o in profile["objectives"]:
            goals.setdefault((o["goal_id"], o["goal_title"]), []).append(o)
        for (gid, gtitle), objs in goals.items():
            with st.expander(f"Goal {gid}: {gtitle}", expanded=False):
                for o in objs:
                    if st.checkbox(f"{o['id']}: {o['text']}", value=o["id"] in s["focus_objectives"],
                                   key=f"q2_{agency_id}_{o['id']}"):
                        chosen.append(o["id"])
        topics = []
        if strength == "weak":
            st.warning("Profile weak: " + "; ".join(why) + ". Pick from the standard NC topic list as well.")
            cols = st.columns(3)
            for i, t in enumerate(loader.standard_topics()):
                if cols[i % 3].checkbox(t, value=t in s["focus_topics"], key=f"q2t_{agency_id}_{i}"):
                    topics.append(t)
        other = st.text_input("Other current priority or project (optional, public information only)",
                              value=s["other_priority"], max_chars=300,
                              placeholder="e.g. stream restoration and flood resilience")
        q("03", "How many applications can you take on this month?", "sets how many top matches you see")
        q3 = st.radio("How many applications can your team take on this month?", label_visibility="collapsed", options= sv.CAPACITY_OPTIONS,
                      index=sv.CAPACITY_OPTIONS.index(s["capacity"]), horizontal=True,
                      help="Sets how many top recommendations you see (1→3, 2→4, 3→5, 4→7, 5+→10).")
        q("04", "What is the smallest award worth your time?")
        q4 = st.radio("Minimum award worth pursuing", label_visibility="collapsed", options= list(sv.MIN_AWARD_OPTIONS),
                      index=list(sv.MIN_AWARD_OPTIONS).index(s["min_award"]), horizontal=True)
        q("05", "Can you provide a cost share or match?")
        q5 = st.radio("Can you provide cost share / match?", label_visibility="collapsed", options= sv.COST_SHARE_OPTIONS,
                      index=sv.COST_SHARE_OPTIONS.index(s["cost_share"]), horizontal=True)
        q("06", "How much lead time do you need to apply?")
        q6 = st.radio("Prep time you need to put an application together", label_visibility="collapsed", options= list(sv.PREP_OPTIONS),
                      index=list(sv.PREP_OPTIONS).index(s["prep_time"]), horizontal=True)
        st.write("")
        if st.form_submit_button("Save and show my matches", type="primary"):
            try:
                saved = fb.save_survey(state.storage(), agency_id, {
                    "focus_objectives": chosen, "focus_topics": topics, "other_priority": other, "capacity": q3,
                    "min_award": q4, "cost_share": q5, "prep_time": q6})
                if saved["other_priority"] != other.strip()[:300]:
                    st.session_state["survey_notice"] = ("Privacy filter redacted part of your 'other priority': "
                                                         + md_safe(saved["other_priority"]))
                st.session_state["edit_survey"] = False
                state.survey_changed()
                st.rerun()
            except fb.BlockedText as e:
                st.error(f"Not saved: {e}")
