"""F1 25 AI Driver Coach — a local telemetry-driven driving coach.

Reads live UDP telemetry from EA Sports F1 25, reduces each lap into
corner-by-corner performance features, compares against a reference lap,
and delivers punchy race-engineer feedback over TTS.
"""

__version__ = "0.1.0"
