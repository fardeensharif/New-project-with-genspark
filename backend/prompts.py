"""
Horror prompt-injection layer.

Every prompt sent to HY-WorldPlay is sandwiched between a fixed
gothic/found-footage style prefix and a negative-prompt suffix so
the AI dream stays inside our nightmare, not a daytime tourist sim.
"""

# Master style anchor - prepended to every generation request.
STYLE_PREFIX = (
    "ultra-realistic gritty bodycam found-footage at 2 AM, "
    "narrow 15-foot visibility through dense charcoal-grey volumetric fog, "
    "decaying Victorian gothic city, damp cobblestone streets reflecting "
    "a sickly amber flickering streetlamp, peeling paint on rotting facades, "
    "shattered windows, rusted iron gates, oppressive darkness beyond view, "
    "faint film grain, slight chromatic aberration, smartphone night-mode noise, "
    "shaky handheld feel, extreme contrast between weak orange light and pitch black, "
)

# Negative prompt - what we never want to see.
NEGATIVE_PROMPT = (
    "daytime, sunny, bright, cheerful, cartoon, anime, clean, polished, "
    "modern skyscrapers, neon signs, crowds of people, video game UI, "
    "cel-shaded, low poly, watermark, text overlay, "
)

# Direction-specific motion conditioning.
DIRECTION_HINTS = {
    "forward":  "camera advances slowly down a misty alley, footsteps echoing",
    "backward": "camera retreats backwards, frame bobbing up and down with panicked steps",
    "left":     "camera pans hard left around a damp brick corner",
    "right":    "camera pans hard right around a damp brick corner",
    "look_up":  "camera tilts up toward a black gothic spire vanishing into fog",
    "look_down":"camera tilts down to wet cobblestones glistening in lamplight",
    "stop":     "camera holds still, slight handheld tremor, fog drifting past",
}

# Optional event injections (jump-scares etc.)
EVENT_INJECTIONS = {
    "figure": (
        "a pale faceless silhouette in tattered clothing manifests "
        "from the fog beneath a broken window, perfectly still, watching"
    ),
    "shadow": "a tall distorted humanoid shadow flickers across the brick wall",
    "child":  "a small Victorian child in a white dress stands motionless at the alley's end",
    "hand":   "a gaunt pale hand reaches out from a shattered window",
    "none":   "",
}


def build_prompt(user_prompt: str, direction: str, event: str = "none") -> dict:
    """Compose the full prompt object sent downstream."""
    direction_hint = DIRECTION_HINTS.get(direction, DIRECTION_HINTS["stop"])
    event_hint = EVENT_INJECTIONS.get(event, "")

    parts = [STYLE_PREFIX, direction_hint]
    if user_prompt:
        # Whatever the streamer whispered into the mic (sanitized).
        parts.append(user_prompt.strip().replace("\n", " ")[:240])
    if event_hint:
        parts.append(event_hint)

    return {
        "prompt": ", ".join(p for p in parts if p),
        "negative_prompt": NEGATIVE_PROMPT,
    }
