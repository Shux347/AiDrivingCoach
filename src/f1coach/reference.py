"""Reference (personal-best) lap persistence.

Stores the extracted corner features of the best valid lap seen, keyed by
track name, as JSON in :data:`~f1coach.config.REFERENCE_LAP_DIR`. The delta
engine compares each new lap against this.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import List, Optional

from . import config
from .corners import Corner


def _path(track: str) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in track) or "default"
    return os.path.join(config.REFERENCE_LAP_DIR, f"ref_{safe}.json")


def save_reference(track: str, corners: List[Corner], lap_time_ms: int) -> None:
    os.makedirs(config.REFERENCE_LAP_DIR, exist_ok=True)
    payload = {
        "track": track,
        "lap_time_ms": lap_time_ms,
        "corners": [asdict(c) for c in corners],
    }
    # Atomic write: dump to a temp file in the same dir, then os.replace() over
    # the target so an interrupted write can never leave a corrupt reference.
    path = _path(track)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_reference(track: str) -> Optional[tuple[List[Corner], int]]:
    path = _path(track)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
        corners = [Corner(**c) for c in payload["corners"]]
        return corners, int(payload["lap_time_ms"])
    except Exception:
        return None
