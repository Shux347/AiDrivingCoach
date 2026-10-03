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
        f"brake {'later' if d.brake_point_delta >= 0 else 'earlier'}",
        f"accelerate {'later' if d.throttle_pickup_delta >= 0 else 'earlier'}",
    ]
    if abs(d.exit_slip_delta) > 0.05:
        slip_word = "more" if d.exit_slip_delta > 0 else "less"
        parts.append(f"{slip_word} rear wheelspin on exit ({d.exit_slip_delta:+.2f})")
    label = f"Track turn {d.corner_index}"
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
        bits.append(f"braked {abs(d.brake_point_delta):.0f} m too early; brake later next time")
    elif d.brake_point_delta > 3:
        bits.append(f"braked {d.brake_point_delta:.0f} m too late; brake earlier next time")
    if d.throttle_pickup_delta > 3:
        bits.append("accelerated too late; accelerate earlier next time")
    elif d.throttle_pickup_delta < -3:
        bits.append("accelerated too early; accelerate later once the car is rotated")
    if d.exit_slip_delta > 0.1:
        bits.append("scrubbed speed with rear wheelspin")
    if not bits:
        bits.append("lost a small amount of time through the corner")
    return bits


def _corner_sentence(d: CornerDelta, intro: str) -> str:
    bits = _issue_bits(d)
    if len(bits) == 1:
        return f"{intro} {bits[0]}."
    body = ", ".join(bits[:-1]) + f", and {bits[-1]}"
    return f"{intro} {body}."


def _follow_up(d: CornerDelta) -> str:
    if d.exit_slip_delta > 0.12:
        return "Ease the throttle on exit and keep the rear tyres planted."
    if d.throttle_pickup_delta > 4:
        return "Get the car rotated sooner and accelerate earlier on exit."
    if d.brake_point_delta > 3:
        return "Brake a touch earlier, then commit to the throttle once the car is rotated."
    if d.brake_point_delta < -3:
        return "Brake later and release the brake smoothly as you turn in."
    return "Brake consistently, then accelerate as soon as the car is rotated."


def _merge_with_follow_up(sentence: str, action: str) -> str:
    """Combine an issue sentence with one action sentence while keeping total output to two sentences."""
    return sentence.rstrip(".") + f"; {action.rstrip('.')}."


def _improvement_bits(d: CornerDelta) -> list[str]:
    bits: list[str] = []
    if d.throttle_pickup_delta < -2:
        bits.append(f"accelerated {abs(d.throttle_pickup_delta):.0f} m earlier")
    if d.exit_slip_delta < -0.1:
        bits.append("kept the rear tyre planted on exit")
    if d.brake_point_delta > 3:
        bits.append(f"braked {d.brake_point_delta:.0f} m later")
    if not bits:
        bits.append("were cleaner through the corner than your reference")
    return bits


def _positive_corner_sentence(d: CornerDelta) -> str:
    bits = _improvement_bits(d)
    if len(bits) == 1:
        return f"Track turn {d.corner_index} was a clear improvement: {bits[0]}."
    body = ", ".join(bits[:-1]) + f", and {bits[-1]}"
    return f"Track turn {d.corner_index} was a clear improvement: {body}."


def _selected_changes(worst: List[CornerDelta], best: Optional[List[CornerDelta]] = None, max_changes: int = 3) -> List[CornerDelta]:
    """Pick the strongest reference-lap changes while keeping at least one positive improvement when it exists."""
    selected: List[CornerDelta] = []
    if best:
        selected.append(best[0])
    if worst:
        selected.extend(worst[: max(0, max_changes - len(selected))])
    if len(selected) < max_changes and best:
        for d in best[1:]:
            if len(selected) >= max_changes:
                break
            if d not in selected:
                selected.append(d)
    if len(selected) < max_changes and worst:
        for d in worst[len(selected) - (1 if best else 0):]:
            if len(selected) >= max_changes:
                break
            if d not in selected:
                selected.append(d)
    return selected[:max_changes]


def _offline_advice(worst: List[CornerDelta], best: Optional[List[CornerDelta]] = None) -> str:
    if not worst and not best:
        return "Clean lap, matched your best everywhere. Keep it exactly there."

    selected = _selected_changes(worst, best)
    if not selected:
        return "Clean lap, matched your best everywhere. Keep it exactly there."

    main_issue = worst[0] if worst else None
    if len(selected) == 1:
        d = selected[0]
        if best is not None and d in best:
            return f"{_positive_corner_sentence(d)} {_follow_up(d)}"
        return f"{_corner_sentence(d, f'Track turn {d.corner_index} cost you the most this lap')} {_follow_up(d)}"

    sentences: List[str] = []
    for d in selected:
        if best is not None and d in best:
            sentences.append(_positive_corner_sentence(d))
        elif main_issue is not None and d is main_issue:
            sentences.append(_corner_sentence(d, f"Track turn {d.corner_index} cost you the most this lap"))
        else:
            sentences.append(_corner_sentence(d, f"Track turn {d.corner_index} was the next change"))

    summary = " ".join(sentences)
    if main_issue is not None:
        summary = f"{summary} {_follow_up(main_issue)}"
    return summary


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

    def coach(self, worst: List[CornerDelta], best: Optional[List[CornerDelta]] = None) -> str:
        """Return the full coaching line using fixed rules, not an LLM."""
        return _offline_advice(worst, best)

    def coach_stream(self, worst: List[CornerDelta], best: Optional[List[CornerDelta]] = None) -> Iterator[str]:
        """Yield the full coaching line in one chunk."""
        yield self.coach(worst, best)
