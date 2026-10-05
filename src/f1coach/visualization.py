"""Headless visual feedback for completed laps."""

from __future__ import annotations

import os
import json
import re
from html import escape
from typing import List

import numpy as np

from .corners import Corner
from .telemetry import Lap, LapSample


class LapChartRenderer:
    """Save one speed comparison chart for every completed lap."""

    def __init__(self, track: str, output_dir: str, history_limit: int = 2) -> None:
        self.track = track
        self.output_dir = output_dir
        self.history_limit = history_limit
        self._laps: List[Lap] = []
        self.live_path = os.path.join(output_dir, "live_dashboard.html")
        self._state_path = os.path.join(output_dir, "live_dashboard_state.json")
        self._track_views = self._load_dashboard_state()
        self._lap_history = self._load_lap_history()

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
        max_distance = max(
            (float(item.arrays()["distance"][-1]) for item in visible_laps if len(item.samples)),
            default=1.0,
        )
        reference_arrays = None
        if reference_samples:
            reference_arrays = self._chart_arrays(Lap(lap_number=0, samples=reference_samples))
        if reference_arrays is None:
            reference_arrays = self._reference_arrays(reference_corners, max_distance)
        display_laps = visible_laps[-1:]
        latest_is_reference = (
            bool(reference_samples and self._matches_reference(visible_laps[-1], reference_samples))
            or bool(reference_lap_time_ms and lap.lap_time_ms and lap.lap_time_ms == reference_lap_time_ms)
        )
        reference_repeated = bool(latest_is_reference and len(visible_laps) > 1)
        if reference_repeated:
            display_laps = visible_laps[-2:-1]
        all_arrays = [self._chart_arrays(item) for item in display_laps]
        max_distance = max(
            (float(a["distance"][-1]) for a in all_arrays if len(a["distance"])),
            default=1.0,
        )
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
        for item, arrays in zip(display_laps[:-1], all_arrays[:-1]):
            if len(arrays["distance"]):
                color = trace_colors[(len(display_laps) - 2 - display_laps[:-1].index(item)) % len(trace_colors)]
                traces.append(
                    f'<path d="{smooth_path(arrays)}" fill="none" stroke="{color}" '
                    'stroke-width="2.5" opacity="0.72" stroke-linejoin="round" />'
                )
        if len(all_arrays[-1]["distance"]):
            traces.append(
                f'<path d="{smooth_path(all_arrays[-1])}" fill="none" stroke="#ff5a36" '
                'stroke-width="4" stroke-linejoin="round" />'
            )
        if reference_arrays is not None:
            traces.append(
                f'<path d="{smooth_path(reference_arrays)}" fill="none" stroke="#f2c14e" '
                'stroke-width="4" stroke-dasharray="10 8" opacity="0.95" '
                'stroke-linejoin="round" />'
            )
        current_arrays = self._chart_arrays(lap)
        current_max = float(current_arrays["speed"].max()) if len(current_arrays["speed"]) else 0.0
        sample_count = len(current_arrays["speed"])
        lap_time = f"{lap.lap_time_ms / 1000:.3f}s" if lap.lap_time_ms else "n/a"
        previous_time = (
            visible_laps[-2].lap_time_ms
            if len(visible_laps) > 1
            else self._last_persisted_lap_time()
        )
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
        display_label = (
            f"Previous lap {display_laps[-1].lap_number} (latest matched reference)"
            if reference_repeated
            else f"Current lap {display_laps[-1].lap_number}"
        )
        subtitle = escape(f"Speed trace comparison  /  {display_label}{reference_label}")
        legend = []
        if reference_arrays is not None:
            legend.append(
                '<line x1="875" y1="150" x2="899" y2="150" stroke="#f2c14e" '
                'stroke-width="3" stroke-dasharray="7 5" />'
                '<text x="907" y="155" fill="#b9c5d6">Reference target</text>'
            )
        for index, item in enumerate(display_laps):
            color = "#ff5a36" if index == len(display_laps) - 1 else trace_colors[(len(display_laps) - 2 - index) % len(trace_colors)]
            label = f"Lap {item.lap_number}" + (" (comparison)" if index == len(display_laps) - 1 and reference_repeated else (" (current)" if index == len(display_laps) - 1 else ""))
            x = 1080 + (index % 2) * 145
            y = 155 + (index // 2) * 24
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

        shared_header = f'''<header class="track-header">
        <div class="eyebrow">F1 DRIVING COACH / TELEMETRY</div>
        <h2>{title}</h2>
        <p>{subtitle}</p>
        <div class="track-metrics">
        <div><span>LAP TIME</span><strong>{escape(lap_time)}</strong></div>
        <div><span>CHANGE FROM PREVIOUS</span><strong>{escape(time_delta)}</strong></div>
        <div><span>TOP SPEED</span><strong>{current_max:.0f} km/h</strong></div>
        <div><span>SAMPLES</span><strong>{sample_count}</strong></div>
        </div>
        <div class="track-legend"><span class="reference-key">---</span> Reference target <span class="current-key">---</span> Comparison lap</div>
        </header>'''

        clip_id = f"{self._safe_id(self.track)}-speed-plot"
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
    <defs><clipPath id="{clip_id}"><rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" /></clipPath></defs>
<rect width="100%" height="100%" fill="#0b1220" />
<rect x="28" y="24" width="1344" height="772" rx="10" fill="#111c2c" stroke="none" />
<text x="60" y="58" font-family="sans-serif" font-size="14" font-weight="700" letter-spacing="2" fill="#ff5a36">F1 DRIVING COACH  /  TELEMETRY</text>
<text x="60" y="91" font-family="sans-serif" font-size="26" font-weight="700" fill="#f4f7fb">{title}</text>
<text x="60" y="145" font-family="sans-serif" font-size="14" fill="#8292a8">{subtitle}</text>
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
<g clip-path="url(#{clip_id})">{''.join(traces)}</g>
</svg>
'''
        throttle_svg = self._build_throttle_svg(display_laps, reference_samples)
        self._track_views[self.track] = {"header": shared_header, "speed": svg, "throttle": throttle_svg}
        self._remember_lap(lap)
        self._write_dashboard()
        return self.live_path

    @staticmethod
    def _matches_reference(lap: Lap, reference_samples: List[LapSample]) -> bool:
        """Return whether a lap's speed and throttle traces match the reference."""
        lap_arrays = lap.arrays()
        reference_arrays = Lap(lap_number=0, samples=reference_samples).arrays()
        if not len(lap_arrays["distance"]) or not len(reference_arrays["distance"]):
            return False
        start = max(float(lap_arrays["distance"][0]), float(reference_arrays["distance"][0]))
        end = min(float(lap_arrays["distance"][-1]), float(reference_arrays["distance"][-1]))
        if end <= start:
            return False
        distances = np.linspace(start, end, 128)
        for field, tolerance in (("speed", 0.5), ("throttle", 0.02)):
            lap_values = np.interp(distances, lap_arrays["distance"], lap_arrays[field])
            reference_values = np.interp(distances, reference_arrays["distance"], reference_arrays[field])
            if not np.allclose(lap_values, reference_values, atol=tolerance, rtol=0.0):
                return False
        return True

    def _load_dashboard_state(self) -> dict[str, dict[str, str]]:
        try:
            with open(self._state_path, encoding="utf-8") as state_file:
                payload = json.load(state_file)
            tracks = payload.get("tracks", {})
            return tracks if isinstance(tracks, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _load_lap_history(self) -> dict[str, list[dict[str, int]]]:
        try:
            with open(self._state_path, encoding="utf-8") as state_file:
                payload = json.load(state_file)
            history = payload.get("lap_history", {})
            if isinstance(history, dict):
                return history
        except (OSError, ValueError, TypeError):
            pass
        migrated: dict[str, list[dict[str, int]]] = {}
        for track, charts in self._track_views.items():
            match = re.search(
                r">LAP TIME</text><text[^>]*>([0-9]+(?:\.[0-9]+)?)s</text>",
                charts.get("speed", ""),
            )
            if match:
                migrated[track] = [{"lap_number": 0, "lap_time_ms": round(float(match.group(1)) * 1000)}]
        return migrated

    def _last_persisted_lap_time(self) -> int:
        history = self._lap_history.get(self.track, [])
        return int(history[-1]["lap_time_ms"]) if history else 0

    def _remember_lap(self, lap: Lap) -> None:
        history = self._lap_history.setdefault(self.track, [])
        entry = {"lap_number": lap.lap_number, "lap_time_ms": lap.lap_time_ms}
        if history and history[-1].get("lap_number") == lap.lap_number:
            history[-1] = entry
        else:
            history.append(entry)
        del history[:-2]

    def _write_dashboard(self) -> None:
        with open(self._state_path, "w", encoding="utf-8") as state_file:
            json.dump({"tracks": self._track_views, "lap_history": self._lap_history}, state_file)

        track_items = []
        track_panels = []
        for index, (track_name, charts) in enumerate(sorted(self._track_views.items())):
            track_id = self._safe_id(track_name)
            active = " active" if index == 0 else ""
            speed_chart = self._ensure_stored_chart_clip(track_name, "speed", charts.get("speed", ""))
            throttle_chart = self._ensure_stored_chart_clip(track_name, "throttle", charts.get("throttle", ""))
            header = charts.get("header") or self._legacy_header(track_name, speed_chart)
            header = header.replace("IMPROVEMENT VS PREVIOUS", "CHANGE FROM PREVIOUS")
            track_items.append(
                f'<button class="track-tab{active}" data-track="{escape(track_name)}">'
                f'{escape(track_name.replace("_", " ").title())}</button>'
            )
            track_panels.append(
                f'<section class="track-panel{active}" data-track="{escape(track_name)}">'
                f'{header}\n'
                '<div class="chart-grid">'
                f'<div id="{track_id}-speed" class="chart-panel" data-track="{escape(track_name)}" data-chart="speed">{speed_chart}</div>'
                f'<div id="{track_id}-throttle" class="chart-panel" data-track="{escape(track_name)}" data-chart="throttle">{throttle_chart}</div>'
                '</div>'
                '</section>'
            )
        title = "F1 Driving Coach - Live Telemetry"
        with open(self.live_path, "w", encoding="utf-8") as live_file:
            live_file.write(
                '<!doctype html><html><head><meta charset="utf-8">'
                '<meta http-equiv="refresh" content="2">'
                f'<title>{title}</title><style>'
                'body{margin:0;background:#0b1220;font-family:sans-serif;color:#f4f7fb}'
                '.track-tabs{display:flex;gap:8px;padding:18px 28px 0;background:#0b1220}'
                'button{border:1px solid #30435e;border-bottom:0;border-radius:7px 7px 0 0;background:#111c2c;color:#9eacc0;padding:10px 22px;font-size:14px;cursor:pointer}'
                'button.active{background:#ff5a36;color:#fff;border-color:#ff5a36}'
                '.track-panel{display:none}.track-panel.active{display:block}'
                '.track-header{padding:28px 40px 18px;background:#111c2c;color:#f4f7fb}.track-header .eyebrow{font-size:12px;font-weight:700;letter-spacing:2px;color:#ff5a36}.track-header h2{margin:7px 0 2px;font-size:28px}.track-header p{margin:0;color:#8292a8;font-size:14px}.track-metrics{display:flex;gap:34px;margin-top:18px;flex-wrap:wrap}.track-metrics div{min-width:125px}.track-metrics span{display:block;color:#75859a;font-size:11px;letter-spacing:1px}.track-metrics strong{display:block;margin-top:5px;font-size:19px}.track-legend{margin-top:14px;color:#b9c5d6;font-size:13px}.reference-key{color:#f2c14e;font-weight:700}.current-key{margin-left:22px;color:#ff5a36;font-weight:700}'
                '.chart-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0;padding:14px 28px 28px;background:#111c2c;border-top:1px solid #2b3b52}'
                '.chart-panel{min-width:0;height:min(520px,calc(100vh - 300px));min-height:280px;overflow:hidden}.chart-panel svg{display:block;width:100%;height:auto;transform:translateY(-80px);margin-bottom:-80px}'
                '@media (max-width:800px){.chart-grid{grid-template-columns:1fr}.chart-panel{height:min(460px,calc(100vh - 280px))}}'
                '</style></head><body>'
                '<nav class="track-tabs" aria-label="Track charts">'
                + "".join(track_items)
                + '</nav>'
                + "".join(track_panels)
                + '<script>\n'
                'var selectionKey="f1coach-dashboard-selection";\n'
                'function activateTrack(track){document.querySelectorAll(".track-tab,.track-panel").forEach(function(item){item.classList.toggle("active",item.dataset.track===track)});}\n'
                'document.querySelectorAll(".track-tab").forEach(function(button){button.addEventListener("click",function(){var saved=JSON.parse(localStorage.getItem(selectionKey)||"{}");saved.track=button.dataset.track;localStorage.setItem(selectionKey,JSON.stringify(saved));activateTrack(button.dataset.track);});});\n'
                'var saved=JSON.parse(localStorage.getItem(selectionKey)||"{}");var first=document.querySelector(".track-tab");activateTrack(saved.track||first.dataset.track);\n'
                '</script></body></html>'
            )

    @staticmethod
    def _legacy_header(track: str, speed_chart: str) -> str:
        """Extract one shared header from charts written before consolidation."""
        def text_after(label: str, default: str) -> str:
            match = re.search(rf">{re.escape(label)}</text><text[^>]*>([^<]*)</text>", speed_chart)
            return match.group(1) if match else default

        title_match = re.search(r'<text x="60" y="91"[^>]*>([^<]*)</text>', speed_chart)
        subtitle_match = re.search(r'<text x="60" y="(?:116|145)"[^>]*>([^<]*)</text>', speed_chart)
        title = title_match.group(1) if title_match else escape(track.replace("_", " ").title())
        subtitle = subtitle_match.group(1) if subtitle_match else "Stored telemetry comparison"
        lap_time = text_after("LAP TIME", "n/a")
        improvement = text_after("VS PREVIOUS", "n/a")
        top_speed = text_after("TOP SPEED", "n/a")
        samples = text_after("SAMPLES", "n/a")
        return f'''<header class="track-header">
<div class="eyebrow">F1 DRIVING COACH / TELEMETRY</div><h2>{title}</h2><p>{subtitle}</p>
<div class="track-metrics"><div><span>LAP TIME</span><strong>{lap_time}</strong></div><div><span>CHANGE FROM PREVIOUS</span><strong>{improvement}</strong></div><div><span>TOP SPEED</span><strong>{top_speed}</strong></div><div><span>SAMPLES</span><strong>{samples}</strong></div></div>
<div class="track-legend"><span class="reference-key">---</span> Reference target <span class="current-key">---</span> Comparison lap</div>
</header>'''

    @staticmethod
    def _ensure_stored_chart_clip(track: str, chart_name: str, svg: str) -> str:
        """Clip chart fragments written by older renderer versions."""
        svg = svg.replace('"<defs', '"><defs', 1)
        svg = svg.replace('x="60" y="116"', 'x="60" y="145"', 1)
        svg = svg.replace('y="123"', 'y="150"')
        svg = svg.replace('y1="123"', 'y1="150"')
        svg = svg.replace('y2="123"', 'y2="150"')
        svg = svg.replace('y="128"', 'y="155"')
        svg = svg.replace('stroke="#243349"', 'stroke="none"')
        svg = svg.replace('<text x="875" y="155" fill="#b9c5d6">Reference target</text>', '')
        if not svg or "clipPath id=" in svg:
            return svg
        clip_id = f"{LapChartRenderer._safe_id(track)}-{chart_name}-plot"
        svg = svg.replace(
            ">",
            f'><defs><clipPath id="{clip_id}"><rect x="105" y="170" width="1243" height="558" /></clipPath></defs>',
            1,
        )
        svg = svg.replace("<path ", f'<path clip-path="url(#{clip_id})" ')
        svg = svg.replace("<polyline ", f'<polyline clip-path="url(#{clip_id})" ')
        return svg

    @staticmethod
    def _chart_arrays(lap: Lap) -> dict:
        """Return telemetry arrays starting at the actual lap boundary."""
        arrays = lap.arrays()
        if not len(arrays["distance"]):
            return arrays
        keep = arrays["distance"] >= 0.0
        return {key: values[keep] for key, values in arrays.items()}

    @staticmethod
    def _safe_id(value: str) -> str:
        return "".join(character if character.isalnum() else "-" for character in value.lower())

    def _build_throttle_svg(
        self,
        visible_laps: List[Lap],
        reference_samples: List[LapSample] | None,
    ) -> str:
        """Build the throttle tab using the same lap comparison styling."""
        width, height = 1400, 820
        left, right, top, bottom = 105, 52, 170, 92
        plot_width = width - left - right
        plot_height = height - top - bottom
        all_arrays = [self._chart_arrays(item) for item in visible_laps]
        reference_arrays = (
            self._chart_arrays(Lap(lap_number=0, samples=reference_samples))
            if reference_samples
            else None
        )
        max_distance = max(
            [float(arrays["distance"][-1]) for arrays in all_arrays if len(arrays["distance"])]
            + ([float(reference_arrays["distance"][-1])] if reference_arrays is not None else [])
            + [1.0]
        )

        def stepped_paths(arrays: dict) -> tuple[str, str]:
            distances = arrays["distance"]
            values = arrays["throttle"]
            if not len(distances):
                return "", ""
            point_count = max(120, min(500, int((distances[-1] - distances[0]) / 10)))
            dense_distances = np.linspace(float(distances[0]), float(distances[-1]), point_count)
            dense_values = np.round(np.interp(dense_distances, distances, values) * 20) / 20
            coordinates = [
                (
                    left + float(distance) / max_distance * plot_width,
                    top + (1.0 - float(value)) * plot_height,
                )
                for distance, value in zip(dense_distances, dense_values)
            ]
            path = [f"M {coordinates[0][0]:.1f},{coordinates[0][1]:.1f}"]
            for index in range(1, len(coordinates)):
                previous = coordinates[index - 1]
                current = coordinates[index]
                path.append(
                    f"L {current[0]:.1f},{previous[1]:.1f} "
                    f"L {current[0]:.1f},{current[1]:.1f}"
                )
            line = " ".join(path)
            baseline = top + plot_height
            area = (
                f"M {coordinates[0][0]:.1f},{baseline:.1f} "
                f"L {coordinates[0][0]:.1f},{coordinates[0][1]:.1f} "
                f"{' '.join(path[1:])} "
                f"L {coordinates[-1][0]:.1f},{baseline:.1f} Z"
            )
            return line, area

        grid = []
        for index in range(6):
            y = top + plot_height * index / 5
            value = 100 * (1 - index / 5)
            grid.append(
                f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#27364a" />'
                f'<text x="{left - 18}" y="{y + 5:.1f}" text-anchor="end">{value:.0f}%</text>'
            )
        x_ticks = []
        for index in range(6):
            x = left + plot_width * index / 5
            x_ticks.append(
                f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height - bottom}" stroke="#1d2a3b" />'
                f'<text x="{x:.1f}" y="{height - bottom + 29}" text-anchor="middle">{max_distance * index / 5:.0f}</text>'
            )
        colors = ["#718096", "#3bb7c8", "#ff5a36"]
        traces = []
        for index, arrays in enumerate(all_arrays):
            if len(arrays["distance"]):
                color = colors[-1] if index == len(all_arrays) - 1 else colors[index % 2]
                line_path, area_path = stepped_paths(arrays)
                traces.append(
                    f'<path d="{area_path}" fill="{color}" opacity="0.12" />'
                    f'<path d="{line_path}" fill="none" stroke="{color}" stroke-width="{4 if index == len(all_arrays) - 1 else 2.5}" opacity="{1 if index == len(all_arrays) - 1 else 0.72}" />'
                )
        if reference_arrays is not None and len(reference_arrays["distance"]):
            reference_path, _ = stepped_paths(reference_arrays)
            traces.append(
                f'<path d="{reference_path}" fill="none" stroke="#f2c14e" stroke-width="4" stroke-dasharray="10 8" />'
            )
        title = escape(self.track.replace("_", " ").title())
        lap_labels = " / ".join(f"Lap {item.lap_number}" for item in visible_laps)
        subtitle = escape(f"Throttle trace comparison  /  {lap_labels}")
        legend = ''
        clip_id = f"{self._safe_id(self.track)}-throttle-plot"
        throttle_bands = (
            f'<rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height * 0.2:.1f}" fill="#35b779" opacity="0.07" />'
            f'<rect x="{left}" y="{top + plot_height * 0.2:.1f}" width="{plot_width}" height="{plot_height * 0.6:.1f}" fill="#f2c14e" opacity="0.05" />'
            f'<rect x="{left}" y="{top + plot_height * 0.8:.1f}" width="{plot_width}" height="{plot_height * 0.2:.1f}" fill="#ff5a36" opacity="0.06" />'
        )
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
    <defs><clipPath id="{clip_id}"><rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" /></clipPath></defs>
<rect width="100%" height="100%" fill="#0b1220" /><rect x="28" y="24" width="1344" height="772" rx="10" fill="#111c2c" stroke="none" />
<text x="60" y="58" font-family="sans-serif" font-size="14" font-weight="700" letter-spacing="2" fill="#ff5a36">F1 DRIVING COACH  /  TELEMETRY</text>
<text x="60" y="91" font-family="sans-serif" font-size="26" font-weight="700" fill="#f4f7fb">{title}</text>
<text x="60" y="116" font-family="sans-serif" font-size="14" fill="#8292a8">{subtitle}</text>
<g font-family="sans-serif" font-size="13">{legend}</g>
<rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" fill="#0d1726" stroke="#2b3b52" />
{throttle_bands}
<g font-family="sans-serif" font-size="13" fill="#8090a5">{''.join(grid)}{''.join(x_ticks)}</g>
<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#8090a5" /><line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#8090a5" />
<g font-family="sans-serif" font-size="14" fill="#aab7c8"><text x="{width / 2:.0f}" y="{height - 25}" text-anchor="middle">LAP DISTANCE (M)</text><text x="30" y="{height / 2:.0f}" text-anchor="middle" transform="rotate(-90 30 {height / 2:.0f})">THROTTLE (%)</text></g>
<g clip-path="url(#{clip_id})">{''.join(traces)}</g>
</svg>'''

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