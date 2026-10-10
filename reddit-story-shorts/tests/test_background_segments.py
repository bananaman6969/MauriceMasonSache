import pytest
from core import gameplay


@pytest.fixture(autouse=True)
def segment_history(tmp_path, monkeypatch):
    monkeypatch.setattr(gameplay, 'SLICE_HISTORY_PATH', tmp_path / 'segments.json')
    monkeypatch.setattr(gameplay, '_last_slice_starts', {})


def test_long_background_matches_narration_and_varies_after_restart(monkeypatch):
    monkeypatch.setattr(gameplay, 'probe_video_metadata', lambda _: {'duration': 1119.0})
    monkeypatch.setattr(gameplay.random, 'uniform', lambda low, high: low)
    first, duration = gameplay.get_random_slice('cooking.mp4', 60.125)
    gameplay._last_slice_starts.clear()  # Simulate a server restart.
    second, second_duration = gameplay.get_random_slice('cooking.mp4', 60.125)
    assert second - first >= 60.125
    assert duration == second_duration == 60.125
    assert 0 <= second <= 1119 - duration


def test_near_fit_uses_available_range_instead_of_repeating_zero(monkeypatch):
    monkeypatch.setattr(gameplay, 'probe_video_metadata', lambda _: {'duration': 62.0})
    monkeypatch.setattr(gameplay.random, 'uniform', lambda low, high: high)
    first, _ = gameplay.get_random_slice('near-fit.mp4', 60.0)
    second, duration = gameplay.get_random_slice('near-fit.mp4', 60.0)
    assert first == 2.0
    assert second != first
    assert 0 <= second <= 2.0
    assert duration == 60.0


def test_short_background_still_covers_full_narration(monkeypatch):
    monkeypatch.setattr(gameplay, 'probe_video_metadata', lambda _: {'duration': 8.0})
    assert gameplay.get_random_slice('short.mp4', 60.25) == (0.0, 60.25)


def test_corrupt_history_does_not_prevent_render(monkeypatch):
    gameplay.SLICE_HISTORY_PATH.write_text('broken')
    monkeypatch.setattr(gameplay, 'probe_video_metadata', lambda _: {'duration': 600.0})
    start, duration = gameplay.get_random_slice('cooking.mp4', 80.0)
    assert 0 <= start <= 520
    assert duration == 80.0
