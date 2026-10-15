import pytest
from audio_qc.loudness import LoudnessParser
from audio_qc.scanner import inspect_file
from audio_qc.synthetic import sine, write_wav


def test_parser_metadata_and_summary():
    p = LoudnessParser()
    for line in ["[ametadata] frame:29 pts:139200 pts_time:2.9", "lavfi.r128.M=-22.12", "lavfi.r128.S=-23.001",
                 "lavfi.r128.I=-23.123", "lavfi.r128.LRA=4.567", "Summary:", "True peak:", " Peak: -1.2 dBFS"]:
        p.feed(line)
    assert p.result(5)["integrated_lufs"] == -23.123
    assert p.result(5)["lra_lu"] == 4.567
    assert p.result(5)["true_peak_dbtp"] == -1.2
    assert p.result(5)["max_short_term_lufs"] == -23.001


def test_no_gate_and_short_programme():
    p = LoudnessParser()
    for line in ["lavfi.r128.I=-70.000", "lavfi.r128.M=-120.691", "Summary:", "True peak:", "Peak: -inf dBFS"]:
        p.feed(line)
    result = p.result(0.2)
    assert all(result[k] is None for k in ("integrated_lufs", "max_momentary_lufs", "lra_lu", "true_peak_dbtp"))
    assert "loudness_unavailable" in LoudnessParser().result(5)


@pytest.mark.integration
def test_1khz_reference_loudness(wav, config):
    a = inspect_file(wav, config)
    assert a.measurements["integrated_lufs"] == pytest.approx(-23.0, abs=0.1)
    assert a.measurements["true_peak_dbtp"] == pytest.approx(-20.0, abs=0.15)
    assert a.measurements["max_momentary_lufs"] == pytest.approx(-23.0, abs=0.1)
    assert a.measurements["max_short_term_lufs"] == pytest.approx(-23.0, abs=0.1)


@pytest.mark.integration
def test_stereo_is_3db_louder(tmp_path, config):
    mono = inspect_file(write_wav(tmp_path/"mono.wav", sine()), config)
    stereo = inspect_file(write_wav(tmp_path/"stereo.wav", sine(channels=2)), config)
    assert stereo.measurements["integrated_lufs"]-mono.measurements["integrated_lufs"] == pytest.approx(3.01, abs=0.03)


@pytest.mark.integration
def test_lfe_excluded_and_71_supported(tmp_path, config):
    signal = sine(channels=6)
    signal[:, [0, 1, 2, 4, 5]] = 0
    a = inspect_file(write_wav(tmp_path/"lfe.wav", signal, mask=0x3f), config)
    assert a.channel_layout == "5.1"
    assert a.measurements["integrated_lufs"] is None
    assert a.measurements["true_peak_dbtp"] == pytest.approx(-20, abs=0.15)
    b = inspect_file(write_wav(tmp_path/"71.wav", sine(channels=8), mask=0x63f), config)
    assert b.channel_layout == "7.1"
    assert b.measurements["integrated_lufs"] is not None


@pytest.mark.integration
def test_unknown_multichannel_not_weighted(tmp_path, config):
    a = inspect_file(write_wav(tmp_path/"unknown.wav", sine(channels=9)), config)
    assert a.measurements.get("integrated_lufs") is None
    assert "layout" in a.measurements["loudness_unavailable"]


@pytest.mark.integration
def test_intersample_peak_exceeds_sample_peak(tmp_path, config):
    import numpy as np
    x = .95*np.sqrt(2)*np.sin(2*np.pi*12000*np.arange(192000)/48000+np.pi/4)
    a = inspect_file(write_wav(tmp_path/"intersample.wav", x), config)
    assert a.measurements["sample_peak_dbfs"] < 0
    assert a.measurements["true_peak_dbtp"] > 2
    assert a.measurements["true_peak_dbtp"] > a.measurements["sample_peak_dbfs"] + 2


@pytest.mark.parametrize("channels,layout,guess", [(1, None, "1"), (2, None, "2"),
                                                   (6, "5.1", "0")])
def test_known_mono_stereo_input_layout_without_filter_relabel(monkeypatch, channels, layout, guess):
    from contextlib import contextmanager
    from io import BytesIO
    from audio_qc.models import AudioFile
    from audio_qc.loudness import measure_loudness
    commands = []
    @contextmanager
    def stream(args, timeout, feed):
        commands.append(args)
        yield BytesIO()
    monkeypatch.setattr("audio_qc.loudness.stream_process", stream)
    audio = AudioFile("/fixture.wav", "fixture.wav", channels=channels, channel_layout=layout)
    assert "loudness_unavailable" in measure_loudness(audio.path, audio)
    args, = commands
    assert args[args.index("-guess_layout_max") + 1] == guess
    assert args.index("-guess_layout_max") < args.index("-i")
    assert args[args.index("-af") + 1] == "ebur128=metadata=1:peak=true:dualmono=false,ametadata=mode=print"
    assert "-ac" not in args and "-ar" not in args
