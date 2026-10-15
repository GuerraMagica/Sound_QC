from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pytest

from audio_qc.config import ConfigError, load_config
from audio_qc.consolidation import CandidateConsolidator, consolidate_candidates
from audio_qc.defects import StreamingDefects, detect_window
from audio_qc.models import Defect, Status
from audio_qc.synthetic import sine


def click(start, length=3, strength=12.5, channel=1, kind="POSSIBLE CLICK / TICK", rate=48000):
    return Defect(start/rate, start, channel, kind, length/rate, Status.WARNING,
                  {"duration_samples": length, "impulse_deviation_db": strength}, f"measured_at_{start}")


def test_reference_geometry_keeps_strongest_original_evidence():
    first = click(2529767, 3, 12.458957406742591)
    second = click(2529771, 8, 12.548333027680375)
    original = deepcopy([asdict(first), asdict(second)])
    event, = consolidate_candidates([second, first], 48000)
    expected = {**asdict(second), "merged_candidate_count": 2,
                "cluster_first_sample": 2529767, "cluster_last_sample": 2529778}
    assert asdict(event) == expected
    assert event.timestamp_seconds == 52.7035625
    assert [asdict(first), asdict(second)] == original


@pytest.mark.parametrize("second_start,expected", [(102, 1), (103, 1), (104, 1), (151, 1), (152, 2), (340, 2)])
def test_intervals_overlap_touch_inclusive_gap_and_separate_clicks(second_start, expected):
    # First interval is [100, 103). Exactly 48 gap samples = 1 ms at 48 kHz.
    assert len(consolidate_candidates([click(100), click(second_start)], 48000)) == expected


def test_duration_not_only_start_distance_and_transitive_cluster_extent():
    raw = [click(100, 100, 15), click(240, 80, 12), click(365, 3, 13)]
    event, = consolidate_candidates(raw, 48000)
    assert event.sample_index == 100  # Union extent is independent of representative.
    assert event.duration_seconds == 100/48000
    assert event.cluster_last_sample == 367
    assert event.merged_candidate_count == 3


@pytest.mark.parametrize("rate,gap,expected", [(44100, 44, 1), (44100, 45, 2), (96000, 96, 1), (96000, 97, 2)])
def test_gap_uses_actual_rate_without_rounding_up(rate, gap, expected):
    assert len(consolidate_candidates([click(100, rate=rate), click(103+gap, rate=rate)], rate)) == expected


def test_zero_gap_only_merges_overlapping_or_touching_intervals():
    assert len(consolidate_candidates([click(100), click(103)], 48000, 0)) == 1
    assert len(consolidate_candidates([click(100), click(104)], 48000, 0)) == 2


def test_exact_duration_samples_takes_priority_over_seconds():
    a = click(100)
    a.duration_seconds = 1.0  # Precise duration_samples remains authoritative.
    assert len(consolidate_candidates([a, click(200)], 48000)) == 2
    del a.measurements["duration_samples"]
    a.duration_seconds = 3/48000
    assert len(consolidate_candidates([a, click(151)], 48000)) == 1


def test_same_time_different_channels_remain_separate():
    events = consolidate_candidates([click(100, channel=1), click(100, channel=2)], 48000)
    assert [e.channel for e in events] == [1, 2]
    assert [e.merged_candidate_count for e in events] == [1, 1]


def test_different_types_and_dropouts_are_not_consolidated():
    raw = [click(100), click(100, kind="POSSIBLE DROPOUT"), click(101, kind="POSSIBLE DROPOUT")]
    assert len(consolidate_candidates(raw, 48000)) == 3


def test_timecode_and_rounded_offset_are_never_merge_keys():
    raw = [click(100), click(340)]
    for event in raw:
        event.timecode = "01:00:00:00"
        event.offset = "00:00:00.000"
    assert len(consolidate_candidates(raw, 48000)) == 2


@pytest.mark.parametrize("first,second,expected", [
    (12, 13, 104), (13, 12, 100), (13, 13, 100),
    (None, None, 100), (float("nan"), 12, 104),
    (float("inf"), 12, 104), (float("-inf"), None, 100),
    (None, -5, 104), ("unavailable", 12, 104),
])
def test_representative_finite_strength_then_earliest(first, second, expected):
    event, = consolidate_candidates([click(100, strength=first), click(104, strength=second)], 48000)
    assert event.sample_index == expected


def test_representative_changes_do_not_lose_channel_pending_cluster():
    raw = [click(100, channel=1, strength=12), click(101, channel=2), click(104, channel=1, strength=13)]
    events = consolidate_candidates(raw, 48000)
    assert [(e.sample_index, e.channel, e.merged_candidate_count) for e in events] == [(101, 2, 1), (104, 1, 2)]


@pytest.mark.parametrize("block", [127, 8192, 48000, 65537])
def test_actual_clicks_consolidate_across_stream_core_boundary(config, block):
    signal = sine(3, amplitude=.03, frequency=220)
    signal[47996:47999] += .7
    signal[48000:48008] += .8
    raw = detect_window(signal, 48000, config["defects"])
    assert [e.sample_index for e in raw] == [47996, 48000]
    stream = StreamingDefects(48000, 1, config["defects"])
    for i in range(0, len(signal), block):
        stream.feed(signal[i:i+block])
    event, = stream.finish()
    assert event.merged_candidate_count == 2
    assert (event.cluster_first_sample, event.cluster_last_sample) == (47996, 48007)
    assert event.sample_index == max(raw, key=lambda e: e.measurements["impulse_deviation_db"]).sample_index
    assert not stream.capped


def test_cap_counts_issues_and_completes_retained_cluster_after_overflow(config, monkeypatch):
    config["defects"]["max_candidates"] = 1
    raw = [click(47996, strength=12), click(47997, channel=2),
           click(47998, kind="POSSIBLE DROPOUT"), click(48000, 8, 13)]
    calls = []
    def windows(data, rate, cfg, offset, core_start, core_end):
        calls.append(core_start)
        return [e for e in raw if core_start <= e.sample_index < core_end]
    monkeypatch.setattr("audio_qc.defects.detect_window", windows)
    stream = StreamingDefects(48000, 2, config["defects"])
    for i in range(0, 144000, 8192):
        stream.feed(np.zeros((min(8192, 144000-i), 2)))
    event, = stream.finish()
    assert calls == [0, 48000]
    assert event.sample_index == 47997 and event.merged_candidate_count == 3
    assert event.channels == [1, 2] and stream.capped
    assert event.channel_events[0].sample_index == 48000
    assert event.channel_events[0].merged_candidate_count == 2
    assert len(stream.buffer) == 0


def test_duplicates_do_not_consume_cap_across_windows(config, monkeypatch):
    config["defects"]["max_candidates"] = 2
    raw = [click(47996), click(48000), click(90000), click(90004), click(120000)]
    monkeypatch.setattr("audio_qc.defects.detect_window", lambda data, rate, cfg, offset, first, last:
                        [e for e in raw if first <= e.sample_index < last])
    stream = StreamingDefects(48000, 1, config["defects"])
    for i in range(0, 144000, 8192):
        stream.feed(np.zeros((min(8192, 144000-i), 1)))
    events = stream.finish()
    assert [e.sample_index for e in events] == [47996, 90000]
    assert [e.merged_candidate_count for e in events] == [2, 2]
    assert stream.capped


def test_cap_does_not_truncate_or_warn_for_one_large_duplicate_cluster():
    state = CandidateConsolidator(48000, 1, max_candidates=1)
    for sample in range(10000):
        state.extend([click(sample)])
        assert len(state.events) == len(state.pending) == 1
    event, = state.finish()
    assert event.merged_candidate_count == state.raw_candidate_count == 10000
    assert not state.capped


def test_exactly_at_cap_still_completes_cluster_at_end_of_file(config, monkeypatch):
    config["defects"]["max_candidates"] = 1
    raw = [click(47996), click(48000, 8, 14)]
    monkeypatch.setattr("audio_qc.defects.detect_window", lambda data, rate, cfg, offset, first, last:
                        [e for e in raw if first <= e.sample_index < last])
    stream = StreamingDefects(48000, 1, config["defects"])
    stream.feed(np.zeros((48009, 1)))
    event, = stream.finish()
    assert event.sample_index == 48000 and event.merged_candidate_count == 2
    assert not stream.capped


def test_gap_expiry_at_window_watermark_is_inclusive():
    state = CandidateConsolidator(48000, 1)
    state.extend([click(100)])
    state.advance(151)  # next candidate may start at the inclusive gap boundary
    state.extend([click(151)])
    assert state.finish()[0].merged_candidate_count == 2


@pytest.mark.parametrize("value", [0, 0.25, 1.0, 10])
def test_merge_gap_config_valid(tmp_path, value):
    path = tmp_path/"gap.yaml"
    path.write_text(f"defects:\n  clicks:\n    merge_gap_ms: {value}\n")
    assert load_config(path)["defects"]["clicks"]["merge_gap_ms"] == value


@pytest.mark.parametrize("value", ["-0.01", "10.001", "true", "null", '"1.0"', ".nan", ".inf"])
def test_merge_gap_config_invalid(tmp_path, value):
    path = tmp_path/"gap.yaml"
    path.write_text(f"defects:\n  clicks:\n    merge_gap_ms: {value}\n")
    with pytest.raises(ConfigError, match="merge_gap_ms"):
        load_config(path)


def test_default_merge_gap_and_separate_source_state():
    assert load_config()["defects"]["clicks"]["merge_gap_ms"] == 1.0
    file_a = consolidate_candidates([click(100)], 48000)
    file_b = consolidate_candidates([click(100)], 48000)
    assert len(file_a) + len(file_b) == 2
    assert file_a[0].merged_candidate_count == file_b[0].merged_candidate_count == 1
