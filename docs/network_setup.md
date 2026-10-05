# Network setup — game on PC, coach on Mac

This is the current cross-machine setup for the project: run F1 25 on a Windows
PC and the coach on a Mac or other local machine on the same home LAN. The game
sends UDP telemetry to the coach, which listens on `0.0.0.0:20777`.

## 1. Confirm both machines are on the same subnet

- **Mac LAN IP:** `192.168.1.13` (subnet `192.168.1.x`, mask `255.255.255.0`).
  Re-check any time with:

  ```bash
  ipconfig getifaddr en0
  ```

  > The Mac may also have a VPN address such as `10.60.64.110`; do not use that
  > for the game telemetry target because the PC cannot reach it directly.

- **PC:** open `cmd` → `ipconfig` and confirm its IPv4 is also in the same
  `192.168.1.x` range.
- If the Mac's address changes often, set a DHCP reservation in your router so
  the PC always has the same target IP.

## 2. Configure the game

Open `Settings → Telemetry Settings` and use:

| Setting | Value |
| --- | --- |
| **UDP Telemetry** | **On** |
| **UDP Broadcast Mode** | **Off** |
| **UDP IP Address** | **`192.168.1.13`** |
| **UDP Port** | **`20777`** |
| **UDP Send Rate** | **60 Hz** (20 Hz is acceptable too) |
| **UDP Format** | **`2025`** |
| **Your Telemetry** | **Public** |

## 3. Firewall and network rules

- **Mac (receiving):** allow inbound UDP traffic to the Python runtime or disable
  the firewall temporarily for the test.
- **PC (sending):** outbound UDP is usually allowed by default, but set the
  network profile to **Private** if Windows is blocking local LAN traffic.
- Turn off Wi‑Fi client isolation or AP isolation if your router is separating
  client devices on the same SSID.

## 4. Verify the connection before starting the full coach

On the Mac, run:

```bash
cd F1DrivingCoach
PYTHONPATH=src python scripts/sniff.py
```

Then drive in the game. A healthy session prints a line like:

```text
[hb] src=192.168.1.50 fmt=2025 | 118 pkt/s (2954 total) | id2=590 id6=1181 id13=1181 | 287 km/h | lap 512 m / total 3.4 km
```

What to look for:

- `src=…` — proves telemetry is reaching the coach.
- `fmt=2025` — matches the app's expected format.
- `id2 / id6 / id13` — the three packet families the app consumes.
- `NO PACKETS yet` — means the game is not sending or the network path is wrong.

## 5. Run the coach

```bash
PYTHONPATH=src python -m f1coach.app --track <trackname>
```

The same heartbeat output continues while the app is running. Silence it with
`F1COACH_HEARTBEAT=0` if you want a quieter console.

## Troubleshooting quick reference

| Symptom | Likely cause |
| --- | --- |
| `NO PACKETS yet` | Game UDP off, wrong IP/port, wrong subnet, firewall blocking, or router isolation |
| `fmt=… ⚠MISMATCH` | Game UDP format is not set to `2025` |
| Packets arrive but decode to zero values | Wrong UDP Format or unusual telemetry layout |
| Works wired but not over Wi‑Fi | Client isolation or different SSIDs/VLANs |

The current app workflow is deterministic and offline: it does not depend on an
external AI service, and the same UDP verification steps apply before any lap is
coached.
