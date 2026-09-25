#!/usr/bin/env python3
"""Phase 1 — the UDP sniffer / connectivity diagnostic.

Standalone tool to confirm the game is streaming and reaching THIS machine
before running the full coach. Binds 0.0.0.0:20777 and, every couple of
seconds, prints a one-line summary: the sender's IP, the UDP format, packet
rate, per-packet-id counts and the player's live speed/lap distance. If no
packets arrive it says so and lists what to check — the single most useful
line when debugging a PC→Mac setup.

Usage:
    python scripts/sniff.py                # live, from the game
    python scripts/sniff.py --mock         # replay synthetic packets locally
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from f1coach import config, mock, packets
from f1coach.receiver import Frame, HeartbeatMonitor, UDPReceiver


def sniff_live() -> None:
    """Run the real receiver + heartbeat so the diagnostic covers every
    failure mode (wrong format, no traffic, wrong car index), not just id 6."""
    q: "queue.Queue[Frame]" = queue.Queue(maxsize=10000)
    receiver = UDPReceiver(q)
    monitor = HeartbeatMonitor(receiver, interval=config.HEARTBEAT_INTERVAL)
    receiver.start()
    monitor.start()
    print(f"Listening on {config.UDP_BIND_IP}:{config.UDP_PORT} — start driving in F1 25 …")
    print("(Enable UDP telemetry: Settings → Telemetry Settings; IP = this machine, port 20777, Format 2025)\n")
    try:
        while True:
            # Drain frames so the queue never fills; the heartbeat does the reporting.
            try:
                q.get(timeout=0.5)
            except queue.Empty:
                pass
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        monitor.stop()
        receiver.stop()


def sniff_mock() -> None:
    """Feed synthetic telemetry through the same decode path (no game needed)."""
    print("Mock mode: replaying synthetic Car Telemetry packets.\n")
    counts: dict[int, int] = {}
    for i in range(20):
        # a little braking-into-a-corner sweep
        speed = max(90, 300 - i * 12)
        brake = 0.0 if i < 5 else min(1.0, (i - 4) * 0.2)
        pkt = mock.build_car_telemetry_packet(speed=speed, throttle=0.0, brake=brake, gear=6)
        _handle(pkt, counts)
        time.sleep(0.05)


def _handle(data: bytes, counts: dict[int, int]) -> None:
    header = packets.parse_header(data)
    if header is None:
        return
    counts[header.packet_id] = counts.get(header.packet_id, 0) + 1
    if header.packet_id == packets.PACKET_ID_CAR_TELEMETRY:
        tel = packets.parse_car_telemetry(data, header)
        if tel is not None:
            print(
                f"[pkt6 #{counts[header.packet_id]:>4}] "
                f"speed={tel.speed:>3} km/h  brake={tel.brake:>4.0%}  "
                f"throttle={tel.throttle:>4.0%}  gear={tel.gear}"
            )


def main() -> None:
    ap = argparse.ArgumentParser(description="F1 25 UDP sniffer (Phase 1)")
    ap.add_argument("--mock", action="store_true", help="replay synthetic packets locally")
    args = ap.parse_args()
    if args.mock:
        sniff_mock()
    else:
        sniff_live()


if __name__ == "__main__":
    main()
