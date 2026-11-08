# Solution Design & GenAI Field Notes

*Repository copy. The submitted Solution Design & GenAI Field Notes document is the full version. Only mistakes we actually observed are listed.*

## 1. Target user
A **state agency employee who handles federal grants as one part of a larger job**, such as a program manager,
budget analyst or IT project manager. The sponsor behind the challenge is **OSBM**, which wants the state to stop
missing federal funding it could win.

## 2. What we learned in the Discovery Session
* **Time is the main constraint.** Every panelist has another primary job. One manages 46 workstreams. They mostly
  apply when a grant is handed to them that's quick to apply for and an obvious match.
* **There's no standard process.** The state has no procedure for grant-seeking. Some agencies have one person who
  reads a daily Grants.gov digest; others have nobody. Past fixes (crowdsourcing, agency points of contact,
  periodic surveys) faded out.
* **A list of everything is useless.** "If it scrapes 800 grants and tells me I'm eligible for 700, nobody will read
  that." They want the few most likely to succeed, how hard each is to apply for, and no expired deadlines.
* **Eligibility and competitiveness are hard to judge.** Who can apply (state vs. local), required matching funds,
  ability to deliver, community partners, and a clear plan all matter.
* **Sources are scattered.** Grants.gov isn't complete. SAM.gov, agency sites, state portals, foundations and
  professional organizations matter too.
* **Matches should follow agency priorities**, now and a few years out, using public strategic plans and budgets.
  That includes discrete events like disaster recovery (Hurricane Helene).
* **Privacy:** don't send sensitive data to an AI model. Federal listings and state plans are public.
* **Sustainability:** OSBM probably won't have a dedicated team to run it, so the tool must be simple and low-maintenance.

## 3. What changed our plan
| Before | After the session |
|---|---|
| Show every eligible grant | **Ranked shortlist**; Low confidence hidden by default; expired items dropped |
| Keyword search per agency | **Broad pull + goal-based matching**, plus a measure of what keyword search misses |
| AI picks grants | **AI explains; people decide** (Pursue / Maybe / Pass on every item) |
| One score | **Score breakdown** with the strategic-plan goal it supports, days left, and effort flags (cost share) |
| Send everything to the LLM | **Summaries for the top 15 only**, contact details redacted, grounding check on dollar amounts |

## 4. Problem statement and requirements
"State staff who handle grants on top of full-time jobs miss relevant federal funding because finding and
matching it is manual and scattered. Our matchmaker ranks new opportunities every morning against each agency's own
strategic plan, explains why each one matches, and lets staff record a decision in seconds."

Requirements: updates daily without anyone pressing a button · explainable (goal plus breakdown) · a person decides ·
built on real NC strategic plans · deadline-aware · cheap and simple to run · works without AI if needed.

## 5. GenAI usage
**Tools:** Claude (planning, code generation, summarizing the discovery session); Azure OpenAI `gpt-4.1-mini` (chat) and
`text-embedding-3-small` inside the product.

**Key prompts:** *(paste the 3–5 prompts your team actually used here)*
1. "Here is the outline of the solve-a-thon event… write me the code so I can put it into Microsoft Azure."
2. In-product summary prompt: see `summarization/explain.py` (`SYSTEM`). It uses only the notice text, says "not stated"
   instead of guessing, and returns JSON.
3. Profile drafting prompt: see `agency_profiles/extract_profile.py` (`PROMPT`).

**Where AI was wrong and how we caught it** *(add your own as you test)*:
* **Transcription errors.** The automatic transcript of the discovery session turned "grants.gov" into "plants.gov"
  and "grandpa", and "SAM.gov" into "Sam SAO". **Caught by** checking against our handwritten notes and the challenge page.
* **Over-scoring off-topic grants.** The first scoring version let a cybersecurity grant reach "Medium" for DEQ,
  because eligibility and timing alone added about 25 points. **Caught by** reviewing each agency's top results by
  hand. **Fixed** by requiring topic relevance (semantic + keyword) before an item can be Medium or High.
* **Retired AI model.** The setup script's first chat model (gpt-4o-mini 2024-07-18) was retired in Azure and the
  deployment failed. **Caught by** reading the deployment output. **Fixed** by having the script try a list of current
  models and use the first one the region allows.
* **Quote cut in half.** The sentence splitter broke "The U.S. Geological Survey…" at "U.S.", so the evidence quote
  began mid-sentence. **Caught by** a smoke test on the real landslide listing. **Fixed** with abbreviation handling,
  plus a regression test.
* **Wrong kind of match.** The landslide grant first matched DEQ's *operating program* instead of a *strategic-plan
  objective*, so the brief couldn't cite the plan. **Fixed:** the brief always names the best plan objective (DEQ 2.B)
  and shows the program as supporting context. (The landslide test case was later removed from the app at the team's
  request; the fix to the brief logic stays.)
* **Wrong numbers in UI copy.** While drafting a method page, the AI wrote the score weights as "alignment 50, applicant
  fit 20, feasibility 15, timing 15". The real weights are alignment 50, applicant fit 20, deadline feasibility 15,
  resources 15. **Caught by** checking the text against `scoring/score.py` before shipping. **Fixed** in the copy.
* **Layout bugs the AI didn't foresee.** A generated mobile layout overflowed sideways by 97 px at 390 px wide (a grid
  child without `min-width: 0`), and animated counters rendered white-on-white inside a light preview frame. **Caught
  by** automated screenshots at 390/768/1440 px with an overflow check. **Fixed** before release (that version of the
  UI was later replaced by the team's preferred design).
* **"1 notices".** Generated copy didn't handle singular counts. **Caught by** reviewing screenshots. **Fixed.**
* **Bugs found by an independent AI review (Codex), then checked by hand.** We asked a second AI to review the code
  and run probe tests. Several of its findings were real and were fixed with a regression test each: a notice saying
  "State governments are not eligible" was still labeled *Appears Eligible*; "unknown" cost sharing earned the
  "no cost share required" points; "a letter of intent is not required" counted as extra effort; grant details and
  NOFO text were never re-fetched after amendments; rankings didn't roll over at midnight; a table button bound twice
  downloaded the CSV twice. **AI was wrong here too:** two other AI reviews that could not open the zip reported
  invented code ("`send_file(STATIC_DIR / filename)`", "`renderGrantCard`") and line numbers. **Caught by** checking
  every claim against the real files and reproducing it before changing anything.
* **Unverified excerpts.** NOFO quotes gathered with a web-reading tool for the cached reference listing are labeled
  "excerpt; verify", because the tool can paraphrase.
* **Invented numbers or quotes in AI output** (guarded against). The app checks every AI evidence quote and effort
  driver word for word against the notice. Failures are replaced and the item is marked "Needs review". The grounding check flags any dollar amount in an AI summary
  that doesn't appear in the notice; the app shows a warning on that item. Record real cases you see here.

* **Privacy filter missed a bare name** ("Jordan Lee approved the plan"). **Caught by** our own evaluation's privacy
  test. **Fixed** with a first-name + surname rule that leaves place and program names ("Jordan Lake", "Ryan White
  HIV/AIDS Program") alone; the test sentence now uses a different made-up name.
* **A metric that proved nothing.** The first evaluation's "found rate" was about 100% by construction (teams only
  judge grants the app showed them). **Caught by** questioning the numbers. **Replaced** with pairwise ranking agreement.
* **Learning from feedback made things worse** on near-identical test grants. **Caught by** the before/after measure.
  **Fixed** with a safeguard that switches learning off for an agency when it doesn't help.
* **Times shown in UTC** because Azure servers run on UTC. **Caught by** the team on the live site. **Fixed:** Eastern time everywhere.

## 6. Evidence
Run the Evaluation page for each agency after the team has recorded decisions: it reports screening and time saved,
reach, score by decision, top-5 accuracy, average position of good grants, ranking agreement, AI accuracy, privacy
filter use and the safety checks. `pytest -q` runs 49 automated tests.
