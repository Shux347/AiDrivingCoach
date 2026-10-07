"""Thread 2 — the telemetry aggregator.

Consumes :class:`~f1coach.receiver.Frame` objects and stitches the three packet
streams (lap data / car telemetry / motion-ex) into per-lap sample sets.

Two hard rules from the spec:

* **Never index by time.** Every sample is tagged with ``m_lapDistance`` so that
  lap N and lap N+1 align *spatially* on the track, not temporally.
* **A lap is "finished" when ``m_currentLapNum`` increments.** That edge is what
  triggers the delta analysis and coaching.

Car-telemetry packets (60 Hz, the richest signal for braking/throttle/speed)
drive sampling: on each one we snapshot the latest known lap distance and wheel
slip and append a :class:`LapSample`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np

from . import config
from .receiver import Frame


@dataclass(slots=True)
class LapSample:
    """One spatially-tagged telemetry sample."""

    lap_distance: float   # metres around the lap (monotonic within a lap)
    speed: float          # km/h
    throttle: float       # 0..1
    brake: float          # 0..1
    steer: float          # -1..1
    gear: int
    rear_slip_ratio: float    # peak rear wheelspin magnitude at this instant
    front_slip_angle: float   # peak front slip-angle magnitude at this instant


@dataclass(slots=True)
class Lap:
    """A completed (or in-progress) lap: samples ordered by lap distance."""

    lap_number: int
    samples: List[LapSample] = field(default_factory=list)
    invalid: bool = False
    lap_time_ms: int = 0

    def __len__(self) -> int:
        return len(self.samples)

    # -- vectorised views --------------------------------------------------
    def arrays(self) -> dict[str, np.ndarray]:
        """Return column arrays, sorted by ascending lap distance.

        Duplicate distances (the car briefly stationary, or a flashback) are
        collapsed to their first occurrence so distance is strictly increasing
        — a precondition for :func:`numpy.interp`-based resampling.
        """
        if not self.samples:
            return {k: np.empty(0) for k in
                    ("distance", "speed", "throttle", "brake", "steer",
                     "gear", "rear_slip", "front_slip")}
        dist = np.fromiter((s.lap_distance for s in self.samples), dtype=float)
        order = np.argsort(dist, kind="stable")
        cols = {
            "distance": dist,
            "speed": np.fromiter((s.speed for s in self.samples), dtype=float),
            "throttle": np.fromiter((s.throttle for s in self.samples), dtype=float),
            "brake": np.fromiter((s.brake for s in self.samples), dtype=float),
            "steer": np.fromiter((s.steer for s in self.samples), dtype=float),
            "gear": np.fromiter((s.gear for s in self.samples), dtype=float),
            "rear_slip": np.fromiter((s.rear_slip_ratio for s in self.samples), dtype=float),
            "front_slip": np.fromiter((s.front_slip_angle for s in self.samples), dtype=float),
        }
        cols = {k: v[order] for k, v in cols.items()}
        # Keep strictly-increasing distance. On a flashback the car rewinds and
        # re-drives a stretch, producing duplicate distances from two time
        # periods; the stable sort keeps them in time order, so keeping the
        # LAST of each equal-distance run selects the corrected re-drive rather
        # than the aborted earlier pass.
        d = cols["distance"]
        keep = np.concatenate((np.diff(d) > 1e-6, [True]))
        return {k: v[keep] for k, v in cols.items()}


class TelemetryAggregator:
    """Merges frames into laps and fires a callback when a lap completes."""

    # total_distance only ever grows in normal forward driving (it does NOT
    # reset at the S/F line). A drop larger than this many metres therefore
    # means a rewind — a flashback, or an in-place restart that keeps the same
    # lap number and session UID (as seen on real F1 25 telemetry).
    _REWIND_DROP_M = 5.0

    def __init__(self, on_lap_complete: Callable[[Lap], None]) -> None:
        self._on_lap_complete = on_lap_complete
        self._current: Optional[Lap] = None
        self._last_lap_num: Optional[int] = None
        # rolling "latest known" state, merged into each sample
        self._lap_distance = 0.0
        self._rear_slip = 0.0
        self._front_slip = 0.0
        self._lap_invalid = 0
        self._last_lap_time_ms = 0
        # restart/flashback detection
        self._session_uid = 0
        self._last_total_distance = 0.0
        # ordering: highest m_overallFrameIdentifier accepted in the current
        # session. Per the F1 25 spec this counter does NOT go back after a
        # flashback and only resets on a new session, so it lets us spot (and
        # drop) a reordered/stale UDP datagram without mistaking a genuine
        # rewind for one. 0 means "no ordering info yet".
        self._last_overall_frame_id = 0
        # diagnostics: last raw fields we traced, to log only on change
        self._dbg_prev: Optional[tuple] = None

    def consume(self, frame: Frame) -> None:
        if frame.lap is not None:
            self._on_lap_frame(frame)
        if frame.motion is not None:
            self._rear_slip = frame.motion.max_rear_slip_ratio
            self._front_slip = frame.motion.max_front_slip_angle
        if frame.telemetry is not None:
            self._on_telemetry_frame(frame)

    # -- handlers ----------------------------------------------------------
    def _on_lap_frame(self, frame: Frame) -> None:
        lap = frame.lap
        assert lap is not None

        # Drop a reordered/stale UDP datagram before it can corrupt state. UDP
        # gives no ordering guarantee, so a late-delivered pre-rewind packet
        # could otherwise look like a rewind (its total_distance is behind ours)
        # and wrongly clear the sticky invalid latch. m_overallFrameIdentifier
        # does NOT rewind on a flashback or in-place restart — confirmed on real
        # F1 25 telemetry, where it kept climbing 153486 -> 153489 -> 153492
        # across a total_distance rewind — so a frame whose overall id is BEHIND
        # the last one we accepted (within the same session) can only be
        # out-of-order, never a genuine rewind. Guarded to stay inert when the id
        # is 0 (synthetic frames / unit tests) or the session changed, so a real
        # rewind and a real session restart are both still handled below.
        if (frame.overall_frame_identifier and self._session_uid
                and frame.session_uid == self._session_uid
                and frame.overall_frame_identifier < self._last_overall_frame_id):
            self._trace_event("STALE frame dropped (overall id went backwards)", frame, lap)
            return
        # Advance the high-water mark, but only on a real (nonzero) id. A 0-id
        # frame (synthetic / no ordering info) must NOT drag the mark down to 0,
        # which would reopen the guard's window for a later stale datagram. A new
        # session legitimately resets the id to a small NONZERO value — that
        # still updates here, because the session-uid clause above makes the
        # guard inert on the transition frame, so re-baselining downward is safe.
        if frame.overall_frame_identifier:
            self._last_overall_frame_id = frame.overall_frame_identifier

        self._lap_distance = lap.lap_distance
        self._trace_frame(frame, lap)

        if self._last_lap_num is None:
            # First lap frame seen — begin tracking. Seed the sticky flag from
            # this frame: if we joined mid-lap and it's already invalid, keep it.
            self._begin_lap(frame, lap, seed_invalid=lap.current_lap_invalid)
            self._trace_event("BEGIN (first frame)", frame, lap)
            return

        if self._is_session_restart(frame, lap):
            # The session was restarted (e.g. "Restart Session" spawning a new
            # session UID, or a return-to-garage that rewinds the lap counter).
            # The in-progress lap is abandoned, NOT completed — discard it
            # without finalising and start fresh. Seed CLEAN (not from this
            # frame): the game can lag its m_currentLapInvalid reset by a frame,
            # so the first post-restart frame may still carry the stale 1; a
            # genuine invalidation of the fresh lap re-appears on its own frames.
            self._begin_lap(frame, lap, seed_invalid=0)
            self._trace_event("SESSION RESTART -> fresh lap", frame, lap)
            return

        if lap.current_lap_num > self._last_lap_num:
            # Lap boundary crossed. This is not an in-lap rewind: the game resets
            # total_distance toward zero at the S/F line, and the first new-lap
            # frame can carry a stale invalid=1 for the previous lap. Finalise the
            # completed lap using ONLY the sticky state accumulated over its own
            # frames, and ignore the transition frame's invalid bit.
            self._trace_event(f"FINALISE lap {self._last_lap_num} "
                              f"(invalid={self._lap_invalid})", frame, lap)
            self._finalise_lap(completed_lap_time_ms=lap.last_lap_time_ms)
            # Start the new lap CLEAN. m_currentLapInvalid is sticky within a lap
            # and resets at the S/F line, but the game can lag that reset by a
            # frame — so the transition frame may still carry the *previous*
            # lap's 1. Ignoring it here avoids inheriting stale invalidity; a
            # genuine invalidation of this lap will re-appear on its own frames.
            self._begin_lap(frame, lap, seed_invalid=0)
            return

        if lap.total_distance < self._last_total_distance - self._REWIND_DROP_M:
            # total_distance only ever grows in normal forward driving (it does
            # NOT reset at the S/F line), so a drop means a rewind: a flashback,
            # or an in-place restart that keeps the SAME lap number and session
            # UID (as seen on real F1 25 telemetry). The game RE-EVALUATES lap
            # validity on a rewind, so our one-way sticky latch must let go of a
            # stale 1. Reset clean and let this lap's remaining frames re-drive
            # the flag: if the game still considers the lap invalid it keeps
            # sending m_currentLapInvalid=1 and we re-accumulate; if the rewind
            # wiped the strike (game sends 0) the lap is correctly valid again.
            self._lap_invalid = int(bool(lap.current_lap_invalid))
            self._session_uid = frame.session_uid
            self._last_total_distance = lap.total_distance
            self._trace_event("REWIND -> resync (clean, re-accumulate)", frame, lap)

        # Same lap still in progress — accumulate stickily and refresh trackers.
        if lap.current_lap_invalid and not self._lap_invalid:
            self._trace_event("MID-LAP invalidation", frame, lap)
        if lap.current_lap_invalid:
            self._lap_invalid = 1
        self._session_uid = frame.session_uid
        self._last_total_distance = lap.total_distance

    def _begin_lap(self, frame: Frame, lap, *, seed_invalid: int) -> None:
        """Start tracking a fresh lap and reset the restart-detection baseline."""
        self._last_lap_num = lap.current_lap_num
        self._session_uid = frame.session_uid
        self._last_total_distance = lap.total_distance
        self._current = Lap(lap_number=lap.current_lap_num)
        self._lap_invalid = seed_invalid

    def _is_session_restart(self, frame: Frame, lap) -> bool:
        """True if the whole SESSION was restarted since the last lap frame.

        This is narrower than a rewind (handled separately in
        :meth:`_on_lap_frame` via a total_distance drop). A session restart is
        signalled by either a new session UID or the lap counter jumping
        *backwards* — both of which abandon the in-progress lap outright rather
        than merely rewinding within it.
        """
        # New session UID → the session was restarted/recreated. Authoritative,
        # and a flashback or in-place restart never changes it. (Guarded so the
        # all-zero UID used by some synthetic frames doesn't trip this.)
        if self._session_uid and frame.session_uid and frame.session_uid != self._session_uid:
            return True
        # Same UID but the lap counter rewound — a restart that resets the lap
        # number (e.g. return to garage / restart from the pit menu).
        if lap.current_lap_num < self._last_lap_num:
            return True
        return False

    def _on_telemetry_frame(self, frame: Frame) -> None:
        if self._current is None:
            return
        tel = frame.telemetry
        assert tel is not None
        self._current.samples.append(
            LapSample(
                lap_distance=self._lap_distance,
                speed=float(tel.speed),
                throttle=tel.throttle,
                brake=tel.brake,
                steer=tel.steer,
                gear=tel.gear,
                rear_slip_ratio=self._rear_slip,
                front_slip_angle=self._front_slip,
            )
        )

    def _finalise_lap(self, completed_lap_time_ms: int) -> None:
        if self._current is None:
            return
        self._current.invalid = bool(self._lap_invalid)
        self._current.lap_time_ms = completed_lap_time_ms
        if len(self._current) > 0:
            self._on_lap_complete(self._current)

    # -- diagnostics -------------------------------------------------------
    def _trace_frame(self, frame: Frame, lap) -> None:
        """Log the raw validity fields whenever any of them changes.

        Enabled with F1COACH_DEBUG_VALIDITY=1. This is the ground-truth capture
        for what the game actually sends across a lap boundary or restart.
        """
        if not config.DEBUG_VALIDITY:
            return
        key = (lap.current_lap_num, lap.current_lap_invalid,
               frame.session_uid, round(lap.total_distance, -1))
        if key == self._dbg_prev:
            return
        self._dbg_prev = key
        print(f"[validity] lapNum={lap.current_lap_num} rawInvalid={lap.current_lap_invalid} "
              f"sticky={self._lap_invalid} uid={frame.session_uid} "
              f"overallFrame={frame.overall_frame_identifier} "
              f"lapDist={lap.lap_distance:.0f} totalDist={lap.total_distance:.0f} "
              f"lastLapMs={lap.last_lap_time_ms}")

    def _trace_event(self, event: str, frame: Frame, lap) -> None:
        if not config.DEBUG_VALIDITY:
            return
        print(f"[validity] >>> {event} | lapNum={lap.current_lap_num} "
              f"rawInvalid={lap.current_lap_invalid} sticky={self._lap_invalid} "
              f"uid={frame.session_uid} overallFrame={frame.overall_frame_identifier} "
              f"totalDist={lap.total_distance:.0f}")
