"""
Trajectory evals for InsureEase.

The distinction that matters here: an OUTPUT eval checks whether the
final answer sounds right. A TRAJECTORY eval checks whether the agent
actually did the right thing - which tools it called, in what order,
with what arguments. A workflow can retrieve the wrong policy section
and still phrase a confident, plausible-sounding wrong answer; only a
trajectory eval catches that. (This is exactly the class of bug we
found and fixed in tools.py during manual testing - these assertions
exist so that class of bug gets caught automatically next time.)

Every case here runs against Rung 4 (the real fixed workflow) and,
separately, against the Rung 5 stub - clearly labeled, since the stub
is rule-based and passing it proves nothing about real agent behavior.
It's still useful to run: it exercises the eval harness itself so bugs
in the ASSERTIONS get caught before any real API cost is on the line.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rung4_workflow import process_claim_fixed_workflow
from rung5_stub import process_claim_stub_agent


@dataclass
class EvalCase:
    id: str
    claim_id: str
    description: str
    expect_outcome: str
    expect_tool_sequence: list[str]
    expect_args_contain: dict[str, dict] = field(default_factory=dict)
    # e.g. {"issue_claim_advance": {"amount_usd": 500.0}}
    # Only set this when a rung's real trajectory legitimately differs
    # from expect_tool_sequence (e.g. one implementation cites the
    # policy section before declining, another doesn't). Leave unset
    # when both rungs are expected to follow the same path.
    rung5_expect_tool_sequence: list[str] | None = None


CASES: list[EvalCase] = [
    EvalCase(
        id="E01",
        claim_id="CLM-100",
        description="Clean claim, active policy, no history -> advance issued at full cap",
        expect_outcome="advance_issued",
        expect_tool_sequence=[
            "get_policy_status",
            "get_claim_history",
            "search_coverage_policy",
            "check_deductible",
            "issue_claim_advance",
        ],
        expect_args_contain={"issue_claim_advance": {"amount_usd": 500.0}},
    ),
    EvalCase(
        id="E02",
        claim_id="CLM-101",
        description="Lapsed policy at incident date -> declined before any advance logic runs",
        expect_outcome="declined",
        expect_tool_sequence=[
            "get_policy_status",
            "search_coverage_policy",
        ],
        # the stub declines immediately without citing a policy section -
        # a legitimately shorter, still-correct trajectory to the same outcome
        rung5_expect_tool_sequence=["get_policy_status"],
    ),
    EvalCase(
        id="E03",
        claim_id="CLM-102",
        description="Two prior paid claims -> escalated on frequency, never reaches coverage search",
        expect_outcome="escalated",
        expect_tool_sequence=[
            "get_policy_status",
            "get_claim_history",
            "escalate_to_adjuster",
        ],
        expect_args_contain={"escalate_to_adjuster": {"reason": "claim frequency flag on policy POL-1003"}},
    ),
    EvalCase(
        id="E04",
        claim_id="CLM-103",
        description="Injury mentioned -> escalates immediately, never reaches history or coverage checks",
        expect_outcome="escalated",
        expect_tool_sequence=[
            "get_policy_status",
            "escalate_to_adjuster",
        ],
        expect_args_contain={"escalate_to_adjuster": {"reason": "injury reported on claim CLM-103"}},
    ),
    EvalCase(
        id="E05",
        claim_id="CLM-104",
        description="Storm/water exclusion, no competing frequency flag -> escalated on exclusion match",
        expect_outcome="escalated",
        expect_tool_sequence=[
            "get_policy_status",
            "get_claim_history",
            "search_coverage_policy",
            "escalate_to_adjuster",
        ],
        expect_args_contain={"search_coverage_policy": {}},  # presence check only; see runner
    ),
    EvalCase(
        id="E06",
        claim_id="CLM-105",
        description="Theft claim, no genuinely matching policy section -> escalated on no-match rather than guessing (the fixed CLM-105 finding)",
        expect_outcome="escalated",
        expect_tool_sequence=[
            "get_policy_status",
            "get_claim_history",
            "search_coverage_policy",
            "escalate_to_adjuster",
        ],
        expect_args_contain={"escalate_to_adjuster": {"reason": "no matching coverage section found for claim CLM-105"}},
    ),
]


def _tool_sequence(trace: list[dict]) -> list[str]:
    return [step["tool"] for step in trace if step["kind"] == "act"]


def _args_for_tool(trace: list[dict], tool_name: str) -> dict | None:
    for step in trace:
        if step["kind"] == "act" and step["tool"] == tool_name:
            return step["args"]
    return None


def run_case(case: EvalCase, process_fn, label: str, expected_sequence: list[str]) -> tuple[bool, list[str]]:
    """Runs one case against a given rung function. Returns (passed, failure_reasons)."""
    result = process_fn(case.claim_id)
    trace = result["trace"]
    failures: list[str] = []

    if result["outcome"] != case.expect_outcome:
        failures.append(f"outcome: expected {case.expect_outcome!r}, got {result['outcome']!r}")

    actual_sequence = _tool_sequence(trace)
    if actual_sequence != expected_sequence:
        failures.append(f"tool sequence: expected {expected_sequence}, got {actual_sequence}")

    for tool_name, expected_args in case.expect_args_contain.items():
        actual_args = _args_for_tool(trace, tool_name)
        if actual_args is None:
            failures.append(f"expected a call to {tool_name!r} but none was made")
            continue
        for key, expected_value in expected_args.items():
            if key not in actual_args:
                failures.append(f"{tool_name}: missing expected arg {key!r}")
            elif actual_args[key] != expected_value:
                failures.append(
                    f"{tool_name}: arg {key!r} expected {expected_value!r}, got {actual_args[key]!r}"
                )

    return (len(failures) == 0, failures)


def run_all(verbose: bool = True) -> dict:
    """Runs every case against both Rung 4 and the Rung 5 stub."""
    summary = {"rung4": {"pass": 0, "fail": 0}, "rung5_stub": {"pass": 0, "fail": 0}}

    for case in CASES:
        for label, fn, key in [
            ("Rung 4", process_claim_fixed_workflow, "rung4"),
            ("Rung 5 stub", process_claim_stub_agent, "rung5_stub"),
        ]:
            expected_sequence = (
                case.rung5_expect_tool_sequence
                if key == "rung5_stub" and case.rung5_expect_tool_sequence is not None
                else case.expect_tool_sequence
            )
            passed, failures = run_case(case, fn, label, expected_sequence)
            summary[key]["pass" if passed else "fail"] += 1
            status = "PASS" if passed else "FAIL"
            if verbose:
                print(f"[{status}] {case.id} ({label}) - {case.description}")
                if not passed:
                    for f in failures:
                        print(f"         - {f}")

    if verbose:
        print()
        for key, label in [("rung4", "Rung 4"), ("rung5_stub", "Rung 5 stub")]:
            p, f = summary[key]["pass"], summary[key]["fail"]
            print(f"{label}: {p} passed, {f} failed, {p + f} total")

    return summary


if __name__ == "__main__":
    results = run_all(verbose=True)
    total_fail = results["rung4"]["fail"] + results["rung5_stub"]["fail"]
    sys.exit(1 if total_fail > 0 else 0)
