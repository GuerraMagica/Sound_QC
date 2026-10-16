"""Regressions from the real 5.1 acceptance report; no client audio bundled."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from audio_qc.loudness import LoudnessParser
from audio_qc.models import Status, MeasurementState as MS, Check
from audio_qc.reports import build_report, write_reports
from audio_qc.scanner import inspect_file
from test_programme import audio, event, build


def parsed(bad_key, token="nan"):
    parser = LoudnessParser()
    for line in ("pts_time:9.5", "lavfi.r128.I=-30.127", "lavfi.r128.M=-32", "lavfi.r128.S=-33",
                 "lavfi.r128.LRA=18.28", f"lavfi.r128.{bad_key}={token}",
                 "pts_time:12", "lavfi.r128.M=-31", "lavfi.r128.S=-32", "lavfi.r128.LRA=18.28",
                 "lavfi.r128.I=-30.127", "Summary:", "True peak:", "Peak: -2.0 dBFS"):
        parser.feed(line)
    return parser.result(3245.96)


@pytest.mark.parametrize("key,metric", [("M", "max_momentary_lufs"), ("S", "max_short_term_lufs"), ("LRA", "lra_lu")])
@pytest.mark.parametrize("token", ["nan", "+inf", "broken"])
def test_auxiliary_error_does_not_invalidate_finite_integrated_loudness(key, metric, token):
    result = parsed(key, token)
    assert result["integrated_lufs"] == -30.127
    assert result["true_peak_dbtp"] == -2
    assert result["measurement_outcomes"]["integrated_lufs"].state == MS.SUCCESS
    assert result["measurement_outcomes"]["true_peak_dbtp"].state == MS.SUCCESS
    assert result["measurement_outcomes"][metric].state == MS.ERROR
    assert f"{key}={token} at 9.5 s" in result["measurement_outcomes"][metric].reason
    assert result[metric] is None  # A later finite sample must not hide a missing window.
    for other in {"max_momentary_lufs", "max_short_term_lufs", "lra_lu"} - {metric}:
        assert result[other] is not None
        assert result["measurement_outcomes"][other].state == MS.SUCCESS


def test_mandatory_integrated_error_is_still_latched():
    result = parsed("I")
    assert result["integrated_lufs"] is None
    assert result["measurement_outcomes"]["integrated_lufs"].state == MS.ERROR
    assert result["true_peak_dbtp"] == -2


@pytest.mark.integration
def test_auxiliary_error_is_an_operational_warning_not_an_acoustic_defect(wav, config, monkeypatch):
    from audio_qc import scanner
    monkeypatch.setattr(scanner, "measure_loudness", lambda *args, **kwargs: parsed("S"))
    before = wav.read_bytes()
    result = inspect_file(wav, config)
    assert result.measurements["integrated_lufs"] == -30.127
    assert result.measurement_outcomes["max_short_term_lufs"].state == MS.ERROR
    assert result.execution_status == "COMPLETED_WITH_WARNINGS"
    assert result.status == Status.PASS
    assert not result.defects
    diagnostic, = result.operational_diagnostics
    assert diagnostic.code == "max_short_term_lufs"
    assert not diagnostic.required and not diagnostic.affects_analysis
    assert wav.read_bytes() == before


@pytest.mark.parametrize("first_rs,expected", [(4800077, 2), (4800138, 2), (4800139, 1), (4800140, 1)])
def test_real_surround_pair_uses_cluster_starts_not_near_identical_representatives(tmp_path, config, first_rs, expected):
    files = [audio(tmp_path, ch, count=155806080) for ch in ("L", "R", "C", "LFE", "Ls", "Rs")]
    files[-1].defects = [replace(event(4800188, Status.WARNING, first=first_rs, last=4800202), merged_candidate_count=2)]
    files[-2].defects = [event(4800187, Status.WARNING, first=4800187, last=4800203)]
    before = deepcopy(files)
    groups = build(files)
    assert len(groups[0]["issues"]) == expected
    assert files == before
    report = build_report(tmp_path, files, [], config, {}, 0, programme_groups=groups)
    issues = report["programme_groups"][0]["issues"]
    assert {i["timecode"] for i in issues} == {"01:01:40:00"}
    if first_rs == 4800077:
        assert issues[1]["cluster_first_sample"] - issues[0]["cluster_first_sample"] == 110
        assert 110 / 48000 * 1000 == pytest.approx(2.2916666667)
        assert issues[0]["channels"] == ["Rs"] and issues[1]["channels"] == ["Ls"]
        assert issues[0]["channel_events"][0]["source_event"]["sample_index"] == 4800188
        assert issues[1]["channel_events"][0]["source_event"]["sample_index"] == 4800187


def test_scope_category_summary_and_cap_are_explicit_without_reclassifying_files(tmp_path, config):
    from audio_qc.programme import default_group_settings
    files = [audio(tmp_path, ch, count=155806080) for ch in ("L", "R")]
    for f in files:
        f.checks = [Check("integrated_loudness", Status.FAIL, "Mono diagnostic versus -24 LUFS")]
        f.defects = [event(i*100, Status.WARNING, kind="POSSIBLE CLICK / TICK" if i % 2 else "DIGITAL DROPOUT") for i in range(1001)]
    files[0].add("defects_capped", Status.WARNING, "Member limit reached")
    before = deepcopy(files)
    groups = build(files, max_issues=1000)
    report = build_report(tmp_path, files, [], config, {}, 0, programme_groups=groups,
                          programme_settings=default_group_settings())
    assert files == before
    assert report["audio_compliance"] == "FAIL"  # Preserve configured physical-file diagnostics.
    assert report["compliance_scope"] == "PHYSICAL_FILES"
    assert report["programme_compliance"] == "NOT_EVALUATED"
    group, = report["programme_groups"]
    assert group["programme_compliance"] == "NOT_EVALUATED"
    assert group["issue_summary"]["retained_issues"] == 1000
    assert group["issue_summary"]["by_type"] == {"DIGITAL DROPOUT": 500, "POSSIBLE CLICK / TICK": 500}
    assert group["issue_summary"]["coverage"] == "INCOMPLETE"
    assert len(group["issues"]) == 1000
    write_reports(report, tmp_path)
    html = (tmp_path/"QC_REPORT.html").read_text()
    assert "Physical-file QC diagnostics" in html
    assert "Programme compliance: NOT_EVALUATED" in html
    assert "These retained results do not represent full defect coverage" in html
    assert html.count('<details class="issue-category">') == 2
    assert '<details class="issue-category" open' not in html
    assert html.count("retained issues</summary>") == 2
    assert html.count("data-group-issue=") == 1000
    assert "physical-channel diagnostic" in html
    assert report["summary"]["file_level_issues"] == 2002
    assert report["summary"]["group_level_issues"] == 1000


def test_nonfinite_source_cannot_be_certified_even_if_ffmpeg_could_return_finite_values(monkeypatch):
    from audio_qc.models import AudioFile
    from audio_qc import loudness
    a = AudioFile("/invalid.wav", "invalid.wav", channels=1, measurements={"nonfinite_samples": 1})
    monkeypatch.setattr(loudness, "stream_process", lambda *a, **k: pytest.fail("Known corrupt samples must not be certified"))
    result = loudness.measure_loudness(Path(a.path), a)
    assert all(o.state == MS.ERROR for o in result["measurement_outcomes"].values())
    assert result["integrated_lufs"] is None and result["true_peak_dbtp"] is None


@pytest.mark.parametrize("severities,expected", [
    ((None, None), None), ((Status.INFO, Status.WARNING), Status.WARNING),
    ((Status.WARNING, Status.INFO), Status.WARNING), ((Status.WARNING, Status.FAIL), Status.FAIL),
    ((Status.FAIL, Status.WARNING), Status.FAIL),
])
def test_group_retains_assessed_file_issue_severity_and_unclassified_forensics(tmp_path, severities, expected):
    from dataclasses import asdict
    from audio_qc.models import DefectIssue
    files = [audio(tmp_path, ch) for ch in ("L", "R")]
    for f, severity in zip(files, severities):
        measured = event()
        f.defects = [DefectIssue(**(asdict(measured) | {"severity": severity}),
                                channels=[1], channel_events=[measured])]
    before = deepcopy(files)
    group, = build(files)
    issue, = group["issues"]
    assert issue["severity"] == expected
    assert [e["file_issue_severity"] for e in issue["channel_events"]] == list(severities)
    assert all(e["source_event"]["severity"] is None for e in issue["channel_events"])
    assert files == before
