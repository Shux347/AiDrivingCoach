import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from f1coach.ai_coach import AICoach
from f1coach.corners import Corner, CornerDelta, best_corners


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


def test_best_corners_rank_real_improvements():
    deltas = [
        CornerDelta(
            corner_index=2,
            brake_point_delta=0.0,
            apex_speed_delta=8.0,
            throttle_pickup_delta=-6.0,
            exit_slip_delta=-0.15,
            current=_corner(2, 0.0, 8.0, -6.0, -0.15),
            reference=_corner(2, 0.0, 0.0, 0.0, 0.0),
        ),
        CornerDelta(
            corner_index=5,
            brake_point_delta=4.0,
            apex_speed_delta=-2.0,
            throttle_pickup_delta=2.0,
            exit_slip_delta=0.05,
            current=_corner(5, 4.0, -2.0, 2.0, 0.05),
            reference=_corner(5, 0.0, 0.0, 0.0, 0.0),
        ),
    ]

    ranked = best_corners(deltas, 2)
    assert [d.corner_index for d in ranked] == [2, 5]


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
    best = [
        CornerDelta(
            corner_index=7,
            brake_point_delta=1.0,
            apex_speed_delta=7.0,
            throttle_pickup_delta=-5.0,
            exit_slip_delta=-0.12,
            current=_corner(7, 1.0, 7.0, -5.0, -0.12),
            reference=_corner(7, 0.0, 0.0, 0.0, 0.0),
        )
    ]

    coach = AICoach(api_key="dummy-key")
    assert coach.online is False

    advice = coach.coach(worst, best)
    print(advice)

    lowered = advice.lower()
    assert "turn 1" in lowered
    assert "turn 4" in lowered
    assert "turn 7" in lowered
    assert "improvement" in lowered or "faster" in lowered or "earlier" in lowered
    assert "throttle" in lowered or "apex" in lowered or "brake" in lowered

    # Wheelspin guidance should not conflict with delayed-throttle coaching.
    assert "ease the throttle on exit" in lowered
    assert "feed the throttle earlier on exit" not in lowered


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
