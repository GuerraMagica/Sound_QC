"""Preview uses canonical grouping, without decoding or writing source media."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from audio_qc.programme import default_group_settings, discover_programmes
from audio_qc.scanner import discover


def request(source, settings=None):
    return dict(request_id=7, source=str(source), settings=settings or default_group_settings())


def fingerprint(paths):
    return [(p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]


@pytest.mark.parametrize('roles', [('L', 'R'), ('L', 'R', 'C', 'LFE', 'Ls', 'Rs')])
def test_preview_matches_canonical_mapping_and_keeps_sources_untouched(tmp_path, roles):
    from audio_qc.group_preview import collect_preview
    paths = [tmp_path/f'Mezcla 日本語 & <test>_{role}.wav' for role in roles]
    for path in paths:
        path.write_bytes(b'filename fixture, deliberately not decodable audio')
    before = fingerprint(paths)
    config = default_group_settings()
    expected = discover_programmes(discover(tmp_path)[0], config)
    result = collect_preview(request(tmp_path, config))
    assert result['status'] == 'SUCCESS' and result['request_id'] == 7
    assert result['group_count'] == len(expected) == 1
    group, = expected
    assert f'{group.name} ({group.layout}, {group.alignment})' in result['text']
    for member in group.members:
        assert f'{member.channel} ← {Path(member.file).name}' in result['text']
    assert 'Media validation will run with QC.' in result['text']
    assert not result['truncated'] and result['notice_count'] == 0
    assert fingerprint(paths) == before
    assert sorted(tmp_path.iterdir()) == sorted(paths)


def test_explicit_groups_without_source_are_still_previewed():
    from audio_qc.group_preview import collect_preview
    settings = default_group_settings()
    settings['naming']['enabled'] = False
    settings['programme_groups'] = [dict(id='explicit', name='Dialogue', layout='stereo',
        alignment={'mode': 'common_file_start'}, members=[
            {'channel': 'L', 'file': '/missing/voice left.wav'},
            {'channel': 'R', 'file': '/missing/voice right.wav'}])]
    result = collect_preview(request('', settings))
    assert result['group_count'] == 1 and result['status'] == 'SUCCESS'
    assert 'L ← voice left.wav' in result['text']
    assert 'common_file_start' in result['text']
    assert 'Media validation will run with QC.' in result['text']


def test_empty_source_and_missing_source_are_distinct(tmp_path):
    from audio_qc.group_preview import collect_preview
    empty = collect_preview(request(''))
    missing = collect_preview(request(tmp_path/'missing'))
    assert empty['status'] == 'SUCCESS' and empty['group_count'] == 0
    assert 'No naming groups found' in empty['text']
    assert missing['status'] == 'ERROR' and missing['group_count'] is None
    assert 'No naming groups found' not in missing['text']


def test_symlinks_and_unreadable_subtree_are_not_silent_empty_results(tmp_path, monkeypatch):
    from audio_qc.group_preview import collect_preview
    (tmp_path/'source_L.wav').write_bytes(b'synthetic placeholder')
    (tmp_path/'skip_R.wav').symlink_to(tmp_path/'source_L.wav')
    denied = tmp_path/'denied'
    denied.mkdir()
    scandir = os.scandir
    def fail(path):
        if Path(path) == denied:
            raise PermissionError('Injected permission denied')
        return scandir(path)
    monkeypatch.setattr(os, 'scandir', fail)
    result = collect_preview(request(tmp_path))
    assert result['status'] == 'PARTIAL' and result['notice_count'] == 2
    assert 'permission denied' in result['text'] and 'symlink' in result['text']
    assert result['group_count'] == 1
    assert 'skip_R.wav' not in result['text'].split('Notices:')[0]


def test_initial_stat_permission_failure_is_reported(tmp_path, monkeypatch):
    from audio_qc.group_preview import collect_preview
    stat = Path.stat
    def denied(path, *a, **kw):
        if path == tmp_path:
            raise PermissionError('Injected stat denied')
        return stat(path, *a, **kw)
    monkeypatch.setattr(Path, 'stat', denied)
    result = collect_preview(request(tmp_path))
    assert result['status'] == 'ERROR' and 'stat denied' in result['text']


def test_failed_directory_walk_is_not_presented_as_no_groups(tmp_path, monkeypatch):
    from audio_qc.group_preview import collect_preview
    def denied(path):
        raise PermissionError('Injected directory denied')
    monkeypatch.setattr(os, 'scandir', denied)
    result = collect_preview(request(tmp_path))
    assert result['status'] == 'PARTIAL' and result['notice_count'] == 1
    assert 'directory denied' in result['text']
    assert 'No naming groups found' not in result['text']


@pytest.mark.parametrize('name_fragment', ['日本語', '\U0001f600', '\x01\\"'],
                         ids=['bmp', 'astral', 'json-escapes'])
def test_preview_abbreviation_does_not_truncate_group_count(tmp_path, name_fragment):
    from audio_qc.group_preview import collect_preview, encode_response
    settings = default_group_settings()
    settings['programme_groups'] = [dict(id=str(i), name=name_fragment*1000, layout='stereo',
        alignment={'mode': 'auto'}, members=[{'channel': 'L', 'file': '/a_L.wav'}]) for i in range(200)]
    result = collect_preview(request('', settings))
    assert result['group_count'] == 200 and result['truncated']
    assert 'abreviada' in result['text']
    assert len(encode_response(result)) <= 256*1024
    assert len(settings['programme_groups']) == 200


@pytest.mark.parametrize('payload', [b'{', b'[]', b'{"request_id": true}', b'x'*(4*1024*1024+1)],
                         ids=['json', 'array', 'bool-id', 'oversize'])
def test_worker_malformed_or_excessive_input_is_bounded_error(payload):
    process = subprocess.run([sys.executable, '-m', 'audio_qc.group_preview'],
                             input=payload, capture_output=True, timeout=10)
    assert process.returncode == 2
    result = json.loads(process.stdout)
    assert result['status'] == 'ERROR'
    assert len(process.stdout) <= 256*1024
    assert b'Traceback' not in process.stderr


def test_real_worker_has_same_result_as_in_process_collector(tmp_path):
    from audio_qc.group_preview import collect_preview
    (tmp_path/'mix_L.wav').touch()
    (tmp_path/'mix_R.wav').touch()
    job = request(tmp_path)
    process = subprocess.run([sys.executable, '-m', 'audio_qc.group_preview'],
                             input=json.dumps(job).encode(), capture_output=True, timeout=10)
    assert process.returncode == 0 and not process.stderr
    assert json.loads(process.stdout) == collect_preview(job)
