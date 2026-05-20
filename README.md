# NIGHTWATCH-CAM — HY-WorldPlay Found-Footage Horror

A "live-streamed gothic nightmare at 2 AM" built on top of the Tencent
**[HY-WorldPlay](https://github.com/Tencent-Hunyuan/HY-WorldPlay)** /
[tencent/HY-World-2.0](https://huggingface.co/tencent/HY-World-2.0)
generative world model.

It looks like raw bodycam footage, not a video game: heavy charcoal fog,
flickering amber streetlamps, decaying Victorian buildings, cobblestone
alleys that subtly warp as the AI dreams them up frame-by-frame. Press
WASD to walk. Whisper into the mic — what you say steers the world.
Say "I think there's someone in the alley…" and a pale faceless
silhouette manifests out of the fog beneath a broken window.

## Architecture

```
   ┌────────────────────┐         ┌──────────────────────────┐
   │  Browser frontend  │         │   FastAPI bridge         │
   │  (index.html +     │ POST    │   backend/server.py      │
   │   app.js + canvas) │ ──────► │                          │
   │                    │ /step   │   ┌──────────────────┐   │
   │  • WASD keys       │ {dir,   │   │ MockAdapter      │   │ ← runs anywhere (CPU)
   │  • Mic → prompt    │  prompt,│   │ (procedural PIL) │   │
   │  • HUD: chat,      │  event} │   └──────────────────┘   │
   │    sanity EKG,     │ ◄────── │   ┌──────────────────┐   │
   │    viewer count,   │  JPEG   │   │ HYWorldAdapter   │   │ ← real GPU model
   │    glitches        │         │   │ tencent/HY-World │   │   (WORLD_BACKEND
   │  • Jump-scare FX   │         │   │ -2.0  (CUDA)     │   │    =hyworld)
   └────────────────────┘         │   └──────────────────┘   │
                                   │     ▲                    │
                                   │     │ prompts.py:        │
                                   │     │ horror style       │
                                   │     │ prefix + negative  │
                                   │     │ prompt every call  │
                                   └──────────────────────────┘
```

The frontend never knows which adapter is active — it just calls
`POST /api/step` and paints whatever JPEG comes back onto a `<canvas>`.

## Quick start (CPU, no GPU required)

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

You'll be running the **MockAdapter** — a procedural PIL renderer that
paints a gothic alley with all the right beats (perspective cobblestones,
flickering lamp, broken windows, fog, faceless figures on cue). It's
not the real AI model but it lets you build and demo the whole streamer
experience without a GPU.

## Switching to the real Tencent HY-WorldPlay model

You need a Linux box with an NVIDIA GPU — A100 / H100 or any 40GB+ card.
A consumer 4090 may work for the smaller HY-World-2.0 variant with
quantization. RunPod, Lambda Labs, Vast.ai or your own rig all work.

```bash
# 1. Base PyTorch + libs
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install diffusers transformers accelerate safetensors einops huggingface_hub
pip install -r backend/requirements.txt

# 2. Accept the model licence and pull weights
huggingface-cli login            # one-time, accept the model's licence
git clone https://huggingface.co/tencent/HY-World-2.0 ./weights/HY-World-2.0

# (or, if you want the playable variant with the action conditioning head)
git clone https://github.com/Tencent-Hunyuan/HY-WorldPlay
bash HY-WorldPlay/scripts/download_weights.sh

# 3. Flip the adapter to the real model and start the server
export WORLD_BACKEND=hyworld
export HYWORLD_WEIGHTS=$PWD/weights/HY-World-2.0
cd backend && uvicorn server:app --host 0.0.0.0 --port 8000
```

The `HYWorldAdapter` (in `backend/adapters/hyworld_adapter.py`) tries
the most common upstream entry-point names (`WorldPlayPipeline.step`,
`diffusers.DiffusionPipeline` with `trust_remote_code=True`, etc.).
If Tencent renames the API in a future release, update `_call_pipeline`
— it's intentionally a small, well-commented function.

The frontend is identical in both modes; only `/api/info` will report
`"backend": "hyworld"` instead of `"mock"`.

## API contract

| Method | Path        | Body / Response |
| ------ | ----------- | --------------- |
| GET    | `/api/info` | JSON: `{backend, resolution, valid_directions, valid_events}` |
| POST   | `/api/reset`| Reset world / camera state |
| POST   | `/api/step` | Body: `{"direction": "forward\|backward\|left\|right\|look_up\|look_down\|stop", "prompt": "<what you said>", "event": "none\|figure\|shadow\|child\|hand"}`. Response: `image/jpeg` binary. Latency reported in `X-Frame-Latency-ms` header. |

The frontend polls `/api/step` at ~6 Hz with the current key state —
which is also a sane budget for the real model on an H100 (~150 ms / frame).

## The horror prompt-injection layer

Every prompt is sandwiched in `backend/prompts.py`:

```
STYLE_PREFIX  ::= ultra-realistic bodycam, 2 AM, charcoal fog, gothic
                  Victorian, damp cobbles, flickering amber streetlamp,
                  decaying brick, broken windows, 15-foot visibility, ...

DIRECTION     ::= "camera advances slowly down a misty alley"
                | "camera retreats backwards, frame bobbing"
                | ...

USER_PROMPT   ::= (whatever the streamer just whispered, max 240 chars)

EVENT         ::= "" | "pale faceless silhouette manifests..."
                       | "tall distorted shadow flickers..."
                       | "Victorian child in white dress..."
                       | "gaunt pale hand reaches out..."

NEGATIVE      ::= daytime, sunny, cartoon, video-game UI, neon, modern, ...
```

This is how we keep the AI dream locked inside the nightmare — without
it, HY-World-2.0 will happily hand you a sunny Italian piazza.

## The streamer HUD

All on top of a single `<canvas>` showing the world feed:

| Position | Element | Behaviour |
| -------- | ------- | --------- |
| Top-left | 🔴 LIVE + viewer count | Viewer count drifts around ~250 but **spikes by hundreds** the moment a scare fires |
| Top-right | Flashlight battery | Drains while on, recovers off; flashlight off = scene drowned in black with only a tiny ambient lamp cone |
| Bottom-left | Chat | Twitch-style usernames, 16-message rolling window. Quiet ambient chatter most of the time, **explodes** with "RUN!", "WTF IS THAT", "TURN AROUND" when scares fire |
| Bottom-center | Subtitles | Live captions from Web Speech API; the exact text is also forwarded to the model as the `prompt` so what you say shapes the world |
| Bottom bar | Sanity heartbeat (EKG) + BPM | BPM climbs as sanity drops; below 35 the whole stage shakes and `#glitch` engages |

## Jump-scare trigger words

If you say any of these into the mic, the backend gets a scripted
`event` injected into the next prompt, and the frontend simultaneously
fires red-flash + glitch + chat-spam + sanity-drop:

| You say… | Event injected |
| -------- | -------------- |
| "someone / figure / man / woman in / down / near …" | `figure` (pale faceless silhouette) |
| "child / kid / girl / boy" | `child` (Victorian child in white) |
| "shadow / something moving" | `shadow` |
| "hand / fingers" | `hand` (reaching from a shattered window) |

## Controls

| Key | Action |
| --- | ------ |
| `W` / `↑` | Walk forward (slow) |
| `S` / `↓` | Retreat backward (panicked bob) |
| `A` `D` / `←` `→` | Pan left / right |
| `Q` `E` | Look up / look down |
| `Space` (hold) | Push-to-talk mic |
| `F` | Toggle flashlight |
| `R` | Reset world |

## Development roadmap status

- [x] **Run the baseline demo** — model weight pull procedure documented; `HYWorldAdapter` wraps the upstream pipeline behind the same interface MockAdapter exposes, so the frontend doesn't change.
- [x] **Build the bridge API** — FastAPI app: `POST /api/step` takes a directional string + prompt, returns a single JPEG frame (`image/jpeg`). Easily upgraded to MJPEG / WebSocket for sub-100ms streaming if needed.
- [x] **Integrate the stream receiver** — frontend `<canvas>` polls at 6 Hz, key state mapped to API requests, mic captions forwarded as prompt steering.
- [x] **Fine-tune the ambiance** — `backend/prompts.py` injects the gothic style prefix + negative prompt into every call. Direction-specific motion hints and event-specific scare injections layered on top.

## Layout

```
webapp/
├── README.md               # this file
├── backend/
│   ├── server.py           # FastAPI app
│   ├── prompts.py          # horror prompt-injection layer
│   ├── requirements.txt
│   └── adapters/
│       ├── __init__.py     # picks Mock vs HYWorld at startup
│       ├── mock_adapter.py # procedural PIL renderer (CPU)
│       └── hyworld_adapter.py  # real Tencent model wrapper (CUDA)
└── frontend/
    ├── index.html          # HUD layout
    ├── style.css           # streamer overlay + glitch FX
    ├── app.js              # input, chat sim, sanity EKG, mic
    └── favicon.ico
```

## Caveats

- The real HY-WorldPlay model is **temporally consistent only across a
  short horizon** — long sessions will drift. Periodically calling
  `/api/reset` (or just `R` in the frontend) is wise.
- The frontend's `prompt` field is capped at 240 chars to keep latency
  predictable on the GPU host.
- The Web Speech API requires HTTPS and an explicit user gesture
  (click "GO LIVE", then hold Space). On localhost it works in
  Chrome/Edge but not Firefox.
