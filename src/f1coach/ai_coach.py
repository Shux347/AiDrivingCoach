"""Phase 4 — the AI coach (Gemini via the google-genai SDK).

Turns a handful of :class:`~f1coach.corners.CornerDelta` objects into a tight,
structured text summary and asks Gemini 2.5 Flash to reply with two punchy
race-engineer sentences.

The Gemini SDK is imported lazily so the rest of the pipeline (and the tests)
runs with no key and no ``google-genai`` installed. Set ``GEMINI_API_KEY`` to
use the live model; otherwise :class:`AICoach` falls back to a deterministic
offline generator so the end-to-end flow still works.
"""

from __future__ import annotations

from typing import Iterator, List, Optional

from . import config
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
# Offline fallback (no API key)
# ---------------------------------------------------------------------------
def _offline_advice(worst: List[CornerDelta]) -> str:
    if not worst:
        return "Clean lap, matched your best everywhere. Keep it exactly there."
    d = worst[0]
    bits: list[str] = []
    if d.brake_point_delta < -3:
        bits.append(f"braked {abs(d.brake_point_delta):.0f} meters too early into Turn {d.corner_index}")
    elif d.brake_point_delta > 3:
        bits.append(f"braked {d.brake_point_delta:.0f} meters late into Turn {d.corner_index}")
    if d.apex_speed_delta < -2:
        bits.append(f"lost {abs(d.apex_speed_delta):.0f} km/h at the apex")
    first = ("You " + ", ".join(bits) + ".") if bits else f"Turn {d.corner_index} cost you the most this lap."
    if d.throttle_pickup_delta > 3:
        second = "Get the car rotated sooner and feed the throttle earlier on exit."
    elif d.exit_slip_delta > 0.1:
        second = "Ease the throttle on exit — you're lighting up the rears and scrubbing speed."
    else:
        second = "Carry more entry speed and commit to the apex."
    return f"{first} {second}"


# ---------------------------------------------------------------------------
# The coach
# ---------------------------------------------------------------------------
class AICoach:
    """Wraps Gemini 2.5 Flash; degrades gracefully to offline advice."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        # Resolve config lazily (inside __init__), not as default-arg values, so
        # tests/runtime that set config.GEMINI_API_KEY after import are honoured.
        api_key = config.GEMINI_API_KEY if api_key is None else api_key
        self._model = config.GEMINI_MODEL if model is None else model
        self._client = None
        self._types = None
        self.online = False
        if api_key:
            try:
                import logging

                from google import genai
                from google.genai import types

                # The SDK logs an AFC (automatic function calling) advisory on
                # every generate_content call; we pass no tools, so silence it.
                logging.getLogger("google_genai").setLevel(logging.ERROR)

                self._client = genai.Client(api_key=api_key)
                self._types = types
                self.online = True
            except Exception as exc:  # pragma: no cover - depends on env
                print(f"[AICoach] Gemini unavailable ({exc}); using offline advice.")

    def _gen_config(self):
        # The Gemini Flash models are *thinking* models: thinking tokens count
        # against max_output_tokens, so a small cap can be fully consumed by
        # thinking, leaving zero visible text. Disable thinking for this
        # short-output task.
        kwargs = dict(
            system_instruction=config.SYSTEM_PROMPT,
            temperature=config.GEMINI_TEMPERATURE,
            max_output_tokens=config.GEMINI_MAX_OUTPUT_TOKENS,
        )
        try:
            kwargs["thinking_config"] = self._types.ThinkingConfig(thinking_budget=0)
        except Exception:  # older SDK without ThinkingConfig — cap is then enough
            pass
        return self._types.GenerateContentConfig(**kwargs)

    def coach(self, worst: List[CornerDelta]) -> str:
        """Return the full coaching line (blocking)."""
        prompt = format_deltas_to_prompt(worst)
        if not self.online:
            return _offline_advice(worst)
        try:
            resp = self._client.models.generate_content(
                model=self._model, contents=prompt, config=self._gen_config()
            )
            return (resp.text or "").strip() or _offline_advice(worst)
        except Exception as exc:  # pragma: no cover - network dependent
            print(f"[AICoach] generation failed ({exc}); using offline advice.")
            return _offline_advice(worst)

    def coach_stream(self, worst: List[CornerDelta]) -> Iterator[str]:
        """Yield the coaching line in chunks as the model produces them."""
        prompt = format_deltas_to_prompt(worst)
        if not self.online:
            yield _offline_advice(worst)
            return
        try:
            for chunk in self._client.models.generate_content_stream(
                model=self._model, contents=prompt, config=self._gen_config()
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as exc:  # pragma: no cover - network dependent
            print(f"[AICoach] stream failed ({exc}); using offline advice.")
            yield _offline_advice(worst)
