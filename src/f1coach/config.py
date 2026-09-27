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

# ---------------------------------------------------------------------------
# Coaching behaviour
# ---------------------------------------------------------------------------
# How many of the worst corners to rank each lap.
WORST_CORNERS_TO_REPORT: int = 2
# Only coach on laps that were not invalidated.
COACH_ON_INVALID_LAPS: bool = os.getenv("F1COACH_COACH_INVALID", "0") == "1"

# ---------------------------------------------------------------------------
# AI (Gemini via google-genai)
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL: str = os.getenv("F1COACH_MODEL", "gemini-3.6-flash")
GEMINI_TEMPERATURE: float = float(os.getenv("F1COACH_TEMPERATURE", "0.7"))
GEMINI_MAX_OUTPUT_TOKENS: int = int(os.getenv("F1COACH_MAX_TOKENS", "200"))

SYSTEM_PROMPT: str = (
    "You are an expert F1 race engineer. You will receive telemetry deltas "
    "comparing the driver's last lap to their personal best. "
    "Respond with exactly two short, punchy sentences of advice meant to be "
    "read over the team radio. Do not use pleasantries. Be direct. "
    "Example: 'You braked 10 meters too early into Turn 4, which compromised "
    "your apex speed. Carry more speed in and wait for the car to rotate "
    "before applying full throttle.'"
)

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
