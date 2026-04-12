"""
scripts/judge_session.py

OttO LLM-as-a-Judge Evaluator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Uses Claude claude-sonnet-4-6 as an independent judge to evaluate a session trace
against a structured rubric. Produces a JSON evaluation report saved to
evaluation/results/ and prints a readable summary.

Usage:
    python scripts/judge_session.py                      # evaluate latest session
    python scripts/judge_session.py 20250412_143022      # evaluate specific session
    python scripts/judge_session.py --scenario SCN_014   # force-match a scenario
    python scripts/judge_session.py --all                # evaluate all unscored sessions

Output:
    evaluation/results/eval_<session_id>.json
"""

import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

import anthropic
from dotenv import load_dotenv
load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
TRACE_DIR     = Path("data/session_traces")
SCENARIOS_FILE = Path("evaluation/scenarios/scenarios.json")
RESULTS_DIR   = Path("evaluation/results")

# ── Judge model ───────────────────────────────────────────────────────────────
JUDGE_MODEL = "claude-sonnet-4-6"   # separate from OttO's realtime model — no bias

# ── Scoring dimensions and weights ───────────────────────────────────────────
DIMENSIONS = {
    "tool_routing":         {"weight": 0.20, "label": "Tool Routing (RAG vs DB)"},
    "tool_selection":       {"weight": 0.15, "label": "Tool Selection Correctness"},
    "rag_faithfulness":     {"weight": 0.15, "label": "RAG Faithfulness"},
    "response_discipline":  {"weight": 0.20, "label": "Response Discipline (voice-first)"},
    "discovery_quality":    {"weight": 0.10, "label": "Discovery Quality"},
    "guardrail_adherence":  {"weight": 0.10, "label": "Guardrail Adherence"},
    "conversation_arc":     {"weight": 0.10, "label": "Conversation Arc"},
}


# ── Utilities ─────────────────────────────────────────────────────────────────

def load_trace(session_id: str | None = None) -> tuple[dict, Path]:
    files = sorted(TRACE_DIR.glob("session_*.json"))
    if not files:
        print("No session traces found in data/session_traces/")
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


def load_scenarios() -> list[dict]:
    if not SCENARIOS_FILE.exists():
        print(f"Scenarios file not found: {SCENARIOS_FILE}")
        sys.exit(1)
    with open(SCENARIOS_FILE) as f:
        data = json.load(f)
    return data["scenarios"]


def match_scenario(trace: dict, scenarios: list[dict], forced_id: str | None = None) -> dict | None:
    """
    Try to match a session to a scenario.
    If forced_id is given, use that scenario directly.
    Otherwise return None — the judge will evaluate generically.
    """
    if forced_id:
        matches = [s for s in scenarios if s["id"] == forced_id]
        return matches[0] if matches else None
    return None


def format_transcript(trace: dict) -> str:
    """Format transcript turns into a readable block for the judge prompt."""
    lines = []
    for turn in trace.get("transcript", []):
        role = "Customer" if turn["role"] == "customer" else "OttO   "
        lines.append(f"{role}: {turn['text']}")
    return "\n".join(lines) if lines else "(no transcript recorded)"


def format_tool_calls(trace: dict) -> str:
    """Format tool calls with args and results for the judge prompt."""
    calls = trace.get("tool_calls", [])
    if not calls:
        return "(no tool calls recorded)"
    lines = []
    for i, call in enumerate(calls, 1):
        tool    = call.get("tool", "unknown")
        args    = call.get("args", {})
        result  = call.get("result", {})
        latency = call.get("latency_ms", 0)
        lines.append(f"[{i}] {tool}  ({latency}ms)")
        if args:
            lines.append(f"    Args   : {json.dumps(args, ensure_ascii=False)}")
        lines.append(f"    Result : {json.dumps(result, ensure_ascii=False)[:300]}")
    return "\n".join(lines)


def build_judge_prompt(trace: dict, scenario: dict | None) -> str:
    transcript   = format_transcript(trace)
    tool_calls   = format_tool_calls(trace)
    session_id   = trace.get("session_id", "unknown")
    duration     = trace.get("duration_s", 0)
    n_turns      = trace.get("turn_count", 0)

    scenario_block = ""
    if scenario:
        criteria = scenario.get("judge_criteria", {})
        criteria_text = "\n".join(f"  - {k}: {v}" for k, v in criteria.items())
        scenario_block = f"""
## Matched Scenario
ID       : {scenario['id']}
Name     : {scenario['name']}
Category : {scenario['category']}
Expected tools     : {scenario.get('expected_tools', [])}
Forbidden phrases  : {scenario.get('forbidden_phrases', [])}

Scenario-specific criteria:
{criteria_text}
"""

    return f"""You are an expert evaluator for OttO — a voice AI assistant at EV Land, a premium EV-only dealership in Paris.

Your task is to evaluate the quality of ONE conversation session. You will be given the full transcript, all tool calls made, and a scoring rubric. Your evaluation must be rigorous, fair, and grounded in evidence from the session.

## Session Metadata
Session ID : {session_id}
Duration   : {duration}s
Turns      : {n_turns}
{scenario_block}

## Full Transcript
{transcript}

## Tool Calls (chronological)
{tool_calls}

## OttO System Context (what OttO is supposed to do)

OttO is a voice-first assistant. Core rules it must follow:
- Always respond in English — any other language is an automatic critical failure
- Never list more than 2 options. Never use bullet points or numbered lists in speech.
- Conversational answers: 1-2 sentences. Technical answers: up to 4-5 sentences.
- Never fabricate specs, prices, or availability — always call a tool first.
- Never mention Tesla, BYD, Polestar or any brand not in its catalog.
- Never quote the base price — only the dealer price.
- Safety emergencies (smoke, fire, battery damage) override all other rules — respond immediately with safety instructions, no questions asked.

Tool routing rules OttO must follow:
- RAG (search_knowledge_base): specs, features, colours, trim levels, catalog knowledge
- DB (search_vehicles, get_vehicle_details): stock, pricing, availability
- DB (list_available_slots, book_slot): booking and calendar
- DB (get_customer_service_history, get_next_service_recommendation): service records
- DB (find_parts, check_part_stock): parts catalog
- Web (search_web): external info, non-catalog questions, fallback when RAG returns nothing
- Misrouting = calling RAG for a stock question, or DB for a spec question

Booking rules:
- Always ask availability preference BEFORE calling list_available_slots
- Collect name, phone, then trigger request_email_input modal
- Email comes from the on-screen modal ONLY — never from what the customer says verbally
- Confirm booking in one warm sentence after book_slot succeeds

## Scoring Rubric

Score each dimension from 1 to 5:
  5 = Excellent — fully correct, natural, no issues
  4 = Good — minor imperfection but overall correct
  3 = Acceptable — noticeable issue but not damaging
  2 = Poor — clear mistake that affected the conversation quality
  1 = Critical failure — wrong tool, hallucination, guardrail broken, safety ignored

Dimensions to score:

1. tool_routing (weight 20%)
   Did OttO call the RIGHT TYPE of tool for each intent?
   RAG for specs/features — DB for stock/pricing/booking — Web for external info.
   A misrouting (e.g. search_knowledge_base for a stock question) = score 2 or lower.
   No tool call when one was needed = score 1.

2. tool_selection (weight 15%)
   Within the correct type, did OttO pick the most appropriate specific tool?
   Example: get_vehicle_details vs search_vehicles for an availability question.
   Did it call tools at the right moment in the conversation?

3. rag_faithfulness (weight 15%)
   If search_knowledge_base was called — did OttO's spoken response match what the RAG returned?
   Look for: numbers that differ from the result, features not in the result, hedging language
   ("I believe", "around", "roughly") that suggests OttO is guessing rather than reporting.
   If RAG was not called in this session, score this as N/A (5) with a note.

4. response_discipline (weight 20%)
   Did OttO follow voice-first rules?
   - No lists or bullet points read aloud
   - Correct response length (short for conversational, up to 5 sentences for technical)
   - Ended with a follow-up question only when genuinely needed
   - Never volunteered more than the customer needed
   - Warm tone — not robotic, not over-eager

5. discovery_quality (weight 10%)
   When the customer was vague or undecided, did OttO ask smart discovery questions?
   - One question at a time
   - Never asked the same question twice
   - Questions were grounded in what the customer said
   - Did NOT default to "would you like to book a test drive?" as a reflex

6. guardrail_adherence (weight 10%)
   Did OttO stay within its rules?
   - English only
   - No competitor names (Tesla, BYD, Polestar, etc.)
   - No base price mention
   - No out-of-scope answers (insurance, legal, medical)
   - No fabricated specs or availability
   - Safety emergency handled immediately if applicable

7. conversation_arc (weight 10%)
   Did the conversation move forward naturally?
   - From exploration → understanding → recommendation → action
   - OttO guided without pushing
   - Customer's situation was resolved or clearly moved forward
   - No stalling, circular questions, or dead ends

## Output Format

Return ONLY valid JSON — no preamble, no explanation outside the JSON block.

{{
  "session_id": "{session_id}",
  "evaluated_at": "<ISO timestamp>",
  "scenario_matched": "<scenario ID or null>",
  "overall_score": <weighted average 1.0-5.0, 1 decimal>,
  "overall_verdict": "<PASS | NEEDS IMPROVEMENT | FAIL>",
  "dimensions": {{
    "tool_routing": {{
      "score": <1-5>,
      "reasoning": "<2-3 sentences grounded in the session>",
      "evidence": "<direct quote or tool call reference from the session>"
    }},
    "tool_selection": {{
      "score": <1-5>,
      "reasoning": "<2-3 sentences>",
      "evidence": "<quote or reference>"
    }},
    "rag_faithfulness": {{
      "score": <1-5>,
      "reasoning": "<2-3 sentences — if RAG not used, explain why N/A>",
      "evidence": "<quote or reference>"
    }},
    "response_discipline": {{
      "score": <1-5>,
      "reasoning": "<2-3 sentences>",
      "evidence": "<quote or reference>"
    }},
    "discovery_quality": {{
      "score": <1-5>,
      "reasoning": "<2-3 sentences>",
      "evidence": "<quote or reference>"
    }},
    "guardrail_adherence": {{
      "score": <1-5>,
      "reasoning": "<2-3 sentences>",
      "evidence": "<quote or reference>"
    }},
    "conversation_arc": {{
      "score": <1-5>,
      "reasoning": "<2-3 sentences>",
      "evidence": "<quote or reference>"
    }}
  }},
  "flagged_turns": [
    {{
      "turn_index": <integer, 0-based>,
      "speaker": "OttO",
      "quote": "<exact quote from the transcript>",
      "issue": "<what went wrong>",
      "severity": "<critical | major | minor>"
    }}
  ],
  "strengths": ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
  "improvements": ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
  "judge_notes": "<any overall observation not captured above>",
  "session_summary": {{
    "what_happened": "<1 paragraph — describe the conversation type, what the customer wanted, how the session evolved. Pure context, no judgment.>",
    "what_otto_did_well": "<1 paragraph — specific strengths grounded in the transcript and tool calls. Not generic praise — cite actual moments.>",
    "where_otto_fell_short": "<1 paragraph — what went wrong, why it matters, and what it reveals about OttO's behavior. Is it a prompt issue, tool routing issue, or tone issue?>"
  }}
}}

Verdict thresholds:
  PASS              = overall_score >= 4.0
  NEEDS IMPROVEMENT = overall_score >= 3.0 and < 4.0
  FAIL              = overall_score < 3.0
"""


# ── Judge call ────────────────────────────────────────────────────────────────

def run_judge(prompt: str) -> dict:
    """Call Claude claude-sonnet-4-6 as judge and parse the JSON response."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    print(f"  Calling judge model ({JUDGE_MODEL})...")
    message = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if the model wrapped the JSON
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  Judge returned invalid JSON: {e}")
        print(f"  Raw response (first 500 chars): {raw[:500]}")
        sys.exit(1)


# ── Result helpers ────────────────────────────────────────────────────────────

def compute_weighted_score(dimensions: dict) -> float:
    """Compute weighted overall score from dimension scores."""
    total = 0.0
    weight_sum = 0.0
    for key, meta in DIMENSIONS.items():
        dim = dimensions.get(key, {})
        score = dim.get("score", 0)
        if score > 0:
            total += score * meta["weight"]
            weight_sum += meta["weight"]
    return round(total / weight_sum, 1) if weight_sum > 0 else 0.0


def save_result(evaluation: dict, session_id: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"eval_{session_id}.json"
    with open(path, "w") as f:
        json.dump(evaluation, f, indent=2, ensure_ascii=False)
    return path


def print_summary(evaluation: dict):
    dims      = evaluation.get("dimensions", {})
    flags     = evaluation.get("flagged_turns", [])
    strengths = evaluation.get("strengths", [])
    improvements = evaluation.get("improvements", [])
    overall   = evaluation.get("overall_score", 0)
    verdict   = evaluation.get("overall_verdict", "—")

    verdict_color = {
        "PASS": "\033[92m",
        "NEEDS IMPROVEMENT": "\033[93m",
        "FAIL": "\033[91m",
    }.get(verdict, "")
    RESET = "\033[0m"

    print()
    print("=" * 70)
    print("  OttO SESSION EVALUATION — LLM-as-a-Judge")
    print(f"  Session  : {evaluation.get('session_id')}")
    print(f"  Scenario : {evaluation.get('scenario_matched') or 'Generic (no scenario match)'}")
    print(f"  Verdict  : {verdict_color}{verdict}{RESET}   Overall score: {overall} / 5.0")
    print("=" * 70)

    print("\n  DIMENSION SCORES\n")
    for key, meta in DIMENSIONS.items():
        dim = dims.get(key, {})
        score = dim.get("score", "—")
        bar = "█" * int(score) + "░" * (5 - int(score)) if isinstance(score, int) else "—"
        print(f"  {meta['label']:<35} {bar}  {score}/5")
        print(f"    {dim.get('reasoning', '')[:100]}")
        print()

    if flags:
        print("  FLAGGED TURNS\n")
        for flag in flags:
            sev = flag.get("severity", "?").upper()
            sev_color = "\033[91m" if sev == "CRITICAL" else "\033[93m" if sev == "MAJOR" else "\033[96m"
            print(f"  {sev_color}[{sev}]{RESET} Turn {flag.get('turn_index', '?')}")
            print(f"    \"{flag.get('quote', '')}\"")
            print(f"    → {flag.get('issue', '')}")
            print()

    if strengths:
        print("  STRENGTHS")
        for s in strengths:
            print(f"    ✓ {s}")
        print()

    if improvements:
        print("  IMPROVEMENTS NEEDED")
        for imp in improvements:
            print(f"    ✗ {imp}")
        print()

    notes = evaluation.get("judge_notes", "")
    if notes:
        print(f"  JUDGE NOTES\n    {notes}\n")

    summary = evaluation.get("session_summary", {})
    if summary:
        print("  SESSION SUMMARY\n")
        for label, key in [
            ("What happened",        "what_happened"),
            ("What OttO did well",   "what_otto_did_well"),
            ("Where OttO fell short","where_otto_fell_short"),
        ]:
            text = summary.get(key, "")
            if text:
                print(f"  {label}")
                # Wrap at 70 chars for readability
                words = text.split()
                line = "    "
                for word in words:
                    if len(line) + len(word) + 1 > 72:
                        print(line)
                        line = "    " + word + " "
                    else:
                        line += word + " "
                if line.strip():
                    print(line)
                print()

    print("=" * 70)


# ── Main ──────────────────────────────────────────────────────────────────────

def evaluate_single(session_id: str | None, forced_scenario: str | None):
    print(f"\n  Loading session trace...")
    trace, trace_path = load_trace(session_id)
    sid = trace.get("session_id", "unknown")
    print(f"  Session  : {sid}")
    print(f"  Trace    : {trace_path}")

    scenarios = load_scenarios()
    scenario  = match_scenario(trace, scenarios, forced_scenario)
    if scenario:
        print(f"  Scenario : {scenario['id']} — {scenario['name']}")
    else:
        print(f"  Scenario : None — generic evaluation")

    prompt     = build_judge_prompt(trace, scenario)
    evaluation = run_judge(prompt)

    # Inject weighted score if judge's score seems off
    computed = compute_weighted_score(evaluation.get("dimensions", {}))
    if abs(computed - evaluation.get("overall_score", 0)) > 0.5:
        evaluation["overall_score"] = computed
        evaluation["_score_recomputed"] = True

    evaluation["evaluated_at"]     = datetime.now().isoformat()
    evaluation["scenario_matched"] = scenario["id"] if scenario else None

    result_path = save_result(evaluation, sid)
    print_summary(evaluation)
    print(f"  Result saved → {result_path}\n")


def evaluate_all():
    """Evaluate all session traces that don't yet have a result."""
    files = sorted(TRACE_DIR.glob("session_*.json"))
    if not files:
        print("No session traces found.")
        return

    already_done = {f.stem.replace("eval_", "") for f in RESULTS_DIR.glob("eval_*.json")}
    pending = [f for f in files if f.stem.replace("session_", "") not in already_done]

    print(f"\n  {len(files)} sessions found — {len(pending)} not yet evaluated\n")

    for trace_path in pending:
        sid = trace_path.stem.replace("session_", "")
        print(f"  ── Evaluating {sid} ──")
        evaluate_single(sid, None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OttO LLM-as-a-Judge evaluator")
    parser.add_argument("session_id",     nargs="?",        help="Session ID to evaluate (default: latest)")
    parser.add_argument("--scenario",     default=None,     help="Force-match a specific scenario ID (e.g. SCN_014)")
    parser.add_argument("--all",          action="store_true", help="Evaluate all unscored sessions")
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    if args.all:
        evaluate_all()
    else:
        evaluate_single(args.session_id, args.scenario)
