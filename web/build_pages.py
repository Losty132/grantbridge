"""Generates the five HTML pages in web/static/ from one shared shell, so the header, privacy banner,
command menu, drawer and survey dialog stay identical everywhere.

    python -m web.build_pages      (run after editing this file; the generated HTML is committed)
"""
import hashlib
from pathlib import Path

OUT = Path(__file__).resolve().parent / "static"

NAV = [("index.html", "Matches", "matches"), ("decisions.html", "Decisions", "decisions"),
       ("evaluation.html", "Evaluation", "evaluation"),
       ("method.html", "Method", "method")]

ICON = {
    "lock": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="10" width="16" height="11" rx="3"></rect><path d="M8 10V7a4 4 0 0 1 8 0v3"></path></svg>',
    "sun": '<svg class="sun-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41"></path></svg>',
    "moon": '<svg class="moon-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>',
    "gear": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>',
    "close": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"></path></svg>',
}


def version(name: str) -> str:
    """Content hash for cache busting: browsers keep CSS/JS for a year and fetch again only when it changes."""
    return hashlib.sha256((OUT / name).read_bytes()).hexdigest()[:10]


def shell(page: str, title: str, description: str, main: str) -> str:
    V_CSS, V_JS, V_LOGO = version("stylesheet.css"), version("script.js"), version("logo-dark.png")  # noqa: N806
    cur = ' aria-current="page"'
    act = ' class="active"'
    nav = "".join(f'<a class="nav-link{" active" if key == page else ""}" href="{href}"{cur if key == page else ""}>'
                  f'{label}</a>' for href, label, key in NAV)
    mnav = "".join(f'<a{act if key == page else ""} href="{href}">{label}</a>' for href, label, key in NAV)
    cmd_pages = "".join(
        f'<a class="command-item" href="{href}"><span class="command-item-icon">{i + 1}</span><span><strong>{label}</strong>'
        f'<small>Go to {label.lower()}</small></span><kbd>{i + 1}</kbd></a>' for i, (href, label, _) in enumerate(NAV))
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{description}">
  <meta name="color-scheme" content="dark light">
  <title>{title} · GrantBridge</title>
  <link rel="icon" type="image/png" href="favicon.png?v={V_LOGO}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&amp;family=Manrope:wght@500;600;700;800&amp;display=swap">
  <link rel="stylesheet" href="stylesheet.css?v={V_CSS}">
  <script src="script.js?v={V_JS}" defer></script>
</head>
<body data-page="{page}">
  <div class="noise-overlay" aria-hidden="true"></div>
  <div class="cursor-glow" aria-hidden="true"></div>
  <div class="scroll-progress" aria-hidden="true"></div>
  <a class="skip-link" href="#main-content">Skip to content</a>

  <header class="site-header">
    <div class="header-container">
      <a class="brand" href="index.html" aria-label="GrantBridge home">
        <img class="brand-logo logo-on-dark" src="logo-dark.png?v={V_LOGO}" alt="GrantBridge" width="130" height="60" decoding="async"><img class="brand-logo logo-on-light" src="logo-light.png?v={V_LOGO}" alt="" aria-hidden="true" width="130" height="60" decoding="async">
      </a>
      <nav class="desktop-navigation" aria-label="Main navigation">{nav}</nav>
      <div class="header-actions">
        <label class="agency-picker"><span class="sr-only">Agency</span><select id="agency-select" aria-label="Agency"></select></label>
        <button class="icon-button command-button" type="button" aria-label="Open command menu (Ctrl or Cmd + K)"><span class="keyboard-icon">⌘K</span></button>
        <button class="icon-button theme-toggle" type="button" aria-label="Switch light or dark theme">{ICON["sun"]}{ICON["moon"]}</button>
        <button class="icon-button settings-button" type="button" aria-label="Settings" aria-expanded="false">{ICON["gear"]}</button>
        <button class="mobile-menu-button" type="button" aria-label="Open navigation" aria-expanded="false"><span></span><span></span></button>
      </div>
    </div>
    <nav class="mobile-navigation" aria-label="Mobile navigation">{mnav}</nav>
    <div class="privacy-strip" role="note">
      <div class="privacy-strip-inner">{ICON["lock"]}<strong>Public information only. Do not enter confidential data.</strong>
        <span>A privacy filter screens everything you type before any AI call, save or download. Personal details are redacted; internal information is blocked.</span> <a class="privacy-more" href="method.html#privacy">How it works</a></div>
    </div>
  </header>

  <div class="settings-panel" role="dialog" aria-label="Settings" aria-hidden="true">
    <div class="settings-row"><label for="user-name">Your initials <small>(recorded on decisions so the team knows who decided; screened)</small></label>
      <input id="user-name" type="text" maxlength="8" autocomplete="off" placeholder="e.g. AR"></div>
    <button class="secondary-button small edit-survey-action" type="button">Edit survey answers</button>
    <button class="secondary-button small refresh-action" type="button">Refresh from Grants.gov now</button>
    <p class="settings-status data-label">Loading data status…</p>
  </div>

  <main id="main-content">
{main}
  </main>

  <footer class="site-footer"><div class="container">
    <div class="footer-top">
      <div class="footer-brand-column">
        <a class="brand brand-footer" href="index.html" aria-label="GrantBridge home"><img class="brand-logo logo-on-dark" src="logo-dark.png?v={V_LOGO}" alt="GrantBridge" width="130" height="60" decoding="async"><img class="brand-logo logo-on-light" src="logo-light.png?v={V_LOGO}" alt="" aria-hidden="true" width="130" height="60" decoding="async"></a>
        <p>A pilot prototype that helps North Carolina agencies find, screen and prioritize federal grants. People make every decision; nothing is ever submitted automatically.</p>
      </div>
      <div class="footer-links-column"><span>Explore</span>{"".join(f'<a href="{h}">{l}</a>' for h, l, _ in NAV)}</div>
      <div class="footer-links-column"><span>Sources</span><a href="https://www.grants.gov" target="_blank" rel="noopener">Grants.gov ↗</a><a href="https://www.osbm.nc.gov/operational-excellence/strategic-planning/agency-strategic-plans" target="_blank" rel="noopener">NC agency strategic plans ↗</a><a href="method.html">How it works</a></div>
      <div class="footer-links-column"><span>Safeguards</span><a href="method.html#privacy">Privacy filter</a><a href="method.html#eligibility">Eligibility rules</a><a href="method.html#ai">How AI is checked</a></div>
    </div>
    <div class="footer-bottom"><p>© <span class="current-year"></span> GrantBridge · Federal Funds Matchmaker for NC agencies · NC OSBM Solve-a-thon prototype · public data only</p>
      <p class="footer-data data-label"></p><button class="back-to-top" type="button">Back to top <span>↑</span></button></div>
  </div></footer>

  <div class="drawer" aria-hidden="true">
    <div class="drawer-backdrop"></div>
    <aside class="drawer-panel" role="dialog" aria-modal="true" aria-label="Opportunity details">
      <button class="drawer-close icon-button" type="button" aria-label="Close details">{ICON["close"]}</button>
      <div class="drawer-content"></div>
    </aside>
  </div>

  <div class="survey-modal" aria-hidden="true">
    <div class="survey-backdrop"></div>
    <div class="survey-panel" role="dialog" aria-modal="true" aria-labelledby="survey-title">
      <button class="survey-close icon-button" type="button" aria-label="Close survey">{ICON["close"]}</button>
      <div class="survey-content"></div>
    </div>
  </div>

  <div class="command-overlay" aria-hidden="true"><div class="command-panel" role="dialog" aria-modal="true" aria-label="Command menu">
    <div class="command-search"><span>⌕</span><input type="text" placeholder="Jump to a page or action…" aria-label="Search commands"><kbd>ESC</kbd></div>
    <div class="command-results"><span class="command-group-label">Pages</span>{cmd_pages}
      <span class="command-group-label">Actions</span>
      <button class="command-item command-action" data-action="survey" type="button"><span class="command-item-icon">✎</span><span><strong>Edit survey answers</strong><small>Change focus areas, capacity, match and timing</small></span><kbd>S</kbd></button>
      <button class="command-item command-action" data-action="clear-survey" type="button"><span class="command-item-icon">⟲</span><span><strong>Clear survey answers</strong><small>Reset focus areas and filters to neutral defaults (undoable)</small></span></button>
      <button class="command-item command-action" data-action="refresh" type="button"><span class="command-item-icon">↻</span><span><strong>Refresh from Grants.gov</strong><small>Pull the latest notices now</small></span><kbd>R</kbd></button>
      <button class="command-item command-action" data-action="theme" type="button"><span class="command-item-icon">◐</span><span><strong>Switch theme</strong><small>Light or dark</small></span><kbd>T</kbd></button>
      <span class="command-group-label agency-commands-label">Agencies</span><div class="agency-commands"></div>
    </div></div></div>

  <div class="toast-stack" aria-live="polite" aria-atomic="false"></div>
</body>
</html>
"""


def section_head(num: str, kicker: str, title: str, muted: str = "", aside: str = "") -> str:
    m = f' <span class="muted-heading">{muted}</span>' if muted else ""
    return (f'<div class="section-heading reveal"><div><span class="section-number">{num}</span><span class="section-kicker">'
            f'{kicker}</span></div><h2>{title}{m}</h2>{aside}</div>')


MATCHES = """    <section class="hero-section">
      <div class="hero-grid-background" aria-hidden="true"></div>
      <div class="hero-orb hero-orb-one" aria-hidden="true"></div><div class="hero-orb hero-orb-two" aria-hidden="true"></div><div class="hero-orb hero-orb-three" aria-hidden="true"></div>
      <div class="container hero-container">
        <div class="hero-content reveal">
          <div class="eyebrow"><span class="status-dot"></span><span class="data-short">Connecting to Grants.gov…</span></div>
          <h1 class="hero-title">Federal funding, ranked for <span class="gradient-text">your plan.</span></h1>
          <p class="hero-description">Every open and forecasted federal notice, scored against <span class="agency-plan-link">your agency's strategic plan</span>, screened for eligibility and timing, and explained with citations. You decide what to pursue.</p>
          <div class="hero-buttons">
            <a class="primary-button magnetic" href="#best-matches">See best matches <span class="button-arrow">↓</span></a>
            <button class="secondary-button magnetic edit-survey-action" type="button">Tune my answers <span>→</span></button>
          </div>
          <div class="hero-trust-row"><div class="mini-avatar-stack" aria-hidden="true"><span>01</span><span>02</span><span>03</span><span>+</span></div>
            <div><strong>Humans decide. Sources are cited.</strong><p>Eligibility comes from rules, never from AI alone.</p></div></div>
        </div>
        <div class="hero-dashboard reveal" aria-label="Live summary">
          <div class="dashboard-window">
            <div class="dashboard-topbar"><div class="window-controls" aria-hidden="true"><span></span><span></span><span></span></div>
              <div class="dashboard-address agency-address">matchmaker / deq</div><div class="dashboard-status data-pill">Live</div></div>
            <div class="dashboard-body">
              <div class="dashboard-welcome"><div><small>Today's picture</small><h2 class="agency-name-heading">Loading…</h2></div></div>
              <div class="dashboard-metrics">
                <article><div class="metric-header"><span>Notices reviewed</span><span class="metric-neutral">open + forecast</span></div><strong class="counter" data-key="reviewed">0</strong><div class="mini-bars mini-bars-live" aria-hidden="true"></div></article>
                <article><div class="metric-header"><span>Passed your filters</span><span class="metric-positive eligible-note">—</span></div><strong class="counter" data-key="shortlist">0</strong><div class="project-progress"><div><span>Directly eligible</span><strong class="counter" data-key="eligible">0</strong></div><div class="progress-track"><span class="eligible-bar"></span></div></div></article>
              </div>
              <div class="dashboard-chart-card"><div class="chart-card-heading"><div><small>Top match right now</small><strong class="hero-top-title">—</strong></div><span class="hero-top-score">—</span></div>
                <div class="hero-top-meta"></div></div>
              <div class="dashboard-bottom-row">
                <article><span class="dashboard-icon">!</span><div><small>Due within 14 days</small><strong><span class="counter" data-key="due14">0</span> <span class="plural" data-for="due14">notices</span></strong></div></article>
                <article><span class="dashboard-icon">↘</span><div><small>Set aside with a reason</small><strong><span class="counter" data-key="set_aside">0</span> <span class="plural" data-for="set_aside">notices</span></strong></div></article>
              </div>
            </div>
          </div>
          <div class="floating-data-card floating-card-one"><span class="floating-card-icon">↗</span><div><small>Best fit score</small><strong class="hero-best-score">—</strong></div></div>
          <div class="floating-data-card floating-card-two"><span class="pulse-ring"></span><div><small>Privacy filter</small><strong>On for every input</strong></div></div>
        </div>
      </div>
      <div class="hero-scroll-indicator"><span>Scroll to explore</span><div class="scroll-line"></div></div>
    </section>

    <section class="section matches-section" id="best-matches"><div class="container">
      """ + section_head("01", "Best matches", "The few worth your time,", "ranked and explained.",
                         '<p class="section-aside top-note">Ranked by a 100-point priority score built from your plan, eligibility, timing and resources. It is not a probability of winning.</p>') + """
      <div class="alert-banner" hidden role="status"></div>
      <div class="matches-layout">
        <div class="match-list" aria-live="polite"><div class="skeleton-card"></div><div class="skeleton-card"></div><div class="skeleton-card"></div></div>
        <aside class="match-aside">
          <div class="due-panel reveal"><div class="due-panel-head"><span class="section-kicker">Due soon</span><h3>Closing within 30 days</h3><a class="text-link calendar-link" href="#" download>Add deadlines to my calendar ↓</a></div><div class="due-list"></div></div>
          <div class="aside-card reveal"><span class="section-kicker">Why items were set aside</span><div class="set-aside-counts"></div></div>
          <div class="aside-card reveal"><span class="section-kicker">Your answers</span><div class="survey-summary"></div>
            <div class="aside-actions"><button class="text-link edit-survey-action" type="button">Edit answers <span>↗</span></button>
            <button class="text-button clear-survey-action" type="button">Clear answers</button></div></div>
        </aside>
      </div>
    </div></section>

    <section class="section glance-section"><div class="container">
      """ + section_head("02", "At a glance", "Where the matches land,", "and how much time is left.") + """
      <div class="chart-grid">
        <figure class="chart-card reveal"><figcaption><span class="section-kicker">By strategic goal</span><strong>Shortlisted notices per plan goal</strong></figcaption><div class="chart chart-goals" role="img" aria-label="Bar chart of shortlisted notices by strategic plan goal"></div><details class="chart-table"><summary>View as table</summary><div class="chart-goals-table"></div></details></figure>
        <figure class="chart-card reveal"><figcaption><span class="section-kicker">Deadline runway</span><strong>Fit score vs. days left to apply</strong></figcaption><div class="chart chart-runway" role="img" aria-label="Scatter chart of fit score against days left to apply"></div><details class="chart-table"><summary>View as table</summary><div class="chart-runway-table"></div></details></figure>
      </div>
    </div></section>

    <section class="section search-section"><div class="container">
      """ + section_head("03", "Search by project", "Describe a project.", "We'll find the closest notices.") + """
      <form class="project-search reveal" autocomplete="off">
        <label for="project-q" class="sr-only">Describe a project</label>
        <input id="project-q" type="text" maxlength="300" placeholder="e.g. stream restoration and flood resilience in eastern North Carolina">
        <button class="primary-button" type="submit">Search <span>→</span></button>
        <p class="field-hint"><span class="shield">✓</span> Screened on the server for personal or internal information before searching.</p>
      </form>
      <div class="privacy-result search-privacy" aria-live="polite"></div>
      <div class="search-results"></div>
    </div></section>

    <section class="section shortlist-section"><div class="container">
      """ + section_head("04", "Everything on your shortlist", "Filter, sort,", "and export.") + """
      <div class="table-toolbar reveal">
        <label>Min score<input type="range" min="0" max="100" step="5" value="0" class="f-score"><output class="f-score-out">0</output></label>
        <label>Due within<select class="f-due"><option value="">Any time</option><option>7</option><option>14</option><option>30</option><option>60</option><option>90</option></select></label>
        <label>Award ceiling<select class="f-fund"><option value="0">Any</option><option value="50000">$50K+</option><option value="250000">$250K+</option><option value="1000000">$1M+</option></select></label>
        <label>Decision<select class="f-decision"><option value="">All but Pass</option><option>None yet</option><option>Pursue</option><option>Maybe</option><option>Pass</option></select></label>
        <label class="grow">Words<input type="search" class="f-text" placeholder="Filter titles"></label>
        <button class="secondary-button small export-csv" type="button">Export CSV ↓</button>
      </div>
      <div class="table-wrap reveal"><table class="data-table shortlist-table"><thead><tr>
        <th data-sort="rank">#</th><th data-sort="score">Score</th><th data-sort="title">Title</th><th data-sort="agency">Funder</th><th data-sort="eligibility">Eligibility</th><th data-sort="days_left">Due</th><th data-sort="award_ceiling">Award ceiling</th><th data-sort="decision">Decision</th></tr></thead><tbody></tbody></table></div>
      <p class="table-count"></p>
    </div></section>

    <section class="section set-aside-section"><div class="container">
      """ + section_head("05", "Set aside", "Removed by a rule,", "never silently.") + """
      <details class="set-aside-details reveal"><summary>Show every set-aside notice and the rule that removed it</summary>
        <div class="table-wrap"><table class="data-table setaside-table"><thead><tr><th>Score before rule</th><th>Title</th><th>Why</th><th>Due</th></tr></thead><tbody></tbody></table></div></details>
    </div></section>"""

DECISIONS = """    <section class="inner-hero"><div class="inner-hero-grid" aria-hidden="true"></div><div class="container">
      <div class="inner-hero-heading reveal"><span class="page-label"><span class="status-dot"></span>Decision log</span>
        <h1>What your team <span class="gradient-text">decided.</span></h1>
        <p class="hero-description">Every Pursue, Maybe and Pass with its reason, who made it and the score at the time. The full history is kept.</p></div>
      <div class="metrics-grid decision-counters reveal">
        <article><strong class="counter" data-key="reviewed">0</strong><span>Notices reviewed</span></article>
        <article><strong class="counter" data-key="Pursue">0</strong><span>Pursue</span></article>
        <article><strong class="counter" data-key="Maybe">0</strong><span>Maybe</span></article>
        <article><strong class="counter" data-key="Pass">0</strong><span>Pass, with reasons</span></article>
      </div></div></section>
    <section class="section compact-section"><div class="container">
      """ + section_head("01", "Log", "Latest decision", "per notice.") + """
      <div class="table-wrap reveal"><table class="data-table decisions-table"><thead><tr><th>When</th><th>Decision</th><th>Relevance</th><th>Title</th><th>Reason</th><th>Note</th><th>By</th><th>Score then</th></tr></thead><tbody></tbody></table></div>
      <div class="decisions-footer"><p class="table-count"></p>
        <button class="secondary-button small clear-decisions" type="button" hidden>Clear all decisions</button>
        <button class="text-button restore-decisions" type="button">Restore last clear</button></div>
      <div class="clear-status" aria-live="polite"></div>
    </div></section>"""

EVALUATION = """    <section class="inner-hero"><div class="inner-hero-grid" aria-hidden="true"></div><div class="container">
      <div class="inner-hero-heading reveal"><span class="page-label"><span class="status-dot"></span>Evaluation</span>
        <h1>Evaluation: <span class="gradient-text eval-agency">your agency</span></h1>
        <p class="hero-description">Measures how closely GrantBridge's rankings match your team's decisions, and confirms the safety rules are working.</p>
        <div class="hero-buttons eval-buttons"><button class="primary-button run-eval" type="button">Run evaluation <span>→</span></button>
          <button class="secondary-button pause-eval" type="button">Pause</button>
          <button class="secondary-button stop-eval" type="button">Stop</button></div>
        <div class="eval-progress" hidden aria-live="polite"><div class="eval-progress-bar"><span></span></div><p class="eval-progress-text field-hint"></p></div>
        <p class="eval-meta field-hint"></p></div>
    </div></section>
    <section class="section compact-section"><div class="container eval-body">
      <h2 class="eval-h2">Scorecard</h2>
      <div class="scorecard"></div>
      <div class="learning-box"></div>
      <h2 class="eval-h2">Reach: grants manual monitoring would miss</h2>
      <div class="reach-box"></div>
      <form class="missed-form" autocomplete="off">
        <label for="missed-grant"><b>Found a grant somewhere else?</b> Paste its Grants.gov link, opportunity ID or number to see whether GrantBridge caught it. Every report makes the reach measure more honest.</label>
        <div class="missed-row"><input id="missed-grant" type="text" maxlength="300" placeholder="e.g. https://www.grants.gov/search-results-detail/358123 or EPA-R-OW-24-01"><button class="secondary-button" type="submit">Check it</button></div>
        <p class="missed-result field-hint" aria-live="polite"></p>
      </form>
      <h2 class="eval-h2">Top 5 quality</h2>
      <ul class="check-list"></ul>
      <h2 class="eval-h2">Items to review</h2>
      <div class="problem-list"></div>
      <details class="eval-details"><summary class="safety-summary">Safety checks</summary><div class="safety-list"></div></details>
      <details class="eval-details"><summary>How these numbers are worked out</summary><div class="eval-how">
        <p><b>Answer key:</b> your team's decisions. Pursue and Maybe mean "good fit"; Pass means "poor fit" unless the reason is about capacity, timing or money (those are left out). A relevance mark, if set, always wins. Grants that have closed or that your survey now filters out are left out.</p>
        <p><b>Fair grading:</b> accuracy is measured on the ranking from your strategic plan alone. The learning box then shows what changes when the app also learns from your decisions; a grant is never moved by its own decision.</p>
        <p><b>Score by decision:</b> the average plan-based score of grants you pursued versus grants you passed on as a poor fit. <b>Top-5 accuracy:</b> of the first 5 on your list that you judged, how many were good (needs 3). <b>Average position:</b> where your good grants sit on the list. <b>Ranking agreement:</b> each good grant compared with each poor-fit one; how often the good one is higher.</p>
        <p><b>Reach:</b> a grant counts as "likely missed by manual monitoring" when it comes from a federal agency outside your usual partners AND was found only by searches beyond your agency&#39;s own keywords (someone watching either would have caught the rest). <b>Time saved</b> is an estimate: grants reviewed × 3 minutes to skim one by hand.</p>
        <p><b>Colours:</b> green is good, amber worth a look, red needs attention. Grey means not enough decisions yet; nothing is guessed.</p>
      </div></details>
    </div></section>"""

METHOD = """    <section class="inner-hero"><div class="inner-hero-grid" aria-hidden="true"></div><div class="container">
      <div class="inner-hero-heading reveal"><span class="page-label"><span class="status-dot"></span>Method</span>
        <h1>How the <span class="gradient-text">score is made.</span></h1>
        <p class="hero-description">Data, filters, scoring, eligibility, effort estimates, AI checks and privacy, in plain language.</p></div>
    </div></section>
    <section class="section compact-section"><div class="container">
      """ + section_head("01", "The flow", "From a federal notice", "to a decision.") + """
      <div class="process-steps flow-steps">
        <article class="process-step reveal"><div class="process-step-number">01</div><div><span>Profile</span><h3>Your strategic plan</h3><p>Each objective from the agency's OSBM-published plan is stored separately with its section and link.</p></div></article>
        <article class="process-step reveal"><div class="process-step-number">02</div><div><span>Survey</span><h3>Six quick questions</h3><p>Focus areas, capacity, minimum award, cost share and prep time tune the ranking.</p></div></article>
        <article class="process-step reveal"><div class="process-step-number">03</div><div><span>Ingest</span><h3>Grants.gov, every morning</h3><p>Open and forecasted notices from the public API, de-duplicated, with first-seen and last-changed dates. If the API fails, cached data is labeled as cached.</p></div></article>
        <article class="process-step reveal"><div class="process-step-number">04</div><div><span>Filter</span><h3>Hard rules first</h3><p>Expired, state not eligible, match you can't provide, or award below your minimum: removed, with the reason shown.</p></div></article>
        <article class="process-step reveal"><div class="process-step-number">05</div><div><span>Score</span><h3>100-point priority score</h3><p>Strategic alignment 50 (meaning + the objective's own keywords), applicant fit 20, deadline feasibility 15 (graded), resource feasibility 15. Missing information gets partial credit, never full, and is named.</p></div></article>
        <article class="process-step reveal"><div class="process-step-number">06</div><div><span>Decide</span><h3>People decide</h3><p>Pursue, Maybe or Pass (a reason is required to pass). Nothing is ever submitted automatically.</p></div></article>
      </div>
    </div></section>
    <section class="section compact-section" id="eligibility"><div class="container">
      """ + section_head("02", "Eligibility", "Rules and citations,", "never AI alone.") + """
      <div class="method-grid reveal">
        <article class="method-card"><h3>Four labels</h3><p><b>Appears Eligible</b> · <b>Needs Human Verification</b> · <b>Partnership Opportunity</b> · <b>Not Eligible for Direct Application</b>. They come from the Grants.gov applicant codes plus sentences quoted from the notice.</p></article>
        <article class="method-card"><h3>Conditions, quoted</h3><p>Matching funds, partners, letters of support, pre-applications and registrations are pulled out with the exact sentence and where it came from.</p></article>
        <article class="method-card"><h3>Open questions</h3><p>Anything uncertain becomes a question for a person, such as "Does the restriction exclude this agency?" It is not a legal determination.</p></article>
      </div>
    </div></section>
    <section class="section compact-section"><div class="container">
      """ + section_head("03", "Effort", "Time estimates", "from the notice itself.") + """
      <div class="method-grid reveal">
        <article class="method-card"><h3>Drivers, each quoted</h3><p>Letter of intent +2 · narrative page limit +1 to +3 · budget justification +1 · cost-share documentation +2 · letters of support +1 each (max 3) · evaluation or data plan +2 · registrations +1 · multi-stage review +2.</p></article>
        <article class="method-card"><h3>Bands</h3><p>0–3 points = Low (about 1–2 weeks) · 4–7 = Medium (3–5 weeks) · 8+ = High (6+ weeks). No drivers found = <b>Unknown — check notice</b>, never Low.</p></article>
        <article class="method-card"><h3>Feasibility</h3><p>Compared with days left and your prep time: Feasible, Tight, or Not enough time. Always labeled "Estimate — based on notice requirements".</p></article>
      </div>
    </div></section>
    <section class="section compact-section" id="ai"><div class="container">
      """ + section_head("04", "AI, checked", "AI explains.", "The code checks it.") + """
      <div class="method-grid reveal">
        <article class="method-card"><h3>Structured output</h3><p>The model returns JSON: matched objective, plan citation, a quote from the notice, reasons and confidence.</p></article>
        <article class="method-card"><h3>Verified against sources</h3><p>The objective must exist in the profile and the quote must appear word for word in the notice. Failures are replaced and marked <b>Needs a second look</b>.</p></article>
        <article class="method-card"><h3>Safe by default</h3><p>Retrieved text is treated as untrusted data, never as instructions. If AI is unavailable, rules and similarity take over and everything still works.</p></article>
      </div>
    </div></section>
    <section class="section compact-section" id="privacy"><div class="container">
      """ + section_head("05", "Privacy filter", "Everything you type", "is screened first.") + """
      <div class="privacy-feature reveal">
        <div class="privacy-copy"><p>The filter runs <b>on the server</b>, so it can't be bypassed from the browser. It screens every typed input: <b>the survey's other priority</b>, <b>project search</b>, <b>decision reasons</b>, <b>decision notes</b>, <b>your initials</b> and <b>notes added to a brief</b>. It runs <b>before</b> any AI call, any save, and any brief copy or download.</p>
          <p>You always see what was removed. Text that looks internal is blocked until you edit it. Original text is never stored; only the count and type of redactions are logged.</p></div>
        <div class="privacy-layers">
          <article><span>Layer 1 · optional</span><h3>Azure AI Language PII detection</h3><p>Names, contact details and IDs, detected inside the Azure tenant when configured.</p></article>
          <article><span>Layer 2 · always on</span><h3>Local pattern filter</h3><p>Emails, phone numbers, SSNs, card numbers (Luhn-checked), street addresses and names after titles or cue words become <code>[EMAIL]</code>, <code>[PHONE]</code>, <code>[NAME]</code>…</p></article>
          <article><span>Layer 3 · always on</span><h3>Internal-information block</h3><p>"Confidential", "internal only", "draft budget", "personnel", "do not distribute" and shortfall amounts stop the action until you edit the text.</p></article>
        </div>
      </div>
    </div></section>"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pages = {
        "index.html": ("matches", "Matches", "Federal grants ranked against NC agency strategic plans.", MATCHES),
        "decisions.html": ("decisions", "Decisions", "Pursue, Maybe and Pass decisions with reasons.", DECISIONS),
        "evaluation.html": ("evaluation", "Evaluation", "Ranking accuracy, top-pick quality and safety tests, explained.", EVALUATION),
        "method.html": ("method", "Method", "How scoring, eligibility, effort and privacy work.", METHOD),
    }
    for name, (key, title, desc, main_html) in pages.items():
        (OUT / name).write_text(shell(key, title, desc, main_html), encoding="utf-8")
        print("wrote", name)


if __name__ == "__main__":
    main()
