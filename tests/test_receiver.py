"""Tests for the UDP receiver's diagnostics: format guard + heartbeat line."""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from f1coach import mock, packets
from f1coach.receiver import UDPReceiver, format_heartbeat


def _telemetry_pkt(speed=200):
    return mock.build_car_telemetry_packet(speed=speed, throttle=1.0, brake=0.0)


def test_record_accepts_matching_format():
    rx = UDPReceiver(out_queue=None)  # type: ignore[arg-type]
    ok = rx._record(_telemetry_pkt(), ("192.168.1.50", 20777))
    assert ok is True
    s = rx.stats()
    assert s["format_ok"] and s["format"] == 2025  # mock stamps the 2025 format
    assert s["sender"] == "192.168.1.50"
    assert s["pid_counts"].get(packets.PACKET_ID_CAR_TELEMETRY) == 1


def test_record_drops_wrong_format():
    rx = UDPReceiver(out_queue=None)  # type: ignore[arg-type]
    pkt = bytearray(_telemetry_pkt())
    struct.pack_into("<H", pkt, 0, 2024)  # stamp an older format
    ok = rx._record(bytes(pkt), ("10.0.0.9", 20777))
    assert ok is False                     # dropped, not decoded
    s = rx.stats()
    assert s["format_ok"] is False
    assert s["format"] == 2024


def test_heartbeat_no_packets():
    line = format_heartbeat(
        {"total_packets": 0, "decoded": 0, "pid_counts": {}, "sender": None,
         "format": None, "format_ok": True, "speed": 0, "lap_distance": 0.0,
         "total_distance": 0.0},
        rate=0.0,
    )
    assert "NO PACKETS" in line


def test_heartbeat_reports_sender_and_counts():
    line = format_heartbeat(
        {"total_packets": 100, "decoded": 90, "pid_counts": {2: 30, 6: 40, 13: 30},
         "sender": "192.168.1.50", "format": 2025, "format_ok": True,
         "speed": 287, "lap_distance": 512.0, "total_distance": 3400.0},
        rate=40.0,
    )
    assert "src=192.168.1.50" in line
    assert "fmt=2025" in line
    assert "id2=30" in line and "id6=40" in line and "id13=30" in line
    assert "287 km/h" in line


def test_heartbeat_flags_mismatch():
    line = format_heartbeat(
        {"total_packets": 10, "decoded": 0, "pid_counts": {6: 10}, "sender": "10.0.0.9",
         "format": 2024, "format_ok": False, "speed": 0, "lap_distance": 0.0,
         "total_distance": 0.0},
        rate=5.0,
    )
    assert "MISMATCH" in line


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
