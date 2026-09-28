"""Tests for the aggregator, corner extraction and delta engine."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np

from f1coach import mock, packets
from f1coach.corners import compute_deltas, extract_corners, worst_corners
from f1coach.receiver import UDPReceiver
from f1coach.telemetry import Lap, LapSample, TelemetryAggregator


def _make_lap(lap_number=1, brake_point=300.0, apex_speed=120.0, pickup=360.0):
    """Synthesize a lap with a straight, one braking zone/corner, then a straight."""
    samples = []
    d = 0.0
    while d < 700.0:
        if d < brake_point:                      # flat-out approach
            speed, throttle, brake = 300.0, 1.0, 0.0
        elif d < apex_from(brake_point):         # braking, slowing to apex
            frac = (d - brake_point) / (apex_from(brake_point) - brake_point)
            speed = 300.0 - (300.0 - apex_speed) * frac
            throttle, brake = 0.0, 0.9
        elif d < pickup:                         # off brakes, near apex
            speed = apex_speed
            throttle, brake = 0.2, 0.0
        else:                                     # power down, accelerating
            speed = min(300.0, apex_speed + (d - pickup) * 2.0)
            throttle, brake = 0.9, 0.0
        rear_slip = 0.35 if pickup <= d < pickup + 20 else 0.02
        samples.append(LapSample(d, speed, throttle, brake, 0.0, 4, rear_slip, 0.03))
        d += 5.0
    return Lap(lap_number=lap_number, samples=samples)


def apex_from(brake_point):
    return brake_point + 40.0


def _assert_raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    raise AssertionError(f"Expected {exc_type.__name__} to be raised")


def test_extract_single_corner():
    lap = _make_lap()
    corners = extract_corners(lap)
    assert len(corners) == 1
    c = corners[0]
    assert abs(c.brake_point - 300.0) <= 5.0
    assert 115.0 <= c.apex_speed <= 125.0
    assert c.throttle_pickup >= c.apex_distance
    assert c.max_exit_slip > 0.3


def test_deltas_braked_earlier_and_slower():
    reference = extract_corners(_make_lap(brake_point=300.0, apex_speed=130.0, pickup=360.0))
    current = extract_corners(_make_lap(brake_point=285.0, apex_speed=120.0, pickup=375.0))
    deltas = compute_deltas(current, reference)
    assert len(deltas) == 1
    d = deltas[0]
    assert d.brake_point_delta < 0        # braked earlier
    assert d.apex_speed_delta < 0         # slower apex
    assert d.throttle_pickup_delta > 0    # later to throttle
    assert d.time_cost_proxy > 0
    assert worst_corners(deltas, 2)[0] is d


def test_aggregator_lap_boundary():
    """Feed frames through the aggregator; a lap-number increment finalises a lap."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)

    def feed_lap(lap_num, n=30, invalid=0):
        for i in range(n):
            d = i * 20.0
            lp = mock.build_lap_data_packet(
                lap_distance=d, current_lap_num=lap_num, current_lap_invalid=invalid,
                last_lap_time_ms=90000,
            )
            hdr = packets.parse_header(lp)
            from f1coach.receiver import Frame
            agg.consume(Frame(session_time=0.0, lap=packets.parse_lap_data(lp, hdr)))
            tp = mock.build_car_telemetry_packet(speed=200, throttle=1.0, brake=0.0)
            thdr = packets.parse_header(tp)
            agg.consume(Frame(session_time=0.0, telemetry=packets.parse_car_telemetry(tp, thdr)))

    feed_lap(1)
    feed_lap(2)  # increment finalises lap 1
    assert len(completed) == 1
    assert completed[0].lap_number == 1
    assert len(completed[0]) > 0


def test_receiver_decode_dispatch():
    pkt = mock.build_motion_ex_packet(rear_slip_ratio=0.5, front_slip_angle=0.1)
    frame = UDPReceiver._decode(pkt)
    assert frame is not None and frame.motion is not None
    assert abs(frame.motion.max_rear_slip_ratio - 0.5) < 1e-6


def test_trail_brake_lift_stays_one_corner():
    """A brief lift mid-braking must not split one corner into two."""
    samples = []
    d = 0.0
    while d < 700.0:
        if d < 300:
            speed, throttle, brake = 300.0, 1.0, 0.0
        elif d < 330:                      # initial braking
            speed, throttle, brake = 200.0, 0.0, 0.9
        elif d < 345:                      # momentary lift (brake dips), no throttle
            speed, throttle, brake = 150.0, 0.1, 0.0
        elif d < 360:                      # trail brake continues
            speed, throttle, brake = 120.0, 0.0, 0.6
        elif d < 400:
            speed, throttle, brake = 120.0, 0.2, 0.0
        else:
            speed, throttle, brake = min(300.0, 120.0 + (d - 400) * 2), 0.9, 0.0
        samples.append(LapSample(d, speed, throttle, brake, 0.0, 3, 0.02, 0.03))
        d += 5.0
    corners = extract_corners(Lap(lap_number=1, samples=samples))
    assert len(corners) == 1  # merged, not split


def test_bijective_matching_no_double_bind():
    """Two current corners must not both bind to a single reference corner."""
    from f1coach.corners import Corner
    ref = [Corner(1, 300.0, 340.0, 120.0, 360.0, 0.05, 3),
           Corner(2, 305.0, 345.0, 118.0, 365.0, 0.05, 3)]
    cur = [Corner(1, 304.0, 344.0, 110.0, 372.0, 0.4, 3),
           Corner(2, 306.0, 346.0, 108.0, 374.0, 0.4, 3)]
    deltas = compute_deltas(cur, ref)
    matched_refs = [d.reference.index for d in deltas]
    assert len(deltas) == 2
    assert len(set(matched_refs)) == 2  # each reference used at most once


def test_flashback_keeps_redrive():
    """On a lap-distance rewind, arrays() keeps the corrected re-drive samples."""
    samples = [
        LapSample(100.0, 250.0, 1.0, 0.0, 0.0, 5, 0.0, 0.0),   # first pass (bad)
        LapSample(110.0, 40.0, 0.0, 1.0, 0.0, 2, 0.0, 0.0),    # spun/aborted
        LapSample(100.0, 260.0, 1.0, 0.0, 0.0, 6, 0.0, 0.0),   # re-drive (good)
        LapSample(110.0, 265.0, 1.0, 0.0, 0.0, 6, 0.0, 0.0),
    ]
    cols = Lap(lap_number=1, samples=samples).arrays()
    # at distance 100 we should keep the re-drive speed (260), not the first (250)
    i = int(np.where(np.isclose(cols["distance"], 100.0))[0][0])
    assert cols["speed"][i] == 260.0


def test_standardise_corners_by_track_point():
    """Known corner positions should be reused across laps; only new track points append."""
    from f1coach.corners import Corner, standardise_corners

    known = [
        Corner(1, 300.0, 340.0, 118.0, 360.0, 0.08, 3),
        Corner(2, 610.0, 650.0, 116.0, 680.0, 0.09, 3),
    ]
    current = [
        Corner(1, 298.0, 338.0, 120.0, 359.0, 0.07, 3),
        Corner(2, 612.0, 652.0, 114.0, 682.0, 0.10, 3),
        Corner(3, 905.0, 945.0, 122.0, 980.0, 0.11, 4),
    ]

    standard = standardise_corners(current, known)
    assert [c.index for c in standard] == [1, 2, 3]
    assert [c.brake_point for c in standard] == [300.0, 610.0, 905.0]
    assert len(standard) == 3


def test_official_track_turn_count_is_used_for_known_tracks():
    """Official circuit turn counts should cap the number of track sectors used for feedback."""
    from f1coach.corners import Corner, standardise_corners
    from f1coach.config import TRACK_TURN_COUNTS

    assert TRACK_TURN_COUNTS["silverstone"] == 18
    assert TRACK_TURN_COUNTS["monaco"] == 19
    assert TRACK_TURN_COUNTS["australia"] == 14
    assert TRACK_TURN_COUNTS["saudi_arabia"] == 27
    assert TRACK_TURN_COUNTS["austria"] == 10
    assert TRACK_TURN_COUNTS["canada"] == 14
    assert TRACK_TURN_COUNTS["texas"] == 20
    assert TRACK_TURN_COUNTS["barcelona"] == 14
    assert TRACK_TURN_COUNTS["spa"] == 19
    assert TRACK_TURN_COUNTS["singapore"] == 19

    current = [Corner(i, 100.0 * i, 120.0 * i, 140.0, 150.0, 0.05, 3) for i in range(1, 25)]
    standard = standardise_corners(current, track_name="silverstone")
    assert len(standard) == 18
    assert standard[0].index == 1
    assert standard[-1].index == 18


def test_track_name_validation_is_strict_and_aliases_are_canonical():
    """Track recognition should be explicit, canonical and reject unknown values."""
    from f1coach import config

    original_track = os.environ.pop("F1COACH_TRACK", None)
    try:
        assert config.resolve_track_name("Silverstone") == "silverstone"
        assert config.resolve_track_name("SILVERSTONE CIRCUIT") == "silverstone"
        assert config.resolve_track_name("texas") == "texas"
        _assert_raises(ValueError, config.resolve_track_name, "auto")
        _assert_raises(ValueError, config.resolve_track_name, "demo")
        _assert_raises(ValueError, config.resolve_track_name, "")
    finally:
        if original_track is not None:
            os.environ["F1COACH_TRACK"] = original_track


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
