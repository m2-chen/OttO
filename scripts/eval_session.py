"""
scripts/eval_session.py

Print a readable evaluation report for the last (or a specific) OttO session.

Usage:
    python scripts/eval_session.py                  # latest session
    python scripts/eval_session.py 20250404_143022  # specific session
"""

import json
import sys
from pathlib import Path

TRACE_DIR = Path("data/session_traces")

RAG_TOOLS   = {"search_knowledge_base"}
DB_TOOLS    = {"search_vehicles", "get_vehicle_details", "compare_vehicles",
               "list_available_slots", "book_slot", "cancel_slot",
               "get_customer_service_history", "get_next_service_recommendation",
               "find_parts", "check_part_stock"}
WEB_TOOLS   = {"search_web"}


def load_trace(session_id: str | None = None) -> dict:
    files = sorted(TRACE_DIR.glob("session_*.json"))
    if not files:
        print("No session traces found. Run OttO and have a conversation first.")
        sys.exit(1)

    if session_id:
        matches = [f for f in files if session_id in f.name]
        if not matches:
            print(f"No trace found for session ID: {session_id}")
            sys.exit(1)
        path = matches[-1]
    else:
        path = files[-1]

    with open(path) as f:
        return json.load(f), path


def fmt_ms(ms: int) -> str:
    return f"{ms}ms" if ms < 1000 else f"{ms/1000:.1f}s"


def print_report(trace: dict, path: Path):
    calls = trace.get("tool_calls", [])
    turns = trace.get("transcript", [])

    print("=" * 70)
    print(f"  OttO SESSION EVALUATION REPORT")
    print(f"  Session : {trace['session_id']}")
    print(f"  Started : {trace['started_at']}")
    print(f"  Duration: {trace['duration_s']}s")
    print(f"  Turns   : {len([t for t in turns if t['role'] == 'customer'])} customer, "
          f"{len([t for t in turns if t['role'] == 'otto'])} OttO")
    print(f"  Tools   : {len(calls)} calls")
    print("=" * 70)

    # ── Tool call summary ─────────────────────────────────────────────────
    print("\n  TOOL CALLS (chronological)\n")

    rag_calls, db_calls, web_calls, other_calls = [], [], [], []
    for c in calls:
        t = c.get("tool", "")
        if t in RAG_TOOLS:   rag_calls.append(c)
        elif t in DB_TOOLS:  db_calls.append(c)
        elif t in WEB_TOOLS: web_calls.append(c)
        else:                other_calls.append(c)

    for i, c in enumerate(calls, 1):
        tool    = c.get("tool", "?")
        latency = fmt_ms(c.get("latency_ms", 0))
        args    = c.get("args", {})
        result  = c.get("result", {})

        if tool in RAG_TOOLS:    source = "RAG"
        elif tool in DB_TOOLS:   source = "DB"
        elif tool in WEB_TOOLS:  source = "WEB"
        else:                    source = "SYS"

        print(f"  [{i:>2}] [{source}] {tool}  ({latency})")

        # Args
        if args:
            for k, v in args.items():
                print(f"        arg  {k}: {v!r}")

        # Tool-specific result summary
        if tool == "search_knowledge_base":
            pages = result.get("pages", [])
            if result.get("status") == "no_results":
                print(f"        ⚠  No results returned")
            else:
                print(f"        ✓  {result.get('pages_retrieved', 0)} page(s) retrieved")
                for p in pages:
                    print(f"           • {p['source']}")
                    print(f"             {p['preview']}")

        elif tool == "search_vehicles":
            print(f"        ✓  {result.get('vehicles_found', '?')} vehicle(s) found")

        elif tool == "get_vehicle_details":
            print(f"        ✓  {result.get('model')}  stock={result.get('stock')}  "
                  f"price=€{result.get('dealer_price', '?')}")

        elif tool == "book_slot":
            status = "✓  Booked" if result.get("success") else "✗  Failed"
            print(f"        {status}  {result.get('customer_name')} @ {result.get('datetime')}")

        elif isinstance(result, dict):
            for k, v in list(result.items())[:3]:
                print(f"        {k}: {str(v)[:80]}")

        print()

    # ── Routing analysis ──────────────────────────────────────────────────
    print("  ROUTING ANALYSIS\n")
    print(f"    RAG calls : {len(rag_calls):>2}  (catalog knowledge)")
    print(f"    DB calls  : {len(db_calls):>2}  (stock, pricing, booking)")
    print(f"    Web calls : {len(web_calls):>2}  (external search)")
    print(f"    Other     : {len(other_calls):>2}  (email modal, etc.)")

    # Latency stats
    if calls:
        latencies = [c.get("latency_ms", 0) for c in calls]
        print(f"\n    Avg latency : {sum(latencies)//len(latencies)}ms")
        print(f"    Slowest     : {max(latencies)}ms  ({calls[latencies.index(max(latencies))].get('tool')})")
        print(f"    Fastest     : {min(latencies)}ms  ({calls[latencies.index(min(latencies))].get('tool')})")

    # ── Transcript ────────────────────────────────────────────────────────
    print("\n" + "─" * 70)
    print("  FULL TRANSCRIPT\n")

    for turn in turns:
        role  = "Customer" if turn["role"] == "customer" else "OttO   "
        print(f"  {role}: {turn['text']}")
    print()

    print(f"  [Trace file: {path}]")
    print("=" * 70)


if __name__ == "__main__":
    session_id = sys.argv[1] if len(sys.argv) > 1 else None
    trace, path = load_trace(session_id)
    print_report(trace, path)
