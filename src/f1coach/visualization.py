"""Headless visual feedback for completed laps."""

from __future__ import annotations

import os
from html import escape
from typing import List

import numpy as np

from .corners import Corner
from .telemetry import Lap, LapSample


class LapChartRenderer:
    """Save one speed comparison chart for every completed lap."""

    def __init__(self, track: str, output_dir: str, history_limit: int = 5) -> None:
        self.track = track
        self.output_dir = output_dir
        self.history_limit = history_limit
        self._laps: List[Lap] = []
        self.live_path = os.path.join(output_dir, f"{track}_live_speed.html")

    def render(
        self,
        lap: Lap,
        reference_corners: List[Corner] | None = None,
        reference_lap_time_ms: int = 0,
        reference_samples: List[LapSample] | None = None,
    ) -> str:
        """Save a chart for ``lap`` and return its path.

        The newest lap is highlighted and the preceding four completed laps are
        retained as a visual baseline without making the chart unreadable.
        """
        if self._laps and self._laps[-1].lap_number == lap.lap_number:
            self._laps[-1] = lap
        else:
            self._laps.append(lap)
        visible_laps = self._laps[-self.history_limit:]
        os.makedirs(self.output_dir, exist_ok=True)
        width, height = 1400, 820
        left, right, top, bottom = 105, 52, 170, 92
        plot_width = width - left - right
        plot_height = height - top - bottom
        all_arrays = [item.arrays() for item in visible_laps]
        max_distance = max(
            (float(a["distance"][-1]) for a in all_arrays if len(a["distance"])),
            default=1.0,
        )
        reference_arrays = None
        if reference_samples:
            reference_arrays = Lap(lap_number=0, samples=reference_samples).arrays()
        if reference_arrays is None:
            reference_arrays = self._reference_arrays(reference_corners, max_distance)
        if reference_arrays is not None:
            max_distance = max(max_distance, float(reference_arrays["distance"][-1]))
        max_speed = max(
            (float(a["speed"].max()) for a in all_arrays if len(a["speed"])),
            default=0.0,
        )
        if reference_arrays is not None:
            max_speed = max(max_speed, float(reference_arrays["speed"].max()))
        y_max = max(300.0, ((max_speed + 24.0) // 20.0) * 20.0)
        y_min = 0.0

        def smooth_path(arrays: dict) -> str:
            """Resample the trace and draw it with smooth cubic segments."""
            distances = arrays["distance"]
            speeds = arrays["speed"]
            if not len(distances):
                return ""
            point_count = max(80, min(600, len(distances) * 4))
            dense_distances = np.linspace(float(distances[0]), float(distances[-1]), point_count)
            dense_speeds = np.interp(dense_distances, distances, speeds)
            coordinates = [
                (
                    left + float(distance) / max_distance * plot_width,
                    top + (1.0 - (float(speed) - y_min) / (y_max - y_min)) * plot_height,
                )
                for distance, speed in zip(dense_distances, dense_speeds)
            ]
            path = [f"M {coordinates[0][0]:.1f},{coordinates[0][1]:.1f}"]
            for index in range(1, len(coordinates)):
                previous = coordinates[index - 1]
                current = coordinates[index]
                before = coordinates[max(0, index - 2)]
                after = coordinates[min(len(coordinates) - 1, index + 1)]
                control_one = (
                    previous[0] + (current[0] - before[0]) / 6.0,
                    previous[1] + (current[1] - before[1]) / 6.0,
                )
                control_two = (
                    current[0] - (after[0] - previous[0]) / 6.0,
                    current[1] - (after[1] - previous[1]) / 6.0,
                )
                path.append(
                    f"C {control_one[0]:.1f},{control_one[1]:.1f} "
                    f"{control_two[0]:.1f},{control_two[1]:.1f} "
                    f"{current[0]:.1f},{current[1]:.1f}"
                )
            return " ".join(path)

        grid = []
        for index in range(7):
            y = top + plot_height * index / 6
            value = y_max * (1 - index / 6)
            grid.append(
                f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" '
                'stroke="#27364a" stroke-width="1" />'
                f'<text x="{left - 18}" y="{y + 5:.1f}" text-anchor="end">{value:.0f}</text>'
            )

        x_ticks = []
        for index in range(6):
            x = left + plot_width * index / 5
            distance = max_distance * index / 5
            x_ticks.append(
                f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height - bottom}" '
                'stroke="#1d2a3b" stroke-width="1" />'
                f'<text x="{x:.1f}" y="{height - bottom + 29}" text-anchor="middle">'
                f'{distance:.0f}</text>'
            )

        trace_colors = ["#718096", "#3bb7c8", "#7b8cff", "#b08cff"]
        traces = []
        if reference_arrays is not None:
            traces.append(
                f'<path d="{smooth_path(reference_arrays)}" fill="none" stroke="#f2c14e" '
                'stroke-width="3" stroke-dasharray="10 8" opacity="0.95" '
                'stroke-linejoin="round" />'
            )
        for item, arrays in zip(visible_laps[:-1], all_arrays[:-1]):
            if len(arrays["distance"]):
                color = trace_colors[(len(visible_laps) - 2 - visible_laps[:-1].index(item)) % len(trace_colors)]
                traces.append(
                    f'<path d="{smooth_path(arrays)}" fill="none" stroke="{color}" '
                    'stroke-width="2.5" opacity="0.72" stroke-linejoin="round" />'
                )
        if len(all_arrays[-1]["distance"]):
            traces.append(
                f'<path d="{smooth_path(all_arrays[-1])}" fill="none" stroke="#ff5a36" '
                'stroke-width="4" stroke-linejoin="round" />'
            )
        current_arrays = all_arrays[-1]
        current_max = float(current_arrays["speed"].max()) if len(current_arrays["speed"]) else 0.0
        sample_count = len(current_arrays["speed"])
        lap_time = f"{lap.lap_time_ms / 1000:.3f}s" if lap.lap_time_ms else "n/a"
        previous_time = visible_laps[-2].lap_time_ms if len(visible_laps) > 1 else 0
        if lap.lap_time_ms and previous_time:
            time_delta = f"{(lap.lap_time_ms - previous_time) / 1000:+.3f}s"
        else:
            time_delta = "n/a"
        title = escape(self.track.replace("_", " ").title())
        reference_label = (
            f"  /  Reference {reference_lap_time_ms / 1000:.3f}s"
            if reference_lap_time_ms
            else ""
        )
        subtitle = escape(
            f"Speed trace comparison  /  Current lap {lap.lap_number}{reference_label}"
        )
        legend = []
        if reference_arrays is not None:
            legend.append(
                '<line x1="875" y1="123" x2="899" y2="123" stroke="#f2c14e" '
                'stroke-width="3" stroke-dasharray="7 5" />'
                '<text x="907" y="128" fill="#b9c5d6">Reference target</text>'
            )
        for index, item in enumerate(visible_laps):
            color = "#ff5a36" if index == len(visible_laps) - 1 else trace_colors[(len(visible_laps) - 2 - index) % len(trace_colors)]
            label = f"Lap {item.lap_number}" + (" (current)" if index == len(visible_laps) - 1 else "")
            x = 1080 + (index % 2) * 145
            y = 128 + (index // 2) * 24
            legend.append(
                f'<line x1="{x}" y1="{y - 5}" x2="{x + 24}" y2="{y - 5}" '
                f'stroke="{color}" stroke-width="3" />'
                f'<text x="{x + 32}" y="{y}" fill="#b9c5d6">{escape(label)}</text>'
            )

        def metric(x: int, label: str, value: str) -> str:
            return (
                f'<text x="{x}" y="91" font-family="sans-serif" fill="#75859a" font-size="13" letter-spacing="1">'
                f'{escape(label.upper())}</text>'
                f'<text x="{x}" y="119" font-family="sans-serif" fill="#f4f7fb" font-size="22" font-weight="700">'
                f'{escape(value)}</text>'
            )

        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#0b1220" />
<rect x="28" y="24" width="1344" height="772" rx="10" fill="#111c2c" stroke="#243349" />
<text x="60" y="58" font-family="sans-serif" font-size="14" font-weight="700" letter-spacing="2" fill="#ff5a36">F1 DRIVING COACH  /  TELEMETRY</text>
<text x="60" y="91" font-family="sans-serif" font-size="26" font-weight="700" fill="#f4f7fb">{title}</text>
<text x="60" y="116" font-family="sans-serif" font-size="14" fill="#8292a8">{subtitle}</text>
{metric(500, "Lap time", lap_time)}
{metric(650, "Vs previous", time_delta)}
{metric(820, "Top speed", f"{current_max:.0f} km/h")}
{metric(980, "Samples", str(sample_count))}
<g font-family="sans-serif" font-size="13">{''.join(legend)}</g>
<rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" fill="#0d1726" stroke="#2b3b52" />
<g font-family="sans-serif" font-size="13" fill="#8090a5">{''.join(grid)}{''.join(x_ticks)}</g>
<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#8090a5" />
<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#8090a5" />
<g font-family="sans-serif" font-size="14" fill="#aab7c8">
<text x="{width / 2:.0f}" y="{height - 25}" text-anchor="middle">LAP DISTANCE (M)</text>
<text x="30" y="{height / 2:.0f}" text-anchor="middle" transform="rotate(-90 30 {height / 2:.0f})">SPEED (KM/H)</text>
</g>
{''.join(traces)}
</svg>
'''
        with open(self.live_path, "w", encoding="utf-8") as live_file:
            live_file.write(
                '<!doctype html>\n'
                '<html><head><meta charset="utf-8">\n'
                '<meta http-equiv="refresh" content="2">\n'
                f'<title>{title} - Live speed comparison</title></head>\n'
                '<body style="margin:0;background:#0b1220">\n'
                f'{svg}\n'
                '</body></html>\n'
            )
        return self.live_path

    @staticmethod
    def _reference_arrays(
        corners: List[Corner] | None,
        lap_distance: float,
    ) -> dict | None:
        """Build a target speed profile from the stored corner landmarks."""
        if not corners:
            return None
        anchors: list[tuple[float, float]] = [(0.0, 300.0)]
        for corner in sorted(corners, key=lambda item: item.apex_distance):
            anchors.extend(
                (
                    (max(0.0, corner.brake_point), 300.0),
                    (max(0.0, corner.apex_distance), float(corner.apex_speed)),
                    (max(0.0, corner.throttle_pickup), min(300.0, corner.apex_speed + 42.0)),
                )
            )
        anchors.append((max(lap_distance, anchors[-1][0] + 150.0), 300.0))
        anchors.sort(key=lambda item: item[0])
        distances = np.array([item[0] for item in anchors], dtype=float)
        speeds = np.array([item[1] for item in anchors], dtype=float)
        unique_distances, unique_indices = np.unique(distances, return_index=True)
        return {
            "distance": unique_distances,
            "speed": speeds[unique_indices],
        }