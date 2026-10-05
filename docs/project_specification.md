# Project specification and current implementation

This document describes the architecture that is actually implemented in the
repository today. It reflects the current deterministic coaching workflow, not the
older LLM-driven prototype that used Gemini.

## Status

The codebase is currently an offline, local race-engineering coach for F1 25. It
reads UDP telemetry, reconstructs laps in distance space, compares each lap to a
stored personal-best reference, and produces deterministic coaching advice using
fixed rules and thresholds.

The current implementation does not call an external AI service and does not
require any API key.

## Project goal

The app should help a driver improve lap-by-lap by:

- listening to live telemetry from F1 25,
- tracking the relevant packet streams without blocking on slow work,
- extracting meaningful turn-level metrics,
- comparing the current lap against a personal best,
- telling the driver what changed and what to fix,
- speaking the advice over the radio using TTS.

## Architecture

The live system is split into a small set of cooperating components:

1. UDP receiver
   - binds to `0.0.0.0:20777`,
   - decodes packet headers and the relevant packet bodies,
   - pushes lightweight `Frame` objects to a queue.

2. Telemetry aggregator
   - consumes frames in order,
   - merges lap data, telemetry, and motion snapshots,
   - keeps samples keyed by `m_lapDistance`,
   - finalises a lap when `m_currentLapNum` increments,
   - tracks invalid laps and restart/rewind edge cases.

3. Corner extraction and delta engine
   - detects braking-defined corners,
   - computes the key metrics for each turn,
   - standardises the corner catalog against the track reference,
   - compares current laps to the reference lap and ranks the worst corners.

4. Coaching and output
   - ranks the major deltas mathematically,
   - builds short radio-style coaching lines,
   - renders lap charts for debugging and visual inspection,
   - speaks the result using `edge-tts`, `pyttsx3`, or `say`.

## Data intake

The app consumes F1 25 UDP packets from the game and expects the 2025 packet
layout. It decodes the following packet IDs:

- Packet 2: Lap Data
  - `m_lapDistance`
  - `m_currentLapNum`
  - `m_currentLapInvalid`
  - `m_sector`

- Packet 6: Car Telemetry
  - `m_speed`
  - `m_throttle`
  - `m_brake`
  - `m_steer`
  - `m_gear`

- Packet 13: Motion Ex
  - rear slip ratio / rear wheelspin
  - front slip angle / understeer signal

The receiver rejects mismatched `F1COACH_EXPECTED_FORMAT` values instead of
trying to parse garbage data.

## Lap model and validity tracking

A core implementation rule is: never index telemetry by wall-clock time. The app
stores per-lap samples in distance space so that lap N and lap N+1 line up
spatially on track.

The aggregator keeps a sticky invalid-lap signal while a lap is in progress and
only finalises a completed lap when the lap number increments. It also handles:

- restart-to-garage and fresh-session resets,
- flashback / rewind conditions,
- stale UDP frames arriving out of order.

This protects the coach from false lap completions and from using wrong
validity state when the game resets or rewinds the session.

## Corner feature extraction

Each corner is reduced to a small set of features rather than sending raw
telemetry to an external model.

Current tracked features include:

- braking point distance,
- speed at the apex / minimum cornering speed,
- throttle-pickup point after the apex,
- rear wheelspin on corner exit,
- track-turn index / corner catalog matching.

This is the basis of the delta comparison against the personal-best track lap.

## Coaching logic

The current implementation deliberately avoids LLMs. Advice is generated from a
fixed, deterministic rule system in [src/f1coach/ai_coach.py](../src/f1coach/ai_coach.py).

The flow is:

- compare current corner metrics against the reference lap,
- rank the worst deltas,
- choose a small number of significant turn changes,
- build a short set of radio-style sentences with a standard voice.

This keeps the feedback fast, repeatable, and independent of network access.

## Reference-lap persistence

Reference laps are saved to `reference_laps/ref_<track>.json` and include:

- track name,
- lap time,
- extracted corner catalog,
- optional sample trace for charts and replay.

The app updates the stored benchmark when a valid lap is faster than the current
reference. Reset commands remove the saved reference for a track before the next
run.

## Runtime configuration

The project is configured mostly through environment variables in
[src/f1coach/config.py](../src/f1coach/config.py). The relevant settings include:

- UDP bind address and port,
- expected packet format,
- heartbeat options,
- TTS engine and voice,
- invalid-lap coaching flag,
- reference-lap directory,
- supported circuit list and aliases.

## Documentation map

- [README.md](../README.md) — quick start and day-to-day usage
- [docs/network_setup.md](network_setup.md) — cross-machine setup and verification
- [docs/futurePlans](futurePlans) — exploratory roadmap ideas and future design directions

The future-plan documents are deliberately separate from the current runtime
implementation; they are design explorations rather than the actual in-repo app
behavior.
