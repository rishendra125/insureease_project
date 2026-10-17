"""
Command-line runner for InsureEase - run any claim through any rung
without writing a fragile inline `python -c "..."` command each time.

Forces UTF-8 stdout/stderr at the top, so trace output containing
special characters (checkmarks, emoji, etc.) never crashes on Windows'
default cp1252 console encoding - this was the root cause of the
CLM-105 print crash encountered during testing.

Usage:
    python run_claim.py CLM-100 rung4
    python run_claim.py CLM-100 stub
    python run_claim.py CLM-100 real      (costs real money - see README)
"""

import io
import sys

# force UTF-8 output regardless of the platform's default console
# encoding - must happen before any other output is written
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "data"))


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[2] not in ("rung4", "stub", "real"):
        print(__doc__)
        sys.exit(1)

    claim_id, rung = sys.argv[1], sys.argv[2]

    if rung == "rung4":
        from rung4_workflow import process_claim_fixed_workflow as fn
    elif rung == "stub":
        from rung5_stub import process_claim_stub_agent as fn
    else:
        print("NOTE: this will make a real Claude API call and incur real cost.")
        confirm = input("Type 'yes' to continue: ")
        if confirm.strip().lower() != "yes":
            print("Cancelled.")
            sys.exit(0)
        from rung5_agent import process_claim_react_agent as fn

    result = fn(claim_id)
    trace = result.get("trace", [])

    print(f"=== {rung} on {claim_id} ===")
    print(json.dumps({k: v for k, v in result.items() if k != "trace"}, indent=2, default=str))
    print()
    print("--- trace ---")
    for step in trace:
        print(step)

    # PERSISTENT log for real-agent runs, matching app.py's behavior -
    # this was missing until now, discovered when a discarded eval run's
    # trace turned out to be unrecoverable. Every real call now survives
    # this process exiting, same as calls made through the Streamlit UI.
    if rung == "real":
        log_path = Path(__file__).resolve().parent / "run_log.jsonl"
        from datetime import datetime as _dt
        log_entry = {
            "claim_id": claim_id,
            "rung5_mode": "real",
            "rung4_outcome": None,  # run_claim.py runs one rung at a time, not both
            "rung5_outcome": result.get("outcome"),
            "agree": None,
            "latency_ms": result.get("latency_ms"),
            "cost_usd": result.get("cost_usd"),
            "trace": trace,  # full trace included here, unlike app.py's log entries -
            # this is the fix for exactly the "trace was thrown away" problem
            "timestamp": _dt.now().isoformat(),
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, default=str) + "\n")
        print()
        print(f"📝 Logged to run_log.jsonl (full trace included, permanent record).")


if __name__ == "__main__":
    main()
