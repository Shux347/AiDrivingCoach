from __future__ import annotations

import os
import tempfile
from f1coach import reference, config
from f1coach.corners import Corner
from f1coach.telemetry import LapSample

def test_reset_reference(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(config, "REFERENCE_LAP_DIR", tmpdir)
        track = "texas"
        
        # Initially no reference
        assert reference.load_reference(track) is None
        assert reference.reset_reference(track) is False

        # Save a reference lap
        corners = [Corner(index=1, brake_point=100.0, apex_distance=120.0, apex_speed=100.0, throttle_pickup=140.0, max_exit_slip=0.1, min_gear=3)]
        samples = [LapSample(0.0, 280.0, 1.0, 0.0, 0.0, 6, 0.0, 0.0)]
        reference.save_reference(track, corners, 90000, samples=samples)
        
        assert reference.load_reference(track) is not None
        loaded_samples = reference.load_reference_samples(track)
        assert loaded_samples is not None
        assert loaded_samples[0].speed == 280.0

        # Reset reference
        assert reference.reset_reference(track) is True
        assert reference.load_reference(track) is None
        assert reference.reset_reference(track) is False
