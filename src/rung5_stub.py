"""
Rung 5 STUB - a rule-based stand-in for the real ReAct agent.

This is NOT an LLM. It does not reason. It is a deliberately simple
keyword-matching function that picks tools in a THINK/ACT/OBSERVE shape
so that:
  1. The Streamlit UI and trace-rendering code can be built and tested
     now, against realistic-looking data, with zero API dependency.
  2. The trajectory-eval harness (checking "did it call the right
     tools in the right order") can be exercised end-to-end locally,
     catching bugs in the eval logic itself before any real API cost
     is on the line.

When the real API stage begins, this file gets swapped for an actual
Claude-powered agent loop - the Streamlit UI and eval harness should
not need to change, only which function they call.

Because this is rule-based, it will NOT show the kind of judgment
failures a real LLM might show (e.g. guessing on empty search results).
Do not mistake a clean run here for evidence that Rung 5 "works" -
it only proves the plumbing works.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))

import tools
from seed_data import CLAIMS

STUB_LABEL = "Rung 5 stub (rule-based, NOT an LLM)"


def _log(trace: list[dict], kind: str, **payload) -> None:
    trace.append({"kind": kind, **payload})


def process_claim_stub_agent(claim_id: str) -> dict:
    """A rule-based approximation of what a ReAct agent MIGHT do.

    Investigates more broadly than the fixed workflow (calls more
    tools, in a data-driven order) but still has no real reasoning -
    every branch here is still an if/else written by us, just shaped
    to resemble an agent's investigation pattern for UI-testing
    purposes.
    """
    trace: list[dict] = []

    claim = CLAIMS.get(claim_id)
    if claim is None:
        return {"trace": trace, "outcome": "error", "detail": f"claim {claim_id} not found", "stub": True}

    _log(trace, "think", text=f"I should start by checking the status of order {claim_id}'s policy.")
    _log(trace, "act", tool="get_policy_status", args={"policy_id": claim.policy_id})
    policy_result = tools.get_policy_status(claim.policy_id)
    _log(trace, "observe", result=policy_result)

    if "error" in policy_result:
        _log(trace, "answer", text=f"I couldn't find a policy for claim {claim_id}.")
        return {"trace": trace, "outcome": "error", "detail": "policy_not_found", "stub": True}

    # injury keyword check - a real agent would infer this from the
    # claimant's free-text description; this stub just checks the flag
    if claim.mentions_injury:
        _log(trace, "think", text="The claim description mentions an injury. This must be escalated immediately.")
        _log(trace, "act", tool="escalate_to_adjuster", args={"reason": f"injury reported on claim {claim_id}"})
        result = tools.escalate_to_adjuster(f"injury reported on claim {claim_id}")
        _log(trace, "observe", result=result)
        _log(trace, "answer", text=f"I've escalated claim {claim_id} to a human adjuster due to a reported injury.")
        return {"trace": trace, "outcome": "escalated", "reason": "injury_reported", "stub": True}

    _log(trace, "think", text="Next I'll check whether the policy was active on the incident date.")
    from datetime import datetime
    effective = datetime.fromisoformat(policy_result["effective_date"])
    expiry = datetime.fromisoformat(policy_result["expiry_date"])
    is_lapsed = not (effective <= claim.incident_date <= expiry) or policy_result["status"] != "active"

    if is_lapsed:
        _log(trace, "think", text="The policy was not active on the incident date, so this claim cannot proceed.")
        _log(trace, "answer", text=f"Claim {claim_id}: the policy was not active on the incident date, so no advance can be issued.")
        return {"trace": trace, "outcome": "declined", "reason": "policy_not_active", "stub": True}

    _log(trace, "think", text="I'll check the claim history for this policy to see if there's a frequency concern.")
    _log(trace, "act", tool="get_claim_history", args={"policy_id": claim.policy_id})
    history_result = tools.get_claim_history(claim.policy_id)
    _log(trace, "observe", result=history_result)

    if history_result["paid_claim_count"] >= 2:
        _log(trace, "think", text="Two or more prior paid claims - this needs manual review before I proceed.")
        _log(trace, "act", tool="escalate_to_adjuster", args={"reason": f"claim frequency flag on policy {claim.policy_id}"})
        result = tools.escalate_to_adjuster(f"claim frequency flag on policy {claim.policy_id}")
        _log(trace, "observe", result=result)
        _log(trace, "answer", text=f"Claim {claim_id} is on a policy with multiple recent paid claims, so I've escalated it for manual review.")
        return {"trace": trace, "outcome": "escalated", "reason": "claim_frequency", "stub": True}

    _log(trace, "think", text="Now let me check the coverage policy for anything relevant to this claim type.")
    query = f"{claim.claim_type} {claim.description}"
    _log(trace, "act", tool="search_coverage_policy", args={"query": query})
    coverage_result = tools.search_coverage_policy(query)
    _log(trace, "observe", result=coverage_result)

    if coverage_result["section"] is None:
        _log(trace, "think", text="No policy section clearly matches this claim type - I should escalate rather than guess.")
        _log(trace, "act", tool="escalate_to_adjuster", args={"reason": f"no matching coverage section found for claim {claim_id}"})
        result = tools.escalate_to_adjuster(f"no matching coverage section found for claim {claim_id}")
        _log(trace, "observe", result=result)
        _log(trace, "answer", text=f"Claim {claim_id}: no policy section clearly matches this claim type, so I've escalated it rather than guessing.")
        return {"trace": trace, "outcome": "escalated", "reason": "no_matching_coverage", "stub": True}

    if coverage_result["section"] == "storm_and_water_exclusion":
        _log(trace, "think", text="This may fall under the storm/water exclusion clause - I should escalate rather than guess.")
        _log(trace, "act", tool="escalate_to_adjuster", args={"reason": f"possible exclusion on claim {claim_id}"})
        result = tools.escalate_to_adjuster(f"possible exclusion on claim {claim_id}")
        _log(trace, "observe", result=result)
        _log(trace, "answer", text=f"Claim {claim_id} may be affected by a policy exclusion, so I've escalated it rather than issuing an advance.")
        return {"trace": trace, "outcome": "escalated", "reason": "possible_exclusion", "stub": True}

    _log(trace, "think", text="No blocking issues found. Let me check the remaining deductible before issuing an advance.")
    _log(trace, "act", tool="check_deductible", args={"policy_id": claim.policy_id})
    deductible_result = tools.check_deductible(claim.policy_id)
    _log(trace, "observe", result=deductible_result)

    advance_amount = min(tools.MAX_ADVANCE_USD, deductible_result["deductible_remaining_usd"])
    if advance_amount <= 0:
        _log(trace, "answer", text=f"Claim {claim_id}: the deductible has been fully used, so no advance is available.")
        return {"trace": trace, "outcome": "declined", "reason": "deductible_exhausted", "stub": True}

    _log(trace, "act", tool="issue_claim_advance", args={"claim_id": claim_id, "amount_usd": advance_amount})
    advance_result = tools.issue_claim_advance(claim_id, advance_amount)
    _log(trace, "observe", result=advance_result)
    _log(trace, "answer", text=f"I've issued an emergency advance of ${advance_amount:.2f} for claim {claim_id}, pending full review.")
    return {"trace": trace, "outcome": "advance_issued", "amount_usd": advance_amount, "stub": True}
