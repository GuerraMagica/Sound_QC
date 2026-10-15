from copy import deepcopy
from dataclasses import asdict
import csv
import json

import pytest

from audio_qc.cli import main
from audio_qc.config import ConfigError, load_config
from audio_qc.models import AudioFile, Defect, Status
from audio_qc.reports import build_report, write_reports
from audio_qc.timecode import (RATES, file_timecode, format_frame, format_offset,
                               parse_frame_rate, parse_start_timecode, sample_frame)


def audio(sample=2529767, reference=172800000, rate=48000):
    result = AudioFile("/delivery/test.wav", "test.wav", sample_rate=rate,
                       bwf={"present": reference is not None, "time_reference": reference,
                            "origination_time": "20:22:33"})
    result.defects.append(Defect(sample/rate if rate else 0.0, sample, 1, "POSSIBLE CLICK / TICK",
                                 3/48000, Status.WARNING, {"test": "evidence"}, "unchanged_detector"))
    return result


def settings(rate="25", source="AUTO", start=None):
    return {"frame_rate": rate, "source": source, "manual_start": start}


@pytest.mark.parametrize("rate,sample,expected", [
    ("25", 2529767, "00:00:52:17"), ("24", 2529767, "00:00:52:16"),
    ("23.976", 48000*1001, "00:16:40:00"),
    ("29.97 NDF", 48000*1001, "00:16:40:00"),
    ("29.97 DF", 48000*1001, "00:16:41;00"),
    ("30", 2529767, "00:00:52:21"),
])
def test_all_rates_file_relative(rate, sample, expected):
    event = file_timecode(audio(sample), settings(rate, "FILE_RELATIVE"))["defects"][0]
    assert event["timecode"] == expected
    assert event["timecode_frame_rate"] == rate
    assert event["timecode_basis"] == "FILE_RELATIVE"


def test_exact_user_bwf_example_and_no_mutation(config):
    a = audio()
    original = deepcopy(asdict(a))
    report = build_report("/delivery", [a], [], config, {}, 0)
    event = report["files"][0]["defects"][0]
    assert event["timecode"] == "01:00:52:17"
    assert event["file_start_timecode"] == "01:00:00:00"
    assert event["offset"] == "00:00:52.703"
    assert event["timecode_basis"] == "BWF_TIMEREFERENCE"
    assert event["sample_index"] == 2529767
    assert event["timestamp_seconds"].hex() == (2529767/48000).hex()
    assert report["files"][0]["bwf"]["time_reference"] == 172800000
    assert asdict(a) == original  # enrich copies only
    round_trip = json.loads(json.dumps(report))
    assert round_trip["files"][0]["defects"][0]["timestamp_seconds"].hex() == a.defects[0].timestamp_seconds.hex()


@pytest.mark.parametrize("rate", ["24", "25", "30"])
def test_bwf_integer_hour_start(rate):
    result = file_timecode(audio(0), settings(rate))
    assert result["defects"][0]["timecode"] == "01:00:00:00"


@pytest.mark.parametrize("reference", [None, -1, 1.0, "172800000", True, 2**64])
def test_auto_fallback_ignores_origination_time(reference):
    result = file_timecode(audio(reference=reference), settings())
    assert result["defects"][0]["timecode"] == "00:00:52:17"
    assert result["timecode_reporting"]["basis"] == "FILE_RELATIVE"
    assert result["timecode_reporting"]["fallback_reason"]


def test_zero_reference_is_valid_and_relative_override_preserves_it():
    a = audio(reference=0)
    assert file_timecode(a, settings())["timecode_reporting"]["basis"] == "BWF_TIMEREFERENCE"
    a = audio()
    result = file_timecode(a, settings(source="FILE_RELATIVE"))
    assert result["bwf"]["time_reference"] == 172800000
    assert result["defects"][0]["timecode"] == "00:00:52:17"


@pytest.mark.parametrize("rate,start,expected", [
    ("25", "10:00:00:00", "10:00:52:17"),
    ("23.976", "10:00:00:00", "10:00:52:15"),
    ("29.97 NDF", "10:00:00:00", "10:00:52:19"),
    ("29.97 DF", "10:00:59;29", "10:01:52;20"),
])
def test_manual_origin_is_a_frame_label(rate, start, expected):
    result = file_timecode(audio(), settings(rate, "MANUAL", start))
    assert result["defects"][0]["timecode"] == expected
    assert result["defects"][0]["file_start_timecode"] == start
    assert result["timecode_reporting"]["basis"] == "MANUAL"


@pytest.mark.parametrize("sample,expected", [
    (0, "00:00:00:00"), (1919, "00:00:00:00"), (1920, "00:00:00:01"),
    (1921, "00:00:00:01"), (48000*60-1, "00:00:59:24"),
    (48000*60, "00:01:00:00"), (48000*3600-1, "00:59:59:24"),
    (48000*3600, "01:00:00:00"), (48000*86400, "00:00:00:00"),
])
def test_containing_frame_and_boundaries(sample, expected):
    rate = RATES["25"]
    assert format_frame(sample_frame(sample, 48000, rate), rate) == expected


@pytest.mark.parametrize("sample,expected", [(47999, "00:00:00:24"), (48000, "00:00:01:00"), (48001, "00:00:01:00")])
def test_second_boundary_in_timecode(sample, expected):
    result = file_timecode(audio(sample, reference=None), settings())
    assert result["defects"][0]["timecode"] == expected


def test_between_frames_preserves_authoritative_location():
    a = audio(1921, reference=1919)
    a.defects[0].timestamp_seconds = 1921/48000
    result = file_timecode(a, settings())
    # floor((1919 + 1921)/1920) = 2, not floor(1919/1920)+floor(1921/1920).
    e = result["defects"][0]
    assert e["timecode"] == "00:00:00:02"
    assert e["sample_index"] == 1921 and e["timestamp_seconds"] == 1921/48000


def test_sample_index_not_float_timestamp_drives_tc():
    a = audio()
    a.defects[0].timestamp_seconds = 52.7034791667
    result = file_timecode(a, settings())
    assert result["defects"][0]["timecode"] == "01:00:52:17"
    assert result["defects"][0]["timestamp_seconds"] == 52.7034791667


@pytest.mark.parametrize("rate,before,after", [("23.976", 2001, 2002), ("29.97 NDF", 1601, 1602), ("29.97 DF", 1601, 1602)])
def test_fractional_frame_boundaries(rate, before, after):
    assert sample_frame(before, 48000, RATES[rate]) == 0
    assert sample_frame(after, 48000, RATES[rate]) == 1


@pytest.mark.parametrize("rate,count", [("23.976", 24000), ("29.97 NDF", 30000), ("29.97 DF", 30000)])
def test_fractional_rates_do_not_accumulate_float_drift(rate, count):
    samples = 48000*1001*10**9
    assert sample_frame(samples, 48000, RATES[rate]) == count*10**9
    assert sample_frame(samples-1, 48000, RATES[rate]) == count*10**9-1


@pytest.mark.parametrize("frame,expected", [
    (1799, "00:00:59;29"), (1800, "00:01:00;02"), (3597, "00:01:59;29"),
    (3598, "00:02:00;02"), (17981, "00:09:59;29"), (17982, "00:10:00;00"),
    (107891, "00:59:59;29"), (107892, "01:00:00;00"),
    (2589407, "23:59:59;29"), (2589408, "00:00:00;00"),
])
def test_drop_frame_numbering_known_boundaries(frame, expected):
    assert format_frame(frame, RATES["29.97 DF"]) == expected
    if frame < 2589408:
        assert parse_start_timecode(expected, RATES["29.97 DF"]) == frame


def test_drop_frame_full_ten_minute_label_sequence():
    # Independent expected sequence: enumerate valid labels, omitting ;00/;01
    # only at the start of minutes 1–9. Exercises all 17,982 consecutive frames.
    frame = 0
    for minute in range(10):
        for second in range(60):
            for label in range(30):
                if minute and second == 0 and label < 2:
                    continue
                expected = f"00:{minute:02d}:{second:02d};{label:02d}"
                assert format_frame(frame, RATES["29.97 DF"]) == expected
                assert parse_start_timecode(expected, RATES["29.97 DF"]) == frame
                frame += 1
    assert frame == 17982


def test_ndf_and_df_same_seconds_different_labels():
    assert file_timecode(audio(0), settings("29.97 NDF"))["defects"][0]["timecode"] == "00:59:56:12"
    assert file_timecode(audio(0), settings("29.97 DF"))["defects"][0]["timecode"] == "01:00:00;00"


def test_day_offset_is_separate_from_24h_tc():
    a = audio(48000*86400+48000, reference=None)
    result = file_timecode(a, settings())
    assert result["defects"][0]["timecode"] == "00:00:01:00"
    assert result["defects"][0]["timecode_day_offset"] == 1
    assert result["defects"][0]["offset"] == "24:00:01.000"


@pytest.mark.parametrize("sample,expected", [(2529767, "00:00:52.703"), (47999, "00:00:00.999"), (48000, "00:00:01.000"), (172800000, "01:00:00.000")])
def test_readable_offset(sample, expected):
    assert format_offset(sample, 48000) == expected


@pytest.mark.parametrize("rate,tc", [("25", "01:00:00:25"), ("24", "10:00:00:24"), ("25", "24:00:00:00"),
                                     ("29.97 DF", "00:01:00;00"), ("29.97 DF", "00:01:00;01"),
                                     ("29.97 DF", "01:00:00:00"), ("29.97 NDF", "01:00:00;00"),
                                     ("25", "10:60:00:00"), ("25", "10:00:60:00"), ("25", None)])
def test_invalid_manual_labels(rate, tc):
    with pytest.raises(ValueError):
        parse_start_timecode(tc, RATES[rate])


@pytest.mark.parametrize("value", [True, None, [], {}, -25, "-25", 23.98, "29.97003", "29.97 DNF"])
def test_invalid_rates(value):
    with pytest.raises(ValueError):
        parse_frame_rate(value)


def test_configuration_and_override_order(tmp_path):
    path = tmp_path/"tc.yaml"
    path.write_text('timecode:\n  frame_rate: "29.97 DF"\n  source: MANUAL\n  manual_start: "10:00:00;00"\n')
    c = load_config(path)
    assert c["timecode"]["frame_rate"] == "29.97 DF"
    c = load_config(path, timecode_overrides={"frame_rate": "25", "source": "FILE_RELATIVE", "manual_start": None})
    assert c["timecode"] == settings("25", "FILE_RELATIVE")
    path.write_text('timecode:\n  source: MANUAL\n')
    with pytest.raises(ConfigError):
        load_config(path)


def test_unknown_rate_unavailable_in_report():
    result = file_timecode(audio(rate=None), settings())
    assert result["defects"][0]["timecode"] is None
    assert result["defects"][0]["offset"] is None


def test_timecode_in_html_json_csv(tmp_path, config):
    report = build_report("/delivery", [audio()], [], config, {}, 0)
    write_reports(report, tmp_path)
    html = (tmp_path/"QC_REPORT.html").read_text()
    assert '<th>TC</th><th>Offset</th>' in html and '<th>Time (s)</th>' not in html
    assert '<span class="tc">01:00:52:17</span>' in html
    assert '00:00:52.703' in html
    header = html.split('</header>')[0]
    assert 'Frame rate: <b>25 fps</b>' in header
    assert 'TC source: <b>BWF TimeReference</b>' in header
    assert 'File start TC: <span class="tc">01:00:00:00</span>' in header
    assert '2529767' in html
    with (tmp_path/"QC_REPORT.csv").open(encoding="utf-8-sig", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["Reporting Frame Rate"] == "25"
    assert row["TimeReference"] == "172800000"
    assert "01:00:52:17" in row["Defect TCs"]


def test_mixed_file_origins_are_not_misrepresented(tmp_path, config):
    a, b = audio(), audio(reference=None)
    b.filename, b.path = "other.wav", "/delivery/other.wav"
    report = build_report("/delivery", [a, b], [], config, {}, 0)
    write_reports(report, tmp_path)
    header = (tmp_path/"QC_REPORT.html").read_text().split('</header>')[0]
    assert "Mixed" in header and "Varies by file" in header


@pytest.mark.integration
def test_cli_reporting_overrides_and_sources_unchanged(wav, tmp_path):
    import hashlib
    before = (hashlib.sha256(wav.read_bytes()).hexdigest(), wav.stat().st_mtime_ns)
    out = tmp_path/"report"
    assert main(["inspect", str(wav), "--frame-rate", "29.97 DF", "--start-timecode", "10:00:00;00", "--quiet", "--output", str(out)]) == 0
    r = json.loads((out/"QC_REPORT.json").read_text())
    assert r["files"][0]["timecode_reporting"]["file_start_timecode"] == "10:00:00;00"
    assert r["configuration"]["timecode"] == settings("29.97 DF", "MANUAL", "10:00:00;00")
    assert before == (hashlib.sha256(wav.read_bytes()).hexdigest(), wav.stat().st_mtime_ns)


def test_cli_invalid_df_is_rejected_before_scan(tmp_path, monkeypatch):
    monkeypatch.setattr("audio_qc.cli.check_tools", lambda: pytest.fail("Should validate before scanning"))
    assert main([str(tmp_path), "--frame-rate", "29.97 DF", "--start-timecode", "00:01:00;00"]) == 2


@pytest.mark.integration
def test_real_bwf_detector_example_retains_exact_samples(tmp_path, config):
    from audio_qc.hashing import sha256_file
    from audio_qc.scanner import inspect_file
    from audio_qc.synthetic import sine, write_wav
    signal = sine(54, amplitude=.04, frequency=220)
    signal[2529767:2529770] += .8
    path = write_wav(tmp_path/"new-synthetic-bwf.wav", signal, bext=True, time_reference=172800000)
    before = (sha256_file(path), path.stat().st_mtime_ns)
    config["defects"]["enabled"] = True
    a = inspect_file(path, config)
    assert len(a.defects) == 1 and a.defects[0].sample_index == 2529767
    report = build_report(path, [a], [], config, {}, 0)
    write_reports(report, tmp_path)
    event = json.loads((tmp_path/"QC_REPORT.json").read_text())["files"][0]["defects"][0]
    assert event["timecode"] == "01:00:52:17"
    assert event["timestamp_seconds"] == 2529767/48000
    assert event["sample_index"] == a.defects[0].sample_index
    assert before == (sha256_file(path), path.stat().st_mtime_ns)


def test_mode_yaml_alias_matches_existing_source(tmp_path):
    path = tmp_path/"mode.yaml"
    path.write_text('timecode:\n  frame_rate: 25\n  mode: MANUAL\n  manual_start: "10:00:00:00"\n')
    assert load_config(path)["timecode"] == settings("25", "MANUAL", "10:00:00:00")
    overridden = load_config(path, timecode_overrides={"source": "AUTO", "manual_start": None})
    assert overridden["timecode"] == settings()


@pytest.mark.parametrize("yaml", [
    "timecode:\n  mode: AUTO\n  source: MANUAL\n",
    "timecode:\n  mode: INVALID\n",
    "timecode:\n  mode: MANUAL\n",
])
def test_mode_alias_rejects_invalid_or_conflicting_values(tmp_path, yaml):
    path = tmp_path/"invalid.yaml"
    path.write_text(yaml)
    with pytest.raises(ConfigError):
        load_config(path)


def test_mode_alias_accepts_matching_source_and_does_not_mutate_overrides(tmp_path):
    path = tmp_path/"matching.yaml"
    path.write_text("timecode:\n  mode: FILE_RELATIVE\n  source: FILE_RELATIVE\n")
    assert load_config(path)["timecode"]["source"] == "FILE_RELATIVE"
    override = {"mode": "AUTO"}
    assert load_config(path, timecode_overrides=override)["timecode"]["source"] == "AUTO"
    assert override == {"mode": "AUTO"}


def test_offsets_have_no_video_frame_rate_dependency(monkeypatch):
    monkeypatch.delitem(RATES, "25")
    assert format_offset(2529767, 48000) == "00:00:52.703"


@pytest.mark.parametrize("sample,rate", [(-1, 48000), (1, 0), (1.0, 48000), (True, 48000)])
def test_invalid_offset_inputs(sample, rate):
    with pytest.raises(ValueError):
        format_offset(sample, rate)


@pytest.mark.parametrize("frame_rate", list(RATES))
@pytest.mark.parametrize("source", ["AUTO", "FILE_RELATIVE", "MANUAL"])
def test_reporting_preserves_detector_count_and_all_legacy_fields(config, frame_rate, source):
    from audio_qc.defects import detect_window
    from audio_qc.synthetic import defect_signals
    a = audio()
    a.defects = detect_window(defect_signals()["channel_dropout"], 48000, config["defects"])
    assert len(a.defects) == 1
    before = deepcopy(asdict(a))
    config["timecode"] = settings(frame_rate, source,
                                   "10:00:00;00" if frame_rate == "29.97 DF" else "10:00:00:00")
    if source != "MANUAL":
        config["timecode"]["manual_start"] = None
    report = build_report("/delivery", [a], [], config, {}, 0)
    events = report["files"][0]["defects"]
    assert len(events) == len(a.defects)
    legacy_keys = ("timestamp_seconds", "sample_index", "channel", "event_type", "duration_seconds",
                   "severity", "measurements", "detection_method", "snippet")
    for measured, rendered in zip(before["defects"], events):
        assert {key: rendered[key] for key in legacy_keys} == {key: measured[key] for key in legacy_keys}
    assert asdict(a) == before


def test_cli_rejects_unsupported_rate_before_any_scan(tmp_path, monkeypatch):
    monkeypatch.setattr("audio_qc.cli.check_tools", lambda: pytest.fail("Validation must precede scanning"))
    assert main([str(tmp_path), "--frame-rate", "27"]) == 2
