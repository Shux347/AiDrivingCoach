# Network setup — game on PC, coach on Mac

Run F1 25 on your Windows PC and the coach on your Mac, over your home LAN. The
game unicasts UDP telemetry to the Mac; the coach listens on `0.0.0.0:20777`.

## 1. Confirm both machines are on the same subnet

- **Mac LAN IP:** `192.168.1.13` (subnet `192.168.1.x`, mask `255.255.255.0`).
  Re-check any time with:
  ```bash
  ipconfig getifaddr en0
  ```
  > Note: the Mac also has a `10.60.64.110` address on a point-to-point/VPN
  > interface. **Do not** use that — the PC can't reach it. Use `192.168.1.13`.
- **PC:** open `cmd` → `ipconfig` → confirm its IPv4 is also `192.168.1.x`.
- If the Mac's IP tends to change, set a DHCP reservation for it on your router
  so you don't have to re-enter it in the game.

## 2. Configure the game (on the PC)

`Settings → Telemetry Settings`:

| Setting | Value | Why |
|---|---|---|
| **UDP Telemetry** | **On** | Master switch — off means no packets at all. |
| **UDP Broadcast Mode** | **Off** | Off = unicast to the one IP below. On ignores the IP field and floods the subnet. |
| **UDP IP Address** | **`192.168.1.13`** | The Mac's LAN IP. Only used when Broadcast is Off. Type every octet carefully. |
| **UDP Port** | **`20777`** | Must match the coach's listen port. |
| **UDP Send Rate** | **60 Hz** (20 Hz is fine too) | Higher = smoother telemetry, more packets. |
| **UDP Format** | **`2025`** | **Critical.** Any other value decodes to garbage — the coach now warns and drops mismatched packets. |
| **Your Telemetry** | **Public** | Ensures your own car's throttle/brake/inputs are populated. |

## 3. Firewall

- **Mac (receiving):** the app firewall must allow inbound UDP to the Python
  binary. On this machine it's already permitted, and stealth mode does not
  block inbound UDP to a listening socket. If packets don't arrive, allow it:
  System Settings → Network → Firewall → Options → add your `python3` and set
  "Allow incoming connections", or temporarily turn the firewall off to test.
- **PC (sending):** Windows allows outbound UDP by default. If the active
  network profile is "Public", switch the home network to **Private**.

## 4. Verify the connection

On the Mac, **before** launching the full coach, run the sniffer:

```bash
cd F1DrivingCoach
PYTHONPATH=src python scripts/sniff.py
```

Then drive in the game. You want to see a line like:

```
[hb] src=192.168.1.50 fmt=2025 | 118 pkt/s (2954 total) | id2=590 id6=1181 id13=1181 | 287 km/h | lap 512 m / total 3.4 km
```

Reading it:
- **`src=…`** — the PC's IP. Proves cross-machine delivery is working.
- **`fmt=2025`** — matches. A `⚠MISMATCH` here means fix the game's UDP Format.
- **`id2 / id6 / id13`** — Lap Data / Car Telemetry / Motion Ex, the three the
  coach uses. All three should climb.
- **`NO PACKETS yet`** instead → nothing is arriving. Check, in order: game UDP
  on, IP set to `192.168.1.13`, port `20777`, both on `192.168.1.x`, Mac
  firewall, and Wi-Fi "client isolation"/"AP isolation" off on the router.

## 5. Run the coach

```bash
PYTHONPATH=src python -m f1coach.app --track <trackname>
```

The same `[hb]` heartbeat prints every few seconds so you always know packets
are flowing. Silence it with `F1COACH_HEARTBEAT=0`. Your first clean lap becomes
the reference; every lap after gets coached against it.

## Troubleshooting quick reference

| Symptom | Likely cause |
|---|---|
| `NO PACKETS yet` | Game UDP off, wrong IP/port, different subnet, Mac firewall, or Wi-Fi client isolation. |
| `fmt=… ⚠MISMATCH` | Game UDP Format isn't 2025. |
| Packets arrive but "none decode" | Wrong UDP Format, or an unusual player car index. |
| Works wired, not on Wi-Fi | Router AP/client isolation, or the machines are on different SSIDs/VLANs. |
