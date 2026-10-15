"""Small deterministic, copyright-free signals used by tests and the demo."""
from pathlib import Path
import struct

import numpy as np


def sine(seconds=4, rate=48000, channels=1, amplitude=0.1, frequency=1000):
    t = np.arange(round(seconds*rate))/rate
    return np.repeat((amplitude*np.sin(2*np.pi*frequency*t))[:, None], channels, axis=1)


def chunk(name, payload):
    return name + struct.pack("<I", len(payload)) + payload + (b"\0" if len(payload) % 2 else b"")


def write_wav(path: Path, samples, rate=48000, bits=24, bext=False, mask=None, rf64=False, float_pcm=False,
              time_reference=2**32+48000):
    """Exclusively create a NEW small test WAV; never overwrite an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if samples.ndim == 1:
        samples = samples[:, None]
    channels = samples.shape[1]
    if float_pcm:
        bits = 32
        raw = samples.astype("<f4").tobytes()
        code = 3
    else:
        code = 1
        integers = np.clip(np.rint(samples*(2**(bits-1))), -2**(bits-1), 2**(bits-1)-1).astype("<i4")
        if bits == 24:
            raw = integers.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
        elif bits == 16:
            raw = integers.astype("<i2").tobytes()
        elif bits == 32:
            raw = integers.tobytes()
        else:
            raise ValueError("Test writer supports 16/24/32-bit PCM")
    align = channels * (bits//8)
    fmt = struct.pack("<HHIIHH", 65534 if mask is not None else code, channels, rate, rate*align, align, bits)
    if mask is not None:
        fmt += struct.pack("<HHI", 22, bits, mask) + struct.pack("<IHH8s", code, 0, 0x10, b"\x80\x00\x00\xaa\x00\x38\x9b\x71")
    chunks = chunk(b"fmt ", fmt)
    if bext:
        b = bytearray(602)
        b[:21] = b"Synthetic QC fixture\0"
        b[256:265] = b"Audio QC\0"
        b[288:296] = b"TEST-01\0"
        b[320:330] = b"2026-10-07"
        b[330:338] = b"12:34:56"
        struct.pack_into("<QH", b, 338, time_reference, 1)
        chunks += chunk(b"bext", bytes(b) + b"A=PCM,F=48000,W=24,M=mono\r\n")
    if rf64:
        data = b"data" + struct.pack("<I", 0xFFFFFFFF) + raw + (b"\0" if len(raw)%2 else b"")
        full_size = 12 + 36 + len(chunks) + len(data)
        ds64 = chunk(b"ds64", struct.pack("<QQQI", full_size-8, len(raw), len(samples), 0))
        content = b"RF64" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE" + ds64 + chunks + data
    else:
        chunks += chunk(b"data", raw)
        content = b"RIFF" + struct.pack("<I", len(chunks)+4) + b"WAVE" + chunks
    with path.open("xb") as handle:
        handle.write(content)
    return path


def defect_signals(rate=48000):
    clean = sine(3, rate, amplitude=0.04, frequency=220)
    one = clean.copy()
    one[rate, 0] += 0.8
    multi = clean.copy()
    multi[rate:rate+8, 0] -= 0.7
    zero = clean.copy()
    zero[rate:rate+round(rate*0.02)] = 0
    quiet = clean.copy()
    quiet[rate:rate+round(rate*0.04)] *= 0.001
    silence = clean.copy()
    silence[rate:2*rate] = 0
    stereo = np.repeat(clean, 2, axis=1)
    stereo[rate:rate+round(rate*0.02), 0] = 0
    transient = clean.copy()
    n = round(rate*0.03)
    transient[rate:rate+n, 0] += 0.7*np.hanning(n)*np.sin(2*np.pi*3000*np.arange(n)/rate)
    return {"clean_sine": clean, "one_sample_click": one, "multi_sample_click": multi,
            "zero_dropout": zero, "attenuation_dropout": quiet, "intentional_silence": silence,
            "channel_dropout": stereo, "legitimate_transient": transient}


def generate_demo(folder: Path):
    folder.mkdir(parents=True, exist_ok=False)
    write_wav(folder/"SCENE01_DIA.wav", sine(), bext=True)
    write_wav(folder/"SCENE01_FX.wav", sine(frequency=300), bext=True)
    write_wav(folder/"stereo_48k.wav", sine(channels=2))
    write_wav(folder/"wrong_rate_44k.wav", sine(rate=44100), rate=44100)
    write_wav(folder/"short_duration.wav", sine(1))
    write_wav(folder/"clipped.wav", sine(amplitude=1.3))
    write_wav(folder/"quiet.wav", sine(amplitude=0.00001))
    write_wav(folder/"nested"/"Diálogo 日本語.wav", sine(frequency=500))
    write_wav(folder/"surround_51.wav", sine(channels=6), mask=0x3f)
    write_wav(folder/"surround_71.wav", sine(channels=8), mask=0x63f)
    write_wav(folder/"RF64_BWF.wav", sine(), bext=True, rf64=True)
    for name, samples in defect_signals().items():
        write_wav(folder/"defects"/f"{name}.wav", samples)
    with (folder/"corrupt.wav").open("xb") as handle:
        handle.write(b"RIFF\xff\xff\xff\xffWAVEinvalid")
    return folder
