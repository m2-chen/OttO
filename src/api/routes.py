"""
src/api/routes.py
WebSocket endpoint — bridges browser audio to OpenAI Realtime API.

Protocol:
  Browser → server : raw PCM16 audio bytes
  Server → browser : raw PCM16 audio bytes (OttO's voice)
  Server → browser : JSON text frames (transcripts, errors, events)
"""

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.agent.session import RealtimeSession

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/voice")
async def voice_endpoint(websocket: WebSocket):
    await websocket.accept()
    log.info("Browser connected — starting OttO session")

    session = RealtimeSession(client_ws=websocket)
    try:
        await session.run()
    except WebSocketDisconnect:
        log.info("Browser disconnected")
    except Exception as e:
        log.error(f"Session error: {e}")
