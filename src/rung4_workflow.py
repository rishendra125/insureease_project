"""
Rung 4 - Fixed Workflow for the InsureEase Claims Intake Agent.

This is plain Python: the entire decision tree is hardcoded here by the
developer. There is no LLM call anywhere in this file. Every branch,
every condition, every tool-call order is fixed in advance - this is
what makes Rung 4 different from Rung 5, and what makes it fully
testable right now with zero API dependency.

Decision tree, in order:
  1. Look up the policy.
  2. If the policy wasn't active on the incident date -> decline. Stop.
  3. If the claim mentions injury -> escalate immediately. Stop.
     (Checked early and unconditionally - injury claims never proceed
     past this point, regardless of anything else about the claim.)
  4. Check claim history. Two or more paid claims in the last 12 months
     -> escalate for manual review. Stop.
  5. Search coverage policy for the claim type, to surface any
     exclusion that applies (e.g. storm/water exclusion).
  6. If an exclusion clause was surfaced -> escalate for adjuster
     review rather than guess. Stop.
  7. Otherwise, check the deductible and issue a capped advance.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from datetime import datetime
import tools
from tools import MAX_ADVANCE_USD

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
from seed_data import CLAIMS


def _log(trace: list[dict], kind: str, **payload) -> None:
    trace.append({"kind": kind, **payload})


def process_claim_fixed_workflow(claim_id: str) -> dict:
    """Runs the fixed decision tree for a single claim.

    Returns a dict with the trace (list of ACT/OBSERVE/DECISION steps,
    for rendering in the UI later) and the final outcome.
    """
    trace: list[dict] = []

    claim = CLAIMS.get(claim_id)
    if claim is None:
        return {"trace": trace, "outcome": "error", "detail": f"claim {claim_id} not found"}

    # Step 1: policy lookup
    _log(trace, "act", tool="get_policy_status", args={"policy_id": claim.policy_id})
    policy_result = tools.get_policy_status(claim.policy_id)
    _log(trace, "observe", result=policy_result)

    if "error" in policy_result:
        _log(trace, "answer", text=f"Unable to process claim {claim_id}: policy not found.")
        return {"trace": trace, "outcome": "error", "detail": "policy_not_found"}

    # Step 2: was the policy active on the incident date?
    effective = datetime.fromisoformat(policy_result["effective_date"])
    expiry = datetime.fromisoformat(policy_result["expiry_date"])
    is_lapsed = not (effective <= claim.incident_date <= expiry) or policy_result["status"] != "active"

    if is_lapsed:
        lapsed_query = "policy not active lapsed status expiry"
        _log(trace, "act", tool="search_coverage_policy", args={"query": lapsed_query})
        lapsed_policy = tools.search_coverage_policy(lapsed_query)
        _log(trace, "observe", result=lapsed_policy)
        _log(
            trace,
            "answer",
            text=(
                f"Claim {claim_id} cannot be processed: the policy was not active on the "
                f"incident date ({claim.incident_date.date()}). Per policy section "
                f"'{lapsed_policy['section']}', no coverage or advance applies. Claim declined at intake."
            ),
        )
        return {"trace": trace, "outcome": "declined", "reason": "policy_not_active"}

    # Step 3: injury check - unconditional, checked before anything else proceeds
    if claim.mentions_injury:
        _log(trace, "act", tool="escalate_to_adjuster", args={"reason": f"injury reported on claim {claim_id}"})
        escalate_result = tools.escalate_to_adjuster(f"injury reported on claim {claim_id}")
        _log(trace, "observe", result=escalate_result)
        _log(
            trace,
            "answer",
            text=(
                f"Claim {claim_id} involves a reported injury and has been escalated to a "
                f"licensed adjuster. No coverage determination or advance can be issued by "
                f"automated intake."
            ),
        )
        return {"trace": trace, "outcome": "escalated", "reason": "injury_reported"}

    # Step 4: claim frequency check
    _log(trace, "act", tool="get_claim_history", args={"policy_id": claim.policy_id})
    history_result = tools.get_claim_history(claim.policy_id)
    _log(trace, "observe", result=history_result)

    if history_result["paid_claim_count"] >= 2:
        _log(trace, "act", tool="escalate_to_adjuster", args={"reason": f"claim frequency flag on policy {claim.policy_id}"})
        escalate_result = tools.escalate_to_adjuster(f"claim frequency flag on policy {claim.policy_id}")
        _log(trace, "observe", result=escalate_result)
        _log(
            trace,
            "answer",
            text=(
                f"Claim {claim_id} is on a policy with {history_result['paid_claim_count']} prior "
                f"paid claims in the review period. Per policy, this requires manual adjuster "
                f"review before any advance. Escalated."
            ),
        )
        return {"trace": trace, "outcome": "escalated", "reason": "claim_frequency"}

    # Step 5: coverage/exclusion search for this claim type
    query = f"{claim.claim_type} coverage {claim.description}"
    _log(trace, "act", tool="search_coverage_policy", args={"query": query})
    coverage_result = tools.search_coverage_policy(query)
    _log(trace, "observe", result=coverage_result)

    # Step 6a: no matching policy section found at all - this must not
    # silently fall through to an advance. A missing/weak search result
    # is exactly the "uncertain, don't guess" case, the same principle
    # instructions.py states for Rung 5. Previously, a None section
    # simply failed the exclusion_sections check below and proceeded to
    # issue an advance anyway - this was the CLM-105 finding.
    if coverage_result["section"] is None:
        _log(trace, "act", tool="escalate_to_adjuster", args={"reason": f"no matching coverage section found for claim {claim_id}"})
        escalate_result = tools.escalate_to_adjuster(f"no matching coverage section found for claim {claim_id}")
        _log(trace, "observe", result=escalate_result)
        _log(
            trace,
            "answer",
            text=(
                f"Claim {claim_id}: no policy section clearly matches this claim type "
                f"('{claim.claim_type}'). Escalated to adjuster rather than guessing "
                f"at coverage - see the CLM-105 finding in README.md."
            ),
        )
        return {"trace": trace, "outcome": "escalated", "reason": "no_matching_coverage"}

    # Step 6b: exclusion check - fixed workflow can only detect this by a
    # keyword match on the section name, since it has no real reasoning
    # about whether the exclusion actually applies to this specific claim.
    exclusion_sections = {"storm_and_water_exclusion"}
    if coverage_result["section"] in exclusion_sections:
        _log(trace, "act", tool="escalate_to_adjuster", args={"reason": f"possible exclusion on claim {claim_id}"})
        escalate_result = tools.escalate_to_adjuster(f"possible exclusion on claim {claim_id}")
        _log(trace, "observe", result=escalate_result)
        _log(
            trace,
            "answer",
            text=(
                f"Claim {claim_id} may fall under an exclusion clause ('{coverage_result['section']}'). "
                f"Escalated to adjuster rather than issuing an advance, since the fixed workflow "
                f"cannot determine whether the exclusion actually applies to this specific loss."
            ),
        )
        return {"trace": trace, "outcome": "escalated", "reason": "possible_exclusion"}

    # Step 7: deductible check and advance
    _log(trace, "act", tool="check_deductible", args={"policy_id": claim.policy_id})
    deductible_result = tools.check_deductible(claim.policy_id)
    _log(trace, "observe", result=deductible_result)

    advance_amount = min(MAX_ADVANCE_USD, deductible_result["deductible_remaining_usd"])
    if advance_amount <= 0:
        _log(
            trace,
            "answer",
            text=f"Claim {claim_id}: deductible has been fully used for this policy year. No advance available.",
        )
        return {"trace": trace, "outcome": "declined", "reason": "deductible_exhausted"}

    _log(trace, "act", tool="issue_claim_advance", args={"claim_id": claim_id, "amount_usd": advance_amount})
    advance_result = tools.issue_claim_advance(claim_id, advance_amount)
    _log(trace, "observe", result=advance_result)
    _log(
        trace,
        "answer",
        text=(
            f"Claim {claim_id} approved. An emergency advance of ${advance_amount:.2f} has been "
            f"issued pending full claim review."
        ),
    )
    return {"trace": trace, "outcome": "advance_issued", "amount_usd": advance_amount}
