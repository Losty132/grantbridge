# GrantBridge: Federal Funds Matchmaker (NC OSBM prototype)

Covers **all 33 NC agencies with an OSBM strategic plan** (pick yours from the header). Helps North Carolina state agencies **find, screen, prioritize and act on federal grant opportunities** with as little
staff time as possible. It pulls live data from Grants.gov, compares each opportunity with the agency's own strategic
plan objectives, filters out what the agency can't use, and explains every recommendation with citations.
**People make every decision; the app never submits applications.**

```
Agency profile (strategic plan) → 6-question survey → Grants.gov ingest → hard filters → hybrid score (/100)
→ eligibility label → time estimate → Top N dashboard → grant brief → Pursue / Maybe / Pass
```
> **🔒 A privacy filter screens everything users type before any AI call, save or download.**
> It runs on the server (it can't be skipped from the browser) on every typed field: the survey's "other priority",
> project search, brief notes, decision reasons, notes and the reviewer's initials (a full name is reduced to initials on the server). Personal details are redacted
> (`[EMAIL]`, `[PHONE]`, `[NAME]`…) and the user is shown exactly what changed; internal information ("internal only",
> "draft budget", "confidential"…) is **blocked** and nothing is saved or sent. A banner on every page says so. See §8.

**Two front ends, one engine.** The default web app is Flask (`web/server.py`, run by gunicorn) serving a hand-built
HTML/CSS/JS site (`web/static/`) with four pages: Matches, Decisions, Evaluation and Method. The original
Streamlit app is kept as a backup (`MODE=classic`). Both use the same Python engine and the same data.

---

## 0. For the state developer picking this up

**What it is.** A Flask web app plus a daily job that rank Grants.gov opportunities against each NC agency's
OSBM strategic plan. Everything runs from one Docker image on Azure Container Apps; data lives in one Blob container.
No database, no build step for the front end.

**Day-one checklist**
1. Read this section, then §4 (deploy) and the code map near the end.
2. Run it locally with no Azure at all (§1): `python -m data_retrieval.refresh` then `flask --app web.server run`.
3. Run `pytest -q` (49 tests, about 15 s, no network).
4. In Azure: `source deploy/azure_names.env && bash deploy/status.sh` shows the URL, job runs and logs.

**Where to change things**

| Task | Where | Notes |
|---|---|---|
| Add or edit an agency | `agency_profiles/profiles/<id>.json` | Picked up automatically (`AGENCIES=all`). `python -m agency_profiles.extract_profile` drafts one from a plan PDF; a person must verify each objective. Run `pytest` (it validates every profile). |
| Change score weights | `scoring/score.py` (constants at the top) | Points per part are documented in §6. Re-run the Evaluation page afterwards. |
| Change eligibility rules | `eligibility/classify.py` | Rules only, with citations. Add a regression test in `tests/test_core.py`. |
| Change privacy rules | `privacy/filter.py`, samples in `evaluation/pii_samples.py` | The block check runs before redaction. Keep both test lists passing. |
| Change the pages | `web/build_pages.py` (HTML), `web/static/stylesheet.css`, `web/static/script.js` | Run `python -m web.build_pages` after editing; asset URLs get a content hash so browsers never use a stale copy. |
| Add an API route | `web/server.py` (route) + `web/service.py` (logic) | Every route that accepts typed text must call `screen()` first. |
| Add a data source (e.g. SAM.gov) | `data_retrieval/` | Produce the same record fields as `normalize.py`; everything downstream works unchanged. |
| Turn on Teams alerts | `ALERT_WEBHOOK_URL='https://…' bash deploy/update.sh` | Stored as a Container Apps secret. |
| Rotate keys | Azure portal or `az containerapp secret set` | Never put secrets in code, zips or git. |

**Runbook**

| Symptom | Check | Fix |
|---|---|---|
| Banner says CACHED DATA | `bash deploy/status.sh` → last job run and `last_error` | Usually Grants.gov was down; the next daily run recovers. `az containerapp job start -n $JOB -g $RG` to retry now. |
| "Matching method: tfidf" | `az cognitiveservices account deployment list …` | Add an `embed` deployment (text-embedding-3-small) or set `AOAI_EMBED_DEPLOYMENT`; then re-run the job. |
| AI explanations off | `AOAI_ENDPOINT` / `AOAI_KEY` on the app | The app falls back to rule-based explanations automatically. |
| Slow first page after a deploy | App logs | Rankings warm up in the background (about 30 s for 33 agencies); `--min-replicas 1` avoids cold starts. |
| Deploy failed | `~/deploy.log` | Usually the subscription isn't selected (`az account set …`) or Cloud Shell is in PowerShell mode. |

**Before production:** add Entra ID sign-in and role-based access (§11), move secrets to Key Vault with managed identity,
have each agency verify its profile, and pilot with a few agencies to tune the score from real decisions (§12-13).

## 1. Quick start in VS Code

1. Install **Python 3.12+** and **VS Code**. Open this folder in VS Code (File → Open Folder).
   Accept the recommended extensions (Python, Docker, Azure Container Apps, Azure CLI).
2. **Terminal → Run Task → `1. Setup: create .venv and install`**. This creates `.venv`, installs the requirements
   and copies `.env.example` to `.env`.
3. Choose the interpreter: `Ctrl/Cmd+Shift+P` → **Python: Select Interpreter** → `.venv`.
4. **Run Task → `2. Refresh data from Grants.gov`**. The first run pulls and caches roughly 1,500–3,000 opportunities
   and takes 5–15 minutes. Later runs only fetch new items.
5. **Run and Debug (F5) → `Run web app (new UI)`** (or `Run classic app (Streamlit backup)`), then open <http://localhost:8000>.
6. **Run Task → `4. Run tests`**. The Testing panel also shows the pytest tests.

The app works **without any Azure services** locally: data goes to `./data`, and matching uses rules + TF-IDF.
Fill in `.env` to use Azure Blob Storage and Azure OpenAI from your laptop.

Without VS Code:
```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt && cp .env.example .env
python -m data_retrieval.refresh
flask --app web.server run --port 8000      # web app  (backup: streamlit run app.py --server.port 8000)
pytest -q
```

## 2. Dependencies
`requirements.txt`: flask, flask-compress, gunicorn (web app), streamlit (backup UI), pandas, numpy, requests,
python-dateutil, azure-storage-blob, azure-core, openai, pypdf, fpdf2, python-dotenv, tzdata. `requirements-dev.txt` adds pytest. Python 3.12+ (the Docker image uses 3.13).

## 3. Configuration (`.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `STORAGE_CONN` | empty → `./data` | Azure Blob Storage connection string (**secret**) |
| `STORAGE_CONTAINER` | `ffm-data` | Blob container |
| `AOAI_ENDPOINT`, `AOAI_KEY` | empty → AI off | Azure OpenAI (key is a **secret**) |
| `AOAI_CHAT_DEPLOYMENT`, `AOAI_EMBED_DEPLOYMENT` | `chat`, `embed` | Deployment names |
| `LANGUAGE_ENDPOINT`, `LANGUAGE_KEY` | empty | Optional Azure AI Language PII detection (privacy layer 1) |
| `AGENCIES` | `all` | `all` = every profile in `agency_profiles/profiles/`; or a comma list such as `deq,dot` |
| `NOFO_FETCH` | `1` | Download and parse the NOFO PDF for top results |
| `BROAD_PULL_CAP`, `KEYWORD_PULL_CAP`, `DETAIL_FETCH_CAP` | 1000, 150, 2500 | Ingestion limits |
| `DETAIL_MAX_AGE_DAYS` | `7` | Re-fetch a grant's details when older than this |
| `PRECOMPUTE_TOP` | `5` | Grants per agency prepared overnight (full notice + verified AI explanation) |
| `ALERT_WEBHOOK_URL` | empty → off | Teams / Slack / Power Automate incoming webhook for deadline alerts (**secret**) |
| `WRITES_PER_MINUTE` | `120` | Changes / searches allowed per address per minute |
| `REFRESH_COOLDOWN_SECONDS`, `EVAL_COOLDOWN_SECONDS` | 600, 60 | Minimum gap between manual refreshes / evaluations |
| `WEB_THREADS` | `8` | gunicorn threads (one process, so one shared cache) |

Secrets live only in `.env` (git-ignored) locally and as Container Apps secrets on Azure. They never appear in code or logs.

## 4. Deploy to Azure

**Architecture:** one Docker image, two roles. `MODE=app` runs the web app (Flask + gunicorn) on an **Azure Container App** (`MODE=classic` = Streamlit backup); `MODE=job`
runs the refresh on an **Azure Container Apps Job** every morning (10:00 UTC). Data lives in **Azure Blob Storage**
(persistent). **Azure OpenAI** is optional. The image is built in the cloud by **Azure Container Registry**, so no
local Docker is needed.

### Option A: Azure Cloud Shell (recommended)
1. Zip this folder (or push it to GitHub). Go to <https://shell.azure.com> → **Bash** → upload the zip
   (or `git clone`), then `unzip federal-funds-matchmaker.zip && cd federal-funds-matchmaker`.
2. **If you already deployed the earlier version**, reuse its resources:
   `cp ~/ffm-matchmaker/deploy/azure_names.env deploy/`
3. `bash deploy/azure_setup.sh` (about 15–20 minutes). It prints the **App URL**.
4. `bash deploy/status.sh` shows the URL, the refresh-job runs (wait for `Succeeded`), and logs.
5. Open the URL **from another computer or a phone** to confirm it's public.
6. After code changes: `bash deploy/update.sh` (add `RUN_JOB=1` to refresh the data too).

### Option B: from VS Code
Install the Azure CLI, run `az login` in the VS Code terminal, then **Run Task → `Azure: first-time setup + deploy`**.
On Windows, run the `.sh` scripts in **Git Bash** or **WSL**, or use Option A.

### Option C: Azure App Service
After Option A has built the image: `bash deploy/appservice_deploy.sh` runs the same container on App Service (B1, with
websockets on for Streamlit). The daily refresh still runs as the Container Apps Job.

Useful commands (after `source deploy/azure_names.env`):
```bash
az containerapp job start -n $JOB -g $RG                      # refresh now
az containerapp logs show -n $APP -g $RG --tail 50 --follow   # live app logs
az group delete -n $RG --yes --no-wait                        # AFTER judging only: delete everything
```

**Fast deploys:** `deploy/update.sh` keeps the Python packages in a base image (`Dockerfile.base`, tagged with a
hash of `requirements.txt`). It is built once (~5 min); later deploys only add the code (~1-2 min). The web app and the
refresh job are updated in parallel, and the app keeps one replica running (no cold start).

## 5. Data sources
* **Grants.gov public API**: `search2` (posted + forecasted; a broad pull filtered to state-eligible applicant types, plus
  each agency's search terms) and `fetchOpportunity` (details, eligibility, award amounts, cost sharing, attachments).
  The NOFO PDF attachment is downloaded best-effort for top results.
* **NC OSBM agency strategic plans** (<https://www.osbm.nc.gov/operational-excellence/strategic-planning/agency-strategic-plans>):
  33 agencies (2025-27 plans) → `agency_profiles/profiles/*.json`; DEQ, DNCR and DPI were built by hand, the other 30
  by `python -m agency_profiles.build_statewide`. Each objective is stored
  separately with its plan section and link. Objective wording is a close summary; check the cited section before
  quoting it externally.
* **Data labels:** the sidebar and every brief say whether data is **LIVE**, **CACHED** (the last refresh failed; the
  error is logged) or a **SNAPSHOT** replay. Status (open / forecasted / expired) is recomputed against today's date
  every time data is displayed.
* De-duplicated by opportunity ID and number. `opportunities/registry.json` tracks first-seen, last-seen and last-modified.

## 6. Scoring methodology (/100: a prioritization score, not a probability of winning)

| Component | Points | Method |
|---|---|---|
| Strategic alignment | 50 | Similarity between the notice and **each** objective (plus operating programs, ×0.95), combined (noisy-OR) with **that objective's own keywords** found in the notice (a title hit counts double; keywords alone can give at most 60%). A second objective that also matches well adds 5%. Objectives you tick in Q2 are boosted (others ×0.85). TF-IDF matches with none of the agency's keywords count ×0.85 (often one shared generic word). Azure OpenAI embeddings when available, otherwise TF-IDF. |
| Applicant / program fit | 20 | Eligibility (Appears Eligible 10, Needs Verification 5, or 3 without applicant codes) + agency keywords with diminishing returns (1 → 3, 2 → 4.5, 3 → 5.3, max 6) + usual federal partner (4) |
| Deadline feasibility | 15 | Graded: Feasible 15 (13 if effort unknown) · Tight 7–12 by how close the time left is to the time needed · Not enough 3 if over a third of the need, else 0 · no close date 8 (often rolling; check the notice) · expired 0 |
| Resource feasibility | 15 | Cost share: none 5, required 5/3/0 by Q5, not stated 3 · Award: ceiling ≥ Q4 5, only total funding/floor listed 4, nothing listed 3 (2 if you set a minimum) · Complexity Low 5 / Medium 4 / High 2 / Unknown 3 |

**Scoring v2 (less harsh, still strict where it matters):** unknown information gets **partial neutral credit, never
full credit**, and the explanation says what is missing, so a good match with a blank field is not buried under weaker
but complete notices. Unrelated notices still score low because alignment carries half the points: on the 3,000-record
benchmark across 33 agencies, the median shortlisted notice scores about 36 while genuine matches score 85–99.
**Hard filters override the score:** expired; state not an
eligible applicant (*Not Eligible for Direct Application* or *Partnership Opportunity*); cost share required when Q5 = No;
award ceiling below Q4. "Too tight" (days left < Q6 prep time) is a flag, not a filter. All exclusions appear under
**Set aside**. Calibration constants are in `scoring/score.py`; tune them with your labeled data.

**AI explanations** return `{matched_objective, objective_citation, grant_evidence_quote, reasons[], confidence,
effort_drivers[]}`. The app checks that the objective exists and that the quote appears word for word in the notice;
anything unverifiable is replaced and marked **Needs review** (shown, not hidden). Retrieved text is wrapped in
`<document>` tags and treated as data, never as instructions.

**Eligibility** (`eligibility/classify.py`) is rules-only: Grants.gov applicant codes + cited notice sentences →
Appears Eligible / Needs Human Verification / Partnership Opportunity / Not Eligible for Direct Application.
Matching-fund, partnership and other conditions are extracted with citations, along with open questions. AI never
decides eligibility.

## 7. Application time estimate
Drivers found in the notice (synopsis, NOFO excerpts, and the full NOFO PDF when available), each with a quote:
LOI/pre-application +2 · narrative page limit +1/+2/+3 (≤10/11–19/20+ pages) · budget justification +1 · cost-share
documentation +2 · letters of support +1 each (max 3) · evaluation plan/logic model/data plan +2 · registrations
(SAM.gov/UEI/Grants.gov) +1 · multi-stage review +2. **0–3 = Low** (~1–2 weeks, 20–60 staff hours), **4–7 = Medium**
(~3–5 weeks, 60–160 hours), **8+ = High** (6+ weeks, 160–320 hours). No drivers = **Unknown — check notice** (never
Low). The top 3 drivers are shown, and the result is compared with days left and Q6 → ✅ Feasible / ⚠️ Tight /
❌ Not enough time. AI-suggested drivers are added only if their quote is verified in the text. The result is always
labeled "Estimate — based on notice requirements".

## 8. Privacy filter design (`privacy/filter.py`)
Scans everything users type: other priority, project search, decision reasons, notes, brief notes. It runs **before**
any AI call, saving feedback, and copying or downloading a brief.
* **Layer 1 (optional):** Azure AI Language PII detection, which stays in the tenant. Set `LANGUAGE_ENDPOINT/KEY`.
* **Layer 2 (always):** local patterns for emails (including "name [at] site [dot] com"), phone numbers (any separator,
  including look-alike Unicode dashes), SSNs, card numbers (Luhn-checked), ID numbers after a cue word (SSN, driver's
  license, passport, tax ID), dates of birth, street addresses and PO boxes, and names after titles or cue words →
  `Contact [NAME] at [EMAIL]`. Text is Unicode-normalised first so look-alike characters can't slip past.
* **Layer 3 (always):** internal-info keywords ("confidential", "internal only", "draft budget", "personnel",
  "do not distribute", "pre-decisional", "not for public release", "FOUO", "CUI", shortfall amounts) → **blocked**, and
  the user is asked to edit.
The user sees what was redacted. Unredacted text is never stored; `privacy/log.json` keeps only counts and types.
The UI has no file upload, and a persistent banner says *Public information only. Do not enter confidential data.*

**Where it runs in the web app (all server-side, in `web/service.py → Engine.screen`):**

| Typed field | Endpoint | Screened before |
|---|---|---|
| Survey "other priority" | `POST /api/survey/{agency}` | saving, matching, any AI call |
| Project search | `POST /api/search/{agency}` | searching |
| Brief notes | `POST /api/brief/{agency}/{id}` | the text copy and the PDF download |
| Decision reason, note, name | `POST /api/decision/{agency}/{id}` | saving |

A redaction returns the cleaned text plus a summary ("Redacted: 1 phone"), which the page shows in a green
*Screened before use* notice. A block returns HTTP 422 and the page shows a red *Not saved or sent* notice.
Every input that accepts text has a ✓ hint under it saying it is screened. `tests/test_web.py` checks every route.

**Clearing decisions:** the Decisions page has *Clear all decisions* (click twice to confirm). The server archives the
old log to `feedback/archive/<agency>_<time-to-the-microsecond>_<random>.json` before emptying it (two clears in the same
second can't overwrite each other), so nothing is lost for audit. Because there is no sign-in, anyone with the link could
clear a log; so every clear is reversible: *Undo* appears right after, and *Restore last clear*
(`POST /api/decisions/{agency}/restore`) puts back the newest archive, then the one before it, and so on.

**Clearing survey answers (the filter):** *Clear answers* (in the survey dialog, the *Your answers* card, or the ⌘K
menu) resets focus areas, other priority, capacity, minimum award, match and prep time to neutral defaults
(`POST /api/survey/{agency}/reset`) and re-ranks. An *Undo* toast puts the previous answers back (they pass the privacy
filter again).

**AI reasons:** an AI-written reason is kept only if the AI's objective and quote verify AND every number it cites
($ amounts, percentages, counts, dates) appears in the notice. Explanations are cached under a version key
(`EXPLAIN_VERSION`), so a rule change regenerates them instead of reusing old ones.

## 9. Testing and evaluation
* `pytest -q`: 49 tests (19 engine + 16 web API, including concurrent decisions, malformed input, midnight roll-over, rate limits, including privacy on every typed-text route) on synthetic `[TEST ONLY]`
  records. They cover hard filters, ranking, "unknown = 0", eligibility labels, a restrictive-eligibility decoy, briefs, time-estimate Unknown, AI quote/objective
  verification (with a deliberately wrong fake AI), privacy redaction and blocking, feedback rules, and that the
  evaluation never fabricates metrics.
* **Evaluation on real data:**
  1. `python -m evaluation.build_label_sheet` writes `evaluation/labels_to_fill.csv` (top, middle and random items per
     agency).
  2. Two teammates fill `relevant` (1/0) and `expected_eligibility` **without looking at scores**, then save the file
     as `evaluation/labels.csv`.
  3. `python -m evaluation.run_eval` (or the Evaluation page) → `evaluation/results/eval_<time>.json/.md` with
     Precision@5, recall@25, eligibility accuracy, plus these tests: expired never actionable, decoys flagged
     (a synthetic universities-only decoy + live semantic decoys), AI explanation accuracy vs. source text, Unknown time estimate, and the PII
     filter on 10 synthetic samples. Failures are listed honestly. With no labels, metrics read "not computed".

**Evaluation page:** a health check for the agency picked in the header, in plain sentences:
*Are the top picks worth your time?* (of the top 5 the team has judged, how many were Pursue/Maybe; shown once 3 are
judged) · *Are good grants ranked above poor ones?* (every liked grant compared with every passed one; can't be
inflated by only judging the top) · *Are the safety rules holding?* Then a 4-line checklist for today's top 5 and a list
of specific grants to look at (title, link, what to do). It checks the exact list the Matches page shows. A Pass for
capacity / timing / money is left out of the answer key; closed or filtered-out grants are left out. Runs in the
background with Pause / Resume / Stop; a run paused for 10 minutes stops itself.
The privacy filter now also removes bare "First Last" names (common first name + surname) while leaving place and
program names such as "Jordan Lake" or "Ryan White HIV/AIDS Program" alone.

## Stretch goals (all three)
**1. Measure your reach.** Evaluation → *Reach*: grants reviewed → possible → recommended; how many of the top 25 come
from federal agencies outside the agency's usual partners, how many were found only by searches beyond its own
keywords, and how many are both ("likely missed by manual monitoring"). Staff can paste a Grants.gov link / ID / number
for a grant they found elsewhere (`POST /api/missed/{agency}`); each report is checked against the data and counted
as caught (with its rank) or a true miss. Also: estimated reading time saved (grants × 3 minutes, labelled as an
estimate).

**2. Race the clock.** Matches page banner: "2 opportunities close within 14 days", each line "This opportunity
closes in 10 days (date)", for grants marked Pursue / Maybe and the current top picks; card tags "Closes in N days".
*Add all to my calendar* downloads an .ics file (`/api/alerts/{agency}/calendar.ics`) with reminders 14, 10, 7 and
1 day before each deadline (Outlook, Google, Apple). Optional Teams / Slack / Power Automate messages: set
`ALERT_WEBHOOK_URL` (`ALERT_WEBHOOK_URL='https://…' bash deploy/update.sh` stores it as a Container Apps secret);
the daily job then posts "closes in N days" on days 14, 10, 7, 3 and 1, each alert once (`alerts/sent.json`).

**3. Learn from the users.** `feedback/learn.py`: grants similar (TF-IDF) to ones the team pursued get up to +8
points, similar to poor fits up to −8; a Pass for capacity / timing / money teaches nothing; a grant is never moved by
its own decision. Each nudge is explained on the grant ("Learned from your team +5: similar to …"). Safeguard:
learning switches itself off for an agency when it would rank the team's own judged grants worse than the plan alone,
and back on when it helps. The Evaluation page shows the effect (top-5 accuracy and ranking agreement, before → after).

**Evaluation scorecard:** screening & time saved · reach · score by decision · top-5 accuracy · average position of
good grants · ranking agreement · AI accuracy (share of AI explanations verified; the rest were replaced) · privacy
filter in real use (last 7 days, counts only) · safety rules. Accuracy is graded on the plan-only ranking so the
team's decisions never grade themselves.

## 10. Reproducible demo walkthrough (about 5 minutes)
1. Open the app URL. Under the headline you should see **Live from Grants.gov · updated …**.
2. Agency **DEQ** (top bar) → survey: tick *Goal 2 → 2.B natural hazards* and *Goal 3 PFAS*, type "stream restoration and flood
   resilience" as the other priority, Q3 = 3, Q4 = Any, Q5 = Sometimes, Q6 = 30 days → **Save**.
3. **Matches**: show the **Due soon** panel, then open match 01 (*Evidence, eligibility, effort and brief →*) → *Why it fits* (score breakdown,
   objective + plan link, evidence quotes) → *Eligibility* (label, cited text, open questions) → *Effort & timing*
   (drivers + feasibility) → *Brief* (download the PDF) → *Decision*: **Maybe** with a note.
4. **Privacy filter (say this out loud):** "A privacy filter screens everything users type before any AI call, save
   or download." Point at the banner, then type `call 919-555-0101` into a Decision note → Save: the green notice
   shows *Redacted: 1 phone* and the saved note reads `call [PHONE]`. Then type `draft budget` into the survey's
   other-priority box → Save: the red notice says *Not saved or sent*. Mention it runs on the server, so it can't be bypassed.
5. **Set aside** on the Matches page, then **Evaluation** → *Run the evaluation now*.

## 11. Security
**Without sign-in (prototype):** each address (the one Azure's ingress records, which a visitor can't fake) may make at most 120 changes or searches a minute (HTTP 429 after that,
`WRITES_PER_MINUTE`); a manual refresh can run once every 10 minutes (`REFRESH_COOLDOWN_SECONDS`) and an evaluation once
a minute (`EVAL_COOLDOWN_SECONDS`). Errors shown in the browser are plain-language; details go to the server log.

Public data only; no uploads. All API and user text is escaped before display. Survey values come from fixed options;
search keywords and IDs are validated before they reach Grants.gov. Secrets are environment variables only.
**Pilot upgrade path:** Microsoft **Entra ID** sign-in (Container Apps built-in auth) · **role-based access** (agency
staff see their agency; OSBM sees all) · **Microsoft Purview DLP** on the storage account and in M365 · **audit logging**
to Log Analytics / Azure Monitor · Key Vault for secrets with managed identity · private endpoints for storage and OpenAI.

## 12. Known limitations
* Grants.gov only; SAM.gov, state pass-through, foundations and professional-organization grants are not covered yet.
* Objective text is a close summary of plan wording, not a verified quotation. Check the cited section.
* NOFO PDF download uses Grants.gov's legacy attachment endpoint and may fail. The estimate then uses the synopsis and
  says so.
* Eligibility comes from structured codes plus keyword rules. "Others (see text)" always needs a person.
* Score calibration constants were set by inspection and need tuning with pilot labels.
* Without Azure AI Language, names are only caught after titles or cue words (see the PII test results).
* No sign-in yet (by design for the prototype): reviewer initials are typed in, and clears are undoable rather than permission-checked.
* 30 of the 33 profiles are close summaries of the 2025-27 plans produced by `agency_profiles/build_statewide.py`; each agency should review its objectives and keywords.

## 13. Statewide expansion path
Add an agency in under a day: download its plan → `python -m agency_profiles.extract_profile ...` (AI draft) → a person
verifies each objective → save it to `agency_profiles/profiles/` → it is picked up automatically (`AGENCIES=all`, the default; set a comma list to restrict). Then: Entra ID +
RBAC, Teams/email deadline alerts (≤30/14/7 days), SAM.gov and state sources, feedback-tuned weights (logged and
testable), Azure AI Search for scale, and a statewide outcome schema (applied / awarded / $) for OSBM reporting.

## Code map
```
web/server.py                Flask app: JSON API, security headers (CSP), gzip, serves web/static
web/gunicorn.conf.py         production server settings (1 process, 8 threads → one shared cache)
web/service.py               engine facade: caching, privacy screening, JSON for the pages
web/build_pages.py           generates the 4 HTML pages from one shared shell (python -m web.build_pages)
web/static/                  index/decisions/evaluation/method .html, stylesheet.css, script.js
app.py                       Streamlit entry (classic backup, MODE=classic)
common/                      config (.env), storage (Blob or local), Azure OpenAI wrapper, text utils
data_retrieval/              Grants.gov client, normalize, refresh pipeline, cache/status, NOFO PDFs
agency_profiles/             profile JSON for 33 NC agencies (DEQ, DNCR, DPI hand-built; 30 more from the OSBM strategic plans via build_statewide.py), loader, AI-assisted extraction
eligibility/                 rules + classification with citations
scoring/                     survey options, hard filters, hybrid /100 score, ranking
time_estimate/               effort drivers + estimate + feasibility
summarization/               verified AI / rules explanations, grant briefs (text + PDF)
privacy/                     sensitive-info filter
feedback/                    survey + decision storage (store.py), learning from decisions (learn.py)
alerts/                      deadline alerts: tracked grants, calendar (.ics), Teams/Slack webhook (deadlines.py)
interface/                   survey, dashboard, reviewed, evaluation, about
evaluation/                  labels CSV, label-sheet builder, PII samples, run_eval.py, results/
tests/                       pytest suite + synthetic TEST ONLY fixture
deploy/                      azure_setup.sh, update.sh (fast deploys), status.sh, appservice_deploy.sh
Dockerfile, Dockerfile.base  app image on top of a cached package image; entrypoint.sh picks MODE=app|classic|job
.vscode/                     tasks, launch (debug) configs, settings, extensions
```

## Performance (the point of the tool is to save staff time)
Measured on a 3,000-notice test dataset, one container:

| What | Time |
|---|---|
| Matches page usable (cards on screen) | ~0.5 s |
| Any API call after warm-up (matches, detail, search, decision) | 2–40 ms |
| Recording a decision, including Pass | ~3 ms (no re-scoring) |
| Saving the survey | ~10 ms; re-ranking runs in the background and is ready before the page reloads |
| 40 simultaneous page loads | ~0.6 s total |

How: the overnight job does the slow work (NOFO PDFs, AI explanations for each agency's top matches →
`precomputed/{agency}.json`). When the server starts it scores every agency in the background, so the first visitor
never waits. Scores are cached per agency + survey + data version; decisions only re-derive the top list. Surveys and
decisions are cached in memory and updated on write. Responses are gzipped; CSS/JS are linked with a content hash and
cached by the browser for a year. The site has no framework and no third-party JavaScript.

## Design
**Web app (default):** dark-first with a light mode (moon button or ⌘K → theme), DM Sans and Manrope type, violet → cyan
gradient accents, subtle grid and noise, cursor glow, scroll progress, scroll-in reveals, count-up stats, animated
score rings, hand-built SVG charts with hover tooltips and table fallbacks, a ⌘K command menu, and a slide-in detail
drawer. Everything respects *reduced motion*. No build step and no third-party JavaScript: the CSP allows scripts only
from the app itself. Styles: `web/static/stylesheet.css`; page markup: edit `web/build_pages.py` and rerun it.

**Switching to the Streamlit backup on Azure:**
`az containerapp update -n app-ffm-web -g rg-ffm-team --set-env-vars MODE=classic` (set `MODE=app` to switch back).

**Classic app:** Editorial look: Fraunces (display serif) for headlines and numbers, Public Sans for body text, warm paper background,
deep ink navy, one lime highlight. All styles are in `interface/theme.py` (colors are the CSS variables at the top).
