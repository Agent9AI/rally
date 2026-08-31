"""Deterministic boundary between model coordination and Rally policy."""

from __future__ import annotations

import json
import os
from typing import Any


def build_handoff(task: str) -> dict[str, Any]:
    """Create a transport-safe handoff envelope for the Rally runner."""
    clean = " ".join((task or "").split())
    if not clean:
        raise ValueError("task must not be empty")
    return {
        "task": clean,
        "source": "google-adk",
        "policy": {
            "requires_independent_verification": True,
            "max_turns": int(os.getenv("RALLY_MAX_TURNS", "12")),
        },
    }


def handoff_to_rally(task: str) -> str:
    """Return a bounded, machine-readable handoff for the Rally runner."""
    return json.dumps(build_handoff(task), separators=(",", ":"))
