# Design notes

## Principle
The users are busy state employees who handle grants on top of another job. Every design choice is judged by one
question: **does it save them time?** So the first screen is the answer (your top few matches, ranked, with reasons),
not a search box or a list of hundreds.

## What the user sees, in order
1. **Matches** opens straight to the agency's top N (N = how many applications they said they can take on).
   First visit: the six-question survey opens by itself (about a minute) and can be changed any time.
2. Each match card shows award, deadline, effort, the plan objective it supports, a quote from the notice and plain
   tags (Eligible to apply · Due in 9 days · Not enough time). One click opens the drawer: fit, eligibility, effort,
   brief, decision.
3. **Due soon** panel lists anything closing within 30 days with the recommended next step.
4. Everything else is one scroll away: charts, project search, the full filterable/exportable shortlist, and what was
   set aside and why.

## Visual language (from the team's reference example site)
Dark-first with a light mode, DM Sans + Manrope, violet→cyan accent, grid and grain texture, editorial two-tone
headings ("The few worth your time, *ranked and explained*"), scroll reveals, count-up stats, animated score rings,
hand-built SVG charts with table fallbacks, a ⌘K command menu and a slide-in drawer. No content from the example
was copied; only the style.

## Speed decisions
- No front-end framework or build step: four small HTML pages, one CSS file, one JS file (served gzipped, cached 5 min).
- The overnight job does the slow work (NOFO PDFs, AI explanations for each agency's top matches), so pages render
  from precomputed results.
- The server keeps rankings and details in memory (one process, 8 threads) and invalidates only what changed.
- The detail drawer loads one opportunity on demand; lists never load full details.

## Accessibility and motion
Visible focus, keyboard-reachable controls (⌘K, Esc closes panels), labels on every input, tables as chart fallbacks,
and `prefers-reduced-motion` turns animation off.
