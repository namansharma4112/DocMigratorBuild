"""Standalone, tkinter-free tests for the progress-bar percentage + ETA math."""
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROGRESS_BANDS = {
    "scan":     (0, 3),
    "extract":  (3, 45),
    "enrich":   (45, 65),
    "dedupe":   (65, 90),
    "organise": (90, 97),
    "tracker":  (97, 99),
    "done":     (99, 100),
}


def compute_progress_percent(phase, current, total, last_pct=0.0):
    if phase not in PROGRESS_BANDS:
        return last_pct
    lo, hi = PROGRESS_BANDS[phase]
    if phase == "done":
        return 100.0
    if total and total > 0:
        frac = max(0.0, min(1.0, current / total))
        return lo + (hi - lo) * frac
    return float(hi)


def compute_eta_seconds(elapsed_seconds: float, pct: float) -> Optional[float]:
    if pct is None or pct < 2.0 or pct >= 100.0 or elapsed_seconds <= 0:
        return None
    total_estimated = elapsed_seconds * (100.0 / pct)
    remaining = total_estimated - elapsed_seconds
    return max(0.0, remaining)


def format_eta(seconds):
    if seconds is None:
        return "Estimating time remaining…"
    seconds = int(round(seconds))
    if seconds < 5:
        return "Almost done…"
    if seconds < 60:
        return f"~{seconds}s remaining"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"~{minutes}m {secs:02d}s remaining"
    hours, minutes = divmod(minutes, 60)
    return f"~{hours}h {minutes:02d}m remaining"


def test_monotonic_increase_across_full_run():
    calls = [
        ("scan", 1, 1), ("extract", 1, 12), ("extract", 6, 12), ("extract", 12, 12),
        ("enrich", 1, 12), ("enrich", 6, 12), ("enrich", 12, 12),
        ("dedupe", 1, 12), ("dedupe", 6, 12), ("dedupe", 12, 12),
        ("organise", 1, 9), ("organise", 5, 9), ("organise", 9, 9),
        ("tracker", 1, 1), ("done", 1, 1),
    ]
    pct = 0.0
    for phase, cur, tot in calls:
        new_pct = compute_progress_percent(phase, cur, tot, pct)
        assert new_pct >= pct
        assert 0.0 <= new_pct <= 100.0
        pct = new_pct
    assert pct == 100.0


def test_each_phase_stays_within_its_own_band():
    for phase, (lo, hi) in PROGRESS_BANDS.items():
        for cur, tot in [(0, 10), (1, 10), (5, 10), (10, 10), (1, 1)]:
            pct = compute_progress_percent(phase, cur, tot)
            assert lo <= pct <= hi or (phase == "done" and pct == 100.0)


def test_zero_total_does_not_crash_or_go_backwards():
    pct = compute_progress_percent("extract", 0, 0, last_pct=10.0)
    assert isinstance(pct, float)
    assert 0.0 <= pct <= 100.0


def test_unknown_phase_is_ignored_gracefully():
    pct = compute_progress_percent("some_future_phase_name", 3, 10, last_pct=42.0)
    assert pct == 42.0


def test_dedupe_reports_granular_progress_within_its_band():
    lo, hi = PROGRESS_BANDS["dedupe"]
    p0 = compute_progress_percent("dedupe", 0, 100)
    p50 = compute_progress_percent("dedupe", 50, 100)
    p100 = compute_progress_percent("dedupe", 100, 100)
    assert p0 == lo
    assert p100 == hi
    assert lo < p50 < hi


def test_eta_none_before_minimum_threshold():
    assert compute_eta_seconds(5.0, 0.5) is None
    assert compute_eta_seconds(5.0, 1.9) is None


def test_eta_none_when_complete_or_no_time_elapsed():
    assert compute_eta_seconds(10.0, 100.0) is None
    assert compute_eta_seconds(0.0, 50.0) is None


def test_eta_basic_linear_extrapolation():
    eta = compute_eta_seconds(10.0, 50.0)
    assert eta is not None
    assert 9.0 <= eta <= 11.0


def test_eta_never_negative():
    eta = compute_eta_seconds(1.0, 95.0)
    assert eta is not None
    assert eta >= 0.0


def test_format_eta_human_readable_bands():
    assert format_eta(None) == "Estimating time remaining…"
    assert format_eta(3) == "Almost done…"
    assert format_eta(45) == "~45s remaining"
    assert format_eta(125) == "~2m 05s remaining"
    assert format_eta(3725) == "~1h 02m remaining"
