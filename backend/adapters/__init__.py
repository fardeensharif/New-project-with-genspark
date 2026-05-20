"""
Adapter layer for HY-WorldPlay world model.

Two implementations share the same `WorldAdapter` interface:

  * MockAdapter      - procedural PIL renderer, runs anywhere (CPU only).
                       Used for development + this no-GPU sandbox.
  * HYWorldAdapter   - real Tencent HY-WorldPlay / HY-World-2.0 wrapper.
                       Requires CUDA + ~40GB VRAM.  Activated when env
                       var WORLD_BACKEND=hyworld is set.

The frontend never knows which one is running.
"""
import os


def get_adapter():
    backend = os.environ.get("WORLD_BACKEND", "mock").lower()
    if backend == "hyworld":
        from .hyworld_adapter import HYWorldAdapter
        return HYWorldAdapter()
    from .mock_adapter import MockAdapter
    return MockAdapter()
