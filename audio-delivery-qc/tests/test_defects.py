from dataclasses import asdict
import numpy as np
import pytest

from audio_qc.defects import StreamingDefects, detect_window
from audio_qc.models import Status
from audio_qc.samples import RunCounter
from audio_qc.scanner import inspect_file
from audio_qc.synthetic import defect_signals, sine, write_wav


@pytest.mark.parametrize("name,type_,channel", [
    ("one_sample_click", "POSSIBLE CLICK / TICK", 1),
    ("multi_sample_click", "POSSIBLE CLICK / TICK", 1),
    ("zero_dropout", "POSSIBLE DROPOUT", 1),
    ("attenuation_dropout", "POSSIBLE DROPOUT", 1),
    ("channel_dropout", "POSSIBLE DROPOUT", 1),
])
def test_true_detections(config, name, type_, channel):
    events = detect_window(defect_signals()[name], 48000, config["defects"])
    assert len(events) == 1
    e = events[0]
    assert (e.event_type, e.channel, e.severity) == (type_, channel, None)
    assert e.sample_index == pytest.approx(48000, abs=1)
    assert e.timestamp_seconds == pytest.approx(1, abs=1/48000)
    assert e.duration_seconds > 0 and e.measurements and e.detection_method
    if name == "channel_dropout":
        assert e.measurements["channel_specific"] is True
        assert e.measurements["continuing_channel"] == 2
    if name in ("zero_dropout", "channel_dropout"):
        assert e.measurements["digital_zero"] is True
        assert e.measurements["event_rms_dbfs"] is None
        assert e.measurements["relative_level_drop_db"] is None


@pytest.mark.parametrize("name", ["clean_sine", "legitimate_transient", "intentional_silence"])
def test_false_positives(config, name):
    assert detect_window(defect_signals()[name], 48000, config["defects"]) == []


def test_detection_benchmark(config, tmp_path):
    """Persist the measured confusion counts for the complete synthetic corpus."""
    import json
    negatives = {"clean_sine", "legitimate_transient", "intentional_silence"}
    tp = fp = fn = tn = 0
    for name, samples in defect_signals().items():
        detected = bool(detect_window(samples, 48000, config["defects"]))
        if name in negatives:
            fp += int(detected)
            tn += int(not detected)
        else:
            tp += int(detected)
            fn += int(not detected)
    result = {"true_positive_files": tp, "false_positive_files": fp, "false_negative_files": fn, "true_negative_files": tn}
    (tmp_path/"benchmark.json").write_text(json.dumps(result))
    assert result == {"true_positive_files": 5, "false_positive_files": 0, "false_negative_files": 0, "true_negative_files": 3}


@pytest.mark.parametrize("block", [127, 8192, 48000, 65537])
def test_overlaps_match_whole_signal(config, block):
    samples = defect_signals()["channel_dropout"]
    # Candidate starts exactly at a core boundary and crosses many block boundaries.
    stream = StreamingDefects(48000, 2, config["defects"])
    for i in range(0, len(samples), block):
        stream.feed(samples[i:i+block])
    actual = stream.finish()
    expected = detect_window(samples, 48000, config["defects"])
    assert [(e.sample_index, e.channel, e.event_type, e.duration_seconds) for e in actual] == [
        (e.sample_index, e.channel, e.event_type, e.duration_seconds) for e in expected]


def test_click_across_chunk_boundary(config):
    samples = sine(3, amplitude=.03, frequency=220)
    samples[48000-4:48000+4] += .7
    stream = StreamingDefects(48000, 1, config["defects"])
    for i in range(0, len(samples), 8192):
        stream.feed(samples[i:i+8192])
    events = stream.finish()
    assert len(events) == 1 and events[0].sample_index == 47996


def test_constant_hold(config):
    samples = sine(3, amplitude=.1, frequency=220)
    samples[48000:48960] = .015
    events = detect_window(samples, 48000, config["defects"])
    assert any(e.detection_method.startswith("constant_sample_run") for e in events)


@pytest.mark.parametrize("duration_ms", [5, 40, 250, 490])
def test_attenuation_across_duration_range(config, duration_ms):
    samples = sine(3, amplitude=.04, frequency=220)
    count = round(duration_ms * 48)
    samples[47520:47520+count] *= .001
    stream = StreamingDefects(48000, 1, config["defects"])
    for i in range(0, len(samples), 8192):
        stream.feed(samples[i:i+8192])
    events = stream.finish()
    assert len(events) == 1
    assert events[0].sample_index == 47520
    assert events[0].duration_seconds == pytest.approx(duration_ms/1000, abs=.001)


def test_candidate_cap(config):
    cfg = config["defects"]
    cfg["max_candidates"] = 1
    samples = sine(3, amplitude=.03, frequency=220)
    samples[30000] += .7
    samples[80000] += .7
    stream = StreamingDefects(48000, 1, cfg)
    for i in range(0, len(samples), 8192):
        stream.feed(samples[i:i+8192])
    assert len(stream.finish()) == 1
    assert stream.capped


def test_run_counter_carries_across_blocks():
    counter = RunCounter()
    counter.feed(np.array([False, True, True]), 0)
    counter.feed(np.array([True, True, False]), 3)
    assert (counter.longest, counter.start, counter.tail) == (4, 1, 0)


@pytest.mark.integration
def test_explicit_zero_fail_rule(tmp_path, config):
    config["defects"]["enabled"] = True
    config["defects"]["dropouts"]["fail_zero_run_ms"] = 800
    p = write_wav(tmp_path/"intentional.wav", defect_signals()["intentional_silence"])
    a = inspect_file(p, config)
    assert any(c.code == "explicit_zero_run_rule" and c.status == Status.FAIL for c in a.checks)
    assert any(e.event_type == "DIGITAL ZERO RUN (EXPLICIT RULE)" for e in a.defects)


@pytest.mark.integration
@pytest.mark.parametrize("name", list(defect_signals()))
def test_pcm_quantized_corpus(tmp_path, config, name):
    config["defects"]["enabled"] = True
    a = inspect_file(write_wav(tmp_path/f"{name}.wav", defect_signals()[name]), config)
    assert bool(a.defects) == (name not in {"clean_sine", "legitimate_transient", "intentional_silence"})
    assert all(e.severity != Status.FAIL for e in a.defects)
