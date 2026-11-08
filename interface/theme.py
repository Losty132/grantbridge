"""Design system. Editorial, high-contrast: warm paper, deep ink, one lime highlight, Fraunces display serif.
All text from Grants.gov or users is html-escaped before it is placed in HTML."""
import html

import streamlit as st

INK = "#0E1A2B"
ACCENT = "#1C3FE0"
LIME = "#C8F25A"
CORAL = "#E5484D"
GREEN = "#0F8A4A"
AMBER = "#B26A00"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700;9..144,800&family=Public+Sans:wght@400;500;600;700&display=swap');
:root{--ink:#0E1A2B;--ink2:#22314A;--muted:#5F6B7A;--faint:#8A94A3;--rule:#E3DFD5;--paper:#F6F4EE;--card:#FFFFFF;
  --accent:#1C3FE0;--lime:#C8F25A;--coral:#E5484D;--green:#0F8A4A;--amber:#B26A00;
  --serif:'Fraunces',Georgia,'Times New Roman',serif;--sans:'Public Sans','Segoe UI',system-ui,sans-serif;}
html, body, .stApp, .stMarkdown, p, li, label, input, textarea, button, select{font-family:var(--sans) !important;}
.stApp{background:var(--paper);color:var(--ink);}
.block-container{padding-top:0 !important;padding-bottom:5rem;max-width:1360px;}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], header[data-testid="stHeader"],
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"]{display:none !important;}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px;}
.num{font-variant-numeric:tabular-nums;}

/* ---------- top bar (Streamlit container with key='topbar') ---------- */
.st-key-topbar{background:var(--ink);margin:12px 0 0 0;padding:12px 22px 6px 22px !important;
  border-bottom:3px solid var(--lime);}
.st-key-topbar [role="radiogroup"]{flex-wrap:nowrap !important;gap:0 !important;}
.st-key-topbar p, .st-key-topbar label, .st-key-topbar span{color:#E8ECF2 !important;}
.ffm-wordmark{display:flex;align-items:center;gap:10px;white-space:nowrap;}
.ffm-wordmark .sq{width:12px;height:12px;background:var(--lime);display:inline-block;}
.ffm-wordmark b{font-family:var(--serif);font-weight:700;font-size:1.22rem;color:#fff;letter-spacing:-0.01em;}
.st-key-topbar [data-testid="stRadioOption"]{padding:6px 2px 8px 2px;margin-right:22px;white-space:nowrap;border-bottom:2px solid transparent;
  border-radius:0;cursor:pointer;}
.st-key-topbar [data-testid="stRadioOption"] > div > div:first-child{display:none;}
.st-key-topbar [data-testid="stRadioOption"] p{font-weight:600;font-size:.9rem;color:#B8C4D4 !important;}
.st-key-topbar [data-testid="stRadioOption"][data-selected="true"]{border-bottom-color:var(--lime);}
.st-key-topbar [data-testid="stRadioOption"][data-selected="true"] p{color:#fff !important;}
.st-key-topbar [data-testid="stRadioOption"]:hover p{color:#fff !important;}
.st-key-topbar div[data-baseweb="select"] > div{background:#17263C !important;border:1px solid #2C3D57 !important;
  border-radius:8px !important;color:#fff !important;}
.st-key-topbar div[data-baseweb="select"] *{color:#fff !important;}
.st-key-topbar [data-testid="stPopover"] button{background:#17263C !important;border:1px solid #2C3D57 !important;color:#fff !important;
  border-radius:8px !important;}
.st-key-topbar [data-testid="stPopover"] button p{color:#fff !important;}

/* ---------- typography ---------- */
.ffm-page{padding:34px 0 8px;}
.ffm-eyebrow{font-size:.74rem;letter-spacing:.16em;text-transform:uppercase;font-weight:700;color:var(--muted);}
.ffm-h1{font-family:var(--serif);font-size:3.1rem;line-height:1.02;font-weight:700;color:var(--ink);letter-spacing:-0.025em;
  margin:.35rem 0 .7rem;}
.ffm-h1 em{font-style:normal;background:linear-gradient(var(--lime),var(--lime)) no-repeat 0 88%/100% 40%;padding:0 .08em;}
.ffm-lede{font-size:1.02rem;color:var(--ink2);max-width:860px;line-height:1.55;}
.ffm-lede b{color:var(--ink);}
.ffm-status{display:inline-flex;align-items:center;gap:8px;font-size:.84rem;color:var(--ink2);margin-top:12px;
  padding:6px 12px;border:1px solid var(--rule);background:#fff;border-radius:999px;}
.ffm-dot{width:8px;height:8px;border-radius:50%;display:inline-block;box-shadow:0 0 0 3px rgba(0,0,0,.04);}
.ffm-h2{font-family:var(--serif);font-size:1.7rem;font-weight:700;letter-spacing:-0.015em;color:var(--ink);margin:0;}
.ffm-h2row{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid var(--ink);
  padding-bottom:8px;margin:34px 0 4px;}
.ffm-h2row span{font-size:.84rem;color:var(--muted);}

/* ---------- ledger stats ---------- */
.ffm-ledger{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);
  margin:26px 0 6px;}
.ffm-ledger > div{padding:18px 22px;border-right:1px solid var(--rule);}
.ffm-ledger > div:last-child{border-right:none;}
.ffm-ledger .v{font-family:var(--serif);font-size:2.6rem;font-weight:700;line-height:1;color:var(--ink);font-variant-numeric:tabular-nums;}
.ffm-ledger .v.hot{color:var(--coral);}
.ffm-ledger .l{font-size:.8rem;color:var(--muted);margin-top:6px;font-weight:500;}

/* ---------- ranked matches ---------- */
.ffm-match{display:grid;grid-template-columns:78px 1fr 132px;gap:22px;padding:24px 0 14px;border-bottom:1px solid var(--rule);}
.ffm-rk{font-family:var(--serif);font-size:3rem;font-weight:700;line-height:.9;color:var(--accent);font-variant-numeric:tabular-nums;}
.ffm-t{font-family:var(--serif);font-size:1.32rem;font-weight:600;line-height:1.25;color:var(--ink);letter-spacing:-0.01em;}
.ffm-f{font-size:.82rem;color:var(--muted);margin:5px 0 12px;font-weight:500;}
.ffm-facts{display:flex;flex-wrap:wrap;gap:26px;margin-bottom:12px;}
.ffm-facts div{font-size:.95rem;color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums;}
.ffm-facts div small{display:block;font-size:.68rem;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);font-weight:700;margin-bottom:2px;}
.ffm-sup{font-size:.9rem;color:var(--ink2);line-height:1.5;border-left:3px solid var(--lime);padding:2px 0 2px 12px;}
.ffm-sup b{color:var(--ink);}
.ffm-q{font-size:.86rem;color:var(--muted);margin-top:8px;font-style:italic;line-height:1.5;}
.ffm-tags{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;}
.ffm-tag{display:inline-flex;align-items:center;gap:6px;font-size:.76rem;font-weight:700;color:var(--ink2);
  padding:3px 10px 3px 8px;border:1px solid var(--rule);border-radius:4px;background:#fff;}
.ffm-tag::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--faint);}
.t-ok::before{background:var(--green);} .t-warn::before{background:var(--amber);} .t-hot::before{background:var(--coral);}
.t-info::before{background:var(--accent);} .t-done{background:var(--ink);color:#fff;border-color:var(--ink);} .t-done::before{background:var(--lime);}
.ffm-score{text-align:right;}
.ffm-score .n{font-family:var(--serif);font-size:2.9rem;font-weight:700;line-height:.9;color:var(--ink);font-variant-numeric:tabular-nums;}
.ffm-score .n small{font-size:.9rem;color:var(--faint);font-family:var(--sans);font-weight:600;}
.ffm-score .bar{height:6px;background:#E9E5DA;margin:10px 0 6px auto;width:100%;}
.ffm-score .bar i{display:block;height:100%;background:var(--ink);}
.ffm-score .bar i.hi{background:linear-gradient(90deg,var(--ink),var(--accent));}
.ffm-score .l{font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);font-weight:700;}

/* ---------- side panel ---------- */
.ffm-panel{background:var(--ink);color:#E8ECF2;padding:24px 24px 18px;margin-top:22px;}
.ffm-panel h4{font-family:var(--serif);font-size:1.35rem;color:#fff;margin:0 0 4px;font-weight:700;}
.ffm-panel .sub{font-size:.8rem;color:#9FB0C6;margin-bottom:12px;}
.ffm-due{display:grid;grid-template-columns:58px 1fr;gap:12px;padding:12px 0;border-top:1px solid #23344F;}
.ffm-due .d{font-family:var(--serif);font-size:1.9rem;font-weight:700;color:var(--lime);line-height:1;font-variant-numeric:tabular-nums;}
.ffm-due .d.hot{color:#FF8A8D;}
.ffm-due .d small{display:block;font-family:var(--sans);font-size:.62rem;letter-spacing:.12em;color:#9FB0C6;font-weight:700;margin-top:3px;}
.ffm-due .x{font-size:.86rem;color:#fff;font-weight:600;line-height:1.35;}
.ffm-due .y{font-size:.78rem;color:#B8C4D4;margin-top:4px;line-height:1.4;}
.ffm-panel2{background:#fff;border:1px solid var(--rule);padding:20px 22px;margin-top:16px;}
.ffm-panel2 h4{font-family:var(--serif);font-size:1.15rem;margin:0 0 10px;color:var(--ink);}
.ffm-panel2 .row{display:flex;justify-content:space-between;font-size:.86rem;padding:6px 0;border-top:1px solid #EFEBE2;color:var(--ink2);}
.ffm-panel2 .row b{font-variant-numeric:tabular-nums;color:var(--ink);}

/* ---------- streamlit widgets ---------- */
.stButton > button, .stDownloadButton > button, .stLinkButton > a, .stFormSubmitButton > button{border-radius:6px !important;
  font-weight:600 !important;border:1px solid var(--ink) !important;background:#fff !important;color:var(--ink) !important;
  box-shadow:none !important;transition:all .12s ease;}
.stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover{background:var(--ink) !important;color:#fff !important;}
.stButton > button:hover p, .stDownloadButton > button:hover p, .stLinkButton > a:hover p{color:#fff !important;}
.stFormSubmitButton > button[kind="primaryFormSubmit"], .stButton > button[kind="primary"]{background:var(--ink) !important;
  color:#fff !important;}
.stFormSubmitButton > button[kind="primaryFormSubmit"] p, .stButton > button[kind="primary"] p{color:#fff !important;}
[class*="st-key-det_"] .stButton > button{border:none !important;background:transparent !important;color:var(--accent) !important;
  padding:0 !important;min-height:0 !important;font-weight:700 !important;}
[class*="st-key-det_"] .stButton > button p{color:var(--accent) !important;font-size:.86rem !important;}
[class*="st-key-det_"] .stButton > button:hover{background:transparent !important;}
[class*="st-key-det_"] .stButton > button:hover p{color:var(--ink) !important;text-decoration:underline;}
div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div{border-radius:6px !important;}
div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:0 !important;border:1px solid var(--rule) !important;background:#fff;}
div[data-testid="stExpander"] details{border-radius:0 !important;border:1px solid var(--rule) !important;background:#fff;}
[role="tablist"]{gap:26px !important;border-bottom:1px solid var(--rule) !important;}
[data-testid="stTab"]{padding:10px 0 !important;background:transparent !important;border-bottom:2px solid transparent;border-radius:0 !important;}
[data-testid="stTab"] p{font-weight:600 !important;color:var(--muted) !important;font-size:.9rem !important;}
[data-testid="stTab"][data-selected="true"]{border-bottom:2px solid var(--ink);}
[data-testid="stTab"][data-selected="true"] p{color:var(--ink) !important;}
.react-aria-SelectionIndicator{display:none !important;}
[data-testid="stDataFrame"]{border:1px solid var(--rule);}

/* ---------- detail content ---------- */
.ffm-detail{background:#fff;border:1px solid var(--rule);border-top:3px solid var(--ink);padding:6px 24px 18px;margin:4px 0 10px 100px;}
.ffm-k{font-size:.7rem;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);font-weight:700;margin:16px 0 6px;}
.ffm-bars{display:flex;flex-direction:column;gap:14px;}
.ffm-bar .h{display:flex;justify-content:space-between;font-size:.88rem;font-weight:600;color:var(--ink);}
.ffm-bar .h span{font-variant-numeric:tabular-nums;color:var(--ink);font-weight:700;}
.ffm-bar .track{height:6px;background:#EEEAE0;margin:6px 0 4px;}
.ffm-bar .fill{height:100%;background:var(--ink);}
.ffm-bar .w{font-size:.8rem;color:var(--muted);line-height:1.45;}
.ffm-note{padding:12px 16px;font-size:.9rem;line-height:1.5;margin:8px 0;border-left:4px solid var(--ink);background:#FBFAF6;color:var(--ink2);}
.n-ok{border-left-color:var(--green);} .n-warn{border-left-color:var(--amber);} .n-hot{border-left-color:var(--coral);}
.n-info{border-left-color:var(--accent);} .ffm-note b{color:var(--ink);}
.ffm-cite{font-family:var(--serif);font-size:1.02rem;line-height:1.5;color:var(--ink);margin:10px 0;padding-left:16px;
  border-left:3px solid var(--lime);}
.ffm-cite span{display:block;font-family:var(--sans);font-size:.74rem;color:var(--muted);margin-top:4px;}
.ffm-list{margin:4px 0 6px;padding-left:18px;} .ffm-list li{font-size:.9rem;color:var(--ink2);margin:4px 0;line-height:1.5;}
.ffm-kv{display:grid;grid-template-columns:repeat(2,1fr);gap:0 24px;}
.ffm-kv div{padding:8px 0;border-bottom:1px solid #EFEBE2;font-size:.88rem;color:var(--ink2);}
.ffm-kv div b{display:block;font-size:.68rem;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);margin-bottom:2px;}

/* ---------- survey ---------- */
.ffm-q{counter-increment:none;}
.ffm-qh{display:flex;gap:14px;align-items:baseline;margin:22px 0 4px;}
.ffm-qh .n{font-family:var(--serif);font-weight:700;color:var(--accent);font-size:1.5rem;font-variant-numeric:tabular-nums;}
.ffm-qh .t{font-family:var(--serif);font-weight:600;font-size:1.22rem;color:var(--ink);}
.ffm-qh .s{font-size:.82rem;color:var(--muted);margin-left:auto;}
.ffm-privacy{font-size:.82rem;color:var(--ink2);border:1px solid var(--rule);background:#fff;padding:9px 14px;margin:18px 0 0;
  display:flex;gap:10px;align-items:center;}
.ffm-privacy b{color:var(--ink);}
.ffm-privacy .ic{width:18px;height:18px;border-radius:50%;background:var(--ink);color:var(--lime);display:grid;place-items:center;
  font-size:.7rem;font-weight:800;flex:0 0 18px;}
.ffm-empty{padding:46px 26px;border:1px dashed #CFC9BB;background:#fff;text-align:center;color:var(--ink2);}
.ffm-empty b{font-family:var(--serif);font-size:1.3rem;display:block;margin-bottom:6px;color:var(--ink);}
/* ---------- always-on micro-interactions ---------- */
.ffm-match{transition:background .25s ease, box-shadow .25s ease;position:relative;}
.ffm-match:hover{background:#FFFDF7;box-shadow:inset 3px 0 0 var(--lime);}
.ffm-match .ffm-rk{transition:transform .3s cubic-bezier(.2,.8,.2,1), color .3s;}
.ffm-match:hover .ffm-rk{transform:translateX(6px);color:var(--ink);}
.ffm-match .ffm-t{transition:color .2s;background:linear-gradient(var(--ink),var(--ink)) 0 100%/0 1px no-repeat;
  transition:background-size .35s ease;display:inline;}
.ffm-match:hover .ffm-t{background-size:100% 1px;}
.ffm-tag{transition:transform .2s ease, box-shadow .2s ease;}
.ffm-tag:hover{transform:translateY(-1px);box-shadow:0 3px 8px rgba(14,26,43,.08);}
.ffm-panel2 .row{transition:padding .2s ease, background .2s;}
.ffm-panel2 .row:hover{padding-left:6px;background:#FBFAF6;}
.ffm-due{transition:transform .25s ease;} .ffm-due:hover{transform:translateX(4px);}
.ffm-dot.live{position:relative;}
.ffm-dot.live::after{content:"";position:absolute;inset:-4px;border-radius:50%;border:2px solid currentColor;
  color:#0F8A4A;animation:ffm-ping 1.8s cubic-bezier(0,0,.2,1) infinite;}
.ffm-due .d.hot{animation:ffm-throb 2.4s ease-in-out infinite;}
[data-testid="stTabPanel"], [role="tabpanel"]{animation:ffm-fade .35s ease both;}
[class*="st-key-panel_"]{animation:ffm-rise .45s cubic-bezier(.2,.8,.2,1) both;}
[class*="st-key-det_"] .stButton > button p{transition:letter-spacing .25s ease;}
[class*="st-key-det_"] .stButton > button:hover p{letter-spacing:.02em;}
.stButton > button, .stDownloadButton > button, .stLinkButton > a{transition:all .18s cubic-bezier(.2,.8,.2,1) !important;}
.stButton > button:active{transform:scale(.98);}
[data-testid="stVegaLiteChart"]{animation:ffm-fade .8s ease both;}
@keyframes ffm-ping{0%{transform:scale(.6);opacity:.9}80%,100%{transform:scale(2.2);opacity:0}}
@keyframes ffm-throb{0%,100%{opacity:1}50%{opacity:.55}}
@keyframes ffm-fade{from{opacity:0}to{opacity:1}}
@keyframes ffm-rise{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion: reduce){*{animation:none !important;transition:none !important;}}
@media (max-width:900px){.ffm-h1{font-size:2.2rem;} .ffm-ledger{grid-template-columns:repeat(2,1fr);}
  .ffm-match{grid-template-columns:48px 1fr;} .ffm-score{grid-column:2;text-align:left;} .ffm-detail{margin-left:0;}
  .st-key-topbar{margin:0 -1rem;padding:12px 1rem !important;}}
</style>
"""


# Entrance animations: injected only the first time a page is shown in a session, so clicking around
# doesn't replay them. Disabled entirely for people who prefer reduced motion.
ANIM_CSS = """
<style>
@media (prefers-reduced-motion: no-preference){
.ffm-page > *{animation:ffm-rise .7s cubic-bezier(.2,.8,.2,1) both;}
.ffm-page > *:nth-child(2){animation-delay:.06s} .ffm-page > *:nth-child(3){animation-delay:.14s}
.ffm-page > *:nth-child(4){animation-delay:.22s} .ffm-page > *:nth-child(5){animation-delay:.3s}
.ffm-h1 em{background:linear-gradient(var(--lime),var(--lime)) no-repeat 0 88%/0% 40%;
  animation:ffm-mark .9s .55s cubic-bezier(.65,0,.35,1) forwards;}
.ffm-ledger > div{animation:ffm-rise .7s cubic-bezier(.2,.8,.2,1) both;}
.ffm-ledger > div:nth-child(1){animation-delay:.25s} .ffm-ledger > div:nth-child(2){animation-delay:.33s}
.ffm-ledger > div:nth-child(3){animation-delay:.41s} .ffm-ledger > div:nth-child(4){animation-delay:.49s}
.ffm-ledger .v{animation:ffm-reveal .9s cubic-bezier(.2,.8,.2,1) both;animation-delay:inherit;}
.ffm-match{animation:ffm-rise .7s cubic-bezier(.2,.8,.2,1) both;}
.ffm-score .bar i{transform-origin:left;animation:ffm-grow 1.1s cubic-bezier(.2,.8,.2,1) both;animation-delay:.6s;}
.ffm-bar .fill{transform-origin:left;animation:ffm-grow .9s cubic-bezier(.2,.8,.2,1) both;}
.ffm-panel{animation:ffm-slide .8s .35s cubic-bezier(.2,.8,.2,1) both;}
.ffm-panel .ffm-due{animation:ffm-rise .6s cubic-bezier(.2,.8,.2,1) both;}
.ffm-panel .ffm-due:nth-of-type(1){animation-delay:.6s} .ffm-panel .ffm-due:nth-of-type(2){animation-delay:.7s}
.ffm-panel .ffm-due:nth-of-type(3){animation-delay:.8s} .ffm-panel .ffm-due:nth-of-type(4){animation-delay:.9s}
.ffm-panel2{animation:ffm-rise .7s .5s cubic-bezier(.2,.8,.2,1) both;}
.ffm-h2row{animation:ffm-rise .6s cubic-bezier(.2,.8,.2,1) both;}
.ffm-h2row::after{content:"";}
.ffm-qh{animation:ffm-rise .5s cubic-bezier(.2,.8,.2,1) both;}
}
@keyframes ffm-mark{to{background-size:100% 40%}}
@keyframes ffm-grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes ffm-reveal{from{clip-path:inset(100% 0 0 0);transform:translateY(10px)}to{clip-path:inset(0 0 0 0);transform:none}}
@keyframes ffm-slide{from{opacity:0;transform:translateX(24px)}to{opacity:1;transform:none}}
</style>
"""


def inject_entrance(first_view: bool):
    if first_view:
        st.markdown(ANIM_CSS, unsafe_allow_html=True)


def e(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def render(s: str):
    st.markdown(s, unsafe_allow_html=True)


def tag(text: str, tone: str = "") -> str:
    return f'<span class="ffm-tag t-{tone}">{e(text)}</span>'


def h2(title: str, note: str = ""):
    render(f'<div class="ffm-h2row"><div class="ffm-h2">{e(title)}</div><span>{e(note)}</span></div>')


def note(inner_html: str, tone: str = "") -> str:
    return f'<div class="ffm-note n-{tone}">{inner_html}</div>'


def cite(text: str, source: str = "") -> str:
    return f'<div class="ffm-cite">“{e(text)}”<span>{e(source)}</span></div>'


def k(label: str) -> str:
    return f'<div class="ffm-k">{e(label)}</div>'


def bars(components: dict) -> str:
    out = []
    for name, c in components.items():
        pct = 100 * c["points"] / c["max"] if c["max"] else 0
        out.append(f'<div class="ffm-bar"><div class="h">{e(name.replace("_", " ").capitalize())}'
                   f'<span>{c["points"]:g} / {c["max"]}</span></div><div class="track"><div class="fill" '
                   f'style="width:{pct:.0f}%"></div></div><div class="w">{e(c["why"])}</div></div>')
    return '<div class="ffm-bars">' + "".join(out) + "</div>"
