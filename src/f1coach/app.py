"""Phase 5 — the application: three threads wired together.

    UDP socket ──▶ [Receiver thread] ──▶ frame_queue
                                            │
                        [Aggregator thread] ┤ drains frames, builds laps
                                            │  on lap complete ──▶ lap_queue
                                            ▼
                          [Coaching thread] ── extract corners, diff vs PB,
                                               call Gemini, speak the radio

Ingestion (receiver + aggregator) is never blocked by the slow work (network
call + audio playback), which lives entirely on the coaching thread.
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
from typing import List, Optional

# Allow running as a script (`python src/f1coach/app.py`) as well as a module
# (`python -m f1coach.app`) by ensuring the `src` dir is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from f1coach import config, reference
from f1coach.ai_coach import AICoach
from f1coach.corners import Corner, compute_deltas, extract_corners, worst_corners
from f1coach.receiver import Frame, HeartbeatMonitor, UDPReceiver
from f1coach.telemetry import Lap, TelemetryAggregator
from f1coach.tts import Speaker


class Coach:
    """Owns the threads and the shared state (reference lap)."""

    def __init__(self, track: str = "default", coach_invalid: bool = config.COACH_ON_INVALID_LAPS) -> None:
        self.track = track
        self.coach_invalid = coach_invalid
        self.frame_queue: "queue.Queue[Frame]" = queue.Queue(maxsize=10000)
        self.lap_queue: "queue.Queue[Lap]" = queue.Queue()
        self.receiver = UDPReceiver(self.frame_queue)
        self.aggregator = TelemetryAggregator(on_lap_complete=self._on_lap_complete)
        self.ai = AICoach()
        self.speaker = Speaker()
        self.heartbeat = HeartbeatMonitor(self.receiver) if config.HEARTBEAT_ENABLED else None
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []

        loaded = reference.load_reference(track)
        self.ref_corners: Optional[List[Corner]] = loaded[0] if loaded else None
        self.ref_lap_time_ms: int = loaded[1] if loaded else 0
        if loaded:
            print(f"Loaded reference lap for '{track}': "
                  f"{self.ref_lap_time_ms/1000:.3f}s, {len(self.ref_corners)} corners.")
        else:
            print(f"No reference lap for '{track}' yet — your first clean lap becomes the benchmark.")

    # -- lap completion (called on the aggregator thread; must be fast) ----
    def _on_lap_complete(self, lap: Lap) -> None:
        self.lap_queue.put(lap)

    # -- thread bodies -----------------------------------------------------
    def _aggregator_loop(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self.frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.aggregator.consume(frame)
            except Exception as exc:  # never let one frame kill ingestion
                print(f"[aggregator] error processing frame: {exc}")

    def _coaching_loop(self) -> None:
        while not self._stop.is_set():
            try:
                lap = self.lap_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._handle_completed_lap(lap)
            except Exception as exc:  # never let one lap kill coaching
                print(f"[coaching] error handling lap {lap.lap_number}: {exc}")

    def _handle_completed_lap(self, lap: Lap) -> None:
        corners = extract_corners(lap)
        lap_time = f"{lap.lap_time_ms/1000:.3f}s" if lap.lap_time_ms else "n/a"
        tag = " (INVALID)" if lap.invalid else ""
        print(f"\n=== Lap {lap.lap_number} complete{tag}: {lap_time}, "
              f"{len(corners)} corners detected ===")

        if lap.invalid and not self.coach_invalid:
            print("Lap invalidated — skipping coaching. Set F1COACH_COACH_INVALID=1 to override.")
            self._maybe_update_reference(lap, corners, allow_invalid=False)
            return

        if self.ref_corners is None:
            print("No reference yet — banking this lap as the benchmark.")
            self._maybe_update_reference(lap, corners, allow_invalid=False, force=True)
            return

        deltas = compute_deltas(corners, self.ref_corners)
        worst = worst_corners(deltas)
        advice = self.ai.coach(worst)
        self.speaker.say(advice)
        self._maybe_update_reference(lap, corners, allow_invalid=False)

    def _maybe_update_reference(self, lap: Lap, corners: List[Corner],
                                allow_invalid: bool, force: bool = False) -> None:
        if lap.invalid and not allow_invalid:
            return
        if not corners:
            return
        beats_pb = self.ref_corners is None or (
            lap.lap_time_ms > 0 and lap.lap_time_ms < self.ref_lap_time_ms
        )
        if force or beats_pb:
            self.ref_corners = corners
            self.ref_lap_time_ms = lap.lap_time_ms or self.ref_lap_time_ms
            reference.save_reference(self.track, corners, self.ref_lap_time_ms)
            print(f"⭐ New reference lap saved ({self.ref_lap_time_ms/1000:.3f}s).")

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self.receiver.start()
        if self.heartbeat is not None:
            self.heartbeat.start()
        for name, target in (("aggregator", self._aggregator_loop),
                             ("coaching", self._coaching_loop)):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        print(f"F1 Driving Coach running. Listening on "
              f"{config.UDP_BIND_IP}:{config.UDP_PORT}. Ctrl-C to stop.")
        print(f"AI: {'Gemini ' + config.GEMINI_MODEL if self.ai.online else 'offline fallback'}"
              f" | TTS: {config.TTS_ENGINE if config.TTS_ENABLED else 'disabled'}")
        if self.heartbeat is not None:
            print("Heartbeat on — a [hb] status line prints every "
                  f"{config.HEARTBEAT_INTERVAL:.0f}s so you can confirm packets are arriving "
                  "(F1COACH_HEARTBEAT=0 to silence).")

    def stop(self) -> None:
        self._stop.set()
        if self.heartbeat is not None:
            self.heartbeat.stop()
        self.receiver.stop()
        for t in self._threads:
            t.join(timeout=2.0)
        # Best-effort: process any laps still queued so a final PB isn't lost.
        # Threads have been asked to stop; drain on the main thread.
        while True:
            try:
                lap = self.lap_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_completed_lap(lap)
            except Exception as exc:
                print(f"[coaching] error draining lap {lap.lap_number}: {exc}")

    def run_forever(self) -> None:
        self.start()
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\nShutting down…")
        finally:
            self.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description="F1 25 AI Driving Coach")
    ap.add_argument("--track", default="default", help="track name key for the reference lap")
    ap.add_argument("--coach-invalid", action="store_true", help="coach even on invalidated laps")
    args = ap.parse_args()
    Coach(track=args.track, coach_invalid=args.coach_invalid).run_forever()


if __name__ == "__main__":
    main()
