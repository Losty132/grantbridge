"""Reusable UI pieces: ranked match row, detail panel (opened on demand), review form."""
from datetime import date

import streamlit as st

from eligibility.classify import APPEARS, NOT_ELIGIBLE, PARTNER, VERIFY
from feedback import store as fb
from interface import state
from interface import theme as T
from privacy.filter import log_event, scan
from summarization import brief

ELIG_TONE = {APPEARS: "ok", VERIFY: "warn", PARTNER: "info", NOT_ELIGIBLE: "hot"}
ELIG_SHORT = {APPEARS: "Eligible to apply", VERIFY: "Verify eligibility", PARTNER: "Partner must apply",
              NOT_ELIGIBLE: "Not eligible"}
PUBLIC_BANNER = "Public information only. Do not enter confidential data."


def money_short(v) -> str:
    if not v:
        return "—"
    return f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"


def funding(r: dict) -> str:
    lo, hi = r.get("award_floor"), r.get("award_ceiling")
    if lo and hi:
        return f"{money_short(lo)}–{money_short(hi)}"
    return f"Up to {money_short(hi)}" if hi else "Not specified"


def nice_date(iso: str | None) -> str:
    if not iso:
        return "Not listed"
    try:
        d = date.fromisoformat(iso)
        return f"{d:%b} {d.day}, {d.year}"
    except ValueError:
        return iso


def due(r: dict) -> str:
    d = r.get("days_left")
    if not r.get("close_date"):
        return "Not listed"
    if d is not None and d >= 0:
        return f"{nice_date(r['close_date'])} · {d}d"
    return f"{nice_date(r['close_date'])} · closed"


def deadline_text(r: dict) -> str:
    return due(r)


def tags(x: dict, review: dict | None) -> str:
    r = x["record"]
    out = [T.tag(ELIG_SHORT.get(x["eligibility"]["label"], x["eligibility"]["label"]),
                 ELIG_TONE.get(x["eligibility"]["label"], ""))]
    d = r.get("days_left")
    if r.get("status") == "forecasted":
        out.append(T.tag("Forecast: not open yet", "info"))
    elif r.get("status") == "expired":
        out.append(T.tag("Closed", ""))
    elif d is not None and d <= 14:
        out.append(T.tag(f"Due in {d} days", "hot"))
    f = (x.get("feasibility") or {}).get("status")
    if f == "not_enough":
        out.append(T.tag("Not enough time", "hot"))
    elif f == "tight":
        out.append(T.tag("Tight timeline", "warn"))
    if x.get("needs_review"):
        out.append(T.tag("Needs a second look", "warn"))
    if review:
        out.append(T.tag(review["action"], "done"))
    return "".join(out)


def match_row(x: dict, rank: int | None, review: dict | None, key: str, profile: dict, agency_id: str,
              show_quote: bool = True, out_key: str | None = None):
    r, est = x["record"], x.get("estimate") or {}
    expl = x.get("explanation") or {}
    score = x["score"]
    tgt = x["matched_target"]
    sup_id, _, sup_text = tgt["label"].partition(": ")
    if not sup_text:
        sup_id, sup_text = "", tgt["label"]
    quote = ""
    if show_quote and expl.get("grant_evidence_quote"):
        q = expl["grant_evidence_quote"]
        q = q if len(q) <= 220 else q[:220].rsplit(" ", 1)[0] + "…"
        quote = f'<div class="ffm-q">“{T.e(q)}”</div>'
    rk = f"{rank:02d}" if rank else "—"
    delay = f"animation-delay:{0.45 + 0.09 * (rank or 0):.2f}s" if rank else ""
    T.render(f"""<div class="ffm-match" style="{delay}">
<div class="ffm-rk">{rk}</div>
<div>
  <div class="ffm-t">{T.e(r['title'])}</div>
  <div class="ffm-f">{T.e(r.get('agency'))} · {T.e(r.get('number'))}</div>
  <div class="ffm-facts">
    <div><small>Award</small>{T.e(funding(r))}</div>
    <div><small>Due</small>{T.e(due(r))}</div>
    <div><small>Effort</small>{T.e(est.get('level', 'Unknown'))}</div>
  </div>
  <div class="ffm-sup"><b>{T.e(sup_id or 'Supports')}</b> {T.e(sup_text[:200])}</div>
  {quote}
  <div class="ffm-tags">{tags(x, review)}</div>
</div>
<div class="ffm-score"><div class="n">{score:.0f}<small> /100</small></div>
  <div class="bar"><i class="{'hi' if score >= 70 else ''}" style="width:{max(0, min(100, score)):.0f}%"></i></div>
  <div class="l">Fit score</div></div>
</div>""")
    open_key = f"open_{key}"
    with st.container(key=f"det_{key}"):
        label = "Hide details" if st.session_state.get(open_key) else "Evidence, eligibility, effort and brief →"
        if st.button(label, key=f"btn_{key}"):
            st.session_state[open_key] = not st.session_state.get(open_key, False)
            st.rerun()
    if st.session_state.get(open_key):
        full = state.enrich(x, state.current_out(out_key or agency_id), agency_id)
        with st.container(key=f"panel_{key}"):
            detail(full, agency_id, profile, review, key)


def detail(x: dict, agency_id: str, profile: dict, review: dict | None, key: str):
    r, e, est, expl = x["record"], x["eligibility"], x["estimate"], x["explanation"]
    tabs = st.tabs(["Why it fits", "Eligibility", "Effort & timing", "Brief", "Decision"])
    with tabs[0]:
        a, b = st.columns([3, 2], gap="large")
        with a:
            T.render(T.k("Score breakdown · a priority score, not a probability of winning") + T.bars(x["components"]))
        with b:
            link = (f' · <a href="{T.e(expl["objective_url"])}" target="_blank">open plan</a>'
                    if expl.get("objective_url") else "")
            T.render(T.k("Strategic objective")
                     + T.note(f"<b>{T.e(expl.get('matched_label'))}</b><br><span style='font-size:.8rem'>"
                              f"{T.e(expl.get('objective_citation'))}{link}</span>", "info"))
            if x.get("matched_program") and (x.get("program_alignment") or 0) >= 0.5:
                src = (x["matched_program"].get("citation") or {}).get("url")
                T.render(T.k("Related agency program") + T.note(
                    f"<b>{T.e(x['matched_program']['label'])}</b>"
                    + (f' · <a href="{T.e(src)}" target="_blank">source</a>' if src else ""), "ok"))
            conf = expl["confidence"]
            T.render(T.k("Confidence") + T.note(
                f"<b>{T.e(conf.capitalize())}</b>" + (" · needs a second look" if x.get("needs_review") else "")
                + f"<br><span style='font-size:.8rem'>{T.e(expl.get('source'))}</span>",
                {"high": "ok", "medium": "info", "low": "warn"}[conf]))
        T.render(T.k("Evidence")
                 + T.cite(x["matched_target"]["label"], "Strategic plan objective (close summary of the plan wording)")
                 + T.cite(expl.get("grant_evidence_quote", ""), "Federal notice, quoted word for word"))
        T.render(T.k("Reasons") + '<ul class="ffm-list">'
                 + "".join(f"<li>{T.e(reason)}</li>" for reason in expl.get("reasons", [])) + "</ul>")
        for n in expl.get("verification", {}).get("notes", []):
            st.warning("Check: " + n)
    with tabs[1]:
        T.render(T.note(f"<b>{T.e(e['label'])}</b><br>" + "<br>".join(T.e(s) for s in e["reasons"])
                        + f"<br><span style='font-size:.78rem'>{T.e(e['method'])}</span>",
                        ELIG_TONE.get(e["label"], "")))
        if e["citations"]:
            T.render(T.k("From the notice") + "".join(T.cite(c["quote"], c["source"]) for c in e["citations"]))
        cond = e["conditions"]
        for title, items in (("Matching funds", cond["matching"]), ("No match required", cond["no_match"]),
                             ("Partners and letters", cond["partnership"]), ("Other conditions", cond["other"])):
            if items:
                T.render(T.k(title) + "".join(T.cite(c["quote"], c["source"]) for c in items))
        if e["open_questions"]:
            T.render(T.k("Questions to resolve") + '<ul class="ffm-list">'
                     + "".join(f"<li>{T.e(q)}</li>" for q in e["open_questions"]) + "</ul>")
    with tabs[2]:
        f = x["feasibility"]
        tone = {"feasible": "ok", "tight": "warn", "not_enough": "hot"}.get(f.get("status"), "")
        T.render(T.note(f"<b>{T.e(est['level'])} effort.</b> {T.e(est['summary'])}<br><b>{T.e(f.get('text', ''))}</b>"
                        f"<br><span style='font-size:.78rem'>{T.e(est['label'])} · based on {T.e(est['basis'])}</span>", tone))
        if est["drivers"]:
            T.render(T.k("What drives the effort") + "".join(
                T.cite(d["quote"], f"{d['detail']} (+{d['points']}) · {d['source']}") for d in est["drivers"]))
        nofo = x.get("nofo") or {}
        if nofo.get("source"):
            st.caption(f"Full notice PDF read: {nofo['source']}")
        elif nofo.get("error") and nofo.get("error") != "not attempted":
            st.caption(f"Full notice PDF not read: {nofo['error']}")
    with tabs[3]:
        notes = st.text_area("Notes to include (optional; screened for personal or internal information)",
                             key=f"notes_{key}", max_chars=1000, height=80)
        res = scan(notes)
        if notes and res.changed:
            st.info("Screened: " + res.summary())
        if res.blocked:
            st.error(res.summary())
        else:
            b = brief.build(x, expl, profile, state.data_label(state.status()), res.text)
            txt = brief.to_text(b)
            if notes:
                log_event(state.storage(), "brief notes", res)
            c1, c2, c3 = st.columns(3)
            c1.download_button("Download PDF", brief.to_pdf(b), file_name=f"brief_{r['number'] or r['id']}.pdf",
                               mime="application/pdf", key=f"dlp_{key}", width="stretch")
            c2.download_button("Download text", txt.encode(), file_name=f"brief_{r['number'] or r['id']}.txt",
                               key=f"dlt_{key}", width="stretch")
            c3.link_button("Official listing", r["url"], width="stretch")
            with st.expander("Preview the brief"):
                st.code(txt, language=None)
    with tabs[4]:
        if review:
            T.render(T.note(f"<b>Last decision: {T.e(review['action'])}</b>"
                            f" · {T.e(review.get('relevance') or 'no mark')} · {T.e(review.get('user') or 'unknown')}"
                            f" · {T.e(review['at'][:10])}<br>Reason: {T.e(review.get('reason') or '—')}"
                            f" · Note: {T.e(review.get('note') or '—')}", "info"))
        with st.form(f"rev_{key}", border=False):
            c1, c2 = st.columns(2)
            action = c1.radio("Decision", fb.ACTIONS, horizontal=True, key=f"act_{key}")
            relevance = c2.radio("Relevance", ["relevant", "irrelevant", "needs investigation", ""], horizontal=True,
                                 format_func=lambda v: v or "skip", index=3, key=f"relv_{key}")
            reason = st.text_input("Reason (required to pass)", key=f"reason_{key}", max_chars=300)
            note_txt = st.text_input("Note (optional)", key=f"note_{key}", max_chars=500)
            if st.form_submit_button("Save decision", type="primary"):
                try:
                    fb.record(state.storage(), agency_id, x, action, relevance, reason, note_txt,
                              st.session_state.get("user_name", ""))
                    shown = scan(reason + " " + note_txt)
                    state.reviews_changed()
                    st.success("Saved." + (" Screened: " + shown.summary() if shown.changed else ""))
                    st.rerun()
                except fb.BlockedText as err:
                    st.error(f"Not saved. {err}")
                except ValueError as err:
                    st.error(str(err))
