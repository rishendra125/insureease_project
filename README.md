# InsureEase

A teaching project that builds the same thing two ways — an insurance claims intake agent — and measures the difference directly.

**Rung 4** is a fixed Python decision tree. Every branch, every condition, every order of operations is written by a developer in advance. No model reasoning is involved in deciding what to do next.

**Rung 5** is a ReAct-style agent. It gets a set of tools and decides for itself which to call, in what order, and when to stop, based on what it discovers along the way.

Both handle the same six claim scenarios. The tradeoff — correctness, cost, latency, failure modes — is measured directly rather than argued about in the abstract.

![Rung 4 vs Rung 5 side-by-side comparison, showing real Claude API reasoning](docs/screenshots/01_trace_example.png)

*A real, billed run: both rungs escalate a claim mentioning possible injury, but Rung 5's full reasoning is visible — it recognised the escalation trigger from `src/instructions.py` on its own. See [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md) for screenshots and a full walkthrough.*

---

## Run it locally

```bash
git clone <this-repo>
cd insureease
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app_v2.py
```

Rung 4 and the rule-based stub are free and need no API key. To use the real Rung 5 agent, paste your Anthropic API key into the sidebar when the app opens — it stays in your browser session only, never written to disk.

If you prefer a `.env` file for local development:

```bash
cp .env.example .env   # then add your ANTHROPIC_API_KEY
```

**Real Rung 5 runs cost money** — roughly 1-5 cents per claim at Claude Sonnet 5 pricing. The app defaults to the free stub and requires an explicit toggle to use the real agent.

---

## The six scenarios

| ID | Scenario | What it tests |
|---|---|---|
| CLM-100 | Clean claim, active policy, no history | The straightforward happy path |
| CLM-101 | Policy lapsed before the incident date | Date boundary logic |
| CLM-102 | Storm damage, two prior paid claims this year | Claim-frequency signal blocking an automatic advance |
| CLM-103 | Injury reported alongside a routine collision | Escalation trigger firing even when the rest looks routine |
| CLM-104 | Storm damage with a policy exclusion | Exclusion detection and escalation rather than guessing |
| CLM-105 | Theft claim, no matching policy section (search returns a plausible but wrong result) | Whether the agent notices a confident-sounding but irrelevant match |

CLM-105 is the most instructive: the first version of the search tool always returned *something*, and that something was wrong. The fix required changing the retrieval logic, not the agent's behavior.

---

## Tools the agent can use

| Tool | Type | Notes |
|---|---|---|
| `get_policy_status` | READ | Coverage type, active/lapsed status, dates |
| `search_coverage_policy` | READ | Keyword search over the policy document |
| `get_claim_history` | READ | Prior claims, frequency signal |
| `get_weather_event_data` | READ | Confirms declared storm events |
| `get_police_report_status` | READ | Whether a police report was filed |
| `check_deductible` | READ | Remaining deductible for the policy year |
| `issue_claim_advance` | WRITE | Hard-capped at $500 in code, not just in the prompt |
| `escalate_to_adjuster` | EXTERNAL | Always permitted, always terminal |

`approve_full_claim_payout` and `deny_claim` are deliberately out of scope — both require real human sign-off.

---

## What the testing actually showed

Both rungs were run against all six scenarios, with Rung 5 making real, billed API calls. The short version: they agreed on the right answer in most cases, but getting there exposed several real bugs that only showed up by actually running the code rather than reading it.

The most instructive scenario was CLM-105 — a theft claim where the policy search kept returning a collision coverage section instead of anything about theft. On the first live run, the agent made eight tool calls, searched the same thing four different ways, got the same wrong answer back every time, and then returned a completely empty response — no advance issued, no escalation, nothing. That silent dead end was a real bug in the agent loop. On the second run after fixing that bug, the agent didn't stall, but it approved a $500 advance based on the same misleading search result. The actual fix wasn't in the agent's instructions — it was in the search tool itself, which was handing the agent bad data dressed up as a confident answer. Once that was fixed, a third run escalated correctly, and the agent's own reasoning trace explicitly named the empty search result as the reason.

CLM-103 — the injury scenario — was the opposite: the fastest and cheapest run in the entire set, because the escalation instruction said to escalate immediately on any injury mention, and the agent did exactly that without investigating further.

CLM-100, the simplest scenario in the set (clean policy, no history, no complications), turned out to be the least consistent. Across eight real runs, it produced three different outcomes: advance issued, a confirmation request back to the claimant, and escalation. None of those is strictly wrong, but a system that can't settle on a single behavior for its easiest case is worth being honest about. The harder scenarios — CLM-102 through CLM-105 — were more consistent than the easy one, which is counterintuitive and the full findings document explains why.

Total cost across every real-agent run in the entire project: approximately $0.62. The full run-by-run results, root-cause write-ups, and what each fix did and didn't resolve are in [docs/FINDINGS.md](docs/FINDINGS.md).

---

## Run the offline evals (free, no API key)

```bash
python evals/cases.py
```

12/12 pass — all six scenarios across both Rung 4 and the stub.

## Run a single claim from the CLI

```bash
python run_claim.py CLM-100 rung4   # free
python run_claim.py CLM-105 stub    # free
python run_claim.py CLM-100 real    # costs money, asks for confirmation
```

---

## Project structure

```
insureease/
├── app.py                     Original Streamlit UI (env-var key, file-based logging)
├── app_v2.py                  Current UI — BYOK via sidebar, session-state-only logging
├── run_claim.py               CLI for single claims, UTF-8 safe
├── requirements.txt
├── .env.example               Template — copy to .env for local dev
├── .gitignore
├── .streamlit/
│   └── config.toml            Custom dark theme
├── src/
│   ├── models.py              Data model
│   ├── tools.py               The 8 tools, pure Python
│   ├── rung4_workflow.py      Fixed workflow
│   ├── rung5_agent.py         Real ReAct agent (Claude API)
│   ├── rung5_stub.py          Rule-based stand-in for free testing
│   └── instructions.py        Rung 5 system prompt
├── data/
│   └── seed_data.py           Policies, claims, coverage document
├── evals/
│   ├── cases.py               Trajectory evals — Rung 4 + stub, free
│   └── cases_real.py          Real-agent evals — costs money, confirmation-gated
└── docs/
    ├── FINDINGS.md            Full testing narrative, run-by-run results, root-cause write-ups
    ├── WALKTHROUGH.md         Visual walkthrough with real screenshots
    └── screenshots/           Real screenshots used in WALKTHROUGH.md
```

The full findings — every real run, every bug found, every fix verified — are in `docs/FINDINGS.md`.
