"""
InsureEase Claims Intake Agent - Streamlit UI.

Rung 4 (fixed workflow) is fully real: plain Python, no LLM, tested.
Rung 5 can run as either a RULE-BASED STUB (free, not an LLM, always
available) or the REAL Claude agent (real cost, requires ANTHROPIC_API_KEY).
Both are clearly labeled everywhere in this UI - a person using this app
should never be able to mistake stub output for real agent behavior, or
trigger a real API call without an explicit, visible choice to do so.
"""

import html
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "data"))

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import plotly.graph_objects as go

from rung4_workflow import process_claim_fixed_workflow
from rung5_stub import process_claim_stub_agent, STUB_LABEL
from seed_data import CLAIMS

try:
    from rung5_agent import process_claim_react_agent
    RUNG5_AGENT_AVAILABLE = True
except ImportError:
    RUNG5_AGENT_AVAILABLE = False

RUNG5_KEY_PRESENT = bool(os.environ.get("ANTHROPIC_API_KEY"))

st.set_page_config(page_title="InsureEase Claims Intake Agent", page_icon="🛡️", layout="wide")

# ---------------------------------------------------------------- styling

st.markdown(
    """
    <style>
    .badge {
        display: inline-block;
        padding: 3px 12px;
        border-radius: 999px;
        font-size: 0.82rem;
        font-weight: 600;
        letter-spacing: 0.02em;
    }
    .badge-green  { background: #14532D; color: #86EFAC; }
    .badge-blue   { background: #1E3A8A; color: #93C5FD; }
    .badge-red    { background: #7F1D1D; color: #FCA5A5; }
    .badge-amber  { background: #78350F; color: #FCD34D; }
    .badge-gray   { background: #374151; color: #D1D5DB; }

    /* trace steps - one consistent box system for THINK/ACT/OBSERVE/ANSWER,
       replacing the earlier mix of st.code (which scrolls horizontally
       and clips long dict values) and unboxed italic text for THINK. */
    .trace-box {
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
        font-size: 0.83rem;
        padding: 10px 14px;
        border-radius: 8px;
        margin-bottom: 8px;
        white-space: pre-wrap;
        word-break: break-word;
        line-height: 1.5;
    }
    .trace-think   { background: #1E1B4B; color: #C7D2FE; font-style: italic; border-left: 3px solid #6366F1; }
    .trace-act     { background: #1E293B; color: #7DD3FC; border-left: 3px solid #0EA5E9; }
    .trace-observe { background: #1E293B; color: #A3E635; border-left: 3px solid #65A30D; }
    .trace-answer  { background: #14532D; color: #BBF7D0; border-left: 3px solid #22C55E; font-family: inherit; font-style: normal; white-space: normal; }

    /* comparison banners - styled to match the badge palette instead of
       Streamlit's default st.success/st.warning colors, which clashed
       with the custom dark theme */
    .compare-banner {
        padding: 14px 18px;
        border-radius: 8px;
        font-size: 0.95rem;
        margin-bottom: 12px;
    }
    .compare-agree    { background: #14532D; color: #BBF7D0; border-left: 4px solid #22C55E; }
    .compare-disagree { background: #451A03; color: #FCD34D; border-left: 4px solid #F59E0B; }

    /* claim detail cards - plain labeled values, not st.metric (which is
       meant for numeric KPIs and looked broken applied to text labels
       like "collision" or a claim ID) */
    .detail-label { font-size: 0.78rem; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 2px; }
    .detail-value { font-size: 1.4rem; font-weight: 600; color: #E2E8F0; margin-bottom: 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

OUTCOME_STYLE = {
    "advance_issued": ("badge-green", "✅ Advance issued"),
    "escalated": ("badge-blue", "🔵 Escalated"),
    "declined": ("badge-red", "🛑 Declined"),
    "error": ("badge-red", "⚠️ Error"),
    "answered_no_action": ("badge-amber", "🟡 No action taken"),
}


def outcome_badge(outcome: str) -> str:
    css_class, label = OUTCOME_STYLE.get(outcome, ("badge-gray", outcome))
    return f'<span class="badge {css_class}">{label}</span>'


SCENARIOS = {
    "CLM-100 — clean claim, active policy": "CLM-100",
    "CLM-101 — lapsed policy (boundary case)": "CLM-101",
    "CLM-102 — multi-factor: storm + claim frequency": "CLM-102",
    "CLM-103 — must escalate: injury reported": "CLM-103",
    "CLM-104 — multi-factor: storm/water exclusion": "CLM-104",
    "CLM-105 — ambiguity test: theft claim, misleading search match": "CLM-105",
}

if "run_history" not in st.session_state:
    st.session_state.run_history = []  # list of dicts, one per completed run

# ---------------------------------------------------------------- header

st.title("🛡️ InsureEase Claims Intake Agent")
st.caption(
    "Compare a fully deterministic fixed workflow (Rung 4) against a real "
    "reasoning agent (Rung 5) on the same insurance claim."
)

# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.subheader("Rung 4 — Fixed Workflow")
    st.markdown('<span class="badge badge-green">✅ Real, tested, free</span>', unsafe_allow_html=True)
    st.caption("Plain Python decision tree. No LLM, no API cost, no randomness.")

    st.divider()

    st.subheader("Rung 5 — ReAct Agent")
    rung5_mode = "stub"
    if RUNG5_AGENT_AVAILABLE and RUNG5_KEY_PRESENT:
        choice = st.radio(
            "Mode",
            ["Rule-based stub (free)", "Real Claude agent (costs money)"],
            index=0,
            label_visibility="collapsed",
        )
        rung5_mode = "real" if choice.startswith("Real") else "stub"
        if rung5_mode == "real":
            st.markdown('<span class="badge badge-amber">💸 Real API - costs money</span>', unsafe_allow_html=True)
            st.caption("~1-5 cents per claim, Claude Sonnet 5. Each run below calls the live API.")
        else:
            st.markdown('<span class="badge badge-gray">🧪 Stub - not an LLM</span>', unsafe_allow_html=True)
            st.caption(f"Backed by `{STUB_LABEL}`.")
    else:
        reason = "`anthropic` not installed" if not RUNG5_AGENT_AVAILABLE else "ANTHROPIC_API_KEY not set"
        st.markdown('<span class="badge badge-gray">🧪 Stub only</span>', unsafe_allow_html=True)
        st.caption(f"Real agent unavailable ({reason}). Using free rule-based stub.")

    st.divider()

    with st.expander("What are Rung 4 and Rung 5?"):
        st.markdown(
            """
| Rung | Who controls the path? |
|---|---|
| 4 — Fixed Workflow | Developer — every branch is hardcoded |
| 5 — ReAct Loop | Model — decides tools and order itself |
"""
        )

    st.divider()

    _spend_placeholder = st.empty()

    def _render_sidebar_spend() -> None:
        """Reads run_log.jsonl fresh and renders the all-time spend summary
        into the placeholder above. Called once on initial page load, and
        again after any real-agent run completes later in the same script
        pass - so the total updates immediately without needing a rerun,
        which would otherwise wipe the just-computed results off screen.
        """
        log_path = Path(__file__).resolve().parent / "run_log.jsonl"
        with _spend_placeholder.container():
            if log_path.exists():
                import json as _json
                entries = []
                with open(log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entries.append(_json.loads(line))
                            except _json.JSONDecodeError:
                                pass
                total_cost = sum(e.get("cost_usd") or 0 for e in entries)
                st.caption(f"💰 **All-time real-agent spend:** ${total_cost:.4f} across {len(entries)} logged run(s)")
                st.caption("Persisted in `run_log.jsonl` - survives restarts, gitignored.")

    _render_sidebar_spend()

    with st.expander("🧪 Dev preview (fake data)"):
        st.caption(
            "Loads obviously-fake demo entries into this session's history "
            "so charts/layout can be previewed with more data. Never writes "
            "to run_log.jsonl, never costs anything, never real."
        )
        if st.button("Load fake preview data", width="stretch"):
            import random as _random
            _fake_claims = ["CLM-100", "CLM-101", "CLM-102", "CLM-103", "CLM-104", "CLM-105"]
            _fake_outcomes = ["advance_issued", "escalated", "declined", "answered_no_action"]
            for _claim in _fake_claims:
                _r4 = _random.choice(["advance_issued", "escalated", "declined"])
                _r5 = _random.choice(_fake_outcomes)
                st.session_state.run_history.append(
                    {
                        "claim_id": f"{_claim} (DEMO)",
                        "rung5_mode": "real",
                        "rung4_outcome": _r4,
                        "rung5_outcome": _r5,
                        "agree": _r4 == _r5,
                        "latency_ms": _random.randint(5000, 25000),
                        "cost_usd": round(_random.uniform(0.01, 0.05), 6),
                    }
                )
            st.rerun()

        st.divider()
        st.caption(
            "Or load your ACTUAL past real-agent runs from run_log.jsonl into "
            "this session's view, for testing layout with genuine data instead "
            "of spending on new API calls. Read-only - never writes anything."
        )
        if st.button("Load real history from run_log.jsonl", width="stretch"):
            import json as _json2
            _real_log_path = Path(__file__).resolve().parent / "run_log.jsonl"
            if _real_log_path.exists():
                with open(_real_log_path, "r", encoding="utf-8") as _f2:
                    for _line2 in _f2:
                        _line2 = _line2.strip()
                        if _line2:
                            try:
                                _entry = _json2.loads(_line2)
                                st.session_state.run_history.append(
                                    {
                                        "claim_id": _entry["claim_id"],
                                        "rung5_mode": _entry["rung5_mode"],
                                        "rung4_outcome": _entry["rung4_outcome"],
                                        "rung5_outcome": _entry["rung5_outcome"],
                                        "agree": _entry["agree"],
                                        "latency_ms": _entry["latency_ms"],
                                        "cost_usd": _entry["cost_usd"],
                                    }
                                )
                            except (_json2.JSONDecodeError, KeyError):
                                pass
                st.rerun()
            else:
                st.error("run_log.jsonl not found yet - no real runs logged.")

    if st.session_state.run_history:
        if st.button("🗑️ Clear session history", width="stretch"):
            st.session_state.run_history = []
            st.rerun()

# ---------------------------------------------------------------- scenario picker

st.header("1 · Pick a claim")
scenario_label = st.selectbox("Scenario", list(SCENARIOS.keys()), label_visibility="collapsed")
claim_id = SCENARIOS[scenario_label]
claim = CLAIMS[claim_id]

if claim_id == "CLM-105":
    st.warning(
        "**Known finding, now fixed:** this scenario previously caused the real agent to "
        "either stall silently or approve an incorrect advance, based on a misleading "
        "policy-search match. A retrieval fix (`MIN_MATCH_SCORE`) resolved this, verified "
        "offline and in one real-agent run. See README.md's Findings section for the full story.",
        icon="🔍",
    )

with st.container(border=True):
    c1, c2, c3 = st.columns(3)
    c1.markdown(f'<div class="detail-label">Claim</div><div class="detail-value">{claim.claim_id}</div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="detail-label">Policy</div><div class="detail-value">{claim.policy_id}</div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="detail-label">Type</div><div class="detail-value">{claim.claim_type}</div>', unsafe_allow_html=True)
    st.markdown(f"**Description:** {claim.description}")
    d1, d2 = st.columns(2)
    d1.caption(f"📍 {claim.loss_location}")
    d2.caption(f"🗓️ Incident: {claim.incident_date}")

st.header("2 · Run")
run_clicked = st.button("▶ Run both rungs", type="primary", width="content")


TOOL_ICONS = {
    "get_policy_status": "📄",
    "search_coverage_policy": "🔎",
    "get_claim_history": "📜",
    "get_weather_event_data": "🌦️",
    "get_police_report_status": "👮",
    "check_deductible": "💳",
    "issue_claim_advance": "💸",
    "escalate_to_adjuster": "🆘",
}


def _humanize_tool_name(name: str) -> str:
    return name.replace("_", " ").title()


def _format_kv_html(data) -> str:
    """Formats a dict as clean 'key: value' lines instead of a raw Python
    repr dump (e.g. {'policy_id': 'POL-1001'}) - the braces/quotes/repr
    formatting is what made trace steps read as debug output rather than
    a normal result, regardless of what color box surrounds them.
    """
    if isinstance(data, dict):
        if not data:
            return '<span style="opacity:0.6">(no data)</span>'
        lines = []
        for k, v in data.items():
            key = html.escape(str(k))
            val = html.escape(str(v))
            lines.append(f'<span style="color:#94A3B8">{key}:</span> {val}')
        return "<br>".join(lines)
    return html.escape(str(data))


def render_trace(trace: list[dict]) -> None:
    for step in trace:
        if step["kind"] == "think":
            text = html.escape(str(step["text"]))
            st.markdown(f'<div class="trace-box trace-think">🧠 {text}</div>', unsafe_allow_html=True)
        elif step["kind"] == "act":
            tool_name = str(step["tool"])
            icon = TOOL_ICONS.get(tool_name, "⚙️")
            label = html.escape(_humanize_tool_name(tool_name))
            args_html = _format_kv_html(step["args"])
            st.markdown(
                f'<div class="trace-box trace-act"><strong>{icon} {label}</strong>'
                f'<div style="font-size:0.85em; opacity:0.85; margin-top:4px;">{args_html}</div></div>',
                unsafe_allow_html=True,
            )
        elif step["kind"] == "observe":
            result_html = _format_kv_html(step["result"])
            st.markdown(
                f'<div class="trace-box trace-observe"><strong>👁️ Result</strong>'
                f'<div style="font-size:0.85em; margin-top:4px;">{result_html}</div></div>',
                unsafe_allow_html=True,
            )
        elif step["kind"] == "answer":
            text = html.escape(str(step["text"]))
            st.markdown(f'<div class="trace-box trace-answer">✅ {text}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- run + results

if run_clicked:
    st.header("3 · Results")
    r4_col, r5_col = st.columns(2)

    with r4_col:
        st.subheader("Rung 4 — Fixed Workflow")
        result4 = process_claim_fixed_workflow(claim_id)
        st.markdown(outcome_badge(result4["outcome"]), unsafe_allow_html=True)
        with st.container(border=True, height=380):
            render_trace(result4["trace"])

    with r5_col:
        if rung5_mode == "real":
            st.subheader("Rung 5 — Real Claude Agent")
            with st.spinner("Calling the Claude API..."):
                try:
                    result5 = process_claim_react_agent(claim_id)
                except Exception as e:
                    st.error(f"Rung 5 API call failed: {e}")
                    result5 = {"trace": [], "outcome": "error"}
            st.markdown(outcome_badge(result5.get("outcome", "error")), unsafe_allow_html=True)
            if "latency_ms" in result5:
                m1, m2 = st.columns(2)
                m1.metric("Latency", f"{result5['latency_ms'] / 1000:.1f} s")
                m2.metric("Cost", f"${result5['cost_usd']:.4f}")
        else:
            st.subheader("Rung 5 — Stub (not an LLM)")
            result5 = process_claim_stub_agent(claim_id)
            st.markdown(outcome_badge(result5["outcome"]), unsafe_allow_html=True)
        with st.container(border=True, height=380):
            render_trace(result5["trace"])

    st.header("4 · Comparison")
    agree = result4["outcome"] == result5["outcome"]
    if agree:
        st.markdown(
            f'<div class="compare-banner compare-agree">✅ Both rungs reached the same outcome: '
            f'<strong>{html.escape(result4["outcome"])}</strong></div>',
            unsafe_allow_html=True,
        )
    else:
        stub_note = (
            "" if rung5_mode == "real"
            else " Since Rung 5 is a rule-based stub, this reflects a difference in two "
                 "hardcoded logic paths, not real agent reasoning."
        )
        st.markdown(
            f'<div class="compare-banner compare-disagree">⚠️ Rungs disagree — Rung 4: '
            f'<strong>{html.escape(result4["outcome"])}</strong>, Rung 5: '
            f'<strong>{html.escape(result5.get("outcome", "error"))}</strong>.{stub_note}</div>',
            unsafe_allow_html=True,
        )

    # record this run for the session history / chart, real-agent runs only
    # carry meaningful cost/latency (Rung 4 is near-instant and free, so it
    # isn't charted - only shown in the outcome-agreement history table)
    run_record = {
        "claim_id": claim_id,
        "rung5_mode": rung5_mode,
        "rung4_outcome": result4["outcome"],
        "rung5_outcome": result5.get("outcome", "error"),
        "agree": agree,
        "latency_ms": result5.get("latency_ms"),
        "cost_usd": result5.get("cost_usd"),
    }
    st.session_state.run_history.append(run_record)

    # PERSISTENT log, separate from session_state - session_state is lost
    # on page refresh or app restart, so real API call results (which cost
    # real money) are also appended to a local file that survives both.
    # Only real-agent runs are logged here, since stub/Rung 4 runs carry
    # no cost and are free to reproduce at will.
    if rung5_mode == "real":
        import json
        from datetime import datetime as _dt
        log_path = Path(__file__).resolve().parent / "run_log.jsonl"
        log_entry = {**run_record, "timestamp": _dt.now().isoformat()}
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
        st.caption(f"📝 Logged to `run_log.jsonl` (permanent record, survives app restarts).")
        _render_sidebar_spend()  # refresh the sidebar total immediately, no rerun needed
else:
    st.caption("Pick a scenario and click **Run both rungs** to see results.")

# ---------------------------------------------------------------- session history

if st.session_state.run_history:
    st.header("Session run history")
    st.caption("Every run made in this browser session, most recent last.")

    rows_html = []
    for i, run in enumerate(st.session_state.run_history, 1):
        mode_tag = "real" if run["rung5_mode"] == "real" else "stub"
        agree_html = (
            '<span style="color:#86EFAC;">✅ Agree</span>' if run["agree"]
            else '<span style="color:#FCD34D;">⚠️ Differ</span>'
        )
        cost_html = f"${run['cost_usd']:.4f}" if run["cost_usd"] is not None else '<span style="opacity:0.5;">—</span>'
        # IMPORTANT: no leading whitespace on any line here. Streamlit's
        # markdown parser treats 4+ spaces of indentation as a literal
        # code block, per standard Markdown rules - this applies even
        # with unsafe_allow_html=True, since indentation is checked before
        # the raw-HTML permission takes effect. An earlier indented
        # triple-quoted version of this string caused the whole table to
        # render as visible raw HTML tags instead of an actual table.
        row = (
            "<tr>"
            f'<td style="padding:10px 12px; border-bottom:1px solid #334155;">{i}</td>'
            f'<td style="padding:10px 12px; border-bottom:1px solid #334155;">'
            f'<span style="color:#94A3B8;font-size:0.82em;">{html.escape(run["claim_id"])}</span><br>'
            f'{outcome_badge(run["rung4_outcome"])}'
            "</td>"
            f'<td style="padding:10px 12px; border-bottom:1px solid #334155;">'
            f'<span style="color:#94A3B8;font-size:0.82em;">({mode_tag})</span><br>'
            f'{outcome_badge(run["rung5_outcome"])}'
            "</td>"
            f'<td style="padding:10px 12px; border-bottom:1px solid #334155;">{agree_html}</td>'
            f'<td style="padding:10px 12px; border-bottom:1px solid #334155; text-align:right; font-weight:600;">{cost_html}</td>'
            "</tr>"
        )
        rows_html.append(row)

    table_html = (
        '<table style="width:100%; border-collapse:collapse; font-size:0.92rem;">'
        "<thead>"
        '<tr style="border-bottom:2px solid #475569;">'
        '<th style="text-align:left; padding:10px 12px; width:5%;">#</th>'
        '<th style="text-align:left; padding:10px 12px; width:32%;">Rung 4</th>'
        '<th style="text-align:left; padding:10px 12px; width:32%;">Rung 5</th>'
        '<th style="text-align:left; padding:10px 12px; width:16%;">Agreement</th>'
        '<th style="text-align:right; padding:10px 12px; width:15%;">Cost</th>'
        "</tr>"
        "</thead>"
        f'<tbody>{"".join(rows_html)}</tbody>'
        "</table>"
    )
    with st.container(border=True):
        st.markdown(table_html, unsafe_allow_html=True)

    real_runs = [r for r in st.session_state.run_history if r["rung5_mode"] == "real" and r["cost_usd"] is not None]
    if len(real_runs) >= 2:
        st.subheader("Real Rung 5 cost & latency across this session")
        labels = [f"{r['claim_id']}" for r in real_runs]
        costs = [r["cost_usd"] for r in real_runs]
        latencies_s = [r["latency_ms"] / 1000 for r in real_runs]

        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            fig = go.Figure()
            fig.add_bar(
                x=labels, y=costs, marker_color="#2563EB",
                text=[f"${c:.3f}" for c in costs], textposition="outside",
            )
            fig.update_layout(
                title="Cost per run (USD)",
                template="plotly_dark",
                height=340,
                margin=dict(l=10, r=10, t=40, b=60),
                yaxis_title="USD",
                xaxis_tickangle=-30,
                showlegend=False,
            )
            st.plotly_chart(fig, width="stretch")

        with chart_col2:
            fig2 = go.Figure()
            fig2.add_bar(
                x=labels, y=latencies_s, marker_color="#F59E0B",
                text=[f"{l:.1f}s" for l in latencies_s], textposition="outside",
            )
            fig2.update_layout(
                title="Latency per run (seconds)",
                template="plotly_dark",
                height=340,
                margin=dict(l=10, r=10, t=40, b=60),
                yaxis_title="seconds",
                xaxis_tickangle=-30,
                showlegend=False,
            )
            st.plotly_chart(fig2, width="stretch")
    elif real_runs:
        st.caption("Run at least 2 claims through the real agent to see a cost/latency chart.")
