"""Synthetic F1 25 packet construction — for tests and offline/mock replay.

These builders produce byte-for-byte valid packets (correct header + correct
per-car array sizes) so the parser and the full pipeline can be exercised
without the game running. They are the inverse of :mod:`f1coach.packets`.
"""

from __future__ import annotations

import struct

from .packets import (
    HEADER_SIZE,
    LAPDATA_ENTRY_SIZE,
    NUM_CARS,
    PACKET_ID_CAR_TELEMETRY,
    PACKET_ID_LAP_DATA,
    PACKET_ID_MOTION_EX,
    TELEMETRY_ENTRY_SIZE,
    _HEADER_FMT,
    _LAPDATA_FMT,
    _MOTIONEX_FMT,
    _TELEMETRY_FMT,
)

_PACKET_FORMAT = 2025


def build_header(packet_id: int, player_car_index: int = 0, session_time: float = 0.0) -> bytes:
    return struct.pack(
        _HEADER_FMT,
        _PACKET_FORMAT,  # m_packetFormat
        25,              # m_gameYear
        1, 0,            # major, minor
        1,               # packet version
        packet_id,       # m_packetId
        123456789,       # m_sessionUID
        session_time,    # m_sessionTime
        0, 0,            # frame ids
        player_car_index,
        255,             # secondary player car index
    )


def build_car_telemetry_packet(
    *,
    speed: int,
    throttle: float,
    brake: float,
    steer: float = 0.0,
    gear: int = 4,
    engine_rpm: int = 11000,
    drs: int = 0,
    player_car_index: int = 0,
    session_time: float = 0.0,
) -> bytes:
    """One packet-id-6 datagram; the player's entry carries the given values."""
    header = build_header(PACKET_ID_CAR_TELEMETRY, player_car_index, session_time)
    empty = bytes(TELEMETRY_ENTRY_SIZE)
    entries = [empty] * NUM_CARS
    entries[player_car_index] = struct.pack(
        _TELEMETRY_FMT,
        speed, throttle, steer, brake,
        0,          # clutch
        gear,
        engine_rpm,
        drs,
        0,          # revLightsPercent
        0,          # revLightsBitValue
        0, 0, 0, 0,             # brakesTemperature[4]
        0, 0, 0, 0,             # tyresSurfaceTemperature[4]
        0, 0, 0, 0,             # tyresInnerTemperature[4]
        0,                      # engineTemperature
        0.0, 0.0, 0.0, 0.0,     # tyresPressure[4]
        0, 0, 0, 0,             # surfaceType[4]
    )
    # trailing fields after the 22-car array (mfdPanelIndex etc.); size-agnostic
    trailer = bytes(3)
    return header + b"".join(entries) + trailer


def build_lap_data_packet(
    *,
    lap_distance: float,
    current_lap_num: int,
    sector: int = 0,
    current_lap_invalid: int = 0,
    total_distance: float = 0.0,
    last_lap_time_ms: int = 0,
    current_lap_time_ms: int = 0,
    player_car_index: int = 0,
    session_time: float = 0.0,
) -> bytes:
    """One packet-id-2 datagram; the player's entry carries the given values."""
    header = build_header(PACKET_ID_LAP_DATA, player_car_index, session_time)
    empty = bytes(LAPDATA_ENTRY_SIZE)
    entries = [empty] * NUM_CARS
    # Build the 33-field LapData tuple, zero except the fields we set.
    fields = [0] * 33
    fields[0] = last_lap_time_ms
    fields[1] = current_lap_time_ms
    fields[10] = lap_distance      # float
    fields[11] = total_distance    # float
    fields[12] = 0.0               # safetyCarDelta (float)
    fields[14] = current_lap_num
    fields[17] = sector
    fields[18] = current_lap_invalid
    fields[31] = 0.0               # speedTrapFastestSpeed (float)
    entries[player_car_index] = struct.pack(_LAPDATA_FMT, *fields)
    trailer = bytes(2)  # m_timeTrialPBCarIdx, m_timeTrialRivalCarIdx
    return header + b"".join(entries) + trailer


def build_motion_ex_packet(
    *,
    rear_slip_ratio: float = 0.0,
    front_slip_angle: float = 0.0,
    player_car_index: int = 0,
    session_time: float = 0.0,
) -> bytes:
    """One packet-id-13 datagram (player only)."""
    header = build_header(PACKET_ID_MOTION_EX, player_car_index, session_time)
    floats = [0.0] * 61
    # wheelSlipRatio[4] at float indices 16-19 ([RL,RR,FL,FR]); set rear wheels
    floats[16] = rear_slip_ratio
    floats[17] = rear_slip_ratio
    # wheelSlipAngle[4] at float indices 20-23; set front wheels
    floats[22] = front_slip_angle
    floats[23] = front_slip_angle
    body = struct.pack(_MOTIONEX_FMT, *floats)
    return header + body


# ---------------------------------------------------------------------------
# Track simulation — emit a full lap's worth of packets for demos/e2e tests
# ---------------------------------------------------------------------------
# A tiny synthetic circuit: (braking_point_m, apex_speed_kmh, throttle_pickup_m).
DEMO_CORNERS = [
    (400.0, 110.0, 470.0),
    (900.0, 180.0, 960.0),
    (1500.0, 90.0, 1580.0),
]
DEMO_LAP_LENGTH_M = 2000.0


def simulate_lap_packets(
    lap_num: int,
    *,
    brake_bias_m: float = 0.0,
    apex_penalty_kmh: float = 0.0,
    pickup_delay_m: float = 0.0,
    exit_slip: float = 0.05,
    step_m: float = 8.0,
    session_time: float = 0.0,
    last_lap_time_ms: int = None,
):
    """Yield (lap_data, telemetry, motion_ex) packet triples along one lap.

    ``*_bias/penalty/delay`` let a caller make a lap deliberately worse than a
    reference lap so the delta engine and coach have something to talk about.

    ``last_lap_time_ms`` is the time reported on the wire for the *previous*
    lap (that is what ``m_lastLapTimeInMS`` holds while this lap is running, and
    it is what finalises the previous lap). When omitted it is derived from this
    lap's own sloppiness as a rough stand-in.
    """
    if last_lap_time_ms is None:
        last_lap_time_ms = int(88000 - brake_bias_m * 5 + pickup_delay_m * 8 + apex_penalty_kmh * 20)
    corners = [
        (bp + brake_bias_m, apex - apex_penalty_kmh, pu + pickup_delay_m)
        for (bp, apex, pu) in DEMO_CORNERS
    ]
    d = 0.0
    while d < DEMO_LAP_LENGTH_M:
        speed, throttle, brake = 320.0, 1.0, 0.0
        rear_slip = 0.02
        for (bp, apex, pu) in corners:
            apex_d = bp + 45.0
            if bp <= d < apex_d:               # braking to apex
                frac = (d - bp) / (apex_d - bp)
                speed = 320.0 - (320.0 - apex) * frac
                throttle, brake = 0.0, 0.95
            elif apex_d <= d < pu:             # apex, trailing off
                speed, throttle, brake = apex, 0.25, 0.0
            elif pu <= d < pu + 60.0:          # power down on exit
                speed = min(320.0, apex + (d - pu) * 1.5)
                throttle, brake = 0.95, 0.0
                rear_slip = exit_slip
        sector = 0 if d < 700 else (1 if d < 1400 else 2)
        yield (
            build_lap_data_packet(
                lap_distance=d, current_lap_num=lap_num, sector=sector,
                total_distance=d + lap_num * DEMO_LAP_LENGTH_M,
                last_lap_time_ms=last_lap_time_ms,
                session_time=session_time,
            ),
            build_car_telemetry_packet(
                speed=int(speed), throttle=throttle, brake=brake,
                gear=min(8, max(2, int(speed // 45))), session_time=session_time,
            ),
            build_motion_ex_packet(rear_slip_ratio=rear_slip, session_time=session_time),
        )
        d += step_m
