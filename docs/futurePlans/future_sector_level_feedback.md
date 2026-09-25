# Future Roadmap: Sector-Level Feedback

## 1. The Goal

The AI Coach now delivers **corner-level** positive feedback: after every lap it praises
the corners where the driver improved on their reference lap (see `best_corners` in
`corners.py` and the "IMPROVED" section in `ai_coach.py`) alongside the corners that cost
time. The next step is to broaden the same praise-and-coach treatment to **sectors** — the
larger, contiguous stretches of track that the game already times natively — so the driver
hears where they gained or lost time at a coarser, more strategic granularity than the
individual braking zone.

* **Corner feedback answers:** "Turn 7 was strong — 6 km/h more at the apex."
* **Sector feedback answers:** "Sector 2 was your best all session — two tenths up on your PB."

Both live side by side: a sector headline framing the lap, then corner-level detail for the
actionable specifics.

## 2. The Core Challenge: There Is No Sector Model Yet

The current pipeline tracks two things: **corners** (derived from braking zones, indexed by
`m_lapDistance`) and **whole-lap time**. It has no concept of a sector. Everything the delta
engine and the coach consume flows from `extract_corners(lap)` and `lap.lap_time_ms`. To
praise sectors we need to introduce sector timing as a first-class feature without disturbing
the corner path that already works.

F1 25 sends sector times in the `LapData` packet (`m_sector1TimeInMS`, `m_sector2TimeInMS`,
and the in-progress `m_sector` index), so the raw data is available — it simply isn't parsed,
aggregated, or stored today.

## 3. Implementation Phases

### Phase 1: Capture Sector Times in the Aggregator

Extend `packets.py` to decode the sector fields from `LapData`, and have
`TelemetryAggregator` (in `telemetry.py`) record per-sector split times as it builds a lap.
Sector 3 is derived: `lap_time_ms - sector1 - sector2`.

* **Data structure:** add `sector_times_ms: list[int]` (length 3) to the `Lap` dataclass.
* **Boundary detection:** watch `m_sector` transitions rather than trusting a single packet,
  so a dropped UDP frame at the split line doesn't lose a sector.
* **Backward compatibility:** default `sector_times_ms` to an empty list so existing tests
  and the corner path are untouched when the field is absent.

### Phase 2: Persist Reference Sectors

Mirror the existing corner-reference persistence (`reference.py`). When a lap becomes the new
PB, save its three sector splits alongside the corner features. This gives the delta engine a
per-sector benchmark to compare against.

* **Optional enhancement:** also track the *best individual sector* seen this session (not
  just the sectors of the single best lap). This is the natural bridge to the Macro-Sector
  Ideal described in [`future_theoretical_optimal.md`](future_theoretical_optimal.md) —
  sector splits almost always fall on straights, so summing best sectors is mathematically
  safe.

### Phase 3: Sector Delta Engine

Add a `SectorDelta` alongside `CornerDelta` in `corners.py`:

```
@dataclass(slots=True)
class SectorDelta:
    sector_index: int          # 1, 2, or 3
    time_delta_ms: int         # negative = faster than reference
```

Then add the sector equivalents of the corner ranking helpers:

* `best_sectors(deltas)` — sectors that beat the reference, biggest gain first (mirrors
  `best_corners`).
* `worst_sectors(deltas)` — sectors that lost time (mirrors `worst_corners`).

This keeps the "only praise genuine improvements / only coach genuine losses" invariant that
the corner path already enforces.

### Phase 4: Wire Sectors Into the Coach

Extend `format_deltas_to_prompt()` and `_offline_advice()` in `ai_coach.py` to accept the
sector deltas and open with a sector headline before the corner detail. The offline generator
gets a `_sector_headline()` helper analogous to `_offline_praise()`.

* **App wiring:** in `app.py`, compute sector deltas next to the corner deltas in
  `_handle_completed_lap` and pass them through `self.ai.coach(...)`.
* **Config:** add `SECTORS_TO_PRAISE` / `SECTORS_TO_COACH` knobs to `config.py` (default: 1
  each), matching `BEST_CORNERS_TO_REPORT` / `WORST_CORNERS_TO_REPORT`.

## 4. Enhanced AI Prompting

Update the Gemini system prompt so the engineer frames the lap at the sector level first,
then drills into corners — the way a real race engineer reads a lap.

* **Prompt example:** *"Big lap — Sector 2 was two tenths up on your best, that's where you
  made the time. Turn 7 in particular, 6 km/h more at the apex. You gave a little back in
  Sector 3; brake five meters later into the final chicane and it's all there."*

## 5. Why Sectors Are Worth the Extra Work

Corner feedback is precise but can feel like a firehose on a long lap. A sector headline gives
the driver a mental model of *where* the lap was won or lost before the specifics land — the
same reason real race engineers call sector deltas over the radio before dissecting a single
corner. It also unlocks the Macro-Sector Ideal stepping stone in the Theoretical Optimal Lap
roadmap without committing to full micro-sector slicing.
