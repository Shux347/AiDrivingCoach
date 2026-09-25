"""Binary decoding of F1 25 UDP telemetry packets.

All layouts are little-endian, byte-packed (no alignment padding) — hence the
``<`` prefix on every struct format string, which is what makes e.g. the
unaligned ``uint64`` ``m_sessionUID`` at offset 7 of the header decode
correctly.

Only the packets the coach needs are fully parsed:

============  ==================  =====================================
Packet id     Struct              What we pull out
============  ==================  =====================================
2             Lap Data            lap distance, lap number, sector, valid
6             Car Telemetry       speed, throttle, brake, steer, gear
13            Motion Ex           wheel slip ratio / slip angle (player)
============  ==================  =====================================

Wheel-array ordering for every ``[4]`` field is **[RL, RR, FL, FR]**
(Rear-Left, Rear-Right, Front-Left, Front-Right). So rear wheelspin lives at
indices 0/1 and front slip angle at indices 2/3.

Layouts verified against the F1 25 UDP specification (packet format 2025) and
cross-checked with community parsers (MacManley/f1-25-udp, Fredrik2002).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import NamedTuple, Optional

# ---------------------------------------------------------------------------
# Packet ids we care about
# ---------------------------------------------------------------------------
PACKET_ID_LAP_DATA = 2
PACKET_ID_CAR_TELEMETRY = 6
PACKET_ID_MOTION_EX = 13

# Wheel array indices (order is [RL, RR, FL, FR])
WHEEL_RL, WHEEL_RR, WHEEL_FL, WHEEL_FR = 0, 1, 2, 3
REAR_WHEELS = (WHEEL_RL, WHEEL_RR)
FRONT_WHEELS = (WHEEL_FL, WHEEL_FR)

NUM_CARS = 22

# ---------------------------------------------------------------------------
# PacketHeader — 29 bytes, prepended to every packet
# ---------------------------------------------------------------------------
_HEADER_FMT = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 29
_header_struct = struct.Struct(_HEADER_FMT)
assert HEADER_SIZE == 29


class PacketHeader(NamedTuple):
    packet_format: int          # e.g. 2025
    game_year: int              # 25
    game_major_version: int
    game_minor_version: int
    packet_version: int
    packet_id: int              # which packet type follows
    session_uid: int
    session_time: float
    frame_identifier: int
    overall_frame_identifier: int
    player_car_index: int       # index of THIS player's car in the per-car arrays
    secondary_player_car_index: int


def parse_header(data: bytes) -> Optional[PacketHeader]:
    """Decode the 29-byte header. Returns None if the datagram is too short."""
    if len(data) < HEADER_SIZE:
        return None
    return PacketHeader._make(_header_struct.unpack_from(data, 0))


# ---------------------------------------------------------------------------
# Car Telemetry (packet id 6) — per-car entry is 60 bytes
# ---------------------------------------------------------------------------
_TELEMETRY_FMT = "<H3fBbHBBH4H4B4BH4f4B"
TELEMETRY_ENTRY_SIZE = struct.calcsize(_TELEMETRY_FMT)  # 60
_telemetry_struct = struct.Struct(_TELEMETRY_FMT)
assert TELEMETRY_ENTRY_SIZE == 60


@dataclass(slots=True)
class CarTelemetry:
    """The subset of CarTelemetryData the coach uses (one car)."""

    speed: int          # km/h
    throttle: float     # 0.0 .. 1.0
    steer: float        # -1.0 (full left) .. 1.0 (full right)
    brake: float        # 0.0 .. 1.0
    gear: int           # -1 (R), 0 (N), 1..8
    engine_rpm: int
    drs: int            # 0 off / 1 on


def parse_car_telemetry(data: bytes, header: PacketHeader) -> Optional[CarTelemetry]:
    """Extract the *player's* car telemetry from a packet-id-6 datagram."""
    start = HEADER_SIZE + header.player_car_index * TELEMETRY_ENTRY_SIZE
    if len(data) < start + TELEMETRY_ENTRY_SIZE:
        return None
    v = _telemetry_struct.unpack_from(data, start)
    # v layout: speed, throttle, steer, brake, clutch, gear, engineRPM, drs,
    #           revLightsPercent, revLightsBitValue, brakesTemp[4], ...
    return CarTelemetry(
        speed=v[0],
        throttle=v[1],
        steer=v[2],
        brake=v[3],
        gear=v[5],
        engine_rpm=v[6],
        drs=v[7],
    )


# ---------------------------------------------------------------------------
# Lap Data (packet id 2) — per-car entry is 57 bytes
# ---------------------------------------------------------------------------
_LAPDATA_FMT = "<IIHBHBHBHBfffBBBBBBBBBBBBBBBHHBfB"
LAPDATA_ENTRY_SIZE = struct.calcsize(_LAPDATA_FMT)  # 57
_lapdata_struct = struct.Struct(_LAPDATA_FMT)
assert LAPDATA_ENTRY_SIZE == 57

# Field indices into the unpacked LapData tuple (see module docstring / spec).
_LD_LAST_LAP_TIME_MS = 0
_LD_CURRENT_LAP_TIME_MS = 1
_LD_LAP_DISTANCE = 10       # float, metres
_LD_TOTAL_DISTANCE = 11     # float, metres
_LD_CURRENT_LAP_NUM = 14    # uint8
_LD_SECTOR = 17            # uint8 (0/1/2)
_LD_CURRENT_LAP_INVALID = 18  # uint8 (0 valid / 1 invalid)


@dataclass(slots=True)
class LapData:
    """The subset of LapData the coach uses (one car)."""

    lap_distance: float         # metres around current lap (can be < 0 pre S/F)
    total_distance: float       # metres travelled this session
    current_lap_num: int
    sector: int                 # 0=S1, 1=S2, 2=S3
    current_lap_invalid: int    # 0=valid, 1=invalid
    last_lap_time_ms: int
    current_lap_time_ms: int


def parse_lap_data(data: bytes, header: PacketHeader) -> Optional[LapData]:
    """Extract the *player's* lap data from a packet-id-2 datagram."""
    start = HEADER_SIZE + header.player_car_index * LAPDATA_ENTRY_SIZE
    if len(data) < start + LAPDATA_ENTRY_SIZE:
        return None
    v = _lapdata_struct.unpack_from(data, start)
    return LapData(
        lap_distance=v[_LD_LAP_DISTANCE],
        total_distance=v[_LD_TOTAL_DISTANCE],
        current_lap_num=v[_LD_CURRENT_LAP_NUM],
        sector=v[_LD_SECTOR],
        current_lap_invalid=v[_LD_CURRENT_LAP_INVALID],
        last_lap_time_ms=v[_LD_LAST_LAP_TIME_MS],
        current_lap_time_ms=v[_LD_CURRENT_LAP_TIME_MS],
    )


# ---------------------------------------------------------------------------
# Motion Ex (packet id 13) — PLAYER car only, no per-car array. 244-byte body.
# ---------------------------------------------------------------------------
_MOTIONEX_FMT = "<61f"  # 61 consecutive floats after the header
MOTIONEX_BODY_SIZE = struct.calcsize(_MOTIONEX_FMT)  # 244
_motionex_struct = struct.Struct(_MOTIONEX_FMT)
assert MOTIONEX_BODY_SIZE == 244

# Float indices (0-based) into the 61-float body, i.e. after the 29-byte header.
# Body byte offset = float_index * 4; packet byte offset = 29 + float_index * 4.
#   floats 0-3   suspensionPosition[4]
#   floats 4-7   suspensionVelocity[4]
#   floats 8-11  suspensionAcceleration[4]
#   floats 12-15 wheelSpeed[4]
#   floats 16-19 wheelSlipRatio[4]   <-- byte 93
#   floats 20-23 wheelSlipAngle[4]   <-- byte 109
_MEX_SLIP_RATIO_BASE = 16
_MEX_SLIP_ANGLE_BASE = 20


@dataclass(slots=True)
class MotionEx:
    """Player-car motion extras the coach uses."""

    wheel_slip_ratio: tuple[float, float, float, float]   # [RL, RR, FL, FR]
    wheel_slip_angle: tuple[float, float, float, float]   # [RL, RR, FL, FR]

    @property
    def max_rear_slip_ratio(self) -> float:
        """Peak rear-wheel spin magnitude (corner-exit instability / wheelspin)."""
        return max(abs(self.wheel_slip_ratio[i]) for i in REAR_WHEELS)

    @property
    def max_front_slip_angle(self) -> float:
        """Peak front-wheel slip-angle magnitude (understeer indicator)."""
        return max(abs(self.wheel_slip_angle[i]) for i in FRONT_WHEELS)


def parse_motion_ex(data: bytes) -> Optional[MotionEx]:
    """Extract the player car's slip data from a packet-id-13 datagram."""
    if len(data) < HEADER_SIZE + MOTIONEX_BODY_SIZE:
        return None
    v = _motionex_struct.unpack_from(data, HEADER_SIZE)
    sr = v[_MEX_SLIP_RATIO_BASE:_MEX_SLIP_RATIO_BASE + 4]
    sa = v[_MEX_SLIP_ANGLE_BASE:_MEX_SLIP_ANGLE_BASE + 4]
    return MotionEx(wheel_slip_ratio=sr, wheel_slip_angle=sa)
