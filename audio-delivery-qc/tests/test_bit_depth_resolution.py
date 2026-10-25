"""Header fallback, conflicting provenance and required-depth acceptance."""
import hashlib
import json
import struct
from copy import deepcopy

import pytest

from audio_qc.bwf import inspect_bwf
from audio_qc.metadata import parse_probe
from audio_qc.models import AudioFile
from audio_qc.rules import assess_file
from audio_qc.synthetic import chunk, sine, write_wav


def header_file(tmp_path, *, bits=24, code=1, valid=None, subtype=1,
                align=None, extension_size=22, truncate=0, duplicate=False):
    align = bits // 8 if align is None else align
    fmt = struct.pack('<HHIIHH', code, 1, 48000, 48000*align, align, bits)
    if code == 65534:
        fmt += struct.pack('<HHI', extension_size, valid, 0)
        fmt += struct.pack('<IHH8s', subtype, 0, 0x10, b'\x80\0\0\xaa\0\x38\x9b\x71')
    if truncate:
        fmt = fmt[:-truncate]
    chunks = chunk(b'fmt ', fmt) * (2 if duplicate else 1) + chunk(b'data', b'\0' * (align*16))
    path = tmp_path/'header.wav'
    path.write_bytes(b'RIFF' + struct.pack('<I', 4+len(chunks)) + b'WAVE' + chunks)
    return path


def probe(audio, *, raw=None, stored=None, channels=1, rate=48000, codec='pcm_s24le'):
    parse_probe({'streams': [{'codec_type': 'audio', 'sample_rate': str(rate),
        'channels': channels, 'codec_name': codec, 'sample_fmt': 's32',
        'bits_per_raw_sample': raw, 'bits_per_sample': stored}]}, audio)


def inspected(path):
    audio = AudioFile(str(path), path.name)
    audio.bwf = inspect_bwf(path)
    return audio


@pytest.mark.parametrize('bits,code,valid,subtype,expected', [
    (16,1,None,1,16), (24,1,None,1,24), (32,1,None,1,32),
    (32,3,None,3,32), (64,3,None,3,64),
    (32,65534,24,1,24), (24,65534,20,1,20), (32,65534,32,3,32),
])
def test_missing_probe_depth_uses_validated_header(tmp_path, bits, code, valid, subtype, expected):
    path = header_file(tmp_path, bits=bits, code=code, valid=valid, subtype=subtype)
    before = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    audio = inspected(path)
    probe(audio, codec='pcm_f64le' if bits == 64 else 'pcm_f32le' if subtype == 3 else 'pcm_s32le')
    assert audio.bit_depth == expected
    assert audio.metadata['bit_depth_provenance']['source'] == 'WAVE_FMT'
    assert (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize('options', [
    dict(bits=32,code=65534,valid=0), dict(bits=32,code=65534,valid=33),
    dict(bits=32,code=65534,valid=24,subtype=3),
    dict(bits=32,code=65534,valid=24,subtype=99),
    dict(bits=32,code=65534,valid=24,truncate=4),
    dict(bits=32,code=65534,valid=24,extension_size=21),
    dict(bits=32,code=65534,valid=24,extension_size=40),
    dict(bits=24,align=4), dict(bits=24,duplicate=True), dict(bits=4,code=2,align=1),
])
def test_unusable_header_never_supplies_guessed_depth(tmp_path, options):
    audio = inspected(header_file(tmp_path, **options))
    probe(audio)
    assert audio.bit_depth is None


def test_extensible_container_width_is_not_a_depth_conflict(tmp_path):
    audio = inspected(header_file(tmp_path, bits=32, code=65534, valid=24))
    probe(audio, stored=32)
    assert audio.bit_depth == 24


@pytest.mark.parametrize('valid', [0, 33])
def test_invalid_extensible_header_cannot_be_certified_by_probe(tmp_path, valid):
    audio = inspected(header_file(tmp_path, bits=32, code=65534, valid=valid))
    probe(audio, raw=24, stored=32)
    assert audio.bit_depth is None
    assert audio.metadata['bit_depth_provenance']['reason']


@pytest.mark.parametrize('values', [dict(raw=16), dict(channels=2), dict(rate=44100), dict(codec='pcm_f32le')])
def test_contradictory_sources_are_unresolved(tmp_path, config, values):
    audio = inspected(header_file(tmp_path))
    probe(audio, **values)
    assert audio.bit_depth is None
    assert audio.metadata['bit_depth_provenance']['reason']
    config['bit_depth'].update(required=24, preferred=None)
    result = assess_file(audio, config)
    assert result.status == 'INCOMPLETE'
    assert result.execution_status == 'FAILED'


def test_no_wave_header_retains_probe_and_never_uses_sample_fmt():
    audio = AudioFile('/not-read.flac', 'not-read.flac')
    probe(audio, raw=24, stored=32, codec='flac')
    assert audio.bit_depth == 24
    probe(audio, codec='flac')
    assert audio.bit_depth is None


@pytest.mark.parametrize('container', ['RIFF', 'RF64', 'BW64'])
def test_bwf_timing_and_probe_are_preserved(tmp_path, container):
    path = write_wav(tmp_path/'bwf.wav', sine(.01), bext=True, rf64=container != 'RIFF')
    if container == 'BW64':
        # Construct the synthetic fixture before passing it to production readers.
        path.write_bytes(b'BW64' + path.read_bytes()[4:])
    audio = inspected(path)
    before = deepcopy(audio.bwf)
    probe(audio, raw=24)
    assert audio.bit_depth == 24
    assert audio.bwf == before
    assert audio.bwf['container'] == container
    assert audio.bwf['time_reference'] == 2**32+48000
    probe(audio)
    assert audio.bit_depth == 24
    assert audio.bwf == before


def test_non_pcm_wave_keeps_explicit_probe_depth(tmp_path):
    audio = inspected(header_file(tmp_path, bits=4, code=2, align=1))
    probe(audio, raw=4, codec='adpcm_ms')
    assert audio.bit_depth == 4


def test_required_unknown_depth_is_incomplete_without_mutating_facts(config):
    audio = AudioFile('/not-read.flac', 'not-read.flac', sample_rate=48000, channels=1)
    probe(audio, codec='flac')
    before = deepcopy(audio)
    config['bit_depth'].update(required=24, preferred=None)
    result = assess_file(audio, config)
    assert result.status == 'INCOMPLETE'
    assert audio == before


@pytest.mark.integration
@pytest.mark.parametrize('mode,expected_depth,exit_code,status', [
    ('missing',24,0,'PASS'), ('conflict',None,2,'INCOMPLETE'),
])
def test_cli_reports_resolution_and_preserves_source(tmp_path, monkeypatch, mode, expected_depth, exit_code, status):
    from audio_qc import metadata
    from audio_qc.cli import main
    source = write_wav(tmp_path/'source.wav', sine(.5), bext=True)
    before = (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size, source.stat().st_mtime_ns)
    original = metadata.parse_probe
    def adjusted(data, audio):
        # Controlled ffprobe boundary: retain real metadata/decode/report pipeline.
        for stream in data['streams']:
            stream.pop('bits_per_sample', None)
            stream['bits_per_raw_sample'] = '16' if mode == 'conflict' else '0'
        return original(data, audio)
    monkeypatch.setattr(metadata, 'parse_probe', adjusted)
    policy = tmp_path/'policy.yaml'
    policy.write_text('preset: CUSTOM\nbit_depth:\n  required: 24\n')
    output = tmp_path/'report'
    assert main(['inspect',str(source),'--config',str(policy),'--output',str(output)]) == exit_code
    report = json.loads((output/'QC_REPORT.json').read_text())
    assert report['status'] == status
    assert report['execution_status'] == ('PARTIAL' if status == 'INCOMPLETE' else 'COMPLETED')
    assert report['files'][0]['bit_depth'] == expected_depth
    assert report['files'][0]['measurement_outcomes']['samples']['state'] == 'SUCCESS'
    assert status in (output/'QC_REPORT.html').read_text()
    assert json.loads((output/'QC_COMPLETE.json').read_text())['audio_compliance'] == status
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size, source.stat().st_mtime_ns) == before
