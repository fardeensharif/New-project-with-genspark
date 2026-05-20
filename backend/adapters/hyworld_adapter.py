"""
Real Tencent HY-WorldPlay / HY-World-2.0 adapter.

This module is import-guarded: it ONLY loads heavy deps (torch,
diffusers, the model weights) when actually instantiated. That way
the FastAPI app can still boot on a CPU-only machine and just refuse
to use the hyworld backend until you set WORLD_BACKEND=hyworld on a
proper GPU host.

------------------------------------------------------------------
DEPLOYMENT (GPU host, e.g. RunPod / Lambda Labs / your own A100/H100)
------------------------------------------------------------------
  1.  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
  2.  pip install diffusers transformers accelerate safetensors einops
  3.  pip install huggingface_hub
  4.  huggingface-cli login            # accept the model's license
  5.  Pull the weights (one of):
        git clone https://huggingface.co/tencent/HY-World-2.0  ./weights/HY-World-2.0
        # or, for the playable variant:
        git clone https://github.com/Tencent-Hunyuan/HY-WorldPlay && \
        bash HY-WorldPlay/scripts/download_weights.sh
  6.  export WORLD_BACKEND=hyworld
  7.  export HYWORLD_WEIGHTS=/abs/path/to/weights/HY-World-2.0
  8.  uvicorn server:app --host 0.0.0.0 --port 8000

The HF model card and the HY-WorldPlay repo currently expose an
inference helper roughly shaped like:

    from hyworldplay import WorldPlayPipeline
    pipe = WorldPlayPipeline.from_pretrained(weights_dir, torch_dtype=torch.bfloat16).to("cuda")
    frame = pipe.step(action=action, prompt=prompt, negative_prompt=neg)

Different upstream releases rename things slightly, so we wrap the
call in a try/except chain that walks the most common entry-point
names.  Update `_call_pipeline` if Tencent renames the API again.
"""
from __future__ import annotations

import io
import os
from typing import Optional


_DIRECTION_TO_ACTION = {
    "forward":   {"move": [0.0, 0.0,  1.0], "rotate": [0.0, 0.0]},
    "backward":  {"move": [0.0, 0.0, -1.0], "rotate": [0.0, 0.0]},
    "left":      {"move": [0.0, 0.0,  0.0], "rotate": [0.0, -0.1]},
    "right":     {"move": [0.0, 0.0,  0.0], "rotate": [0.0,  0.1]},
    "look_up":   {"move": [0.0, 0.0,  0.0], "rotate": [-0.08, 0.0]},
    "look_down": {"move": [0.0, 0.0,  0.0], "rotate": [ 0.08, 0.0]},
    "stop":      {"move": [0.0, 0.0,  0.0], "rotate": [0.0,   0.0]},
}


class HYWorldAdapter:
    def __init__(self):
        try:
            import torch  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "WORLD_BACKEND=hyworld requires torch + the Tencent HY-WorldPlay "
                "dependencies installed.  See backend/adapters/hyworld_adapter.py "
                "header for setup instructions."
            ) from e

        self.weights_dir = os.environ.get("HYWORLD_WEIGHTS", "./weights/HY-World-2.0")
        self._pipe = None
        self._lazy_init()

    def _lazy_init(self):
        import torch

        weights = self.weights_dir
        if not os.path.isdir(weights):
            raise RuntimeError(
                f"HYWORLD_WEIGHTS not found at {weights}. "
                "Download the Tencent HY-World-2.0 weights first."
            )

        # Try the shapes we've seen across upstream releases.
        last_err = None
        for loader in (
            self._try_load_worldplay,
            self._try_load_diffusers,
        ):
            try:
                self._pipe = loader(weights, torch)
                if self._pipe is not None:
                    break
            except Exception as e:  # pragma: no cover - depends on env
                last_err = e
        if self._pipe is None:
            raise RuntimeError(
                f"Could not load HY-WorldPlay pipeline from {weights}. "
                f"Last error: {last_err}"
            )

    @staticmethod
    def _try_load_worldplay(weights, torch):
        try:
            from hyworldplay import WorldPlayPipeline  # type: ignore
        except ImportError:
            return None
        return WorldPlayPipeline.from_pretrained(
            weights, torch_dtype=torch.bfloat16
        ).to("cuda")

    @staticmethod
    def _try_load_diffusers(weights, torch):
        try:
            from diffusers import DiffusionPipeline
        except ImportError:
            return None
        pipe = DiffusionPipeline.from_pretrained(
            weights, torch_dtype=torch.bfloat16, trust_remote_code=True
        )
        return pipe.to("cuda")

    # ------------------------------------------------------------------
    # public API (matches MockAdapter)
    # ------------------------------------------------------------------

    def reset(self):
        if hasattr(self._pipe, "reset"):
            self._pipe.reset()

    def step(self, direction: str, prompt: str, event: str = "none") -> bytes:
        action = _DIRECTION_TO_ACTION.get(direction, _DIRECTION_TO_ACTION["stop"])
        from .. import prompts
        prompt_pkg = prompts.build_prompt(prompt, direction, event)

        image = self._call_pipeline(action, prompt_pkg)
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=82)
        return buf.getvalue()

    def info(self) -> dict:
        return {
            "backend": "hyworld",
            "weights": self.weights_dir,
            "device": "cuda",
        }

    # ------------------------------------------------------------------

    def _call_pipeline(self, action: dict, prompt_pkg: dict):
        """Try the various method names upstream has used."""
        pipe = self._pipe
        kwargs = dict(
            prompt=prompt_pkg["prompt"],
            negative_prompt=prompt_pkg["negative_prompt"],
            action=action,
        )
        for method in ("step", "play_step", "generate_next", "__call__"):
            fn = getattr(pipe, method, None)
            if fn is None:
                continue
            try:
                out = fn(**kwargs)
            except TypeError:
                # older signature: (action, prompt)
                out = fn(action, prompt_pkg["prompt"])
            # normalize -> PIL.Image
            if hasattr(out, "images"):
                return out.images[0]
            if isinstance(out, list):
                return out[0]
            return out
        raise RuntimeError("HY-WorldPlay pipeline exposes no known step method.")
