import csv
from hashlib import sha256
import json
from pathlib import Path

import pytest
import yaml

from audio_qc.cli import main
from audio_qc.models import Status
from audio_qc.programme import LAYOUTS
from audio_qc.synthetic import defect_signals, write_wav, sine


def fingerprint(paths):
    return {str(p): (sha256(p.read_bytes()).hexdigest(), p.stat().st_size, p.stat().st_mtime_ns) for p in paths}


def fixtures(source):
    """Real PCM24 decoding/detection, including shared + single-channel events."""
    source.mkdir()
    shared = defect_signals()["zero_dropout"]
    paths = []
    for layout, name in (("stereo", "Diálogo 日本語_EN_PM"), ("5.1", "Episode_PM_51")):
        for role in LAYOUTS[layout]:
            samples = shared.copy()
            if role == "L":
                samples[96000:96960] = 0
            paths.append(write_wav(source/f"{name}_{role}.wav", samples, bext=True, time_reference=172800000))
    paths.append(write_wav(source / "Incomplete_L.wav", shared, bext=True))
    paths.append(write_wav(source / "Mismatch_L.wav", shared, bext=True, time_reference=1000))
    paths.append(write_wav(source / "Mismatch_R.wav", shared, bext=True, time_reference=1001))
    paths.append(write_wav(source / "Independent.wav", sine(channels=6), bext=True, mask=0x3f))
    return paths


@pytest.mark.integration
def test_real_cli_groups_evidence_reports_and_source_integrity(tmp_path, monkeypatch):
    import audio_qc.cli as cli
    source, output = tmp_path / "sources", tmp_path / "reports"
    paths = fixtures(source)
    before = fingerprint(paths)
    calls = []
    original = cli.inspect_file
    def counted(path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(cli, "inspect_file", counted)
    code = main(["inspect", str(source), "--detect-groups", "--export-defect-snippets", "--output", str(output)])
    assert code == 2  # Requested M6 levels for invalid groups are incomplete.
    report = json.loads((output/"QC_REPORT.json").read_text())
    html = (output/"QC_REPORT.html").read_text()
    assert report["schema_version"] == 5
    assert len(calls) == len(set(calls)) == len(paths)
    groups = report["programme_groups"]
    assert len(groups) == 4
    valid = [g for g in groups if g["validation_status"] == "VALID"]
    assert {g["layout"] for g in valid} == {"stereo", "5.1"}
    for group in valid:
        assert group["defect_coverage"] == "COMPLETE"
        assert group["programme_measurement"]["state"] == "SUCCESS"
        shared = [e for e in group["issues"] if e["sample_index"] == 48000]
        assert len(shared) == 2
        assert {e["event_type"] for e in shared} == {"POSSIBLE DROPOUT", "DIGITAL SIGNAL LOSS"}
        assert shared[0]["channels"] == list(LAYOUTS[group["layout"]])
        assert shared[0]["timecode"] == "01:00:01:00"
        assert any(e["channels"] == ["L"] and e["sample_index"] == 96000 for e in group["issues"])
        for issue in group["issues"]:
            assert issue["severity"] == (Status.FAIL if issue["event_type"] == "DIGITAL SIGNAL LOSS" else Status.WARNING)
            assert html.count('data-group-issue="' + issue["id"] + '"') == 1
            for event in issue["channel_events"]:
                assert (output / event["snippet"]).is_file()
                assert "Evidence " + event["logical_channel"] in html
                assert event["physical_channel"] == 1
                # Source measurements are preserved in the file view.
                file = next(f for f in report["files"] if f["path"] == event["source_path"])
                original_event = file["defects"][event["file_issue_index"]-1]["channel_events"][0]
                assert original_event["measurements"] == event["source_event"]["measurements"]
    assert 'target="_blank" rel="noopener"' in html
    assert "Channels: L, R, C, LFE, Ls, Rs" in html
    assert "virtual_multichannel" in html
    assert report["summary"]["group_level_issues"] == sum(len(g["issues"]) for g in groups)
    assert report["summary"]["file_level_issues"] == report["summary"]["defect_issues"]
    assert report["summary"]["file_level_issues"] > report["summary"]["group_level_issues"]
    assert all(not g["issues"] for g in groups if g not in valid)
    with (output/"QC_GROUP_ISSUES.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == report["summary"]["group_level_issues"]
    assert "QC_GROUP_ISSUES.csv" in json.loads((output/"QC_COMPLETE.json").read_text())["reports"]
    assert fingerprint(paths) == before


@pytest.mark.integration
def test_cli_disabled_default_and_explicit_manifest_missing_member(tmp_path):
    source = tmp_path / "sources"
    source.mkdir()
    path = write_wav(source / "some L.wav", sine(), bext=False)
    before = fingerprint([path])
    manifest = tmp_path / "groups.yaml"
    manifest.write_text(yaml.safe_dump({"schema_version": 1, "programme_groups": [{"id": "explicit", "layout": "stereo",
                        "alignment": {"mode": "common_file_start"}, "members": [
                            {"channel": "L", "file": "sources/some L.wav"},
                            {"channel": "R", "file": "missing R.wav"}]}]}))
    output = tmp_path / "explicit_report"
    assert main([str(source), "--groups", str(manifest), "--output", str(output)]) == 2
    report = json.loads((output/"QC_REPORT.json").read_text())
    assert len(report["files"]) == 2
    assert report["programme_groups"][0]["validation_status"] != "VALID"
    assert not report["programme_groups"][0]["issues"]
    assert next(f for f in report["files"] if f["path"] == str(path))["measurements"]["decoded_sample_frames"] == 192000
    output = tmp_path / "ordinary_report"
    assert main([str(source), "--output", str(output)]) == 0
    report = json.loads((output/"QC_REPORT.json").read_text())
    assert report["programme_groups"] == []
    assert not (output/"QC_GROUP_ISSUES.csv").exists()
    assert fingerprint([path]) == before


def test_malformed_manifest_rejected_before_tools_or_scan(tmp_path, monkeypatch):
    import audio_qc.cli as cli
    path = tmp_path / "groups.yaml"
    path.write_text("schema_version: 1\nunknown: yes\n")
    monkeypatch.setattr(cli, "check_tools", lambda: pytest.fail("tools called before validation"))
    output = tmp_path / "out"
    assert main([str(tmp_path), "--groups", str(path), "--output", str(output)]) == 2
    assert not output.exists()
