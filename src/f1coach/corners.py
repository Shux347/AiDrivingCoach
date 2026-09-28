"""Phase 3/4 — corner extraction and the delta engine.

A **corner** is derived from a braking event: the region where ``m_brake``
exceeds :data:`~f1coach.config.BRAKE_ON_THRESHOLD`. From each we distil the four
features the spec asks for, all indexed by track distance so laps align
spatially:

* **Braking point** — distance where brake first crosses the threshold.
* **Apex speed** — minimum speed between the braking point and throttle pick-up.
* **Throttle pick-up point** — distance, after the apex, where throttle first
  crosses :data:`~f1coach.config.THROTTLE_ON_THRESHOLD`.
* **Max exit slip** — peak rear wheel-slip ratio from apex through corner exit
  (instability / wheelspin).

The delta engine then matches each corner in the current lap to the nearest
corner in the reference (personal-best) lap *by braking point* and reports the
signed differences (negative braking-point delta ⇒ braked earlier, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from . import config
from .telemetry import Lap


@dataclass(slots=True)
class Corner:
    """Reduced features for a single corner."""

    index: int                  # 1-based order around the lap ("Turn N-ish")
    brake_point: float          # metres — where braking began
    apex_distance: float        # metres — where min speed occurred
    apex_speed: float           # km/h
    throttle_pickup: float      # metres — where throttle > threshold after apex
    max_exit_slip: float        # peak rear slip ratio on exit
    min_gear: int               # lowest gear taken through the corner


def extract_corners(lap: Lap) -> List[Corner]:
    """Detect braking-defined corners and reduce each to features."""
    cols = lap.arrays()
    dist = cols["distance"]
    if dist.size < 3:
        return []

    brake = cols["brake"]
    throttle = cols["throttle"]
    speed = cols["speed"]
    rear_slip = cols["rear_slip"]
    gear = cols["gear"]
    n = dist.size

    regions = _merge_brake_regions(_brake_regions(brake), dist, throttle)

    corners: List[Corner] = []
    for start, end in regions:
        brake_point = float(dist[start])
        brake_release = float(dist[end - 1])

        # Reject noise: braking events shorter than the minimum zone length.
        if brake_release - brake_point < config.MIN_BRAKE_ZONE_METERS:
            continue

        # -- cornering phase: braking start -> throttle pick-up ------------
        # Throttle pick-up: first sample at/after brake release where throttle
        # crosses the threshold, bounded so the search can't run into the next
        # corner or the straight beyond it.
        search_limit = _next_brake_start(regions, start) or n
        pickup_idx = _first_crossing(throttle, end - 1, config.THROTTLE_ON_THRESHOLD, search_limit)
        phase_end = pickup_idx if pickup_idx is not None else min(end + 1, n - 1)

        # Apex = min speed between braking start and throttle pick-up.
        phase = slice(start, max(phase_end + 1, start + 1))
        seg_speed = speed[phase]
        apex_rel = int(np.argmin(seg_speed))
        apex_idx = start + apex_rel
        apex_distance = float(dist[apex_idx])
        apex_speed = float(speed[apex_idx])

        throttle_pickup = float(dist[pickup_idx]) if pickup_idx is not None else brake_release

        # Exit slip: apex -> pickup (plus a short exit window).
        exit_end = min((pickup_idx if pickup_idx is not None else phase_end) + 5, n)
        exit_slip = float(np.max(rear_slip[apex_idx:exit_end])) if exit_end > apex_idx else 0.0

        min_gear = int(np.min(gear[phase])) if seg_speed.size else 0

        corners.append(
            Corner(
                index=len(corners) + 1,
                brake_point=brake_point,
                apex_distance=apex_distance,
                apex_speed=apex_speed,
                throttle_pickup=throttle_pickup,
                max_exit_slip=exit_slip,
                min_gear=min_gear,
            )
        )

    return corners


def standardise_corners(
    current: List[Corner],
    known: Optional[List[Corner]] = None,
    match_distance: Optional[float] = None,
    track_name: Optional[str] = None,
) -> List[Corner]:
    """Normalize a lap's detected corners against a track catalog.

    Any corner whose braking point sits within ``match_distance`` of an existing
    track marker is treated as the same physical turn. Otherwise it is appended
    as a new track point until the official turn count for the circuit is reached.
    The result is sorted by brake point and carries the canonical track location
    for each corner.
    """
    catalogue = sorted((list(known) if known else []), key=lambda c: c.brake_point)
    match_limit = config.CORNER_CATALOG_MATCH_METERS if match_distance is None else match_distance
    official_count = config.official_turn_count(track_name)
    canonical: List[Corner] = []
    reserved_catalogue: set[int] = set()

    for corner in sorted(current, key=lambda c: c.brake_point):
        match_idx = None
        had_candidate = False
        for idx, ref in enumerate(catalogue):
            gap = abs(ref.brake_point - corner.brake_point)
            if gap <= match_limit:
                had_candidate = True
                if idx in reserved_catalogue:
                    continue
                if match_idx is None or gap < abs(catalogue[match_idx].brake_point - corner.brake_point):
                    match_idx = idx

        if match_idx is not None:
            match = catalogue[match_idx]
            reserved_catalogue.add(match_idx)
            canonical.append(
                Corner(
                    index=match.index,
                    brake_point=match.brake_point,
                    apex_distance=corner.apex_distance,
                    apex_speed=corner.apex_speed,
                    throttle_pickup=corner.throttle_pickup,
                    max_exit_slip=corner.max_exit_slip,
                    min_gear=corner.min_gear,
                )
            )
            continue

        if had_candidate:
            continue

        if official_count is not None and len(catalogue) >= official_count:
            continue

        new_corner = Corner(
            index=len(catalogue) + 1,
            brake_point=corner.brake_point,
            apex_distance=corner.apex_distance,
            apex_speed=corner.apex_speed,
            throttle_pickup=corner.throttle_pickup,
            max_exit_slip=corner.max_exit_slip,
            min_gear=corner.min_gear,
        )
        catalogue.append(new_corner)
        reserved_catalogue.add(len(catalogue) - 1)
        canonical.append(new_corner)

    canonical.sort(key=lambda c: c.brake_point)
    for i, corner in enumerate(canonical, start=1):
        corner.index = i
    return canonical


def _brake_regions(brake: np.ndarray) -> List[tuple[int, int]]:
    """Maximal contiguous runs of ``brake > threshold`` as [start, end) pairs."""
    braking = brake > config.BRAKE_ON_THRESHOLD
    regions: List[tuple[int, int]] = []
    idx = 0
    n = braking.size
    while idx < n:
        if not braking[idx]:
            idx += 1
            continue
        start = idx
        while idx < n and braking[idx]:
            idx += 1
        regions.append((start, idx))
    return regions


def _merge_brake_regions(
    regions: List[tuple[int, int]], dist: np.ndarray, throttle: np.ndarray
) -> List[tuple[int, int]]:
    """Coalesce braking bursts split by a brief lift (trail-braking, lockups).

    Two adjacent regions merge when the track gap between them is under
    :data:`~f1coach.config.CORNER_MERGE_GAP_METERS` *and* throttle never truly
    picks up in the gap — i.e. it was a momentary lift, not a corner exit.
    """
    if not regions:
        return regions
    merged = [regions[0]]
    for start, end in regions[1:]:
        prev_start, prev_end = merged[-1]
        gap_m = float(dist[start] - dist[prev_end - 1])
        gap_throttle = throttle[prev_end:start]
        lifted_only = gap_throttle.size == 0 or float(np.max(gap_throttle)) <= config.THROTTLE_ON_THRESHOLD
        if gap_m <= config.CORNER_MERGE_GAP_METERS and lifted_only:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def _next_brake_start(regions: List[tuple[int, int]], current_start: int) -> Optional[int]:
    """Start index of the first braking region that begins after ``current_start``."""
    for start, _end in regions:
        if start > current_start:
            return start
    return None


def _first_crossing(
    signal: np.ndarray, from_idx: int, threshold: float, limit: Optional[int] = None
) -> Optional[int]:
    """Index of the first sample in ``[from_idx, limit)`` exceeding ``threshold``."""
    stop = signal.size if limit is None else min(limit, signal.size)
    for i in range(max(from_idx, 0), stop):
        if signal[i] > threshold:
            return i
    return None


# ---------------------------------------------------------------------------
# Delta engine
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class CornerDelta:
    """Signed differences for one corner vs. the reference lap."""

    corner_index: int
    brake_point_delta: float     # m: negative = braked earlier than reference
    apex_speed_delta: float      # km/h: negative = slower apex than reference
    throttle_pickup_delta: float  # m: negative = back on throttle earlier
    exit_slip_delta: float       # positive = more wheelspin than reference
    # absolute reference/current values, for prompt context
    current: Corner = None  # type: ignore[assignment]
    reference: Corner = None  # type: ignore[assignment]

    @property
    def time_cost_proxy(self) -> float:
        """A rough, unit-free "how much did this corner hurt" score.

        Slower apex speed and later throttle pick-up both cost lap time; more
        exit slip scrubs speed. Used only to rank which corners to coach on.
        """
        return (
            max(0.0, -self.apex_speed_delta) * 1.0        # km/h lost at apex
            + max(0.0, self.throttle_pickup_delta) * 0.5   # metres late to power
            + max(0.0, self.exit_slip_delta) * 20.0        # instability penalty
        )

    @property
    def improvement_proxy(self) -> float:
        """Positive score for corner gains vs. the reference lap."""
        return (
            max(0.0, self.apex_speed_delta) * 1.0          # km/h gained at apex
            + max(0.0, -self.throttle_pickup_delta) * 0.5  # earlier throttle pickup
            + max(0.0, -self.exit_slip_delta) * 20.0       # cleaner exit, less wheelspin
            + max(0.0, self.brake_point_delta) * 0.2        # later, more committed braking
        )


def compute_deltas(
    current: List[Corner],
    reference: List[Corner],
    max_match_distance: float = 120.0,
) -> List[CornerDelta]:
    """Match current corners to reference corners by braking point and diff them.

    Matching is one-to-one: candidate (current, reference) pairs within
    ``max_match_distance`` are assigned greedily closest-first, and each
    reference corner is used at most once. This avoids two nearby current
    corners (a chicane, or a brake-tap split) both binding to the same
    reference corner.
    """
    # Build all candidate pairs within range, then assign closest-first.
    pairs = []
    for ci, corner in enumerate(current):
        for ri, ref in enumerate(reference):
            gap = abs(ref.brake_point - corner.brake_point)
            if gap <= max_match_distance:
                pairs.append((gap, ci, ri))
    pairs.sort(key=lambda p: p[0])

    used_current: set[int] = set()
    used_reference: set[int] = set()
    matched: dict[int, int] = {}  # current index -> reference index
    for gap, ci, ri in pairs:
        if ci in used_current or ri in used_reference:
            continue
        matched[ci] = ri
        used_current.add(ci)
        used_reference.add(ri)

    deltas: List[CornerDelta] = []
    for ci, corner in enumerate(current):
        if ci not in matched:
            continue
        ref = reference[matched[ci]]
        deltas.append(
            CornerDelta(
                corner_index=corner.index,
                brake_point_delta=corner.brake_point - ref.brake_point,
                apex_speed_delta=corner.apex_speed - ref.apex_speed,
                throttle_pickup_delta=corner.throttle_pickup - ref.throttle_pickup,
                exit_slip_delta=corner.max_exit_slip - ref.max_exit_slip,
                current=corner,
                reference=ref,
            )
        )
    return deltas


def worst_corners(deltas: List[CornerDelta], n: int = config.WORST_CORNERS_TO_REPORT) -> List[CornerDelta]:
    """The ``n`` corners that cost the most time this lap, worst first."""
    return sorted(deltas, key=lambda d: d.time_cost_proxy, reverse=True)[:n]


def best_corners(deltas: List[CornerDelta], n: int = config.WORST_CORNERS_TO_REPORT) -> List[CornerDelta]:
    """The ``n`` corners where the current lap genuinely improved versus the reference."""
    return sorted(
        (d for d in deltas if d.improvement_proxy > 0.0),
        key=lambda d: d.improvement_proxy,
        reverse=True,
    )[:n]
