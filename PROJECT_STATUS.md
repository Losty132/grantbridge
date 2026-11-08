# Project status

**Updated:** Sat Nov 7, 2026 · **Deadline:** submissions before 9 a.m. Sun Nov 8

## Where things stand
A working prototype that runs on the provided Azure environment (Container App + daily refresh job + Blob Storage +
Azure OpenAI). Deploy with `RUN_JOB=1 bash deploy/update.sh` from Cloud Shell (see README §4).

## Done
- Live Grants.gov ingest (Search2 + fetchOpportunity), cached, labeled LIVE / CACHED / SNAPSHOT; daily refresh at 6 AM ET.
- Agency profiles for all 33 NC agencies with OSBM strategic plans (DEQ, DNCR, DPI hand-built and cited; 30 more summarised from the 2025-27 plans, keywords are team matching aids). AGENCIES=all is the default.
- Branded as GrantBridge (logo in header, footer and favicon; light/dark logo variants).
- Decision clears are archived with unique names and can be undone (Restore last clear). Reviewer names are stored as initials only.
- Six-question survey → hard filters → 100-point priority score with breakdown → eligibility label from rules with
  quotes → effort and deadline estimate → top N → one-page brief (PDF or text).
- Decisions: **Pursue / Maybe / Pass** (a reason is required to pass); older Save / Investigate / Dismiss records
  are read with the new names.
- **Privacy filter on the server** for every typed field, before any AI call, save or download (redact or block).
- Web app: Flask + the hand-built HTML/CSS/JS site in the style of the team's reference example (Matches, Decisions,
  Evaluation, Method). Streamlit kept as a backup (`MODE=classic`).
- Evaluation page and `evaluation/run_eval.py` (tests + metrics from hand labels; nothing pre-filled).
- 35 automated tests (`pytest -q`).

## Decisions made today
- The USGS landslide test scenario was **removed** at the team's request (page, API, evaluation test, docs). The
  decoy check stays, using a synthetic universities-only decoy plus live semantic decoys.
- Web server moved from FastAPI to **Flask** (per the Step 1 brief); production runs under gunicorn.
- A React + Tailwind + shadcn/ui + Magic UI version of the front end was built and verified, then **set aside**
  because the team preferred the example-style UI. See COMPONENT_INVENTORY.md.

## Outstanding
- Team: fill `evaluation/labels.csv` (two labelers, blind to scores) so precision/recall can be computed.
- Team: put the discovery notes and prompts you used into GENAI_FIELD_NOTES.md in your own words.
- Team: slides (pitch, demo, evidence, pilot plan, scaling).

## Blockers / access
- None for the core app. Magic UI Pro (header-1) needs a paid license; not needed for the chosen UI.

## Checks run
See README §9 and the final report. `pytest -q` → 35 passed; browser checks at 1440 / 768 / 390 px with no
horizontal overflow and no console errors.
