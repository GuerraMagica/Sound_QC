import pytest
from audio_qc.config import ConfigError, load_config


def test_presets():
    film = load_config()
    assert film["loudness"]["target_lufs"] is None
    assert film["sample_rate"]["required"] == 48000
    broadcast = load_config(preset="BROADCAST_EBU_R128")
    assert broadcast["loudness"]["target_lufs"] == -23
    assert broadcast["true_peak"]["maximum"] == -1
    assert load_config(preset="CUSTOM")["sample_rate"]["required"] is None


def test_partial_override_and_cli_preset(tmp_path):
    path = tmp_path/"c.yaml"
    path.write_text("loudness:\n  tolerance: 1.0\n")
    c = load_config(path, "BROADCAST_EBU_R128")
    assert c["loudness"]["target_lufs"] == -23
    assert c["loudness"]["tolerance"] == 1


@pytest.mark.parametrize("yaml", [
    "foo: 1", "sample_rate: 48000", "sample_rate:\n  required: true",
    "duration_tolerance_ms: -1", "loudness:\n  enabled: maybe", "preset: FILM48K",
    "loudness:\n  target_lufs: -23", "channels:\n  allowed: [0, 2]",
    "defects:\n  clicks:\n    sensitivity: arbitrary", "defects:\n  dropouts:\n    min_duration_ms: 600",
    "true_peak:\n  maximum: .nan", "preset: FILM_48K\npreset: CUSTOM", "- invalid",
    "defects:\n  max_candidates: 1.5", "bwf:\n  required: 1", "expected_stems: FX",
])
def test_invalid_yaml(tmp_path, yaml):
    path = tmp_path/"invalid.yaml"
    path.write_text(yaml)
    with pytest.raises(ConfigError):
        load_config(path)


def test_all_shipped_configs():
    from pathlib import Path
    for path in (Path(__file__).parents[1]/"config").glob("*.yaml"):
        load_config(path)
