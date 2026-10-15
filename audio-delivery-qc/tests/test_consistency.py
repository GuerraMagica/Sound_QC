from audio_qc.consistency import group_checks
from audio_qc.models import AudioFile, Status


def item(name, duration=60, rate=48000, bits=24, channels=1):
    return AudioFile("/delivery/"+name, name, decoded_duration_seconds=duration,
                     sample_rate=rate, bit_depth=bits, codec="pcm_s24le", channels=channels)


def test_mixed_formats_durations_and_counts(config):
    files = [item("a.wav"), item("b.wav"), item("c.wav", 12, 44100, 16, 6)]
    checks = group_checks(files, config)
    codes = {c.code for c in checks}
    assert {"mixed_sample_rate", "mixed_bit_depth", "duration_spread", "duration_outlier", "mixed_channels"} <= codes
    assert all(c.status != Status.FAIL for c in checks)
    assert next(c for c in checks if c.code == "mixed_channels").status == Status.INFO


def test_duration_tolerance(config):
    assert not any(c.code == "duration_spread" for c in group_checks([item("a.wav"), item("b.wav", 60.020)], config))
    assert any(c.code == "duration_spread" for c in group_checks([item("a.wav"), item("b.wav", 60.021)], config))


def test_missing_stems_requires_evidence(config):
    assert not any(c.code == "potential_missing_stems" for c in group_checks([item("DIA.wav")], config))
    found = group_checks([item("scene_DIA_v1.wav"), item("scene_FX_v1.wav")], config)
    assert any(c.code == "potential_missing_stems" and "MX" in c.message for c in found)
    unrelated = group_checks([item("scene01_DIA.wav"), item("scene02_FX.wav")], config)
    assert not any(c.code == "potential_missing_stems" for c in unrelated)


def test_duplicates(config):
    a, b = item("same.wav"), item("same.wav")
    a.sha256 = b.sha256 = "abc"
    a.audio_sha256 = b.audio_sha256 = "def"
    checks = group_checks([a, b], config)
    assert {c.code for c in checks} == {"duplicate_filename", "duplicate_file", "duplicate_audio"}
