"""Real Qt subprocesses, controlled by barriers rather than timing assumptions."""
import json
import os
from pathlib import Path
import time

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtTest import QTest


def wait_until(qapp, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(5)
    assert predicate(), 'Qt operation did not reach the expected state'


@pytest.fixture
def helper(tmp_path, monkeypatch):
    control = tmp_path/'control'
    control.mkdir()
    script = tmp_path/'preview_fixture.py'
    script.write_text('''import json, os, pathlib, signal, sys, time
control = pathlib.Path(sys.argv[1])
job = json.load(sys.stdin)
name = pathlib.Path(job['source']).name
if name.startswith('stubborn'):
    signal.signal(signal.SIGTERM, lambda *_: (control/(name+'.term')).touch())
(control/(name+'.ready')).write_text(str(os.getpid()))
if name.startswith(('hold', 'stubborn')):
    while not (control/(name+'.release')).exists():
        time.sleep(.005)
if name == 'invalid':
    print('{'); sys.exit(0)
if name == 'stdout-flood':
    sys.stdout.write('x'*1048576); sys.stdout.flush(); sys.exit(0)
if name == 'stderr-flood':
    sys.stderr.write('x'*1048576); sys.stderr.flush(); sys.exit(0)
if name == 'crash':
    print('Injected auxiliary failure', file=sys.stderr); sys.exit(3)
print(json.dumps(dict(request_id=job['request_id'] + (1 if name == 'wrong-id' else 0),
    status='SUCCESS', text=name+' '+job['settings']['naming']['layout'],
    group_count=1, notice_count=0, truncated=False)))
''')
    start = QProcess.start
    def replacement(process, *args):
        if len(args) > 1 and list(args[1]) == ['-m', 'audio_qc.group_preview']:
            return start(process, args[0], [str(script), str(control)])
        return start(process, *args)
    monkeypatch.setattr(QProcess, 'start', replacement)
    return control


def select(window, tmp_path, name):
    source = tmp_path/name
    source.mkdir(exist_ok=True)
    window.source.setText(str(source))
    window.group_detection.setChecked(True)


def assert_reaped(control, name):
    pid = int((control/(name+'.ready')).read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_gui_responds_while_auxiliary_waits_and_snapshot_is_independent(window, qapp, helper, tmp_path):
    select(window, tmp_path, 'hold-A')
    wait_until(qapp, lambda: (helper/'hold-A.ready').exists())
    ticks = []
    QTimer.singleShot(0, lambda: ticks.append(True))
    wait_until(qapp, lambda: ticks)
    assert 'Buscando' in window.group_preview.text()
    assert window.run_button.isEnabled() and not window._running
    assert window.status.text().startswith('Ready')
    (helper/'hold-A.release').touch()
    wait_until(qapp, lambda: window._preview.is_idle)
    assert window.group_preview.text() == 'hold-A auto'
    assert_reaped(helper, 'hold-A')


def test_only_latest_request_survives_rapid_changes(window, qapp, helper, tmp_path):
    select(window, tmp_path, 'stubborn-A')
    wait_until(qapp, lambda: (helper/'stubborn-A.ready').exists())
    select(window, tmp_path, 'B')
    select(window, tmp_path, 'C')
    # A writes a well-formed success after cancellation was requested.
    (helper/'stubborn-A.release').touch()
    wait_until(qapp, lambda: (helper/'C.ready').exists() and window._preview.is_idle)
    assert window.group_preview.text() == 'C auto'
    assert not (helper/'B.ready').exists()
    assert_reaped(helper, 'stubborn-A')
    assert_reaped(helper, 'C')


def test_settings_snapshot_is_captured_when_request_is_queued(window, qapp, helper, tmp_path):
    from audio_qc.programme import default_group_settings
    window._group_settings = default_group_settings()
    window._group_settings['naming']['layout'] = 'stereo'
    select(window, tmp_path, 'hold-settings')
    window._group_settings['naming']['layout'] = '5.1'
    wait_until(qapp, lambda: (helper/'hold-settings.ready').exists())
    (helper/'hold-settings.release').touch()
    wait_until(qapp, lambda: window._preview.is_idle)
    assert window.group_preview.text() == 'hold-settings stereo'


def test_load_new_yaml_discards_previous_result(window, qapp, helper, tmp_path):
    select(window, tmp_path, 'stubborn-yaml')
    wait_until(qapp, lambda: (helper/'stubborn-yaml.ready').exists())
    settings = tmp_path/'groups.yaml'
    settings.write_text('schema_version: 1\nnaming:\n  enabled: true\n  layout: stereo\n')
    assert window.load_groups(settings)
    (helper/'stubborn-yaml.release').touch()
    wait_until(qapp, lambda: window._preview.is_idle)
    assert window.group_preview.text() == 'stubborn-yaml stereo'


def test_cancel_before_debounce_never_starts_worker(window, qapp, helper, tmp_path):
    select(window, tmp_path, 'never-start')
    window.group_detection.setChecked(False)
    assert window._preview.is_idle
    # Let the event loop run beyond the debounce deadline.
    done = []
    QTimer.singleShot(250, lambda: done.append(True))
    wait_until(qapp, lambda: done)
    assert not (helper/'never-start.ready').exists()


def test_preview_does_not_stat_source_on_gui_thread(window, qapp, helper, tmp_path, monkeypatch):
    source = tmp_path/'hold-no-stat'
    source.mkdir()
    stat = Path.stat
    def prohibited(path, *a, **kw):
        if path == source:
            pytest.fail('Source filesystem access occurred in the GUI process')
        return stat(path, *a, **kw)
    monkeypatch.setattr(Path, 'stat', prohibited)
    window.source.setText(str(source))
    window.group_detection.setChecked(True)
    wait_until(qapp, lambda: (helper/'hold-no-stat.ready').exists())
    (helper/'hold-no-stat.release').touch()
    wait_until(qapp, lambda: window._preview.is_idle)
    assert window.group_preview.text() == 'hold-no-stat auto'


def test_disable_groups_kills_uncooperative_auxiliary(window, qapp, helper, tmp_path):
    select(window, tmp_path, 'stubborn-disable')
    wait_until(qapp, lambda: (helper/'stubborn-disable.ready').exists())
    window.group_detection.setChecked(False)
    wait_until(qapp, lambda: window._preview.is_idle)
    assert window.group_preview.text() == 'Programme grouping disabled'
    assert (helper/'stubborn-disable.term').exists()
    assert_reaped(helper, 'stubborn-disable')


def test_close_waits_asynchronously_for_reaping_then_closes(window, qapp, helper, tmp_path):
    window.show()
    select(window, tmp_path, 'stubborn-close')
    wait_until(qapp, lambda: (helper/'stubborn-close.ready').exists())
    window.close()
    ticks = []
    QTimer.singleShot(0, lambda: ticks.append(True))
    wait_until(qapp, lambda: ticks)
    wait_until(qapp, lambda: not window.isVisible() and window._preview.is_idle)
    assert_reaped(helper, 'stubborn-close')


@pytest.mark.parametrize('name', ['invalid', 'wrong-id', 'stdout-flood', 'stderr-flood', 'crash'])
def test_auxiliary_failure_is_visible_and_next_request_recovers(window, qapp, helper, tmp_path, name):
    select(window, tmp_path, name)
    wait_until(qapp, lambda: (helper/(name+'.ready')).exists() and window._preview.is_idle)
    assert 'no disponible' in window.group_preview.text()
    assert len(window.group_preview.text()) < 8192
    assert window.run_button.isEnabled() and not window._running
    assert_reaped(helper, name)
    select(window, tmp_path, 'recovered')
    wait_until(qapp, lambda: (helper/'recovered.ready').exists() and window._preview.is_idle)
    assert window.group_preview.text() == 'recovered auto'


def test_failed_start_does_not_leave_gui_busy(window, qapp, tmp_path, monkeypatch):
    start = QProcess.start
    def unavailable(process, *args):
        if len(args) > 1 and list(args[1]) == ['-m', 'audio_qc.group_preview']:
            return start(process, str(tmp_path/'nonexistent-python'), [])
        return start(process, *args)
    monkeypatch.setattr(QProcess, 'start', unavailable)
    select(window, tmp_path, 'source')
    wait_until(qapp, lambda: 'no disponible' in window.group_preview.text())
    assert window._preview.is_idle and window.run_button.isEnabled()


def test_large_astral_names_are_abbreviated_by_real_worker_not_rejected(window, qapp):
    from audio_qc.programme import default_group_settings
    settings = default_group_settings()
    settings['programme_groups'] = [dict(id=str(i), name='\U0001f600'*1000, layout='stereo',
        alignment={'mode': 'auto'}, members=[{'channel': 'L', 'file': '/missing_L.wav'}]) for i in range(100)]
    window._group_settings = settings
    window.group_detection.setChecked(True)
    wait_until(qapp, lambda: window._preview.is_idle)
    text = window.group_preview.text()
    assert 'abreviada' in text and '100 grupos' in text
    assert 'no disponible' not in text
    assert len(window._group_settings['programme_groups']) == 100


@pytest.mark.integration
def test_run_qc_invalidates_preview_and_preserves_final_summary(window, qapp, helper, tmp_path):
    from audio_qc.synthetic import sine, write_wav
    from audio_qc.hashing import sha256_file
    source = tmp_path/'stubborn-QC'
    source.mkdir()
    paths = [write_wav(source/f'Mix_{ch}.wav', sine(3), bext=True) for ch in ('L', 'R')]
    before = [(sha256_file(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths]
    select(window, tmp_path, 'stubborn-QC')
    wait_until(qapp, lambda: (helper/'stubborn-QC.ready').exists())
    # Keep the old response pending until after the real QC has completed.
    # Normal kill escalation is independently tested above.
    window._preview._kill_timer.setInterval(30000)
    try:
        window.run_qc()
        assert window._running
        wait_until(qapp, lambda: not window._running, timeout=25)
        assert 'Mix: VALID' in window.group_preview.text()
        summary = window.group_preview.text()
    finally:
        (helper/'stubborn-QC.release').touch()
    wait_until(qapp, lambda: window._preview.is_idle)
    assert window.group_preview.text() == summary
    assert 'Mix: VALID' in window.group_preview.text()
    assert 'stubborn-QC auto' not in window.group_preview.text()
    assert window.open_button.isEnabled()
    report = json.loads(window.report_path.with_suffix('.json').read_text())
    assert report['configuration'] == window._scan_config
    assert [(sha256_file(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths] == before
    assert_reaped(helper, 'stubborn-QC')
