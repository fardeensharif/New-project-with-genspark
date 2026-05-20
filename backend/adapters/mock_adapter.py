"""
Procedural gothic-bodycam frame generator.

Stands in for the real HY-WorldPlay model when no GPU is available.
Renders 768x432 JPEG frames featuring:
  - damp cobblestone street receding in perspective
  - decaying Victorian buildings on left/right with broken windows
  - flickering amber streetlamp halo
  - heavy charcoal fog limiting visibility to ~15 ft
  - optional pale faceless figure for jump-scare events
  - per-frame grain, AI-dream edge warp, vignette, scanlines

State is kept across frames so "forward" actually moves you forward,
"left/right" pans, etc.  The render order matters: we paint a
properly-lit scene FIRST, then mix in fog using lightness modulation
(not by drowning the whole frame in grey).
"""
from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageChops


W, H = 768, 432
HORIZON = int(H * 0.55)


@dataclass
class CameraState:
    z: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0
    bob: float = 0.0
    lamp_phase: float = 0.0
    seed: int = 1337
    last_event: str = "none"
    event_age: int = 999


def _hex(c):
    return tuple(int(c[i:i+2], 16) for i in (1, 3, 5))


COBBLE_DARK = _hex("#2a221c")
COBBLE_MID  = _hex("#3d342a")
COBBLE_WET  = _hex("#544638")
BRICK_DARK  = _hex("#3a241c")
BRICK_RED   = _hex("#7a3a26")
LAMP_AMBER  = _hex("#ffc060")
SKY         = _hex("#15161c")
FOG         = _hex("#2c2e34")
PALE_FLESH  = _hex("#e6d5c2")


# ----------------------------------------------------------------------
# Scene primitives (painted with realistic lighting BEFORE fog)
# ----------------------------------------------------------------------

def _paint_sky(draw, cam):
    """Murky charcoal sky with a hint of orange sodium-lamp glow."""
    for y in range(HORIZON):
        t = y / HORIZON
        # darker at top, slight warm tint near horizon
        r = int(SKY[0] + (28 - SKY[0]) * t)
        g = int(SKY[1] + (22 - SKY[1]) * t)
        b = int(SKY[2] + (26 - SKY[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))


def _paint_cobblestones(draw, cam):
    """Cobblestones in perspective, brighter at the horizon (where the lamp lights them)."""
    rng = random.Random(cam.seed ^ 0xC0BB1E)
    for row in range(30):
        t = row / 30.0
        y      = HORIZON + int((H - HORIZON) * (t ** 1.6))
        y_next = HORIZON + int((H - HORIZON) * (((row + 1) / 30.0) ** 1.6))
        if y_next <= y:
            continue
        stone_w = max(6, int(8 + 60 * t))
        offset = int((cam.z * (8 + 80 * t)) % stone_w)

        # closer to camera = darker (we're standing in shadow)
        # closer to horizon = brighter (the lamp is back there)
        light = 0.45 + 0.55 * (1 - t)   # 1.0 near horizon, 0.45 near feet
        for x in range(-stone_w, W + stone_w, stone_w):
            sx = x - offset
            base = COBBLE_MID if (row + (sx // stone_w)) % 2 == 0 else COBBLE_DARK
            if rng.random() < 0.22:
                base = COBBLE_WET
            shade = tuple(int(c * light) for c in base)
            draw.rectangle([sx, y, sx + stone_w - 1, y_next - 1], fill=shade)
            # wet sheen on top edge
            if rng.random() < 0.35:
                sheen = tuple(int(c * light * 1.7 + 12) for c in base)
                draw.line([sx + 1, y, sx + stone_w - 2, y], fill=sheen)


def _paint_buildings(draw, cam):
    """Decaying Victorian facades framing the alley."""
    pan = int(math.sin(cam.yaw) * 180)

    for side in (-1, 1):  # -1 left, +1 right
        for i in range(7):
            t = i / 7.0
            # outer edge = screen edge, inner edge marches toward vanishing point
            if side == -1:
                x_outer = int(-pan + (-50 + 280 * t))
                x_inner = int(-pan + (40 + 320 * t))
            else:
                x_outer = int(W - pan - (-50 + 280 * t))
                x_inner = int(W - pan - (40 + 320 * t))

            y_top = int(HORIZON - (1 - t) * (HORIZON - 20))
            y_bot = int(HORIZON + (1 - t) * (H - HORIZON))

            # closer building = darker (more in foreground shadow)
            light = 0.35 + 0.65 * t
            r = int(BRICK_DARK[0] + (BRICK_RED[0] - BRICK_DARK[0]) * t)
            g = int(BRICK_DARK[1] + (BRICK_RED[1] - BRICK_DARK[1]) * t)
            b = int(BRICK_DARK[2] + (BRICK_RED[2] - BRICK_DARK[2]) * t)
            shade = (int(r * light * 1.3), int(g * light * 1.3), int(b * light * 1.3))

            pts = [(x_outer, y_top), (x_inner, y_top),
                   (x_inner, y_bot), (x_outer, y_bot)]
            draw.polygon(pts, fill=shade)

            # mortar lines (horizontal)
            mortar = tuple(max(0, c - 18) for c in shade)
            n_lines = 6
            for k in range(1, n_lines):
                ly = y_top + (y_bot - y_top) * k // n_lines
                # only draw if visible width is reasonable
                if abs(x_inner - x_outer) > 6:
                    draw.line([(min(x_outer, x_inner), ly),
                               (max(x_outer, x_inner), ly)], fill=mortar)

            # broken windows
            if i < 5 and (i + int(cam.z) // 4 + (0 if side < 0 else 1)) % 2 == 0:
                wx = (x_outer + x_inner) // 2
                ww = max(8, int(abs(x_inner - x_outer) * 0.35))
                wh = max(12, int((y_bot - y_top) * 0.18))
                wy = y_top + (y_bot - y_top) // 3
                draw.rectangle([wx - ww//2, wy, wx + ww//2, wy + wh], fill=(6, 6, 9))
                # cracked glass
                crack = (60, 55, 50)
                draw.line([wx - ww//2 + 1, wy + 2, wx + ww//2 - 1, wy + wh - 2], fill=crack)
                draw.line([wx + ww//2 - 1, wy + 2, wx - ww//2 + 1, wy + wh - 2], fill=crack)


def _paint_streetlamp(img, draw, cam):
    """The flickering amber streetlamp at the end of the alley."""
    cx = W // 2 + int(math.sin(cam.yaw) * 30)
    cy = HORIZON - 15

    # flicker factor
    flicker = 0.6 + 0.4 * (math.sin(cam.lamp_phase * 2.3) ** 2)
    if random.random() < 0.05:
        flicker *= 0.4

    # warm halo - additive glow on top of scene
    halo = Image.new("RGB", (W, H), (0, 0, 0))
    hd = ImageDraw.Draw(halo)
    for r in range(260, 12, -8):
        # intensity falls off with radius
        falloff = (1 - r / 260) ** 1.6
        i = falloff * flicker
        col = (int(LAMP_AMBER[0] * i),
               int(LAMP_AMBER[1] * i * 0.85),
               int(LAMP_AMBER[2] * i * 0.45))
        hd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    halo = halo.filter(ImageFilter.GaussianBlur(14))
    # additive blend
    img_rgb = img.convert("RGB") if img.mode != "RGB" else img
    blended = ImageChops.add(img_rgb, halo, scale=1.0)
    img.paste(blended)

    # lamp post + bulb (re-paint on top)
    draw.line([(cx, cy), (cx, cy + 80)], fill=(14, 12, 10), width=3)
    bulb = (min(255, int(LAMP_AMBER[0] * flicker * 1.3)),
            min(255, int(LAMP_AMBER[1] * flicker * 1.1)),
            min(255, int(LAMP_AMBER[2] * flicker * 0.7)))
    draw.ellipse([cx - 8, cy - 12, cx + 8, cy + 4], fill=bulb)
    # bulb halo direct
    draw.ellipse([cx - 14, cy - 18, cx + 14, cy + 10],
                 outline=(int(bulb[0]*0.5), int(bulb[1]*0.4), int(bulb[2]*0.2)))


def _paint_event_figure(draw, cam):
    """The pale faceless silhouette."""
    if cam.last_event != "figure" or cam.event_age > 60:
        return
    age = cam.event_age
    alpha_t = min(1.0, age / 6.0)

    # offset slightly so we see it just off-center
    fx = W // 2 + int(math.sin(cam.yaw + 0.5) * 60) - 18
    fy = int(H * 0.46)
    fw = 36
    fh = 110

    # long dark coat
    coat = (10, 8, 8)
    draw.rectangle([fx, fy + 30, fx + fw, fy + fh], fill=coat)
    # tattered hem
    for i in range(7):
        draw.polygon(
            [(fx + i*5, fy + fh),
             (fx + i*5 + 3, fy + fh + 8 + (i % 3) * 2),
             (fx + i*5 + 5, fy + fh)],
            fill=coat,
        )
    # shoulders
    draw.polygon(
        [(fx - 4, fy + 32), (fx + fw + 4, fy + 32),
         (fx + fw, fy + 38), (fx, fy + 38)],
        fill=coat,
    )
    # head - pale, faceless, lit by the lamp
    head_color = tuple(int(c * (0.4 + 0.6 * alpha_t)) for c in PALE_FLESH)
    draw.ellipse([fx + fw//2 - 11, fy + 8, fx + fw//2 + 11, fy + 34],
                 fill=head_color)
    # subtle shadow under chin
    draw.ellipse([fx + fw//2 - 8, fy + 28, fx + fw//2 + 8, fy + 36],
                 fill=tuple(int(c * 0.6) for c in head_color))


# ----------------------------------------------------------------------
# Post-FX (fog, grain, AI-dream warp, vignette)
# ----------------------------------------------------------------------

def _apply_fog(img, cam):
    """
    Heavy charcoal fog that ATTENUATES the scene toward distance.
    Instead of a black mask that hides everything, we blend the
    image toward FOG colour based on depth (top-of-frame and screen
    edges).  Closer center stays visible, far away dissolves.
    """
    # build a depth-ish map: brightest near bottom-center (close),
    # darkest near horizon + edges (far).
    depth = Image.new("L", (W, H), 0)
    dd = ImageDraw.Draw(depth)
    cx = W // 2 + int(math.sin(cam.yaw) * 30)
    cy = int(H * 0.85)
    max_r = int(math.hypot(W, H) * 0.95)
    for r in range(max_r, 12, -6):
        # 0 = transparent (scene shows), 255 = solid fog
        # Use slower power so middle distance stays partially visible
        t = r / max_r
        v = int(255 * (t ** 2.2))
        dd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=v)
    depth = depth.filter(ImageFilter.GaussianBlur(34))

    fog_layer = Image.new("RGB", (W, H), FOG)
    # composite(img, fog, depth) -> where depth white we keep img,
    # where depth black we use fog.  We want the opposite: dark =
    # foreground stays, bright = fog wins.  Use composite the other way.
    out = Image.composite(fog_layer, img.convert("RGB"), depth)
    return out


def _apply_warp_and_grain(img, cam):
    """Subtle AI-dream horizontal shear + film grain."""
    # Edge warp: stronger during yaw / right after a scare
    warp_amt = 1 + int(abs(cam.yaw) * 18) + max(0, 5 - cam.event_age)
    if warp_amt > 1:
        warped = img.copy()
        rng = random.Random(int(cam.z * 100) ^ cam.seed)
        for y in range(0, H, 6):
            dx = int(math.sin(y * 0.045 + cam.lamp_phase * 0.6) * warp_amt * 0.5)
            slice_ = img.crop((0, y, W, y + 6))
            warped.paste(slice_, (dx, y))
        img = warped

    # film grain
    grain = Image.effect_noise((W, H), 16).convert("RGB")
    img = ImageChops.add(img, grain, scale=10.0)

    # gentle vignette - darken corners ~40%, not full black
    vign = Image.new("L", (W, H), 255)
    vd = ImageDraw.Draw(vign)
    max_r = int(math.hypot(W, H) * 0.55)
    for r in range(max_r, 0, -6):
        v = int(255 - 110 * (1 - r / max_r) ** 2)
        vd.ellipse([W//2 - r, H//2 - r, W//2 + r, H//2 + r], fill=v)
    vign = vign.filter(ImageFilter.GaussianBlur(40))
    dark = Image.new("RGB", (W, H), (8, 8, 10))
    img = Image.composite(img, dark, vign)
    return img


# ----------------------------------------------------------------------
# Adapter
# ----------------------------------------------------------------------

class MockAdapter:
    def __init__(self):
        self.cam = CameraState()

    def reset(self):
        self.cam = CameraState()

    def info(self):
        return {
            "backend": "mock",
            "resolution": [W, H],
            "note": "Procedural PIL stand-in. Set WORLD_BACKEND=hyworld on a GPU host to use the real Tencent model.",
        }

    def step(self, direction: str, prompt: str, event: str = "none") -> bytes:
        self._update(direction, event)
        frame = self._render()
        buf = io.BytesIO()
        frame.save(buf, format="JPEG", quality=80)
        return buf.getvalue()

    # ------------------------------------------------------------------

    def _update(self, direction, event):
        c = self.cam
        c.lamp_phase += 0.35
        c.event_age += 1

        if direction == "forward":
            c.z += 0.7
            c.bob += 0.5
        elif direction == "backward":
            c.z -= 0.5
            c.bob += 0.7
        elif direction == "left":
            c.yaw -= 0.08
        elif direction == "right":
            c.yaw += 0.08
        elif direction == "look_up":
            c.pitch -= 0.05
        elif direction == "look_down":
            c.pitch += 0.05

        c.yaw = max(-0.8, min(0.8, c.yaw))

        if event and event != "none":
            c.last_event = event
            c.event_age = 0

    def _render(self):
        img = Image.new("RGB", (W, H), SKY)
        draw = ImageDraw.Draw(img)

        # 1. base scene, fully lit
        _paint_sky(draw, self.cam)
        _paint_buildings(draw, self.cam)
        _paint_cobblestones(draw, self.cam)
        _paint_streetlamp(img, draw, self.cam)
        _paint_event_figure(draw, self.cam)

        # 2. fog attenuation
        img = _apply_fog(img, self.cam)

        # 3. grain + warp + vignette
        img = _apply_warp_and_grain(img, self.cam)

        # 4. camera bob
        bob_dy = int(math.sin(self.cam.bob) * 3)
        if bob_dy:
            shifted = Image.new("RGB", (W, H), (0, 0, 0))
            shifted.paste(img, (0, bob_dy))
            img = shifted

        return img
