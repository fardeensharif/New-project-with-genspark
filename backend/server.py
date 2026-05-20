"""
FastAPI bridge between the horror-streamer frontend and the
HY-WorldPlay world model (real or mock).

Endpoints
---------
GET  /                  -> serves the frontend (index.html)
GET  /api/info          -> returns which adapter is loaded
POST /api/reset         -> resets the world / camera state
POST /api/step          -> JSON in, single JPEG frame out (binary)
                           body: {"direction": "...", "prompt": "...", "event": "..."}

The frontend just hammers /api/step at ~6 Hz with the current key
state, gets back a JPEG, and paints it onto a <canvas>.  This is the
simplest contract that maps cleanly onto the real model later: the
GPU host can keep its own session state keyed by client IP / cookie.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from adapters import get_adapter
import prompts as prompt_lib


# ----------------------------------------------------------------------
# App + adapter init
# ----------------------------------------------------------------------

app = FastAPI(title="HY-WorldPlay Horror Bridge", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ADAPTER = get_adapter()
# Single global adapter is fine for the demo. For multi-user prod,
# wrap this in a per-session manager.
LOCK = asyncio.Lock()


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------

VALID_DIRECTIONS = {
    "forward", "backward", "left", "right",
    "look_up", "look_down", "stop",
}
VALID_EVENTS = set(prompt_lib.EVENT_INJECTIONS.keys())


class StepRequest(BaseModel):
    direction: str = Field("stop", description="One of " + ", ".join(sorted(VALID_DIRECTIONS)))
    prompt: str = Field("", max_length=240, description="What the streamer just whispered")
    event: str = Field("none", description="Optional scripted scare: " + ", ".join(sorted(VALID_EVENTS)))


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------

@app.get("/api/info")
async def info():
    data = ADAPTER.info()
    data["valid_directions"] = sorted(VALID_DIRECTIONS)
    data["valid_events"] = sorted(VALID_EVENTS)
    return JSONResponse(data)


@app.post("/api/reset")
async def reset():
    async with LOCK:
        ADAPTER.reset()
    return {"ok": True}


@app.post("/api/step")
async def step(req: StepRequest):
    direction = req.direction if req.direction in VALID_DIRECTIONS else "stop"
    event = req.event if req.event in VALID_EVENTS else "none"

    # Build the horror-anchored prompt (logged for debugging only).
    prompt_pkg = prompt_lib.build_prompt(req.prompt, direction, event)

    # Adapter call is potentially slow (real model). Serialize.
    t0 = time.perf_counter()
    async with LOCK:
        # Mock is fast; real adapter is heavy but we still hold the lock.
        loop = asyncio.get_event_loop()
        jpeg: bytes = await loop.run_in_executor(
            None, ADAPTER.step, direction, prompt_pkg["prompt"], event
        )
    dt_ms = int((time.perf_counter() - t0) * 1000)

    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={
            "X-Frame-Latency-ms": str(dt_ms),
            "X-Direction": direction,
            "X-Event": event,
            "Cache-Control": "no-store",
        },
    )


# ----------------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------------

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

@app.get("/")
async def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/favicon.ico")
async def favicon():
    return FileResponse(os.path.join(FRONTEND_DIR, "favicon.ico"))


# Mount everything else under /static so /api/* keeps priority.
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
