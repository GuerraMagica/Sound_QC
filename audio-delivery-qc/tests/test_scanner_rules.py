from pathlib import Path
import hashlib
import numpy as np
import pytest

from audio_qc.config import load_config
from audio_qc.models import AudioFile, Check, Status, overall_status
from audio_qc.scanner import discover, inspect_file
from audio_qc.synthetic import sine, write_wav


def fingerprint(path):
    return (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns, path.stat().st_size)


def test_status_precedence():
    assert overall_status([]) == Status.INFO
    assert overall_status([Check("a", Status.PASS, ""), Check("b", Status.INFO, "")]) == Status.PASS
    assert overall_status([Check("a", Status.PASS, ""), Check("b", Status.WARNING, "")]) == Status.WARNING
    assert overall_status([Check("a", Status.WARNING, ""), Check("b", Status.FAIL, "")]) == Status.FAIL


def test_recursive_discovery_and_empty(tmp_path):
    assert discover(tmp_path)[0] == []
    paths = [write_wav(tmp_path/"Nested"/"Diálogo 日本語.WAV", sine(.1)), write_wav(tmp_path/"mono.bwf", sine(.1))]
    (tmp_path/"ignore.txt").write_text("not audio")
    assert set(discover(tmp_path)[0]) == set(paths)
    (tmp_path/"loop").symlink_to(tmp_path, target_is_directory=True)
    (tmp_path/"link.wav").symlink_to(paths[0])
    scanned, notices = discover(tmp_path)
    assert set(scanned) == set(paths)
    assert len(notices) == 2


@pytest.mark.integration
def test_readonly_pass_bwf(wav, config):
    before = fingerprint(wav)
    wav.chmod(0o444)
    try:
        a = inspect_file(wav, config, with_hash=True)
        assert a.status == Status.PASS
        assert a.sha256 == before[0]
        assert a.audio_sha256 is not None
        assert a.decoded_duration_seconds == 4
        assert fingerprint(wav) == before
    finally:
        wav.chmod(0o644)


@pytest.mark.integration
@pytest.mark.parametrize("rate,bits,expected", [(44100, 24, Status.FAIL), (48000, 16, Status.WARNING), (48000, 24, Status.PASS)])
def test_format_rules(tmp_path, config, rate, bits, expected):
    p = write_wav(tmp_path/"input.wav", sine(1, rate=rate), rate, bits, bext=True)
    assert inspect_file(p, config).status == expected


@pytest.mark.integration
def test_clipping_and_isolated_rail(tmp_path, config):
    a = inspect_file(write_wav(tmp_path/"clip.wav", sine(amplitude=1.3)), config)
    assert any(c.code == "clipping" and c.status == Status.FAIL for c in a.checks)
    samples = sine()
    samples[8000] = 1
    b = inspect_file(write_wav(tmp_path/"rail.wav", samples), config)
    assert any(c.code == "clipping" and c.status == Status.WARNING for c in b.checks)


@pytest.mark.integration
def test_float_overload_and_nan(tmp_path, config):
    x = sine()
    x[1000] = 1.5
    a = inspect_file(write_wav(tmp_path/"over.wav", x, float_pcm=True), config)
    assert a.measurements["overload_samples"] == 1
    assert a.status == Status.FAIL
    x[1000] = np.nan
    b = inspect_file(write_wav(tmp_path/"nan.wav", x, float_pcm=True), config)
    assert b.status == Status.FAIL


@pytest.mark.integration
def test_silence_quiet_and_tiny_are_unavailable_not_failed(tmp_path, config):
    for name, x in [("silent", np.zeros((48000, 1))), ("quiet", sine(amplitude=1e-6)), ("tiny", sine(.1))]:
        a = inspect_file(write_wav(tmp_path/f"{name}.wav", x), config)
        assert a.measurements.get("integrated_lufs") is None
        assert a.status != Status.FAIL


@pytest.mark.integration
def test_broadcast_and_no_film_target(wav):
    broadcast = load_config(preset="BROADCAST_EBU_R128")
    assert inspect_file(wav, broadcast).status == Status.PASS
    broadcast["loudness"]["target_lufs"] = -30
    assert inspect_file(wav, broadcast).status == Status.FAIL
    film = load_config()
    assert inspect_file(wav, film).status == Status.PASS


@pytest.mark.integration
def test_corrupt_and_truncated(tmp_path, config):
    bad = tmp_path/"bad.wav"
    bad.write_bytes(b"broken audio")
    assert inspect_file(bad, config).status == Status.FAIL
    p = write_wav(tmp_path/"truncated.wav", sine())
    p.write_bytes(p.read_bytes()[:-6])
    assert inspect_file(p, config).status == Status.FAIL


@pytest.mark.integration
def test_hashes_separate_file_and_audio(tmp_path, config):
    x = sine()
    a = inspect_file(write_wav(tmp_path/"no_bext.wav", x), config, True)
    b = inspect_file(write_wav(tmp_path/"with_bext.wav", x, bext=True), config, True)
    assert a.sha256 != b.sha256
    assert a.audio_sha256 == b.audio_sha256
    no_hash = inspect_file(Path(a.path), config)
    assert no_hash.sha256 is None and no_hash.audio_sha256 is None


@pytest.mark.integration
def test_disable_loudness_keeps_peak_and_decode(wav, config):
    config["loudness"]["enabled"] = False
    a = inspect_file(wav, config)
    assert a.measurements["sample_peak_dbfs"] == pytest.approx(-20, abs=.01)
    assert "integrated_lufs" not in a.measurements
    assert a.status == Status.PASS
