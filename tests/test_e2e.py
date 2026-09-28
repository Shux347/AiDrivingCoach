"""End-to-end pipeline test (in-process, offline AI, TTS captured).

Drives the whole Coach: decode packets -> aggregate -> lap boundary ->
extract corners -> bank reference -> diff -> coach. No sockets, no network,
no audio; deterministic.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from f1coach import config, mock
from f1coach.receiver import UDPReceiver


def _run_pipeline():
    # isolate reference storage
    tmp = tempfile.mkdtemp()
    config.REFERENCE_LAP_DIR = tmp

    from f1coach.app import Coach

    coach = Coach(track="silverstone")
    coach.speaker.enabled = False
    spoken = []
    coach.speaker.say = spoken.append  # capture radio lines

    def feed(lap_num, **kwargs):
        for lap_pkt, tel_pkt, mex_pkt in mock.simulate_lap_packets(lap_num, **kwargs):
            for pkt in (lap_pkt, tel_pkt, mex_pkt):
                frame = UDPReceiver._decode(pkt)
                if frame is not None:
                    coach.aggregator.consume(frame)

    import queue as _queue

    def drain():
        # coaching thread isn't running in-process; process finalised laps here
        while True:
            try:
                lap = coach.lap_queue.get_nowait()
            except _queue.Empty:
                break
            coach._handle_completed_lap(lap)

    feed(1, last_lap_time_ms=90000)                     # clean reference
    drain()                                             # lap 1 not yet finalised
    feed(2, last_lap_time_ms=88000, brake_bias_m=-18.0, # sloppy lap; wire time = lap 1's
         apex_penalty_kmh=12.0, pickup_delay_m=22.0, exit_slip=0.4)
    drain()                                             # finalises + banks lap 1 (88.0s)
    feed(3, last_lap_time_ms=91500)                     # marker; wire time = lap 2's (slow)
    drain()                                             # coaches on lap 2

    return coach, spoken


def test_reference_banked_and_lap2_coached():
    coach, spoken = _run_pipeline()
    # reference lap was banked from lap 1
    assert coach.ref_corners is not None
    assert len(coach.ref_corners) == len(mock.DEMO_CORNERS)
    # lap 2 produced a coaching line
    assert len(spoken) >= 1
    advice = " ".join(spoken).lower()
    print("Radio said:", spoken)
    # offline advice should reference braking early (we biased brake -18m)
    assert "early" in advice or "turn" in advice
    # the sloppy lap 2 (91.5s) must NOT have overwritten the lap-1 reference (88.0s)
    assert coach.ref_lap_time_ms == 88000


def test_corner_count_matches_track():
    coach, _ = _run_pipeline()
    assert len(coach.ref_corners) == 3


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
