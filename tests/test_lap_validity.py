"""Regression tests for lap-validity attribution across the lap boundary.

A lap the game counts as valid must not be flagged invalid, and an invalid lap
must not poison the following valid lap. See telemetry._on_lap_frame.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from f1coach import mock, packets
from f1coach.receiver import Frame
from f1coach.telemetry import TelemetryAggregator


def _lap_frame(agg, lap_num, dist, invalid=0, last_lap_time_ms=90000,
               total_distance=0.0, session_uid=0, overall_frame_id=0):
    pkt = mock.build_lap_data_packet(
        lap_distance=dist, current_lap_num=lap_num,
        current_lap_invalid=invalid, last_lap_time_ms=last_lap_time_ms,
        total_distance=total_distance,
    )
    hdr = packets.parse_header(pkt)
    agg.consume(Frame(session_time=0.0, session_uid=session_uid,
                      overall_frame_identifier=overall_frame_id,
                      lap=packets.parse_lap_data(pkt, hdr)))


def _telemetry_frame(agg):
    pkt = mock.build_car_telemetry_packet(speed=200, throttle=1.0, brake=0.0)
    hdr = packets.parse_header(pkt)
    agg.consume(Frame(session_time=0.0, telemetry=packets.parse_car_telemetry(pkt, hdr)))


def test_valid_lap_not_contaminated_by_new_lap_invalid():
    """Lap 1 is clean; the FIRST frame of lap 2 reports invalid=1 (e.g. an
    out-lap or a track-limit at the line). Lap 1 must stay VALID."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    for i in range(5):                       # lap 1, all valid
        _lap_frame(agg, 1, i * 100.0, invalid=0)
        _telemetry_frame(agg)
    # transition frame: lap number ticks to 2 AND carries invalid=1 (new lap)
    _lap_frame(agg, 2, 5.0, invalid=1)
    _telemetry_frame(agg)
    assert len(completed) == 1
    assert completed[0].lap_number == 1
    assert completed[0].invalid is False     # not contaminated


def test_invalid_lap_does_not_poison_next_valid_lap():
    """Lap 1 is invalid; the transition frame still carries the stale 1, but
    lap 2's own frames are clean. Lap 2 must be VALID."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    for i in range(4):                       # lap 1, invalidated
        _lap_frame(agg, 1, i * 100.0, invalid=1)
        _telemetry_frame(agg)
    # lap 2 transition frame carries the lagging stale 1 ...
    _lap_frame(agg, 2, 5.0, invalid=1)
    _telemetry_frame(agg)
    for i in range(1, 4):                     # ... but lap 2's own frames are clean
        _lap_frame(agg, 2, i * 100.0, invalid=0)
        _telemetry_frame(agg)
    _lap_frame(agg, 3, 5.0, invalid=0)        # finalise lap 2
    _telemetry_frame(agg)
    assert len(completed) == 2
    assert completed[0].lap_number == 1 and completed[0].invalid is True
    assert completed[1].lap_number == 2 and completed[1].invalid is False


def test_genuinely_invalid_lap_is_still_flagged():
    """A real mid-lap invalidation must still mark the lap invalid."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    _lap_frame(agg, 1, 0.0, invalid=0)
    _telemetry_frame(agg)
    _lap_frame(agg, 1, 200.0, invalid=1)      # went off track mid-lap
    _telemetry_frame(agg)
    _lap_frame(agg, 1, 400.0, invalid=1)      # sticky
    _telemetry_frame(agg)
    _lap_frame(agg, 2, 5.0, invalid=0)        # finalise lap 1
    _telemetry_frame(agg)
    assert len(completed) == 1
    assert completed[0].invalid is True


def test_restart_via_new_session_uid_clears_invalidation():
    """Invalidate a lap, then hit 'Restart Session' (new session UID, lap
    counter back to 1). The next clean lap must NOT inherit the invalidation,
    and the abandoned lap must never be finalised."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    # Lap 3 of session A — driver goes off track, lap is invalidated.
    for i in range(4):
        _lap_frame(agg, 3, i * 100.0, invalid=1,
                   total_distance=6000.0 + i * 100.0, session_uid=1)
        _telemetry_frame(agg)
    # "Restart Session": new UID, lap counter resets to 1, distance meter to ~0.
    for i in range(4):
        _lap_frame(agg, 1, i * 100.0, invalid=0,
                   total_distance=i * 100.0, session_uid=2)
        _telemetry_frame(agg)
    # Cross the S/F line into lap 2 to finalise the fresh lap 1.
    _lap_frame(agg, 2, 5.0, invalid=0, total_distance=800.0, session_uid=2)
    _telemetry_frame(agg)
    assert len(completed) == 1                       # abandoned lap 3 discarded
    assert completed[0].lap_number == 1
    assert completed[0].invalid is False             # pre-restart flag cleared


def test_restart_to_garage_same_session_clears_invalidation():
    """Same as above but the restart keeps the session UID (e.g. restart lap /
    return to garage). Detected by the lap counter rewinding while the
    session-distance meter resets toward the start."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    for i in range(4):
        _lap_frame(agg, 3, i * 100.0, invalid=1,
                   total_distance=6000.0 + i * 100.0, session_uid=7)
        _telemetry_frame(agg)
    for i in range(4):                               # lap counter 3 -> 1, dist -> ~0
        _lap_frame(agg, 1, i * 100.0, invalid=0,
                   total_distance=i * 100.0, session_uid=7)
        _telemetry_frame(agg)
    _lap_frame(agg, 2, 5.0, invalid=0, total_distance=800.0, session_uid=7)
    _telemetry_frame(agg)
    assert len(completed) == 1
    assert completed[0].lap_number == 1
    assert completed[0].invalid is False


def test_flashback_within_lap_is_not_a_restart():
    """A flashback (same UID, same lap, short distance rewind) must NOT be
    treated as a restart: a lap invalidated before the flashback stays invalid."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    _lap_frame(agg, 2, 0.0, invalid=0, total_distance=2000.0, session_uid=9)
    _telemetry_frame(agg)
    _lap_frame(agg, 2, 300.0, invalid=1, total_distance=2300.0, session_uid=9)  # off track
    _telemetry_frame(agg)
    # Flashback: rewind a short stretch — same lap, same UID, small distance drop.
    _lap_frame(agg, 2, 150.0, invalid=1, total_distance=2150.0, session_uid=9)
    _telemetry_frame(agg)
    _lap_frame(agg, 2, 400.0, invalid=1, total_distance=2400.0, session_uid=9)
    _telemetry_frame(agg)
    _lap_frame(agg, 3, 5.0, invalid=0, total_distance=2600.0, session_uid=9)   # finalise lap 2
    _telemetry_frame(agg)
    assert len(completed) == 1
    assert completed[0].lap_number == 2
    assert completed[0].invalid is True              # not wiped by the flashback


def test_rewind_same_lap_resyncs_validity():
    """The real-telemetry bug: mid-lap the driver goes off (invalid=1), then
    restarts/rewinds IN PLACE — same lap number, same session UID, only
    total_distance drops — and the game re-evaluates the lap as valid (sends
    m_currentLapInvalid=0 from there on). The completed lap must be VALID: our
    sticky latch must let go of the stale 1 on the rewind. Mirrors the captured
    trace (lapNum 17 frozen, uid constant, totalDist 95818 -> 93181)."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    _lap_frame(agg, 17, 1000.0, invalid=0, total_distance=94000.0, session_uid=999)
    _telemetry_frame(agg)
    _lap_frame(agg, 17, 1405.0, invalid=1, total_distance=95656.0, session_uid=999)  # off track
    _telemetry_frame(agg)
    _lap_frame(agg, 17, 1567.0, invalid=1, total_distance=95818.0, session_uid=999)  # still invalid
    _telemetry_frame(agg)
    # Restart in place: SAME lap number and UID, total_distance jumps backwards,
    # and the game now reports the lap as valid again.
    _lap_frame(agg, 17, 4820.0, invalid=0, total_distance=93181.0, session_uid=999)
    _telemetry_frame(agg)
    for d, td in [(4900.0, 93261.0), (5000.0, 93361.0)]:                # clean rest of lap
        _lap_frame(agg, 17, d, invalid=0, total_distance=td, session_uid=999)
        _telemetry_frame(agg)
    _lap_frame(agg, 18, 5.0, invalid=0, total_distance=93500.0, session_uid=999)  # finalise lap 17
    _telemetry_frame(agg)
    assert len(completed) == 1
    assert completed[0].lap_number == 17
    assert completed[0].invalid is False             # rewind cleared the stale strike


def test_rewind_that_keeps_the_strike_stays_invalid():
    """A rewind that does NOT wipe the invalidation (game keeps sending
    invalid=1 after the rewind) must leave the lap invalid — re-accumulation,
    not blind clearing."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    _lap_frame(agg, 5, 800.0, invalid=1, total_distance=40800.0, session_uid=3)   # off track
    _telemetry_frame(agg)
    _lap_frame(agg, 5, 1200.0, invalid=1, total_distance=41200.0, session_uid=3)
    _telemetry_frame(agg)
    # Rewind (distance drops) but the strike stands: game still reports invalid.
    _lap_frame(agg, 5, 600.0, invalid=1, total_distance=40600.0, session_uid=3)
    _telemetry_frame(agg)
    _lap_frame(agg, 5, 1000.0, invalid=1, total_distance=41000.0, session_uid=3)
    _telemetry_frame(agg)
    _lap_frame(agg, 6, 5.0, invalid=0, total_distance=41500.0, session_uid=3)      # finalise lap 5
    _telemetry_frame(agg)
    assert len(completed) == 1
    assert completed[0].lap_number == 5
    assert completed[0].invalid is True


def test_stale_reordered_frame_is_dropped():
    """A delayed pre-invalidation datagram (lower overall-frame id AND lower
    total_distance, reporting valid) arrives out of order after the lap was
    invalidated. Without the ordering guard it would masquerade as a rewind and
    clear the strike; the guard must DROP it and leave the lap invalid."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    _lap_frame(agg, 4, 800.0, invalid=0, total_distance=40800.0,
               session_uid=5, overall_frame_id=1000)
    _telemetry_frame(agg)
    _lap_frame(agg, 4, 1200.0, invalid=1, total_distance=41200.0,
               session_uid=5, overall_frame_id=1010)      # off track
    _telemetry_frame(agg)
    _lap_frame(agg, 4, 1400.0, invalid=1, total_distance=41400.0,
               session_uid=5, overall_frame_id=1020)
    _telemetry_frame(agg)
    # Reordered stale datagram: id BEHIND 1020, distance behind, reports valid.
    _lap_frame(agg, 4, 700.0, invalid=0, total_distance=40700.0,
               session_uid=5, overall_frame_id=1005)
    _telemetry_frame(agg)
    _lap_frame(agg, 5, 5.0, invalid=0, total_distance=41600.0,
               session_uid=5, overall_frame_id=1030)       # finalise lap 4
    _telemetry_frame(agg)
    assert len(completed) == 1
    assert completed[0].lap_number == 4
    assert completed[0].invalid is True                    # stale packet ignored


def test_genuine_rewind_with_climbing_overall_id_still_resyncs():
    """A real flashback/rewind drops total_distance but the overall-frame id
    KEEPS CLIMBING (confirmed on real F1 25 telemetry: 153486 -> 153489 ->
    153492 across a total_distance rewind). The guard must NOT drop it: the
    strike is re-evaluated and the lap ends valid."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    _lap_frame(agg, 19, 304.0, invalid=0, total_distance=106336.0,
               session_uid=42, overall_frame_id=153486)
    _telemetry_frame(agg)
    _lap_frame(agg, 19, 1400.0, invalid=1, total_distance=107400.0,
               session_uid=42, overall_frame_id=153489)    # off track
    _telemetry_frame(agg)
    # Rewind in place: total_distance drops, overall id still climbs, game valid.
    _lap_frame(agg, 19, 4820.0, invalid=0, total_distance=104962.0,
               session_uid=42, overall_frame_id=153492)
    _telemetry_frame(agg)
    _lap_frame(agg, 19, 4834.0, invalid=0, total_distance=104976.0,
               session_uid=42, overall_frame_id=153498)
    _telemetry_frame(agg)
    _lap_frame(agg, 20, 5.0, invalid=0, total_distance=105100.0,
               session_uid=42, overall_frame_id=153510)     # finalise lap 19
    _telemetry_frame(agg)
    assert len(completed) == 1
    assert completed[0].lap_number == 19
    assert completed[0].invalid is False                   # rewind cleared strike


def test_new_session_rebaselines_overall_id():
    """A new session resets m_overallFrameIdentifier to a small value. Its
    frames must NOT be dropped just because the prior session ended on a much
    larger id — the guard re-baselines across the session change."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    # Session A, deep into the race — large overall ids.
    for i in range(3):
        _lap_frame(agg, 30, 200.0 + i * 100, invalid=0,
                   total_distance=90000.0 + i * 100,
                   session_uid=100, overall_frame_id=200000 + i)
        _telemetry_frame(agg)
    # Restart: new UID, overall id resets small, lap counter back to 1.
    for i in range(3):
        _lap_frame(agg, 1, i * 100.0, invalid=0, total_distance=i * 100.0,
                   session_uid=200, overall_frame_id=50 + i)
        _telemetry_frame(agg)
    _lap_frame(agg, 2, 5.0, invalid=0, total_distance=400.0,
               session_uid=200, overall_frame_id=60)         # finalise lap 1
    _telemetry_frame(agg)
    assert len(completed) == 1                               # session-A lap discarded
    assert completed[0].lap_number == 1
    assert completed[0].invalid is False


def test_zero_id_frame_does_not_reopen_stale_guard():
    """A 0-id frame (no ordering info) must NOT drag the high-water mark down to
    0. If it did, a later genuinely-stale datagram (id below the real mark) would
    slip past the guard and wrongly clear the strike via the rewind branch. The
    mark is advanced only on nonzero ids, so the stale frame is still dropped."""
    completed = []
    agg = TelemetryAggregator(on_lap_complete=completed.append)
    _lap_frame(agg, 4, 800.0, invalid=0, total_distance=40800.0,
               session_uid=5, overall_frame_id=1000)
    _telemetry_frame(agg)
    _lap_frame(agg, 4, 1200.0, invalid=1, total_distance=41200.0,
               session_uid=5, overall_frame_id=1010)      # off track
    _telemetry_frame(agg)
    _lap_frame(agg, 4, 1400.0, invalid=1, total_distance=41400.0,
               session_uid=5, overall_frame_id=1020)
    _telemetry_frame(agg)
    # A 0-id frame is accepted (guard inert) but must not lower the mark to 0.
    _lap_frame(agg, 4, 1450.0, invalid=1, total_distance=41450.0,
               session_uid=5, overall_frame_id=0)
    _telemetry_frame(agg)
    # Now a genuinely stale datagram: id behind the real mark (1020), distance
    # behind, reports valid. Must still be dropped — not clear the strike.
    _lap_frame(agg, 4, 700.0, invalid=0, total_distance=40700.0,
               session_uid=5, overall_frame_id=1005)
    _telemetry_frame(agg)
    _lap_frame(agg, 5, 5.0, invalid=0, total_distance=41600.0,
               session_uid=5, overall_frame_id=1030)       # finalise lap 4
    _telemetry_frame(agg)
    assert len(completed) == 1
    assert completed[0].lap_number == 4
    assert completed[0].invalid is True                    # guard held despite 0-id frame


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
