"""Thread 1 — the UDP receiver.

Binds a UDP socket, decodes every datagram's header, parses the three packet
types the coach needs, and pushes lightweight parsed frames onto a
thread-safe queue for the aggregator to consume. Runs on a background thread so
packet ingestion never blocks on network requests or audio playback.
"""

from __future__ import annotations

import queue
import socket
import threading
from dataclasses import dataclass
from typing import Optional

from . import config, packets


@dataclass(slots=True)
class Frame:
    """A single decoded telemetry sample, merged as packets arrive.

    The receiver emits one Frame per relevant packet; the aggregator stitches
    lap data, car telemetry and motion-ex together by proximity in the stream.
    """

    session_time: float
    lap: Optional[packets.LapData] = None
    telemetry: Optional[packets.CarTelemetry] = None
    motion: Optional[packets.MotionEx] = None
    session_uid: int = 0          # changes when the session is restarted/recreated
    # Monotonic frame counter that, per the F1 25 spec, does NOT go back after a
    # flashback (unlike frame_identifier / session_time). Resets to 0 on a new
    # session, so it is monotonic only *within* one session_uid. Lets the
    # aggregator spot reordered/stale UDP datagrams. 0 when absent (synthetic
    # frames / unit tests), which the aggregator treats as "no ordering info".
    overall_frame_identifier: int = 0


class UDPReceiver:
    """Background UDP listener that fills a queue with :class:`Frame` objects."""

    def __init__(
        self,
        out_queue: "queue.Queue[Frame]",
        bind_ip: str = config.UDP_BIND_IP,
        port: int = config.UDP_PORT,
    ) -> None:
        self._queue = out_queue
        self._bind_ip = bind_ip
        self._port = port
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.packets_received = 0            # decoded frames we care about
        # -- live diagnostics (read by the heartbeat monitor) --------------
        self.total_packets = 0               # every datagram with a valid header
        self.pid_counts: dict[int, int] = {}  # per packet-id tally
        self.last_sender: Optional[str] = None
        self.seen_format: Optional[int] = None
        self.last_speed: int = 0
        self.last_lap_distance: float = 0.0
        self.last_total_distance: float = 0.0
        self._format_ok = True
        self._warned_format = False
        self._warned_truncation = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self._bind_ip, self._port))
        # A timeout lets the loop notice the stop event even with no traffic.
        self._sock.settimeout(0.5)
        self._thread = threading.Thread(target=self._run, name="udp-receiver", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    # -- receive loop ------------------------------------------------------
    def _run(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(config.UDP_BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break  # socket closed during shutdown

            if not self._record(data, addr):
                continue  # bad header or wrong UDP format — don't parse garbage

            frame = self._decode(data)
            if frame is not None:
                self.packets_received += 1
                if frame.telemetry is not None:
                    self.last_speed = frame.telemetry.speed
                if frame.lap is not None:
                    self.last_lap_distance = frame.lap.lap_distance
                    self.last_total_distance = frame.lap.total_distance
                try:
                    self._queue.put_nowait(frame)
                except queue.Full:
                    pass  # drop rather than block ingestion

    def _record(self, data: bytes, addr) -> bool:
        """Update diagnostics and validate the packet format.

        Returns True if the datagram should be decoded, False to drop it (bad
        header, or a UDP format we don't parse — which would decode to garbage).
        Also emits one-time warnings for a format mismatch or a datagram large
        enough to have been truncated by the socket buffer.
        """
        header = packets.parse_header(data)
        if header is None:
            return False
        self.last_sender = addr[0] if addr else self.last_sender
        self.total_packets += 1
        self.pid_counts[header.packet_id] = self.pid_counts.get(header.packet_id, 0) + 1
        self.seen_format = header.packet_format

        if len(data) >= config.UDP_BUFFER_SIZE and not self._warned_truncation:
            self._warned_truncation = True
            print(f"[receiver] datagram reached buffer size ({config.UDP_BUFFER_SIZE} B) "
                  "— possible truncation; raise F1COACH buffer if a new format is in use.")

        if header.packet_format != config.EXPECTED_UDP_FORMAT:
            self._format_ok = False
            if not self._warned_format:
                self._warned_format = True
                print(f"[receiver] ⚠ UDP format {header.packet_format} received, "
                      f"expected {config.EXPECTED_UDP_FORMAT}. Set F1 25 → Settings → "
                      "Telemetry Settings → UDP Format to 2025 (or set F1COACH_EXPECTED_FORMAT). "
                      "Dropping packets until the format matches to avoid garbage coaching.")
            return False
        return True

    def stats(self) -> dict:
        """A snapshot of live receive diagnostics for the heartbeat monitor."""
        return {
            "total_packets": self.total_packets,
            "decoded": self.packets_received,
            "pid_counts": dict(self.pid_counts),
            "sender": self.last_sender,
            "format": self.seen_format,
            "format_ok": self._format_ok,
            "speed": self.last_speed,
            "lap_distance": self.last_lap_distance,
            "total_distance": self.last_total_distance,
        }

    @staticmethod
    def _decode(data: bytes) -> Optional[Frame]:
        header = packets.parse_header(data)
        if header is None:
            return None
        pid = header.packet_id
        if pid == packets.PACKET_ID_LAP_DATA:
            lap = packets.parse_lap_data(data, header)
            if lap is None:
                return None
            return Frame(session_time=header.session_time,
                         session_uid=header.session_uid,
                         overall_frame_identifier=header.overall_frame_identifier,
                         lap=lap)
        if pid == packets.PACKET_ID_CAR_TELEMETRY:
            tel = packets.parse_car_telemetry(data, header)
            if tel is None:
                return None
            return Frame(session_time=header.session_time,
                         session_uid=header.session_uid,
                         overall_frame_identifier=header.overall_frame_identifier,
                         telemetry=tel)
        if pid == packets.PACKET_ID_MOTION_EX:
            mex = packets.parse_motion_ex(data)
            if mex is None:
                return None
            return Frame(session_time=header.session_time,
                         session_uid=header.session_uid,
                         overall_frame_identifier=header.overall_frame_identifier,
                         motion=mex)
        return None  # a packet type we don't care about


# ---------------------------------------------------------------------------
# Heartbeat monitor — a connection diagnostic shared by app.py and sniff.py
# ---------------------------------------------------------------------------
def format_heartbeat(stats: dict, rate: float) -> str:
    """One-line status from a :meth:`UDPReceiver.stats` snapshot + packet rate."""
    if stats["total_packets"] == 0:
        return ("[hb] NO PACKETS yet — check: game UDP telemetry ON? IP points at "
                "THIS machine? port 20777? same subnet? firewall? UDP Format 2025?")
    ids = " ".join(f"id{pid}={n}" for pid, n in sorted(stats["pid_counts"].items()))
    fmt = stats["format"]
    fmt_tag = f"fmt={fmt}" + ("" if stats["format_ok"] else " ⚠MISMATCH")
    line = (f"[hb] src={stats['sender']} {fmt_tag} | {rate:.0f} pkt/s "
            f"({stats['total_packets']} total) | {ids}")
    if stats["format_ok"] and stats["decoded"] == 0 and stats["total_packets"] > 0:
        line += " | packets arriving but none decode — likely wrong UDP Format"
    else:
        line += (f" | {stats['speed']:.0f} km/h | lap {stats['lap_distance']:.0f} m "
                 f"/ total {stats['total_distance']/1000:.1f} km")
    return line


class HeartbeatMonitor:
    """Background thread that periodically prints a receiver status line."""

    def __init__(self, receiver: "UDPReceiver",
                 interval: float = config.HEARTBEAT_INTERVAL) -> None:
        self._receiver = receiver
        self._interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._prev_total = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 0.5)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            stats = self._receiver.stats()
            rate = (stats["total_packets"] - self._prev_total) / self._interval
            self._prev_total = stats["total_packets"]
            print(format_heartbeat(stats, rate))
