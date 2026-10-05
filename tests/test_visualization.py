import os

from f1coach.telemetry import Lap, LapSample
from f1coach.corners import Corner
from f1coach.visualization import LapChartRenderer


def _lap(number: int, speed_offset: float) -> Lap:
    return Lap(
        lap_number=number,
        samples=[
            LapSample(0.0, 100.0 + speed_offset, 0.0, 0.0, 0.0, 3, 0.0, 0.0),
            LapSample(100.0, 180.0 + speed_offset, 0.0, 0.0, 0.0, 4, 0.0, 0.0),
            LapSample(200.0, 140.0 + speed_offset, 0.0, 0.0, 0.0, 4, 0.0, 0.0),
        ],
    )


def test_render_saves_each_lap_and_compares_recent_speed_traces(tmp_path):
    renderer = LapChartRenderer("test_track", str(tmp_path))

    first_path = renderer.render(_lap(1, 0.0))
    second_path = renderer.render(_lap(2, 10.0))

    assert renderer.live_path.endswith("live_dashboard.html")
    assert os.path.exists(renderer.live_path)
    chart = open(second_path, encoding="utf-8").read()
    assert "Lap 1" not in chart
    assert "Lap 2 (current)" in chart
    assert "LAP DISTANCE (M)" in chart
    assert "SPEED (KM/H)" in chart
    assert chart.count("C ") > 50
    live_chart = open(renderer.live_path, encoding="utf-8").read()
    assert 'http-equiv="refresh" content="2"' in live_chart
    assert "Lap 2 (current)" in live_chart
    assert 'data-chart="speed"' in live_chart
    assert 'data-chart="throttle"' in live_chart
    assert 'THROTTLE (%)' in live_chart
    assert "localStorage.setItem(selectionKey" in live_chart
    assert "localStorage.getItem(selectionKey)" in live_chart


def test_render_uses_reference_corner_speeds_as_target_curve(tmp_path):
    renderer = LapChartRenderer("mexico", str(tmp_path))
    path = renderer.render(
        _lap(2, 0.0),
        reference_corners=[Corner(1, 400.0, 500.0, 120.0, 560.0, 0.1, 3)],
        reference_lap_time_ms=80000,
    )

    chart = open(path, encoding="utf-8").read()
    assert "Reference target" in chart
    assert 'stroke-dasharray="10 8"' in chart


def test_render_prefers_recorded_reference_samples(tmp_path):
    renderer = LapChartRenderer("mexico", str(tmp_path))
    recorded = [
        LapSample(0.0, 250.0, 0.0, 0.0, 0.0, 5, 0.0, 0.0),
        LapSample(100.0, 260.0, 0.0, 0.0, 0.0, 5, 0.0, 0.0),
    ]
    path = renderer.render(_lap(2, 0.0), reference_samples=recorded)
    chart = open(path, encoding="utf-8").read()
    assert "Reference target" in chart


def test_live_chart_keeps_only_last_two_laps(tmp_path):
    renderer = LapChartRenderer("mexico", str(tmp_path))
    renderer.render(_lap(1, 0.0))
    renderer.render(_lap(2, 10.0))
    renderer.render(_lap(3, 20.0))

    chart = open(renderer.live_path, encoding="utf-8").read()
    assert "Lap 2" not in chart
    assert "Lap 3 (current)" in chart


def test_matching_reference_uses_previous_lap_for_comparison(tmp_path):
    renderer = LapChartRenderer("brazil", str(tmp_path))
    previous = _lap(1, 0.0)
    latest = _lap(2, 10.0)
    renderer.render(previous)
    dashboard_path = renderer.render(latest, reference_samples=latest.samples)

    dashboard = open(dashboard_path, encoding="utf-8").read()
    assert "Previous lap 1 (latest matched reference)" in dashboard
    assert "Lap 1 (comparison)" in dashboard
    assert "Lap 2 (current)" not in dashboard


def test_change_from_previous_is_signed(tmp_path):
    renderer = LapChartRenderer("brazil", str(tmp_path))
    previous = _lap(1, 0.0)
    previous.lap_time_ms = 80000
    current = _lap(2, 10.0)
    current.lap_time_ms = 78500
    dashboard_path = renderer.render(previous)
    renderer.render(current)

    dashboard = open(dashboard_path, encoding="utf-8").read()
    assert "CHANGE FROM PREVIOUS" in dashboard
    assert "-1.500s" in dashboard


def test_slower_lap_change_is_positive(tmp_path):
    renderer = LapChartRenderer("singapore", str(tmp_path))
    previous = _lap(1, 0.0)
    previous.lap_time_ms = 80000
    current = _lap(2, 10.0)
    current.lap_time_ms = 81500
    dashboard_path = renderer.render(previous)
    renderer.render(current)

    dashboard = open(dashboard_path, encoding="utf-8").read()
    assert "+1.500s" in dashboard


def test_change_from_previous_survives_renderer_restart(tmp_path):
    first_renderer = LapChartRenderer("singapore", str(tmp_path))
    previous = _lap(1, 0.0)
    previous.lap_time_ms = 95000
    first_renderer.render(previous)

    second_renderer = LapChartRenderer("singapore", str(tmp_path))
    current = _lap(2, 10.0)
    current.lap_time_ms = 94445
    dashboard_path = second_renderer.render(current)

    dashboard = open(dashboard_path, encoding="utf-8").read()
    assert "-0.555s" in dashboard


def test_matching_reference_time_hides_latest_duplicate_without_samples(tmp_path):
    renderer = LapChartRenderer("singapore", str(tmp_path))
    previous = _lap(1, 0.0)
    previous.lap_time_ms = 96000
    latest = _lap(2, 10.0)
    latest.lap_time_ms = 94445
    dashboard_path = renderer.render(previous)
    renderer.render(latest, reference_lap_time_ms=94445)

    dashboard = open(dashboard_path, encoding="utf-8").read()
    assert "Previous lap 1 (latest matched reference)" in dashboard
    assert "Lap 2 (current)" not in dashboard
    assert "-1.555s" in dashboard


def test_dashboard_keeps_multiple_track_tabs(tmp_path):
    mexico = LapChartRenderer("mexico", str(tmp_path))
    dashboard_path = mexico.render(_lap(1, 0.0))

    brazil = LapChartRenderer("brazil", str(tmp_path))
    brazil.render(_lap(1, 20.0))

    dashboard = open(dashboard_path, encoding="utf-8").read()
    assert 'data-track="mexico"' in dashboard
    assert 'data-track="brazil"' in dashboard
    assert dashboard.count('data-chart="speed"') == 2
    assert dashboard.count('data-chart="throttle"') == 2
    assert dashboard.count('class="chart-grid"') == 2