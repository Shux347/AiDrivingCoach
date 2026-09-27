import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from f1coach.ai_coach import AICoach
from f1coach.corners import Corner, CornerDelta


def _corner(index: int, brake: float, apex: float, pickup: float, slip: float) -> Corner:
    return Corner(
        index=index,
        brake_point=100.0 + brake,
        apex_distance=140.0,
        apex_speed=220.0 + apex,
        throttle_pickup=260.0 + pickup,
        max_exit_slip=slip,
        min_gear=4,
    )


def test_coach_uses_ranked_corners_without_llm():
    worst = [
        CornerDelta(
            corner_index=1,
            brake_point_delta=-18.0,
            apex_speed_delta=-12.0,
            throttle_pickup_delta=16.0,
            exit_slip_delta=0.30,
            current=_corner(1, -18.0, -12.0, 16.0, 0.30),
            reference=_corner(1, 0.0, 0.0, 0.0, 0.0),
        ),
        CornerDelta(
            corner_index=4,
            brake_point_delta=8.0,
            apex_speed_delta=-6.0,
            throttle_pickup_delta=12.0,
            exit_slip_delta=0.20,
            current=_corner(4, 8.0, -6.0, 12.0, 0.20),
            reference=_corner(4, 0.0, 0.0, 0.0, 0.0),
        ),
    ]

    coach = AICoach(api_key="dummy-key")
    assert coach.online is False

    advice = coach.coach(worst)
    print(advice)

    sentences = [s.strip() for s in advice.split(".") if s.strip()]
    assert len(sentences) >= 2, f"Expected two deterministic coaching sentences, got: {advice!r}"
    lowered = advice.lower()
    assert "turn 1" in lowered
    assert "turn 4" in lowered
    assert "throttle" in lowered or "apex" in lowered or "brake" in lowered


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
