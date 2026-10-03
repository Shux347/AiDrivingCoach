"""Central configuration for the F1 25 AI Driver Coach.

Values can be overridden via environment variables (see `.env.example`).
"""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv optional at runtime
    pass


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
UDP_BIND_IP: str = os.getenv("F1COACH_BIND_IP", "0.0.0.0")
UDP_PORT: int = int(os.getenv("F1COACH_PORT", "20777"))
# Largest real F1 25 packet is ~1460 bytes; 4096 leaves ample headroom and lets
# us detect truncation (a datagram arriving at exactly the buffer size).
UDP_BUFFER_SIZE: int = 4096

# The UDP packet format the parsers expect. F1 25 = 2025. If the game is set to
# a different format (2024/2023/…) the byte offsets differ and every field
# decodes to garbage, so the receiver flags a mismatch instead of coaching lies.
EXPECTED_UDP_FORMAT: int = int(os.getenv("F1COACH_EXPECTED_FORMAT", "2025"))

# ---------------------------------------------------------------------------
# Live heartbeat (connection diagnostic)
# ---------------------------------------------------------------------------
# A periodic one-line status showing sender IP, packet rate, per-id counts and
# live speed/distance — so you can confirm the PC is reaching this machine long
# before a lap completes. Set F1COACH_HEARTBEAT=0 to silence it.
HEARTBEAT_ENABLED: bool = os.getenv("F1COACH_HEARTBEAT", "1") == "1"
HEARTBEAT_INTERVAL: float = float(os.getenv("F1COACH_HEARTBEAT_INTERVAL", "2.5"))

# Print a per-transition trace of the raw lap-validity fields (lap number,
# session UID, lap/total distance, m_currentLapInvalid) plus every lap
# start/restart/finalise decision the aggregator makes. Use this to capture what
# the game actually sends across a restart when a valid lap is wrongly flagged.
DEBUG_VALIDITY: bool = os.getenv("F1COACH_DEBUG_VALIDITY", "0") == "1"

# ---------------------------------------------------------------------------
# Feature-engineering thresholds (see spec §4)
# ---------------------------------------------------------------------------
BRAKE_ON_THRESHOLD: float = 0.20   # m_brake > 0.20 marks the braking point
THROTTLE_ON_THRESHOLD: float = 0.50  # m_throttle > 0.50 marks throttle pick-up
# A braking event shorter than this (metres) is treated as noise, not a corner.
MIN_BRAKE_ZONE_METERS: float = 15.0
# Two braking bursts closer than this (metres), with no real throttle application
# between them, are merged into one corner (trail-braking lift, lockup correction).
CORNER_MERGE_GAP_METERS: float = 30.0
# A detected corner is considered the same physical turn as an existing track
# point if its braking point falls within this distance of the stored marker.
# Larger than the merge gap so we avoid splitting a real corner into two separate
# entries while still distinguishing adjacent bends/turns.
CORNER_CATALOG_MATCH_METERS: float = 45.0

# ---------------------------------------------------------------------------
# Coaching behaviour
# ---------------------------------------------------------------------------
# How many of the worst corners to rank each lap.
WORST_CORNERS_TO_REPORT: int = 2
# Only coach on laps that were not invalidated.
COACH_ON_INVALID_LAPS: bool = os.getenv("F1COACH_COACH_INVALID", "0") == "1"

# ---------------------------------------------------------------------------
# Text-to-speech
# ---------------------------------------------------------------------------
TTS_ENABLED: bool = os.getenv("F1COACH_TTS", "1") == "1"
TTS_VOICE: str = os.getenv("F1COACH_VOICE", "en-GB-RyanNeural")
TTS_RATE: str = os.getenv("F1COACH_TTS_RATE", "+8%")  # slightly urgent, radio-like
# "edge" (online, high quality) or "pyttsx3" (offline fallback)
TTS_ENGINE: str = os.getenv("F1COACH_TTS_ENGINE", "edge")

# ---------------------------------------------------------------------------
# Reference lap persistence
# ---------------------------------------------------------------------------
REFERENCE_LAP_DIR: str = os.getenv(
    "F1COACH_REF_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "reference_laps"),
)
LAP_CHART_DIR: str | None = os.getenv("F1COACH_LAP_CHART_DIR")

# Official turn counts for the current F1 25 circuit list.
# Values are based on the current FIA race-weekend layouts used at each venue.
TRACK_TURN_COUNTS: dict[str, int] = {
    "australia": 14,
    "bahrain": 15,
    "china": 16,
    "japan": 18,
    "saudi_arabia": 27,
    "miami": 19,
    "imola": 19,
    "monaco": 19,
    "canada": 14,
    "barcelona": 14,
    "austria": 10,
    "silverstone": 18,
    "spa": 19,
    "hungary": 14,
    "netherlands": 14,
    "monza": 11,
    "singapore": 19,
    "azerbaijan": 20,
    "texas": 20,
    "mexico": 17,
    "brazil": 15,
    "las_vegas": 17,
    "qatar": 16,
    "abu_dhabi": 16,
}
VALID_TRACKS: frozenset[str] = frozenset(TRACK_TURN_COUNTS)
ALIASES: dict[str, str] = {
    "albert_park": "australia",
    "australia": "australia",
    "bahrain": "bahrain",
    "bahrain_international_circuit": "bahrain",
    "china": "china",
    "shanghai": "china",
    "japan": "japan",
    "suzuka": "japan",
    "saudi_arabia": "saudi_arabia",
    "jeddah": "saudi_arabia",
    "miami": "miami",
    "miami_international_autodrome": "miami",
    "imola": "imola",
    "autodromo_enzo_e_dino_ferrari": "imola",
    "monaco": "monaco",
    "monaco_circuit": "monaco",
    "canada": "canada",
    "circuit_gilles_villeneuve": "canada",
    "barcelona": "barcelona",
    "catalunya": "barcelona",
    "barcelona_catalunya": "barcelona",
    "circuit_de_barcelona_catalunya": "barcelona",
    "austria": "austria",
    "red_bull_ring": "austria",
    "silverstone": "silverstone",
    "silverstone_circuit": "silverstone",
    "silverstonegp": "silverstone",
    "spa": "spa",
    "spa_francorchamps": "spa",
    "spafrancorchamps": "spa",
    "hungary": "hungary",
    "hungaroring": "hungary",
    "netherlands": "netherlands",
    "zandvoort": "netherlands",
    "monza": "monza",
    "italy": "monza",
    "singapore": "singapore",
    "marina_bay": "singapore",
    "azerbaijan": "azerbaijan",
    "baku": "azerbaijan",
    "texas": "texas",
    "cota": "texas",
    "circuit_of_the_americas": "texas",
    "mexico": "mexico",
    "rodriguez": "mexico",
    "brazil": "brazil",
    "interlagos": "brazil",
    "las_vegas": "las_vegas",
    "vegas": "las_vegas",
    "las_vegas_strip_circuit": "las_vegas",
    "qatar": "qatar",
    "lusail": "qatar",
    "abu_dhabi": "abu_dhabi",
    "yas_marina": "abu_dhabi",
}


def _normalise_track_key(track_name: str | None) -> str:
    if not track_name:
        return ""
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in track_name).strip("_")


def official_turn_count(track_name: str | None) -> int | None:
    """Return the official FIA turn count for a known track, or None if unknown."""
    key = _normalise_track_key(track_name)
    if not key:
        return None
    for candidate in (
        key,
        key.replace("_circuit", ""),
        key.replace("_grand_prix", ""),
        key.replace("_gp", ""),
        key.replace("_international", ""),
    ):
        if candidate in TRACK_TURN_COUNTS:
            return TRACK_TURN_COUNTS[candidate]
    return None


def resolve_track_name(track_name: str | None) -> str:
    """Canonicalise a user-supplied track name and validate it against the F1 25 list."""
    env_name = os.getenv("F1COACH_TRACK")
    candidate = env_name if env_name else track_name
    key = _normalise_track_key(candidate)

    if not key or key in {"auto", "default", "none"}:
        raise ValueError(
            "Missing --track. Choose one of: "
            + ", ".join(sorted(VALID_TRACKS))
        )

    resolved = ALIASES.get(key, key)
    if resolved not in VALID_TRACKS:
        raise ValueError(
            f"Unknown track '{candidate}'. Choose one of: "
            + ", ".join(sorted(VALID_TRACKS))
        )
    return resolved
