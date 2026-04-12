"""
src/agent/session_trace.py

Per-session structured trace for evaluating OttO's behavior.

Captures every turn: what the customer said, what tool OttO called,
what it got back, and what it said. Written to a JSON file at end of session.

Evaluation targets:
  - Tool routing correctness (did OttO pick the right tool?)
  - RAG quality (similarity scores, pages retrieved, was it useful?)
  - Response faithfulness (did OttO stick to what the tool returned?)
  - Latency (how long did each tool call take?)
"""

import json
import time
from datetime import datetime
from pathlib import Path

TRACE_DIR = Path("data/session_traces")


class SessionTrace:
    """
    Accumulates all agent interactions for one WebSocket session.
    Call .save() at session end to persist the trace as JSON.
    """

    def __init__(self):
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.started_at = time.time()
        self.turns: list[dict] = []             # conversation turns
        self.tool_calls: list[dict] = []        # all tool invocations
        self._pending: dict[str, dict] = {}     # call_id → pending tool call

    # ------------------------------------------------------------------ #
    # Conversation turns
    # ------------------------------------------------------------------ #

    def log_customer(self, text: str):
        self.turns.append({
            "role":      "customer",
            "text":      text,
            "timestamp": time.time(),
        })
        self.save()

    def log_otto(self, text: str):
        self.turns.append({
            "role":      "otto",
            "text":      text,
            "timestamp": time.time(),
        })
        self.save()

    # ------------------------------------------------------------------ #
    # Tool call lifecycle
    # ------------------------------------------------------------------ #

    def tool_started(self, call_id: str, name: str, args: dict):
        self._pending[call_id] = {
            "call_id":    call_id,
            "tool":       name,
            "args":       args,
            "started_at": time.time(),
        }

    def tool_finished(self, call_id: str, result: dict | list | str):
        entry = self._pending.pop(call_id, {})
        entry["latency_ms"] = round((time.time() - entry.get("started_at", time.time())) * 1000)
        entry["result"]     = self._summarise_result(entry.get("tool", ""), result)
        self.tool_calls.append(entry)
        self.save()

    # ------------------------------------------------------------------ #
    # Result summariser — keeps the trace readable
    # ------------------------------------------------------------------ #

    @staticmethod
    def _summarise_result(tool: str, result) -> dict:
        """
        For RAG: extract similarity scores and page count — the raw text can be huge.
        For search_vehicles: count results.
        For everything else: pass through as-is (it's already compact JSON).
        """
        if tool == "search_knowledge_base":
            # search_knowledge_base returns {"text": "...", "image_paths": [...]}
            # extract the text field for page parsing
            if isinstance(result, dict):
                text = result.get("text", "")
            else:
                text = str(result)

            if not text or text.startswith("No"):
                return {"status": "no_results", "raw": text}

            result = text

            pages = []
            for block in result.split("\n\n---\n\n"):
                header_end = block.find("]")
                if header_end != -1:
                    header   = block[1:header_end]     # "Kia EV9 — Catalog page 3"
                    preview  = block[header_end + 2:header_end + 120].replace("\n", " ")
                    pages.append({"source": header, "preview": preview + "…"})
            return {"pages_retrieved": len(pages), "pages": pages}

        if tool == "search_vehicles":
            items = result.get("results", result) if isinstance(result, dict) else result
            count = len(items) if isinstance(items, list) else 1
            return {"vehicles_found": count, "raw": result}

        if tool == "get_vehicle_details":
            raw = result if isinstance(result, dict) else {}
            return {
                "model":        raw.get("model"),
                "stock":        raw.get("total_stock"),
                "dealer_price": raw.get("min_dealer_price"),
            }

        if tool == "book_slot":
            raw = result if isinstance(result, dict) else {}
            return {
                "success":       raw.get("success"),
                "customer_name": raw.get("customer_name"),
                "datetime":      raw.get("datetime"),
            }

        # Default — return as-is (small payloads like list_available_slots, find_parts, etc.)
        return result if isinstance(result, (dict, list)) else {"raw": str(result)[:300]}

    # ------------------------------------------------------------------ #
    # Save to disk
    # ------------------------------------------------------------------ #

    def save(self):
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        path = TRACE_DIR / f"session_{self.session_id}.json"

        payload = {
            "session_id":   self.session_id,
            "started_at":   datetime.fromtimestamp(self.started_at).isoformat(),
            "duration_s":   round(time.time() - self.started_at),
            "turn_count":   len(self.turns),
            "tool_calls":   self.tool_calls,
            "transcript":   self.turns,
        }

        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)

        return path
