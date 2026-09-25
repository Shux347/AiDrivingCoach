#!/usr/bin/env python3
"""Send synthetic F1 25 telemetry over UDP so the coach can be demoed offline.

Emits two laps to 127.0.0.1:20777:
  * Lap 1 — a clean reference lap (becomes the personal best).
  * Lap 2 — deliberately worse (braking early, slower apex, late throttle,
            snappy exits) so the delta engine and coach have plenty to say.

Run the coach in one terminal, then this in another:
    python -m f1coach.app                # terminal 1
    python scripts/mock_sender.py        # terminal 2
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from f1coach import config, mock


def send_lap(sock, addr, lap_num, delay, **kwargs):
    for lap_pkt, tel_pkt, mex_pkt in mock.simulate_lap_packets(lap_num, **kwargs):
        sock.sendto(lap_pkt, addr)
        sock.sendto(tel_pkt, addr)
        sock.sendto(mex_pkt, addr)
        time.sleep(delay)


def main() -> None:
    ap = argparse.ArgumentParser(description="F1 25 mock telemetry sender")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=config.UDP_PORT)
    ap.add_argument("--delay", type=float, default=0.01, help="seconds between frames")
    args = ap.parse_args()
    addr = (args.host, args.port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"Sending mock telemetry to {addr} …")
    print("Lap 1 (clean reference)…")
    send_lap(sock, addr, 1, args.delay, last_lap_time_ms=90000)
    print("Lap 2 (sloppier — braked early, slow apex, late throttle, snappy exit)…")
    # Lap 2 carries lap 1's (fast) time on the wire, finalising lap 1 as the PB.
    send_lap(sock, addr, 2, args.delay, last_lap_time_ms=88000,
             brake_bias_m=-18.0, apex_penalty_kmh=12.0, pickup_delay_m=22.0, exit_slip=0.4)
    # A third lap frame with an incremented number so the coach finalises lap 2.
    # It carries lap 2's (slow) time, so lap 2 will NOT beat the reference.
    print("Lap 3 marker (finalises lap 2)…")
    send_lap(sock, addr, 3, args.delay, last_lap_time_ms=91500)
    print("Done. The coach should have delivered radio for lap 2.")


if __name__ == "__main__":
    main()
