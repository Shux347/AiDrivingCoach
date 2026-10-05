# F1 Driving Coach

A local Python telemetry coach for EA Sports F1 25. It listens to live UDP packets,
tracks lap validity, stores a personal-best reference lap, extracts the key
corner metrics for each lap, and gives deterministic race-engineer feedback over
text-to-speech.

This project is intentionally offline and self-contained: it does not require a
Google Gemini key or any external AI service.

> 📻 RADIO: Turn 10 improved the most: earlier throttle pickup. Turn 1 cost you the most this lap: late acceleration. Turn 7 was the next change: small time loss. Brake consistently, then accelerate as soon as the car is rotated.

## What the current app does

The implementation in [src/f1coach](src/f1coach) is a deterministic pipeline:

1. UDP receiver — listens on port 20777, decodes the F1 25 packet header and the
   packet IDs used by the app.
2. Telemetry aggregation — merges Lap Data, Car Telemetry, and Motion Ex into
   lap samples indexed by `m_lapDistance`, not by wall-clock time.
3. Corner extraction — identifies braking-defined corners, measures the key
   features on each turn, and compares them against the stored reference lap.
4. Coaching and audio — ranks the worst corners, applies fixed thresholds, and
   plays the radio-style advice through `edge-tts` with offline fallbacks.

The app also renders lap charts and persists reference laps per track in
`reference_laps/`.

## Packet coverage

The current implementation decodes these F1 25 packet types:

| Packet ID | Struct | Fields used |
| --- | --- | --- |
| 2 | Lap Data | `m_lapDistance`, `m_currentLapNum`, `m_currentLapInvalid`, `m_sector` |
| 6 | Car Telemetry | `m_speed`, `m_throttle`, `m_brake`, `m_steer`, `m_gear` |
| 13 | Motion Ex | `m_wheelSlipRatio`, `m_wheelSlipAngle` |

The parser expects the 2025 UDP format and drops mismatched packets instead of
coaching on corrupted data.

## Quick start

```bash
cd F1DrivingCoach
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Running the coach

```bash
PYTHONPATH=src python -m f1coach.app --track silverstone
```

`--track` resolves the circuit name and keys the reference lap file in
`reference_laps/`. Your first clean lap becomes the benchmark; any faster valid
lap replaces it.

### Useful flags

| Flag | Meaning |
| --- | --- |
| `--track TRACK` | Required circuit name, for example `silverstone`, `mexico`, or `brazil` |
| `--reset-reference` | Deletes the saved reference lap for that track before the next run |
| `--coach-invalid` | Coaches invalidated laps as well as clean laps |

### Mock/no-game replay

```bash
# terminal 1
F1COACH_TTS=0 PYTHONPATH=src python -m f1coach.app --track silverstone

# terminal 2
python scripts/mock_sender.py
```

This replays synthetic telemetry so you can test the app without running F1 25.

### Connectivity sniffer

Run the sniffer before the full coach to confirm UDP delivery is working:

```bash
PYTHONPATH=src python scripts/sniff.py
python scripts/sniff.py --mock
```

The output includes a heartbeat with sender IP, packet rate, packet counts, and
live speed. This is useful when the game is running on a different machine.

## Configuration

The project uses environment variables defined in [src/f1coach/config.py](src/f1coach/config.py)
and the sample file `.env.example`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `F1COACH_PORT` | `20777` | UDP listen port |
| `F1COACH_EXPECTED_FORMAT` | `2025` | Required telemetry format |
| `F1COACH_HEARTBEAT` | `1` | Enable or silence the live heartbeat |
| `F1COACH_TTS` | `1` | Disable spoken audio and print only |
| `F1COACH_TTS_ENGINE` | `edge` | Preferred TTS engine |
| `F1COACH_VOICE` | `en-GB-RyanNeural` | Edge voice selection |
| `F1COACH_COACH_INVALID` | `0` | Allow coaching on invalidated laps |

## Current architecture

```text
F1 25 UDP telemetry
        │
        ▼
[Receiver thread] ──▶ [Frame queue]
        │
        ▼
[TelemetryAggregator] ──▶ [Lap queue]
        │
        ▼
[Corner extraction + delta comparison]
        │
        ▼
[Deterministic coaching engine]
        │
        ├─▶ chart rendering
        └─▶ TTS output (edge-tts / pyttsx3 / macOS say)
```

## Project layout

```text
src/f1coach/
  ai_coach.py     # deterministic rule engine for coach messages
  app.py         # runtime wiring for receiver + aggregator + coach
  config.py      # environment-based runtime configuration
  corners.py     # corner extraction and delta calculations
  mock.py        # synthetic packet builders / track simulator
  packets.py     # packet decoding and binary layout helpers
  receiver.py    # UDP listener and heartbeat monitor
  reference.py   # reference-lap persistence and reset logic
  telemetry.py   # lap assembly and distance-based aggregation
  tts.py         # spoken output with fallback engines
  visualization.py
scripts/
  mock_sender.py
  sniff.py
docs/
  network_setup.md
  project_specification.md
reference_laps/
  ref_*.json
  charts/
tests/
```

## Documentation

- [docs/network_setup.md](docs/network_setup.md) — cross-machine game setup and firewall guidance.
- [docs/project_specification.md](docs/project_specification.md) — current architecture and implementation notes.
- [docs/futurePlans](docs/futurePlans) — long-range ideas and design exploration, not the current runtime path.

## Tests

```bash
PYTHONPATH=src pytest -q
```

The suite exercises the packet decoders, lap aggregation, corner extraction, and
radio-coaching logic without requiring a live game session.
