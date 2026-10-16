import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import json
import time

import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from audio_qc.config import load_config


@pytest.mark.parametrize("enabled,maximum", [(True, -1), (False, None)])
def test_true_peak_visible_mode_roundtrip_and_worker_snapshot(window, make_window, tmp_path, enabled, maximum):
    window.preset.setCurrentText("CUSTOM")
    editor = window.spec_editor
    editor.peak_value.setText("-1")
    editor.select(editor.peak_mode, enabled)
    assert editor.peak_value.isEnabled() == enabled
    assert window.effective_config()["true_peak"]["maximum"] == maximum
    assert ("máximo -1 dBTP" if enabled else "sin máximo; el valor desactivado no se aplica") in editor.hint.text()
    assert "seis archivos de 1 canal" in editor.hint.text()
    path = tmp_path / "custom.yaml"
    assert window.save_yaml(path)
    second = make_window()
    assert second.load_yaml(path)
    assert second.effective_config()["true_peak"]["maximum"] == maximum
    args = second.scan_arguments(tmp_path / "out")
    snapshot = Path(args[args.index("--config")+1])
    assert load_config(snapshot)["true_peak"]["maximum"] == maximum
    second.spec_editor.peak_value.setText("-9")
    assert load_config(snapshot)["true_peak"]["maximum"] == maximum


@pytest.mark.integration
def test_real_gui_minus_one_peak_matches_saved_report(window, wav):
    window.source.setText(str(wav))
    window.preset.setCurrentText("CUSTOM")
    editor = window.spec_editor
    editor.select(editor.peak_mode, True)
    editor.peak_value.setText("-1")
    window.run_button.click()
    deadline = time.monotonic()+20
    while window._running and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(10)
    assert not window._running, window.log.toPlainText()
    assert window.open_button.isEnabled(), window.log.toPlainText()
    report = json.loads(window.report_path.with_suffix(".json").read_text())
    assert report["configuration"]["true_peak"]["maximum"] == -1
    assert "True Peak: maximum -1 dBTP" in window.log.toPlainText()
