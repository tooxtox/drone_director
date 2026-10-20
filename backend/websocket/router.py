"""Bounded dashboard stream; a fresh connection receives environment and waypoints."""

import asyncio
from time import monotonic

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/api/ws")
async def stream(socket: WebSocket):
    await socket.accept()
    engine = socket.app.state.engine
    previous_environment = None
    previous_state = None
    last_sent = 0.0
    sequence = 0
    try:
        while True:
            if sequence and (engine.version, engine.environment.version) == previous_state and monotonic() - last_sent < 2:
                await asyncio.sleep(0.05)
                continue
            snapshot = await asyncio.to_thread(engine.snapshot, include_environment=False)
            version = snapshot.get("environment_version")
            state = (snapshot.get("version"), version)
            if sequence == 0 or version != previous_environment:
                snapshot = await asyncio.to_thread(engine.snapshot, include_environment=True)
                previous_environment = snapshot.get("environment_version")
                state = (snapshot.get("version"), previous_environment)
            else:
                snapshot.pop("waypoints")
            snapshot.pop("missions")
            snapshot["history"] = snapshot["history"][-240:]
            sequence += 1
            await asyncio.wait_for(socket.send_json({
                "type": "snapshot", "sequence": sequence, "data": snapshot,
            }), timeout=5.0)
            previous_state = state
            last_sent = monotonic()
            # Simulation advances independently; a slow subscriber cannot accumulate a queue.
            await asyncio.sleep(0.2)
    except (WebSocketDisconnect, asyncio.TimeoutError, OSError, RuntimeError):
        return
