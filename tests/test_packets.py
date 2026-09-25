"""Round-trip tests: build a synthetic packet, parse it, assert values survive."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from f1coach import mock, packets


def test_header_size():
    assert packets.HEADER_SIZE == 29


def test_entry_sizes():
    assert packets.TELEMETRY_ENTRY_SIZE == 60
    assert packets.LAPDATA_ENTRY_SIZE == 57
    assert packets.MOTIONEX_BODY_SIZE == 244


def test_telemetry_roundtrip():
    pkt = mock.build_car_telemetry_packet(
        speed=287, throttle=0.95, brake=0.0, steer=-0.1, gear=7, player_car_index=3
    )
    header = packets.parse_header(pkt)
    assert header is not None
    assert header.packet_id == packets.PACKET_ID_CAR_TELEMETRY
    assert header.player_car_index == 3
    tel = packets.parse_car_telemetry(pkt, header)
    assert tel is not None
    assert tel.speed == 287
    assert abs(tel.throttle - 0.95) < 1e-6
    assert tel.brake == 0.0
    assert tel.gear == 7


def test_lap_data_roundtrip():
    pkt = mock.build_lap_data_packet(
        lap_distance=1234.5, current_lap_num=4, sector=1, current_lap_invalid=0
    )
    header = packets.parse_header(pkt)
    assert header.packet_id == packets.PACKET_ID_LAP_DATA
    lap = packets.parse_lap_data(pkt, header)
    assert lap is not None
    assert abs(lap.lap_distance - 1234.5) < 1e-3
    assert lap.current_lap_num == 4
    assert lap.sector == 1
    assert lap.current_lap_invalid == 0


def test_motion_ex_roundtrip():
    pkt = mock.build_motion_ex_packet(rear_slip_ratio=0.42, front_slip_angle=0.07)
    header = packets.parse_header(pkt)
    assert header.packet_id == packets.PACKET_ID_MOTION_EX
    mex = packets.parse_motion_ex(pkt)
    assert mex is not None
    assert abs(mex.max_rear_slip_ratio - 0.42) < 1e-6
    assert abs(mex.max_front_slip_angle - 0.07) < 1e-6


def test_short_packet_returns_none():
    assert packets.parse_header(b"\x00" * 10) is None
    hdr = packets.parse_header(mock.build_header(packets.PACKET_ID_MOTION_EX))
    assert packets.parse_motion_ex(b"\x00" * 30) is None


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
