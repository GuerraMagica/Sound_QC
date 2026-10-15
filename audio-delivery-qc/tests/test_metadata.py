from audio_qc.bwf import inspect_bwf
from audio_qc.metadata import parse_probe, inspect_metadata
from audio_qc.models import AudioFile
from audio_qc.process import ToolError
from audio_qc.synthetic import sine, write_wav
import pytest


def test_probe_parser_fallback():
    a = AudioFile("test", "test")
    parse_probe({"streams": [{"codec_type": "audio", "sample_rate": "48000", "channels": 2,
                              "bits_per_raw_sample": "24", "bits_per_sample": 32,
                              "duration_ts": 48000, "time_base": "1/48000", "codec_name": "pcm_s24le", "sample_fmt": "s32"}]}, a)
    assert (a.duration_seconds, a.sample_rate, a.channels, a.bit_depth) == (1, 48000, 2, 24)
    assert a.pcm_format == "s32"  # container format is not the true bit depth


def test_no_audio_stream():
    with pytest.raises(ToolError):
        parse_probe({"streams": []}, AudioFile("x", "x"))


def test_bext_64bit(wav):
    b = inspect_bwf(wav)
    assert b["present"] is True
    assert b["time_reference"] == 2**32+48000
    assert b["originator"] == "Audio QC"
    assert b["origination_date"] == "2026-10-07"
    assert b["origination_time"] == "12:34:56"
    assert "A=PCM" in b["coding_history"]
    assert not b["errors"]
    assert b["declared_sample_frames"] == 192000


def test_rf64(tmp_path):
    path = write_wav(tmp_path/"rf64.wav", sine(0.1), bext=True, rf64=True)
    b = inspect_bwf(path)
    assert b["container"] == "RF64"
    assert b["data_bytes"] == 4800*3
    assert b["time_reference"] == 2**32+48000
    assert not b["errors"]


def test_truncated_chunk(wav):
    original = wav.read_bytes()
    # Test fixture mutation only, before handing the file to the inspector.
    wav.write_bytes(original[:-10])
    assert inspect_bwf(wav)["errors"]


@pytest.mark.integration
def test_real_ffprobe(wav):
    a = AudioFile(str(wav), wav.name)
    inspect_metadata(wav, a)
    assert (a.sample_rate, a.bit_depth, a.channels, a.duration_seconds) == (48000, 24, 1, 4.0)
