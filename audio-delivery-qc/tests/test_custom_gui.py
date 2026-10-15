import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
import json
from pathlib import Path
import time

import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from audio_qc.config import ConfigError, load_config
from audio_qc.gui_window import QCWindow


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = QCWindow()
    yield win
    if win.process.state() != QProcess.NotRunning:
        win.process.kill()
        win.process.waitForFinished(5000)
    win.close()
    app.processEvents()


def configure(window):
    window.preset.setCurrentText('CUSTOM')
    e = window.spec_editor
    e.select(e.rate_mode,True)
    e.rate_value.setText('48000')
    e.select(e.bits_required,24)
    e.select(e.loudness_mode,'target')
    e.target.setText('-14,0')
    e.tolerance.setText('1,0')
    e.select(e.peak_mode,True)
    e.peak_value.setText('-6,0')
    e.select(e.bwf_mode,'required')
    e.channels.setText('1, 2, 6')
    e.select(e.clipping,False)


def wait_scan(window):
    deadline = time.monotonic()+20
    while window._running and time.monotonic()<deadline:
        QApplication.processEvents()
        QTest.qWait(10)
    assert not window._running,window.log.toPlainText()
    assert window.open_button.isEnabled(),window.log.toPlainText()
    return json.loads(window.report_path.with_suffix('.json').read_text())


def test_initial_custom_uses_canonical_defaults_and_builtins_read_only(window):
    for preset in ('FILM_48K','BROADCAST_EBU_R128'):
        window.preset.setCurrentText(preset)
        assert not window.spec_editor.isEnabled()
        assert not window.save_button.isEnabled()
        assert window.copy_button.isEnabled()
        assert 'solo lectura' in window.preset_summary.text()
        assert window.effective_config() == load_config(preset=preset)
    window.preset.setCurrentText('CUSTOM')
    assert window.spec_editor.isEnabled() and window.save_button.isEnabled()
    assert window.effective_config() == load_config(preset='CUSTOM')


def test_custom_controls_and_spanish_decimal_input(window):
    configure(window)
    c = window.effective_config()
    assert c['sample_rate']['required']==48000
    assert c['bit_depth']=={'required':24,'preferred':None}
    assert c['loudness']=={'enabled':True,'target_lufs':-14,'tolerance':1}
    assert c['true_peak']['maximum']==-6
    assert c['bwf']['required']
    assert c['channels']['allowed']==[1,2,6]
    assert c['clipping']=={'fail':False,'consecutive_samples':3}
    window.preset.setCurrentText('FILM_48K')
    window.preset.setCurrentText('CUSTOM')
    assert window.effective_config()==c


def test_copy_to_custom_preserves_preset_and_technical_settings(window,tmp_path):
    path=tmp_path/'technical.yaml'
    path.write_text('preset: BROADCAST_EBU_R128\ndefects:\n  max_candidates: 42\n  clicks:\n    merge_gap_ms: 0.25\n  issues:\n    cross_channel_merge_ms: 0\nclipping:\n  consecutive_samples: 5\n')
    window.load_yaml(path)
    window.frame_rate.setCurrentText('24')
    window.defects.setChecked(True)
    expected=window.effective_config()
    window.copy_button.click()
    expected['preset']='CUSTOM'
    assert window.effective_config()==expected
    window.spec_editor.target.setText('-14')
    assert load_config(preset='BROADCAST_EBU_R128')['loudness']['target_lufs']==-23
    window.preset.setCurrentText('BROADCAST_EBU_R128')
    expected['preset']='BROADCAST_EBU_R128'
    assert window.effective_config()==expected


@pytest.mark.parametrize('field,text', [('target','NaN'),('target','inf'),('tolerance',''),
                                       ('tolerance','-1'),('rate_value','48,000'),('channels','1,0'),
                                       ('channels','1,2,'),('peak_value','-6,1.2')])
def test_invalid_edit_never_starts_or_clamps(window,wav,field,text):
    configure(window)
    widget=getattr(window.spec_editor,field)
    widget.setText(text)
    window.source.setText(str(wav))
    window.run_button.click()
    assert window.process.state()==QProcess.NotRunning
    assert window.report_path is None and window._scan_directory is None
    assert 'inválida' in window.status.text()
    assert widget.text()==text


def test_report_only_disabled_and_unrestricted_modes(window):
    configure(window)
    e=window.spec_editor
    e.select(e.rate_mode,False)
    e.select(e.bits_required,None)
    e.select(e.bits_preferred,16)
    e.select(e.loudness_mode,'report')
    e.select(e.peak_mode,False)
    e.select(e.bwf_mode,'warning')
    e.channels.clear()
    c=window.effective_config()
    assert c['sample_rate']['required'] is None and c['bit_depth']=={'required':None,'preferred':16}
    assert c['loudness']=={'enabled':True,'target_lufs':None,'tolerance':None}
    assert c['true_peak']['maximum'] is None and c['channels']['allowed'] is None
    assert c['bwf']=={'required':False,'warn_if_missing':True}
    e.select(e.loudness_mode,'disabled')
    e.select(e.bwf_mode,'ignored')
    assert window.effective_config()['loudness']=={'enabled':False,'target_lufs':None,'tolerance':None}
    assert window.effective_config()['bwf']=={'required':False,'warn_if_missing':False}


def test_invalid_load_keeps_current_state_and_cancel_changes_nothing(window,tmp_path,monkeypatch):
    configure(window)
    window.frame_rate.setCurrentText('30')
    before=deepcopy(window.effective_config())
    bad=tmp_path/'bad.yaml'
    bad.write_text('preset: CUSTOM\ntimecode:\n  frame_rate: 24\nloudness:\n  target_lufs: -14\n  tolerance: -1\n')
    assert window.load_yaml(bad) is False
    assert window.effective_config()==before and window.config_path is None
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a: ('',''))
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a: ('',''))
    window.select_config()
    window.select_save_config()
    assert window.effective_config()==before


def test_gui_save_load_and_worker_use_same_resolved_policy(window,tmp_path,monkeypatch):
    configure(window)
    window.frame_rate.setCurrentText('23.976')
    window.defects.setChecked(True)
    expected=window.effective_config()
    path=tmp_path/'Especificación española 日本語.yaml'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a: (str(path),''))
    window.save_button.click()
    assert load_config(path)==expected
    second=QCWindow()
    try:
        assert second.load_yaml(path)
        assert second.effective_config()==expected
        args=second.scan_arguments(tmp_path/'report')
        worker_path=Path(args[args.index('--config')+1])
        assert worker_path!=path
        assert load_config(worker_path)==expected
        assert second._scan_config==expected
    finally:
        second.close()


def test_save_error_is_visible_and_does_not_change_editor(window,tmp_path):
    configure(window)
    before=window.effective_config()
    assert not window.save_yaml(tmp_path/'missing'/'custom.yaml')
    assert 'No se pudo guardar' in window.status.text()
    assert window.effective_config()==before


@pytest.mark.integration
def test_real_worker_uses_snapshot_even_when_fields_and_original_yaml_change(window,wav,tmp_path):
    configure(window)
    path=tmp_path/'custom.yaml'
    window.save_yaml(path)
    window.load_yaml(path)
    expected=window.effective_config()
    window.source.setText(str(wav))
    window.run_button.click()
    output=window.report_path
    snapshot=Path(window._scan_directory.name)/'resolved.yaml'
    assert load_config(snapshot)==expected
    assert not window.settings.isEnabled()
    window.spec_editor.target.setText('-30')
    path.write_text('invalid: changed after scan started\n')
    window.run_qc()  # Also guard programmatic/repeated Run during startup.
    assert window.report_path==output
    report=wait_scan(window)
    assert report['configuration']==expected
    assert not snapshot.exists()
    assert window.effective_config()['loudness']['target_lufs']==-30
