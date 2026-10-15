import csv
import json
from copy import deepcopy

import pytest

from audio_qc.models import AudioFile, Defect, Status
from audio_qc.reports import build_report, write_reports
from audio_qc.reports.csv_report import write_defects_csv


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def candidate_file():
    a = AudioFile("/delivery/Diálogo 日本語.wav", "Diálogo 日本語.wav", sample_rate=48000,
                  bwf={"present": True, "time_reference": 172800000})
    for sample in (2529767, 2529768):
        a.defects.append(Defect(sample/48000, sample, 1, "POSSIBLE CLICK / TICK", 3/48000,
                                Status.WARNING, {"test_value": 12.345}, "test_method"))
    return a


def test_csv_uses_canonical_positions_and_preserves_file_summary(tmp_path, config):
    a = candidate_file()
    original = deepcopy(a.to_dict())
    report = build_report("/delivery", [a], [], config, {}, 0)
    write_reports(report, tmp_path)
    rows = read_csv(tmp_path/"QC_DEFECTS.csv")
    assert len(rows) == 2
    assert len(read_csv(tmp_path/"QC_REPORT.csv")) == 1
    for row, event in zip(rows, report["files"][0]["defects"]):
        assert row["TC"] == event["timecode"] == "01:00:52:17"
        assert row["Offset"] == event["offset"] == "00:00:52.703"
        assert row["Frame Rate"] == event["timecode_frame_rate"] == "25"
        assert row["TC Basis"] == event["timecode_basis"] == "BWF_TIMEREFERENCE"
        assert row["File Start TC"] == "01:00:00:00"
        assert int(row["Sample Index"]) == event["sample_index"]
        assert float(row["Timestamp Seconds"]).hex() == event["timestamp_seconds"].hex()
        assert int(row["TimeReference"]) == 172800000
        assert json.loads(row["Evidence"]) == event["measurements"]
        assert row["File"] == a.filename
    assert a.to_dict() == original


def test_csv_empty_candidates_and_no_overwrite(tmp_path, config):
    report = build_report("/delivery", [], [], config, {}, 0)
    path = tmp_path/"QC_DEFECTS.csv"
    write_defects_csv(report, path)
    assert read_csv(path) == []
    assert "TC,Offset,Frame Rate,TC Basis" in path.read_text(encoding="utf-8-sig")
    with pytest.raises(FileExistsError):
        write_defects_csv(report, path)


def test_csv_unavailable_positions_are_blank_and_text_is_safe(tmp_path, config):
    a = candidate_file()
    a.filename = '=HYPERLINK("example")'
    a.sample_rate = None
    a.defects[0].detection_method = "@unsafe"
    report = build_report("/delivery", [a], [], config, {}, 0)
    path = tmp_path/"QC_DEFECTS.csv"
    write_defects_csv(report, path)
    row = read_csv(path)[0]
    assert row["TC"] == row["Offset"] == ""
    assert row["File"].startswith("'=")
    assert row["Method"] == "'@unsafe"
    assert row["Sample Index"] == "2529767"


def test_csv_drop_frame_and_day_offsets(tmp_path, config):
    a = candidate_file()
    config["timecode"] = {"frame_rate": "29.97 DF", "source": "MANUAL", "manual_start": "23:59:59;29"}
    report = build_report("/delivery", [a], [], config, {}, 0)
    write_reports(report, tmp_path)
    row = read_csv(tmp_path/"QC_DEFECTS.csv")[0]
    event = report["files"][0]["defects"][0]
    assert row["TC"] == event["timecode"] and ";" in row["TC"]
    assert row["TC Day Offset"] == "1"
    assert row["File Start TC Day Offset"] == "0"
    assert row["Frame Rate"] == "29.97 DF"
    assert row["TC Basis"] == "MANUAL"


def test_html_labels_rate_as_reporting_setting(tmp_path, config):
    report = build_report("/delivery", [candidate_file()], [], config, {}, 0)
    write_reports(report, tmp_path)
    html = (tmp_path/"QC_REPORT.html").read_text()
    assert "Frame rate is a reporting setting" in html
    assert "not timecode metadata embedded in the WAV" in html
