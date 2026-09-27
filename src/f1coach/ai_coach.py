"""Phase 4 — the deterministic driving coach.

Turns a handful of :class:`~f1coach.corners.CornerDelta` objects into a short,
structured coaching message using fixed rules and weighted thresholds instead of
any external model.
"""

from __future__ import annotations

from typing import Iterator, List, Optional

from .corners import CornerDelta


# ---------------------------------------------------------------------------
# Delta -> prompt text
# ---------------------------------------------------------------------------
def _fmt_signed(value: float, unit: str, pos_word: str, neg_word: str, ndigits: int = 0) -> str:
    """e.g. (-15, 'm', 'later', 'earlier') -> '15m earlier'."""
    mag = abs(round(value, ndigits))
    if ndigits == 0:
        mag = int(mag)
    word = pos_word if value >= 0 else neg_word
    return f"{mag}{unit} {word}"


def describe_delta(d: CornerDelta) -> str:
    """One bullet line summarising a corner's deltas vs. the reference lap."""
    parts = [
        f"braking point {_fmt_signed(d.brake_point_delta, 'm', 'later', 'earlier')}",
        f"apex speed {_fmt_signed(d.apex_speed_delta, ' km/h', 'faster', 'slower')}",
        f"back to throttle {_fmt_signed(d.throttle_pickup_delta, 'm', 'later', 'earlier')}",
    ]
    if abs(d.exit_slip_delta) > 0.05:
        slip_word = "more" if d.exit_slip_delta > 0 else "less"
        parts.append(f"{slip_word} rear wheelspin on exit ({d.exit_slip_delta:+.2f})")
    label = f"Turn {d.corner_index}"
    return f"- {label} (~{d.current.brake_point:.0f} m): " + "; ".join(parts)


def format_deltas_to_prompt(worst: List[CornerDelta]) -> str:
    """Build the user-message text summarising the worst corners of the lap."""
    if not worst:
        return "The lap closely matched the reference across all corners. No major deltas."
    lines = [
        "Telemetry deltas vs. personal best (negative time-lost values already ranked worst-first):",
    ]
    lines.extend(describe_delta(d) for d in worst)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Purely mathematical, deterministic coaching logic (no LLM / no API)
# ---------------------------------------------------------------------------
def _issue_bits(d: CornerDelta) -> list[str]:
    bits: list[str] = []
    if d.brake_point_delta < -3:
        bits.append(f"braked {abs(d.brake_point_delta):.0f} m too early")
    elif d.brake_point_delta > 3:
        bits.append(f"braked {d.brake_point_delta:.0f} m too late")
    if d.apex_speed_delta < -2:
        bits.append(f"lost {abs(d.apex_speed_delta):.0f} km/h at the apex")
    if d.throttle_pickup_delta > 3:
        bits.append(f"returned to throttle {d.throttle_pickup_delta:.0f} m too late")
    if d.exit_slip_delta > 0.1:
        bits.append("scrubbed speed with rear wheelspin")
    if not bits:
        bits.append("carried a little too much speed through the entry")
    return bits


def _corner_sentence(d: CornerDelta, intro: str) -> str:
    bits = _issue_bits(d)
    if len(bits) == 1:
        return f"{intro} {bits[0]}."
    body = ", ".join(bits[:-1]) + f", and {bits[-1]}"
    return f"{intro} {body}."


def _follow_up(d: CornerDelta) -> str:
    if d.throttle_pickup_delta > 4:
        return "Get the car rotated sooner and feed the throttle earlier on exit."
    if d.apex_speed_delta < -2:
        return "Carry more entry speed and wait for the car to rotate before applying full throttle."
    if d.exit_slip_delta > 0.12:
        return "Ease the throttle on exit and keep the rear tyres planted."
    if d.brake_point_delta > 3:
        return "Brake a touch earlier and commit to the apex without lifting late."
    return "Carry more speed in and keep a stable line through the middle of the corner."


def _offline_advice(worst: List[CornerDelta]) -> str:
    if not worst:
        return "Clean lap, matched your best everywhere. Keep it exactly there."
    if len(worst) == 1:
        d = worst[0]
        first = _corner_sentence(d, f"Turn {d.corner_index} cost you the most this lap")
        return f"{first} {_follow_up(d)}"

    primary = worst[0]
    secondary = worst[1]
    first = _corner_sentence(primary, f"Turn {primary.corner_index} cost you the most this lap")
    second = _corner_sentence(secondary, f"Turn {secondary.corner_index} was the next issue")
    return f"{first} {second} {_follow_up(primary)}"


# ---------------------------------------------------------------------------
# The coach
# ---------------------------------------------------------------------------
class AICoach:
    """Deterministic, purely mathematical race-engineer advice."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.online = False

    def coach(self, worst: List[CornerDelta]) -> str:
        """Return the full coaching line using fixed rules, not an LLM."""
        return _offline_advice(worst)

    def coach_stream(self, worst: List[CornerDelta]) -> Iterator[str]:
        """Yield the full coaching line in one chunk."""
        yield self.coach(worst)
