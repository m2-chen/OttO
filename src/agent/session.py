"""
src/agent/session.py
Manages a single OpenAI Realtime API WebSocket session.

Responsibilities:
  - Open a WebSocket connection to OpenAI Realtime
  - Configure the session (voice, tools, system prompt)
  - Bridge audio: browser → OpenAI, OpenAI → browser
  - Intercept function_call events, execute tools, return results
"""

import json
import asyncio
import base64
import logging
import os
from decimal import Decimal
from datetime import date, datetime

import websockets
from websockets.asyncio.client import ClientConnection

from src.agent.prompts import OTTO_SYSTEM_PROMPT
from src.agent.tools_registry import TOOL_SCHEMAS, TOOL_IMPLEMENTATIONS

log = logging.getLogger(__name__)

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-1.5"


class RealtimeSession:
    """
    Bridges a browser WebSocket (client_ws) to the OpenAI Realtime WebSocket (openai_ws).
    Audio flows in both directions; tool calls are intercepted and handled server-side.
    """

    def __init__(self, client_ws):
        self.client_ws: any = client_ws          # FastAPI WebSocket
        self.openai_ws: ClientConnection | None = None

    async def run(self):
        """Open the OpenAI connection, configure the session, then pump messages."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            await self.client_ws.send_text(json.dumps({"error": "OPENAI_API_KEY not set"}))
            return

        headers = {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        async with websockets.connect(OPENAI_REALTIME_URL, additional_headers=headers) as openai_ws:
            self.openai_ws = openai_ws
            await self._configure_session()

            # Run both directions concurrently
            await asyncio.gather(
                self._client_to_openai(),
                self._openai_to_client(),
            )

    # ------------------------------------------------------------------
    # Session configuration
    # ------------------------------------------------------------------
    async def _configure_session(self):
        """Send session.update to set voice, prompt, and tools."""
        await self.openai_ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "voice": "ash",
                "instructions": OTTO_SYSTEM_PROMPT,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",       # OpenAI detects end-of-speech automatically
                    "threshold": 0.8,           # higher = less sensitive to background noise
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 800, # wait longer before considering turn complete
                },
                "tools": TOOL_SCHEMAS,
                "tool_choice": "auto",
                "temperature": 0.7,
            },
        }))
        log.info("Session configured — OttO is ready")
        # Trigger OttO to speak first — like a real dealership picking up the phone
        await self.openai_ws.send(json.dumps({"type": "response.create"}))

    # ------------------------------------------------------------------
    # Audio bridge: browser → OpenAI
    # ------------------------------------------------------------------
    async def _client_to_openai(self):
        """
        Receive audio bytes from the browser and forward to OpenAI.
        The browser sends raw PCM16 audio as binary WebSocket frames.
        """
        try:
            async for message in self.client_ws.iter_bytes():
                audio_b64 = base64.b64encode(message).decode()
                await self.openai_ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": audio_b64,
                }))
        except Exception as e:
            log.warning(f"Client → OpenAI stream ended: {e}")

    # ------------------------------------------------------------------
    # Event bridge: OpenAI → browser (with tool interception)
    # ------------------------------------------------------------------
    async def _openai_to_client(self):
        """
        Receive events from OpenAI and:
          - Forward audio delta events straight to the browser
          - Intercept function_call_arguments.done → execute tool → return result
          - Forward transcript events for UI display
        """
        pending_tool_calls: dict[str, dict] = {}  # call_id → {name, arguments_str}

        try:
            async for raw in self.openai_ws:
                event = json.loads(raw)
                event_type = event.get("type", "")

                # Audio chunk — send directly to browser
                if event_type == "response.audio.delta":
                    audio_bytes = base64.b64decode(event["delta"])
                    await self.client_ws.send_bytes(audio_bytes)

                # Function call item added — capture the function name here
                # (the name is NOT included in subsequent delta/done events)
                elif event_type == "response.output_item.added":
                    item = event.get("item", {})
                    if item.get("type") == "function_call":
                        call_id = item["call_id"]
                        pending_tool_calls[call_id] = {"name": item["name"], "arguments": ""}
                        log.info(f"Tool call queued: {item['name']} (call_id={call_id})")

                # Tool call arguments streaming — accumulate
                elif event_type == "response.function_call_arguments.delta":
                    call_id = event["call_id"]
                    if call_id not in pending_tool_calls:
                        pending_tool_calls[call_id] = {"name": "", "arguments": ""}
                    pending_tool_calls[call_id]["arguments"] += event.get("delta", "")

                # Tool call is complete — execute it
                elif event_type == "response.function_call_arguments.done":
                    call_id   = event["call_id"]
                    name      = event.get("name") or pending_tool_calls.get(call_id, {}).get("name", "")
                    arguments = event.get("arguments", pending_tool_calls.get(call_id, {}).get("arguments", "{}"))

                    result = await self._execute_tool(name, arguments)
                    pending_tool_calls.pop(call_id, None)

                    # Return the result to OpenAI so it can speak the answer
                    await self.openai_ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(result),
                        },
                    }))
                    # Ask OpenAI to respond now
                    await self.openai_ws.send(json.dumps({"type": "response.create"}))

                # Transcript — forward to browser for display
                elif event_type in (
                    "conversation.item.input_audio_transcription.completed",
                    "response.audio_transcript.delta",
                    "response.audio_transcript.done",
                ):
                    await self.client_ws.send_text(json.dumps(event))

                # Errors — log and forward
                elif event_type == "error":
                    log.error(f"OpenAI error: {event}")
                    await self.client_ws.send_text(json.dumps(event))

        except Exception as e:
            log.warning(f"OpenAI → Client stream ended: {e}")

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------
    async def _execute_tool(self, name: str, arguments_json: str) -> dict:
        """Parse arguments and call the matching Python function."""
        try:
            args = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError:
            return {"error": f"Invalid arguments JSON for tool {name}"}

        fn = TOOL_IMPLEMENTATIONS.get(name)
        if not fn:
            return {"error": f"Unknown tool: {name}"}

        try:
            log.info(f"Tool call: {name}({args})")
            result = fn(**args)
            raw = result if isinstance(result, dict) else {"results": result}
            return self._make_serializable(raw)
        except Exception as e:
            log.error(f"Tool {name} failed: {e}")
            return {"error": str(e)}

    @staticmethod
    def _make_serializable(obj):
        """Recursively convert DB types (Decimal, date, datetime) to JSON-safe types."""
        if isinstance(obj, dict):
            return {k: RealtimeSession._make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [RealtimeSession._make_serializable(v) for v in obj]
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return obj
