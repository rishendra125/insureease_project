"""
Rung 5 - the real ReAct agent for InsureEase, powered by the Claude API.

This replaces rung5_stub.py's rule-based logic with an actual model that
decides, at each step, which tool to call, with what arguments, and when
to stop - using instructions.py as its system prompt and tools.py as its
only way to observe the world or take action.

Requires an ANTHROPIC_API_KEY environment variable. If it isn't set, this
module raises a clear error rather than silently falling back to the stub -
mixing a real agent and a fake one behind the same function name would
make cost/latency numbers meaningless.

Pricing (Claude Sonnet 5, introductory rate through August 31, 2026,
per Anthropic's official pricing page): $2.00 / MTok input, $10.00 / MTok
output. This is a real cost per call - see MAX_STEPS below for the
step-budget guardrail that bounds it.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))

from dotenv import load_dotenv

# loads ANTHROPIC_API_KEY from a local .env file if one exists, without
# overriding a variable that's already set in the real environment.
# .env is gitignored - see .gitignore and .env.example in the project root.
load_dotenv()

import anthropic
import tools
from instructions import SYSTEM_PROMPT
from seed_data import CLAIMS

MODEL = "claude-sonnet-5"
MAX_STEPS = 5  # step-budget guardrail, mirrors the escalate-rather-than-spin principle

# Official pricing as of August 2026 (introductory rate through Aug 31, 2026;
# standard $3/$15 takes effect September 1, 2026 - update this if re-running
# this project after that date). Source: platform.claude.com/docs/en/about-claude/pricing
PRICE_PER_MTOK_INPUT_USD = 2.00
PRICE_PER_MTOK_OUTPUT_USD = 10.00

TOOL_SCHEMAS = [
    {
        "name": "get_policy_status",
        "description": "Look up a policy by ID. Returns coverage type, active/lapsed status, and effective/expiry dates.",
        "input_schema": {
            "type": "object",
            "properties": {"policy_id": {"type": "string"}},
            "required": ["policy_id"],
        },
    },
    {
        "name": "search_coverage_policy",
        "description": "Search the coverage policy document for the section relevant to a query. Returns the best-matching section name and text, or an empty result if nothing matches.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_claim_history",
        "description": "Get prior claims filed on a policy, including how many were paid. Used to check claim-frequency concerns.",
        "input_schema": {
            "type": "object",
            "properties": {"policy_id": {"type": "string"}},
            "required": ["policy_id"],
        },
    },
    {
        "name": "get_weather_event_data",
        "description": "Check whether a declared storm/catastrophe weather event occurred at a location on a given date (YYYY-MM-DD).",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "date": {"type": "string"},
            },
            "required": ["location", "date"],
        },
    },
    {
        "name": "get_police_report_status",
        "description": "Check whether a police report was filed for a claim, and its reference number if so.",
        "input_schema": {
            "type": "object",
            "properties": {"claim_id": {"type": "string"}},
            "required": ["claim_id"],
        },
    },
    {
        "name": "check_deductible",
        "description": "Get the remaining deductible for a policy's current year.",
        "input_schema": {
            "type": "object",
            "properties": {"policy_id": {"type": "string"}},
            "required": ["policy_id"],
        },
    },
    {
        "name": "issue_claim_advance",
        "description": "Issue an emergency advance payment for a claim. Hard-capped at $500 in code - requests above the cap are rejected with an error, they are not silently clamped.",
        "input_schema": {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "amount_usd": {"type": "number"},
            },
            "required": ["claim_id", "amount_usd"],
        },
    },
    {
        "name": "escalate_to_adjuster",
        "description": "Escalate a claim to a human adjuster. Always permitted, always terminal - no further automated action happens on this claim after escalation.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]

TOOL_FUNCTIONS = {
    "get_policy_status": tools.get_policy_status,
    "search_coverage_policy": tools.search_coverage_policy,
    "get_claim_history": tools.get_claim_history,
    "get_weather_event_data": tools.get_weather_event_data,
    "get_police_report_status": tools.get_police_report_status,
    "check_deductible": tools.check_deductible,
    "issue_claim_advance": tools.issue_claim_advance,
    "escalate_to_adjuster": tools.escalate_to_adjuster,
}


def _get_client(api_key: str | None = None) -> anthropic.Anthropic:
    # BYOK: accept a key passed in from the UI (session state), falling back
    # to the environment variable for local runs with a .env file.
    resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not resolved_key:
        raise RuntimeError(
            "No API key available. Provide your Anthropic API key via the "
            "sidebar in the app, or set ANTHROPIC_API_KEY in your .env file."
        )
    return anthropic.Anthropic(api_key=resolved_key)


def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000 * PRICE_PER_MTOK_INPUT_USD
        + output_tokens / 1_000_000 * PRICE_PER_MTOK_OUTPUT_USD
    )


def process_claim_react_agent(claim_id: str, client: anthropic.Anthropic | None = None, api_key: str | None = None) -> dict:
    """Runs the real ReAct loop for a single claim, calling the Claude API.

    Returns the same trace/outcome shape as rung4_workflow and rung5_stub,
    plus real latency_ms, tokens, and cost_usd - none of which the stub
    could ever meaningfully report.
    """
    if client is None:
        client = _get_client(api_key=api_key)

    claim = CLAIMS.get(claim_id)
    if claim is None:
        return {"trace": [], "outcome": "error", "detail": f"claim {claim_id} not found"}

    start_time = time.monotonic()
    trace: list[dict] = []
    total_input_tokens = 0
    total_output_tokens = 0

    user_message = (
        f"A new claim has come in. Claim ID: {claim.claim_id}. "
        f"Policy ID: {claim.policy_id}. Claim type: {claim.claim_type}. "
        f"Incident date: {claim.incident_date.isoformat()}. "
        f"Customer's description: \"{claim.description}\". "
        f"Loss location: {claim.loss_location}. "
        f"Investigate as needed using your tools, then either issue an "
        f"appropriate advance, decline the claim, or escalate to a human "
        f"adjuster, per your instructions."
    )
    messages: list[dict] = [{"role": "user", "content": user_message}]

    final_outcome = "incomplete"
    final_reason = None
    final_amount = None

    for step_num in range(MAX_STEPS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1536,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        text_blocks = [b.text for b in response.content if b.type == "text"]
        if text_blocks:
            trace.append({"kind": "think", "text": " ".join(text_blocks)})

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            # model returned a final answer with no further tool calls.
            # Only treat this as "no action taken" if a prior tool call in
            # this same run hasn't already set a terminal outcome - the
            # model's closing text after issuing an advance or escalating
            # is normal and should not overwrite that outcome.
            final_text = " ".join(text_blocks) if text_blocks else ""
            trace.append({"kind": "answer", "text": final_text, "stop_reason": response.stop_reason})

            if final_outcome in ("advance_issued", "escalated"):
                break

            if final_text.strip():
                # a real, non-empty answer with no tool call - the model
                # is explicitly declining without issuing an advance
                final_outcome = "answered_no_action"
                break

            # SAFETY NET: an empty or truncated final answer must never be
            # the terminal state. This can happen if max_tokens cuts the
            # response off mid-generation. Rather than silently dropping
            # the claim with no advance and no escalation, force an
            # escalation here - the same guardrail principle as the
            # step-budget fallback below, just triggered by a different
            # failure mode (empty response instead of exhausted budget).
            forced = tools.escalate_to_adjuster(
                f"agent returned an empty/truncated response (stop_reason={response.stop_reason}) on claim {claim_id}"
            )
            trace.append({
                "kind": "act",
                "tool": "escalate_to_adjuster",
                "args": {"reason": f"empty agent response on claim {claim_id}"},
            })
            trace.append({"kind": "observe", "result": forced})
            trace.append({
                "kind": "answer",
                "text": "I wasn't able to reach a clear conclusion, so I've escalated this to a human specialist.",
            })
            final_outcome = "escalated"
            final_reason = "empty_agent_response"
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []

        for block in tool_use_blocks:
            tool_name = block.name
            tool_args = block.input
            trace.append({"kind": "act", "tool": tool_name, "args": tool_args})

            fn = TOOL_FUNCTIONS.get(tool_name)
            if fn is None:
                result = {"error": f"unknown tool {tool_name}"}
            else:
                result = fn(**tool_args)
            trace.append({"kind": "observe", "result": result})

            if tool_name == "issue_claim_advance" and result.get("advance_issued"):
                final_outcome = "advance_issued"
                final_amount = result.get("amount_usd")
            elif tool_name == "escalate_to_adjuster" and result.get("escalated"):
                final_outcome = "escalated"
                final_reason = result.get("reason")

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})
        # loop continues naturally - the next iteration's messages.create
        # call will return the model's final text once it stops calling
        # tools, so no separate "closing" call is needed here
    else:
        # step budget exhausted without a terminal action - force-escalate,
        # the same guardrail principle used elsewhere in this project
        forced = tools.escalate_to_adjuster(f"step budget exceeded on claim {claim_id}")
        trace.append({"kind": "act", "tool": "escalate_to_adjuster", "args": {"reason": f"step budget exceeded on claim {claim_id}"}})
        trace.append({"kind": "observe", "result": forced})
        trace.append({"kind": "answer", "text": "I wasn't able to resolve this within my step budget, so I've escalated it to a human specialist."})
        final_outcome = "escalated"
        final_reason = "step_budget_exceeded"

    elapsed_ms = round((time.monotonic() - start_time) * 1000)
    cost_usd = _estimate_cost_usd(total_input_tokens, total_output_tokens)

    result = {
        "trace": trace,
        "outcome": final_outcome,
        "reason": final_reason,
        "latency_ms": elapsed_ms,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "cost_usd": round(cost_usd, 6),
        "cost_per_10k_usd": round(cost_usd * 10_000, 2),
    }
    if final_amount is not None:
        result["amount_usd"] = final_amount
    return result
