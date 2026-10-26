from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from audio_qc.config import ConfigError
from audio_qc.models import AudioFile, Defect, MeasurementOutcome, MeasurementState, Status
from audio_qc.programme import (LAYOUTS, ProgrammeDefinition, ProgrammeMember, default_group_settings,
                                validate_group_settings, load_group_settings, discover_programmes, build_programmes)


def audio(tmp_path, channel, *, name="Programme", origin=172800000, count=192000, rate=48000):
    path = tmp_path / f"{name}_{channel}.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    return AudioFile(str(path), path.name, channels=1, sample_rate=rate, codec="pcm_s24le", bit_depth=24,
                     measurements={"decoded_sample_frames": count},
                     bwf={"present": origin is not None, "time_reference": origin},
                     measurement_outcomes={"samples": MeasurementOutcome(MeasurementState.SUCCESS)})


def event(sample=1000, severity=None, kind="POSSIBLE CLICK / TICK", first=None, last=None):
    return Defect(sample/48000, sample, 1, kind, 1/48000, severity,
                  {"duration_samples": 1, "impulse_deviation_db": 30.5}, "test exact samples",
                  cluster_first_sample=sample if first is None else first,
                  cluster_last_sample=sample if last is None else last)


def build(files, settings=None, **kwargs):
    settings = settings or default_group_settings()
    definitions = discover_programmes([a.path for a in files], settings)
    return build_programmes(definitions, files, detection_enabled=kwargs.pop("detection_enabled", True), **kwargs)


@pytest.mark.parametrize("layout", LAYOUTS)
def test_valid_layout_and_input_immutability(tmp_path, layout):
    files = [audio(tmp_path, ch) for ch in LAYOUTS[layout]]
    for a in files:
        a.defects = [event()]
    before = deepcopy(files)
    group, = build(files)
    assert group["validation_status"] == "VALID"
    assert group["layout"] == layout
    assert group["group_origin"] == 172800000
    assert group["coverage"]["union_end_exclusive"] == 192000
    assert len(group["issues"]) == 1
    assert group["issues"][0]["channels"] == list(LAYOUTS[layout])
    assert group["issues"][0]["severity"] is None
    assert files == before


@pytest.mark.parametrize("change,code,status", [
    ("missing", "missing_channels", "INCOMPLETE"),
    ("duplicate", "duplicate_channels", "AMBIGUOUS"),
    ("rate", "sample_rate_mismatch", "TECHNICALLY_INCONSISTENT"),
    ("count", "sample_count_mismatch", "TECHNICALLY_INCONSISTENT"),
    ("origin", "bwf_start_mismatch", "TECHNICALLY_INCONSISTENT"),
    ("mixed_bwf", "mixed_timing", "TECHNICALLY_INCONSISTENT"),
    ("stereo", "not_mono", "TECHNICALLY_INCONSISTENT"),
    ("decode", "unreadable_media", "TECHNICALLY_INCONSISTENT"),
    ("format", "unsupported_format", "TECHNICALLY_INCONSISTENT"),
    ("corrupt", "unreliable_source", "TECHNICALLY_INCONSISTENT"),
])
def test_invalid_groups_preserve_independent_files(tmp_path, change, code, status):
    files = [audio(tmp_path, ch) for ch in ("L", "R")]
    for a in files:
        a.defects = [event()]
    if change == "missing":
        files.pop()
    elif change == "duplicate":
        duplicate = deepcopy(files[0])
        duplicate.path = str(tmp_path / "Programme.L.wav")
        Path(duplicate.path).touch()
        files.append(duplicate)
    elif change == "rate":
        files[1].sample_rate = 44100
    elif change == "count":
        files[1].measurements["decoded_sample_frames"] += 1
    elif change == "origin":
        files[1].bwf["time_reference"] += 1
    elif change == "mixed_bwf":
        files[1].bwf = {}
    elif change == "stereo":
        files[1].channels = 2
    elif change == "decode":
        files[1].measurement_outcomes["samples"] = MeasurementOutcome(MeasurementState.ERROR, "permission denied")
    elif change == "format":
        files[1].codec = "flac"
    elif change == "corrupt":
        files[1].bwf["errors"] = ["truncated data"]
    before = deepcopy(files)
    group, = build(files)
    assert group["validation_status"] == status
    assert code in [r["code"] for r in group["reasons"]]
    assert not group["issues"]
    assert group["defect_coverage"] == "INCOMPLETE"
    assert files == before


def test_no_bwf_conservative_start_and_large_origin(tmp_path):
    files = [audio(tmp_path, ch, origin=None) for ch in ("L", "R")]
    group, = build(files)
    assert group["validation_status"] == "VALID"
    assert group["alignment_mode"] == "common_file_start"
    assert group["warnings"][0]["code"] == "assumed_common_start"
    for a in files:
        a.bwf = {"present": True, "time_reference": 2**63+17}
    group, = build(files)
    assert group["group_origin"] == 2**63+17
    files[1].bwf["time_reference"] += 1
    group, = build(files)
    assert group["validation_status"] == "TECHNICALLY_INCONSISTENT"
    assert group["coverage"]["start_spread_samples"] == 1
    assert group["coverage"]["end_spread_samples"] == 1
    assert group["coverage"]["overlap_start"] == 1


def test_explicit_common_start_discloses_contradictory_bwf(tmp_path):
    files = [audio(tmp_path, "L", origin=1), audio(tmp_path, "R", origin=22)]
    settings = default_group_settings()
    settings["naming"]["alignment"] = "common_file_start"
    group, = build(files, settings)
    assert group["validation_status"] == "VALID"
    assert group["warnings"][0]["code"] == "bwf_contradicts_common_start"
    assert group["coverage"]["start_spread_samples"] == 0


def test_required_bwf_and_bit_depth_warning(tmp_path):
    files = [audio(tmp_path, ch, origin=None) for ch in ("L", "R")]
    settings = default_group_settings()
    settings["naming"]["alignment"] = "bwf_time_reference"
    group, = build(files, settings)
    assert "missing_bwf" in [r["code"] for r in group["reasons"]]
    files[1].bit_depth = 16
    files[1].codec = "pcm_s16le"
    group, = build(files)
    assert group["validation_status"] == "VALID"
    assert "mixed_pcm_formats" in [r["code"] for r in group["warnings"]]


def test_identity_requires_full_prefix_directory_and_case(tmp_path):
    files = [audio(tmp_path, "L", name="episode_EN_PM"), audio(tmp_path, "R", name="episode_ES_PM"),
             audio(tmp_path / "other", "R", name="episode_EN_PM"), audio(tmp_path, "R", name="episode_EN_pm")]
    groups = build(files)
    assert len(groups) == 4
    assert all(g["validation_status"] == "INCOMPLETE" for g in groups)
    assert discover_programmes([tmp_path / "other.wav"], default_group_settings()) == ()


def test_yaml_relative_unicode_and_explicit_members(tmp_path):
    raw = {"schema_version": 1, "programme_groups": [{"id": "p", "name": "日本語 diálogo", "layout": "stereo",
           "alignment": {"mode": "common_file_start"}, "members": [
               {"channel": "L", "file": "Áudio L.wav"}, {"channel": "R", "file": "Áudio R.wav"}]}]}
    path = tmp_path / "groups.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True))
    settings = load_group_settings(path)
    definitions = discover_programmes([], settings)
    assert definitions[0].members[0].file == str(tmp_path / "Áudio L.wav")
    group, = build_programmes(definitions, [], detection_enabled=True)
    assert group["validation_status"] == "INCOMPLETE"
    assert group["name"] == "日本語 diálogo"


@pytest.mark.parametrize("raw", [
    {"schema_version": True}, {"schema_version": 2}, {"schema_version": 1, "typo": 1},
    {"schema_version": 1, "naming": {"enabled": "yes"}},
    {"schema_version": 1, "naming": {"layout": "7.1"}},
    {"schema_version": 1, "naming": {"alignment": "guess"}},
    {"schema_version": 1, "naming": {"suffixes": {"L": ["L"]}}},
    {"schema_version": 1, "naming": {"suffixes": {"L": ["_L"], "R": ["_L"]}}},
    {"schema_version": 1, "naming": {"suffixes": {"L": ["_L"], "R": ["_foo_L"]}}},
    {"schema_version": 1, "programme_groups": "bad"},
])
def test_strict_config(raw, tmp_path):
    with pytest.raises(ConfigError):
        validate_group_settings(raw, tmp_path)


def test_unsafe_yaml_and_duplicate_keys(tmp_path):
    path = tmp_path / "groups.yaml"
    for text in ("schema_version: 1\nschema_version: 1", "!!python/object/apply:os.system ['false']"):
        path.write_text(text)
        with pytest.raises(ConfigError):
            load_group_settings(path)


def test_custom_suffixes_and_layout(tmp_path):
    settings = validate_group_settings({"schema_version": 1, "naming": {"enabled": True, "layout": "stereo",
               "suffixes": {"L": ["-LEFT"], "R": ["-RIGHT"]}}}, tmp_path)
    definitions = discover_programmes([tmp_path / "Print Mix-LEFT.wav", tmp_path / "Print Mix-RIGHT.wav"], settings)
    assert len(definitions) == 1
    assert definitions[0].name == "Print Mix"
    assert [m.channel for m in definitions[0].members] == ["L", "R"]


def test_canonical_duplicate_and_shared_file_are_ambiguous(tmp_path):
    file = audio(tmp_path, "L")
    member = ProgrammeMember("L", file.path)
    definition = ProgrammeDefinition("p", "P", "stereo", "auto", (member, replace(member, channel="R")))
    group, = build_programmes([definition], [file], detection_enabled=True)
    assert "duplicate_file" in [r["code"] for r in group["reasons"]]
    groups = build_programmes([definition, replace(definition, id="q")], [file], detection_enabled=True)
    assert all("shared_file" in [r["code"] for r in g["reasons"]] for g in groups)


@pytest.mark.parametrize("delta,count", [(0, 1), (48, 1), (49, 2), (377, 2)])
def test_exact_inclusive_tolerance_and_subframe_events(tmp_path, delta, count):
    files = [audio(tmp_path, ch) for ch in ("L", "R")]
    files[0].defects = [event(1000)]
    files[1].defects = [event(1000+delta)]
    group, = build(files)
    assert len(group["issues"]) == count


def test_fixed_window_no_chaining_or_overlap_only(tmp_path):
    files = [audio(tmp_path, ch) for ch in LAYOUTS["5.1"]]
    for a, sample in zip(files, [1000, 1048, 1096]):
        a.defects = [event(sample, last=2000)]
    group, = build(files)
    assert [i["channels"] for i in group["issues"]] == [["L", "R"], ["C"]]


def test_cluster_start_not_representative_and_forensics(tmp_path):
    files = [audio(tmp_path, ch) for ch in ("L", "R")]
    files[0].defects = [replace(event(1050, Status.INFO, first=1000, last=1060), merged_candidate_count=2)]
    files[1].defects = [event(1048, Status.WARNING)]
    group, = build(files)
    issue, = group["issues"]
    assert issue["sample_index"] == 1000
    assert issue["cluster_last_sample"] == 1060
    assert issue["severity"] == Status.WARNING
    assert issue["merged_candidate_count"] == 3
    assert issue["channel_events"][0]["source_event"] == __import__("dataclasses").asdict(files[0].defects[0])
    assert issue["channel_events"][0]["group_sample_index"] == 1050
    assert issue["channel_events"][1]["physical_channel"] == 1
    assert issue["channel_events"][1]["logical_channel"] == "R"
    assert issue["channel_events"][1]["source_path"] == files[1].path
    assert build(list(reversed(files))) == [group]


def test_different_type_same_channel_and_independent_groups(tmp_path):
    files = [audio(tmp_path, ch) for ch in ("L", "R")]
    files[0].defects = [event(), event(1001), event(1002, kind="DIGITAL DROPOUT")]
    files[1].defects = [event()]
    group, = build(files)
    assert len(group["issues"]) == 3
    others = [audio(tmp_path, ch, name="Other") for ch in ("L", "R")]
    others[0].defects = [event()]
    groups = build(files + others)
    assert len(groups) == 2
    assert sorted(len(g["issues"]) for g in groups) == [1, 3]


@pytest.mark.parametrize("left,right,expected", [(Status.INFO, Status.WARNING, Status.WARNING),
                                                 (Status.FAIL, Status.WARNING, Status.FAIL), (None, None, None)])
def test_severity_and_unclassified_measurements(tmp_path, left, right, expected):
    files = [audio(tmp_path, ch) for ch in ("L", "R")]
    files[0].defects = [event(severity=left)]
    files[1].defects = [event(1001, right)]
    assert build(files)[0]["issues"][0]["severity"] == expected
    assert build(list(reversed(files)))[0]["issues"][0]["severity"] == expected


def test_cap_counts_issues_preserves_constituents_and_warns(tmp_path):
    files = [audio(tmp_path, ch) for ch in ("L", "R")]
    for a in files:
        a.defects = [event(1000), event(1100)]
    group, = build(files, max_issues=1)
    assert len(group["issues"]) == 1
    assert group["issues"][0]["channels"] == ["L", "R"]
    assert group["issues_capped"]
    assert group["defect_coverage"] == "INCOMPLETE"
    files[0].add("defects_capped", Status.WARNING, "public limit exceeded")
    group, = build(files)
    assert "defects_capped" in str(group["coverage_limitations"])
    assert group["defect_coverage"] == "INCOMPLETE"
    group, = build(files, detection_enabled=False)
    assert not group["issues"]
    assert group["defect_coverage"] == "NOT_MEASURED"


def test_invalid_bwf_never_silently_falls_back(tmp_path):
    files = [audio(tmp_path, ch) for ch in ("L", "R")]
    for a in files:
        a.bwf["time_reference"] = 2**64
    group, = build(files)
    assert group["validation_status"] == "TECHNICALLY_INCONSISTENT"
    assert "invalid_bwf" in [r["code"] for r in group["reasons"]]


@pytest.mark.parametrize("mutation", ["id", "layout", "channel", "field", "members"])
def test_explicit_manifest_strict_fields(tmp_path, mutation):
    group = {"id": "p", "layout": "stereo", "alignment": {"mode": "auto"},
             "members": [{"channel": "L", "file": "p_L.wav"}]}
    groups = [group]
    if mutation == "id":
        groups.append(deepcopy(group))
    elif mutation == "layout":
        group["layout"] = []
    elif mutation == "channel":
        group["members"][0]["channel"] = None
    elif mutation == "field":
        group["members"][0]["typo"] = "x"
    else:
        group["members"] = []
    with pytest.raises(ConfigError):
        validate_group_settings({"schema_version": 1, "programme_groups": groups}, tmp_path)


def test_canonical_path_aliases(tmp_path):
    (tmp_path / "sub").mkdir()
    settings = validate_group_settings({"schema_version": 1, "programme_groups": [{"id": "p", "layout": "stereo",
        "alignment": {"mode": "auto"}, "members": [{"channel": "L", "file": "Programme_L.wav"},
        {"channel": "R", "file": "sub/../Programme_L.wav"}]}]}, tmp_path)
    a = audio(tmp_path, "L")
    group, = build([a], settings)
    assert group["validation_status"] == "AMBIGUOUS"
    assert "duplicate_file" in [r["code"] for r in group["reasons"]]


@pytest.mark.parametrize("source,manual,expected", [("AUTO", None, "01:00:00:00"),
    ("FILE_RELATIVE", None, "00:00:00:00"), ("MANUAL", "10:00:00:00", "10:00:00:00")])
def test_group_report_timecode_navigation_and_escaping(tmp_path, config, source, manual, expected):
    from audio_qc.reports import build_report, write_reports
    files = [audio(tmp_path, ch, name='<mix & "quoted">') for ch in ("L", "R")]
    for a in files:
        a.defects = [event(47)]
        a.defects[0].snippet = 'defect_snippets/音 & "clip".wav'
    config["timecode"].update(source=source, manual_start=manual)
    groups = build(files)
    before = deepcopy(groups)
    report = build_report(tmp_path, files, [], config, {}, 0, programme_groups=groups,
                          programme_settings=default_group_settings())
    assert report["programme_groups"][0]["issues"][0]["timecode"] == expected
    assert groups == before
    out = tmp_path / "out"
    out.mkdir()
    write_reports(report, out)
    html = (out / "QC_REPORT.html").read_text()
    assert '<mix & "quoted">' not in html
    assert '&lt;mix &amp; &quot;quoted&quot;&gt;' in html
    assert 'href="defect_snippets/%E9%9F%B3%20%26%20%22clip%22.wav" target="_blank" rel="noopener"' in html
    assert 'Original file-level issues (forensic view)' in html
    assert html.count('data-group-issue=') == 1
    assert report["summary"]["file_level_issues"] == 2
    assert report["summary"]["group_level_issues"] == 1


def test_no_matches_are_explicit_in_group_report(tmp_path, config):
    from audio_qc.reports import build_report, write_reports
    report = build_report(tmp_path, [], [], config, {}, 0, programme_settings=default_group_settings())
    write_reports(report, tmp_path)
    assert "No matching programme definitions found" in (tmp_path/"QC_REPORT.html").read_text()
    assert (tmp_path/"QC_GROUP_ISSUES.csv").is_file()


def test_failed_group_csv_does_not_publish_completion_marker(tmp_path, config, monkeypatch):
    import audio_qc.reports as reports
    report = reports.build_report(tmp_path, [], [], config, {}, 0, programme_settings=default_group_settings())
    def fail(*_):
        raise OSError("disk full")
    monkeypatch.setattr(reports, "write_group_csv", fail)
    with pytest.raises(OSError, match="disk full"):
        reports.write_reports(report, tmp_path)
    assert not (tmp_path/"QC_COMPLETE.json").exists()


@pytest.mark.parametrize("invalid", ["rate", "mixed_bwf"])
def test_unresolved_alignment_never_fabricates_group_positions(tmp_path, invalid):
    files = [audio(tmp_path, ch) for ch in ("L", "R")]
    if invalid == "rate":
        files[1].sample_rate = 44100
    else:
        files[1].bwf = {}
    group, = build(files)
    assert group["coverage"] is None
    assert group["group_origin"] is None
    assert all(m["start_sample"] is None and m["end_sample_exclusive"] is None for m in group["members"])


@pytest.mark.parametrize('code,status', [('signal_loss_records', Status.WARNING),
                                        ('signal_loss_coverage', Status.INCOMPLETE)])
def test_signal_loss_member_limit_or_failure_prevents_complete_group_coverage(tmp_path, code, status):
    files = [audio(tmp_path, ch) for ch in ('L', 'R')]
    files[0].add(code, status, 'Signal-loss evidence incomplete')
    group, = build(files)
    assert group['validation_status'] == 'VALID'
    assert group['defect_coverage'] == 'INCOMPLETE'
    assert code in str(group['coverage_limitations'])
