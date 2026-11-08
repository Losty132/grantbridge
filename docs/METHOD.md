## How the Federal Funds Matchmaker works

**Purpose.** Help NC agencies find, screen, prioritize and act on federal grants with less staff time.
It supports human judgment: it never makes the final decision and never submits an application.

**Flow.** Agency profile (from the strategic plan) → 6-question survey → Grants.gov ingest → hard filters →
hybrid score (/100) → eligibility label → time estimate → Top N → grant brief → Pursue / Maybe / Pass.

### Data
* **Grants.gov** public API (`search2` + `fetchOpportunity`), refreshed daily by a scheduled job and on demand with
  the **Refresh** button. Every screen shows whether data is **LIVE**, **CACHED** (last refresh failed) or a **SNAPSHOT**.
* **Agency profiles** from strategic plans published by NC OSBM. Each objective is stored separately with its plan
  section and link. Objective wording is a close summary of the plan; check the cited section before quoting it.

### Hard filters (override any score)
Expired · state government not an eligible applicant (labeled *Not Eligible for Direct Application* or
*Partnership Opportunity*) · cost share required when you answered "No" · award ceiling below your minimum.
"Too tight" is a flag, not a filter. Every exclusion is listed under **Filtered out (why)**.

### Score (/100): a prioritization score, not a probability of winning
| Component | Points | How |
|---|---|---|
| Strategic alignment | 50 | Similarity to **each** objective (and the agency's operating programs); best match counts; your Q2 picks are boosted |
| Applicant / program fit | 20 | Eligibility label (10) + program keywords (6) + usual federal partner (4) |
| Deadline feasibility | 15 | Days left vs. your prep time (Q6) and the time estimate |
| Resource feasibility | 15 | Cost share vs. Q5 (5) + award vs. Q4 (5) + complexity (5) |

Unknown information gets partial neutral credit, never full credit, and is named (scoring v2; see README §6). Similarity uses Azure OpenAI embeddings when available, and
TF-IDF otherwise.

### Eligibility (rules only, never AI alone)
Based on the Grants.gov eligible-applicant codes plus cited sentences from the notice. Restrictions, matching funds,
partnership and other conditions are quoted with their source. This is not a legal determination.

### Application time estimate
Effort drivers are found in the notice (synopsis, and the full NOFO PDF when it can be downloaded), each with a quote:
pre-application/LOI (+2), narrative page limit (+1 to +3), budget justification (+1), cost-share documentation (+2),
letters of support (+1 each, max 3), evaluation/logic model/data plan (+2), registrations (+1), multi-stage review (+2).
0–3 points = **Low** (~1–2 weeks), 4–7 = **Medium** (~3–5 weeks), 8+ = **High** (6+ weeks). No drivers found =
**Unknown — check notice**. This is always an estimate based on the notice requirements.

### AI explanations
The model gets the objectives and the notice text (as untrusted data inside `<document>` tags) and must return
structured JSON. The app checks that the objective exists in the profile and that the quoted evidence appears
word for word in the notice. If either check fails, the rules explanation is used and the item is marked
**Needs review**. If AI is unavailable, everything still works with rules + similarity.

### Privacy
**A privacy filter screens everything users type before any AI call, save or download.**
Anything you type (other priority, project search, reasons, notes, your name, brief notes) is filtered on the server before any AI call,
save or download. Emails, phone numbers, SSNs, card numbers, street addresses and names are redacted (Azure AI
Language PII when configured, plus a local filter). Phrases like "confidential", "internal only" or "draft budget"
block the action until you edit the text. Only counts of redactions are logged, never the original text.

The filter runs on the server, so it applies no matter how the app is reached. You always see what was redacted
(green notice) or why something was blocked (red notice).
