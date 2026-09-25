# Future Roadmap: Authoritative Lap Validity (Session History Packet)

## 1. The Goal
Today the coach *infers* whether a lap was legal by watching the `m_currentLapInvalid`
flag tick over the live `LapData` stream and reasoning about lap boundaries,
flashbacks and restarts (see `TelemetryAggregator` in
[`src/f1coach/telemetry.py`](../src/f1coach/telemetry.py)). That heuristic now
works — it survives an in-place restart by detecting a drop in `m_totalDistance`
and re-syncing the sticky flag — but it is still a *reconstruction* of a fact the
game already knows.

The next evolution is to stop guessing and read the game's own verdict from
**`PacketSessionHistoryData` (packet ID 11)**, which carries an authoritative,
already-resolved validity bit for every completed lap. This removes an entire
class of edge cases and, as a bonus, unlocks **per-sector validity**.

## 2. Why This Is Better Than the Heuristic

| | Live-flag heuristic (current) | Session History (proposed) |
|---|---|---|
| Source of truth | We re-derive it from a noisy stream | Game's final, resolved record |
| Rewind / flashback / restart | Handled by `total_distance`-drop detection + re-sync | Irrelevant — the entry reflects the final state |
| Tuning knobs | `_REWIND_DROP_M` threshold | None |
| Sector-level validity | Not available | Free (bits `0x02/0x04/0x08`) |
| Failure mode | Mis-classify an exotic rewind pattern | Packet disabled / entry not yet populated |

The heuristic is proven on real hardware, so this is **additive insurance**, not
a rewrite. Packet 11 becomes the primary source; the existing sticky-flag logic
stays as the fallback.

## 3. The Packet
One `PacketSessionHistoryData` is emitted per car, cycling through all cars a few
times per second. The fields that matter:

* `m_carIdx` — which car this history belongs to. **Filter to `header.player_car_index`.**
* `m_numLaps` — how many lap entries are populated.
* `m_lapHistoryData[]` — one entry per lap. Each entry holds the lap time, three
  sector times, and a **`m_lapValidBitFlags`** bitfield:
  * `0x01` — lap valid (overall)
  * `0x02` — sector 1 valid
  * `0x04` — sector 2 valid
  * `0x08` — sector 3 valid

For a completed lap *N*, read entry `N-1`'s bitflags and test bit `0x01`. That
single bit **is** the answer.

### Proposed (unverified) byte layout
Derived from the F1 25 field list and internally self-consistent, but **not yet
confirmed against a real capture**:

* Lap-history entry: `<IHBHBHBB` — 14 bytes; `m_lapValidBitFlags` at entry offset 13.
* Array of entries begins at packet offset 36 (29-byte header + leading fields).
* Read entry *i*'s validity byte at absolute offset `36 + i*14 + 13`.
* `m_carIdx` at body offset 0, `m_numLaps` at body offset 1.

> ⚠ **Do not ship on these offsets blind.** Validate them against one real
> packet-11 datagram first (Phase 0).

## 4. Implementation Phases

### Phase 0: Verify the Layout (do this first)
Capture a single real packet-11 datagram and confirm the offsets before writing
any parsing the pipeline depends on.
* Temporarily log packet ID 11 in [`receiver.py`](../src/f1coach/receiver.py)
  (or extend `scripts/`), dump the raw bytes, and confirm `m_lapValidBitFlags`
  lands where §3 predicts for known valid/invalid laps.
* The existing `F1COACH_DEBUG_VALIDITY` trace machinery makes cross-checking the
  authoritative bit against our heuristic `sticky` value trivial.

### Phase 1: Parse the Packet
* Add `PACKET_ID_SESSION_HISTORY = 11` and a `parse_session_history` to
  [`packets.py`](../src/f1coach/packets.py), returning a small dataclass:
  `{ car_idx, num_laps, lap_valid_bitflags: list[int] }` (player car only).
* Add a matching `build_session_history_packet` to
  [`mock.py`](../src/f1coach/mock.py) so it is unit-testable offline.

### Phase 2: Wire It Into the Frame Stream
* Extend the `Frame` dataclass and `UDPReceiver._decode` to carry an optional
  `history` payload (mirroring how `lap` / `telemetry` / `motion` are handled).

### Phase 3: Use It as the Source of Truth
* In `TelemetryAggregator`, cache the latest player `lap_valid_bitflags`.
* At lap finalisation, look up the just-completed lap number's bit `0x01`:
  * **valid bit present →** authoritative valid.
  * **valid bit clear →** authoritative invalid.
  * **entry missing / packet never seen →** fall back to the current sticky-flag
    result.
* Handle the **timing skew**: the history entry for lap *N* can lag the
  lap-boundary `LapData` frame by a frame or two. Either wait briefly for the
  authoritative bit before firing the completion callback, or fire with the
  heuristic value and backfill/correct once the entry arrives.

### Phase 4: Sector-Level Validity (bonus)
* Surface bits `0x02/0x04/0x08` on the completed `Lap` so coaching can say
  *"lap was valid but sector 2 was invalidated"* — richer than the binary flag
  we expose today.

## 5. Testing
* Offline unit tests using `build_session_history_packet`: a lap whose bit
  `0x01` is clear must finalise **invalid** even if the live flag never fired,
  and vice-versa.
* A fallback test: with no packet-11 ever delivered, behaviour must be identical
  to today's heuristic (all current `tests/test_lap_validity.py` cases still pass).
* Regression guard: the real-hardware in-place-restart scenario must resolve to
  **valid** via the authoritative bit, matching the heuristic result we verified.

## 6. Risks & Notes
* **Layout confidence** — offsets are inferred, not spec-confirmed; Phase 0 is a
  hard prerequisite.
* **Packet availability** — a user can disable individual packets in the F1 25
  telemetry menu. The fallback path keeps the coach correct if packet 11 is off.
* **Keep the heuristic** — it is proven and cheap; it remains the safety net, not
  dead code.
