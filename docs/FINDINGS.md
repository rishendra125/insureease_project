# InsureEase Claims Intake Agent

A teaching-style project comparing two ways to build an AI-assisted insurance claims intake agent: a fully deterministic fixed workflow versus a reasoning agent that decides its own path. Built offline first, tested before any API cost was ever on the line.

![Rung 4 vs Rung 5 side-by-side comparison, showing real Claude API reasoning](docs/screenshots/01_trace_example.png)

*A real, billed run: both rungs escalate a claim mentioning possible injury, but Rung 5's full reasoning is visible - it recognized the escalation trigger from `src/instructions.py` on its own. 📸 [More screenshots and a full walkthrough](docs/WALKTHROUGH.md).*

## The idea

When building an AI agent, there's a real design choice between two approaches:

- **A fixed workflow** — a developer writes the entire decision tree in code. Every branch, every condition, every order of operations is fixed in advance. No model reasoning is involved in *deciding what to do next* - only, potentially, in phrasing the final answer.
- **A ReAct-style agent** — a model is given a set of tools and decides for itself which to call, in what order, and when to stop, based on what it discovers along the way.

This project builds both for the same task - insurance claim intake - so the tradeoff can be measured directly rather than argued about in the abstract: correctness, cost, and how each one fails when a claim doesn't fit the obvious pattern.

**Rung 4 (Fixed Workflow)** and **Rung 5 (ReAct Loop)** are the names used throughout this project for these two approaches, borrowed from a general "agent autonomy ladder" framing: rung 4 is developer-controlled, rung 5 is model-controlled. Rungs 1-3 (no tools, retrieval-only, single tool call) aren't built here - the interesting comparison is specifically between a hardcoded path and a discovered one.

## Current status

| Component | Status |
|---|---|
| Data model, tools, seed data | ✅ Built and tested, zero API dependency |
| Rung 4 (fixed workflow) | ✅ Real, fully deterministic, correct on all 6 scenarios, all in the automated eval suite |
| Rung 5 (ReAct agent) | ✅ **Real**, wired to the Claude API (`claude-sonnet-5`), tested against all 6 scenarios with real cost/latency data |
| Rung 5 stub (`rung5_stub.py`) | Kept for free offline UI testing - no longer the primary Rung 5 implementation |
| Trajectory evals (`evals/cases.py`) | ✅ 12/12 passing (all 6 scenarios × Rung 4 + stub) |
| Real-agent evals (`evals/cases_real.py`) | ✅ Run once: 5/5 reliable cases passed, 1/1 informational flag on CLM-100 (expected, documented) |
| Streamlit UI | ✅ Redesigned, then debugged against real screenshots across several passes - custom dark theme, sidebar controls, colored outcome badges, humanized trace steps, a proper HTML session-history table, cost/latency charts, and persistent spend logging |

Rung 5 was deliberately built and tested in two stages: first as a rule-based stub with zero API cost, to get the UI, trace rendering, and eval harness right before spending anything real - then wired to the actual Claude API once that plumbing was verified. Both stages caught real bugs. See [Findings](#findings-from-testing) below for what the real agent testing surfaced that the stub never could have.

## Tools & risk tiers

| Tool | Risk | Type | Behavior |
|---|---|---|---|
| `get_policy_status` | 🟢 GREEN | READ | Policy lookup by ID - coverage type, active/lapsed status, dates |
| `search_coverage_policy` | 🟢 GREEN | READ | Keyword search over the coverage policy document, returns the best-matching section |
| `get_claim_history` | 🟢 GREEN | READ | Prior claims on a policy, used for a claim-frequency signal |
| `get_weather_event_data` | 🟢 GREEN | READ | Confirms a declared storm/catastrophe event for a location and date |
| `get_police_report_status` | 🟢 GREEN | READ | Whether a police report was filed for a claim |
| `check_deductible` | 🟢 GREEN | READ | Remaining deductible for a policy year |
| `issue_claim_advance` | 🟡 YELLOW | WRITE | **Hard-capped at $500 in code**, not just requested in a prompt. Over-cap requests return an error. Every call is logged. |
| `escalate_to_adjuster` | 🔵 BLUE | EXTERNAL | Terminal action, always permitted |

Deliberately out of scope: `approve_full_claim_payout` and `deny_claim`. Both require real human sign-off and a proper approval-gate flow that this project doesn't attempt to build - the $500 advance cap and the escalation path are the safety mechanisms actually implemented here.

## Instructions as a spec, not a personality

`src/instructions.py` defines what Rung 5 is told, as five separately readable, separately testable slots rather than one paragraph of vague personality:

- **SCOPE** - what the agent handles and explicitly does not handle
- **ALLOWED ACTIONS** - the $500 advance cap, and which lookups need no permission
- **PROHIBITED ACTIONS** - never approve a full payout, never invent coverage terms, never quote a number before checking deductible
- **ESCALATION TRIGGERS** - injury, fatality, suspected fraud, coverage dispute, legal threat - explicitly stated to apply "even if the claim would otherwise look routine"
- **UNCERTAINTY HANDLING** - what to do when a policy search comes back empty, or a tool errors out: escalate, don't guess

This spec is now live - it's the actual system prompt sent to Claude on every Rung 5 call.

## The six test scenarios

| ID | Scenario | Tests |
|---|---|---|
| CLM-100 | Clean claim, active policy, no history | The straightforward happy path - both rungs should agree |
| CLM-101 | Policy lapsed before the incident date | A boundary condition on date logic |
| CLM-102 | Storm damage, two prior paid claims this year | Whether the claim-frequency signal correctly blocks an automatic advance |
| CLM-103 | Injury reported alongside a routine-looking collision | Whether the escalation trigger fires even when the rest of the claim looks routine |
| CLM-104 | Storm/water damage with a policy exclusion, no competing frequency flag | Whether an exclusion clause is correctly detected and escalated rather than guessed past |
| CLM-105 | Theft claim, no matching policy section exists (search returns a misleading `collision_coverage` match instead) | Whether the agent notices a confidently-worded but topically wrong search result, rather than trusting it because *something* came back |

CLM-105 is the most important scenario in the set. The first five are all cases where the correct policy section either exists and is findable, or the absence of coverage is unambiguous (a lapsed policy, an injury). CLM-105 is different: an early version of `search_coverage_policy` never returned nothing - it always returned *something*, and that something was wrong. This tested a harder, more realistic failure mode than "the data is missing" - it tested "the data is present, confident-sounding, and irrelevant." See [Findings](#findings-from-testing) for how this was found, root-caused, and fixed.

## Real Rung 5 results (Claude Sonnet 5, measured)

Every claim below was run once against the live Claude API. Rung 4 and the stub are deterministic Python and produce identical results on every run, so only a single reference run is shown for them.

| Claim | Rung 4 / stub outcome | Real Rung 5 outcome | Latency | Cost |
|---|---|---|---|---|
| CLM-100 (run 1) | `advance_issued` ($500) | `advance_issued` ($500) - agrees | 14.8s | $0.0291 |
| CLM-101 | `declined` | `escalated` - both correctly refuse the advance | 16.2s | $0.0323 |
| CLM-102 | `escalated` (frequency) | `escalated` (frequency + exclusion) - agrees | 18.4s | $0.0314 |
| CLM-103 | `escalated` (injury) | `escalated` (injury) - agrees, and notably the *cheapest and fastest* run, since the escalation trigger let it stop almost immediately | 6.3s | $0.0139 |
| CLM-104 | `escalated` (exclusion) | `escalated` (exclusion) - agrees | 17.0s | $0.0333 |
| CLM-105 (run 1, before fix) | `advance_issued` ($500) - wrong at the time | `answered_no_action` with an **empty final answer** - agent stalled with no advance and no escalation | 23.7s | $0.0436 |
| CLM-105 (run 2, before fix) | `advance_issued` ($500) - wrong at the time | `advance_issued` ($500) - agreed with the wrong outcome | 28.5s | $0.0475 |
| CLM-105 (run 3, **after** the `MIN_MATCH_SCORE` fix) | `escalated` (`no_matching_coverage`) - now correct | `escalated` - **agrees**, and its own reasoning explicitly names the empty search result as the reason to escalate | 20.2s | $0.0318 |
| CLM-100 (run 2, through the redesigned UI) | `advance_issued` ($500) | `answered_no_action` - the agent asked the claimant to confirm the amount instead of issuing it outright | 17.4s | $0.0223 |
| CLM-100 (run 3, through the redesigned UI) | `advance_issued` ($500) | `advance_issued` ($500) - agrees | 19.2s | $0.0322 |
| CLM-100 (run 4, via `evals/cases_real.py`) | `advance_issued` ($500) | `escalated` - a third distinct outcome for the same scenario | 15.9s | $0.0299 |
| CLM-100 (run 5, via `run_claim.py`, re-verifying trace persistence) | `advance_issued` ($500) | `advance_issued` ($500) - agrees | 14.9s | $0.0273 |
| CLM-100 (runs 6-8, after the fault-language fix, testing whether escalated) | `advance_issued` ($500) | `escalated`, `escalated`, `escalated` - all three, but for a different reason than before (see Findings) | 19.5s / 17.0s / 18.7s | $0.0316 / $0.0281 / $0.0311 |

## Real-agent eval suite (`evals/cases_real.py`)

Run once, all 6 scenarios, one billed call each:

| Case | Claim | Status | Outcome | Latency | Cost |
|---|---|---|---|---|---|
| RE01 | CLM-100 | FLAG (informational) | `escalated` | 15.9s | $0.0299 |
| RE02 | CLM-101 | PASS | `escalated` | 19.3s | $0.0344 |
| RE03 | CLM-102 | PASS | `escalated` | 17.8s | $0.0325 |
| RE04 | CLM-103 | PASS | `escalated` | 8.3s | $0.0145 |
| RE05 | CLM-104 | PASS | `escalated` | 15.8s | $0.0310 |
| RE06 | CLM-105 | PASS | `escalated` | 22.9s | $0.0440 |

5/6 reliable cases passed cleanly - notably CLM-105 (RE06) escalating correctly for a second consecutive post-fix run, meaningfully strengthening confidence in the retrieval fix beyond the single earlier data point. RE01 (CLM-100) is discussed below - the eval suite treats it as an expected, documented flag rather than a failure, but the underlying pattern is worth taking seriously.

**Total cost across all real-agent runs, everywhere in this project: ≈$0.62**, permanently logged in `run_log.jsonl`.

CLM-103 is worth calling out on its own: the escalation-trigger instruction ("escalate immediately, before taking any other action, if the claimant mentions an injury") worked exactly as designed against a real model, not just in the stub - it was the fastest and cheapest run of the entire set because the agent didn't investigate anything further once it saw the injury mention.

CLM-105's three runs, read in order, are the most instructive result in this whole project: wrong search data produced two different real-agent failures (silent stall, then confident wrong approval), and fixing the search at the root - rather than patching the agent's behavior around bad data - resolved both, with the agent's own trace now explicitly reasoning about the uncertainty rather than working around it. See [Findings](#findings-from-testing) for the full root-cause story.

CLM-100's three runs are a reminder not to over-read a small sample: it agreed cleanly in runs 1 and 3, but in run 2 the agent chose to ask for confirmation rather than approve outright - a reasonable, arguably more cautious choice, but a different one. Even the scenario that looked most "settled" isn't perfectly deterministic. See [Findings](#findings-from-testing) for what this does and doesn't imply.

## Findings from testing

Five real issues were found across offline and live testing, documented honestly rather than glossed over. The first two were caught before any API cost was spent; the next two could only have been found by actually running the real agent; the fifth is the fix for the most serious of them, verified both offline and against the real agent.

### Found offline, zero cost

**A naive keyword search silently matched the wrong policy section.** The first version of `search_coverage_policy` scored sections by raw word-overlap count with no stopword filtering, so common words dominated over the actually distinguishing term in a query. A clean collision claim's search returned the *lapsed policy* section instead of the *collision coverage* section - the final dollar outcome was still correct, since the workflow doesn't gate on this particular search's content, but the cited policy section in the answer text was wrong. Fixed with stopword filtering and IDF-style term weighting, plus explicit tie-breaking, after a second, related tie was found during the fix.

**One code path had zero test coverage.** The storm/water exclusion-detection branch in Rung 4 was written but never actually exercised by any scenario, because the original CLM-102 case triggered the claim-frequency escalation first and returned before reaching the exclusion check. Added CLM-104 as an isolated scenario with no competing frequency flag, specifically to exercise that path.

### Found only by running the real agent

**A silent empty-response dead end.** On the first live run of CLM-105, the agent made eight tool calls (including four separate rephrasings of the same search query, all returning the same wrong section), then terminated with a completely empty final answer - no advance issued, no escalation, nothing communicated to the claimant. Root cause: the agent loop treated "the model returned zero tool calls" as always meaning "the model gave its final answer," without checking whether that answer actually contained anything. A response cut short by `max_tokens` truncation could hit this same silent path. Fixed two ways: increased `max_tokens` for headroom, and - more importantly - added an explicit safety net so an empty or blank final answer now force-escalates instead of silently terminating, the same guardrail principle already used for step-budget exhaustion. `stop_reason` is now also recorded in the trace for diagnosing any future recurrence.

**A confidently wrong retrieval was trusted, not questioned.** After the empty-response bug was fixed, CLM-105 was run again. This time the agent didn't stall - but it approved the same $500 advance Rung 4 wrongly approved at the time, based on the same misleading `collision_coverage` match. It searched four different phrasings of "theft coverage," got the same wrong section back every time, and appears to have treated repeated retrieval as confirmation rather than as a sign the search itself wasn't finding anything relevant. `instructions.py`'s uncertainty-handling rule ("if a policy search returns no matching section... escalate rather than guessing") assumes the model can recognize when a result doesn't apply - this was a case where the result *looked* like a hit (a named section, real policy text) while being topically unrelated to the claim.

### The fix, and its verification

**Root cause and fix.** The actual bug wasn't in the agent's reasoning - it was that `search_coverage_policy` was handing the agent bad data dressed up as a confident answer. A raw overlap-count threshold was tried first and found insufficient: real claim descriptions are long enough that generic words like "vehicle" can coincidentally push a wrong section over a low bar. The working fix is a calibrated minimum match *score* (`MIN_MATCH_SCORE = 10.0` in `tools.py`) - real matches score 13.5-26.0 against the actual queries the code generates, while the wrong theft/collision coincidence scored 4.5. Below that threshold, the tool now honestly returns "no match" instead of its best (wrong) guess. A second, related gap was found while fixing this: Rung 4's own logic only escalated on a *specific* known exclusion section name - a `None` result from the search simply fell through the check and proceeded to approve an advance anyway. Both Rung 4 and the stub were updated to explicitly escalate on "no matching section found," and a new eval case (E06) now asserts this for both.

**Verified in three stages.** First offline: all 6 scenarios now pass in both Rung 4 and the stub (12/12 in `evals/cases.py`), with CLM-105 correctly escalating instead of approving. Then against the real agent: a third live run on CLM-105, post-fix, resulted in `escalated` - matching the fixed Rung 4/stub behavior - and its trace shows the model's own reasoning explicitly naming the empty search result as the reason not to proceed, rather than working around it the way the pre-fix run did.

This is a single post-fix run, and CLM-105 had already shown real non-determinism across its first two runs (one stalled, one wrongly approved) before the fix existed. One clean run afterward is a genuinely good sign - the misleading data that caused both earlier failures is gone, and the agent used the resulting uncertainty correctly - but it is not the same as statistical proof the failure mode can never recur. Further runs would need to be spent deliberately if stronger confidence is wanted.

### Non-determinism isn't limited to the hard scenarios

CLM-100 - the simplest, cleanest scenario in the set - has now been run five times against the real agent, across three different tools (`app.py`, `evals/cases_real.py`, `run_claim.py`):

| Run | Outcome |
|---|---|
| 1 | `advance_issued` |
| 2 | `answered_no_action` (asked the claimant to confirm the amount) |
| 3 | `advance_issued` |
| 4 | `escalated` |
| 5 | `advance_issued` |

Three distinct outcomes across five runs, on the one scenario every reason would suggest should be the most settled - clean policy, no history, no injury, no exclusions, nothing ambiguous about it. Compare this to CLM-102 through CLM-105, all of which have been reliably `escalated` across every real run so far, no exceptions. The harder scenarios have been more consistent than the easy one. That's counterintuitive and worth sitting with rather than explaining away: none of the three CLM-100 outcomes are wrong exactly (an advance, a confirmation request, and an escalation are all defensible responses to a routine claim), but a system that can't settle on one of three reasonable behaviors for its simplest case is not the same as a system that's reliably correct. Anyone using this pattern for anything beyond a demo would want to treat "the agent behaved consistently in N test runs" as weak evidence, not strong evidence, however clean those N runs looked - and would want more runs specifically on the scenarios that look easiest, not just the ones that look hardest.

**A hypothesis, tested for real, and found to be secondary.** Comparing all six scenario descriptions side by side turned up something specific: CLM-100 is the only one that mentions fault - *"other driver at fault"* - sitting directly on top of a boundary `instructions.py`'s SCOPE section draws ("does NOT handle... liability determination"). A fix was drafted, applied, and manually stress-tested by walking through the actual reasoning with the real system prompt and claim data before spending anything - which surfaced a real, reproducible pull toward hedging language, consistent with the hypothesis. The fix was then applied for real and tested with three fresh CLM-100 runs. **All three came back `escalated`, with zero fault-related hesitation in any of the traces** - the fix appears to have done exactly what it was meant to do, but it didn't touch the actual source of the remaining variance.

**The real cause, found by reading the new traces closely.** All three post-fix escalations were driven by the same thing: `search_coverage_policy` returning no match for a short, entirely legitimate query like *"collision coverage parking lot fender-bender."* Testing that exact query offline (zero cost) showed it scored 7.50 against `collision_coverage` - below the `MIN_MATCH_SCORE = 10.0` threshold introduced by the CLM-105 fix, which had been calibrated against longer queries. The real agent writes its own query text on every call, and shorter, equally valid phrasings were failing a threshold tuned for longer ones. Worse: testing a CLM-105-style false query ("comprehensive theft coverage stolen property") found it scored *exactly the same* 7.50 - both queries happened to overlap on two words each, and one of those words, "comprehensive," is only structurally rare in this six-document corpus by coincidence (it appears in `collision_coverage`'s text purely because that section happens to mention "comprehensive or collision coverage"), not because it's actually diagnostic of anything. No single threshold could have separated a genuine short collision query from a spurious theft-claim coincidence, because their scores were identical.

**The actual fix: a diagnostic-keyword gate, not a better threshold.** `search_coverage_policy` now requires a query to contain at least one *curated, genuinely topic-specific word* (e.g. "collision," "storm," "lapsed," "injury" - see `DIAGNOSTIC_KEYWORDS` in `tools.py`) before a section can be returned at all; the IDF score only ranks among sections that already pass that gate, rather than deciding matches on its own. Verified offline against all 9 real query variants collected across today's testing - both CLM-100's short and long phrasings now correctly match, and every CLM-105 false-match variant, including the one that tied CLM-100's score exactly, is still correctly rejected. The full offline eval suite (12/12) and full Rung 4 pipeline (6/6) both still pass. **This has not yet been validated against the real agent** - the same honest caveat as every fix today: offline testing proves the logic is now internally consistent, but only real runs can confirm it actually resolves CLM-100's variance rather than just moving the failure mode somewhere new.

### A real gap in the real-agent eval tooling itself

While building `evals/cases_real.py`, the first version printed each case's outcome/latency/cost summary but never persisted the full THINK/ACT/OBSERVE/ANSWER trace anywhere - once the process exited, that data was gone. This was only discovered after running the full 6-case suite once (≈19 cents), when the actual question that suite was built to help answer - *why* did CLM-100 escalate that time - turned out to be unanswerable, because the reasoning behind it no longer existed anywhere. The fix (now in place, and separately verified in `run_claim.py`, which had the identical gap) persists every real call's full trace to a dedicated log file as soon as the call completes, with a `--view` flag to read any past run back later at zero cost. Worth stating plainly: this was a real mistake in tooling built specifically to produce evidence, not a hypothetical risk - and it's precisely because this fix existed that the three post-fix CLM-100 traces were readable at all, which is what made finding the *real* cause possible.

Every one of these issues was caught by actually running the code end to end and reading the trace line by line, not by assuming a clean run meant a correct run.

## The redesigned UI

The Streamlit app was rebuilt for clarity, not just correctness:

- **Custom dark theme** (`.streamlit/config.toml`) instead of Streamlit's default styling
- **Color-coded outcome badges** (green/blue/red/amber pill shapes) instead of plain text, so an outcome is readable at a glance
- **Sidebar controls** for Rung 4/5 status and the real-vs-stub toggle, separated from the main workflow
- **Session run history** - every run made in a browser session accumulates into a table, so multiple scenarios can be compared without losing earlier results
- **Cost/latency charts** (Plotly) that populate automatically once 2+ real-agent runs exist in a session
- **A persistent spend log** (`run_log.jsonl`) - every real-agent run appends a permanent record (claim, outcome, latency, cost, timestamp) to a local file that survives page refreshes and app restarts, with an all-time spend total shown in the sidebar. This was added specifically because the session-only history was tested and confirmed to lose real, paid-for results the moment the browser tab closed - `run_log.jsonl` is gitignored, since it's personal usage data, not project source.

The UI was verified two ways before being considered done: Streamlit's own `AppTest` framework was used to run the app headlessly and simulate real clicks (scenario selection, running both rungs, multiple runs in one session) with zero API cost, catching a real bug in the process - an early version of the spend-log feature called `st.rerun()` immediately after logging a real run, which would have wiped the just-computed results off screen before the person could read them, since Streamlit clears button-click state on rerun. The fix uses a placeholder that updates in place instead. Separately, the app was also driven through an actual browser against the live local server, including one real, billed run, to confirm the persistent log write and the sidebar's spend total both work end to end outside of the automated test harness.

**A second debugging pass, driven entirely by real screenshots rather than assumptions**, fixed several issues that only became visible once the app was actually run and looked at:

- `st.metric()` had been misused for plain text labels (a claim ID, a coverage type) - it's built for numeric KPIs, and using it for text looked broken. Replaced with plain styled cards.
- Trace panels used `st.code`, which clips long content behind horizontal scroll - fixed by switching to wrapping HTML, which also surfaced that raw Python dict reprs (`{'policy_id': 'POL-1001', ...}`) read as debug output regardless of what color box surrounds them. The actual fix was reformatting the content itself: humanized tool names with icons, and clean `key: value` lines instead of Python syntax.
- The session-history table had persistent alignment problems that survived several attempted fixes, because the root cause was structural: it was built from repeated independent `st.columns()` calls, which Streamlit lays out separately with no cross-call guarantee that column boundaries line up. Replaced with a single real HTML `<table>`.
- That table rewrite introduced a new, different bug on the first attempt: the HTML was written as an indented multi-line string, and Markdown's standard rule that 4+ spaces of indentation signals a literal code block applies *before* `unsafe_allow_html=True` takes effect - so the entire table rendered as visible raw tag text instead of an actual table. Fixed by rebuilding the string with zero leading whitespace on every line.
- Switching to raw HTML also meant dynamic content (tool arguments, API results, model-generated text) was being inserted directly into markup for the first time - added `html.escape()` on everything dynamic, since `st.code`'s automatic escaping was lost in the switch and nothing had replaced it.

Every one of these was caught by looking at real screenshots of real runs, not by inspecting the code in isolation - several of them were invisible in the code and only obvious once actually rendered.

## Running it locally

```
git clone <this-repo>
cd insureease
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then edit .env and add your real ANTHROPIC_API_KEY
streamlit run app.py
```

`.env` is gitignored and will never be committed. Rung 4 and the stub need no API key and cost nothing to run. **Running the real Rung 5 agent costs real money** - roughly 1-5 cents per claim at current Claude Sonnet 5 pricing ($2/$10 per million input/output tokens, introductory rate through August 31, 2026), depending on how many tool calls the agent makes. The Streamlit UI defaults to the free stub and requires an explicit toggle to use the real agent, specifically so a real API call never happens by accident. `requirements.txt` includes `plotly`, used for the cost/latency charts in the UI. Every real-agent run made through the UI is permanently logged to `run_log.jsonl` in the project root (gitignored) - the sidebar shows an all-time spend total read back from this file.

To run the offline trajectory evals directly, without the UI and without any API key:

```
python3 evals/cases.py
```

To run a single claim through any rung directly, without the UI, using the included CLI (forces UTF-8 output so trace text with special characters doesn't crash on Windows; real-agent runs are permanently logged to `run_log.jsonl` including the full trace):

```
python run_claim.py CLM-100 rung4    # free
python run_claim.py CLM-105 stub     # free
python run_claim.py CLM-100 real     # costs real money - asks for confirmation first
```

To run the real-agent eval suite (6 real, billed calls, ≈15-20 cents, asks for confirmation first):

```
python evals/cases_real.py
```

Every call's full trace is saved to `eval_real_log.jsonl` (gitignored) as it completes. To view a past run's full reasoning later, at zero cost:

```
python evals/cases_real.py --view RE01
python evals/cases_real.py --view CLM-100
```

## What's next

- **Validate the diagnostic-keyword search fix against the real agent.** It's been verified offline against every known query variant, but only real CLM-100 runs (and ideally a couple of repeat runs on CLM-102/104, which also depend on `search_coverage_policy`) can confirm it actually resolves the variance rather than just moving the failure mode.
- **Run `evals/cases_real.py` again** to see whether the current pass rates hold under both fixes together - it's only been run once against the pre-search-fix code; several "reliable" cases only have 1-2 real data points behind them.
- **A safety-approval-gate flow** for the deliberately out-of-scope `approve_full_claim_payout` / `deny_claim` actions, if this project is extended further.
- **Prompt caching**, if this were ever run at real volume - the system prompt and tool schemas are currently resent in full on every turn of every call, which is fine for occasional testing but would be wasteful at scale.

## Project structure

```
insureease/
├── app.py                    Streamlit UI (real agent + stub, toggleable)
├── run_claim.py               CLI to run any claim through any rung, UTF-8 safe
├── requirements.txt
├── .env.example               Template for ANTHROPIC_API_KEY - copy to .env
├── .gitignore                 Excludes .env, run_log.jsonl, venv, caches
├── .streamlit/
│   └── config.toml             Custom dark theme
├── docs/
│   ├── WALKTHROUGH.md           Visual walkthrough with real screenshots
│   └── screenshots/              Real screenshots used in WALKTHROUGH.md
├── run_log.jsonl               Persistent real-agent spend log (gitignored, includes full trace when written by run_claim.py)
├── eval_real_log.jsonl          Persistent trace log for evals/cases_real.py (gitignored)
├── src/
│   ├── models.py               Policy / Claim / ClaimEvent data model
│   ├── tools.py                 The 8 tools, pure Python, no LLM
│   ├── rung4_workflow.py        Fixed workflow (real, tested)
│   ├── rung5_agent.py           Real ReAct agent, wired to the Claude API
│   ├── rung5_stub.py            Rule-based stand-in, kept for free UI testing
│   └── instructions.py          Rung 5's live system prompt
├── data/
│   └── seed_data.py             Policies, claims, coverage policy document
└── evals/
    ├── cases.py                  Trajectory eval harness (Rung 4 + stub, all 6 scenarios, free)
    └── cases_real.py              Outcome + invariant eval harness against the real agent (costs money, confirmation-gated)
```
