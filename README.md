# F1 25 AI Driver Coach

A local Python app that reads live UDP telemetry from **EA Sports F1 25**,
reduces each lap into corner-by-corner performance features, compares them
against your personal-best reference lap, and delivers punchy race-engineer
feedback over text-to-speech — automatically, at the end of every lap.

> *"You braked 16 meters too early into Turn 1, losing 12 km/h at the apex. Get
> the car rotated sooner and feed the throttle earlier on exit."*

## How it works

Four modular layers, wired across three threads so telemetry ingestion is never
blocked by network calls or audio playback:

```
 F1 25  ──UDP 20777──▶  [Receiver thread]  ──▶ frame queue
                                                  │
                              [Aggregator thread]  ┤  index samples by lap
                                                  │   distance; detect lap end
                                                  ▼
                                [Coaching thread]  ── extract corners → diff vs
                                                      personal best → deterministic
                                                      rule engine → speak the team radio
```

1. **UDP Receiver** ([receiver.py](src/f1coach/receiver.py)) — binds `0.0.0.0:20777`,
   decodes the 29-byte packet header, parses the three packets we need, and
   queues lightweight frames.
2. **Telemetry Aggregator** ([telemetry.py](src/f1coach/telemetry.py)) — merges
   the packet streams and stores every sample **indexed by `m_lapDistance`** so
   laps align *spatially*, not temporally. A lap is "done" when
   `m_currentLapNum` increments.
3. **Corner / Delta Engine** ([corners.py](src/f1coach/corners.py)) — detects
   braking-defined corners and reduces each to four features (braking point,
   apex speed, throttle pick-up point, max exit slip), then diffs against the
   reference lap.
4. **Coaching + Audio** ([ai_coach.py](src/f1coach/ai_coach.py), [tts.py](src/f1coach/tts.py)) —
   scores the two worst corners with fixed mathematical thresholds and speaks the
   result via **edge-tts** (with an offline `pyttsx3` / macOS `say` fallback).

### The packets it decodes

| Packet id | Struct           | Fields used                                          |
|-----------|------------------|------------------------------------------------------|
| 2         | Lap Data         | `m_lapDistance`, `m_currentLapNum`, `m_sector`, `m_currentLapInvalid` |
| 6         | Car Telemetry    | `m_speed`, `m_throttle`, `m_brake`, `m_steer`, `m_gear` |
| 13        | Motion Ex        | `m_wheelSlipRatio` (rear wheelspin), `m_wheelSlipAngle` (front understeer) |

Byte layouts (little-endian, byte-packed) are verified against the F1 25 UDP
spec — header = 29 B, LapData entry = 57 B, CarTelemetry entry = 60 B, Motion
Ex body = 244 B. Wheel arrays are ordered `[RL, RR, FL, FR]`.

## Setup

```bash
cd F1DrivingCoach
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

The coach runs entirely offline with a deterministic rule engine, so you can
build and demo the full pipeline without any external AI service or key.

### Enable telemetry in F1 25

Settings → Telemetry Settings:
* **UDP Telemetry:** On
* **UDP Broadcast Mode:** Off (or point IP at this machine)
* **UDP Port:** `20777`
* **UDP Format:** `2025`

> **Running the game and coach on different machines** (e.g. game on a PC,
> coach on a Mac)? See [docs/network_setup.md](docs/network_setup.md) for the
> exact IP/firewall setup and how to verify the connection.

## Running

```bash
# The full coach (needs the game running, or the mock sender below)
PYTHONPATH=src python -m f1coach.app --track silverstone
```

`--track NAME` keys the reference-lap file (`reference_laps/ref_NAME.json`); your
first clean lap on that track becomes the benchmark, and any faster valid lap
replaces it.

### Resetting reference laps

To clear an existing reference lap for a circuit so your next clean lap becomes the new benchmark:

```bash
PYTHONPATH=src python -m f1coach.app --track silverstone --reset-reference
```

### CLI options

| Flag | Meaning |
|------|---------|
| `--track TRACK` | F1 25 circuit name (required, e.g. `silverstone`, `mexico`, `texas`) |
| `--reset-reference` | Reset / delete the stored reference lap for this track before running |
| `--coach-invalid` | Coach on invalidated laps as well as clean laps |

### Try it with no game (mock replay)

Two terminals:

```bash
# terminal 1 — the coach
F1COACH_TTS=0 PYTHONPATH=src python -m f1coach.app --track silverstone

# terminal 2 — synthetic telemetry: one clean lap, then a sloppy one
python scripts/mock_sender.py
```

You'll see lap 1 banked as the reference and lap 2 coached.

### Phase 1 sniffer (connectivity diagnostic)

Run this first to confirm the game is reaching this machine — it prints a live
heartbeat with the sender IP, packet rate, per-packet-id counts and speed:

```bash
PYTHONPATH=src python scripts/sniff.py   # live: [hb] status line every few seconds
python scripts/sniff.py --mock           # offline: replays synthetic packets
```

The main coach prints the same `[hb]` heartbeat, so you always know packets are
flowing even before a lap completes. Set `F1COACH_HEARTBEAT=0` to silence it.

## Configuration

All via env vars (see [config.py](src/f1coach/config.py) / `.env.example`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `F1COACH_PORT` | `20777` | UDP port |
| `F1COACH_EXPECTED_FORMAT` | `2025` | UDP packet format to accept; mismatches are flagged and dropped |
| `F1COACH_HEARTBEAT` | `1` | `0` silences the `[hb]` connection status line |
| `F1COACH_TTS` | `1` | `0` disables audio (prints only) |
| `F1COACH_TTS_ENGINE` | `edge` | `edge` or `pyttsx3` |
| `F1COACH_VOICE` | `en-GB-RyanNeural` | edge-tts voice |
| `F1COACH_COACH_INVALID` | `0` | `1` to coach on invalidated laps too |

## Tests

Pure-Python, no game or network needed (synthetic packets are byte-for-byte
valid):

```bash
python tests/test_packets.py    # struct round-trips
python tests/test_corners.py    # aggregator, corner extraction, deltas
python tests/test_e2e.py        # full in-process pipeline
```

## Project layout

```
src/f1coach/
  packets.py     # binary decode of F1 25 UDP packets (verified layouts)
  mock.py        # synthetic packet builders + track simulator
  receiver.py    # Thread 1: UDP listener
  telemetry.py   # Thread 2: distance-indexed aggregation, lap detection
  corners.py     # corner extraction + delta engine
  ai_coach.py    # deterministic rule-based coaching engine
  tts.py         # edge-tts / pyttsx3 / macOS `say`
  reference.py   # personal-best lap persistence
  app.py         # wires the three threads together
scripts/
  sniff.py       # Phase 1 standalone sniffer
  mock_sender.py # UDP replay for demos
tests/           # round-trip + pipeline tests
```
