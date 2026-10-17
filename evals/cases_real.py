"""
Real-agent evals for InsureEase.

This is deliberately NOT structured like evals/cases.py. Rung 4 and the
stub are pure Python - exact tool-sequence assertions make sense because
the same input always produces the same output. The real agent does not
work that way: today's testing showed CLM-100 producing two different
outcomes across three runs, and CLM-105 producing three different
outcomes across its three runs (one of them a real bug, now fixed).
Asserting one exact expected sequence against a system we've already
proven is non-deterministic would just generate false failures on
legitimate variation.

Instead, each case here defines:
  - a set of ACCEPTABLE outcomes (not always exactly one), calibrated
    against what's actually been observed in real runs today, plus
    whether that acceptable-set is "reliable" (tight, likely to hold)
    or "informational" (known to vary, logged but not hard-failed)
  - INVARIANTS: properties that must hold regardless of which valid
    path the agent takes - e.g. "an advance is never issued above the
    $500 cap", "an escalated outcome always has a real escalate call
    behind it", "the injury trigger fires before any other tool call"

COST WARNING: every case here makes a real, billed Claude API call.
Running the full suite costs roughly 15-20 cents at current pricing.
This file refuses to run without explicit confirmation - see main()
at the bottom. Nothing here runs automatically or as a side effect of
importing this module.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rung5_agent import process_claim_react_agent


@dataclass
class RealEvalCase:
    id: str
    claim_id: str
    description: str
    acceptable_outcomes: set[str]
    reliable: bool  # True = deviation is a real finding worth flagging clearly.
    # False = known non-deterministic from today's testing, logged as
    # informational only, never causes a hard failure on its own.
    notes: str = ""


CASES: list[RealEvalCase] = [
    RealEvalCase(
        id="RE01",
        claim_id="CLM-100",
        description="Clean claim, active policy - expected straightforward approval",
        acceptable_outcomes={"advance_issued", "answered_no_action"},
        reliable=False,
        notes=(
            "Observed 3 real outcomes today: advance_issued, advance_issued, "
            "answered_no_action (asked the claimant to confirm the amount "
            "instead of approving outright). Both are reasonable agent "
            "behavior - neither is a bug - so this is informational, not "
            "a hard pass/fail on outcome alone."
        ),
    ),
    RealEvalCase(
        id="RE02",
        claim_id="CLM-101",
        description="Lapsed policy - expected refusal, either declined or escalated",
        acceptable_outcomes={"declined", "escalated"},
        reliable=False,
        notes="Only 1 real run so far (escalated). Declined would also be correct - Rung 4 declines directly.",
    ),
    RealEvalCase(
        id="RE03",
        claim_id="CLM-102",
        description="Two prior paid claims - claim-frequency rule should force escalation",
        acceptable_outcomes={"escalated"},
        reliable=True,
        notes="Only 1 real run so far, but the underlying instruction is unambiguous - deviation is worth investigating.",
    ),
    RealEvalCase(
        id="RE04",
        claim_id="CLM-103",
        description="Injury reported - escalation trigger, the most consistently reliable real-agent behavior observed",
        acceptable_outcomes={"escalated"},
        reliable=True,
        notes="3/3 real runs escalated, and 3/3 escalated as the very first tool call - see the first-call invariant below.",
    ),
    RealEvalCase(
        id="RE05",
        claim_id="CLM-104",
        description="Storm/water exclusion - should escalate rather than guess",
        acceptable_outcomes={"escalated"},
        reliable=True,
        notes="Only 1 real run so far (escalated).",
    ),
    RealEvalCase(
        id="RE06",
        claim_id="CLM-105",
        description="The fixed retrieval-trust bug - this IS the scenario the whole MIN_MATCH_SCORE fix targets",
        acceptable_outcomes={"escalated"},
        reliable=True,
        notes=(
            "Only 1 real run against the current fixed code (escalated, correctly). "
            "Two earlier runs against pre-fix code failed differently (empty "
            "stall, then wrong approval) - see README.md. A failure here now "
            "would be the most important possible finding in this whole "
            "project, since it's the exact case the fix was built for."
        ),
    ),
]


def _tool_sequence(trace: list[dict]) -> list[str]:
    return [step["tool"] for step in trace if step["kind"] == "act"]


def _check_invariants(case: RealEvalCase, result: dict) -> list[str]:
    """Checks properties that must hold regardless of which acceptable
    outcome the agent reached. Returns a list of violation descriptions
    (empty list = all invariants held).
    """
    violations: list[str] = []
    trace = result["trace"]
    sequence = _tool_sequence(trace)
    outcome = result.get("outcome")

    # INVARIANT: the agent must always reach a real terminal state - never
    # a raw error and never (post-fix) a silent empty answer.
    if outcome in (None, "", "error"):
        violations.append(f"non-terminal or error outcome: {outcome!r}")

    # INVARIANT: if the outcome claims an advance was issued, an actual
    # issue_claim_advance call with a successful result must exist in the
    # trace - the label should never be able to drift from what actually
    # happened.
    if outcome == "advance_issued":
        if "issue_claim_advance" not in sequence:
            violations.append("outcome is advance_issued but no issue_claim_advance call exists in trace")
        else:
            amount = result.get("amount_usd")
            if amount is not None and amount > 500.0:
                violations.append(f"advance amount {amount} exceeds the $500 hard cap")

    # INVARIANT: if the outcome claims escalation, an actual
    # escalate_to_adjuster call must exist.
    if outcome == "escalated" and "escalate_to_adjuster" not in sequence:
        violations.append("outcome is escalated but no escalate_to_adjuster call exists in trace")

    # INVARIANT specific to the injury-trigger case: escalate_to_adjuster
    # must be the very first tool call, matching instructions.py's
    # "escalate immediately, before taking any other action" rule, and
    # matching what's actually been observed in all 3 real runs so far.
    if case.claim_id == "CLM-103" and sequence:
        if sequence[0] != "escalate_to_adjuster":
            violations.append(
                f"expected escalate_to_adjuster as the first call for the injury trigger, "
                f"got {sequence[0]!r} first (full sequence: {sequence})"
            )

    return violations


def run_case(case: RealEvalCase) -> dict:
    """Runs one case against the REAL agent. Makes one billed API call."""
    result = process_claim_react_agent(case.claim_id)
    outcome_ok = result.get("outcome") in case.acceptable_outcomes
    violations = _check_invariants(case, result)

    return {
        "case": case,
        "result": result,
        "outcome_ok": outcome_ok,
        "invariant_violations": violations,
        "hard_fail": case.reliable and (not outcome_ok or violations),
        "soft_flag": (not case.reliable) and (not outcome_ok or violations),
    }


def run_all(verbose: bool = True, log_traces: bool = True) -> list[dict]:
    """Runs every case against the real agent. Costs real money - see main().

    Every call's full trace is persisted to eval_real_log.jsonl as it
    completes (not just the summary line) - trace data costs real money
    to produce and should never be thrown away when the process exits.
    """
    results = []
    log_path = Path(__file__).resolve().parent.parent / "eval_real_log.jsonl"

    for case in CASES:
        r = run_case(case)
        results.append(r)

        if log_traces:
            import json as _json
            from datetime import datetime as _dt
            log_entry = {
                "eval_id": case.id,
                "claim_id": case.claim_id,
                "outcome": r["result"].get("outcome"),
                "latency_ms": r["result"].get("latency_ms"),
                "cost_usd": r["result"].get("cost_usd"),
                "hard_fail": r["hard_fail"],
                "soft_flag": r["soft_flag"],
                "invariant_violations": r["invariant_violations"],
                "trace": r["result"].get("trace", []),
                "timestamp": _dt.now().isoformat(),
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(log_entry, default=str) + "\n")

        if verbose:
            outcome = r["result"].get("outcome")
            cost = r["result"].get("cost_usd", 0.0)
            latency = r["result"].get("latency_ms", 0)
            if r["hard_fail"]:
                status = "FAIL"
            elif r["soft_flag"]:
                status = "FLAG"
            else:
                status = "PASS"
            print(f"[{status}] {case.id} ({case.claim_id}) - {case.description}")
            print(f"         outcome={outcome!r} latency={latency}ms cost=${cost:.4f}")
            if not r["outcome_ok"]:
                print(f"         outcome {outcome!r} not in acceptable set {case.acceptable_outcomes}")
            for v in r["invariant_violations"]:
                print(f"         invariant violation: {v}")
            if status == "FLAG":
                print(f"         (informational only - {case.notes})")
            print()

    if verbose:
        hard_fails = sum(1 for r in results if r["hard_fail"])
        soft_flags = sum(1 for r in results if r["soft_flag"])
        total_cost = sum(r["result"].get("cost_usd", 0.0) for r in results)
        print(f"Summary: {len(results)} cases, {hard_fails} hard failures, "
              f"{soft_flags} informational flags, total cost ${total_cost:.4f}")
        if log_traces:
            print(f"Full traces for every call above are saved in eval_real_log.jsonl "
                  f"(project root) - nothing paid-for is lost when this process exits.")

    return results


def view_trace(eval_id_or_claim_id: str) -> None:
    """Prints the full saved trace for a past eval run, read from
    eval_real_log.jsonl - zero cost, no API call, just reading a file.
    Matches on either the eval ID (e.g. "RE01") or the claim ID
    (e.g. "CLM-100"); if multiple matches exist, shows the most recent.
    """
    log_path = Path(__file__).resolve().parent.parent / "eval_real_log.jsonl"
    if not log_path.exists():
        print("eval_real_log.jsonl not found - no eval runs have been logged yet.")
        return

    import json as _json
    matches = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if entry.get("eval_id") == eval_id_or_claim_id or entry.get("claim_id") == eval_id_or_claim_id:
                matches.append(entry)

    if not matches:
        print(f"No logged runs found matching {eval_id_or_claim_id!r}.")
        return

    entry = matches[-1]  # most recent match
    print(f"=== {entry['eval_id']} ({entry['claim_id']}) - {entry['timestamp']} ===")
    print(f"Outcome: {entry['outcome']} | Latency: {entry['latency_ms']}ms | Cost: ${entry['cost_usd']:.4f}")
    if entry["invariant_violations"]:
        print(f"Violations: {entry['invariant_violations']}")
    print()
    print("--- Trace ---")
    for step in entry.get("trace", []):
        print(step)


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--view":
        view_trace(sys.argv[2])
        return

    print(f"This will make {len(CASES)} real, billed Claude API calls "
          f"(roughly 15-20 cents total at current pricing).")
    confirm = input("Type 'yes' to continue: ")
    if confirm.strip().lower() != "yes":
        print("Cancelled - no API calls made.")
        sys.exit(0)

    results = run_all(verbose=True)
    hard_fails = sum(1 for r in results if r["hard_fail"])
    sys.exit(1 if hard_fails > 0 else 0)


if __name__ == "__main__":
    main()
