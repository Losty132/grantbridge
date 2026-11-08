# Requirements and their sources

| Source | What it contributes | Affects | Kind | Status |
|---|---|---|---|---|
| Official challenge page (tarheels.live/solveathon/final-challenge) | Load federal data, build profiles from real NC plans, score + rank, summarize, simple UI, run on Azure, human decides, evaluate, README, field notes with an AI mistake | Whole product | **Official requirement** | Done (labels + slides are team work) |
| Final Quest PDF | Same as above, plus bonus quests: coverage, deadline alerts, feedback loop | Coverage counts, "due within 14 days", decisions as feedback | Official requirement | Core done; bonuses partly (deadline flags, feedback log) |
| Solve-a-thon Starter Kit (.docx) | Suggested Azure architecture and services | Container App, Blob, Azure OpenAI | Suggested implementation | Used where it fit |
| NC OSBM agency strategic plans (PDF/site) | Goals and objectives per agency | `agency_profiles/profiles/*.json` | Official data source | Done for all 33 agencies with OSBM strategic plans (DEQ, DNCR, DPI in full detail; 30 summarised by build_statewide.py, team review pending) |
| Discovery session transcripts + notes | Time is the constraint; few good matches beat many; eligibility and matching funds matter; privacy | Top N by capacity, set-aside reasons, eligibility labels, privacy filter | Client observation | Done |
| Client notes (Google Doc) | One person reads a daily Grants.gov digest; no standard process; time; "filter out sensitive info before it gets sent out (bonus)"; all federal opportunities are public | Daily refresh, ranking, privacy filter | Client observation | Done |
| Team spec (attachment, sections 1–14) | Survey, hard filters, hybrid score, eligibility labels, time estimate, brief, decisions, privacy filter, evaluation, security, README sections | Engine + UI | Team requirement | Done; landslide scenario (§13) **removed at team request** |
| Step 1 brief (attachment) | Project tracking docs; Flask backend; React/shadcn/Magic UI front end; reference site; motion rules | Docs, Flask, front end | Team requirement | Flask + docs done; React version built then set aside for the example-style UI |
| Reference example site (vertex-studio-site.zip) | Visual language: dark/light themes, reveals, counters, command menu, editorial headings | `web/static/` | Illustrative example | Done (style only; no content copied) |
| startup-template-sage.vercel.app | Hero composition reference | React version only | Illustrative example | Measured; used in the set-aside React version |

Nothing private is published on the site: no transcripts, notes, credentials or unrelated document text.
