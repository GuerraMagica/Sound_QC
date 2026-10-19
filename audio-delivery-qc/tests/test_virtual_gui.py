import sys
import time
import json
import subprocess
import pytest
from PySide6.QtCore import QProcess
from m6_fixtures import make_programme_fixture


def test_cancel_button_states_and_snapshot(window,tmp_path):
    assert not window.cancel_button.isEnabled()
    args=window.scan_arguments(tmp_path/'output')
    assert '--gui-control-stdin' in args
    window.cancel_qc()  # Idle and repeated requests are harmless.
    window.cancel_qc()
    window.scan_finished(130)
    assert 'Cancelado' in window.status.text()
    assert not window.open_button.isEnabled()
    assert window.run_button.isEnabled()


@pytest.mark.integration
def test_real_gui_cancellation(window,qapp,tmp_path):
    f=make_programme_fixture(tmp_path/'fixture',layout='stereo',seconds=40)
    window.source.setText(str(tmp_path/'fixture'/'sources'))
    window.load_groups(f['manifest'])
    window.run_qc()
    assert window.cancel_button.isEnabled()
    deadline=time.monotonic()+10
    while time.monotonic()<deadline and not window.log.toPlainText():
        qapp.processEvents(); time.sleep(.01)
    window.cancel_qc();window.cancel_qc()
    while time.monotonic()<deadline and window.process.state()!=QProcess.NotRunning:
        qapp.processEvents();time.sleep(.01)
    qapp.processEvents()
    assert window.process.state()==QProcess.NotRunning
    assert window.process.exitCode()==130
    assert not (window.report_path.parent/'QC_COMPLETE.json').exists()
    assert 'Cancelado' in window.status.text()


@pytest.mark.integration
def test_gui_programme_summary_displays_measured_levels(window,qapp,tmp_path):
    f=make_programme_fixture(tmp_path/'fixture',layout='stereo',seconds=4)
    window.source.setText(str(tmp_path/'fixture'/'sources'))
    window.load_groups(f['manifest'])
    window.run_qc()
    deadline=time.monotonic()+15
    while time.monotonic()<deadline and window.process.state()!=QProcess.NotRunning:
        qapp.processEvents();time.sleep(.01)
    qapp.processEvents()
    assert window.process.state()==QProcess.NotRunning
    assert window.open_button.isEnabled()
    report=json.loads(window.report_path.with_suffix('.json').read_text())
    metrics=report['programme_groups'][0]['programme_measurement']['measurements']
    assert 'LUFS' in window.group_preview.text()
    assert str(metrics['integrated_lufs']) in window.group_preview.text()
    assert 'dBTP' in window.group_preview.text()
    assert report['configuration']==window._scan_config


@pytest.mark.integration
def test_gui_cancels_during_virtual_ffmpeg(window,qapp,tmp_path,monkeypatch):
    import os,shutil
    real=shutil.which('ffmpeg')
    wrapper_dir=tmp_path/'bin';wrapper_dir.mkdir()
    pidfile=tmp_path/'virtual.pid'
    wrapper=wrapper_dir/'ffmpeg'
    wrapper.write_text('#!'+sys.executable+'\nimport os,sys,pathlib\na=sys.argv[1:]\n'
        +'if "-filter_complex" in a:\n    pathlib.Path('+repr(str(pidfile))+').write_text(str(os.getpid()))\n'
        +'    a.insert(a.index("-i"), "-re")\nos.execv('+repr(real)+',["ffmpeg",*a])\n')
    wrapper.chmod(0o700)
    monkeypatch.setenv('PATH',str(wrapper_dir)+os.pathsep+os.environ['PATH'])
    f=make_programme_fixture(tmp_path/'fixture',layout='stereo',seconds=4)
    window.source.setText(str(tmp_path/'fixture'/'sources'));window.load_groups(f['manifest']);window.run_qc()
    deadline=time.monotonic()+15
    while time.monotonic()<deadline and 'Programme Programa 日本語 · EBU R128' not in window.log.toPlainText():
        qapp.processEvents();time.sleep(.01)
        if window.process.state()==QProcess.NotRunning: break
    assert 'Programme Programa 日本語 · EBU R128' in window.log.toPlainText()
    pid=int(pidfile.read_text())
    os.kill(pid,0)  # Actual FFmpeg is alive during its virtual measurement.
    window.cancel_qc()
    while time.monotonic()<deadline and window.process.state()!=QProcess.NotRunning:
        qapp.processEvents();time.sleep(.01)
    qapp.processEvents()
    assert window.process.exitCode()==130
    with pytest.raises(ProcessLookupError):os.kill(pid,0)
    assert not (window.report_path.parent/'QC_COMPLETE.json').exists()
