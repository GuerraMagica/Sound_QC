import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from audio_qc.cli import create_output, main
from audio_qc.models import AudioFile, Check, DEFECT_NOTICE, Status
from audio_qc.process import ToolError, check_tools, stream_process
from audio_qc.reports import build_report, write_reports
from audio_qc.scanner import inspect_file
from audio_qc.snippets import export_snippets
from audio_qc.synthetic import defect_signals, sine, write_wav


def test_three_reports_escape_and_unavailable(tmp_path, config):
    a = AudioFile('/folder/=<script>alert("x")</script>.wav', '=<script>alert("x")</script>.wav')
    a.add("unavailable", Status.WARNING, '<script>unsafe</script> & "value"')
    report = build_report(tmp_path, [a], [], config, {}, 0.1)
    write_reports(report, tmp_path)
    restored = json.loads((tmp_path/"QC_REPORT.json").read_text())
    assert restored["files"][0]["duration_seconds"] is None
    assert restored["files"][0]["path"] == a.path
    with (tmp_path/"QC_REPORT.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["File"].startswith("'=")
    assert rows[0]["True Peak dBTP"] == ""
    html = (tmp_path/"QC_REPORT.html").read_text()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert DEFECT_NOTICE in html
    assert "https://" not in html
    with pytest.raises(FileExistsError):
        write_reports(report, tmp_path)


def test_no_overwrite_or_output_inside_source(tmp_path):
    source = tmp_path/"source"
    source.mkdir()
    for target in [source, source/"reports", tmp_path]:
        with pytest.raises(ValueError):
            create_output(source, target)


def test_missing_dependencies_message(monkeypatch):
    monkeypatch.setattr("audio_qc.process.shutil.which", lambda _: None)
    with pytest.raises(ToolError, match="brew install ffmpeg"):
        check_tools()


def test_process_failure_and_timeout():
    with pytest.raises(ToolError, match="specific failure"):
        with stream_process([sys.executable, "-c", "import sys; print('specific failure',file=sys.stderr); sys.exit(1)"]) as output:
            output.read()
    with pytest.raises(ToolError, match="timeout"):
        with stream_process([sys.executable, "-c", "import time; time.sleep(2)"], timeout=.05) as output:
            output.read()


def test_configuration_invalid_before_scanning(tmp_path, monkeypatch, capsys):
    path = tmp_path/"invalid.yaml"
    path.write_text("invalid: 123")
    monkeypatch.setattr("audio_qc.cli.check_tools", lambda: pytest.fail("Must validate first"))
    assert main([str(tmp_path), "--config", str(path)]) == 2
    assert "Unknown setting" in capsys.readouterr().err


@pytest.mark.integration
def test_corrupt_does_not_abort_and_source_is_unchanged(tmp_path):
    source = tmp_path/"audio"
    source.mkdir()
    good = write_wav(source/"nested"/"Diálogo 日本語.wav", sine(), bext=True)
    bad = source/"broken.wav"
    bad.write_bytes(b"corrupt")
    before = {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in (good, bad)}
    out = tmp_path/"result"
    assert main(["inspect", str(source), "--hash", "--output", str(out), "--quiet"]) == 2
    report = json.loads((out/"QC_REPORT.json").read_text())
    assert report["summary"]["total_files"] == 2
    assert report["summary"]["INCOMPLETE"] == 1
    assert report["execution_status"] == "PARTIAL"
    assert report["summary"]["PASS"] == 1
    for path, state in before.items():
        assert (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) == state
    assert all((out/f"QC_REPORT.{ext}").is_file() for ext in ("html", "csv", "json"))


@pytest.mark.integration
def test_empty_folder(tmp_path):
    source = tmp_path/"empty"
    source.mkdir()
    output = tmp_path/"reports"
    assert main([str(source), "--output", str(output), "--quiet"]) == 0
    report = json.loads((output/"QC_REPORT.json").read_text())
    assert report["summary"]["total_files"] == 0
    assert report["status"] == "WARNING"


@pytest.mark.integration
def test_real_module_and_executable(wav, tmp_path):
    module = subprocess.run([sys.executable, "-m", "audio_qc", str(wav), "--quiet", "--output", str(tmp_path/"module")], capture_output=True, text=True)
    assert module.returncode == 0, module.stderr
    executable = Path(sys.executable).parent/"audio-qc"
    result = subprocess.run([str(executable), "--version"], capture_output=True, text=True)
    assert result.returncode == 0 and "1.0.0" in result.stdout


@pytest.mark.integration
def test_finder_launcher_terminal_flow(wav):
    import shlex
    launcher = Path(__file__).parents[1]/"scripts"/"launcher.py"
    result = subprocess.run([sys.executable, str(launcher)],
                            input=shlex.quote(str(wav))+"\n1\nn\n", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "HTML report:" in result.stdout
    reports = list(wav.parent.glob("*_QC_*/QC_REPORT.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text())
    assert report["summary"]["PASS"] == 1


@pytest.mark.integration
def test_snippet_preserves_signal_and_relative_link(tmp_path, config):
    config["defects"]["enabled"] = True
    samples = sine(4, amplitude=.04, frequency=220)
    position = 84000
    samples[position] += .8
    source = write_wav(tmp_path/"click.wav", samples)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    a = inspect_file(source, config)
    assert len(a.defects) == 1
    output = tmp_path/"report"
    output.mkdir()
    export_snippets(a, output, config, 1)
    snippet = output/a.defects[0].snippet
    assert snippet.exists()
    decoded = subprocess.run(["ffmpeg", "-v", "error", "-i", str(snippet), "-f", "f64le", "-c:a", "pcm_f64le", "-"], capture_output=True, check=True).stdout
    signal = np.frombuffer(decoded, dtype="<f8")
    first = position-48000
    expected = samples[first:position+48001, 0]
    assert len(signal) == len(expected)
    assert np.max(np.abs(signal-expected)) < 1e-7
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    report = build_report(source, [a], [], config, {}, 0)
    write_reports(report, output)
    assert a.defects[0].snippet in (output/"QC_REPORT.html").read_text()
