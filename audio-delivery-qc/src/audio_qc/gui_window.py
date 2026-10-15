"""Desktop specification/reporting controls, using the canonical CLI scan worker."""
from datetime import datetime, timezone
from copy import deepcopy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import uuid

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QGridLayout, QLabel, QLineEdit, QPushButton, QComboBox,
                              QCheckBox, QProgressBar, QPlainTextEdit, QFileDialog, QScrollArea)

from .config import PRESETS, ConfigError, load_config, resolve_config, save_config
from .spec_editor import SpecificationEditor
from .reports.specification import specification_rows
from .timecode import RATES, SOURCES


class QCWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AUDIO DELIVERY QC INSPECTOR")
        self.resize(960, 820)
        self.report_path = None
        self.config_path = None
        self._profiles = {name: load_config(preset=name) for name in PRESETS}
        self._technical = load_config()
        self._scan_directory = None
        self._scan_config = None
        self._running = False
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        title = QLabel("AUDIO DELIVERY QC INSPECTOR")
        title.setStyleSheet("font-size:22px;font-weight:600;color:#153f4c")
        layout.addWidget(title)
        layout.addWidget(QLabel("Local technical QC · source audio stays read-only"))
        self.settings = QWidget()
        form = QVBoxLayout(self.settings)
        form.setContentsMargins(0, 0, 0, 0)
        paths = QHBoxLayout()
        self.source = QLineEdit()
        self.source.setPlaceholderText("Select an audio file or delivery folder")
        self.source.setAccessibleName("Source file or folder")
        paths.addWidget(self.source, 1)
        for label, callback in (("Select File", self.select_file), ("Select Folder", self.select_folder)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            paths.addWidget(button)
        form.addLayout(paths)
        grid = QGridLayout()
        self.preset = QComboBox()
        self.preset.addItems(PRESETS)
        self.preset.setAccessibleName("QC preset")
        self.frame_rate = QComboBox()
        self.frame_rate.addItems(list(RATES))
        self.frame_rate.setCurrentText("25")
        self.frame_rate.setAccessibleName("Frame Rate")
        self.tc_source = QComboBox()
        self.tc_source.addItems(SOURCES)
        self.tc_source.setAccessibleName("TC source")
        self.manual_start = QLineEdit("10:00:00:00")
        self.manual_start.setAccessibleName("Manual start TC")
        self.manual_start.setStyleSheet("font-family:Menlo,monospace")
        for row, col, label, widget in ((0, 0, "QC preset", self.preset), (0, 2, "Frame Rate", self.frame_rate),
                                        (1, 0, "TC source", self.tc_source), (1, 2, "Manual start TC", self.manual_start)):
            caption = QLabel(label)
            caption.setBuddy(widget)
            grid.addWidget(caption, row, col)
            grid.addWidget(widget, row, col+1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        form.addLayout(grid)
        self.tc_hint = QLabel()
        self.tc_hint.setWordWrap(True)
        form.addWidget(self.tc_hint)
        self.tc_source.currentTextChanged.connect(self.update_tc_controls)
        self.frame_rate.currentTextChanged.connect(self.update_tc_controls)
        self.update_tc_controls()
        config_row = QHBoxLayout()
        self.config_label = QLabel("Especificación: valores del preset")
        self.config_label.setWordWrap(True)
        config_row.addWidget(self.config_label, 1)
        load_button = QPushButton("Cargar especificación…")
        load_button.clicked.connect(self.select_config)
        config_row.addWidget(load_button)
        self.save_button = QPushButton("Guardar especificación…")
        self.save_button.clicked.connect(self.select_save_config)
        config_row.addWidget(self.save_button)
        self.copy_button = QPushButton("Copiar a CUSTOM")
        self.copy_button.clicked.connect(self.copy_to_custom)
        config_row.addWidget(self.copy_button)
        form.addLayout(config_row)
        self.spec_editor = SpecificationEditor()
        self.spec_editor.set_config(self._profiles["CUSTOM"])
        form.addWidget(self.spec_editor)
        self.preset_summary = QLabel()
        self.preset_summary.setWordWrap(True)
        form.addWidget(self.preset_summary)
        self.preset.currentTextChanged.connect(self.update_specification)
        self.update_specification()
        options = QHBoxLayout()
        self.defects = QCheckBox("Detect defect candidates")
        self.snippets = QCheckBox("Export evidence WAVs")
        self.hashes = QCheckBox("Calculate SHA-256")
        self.snippets.toggled.connect(lambda enabled: self.defects.setChecked(True) if enabled else None)
        self.defects.toggled.connect(lambda enabled: self.snippets.setChecked(False) if not enabled else None)
        for widget in (self.defects, self.snippets, self.hashes):
            options.addWidget(widget)
        form.addLayout(options)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(self.settings)
        settings_scroll.setMinimumHeight(300)
        layout.addWidget(settings_scroll, 2)
        actions = QHBoxLayout()
        self.run_button = QPushButton("Run QC")
        self.run_button.setStyleSheet("background:#17566a;color:white;padding:10px;font-weight:600")
        self.run_button.clicked.connect(self.run_qc)
        self.open_button = QPushButton("Open Report")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_report)
        actions.addWidget(self.run_button)
        actions.addWidget(self.open_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("Ready. Reports will be created in a new folder beside the source.")
        self.status.setWordWrap(True)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setPlaceholderText("Scan progress and report location will appear here.")
        layout.addWidget(self.log, 1)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_progress)
        self.process.finished.connect(self.scan_finished)
        self.process.errorOccurred.connect(self.process_error)

    def update_tc_controls(self, *_):
        manual = self.tc_source.currentText() == "MANUAL"
        self.manual_start.setEnabled(manual)
        value = self.manual_start.text()
        if len(value) == 11 and value[8] in ":;":
            self.manual_start.setText(value[:8] + (";" if self.frame_rate.currentText() == "29.97 DF" else ":") + value[9:])
        messages = {"AUTO": "Use BWF TimeReference when available; otherwise start at 00:00:00:00.",
                    "FILE_RELATIVE": "Ignore BWF for displayed TC. The first sample is at 00:00:00:00.",
                    "MANUAL": "Set the TC of the first sample. Use a semicolon for 29.97 DF."}
        self.tc_hint.setText(messages[self.tc_source.currentText()] + " Detection always uses exact audio samples.")

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select audio file", "", "Audio (*.wav *.wave *.bwf *.rf64 *.bw64 *.w64 *.aif *.aiff *.flac);;All files (*)")
        if path:
            self.source.setText(path)

    def select_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select delivery folder")
        if path:
            self.source.setText(path)

    def select_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cargar especificación QC", "", "YAML (*.yaml *.yml)")
        if path:
            self.load_yaml(Path(path))

    def load_yaml(self, path):
        try:
            config = load_config(path)
        except ValueError as exc:
            self.status.setText(f"Configuración inválida: {exc}")
            return False
        # Apply only after the complete configuration has passed validation.
        self._technical = deepcopy(config)
        self._profiles[config["preset"]] = deepcopy(config)
        if config["preset"] == "CUSTOM":
            self.spec_editor.set_config(config)
        self.config_path = path
        self.config_label.setText(f"Especificación: {path.name}")
        self.preset.setCurrentText(config["preset"])
        self.update_specification()
        self.frame_rate.setCurrentText(config["timecode"]["frame_rate"])
        self.tc_source.setCurrentText(config["timecode"]["source"])
        if config["timecode"]["manual_start"]:
            self.manual_start.setText(config["timecode"]["manual_start"])
        self.defects.setChecked(config["defects"]["enabled"])
        self.status.setText("Especificación cargada. Los controles de timecode y detección conservan sus ajustes independientes.")
        return True

    def update_specification(self, *_):
        custom = self.preset.currentText() == "CUSTOM"
        self.spec_editor.setVisible(custom)
        self.spec_editor.setEnabled(custom)
        self.preset_summary.setVisible(not custom)
        self.copy_button.setEnabled(not custom)
        self.save_button.setEnabled(custom)
        config = deepcopy(self._profiles[self.preset.currentText()])
        config["clipping"]["consecutive_samples"] = self._technical["clipping"]["consecutive_samples"]
        self.preset_summary.setText("Especificación de solo lectura · " + self.preset.currentText() + "\n" +
                                   "\n".join(f"{label}: {value}" for label, value in specification_rows(config)))

    def effective_config(self):
        selected = self.preset.currentText()
        config = deepcopy(self._technical)
        for key in ("sample_rate", "bit_depth", "pcm", "channels", "loudness", "true_peak", "bwf"):
            config[key] = deepcopy(self._profiles[selected][key])
        config["clipping"]["fail"] = self._profiles[selected]["clipping"]["fail"]
        config["preset"] = selected
        if selected == "CUSTOM":
            config = self.spec_editor.resolve(config)
        timing = {"frame_rate": self.frame_rate.currentText(), "source": self.tc_source.currentText(),
                  "manual_start": self.manual_start.text() if self.tc_source.currentText() == "MANUAL" else None}
        config["defects"]["enabled"] = self.defects.isChecked()
        return resolve_config(config, timecode_overrides=timing)

    def copy_to_custom(self):
        try:
            config = resolve_config(self.effective_config(), preset="CUSTOM")
        except ValueError as exc:
            self.status.setText(f"Configuración inválida: {exc}")
            return
        self._profiles["CUSTOM"] = config
        self.spec_editor.set_config(config)
        self.preset.setCurrentText("CUSTOM")
        self.status.setText("Ajustes copiados a CUSTOM. El preset incluido no se ha modificado.")

    def select_save_config(self):
        path, _ = QFileDialog.getSaveFileName(self, "Guardar especificación CUSTOM", "custom.yaml", "YAML (*.yaml *.yml)")
        if path:
            self.save_yaml(Path(path))

    def save_yaml(self, path):
        try:
            save_config(path, resolve_config(self.effective_config(), preset="CUSTOM"))
        except ValueError as exc:
            self.status.setText(f"No se pudo guardar: {exc}")
            return False
        self.config_label.setText(f"Especificación guardada: {path.name}")
        self.status.setText(f"Especificación CUSTOM guardada: {path}")
        return True

    def _clear_snapshot(self):
        if self._scan_directory is not None:
            self._scan_directory.cleanup()
            self._scan_directory = None

    def scan_arguments(self, output):
        if self._running:
            raise ConfigError("Ya hay un análisis en curso")
        config = self.effective_config()
        self._clear_snapshot()
        self._scan_directory = TemporaryDirectory(prefix="audio-qc-scan-")
        snapshot = Path(self._scan_directory.name) / "resolved.yaml"
        try:
            save_config(snapshot, config)
            snapshot.chmod(0o400)
        except (ValueError, OSError):
            self._clear_snapshot()
            raise
        self._scan_config = deepcopy(config)
        timing = config["timecode"]
        args = ["inspect", self.source.text(), "--preset", config["preset"], "--config", str(snapshot),
                "--frame-rate", timing["frame_rate"], "--timecode-source", timing["source"],
                "--output", str(output)]
        if timing["source"] == "MANUAL":
            args.extend(["--start-timecode", timing["manual_start"]])
        args.append("--defects" if self.defects.isChecked() else "--no-defects")
        if self.snippets.isChecked():
            args.append("--export-defect-snippets")
        if self.hashes.isChecked():
            args.append("--hash")
        return args

    def run_qc(self):
        if self._running or self.process.state() != QProcess.NotRunning:
            return
        source = Path(self.source.text()).expanduser().absolute()
        if not self.source.text() or not source.exists():
            self.status.setText("Select an existing source file or folder.")
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output = source.parent / f"{source.stem}_QC_{stamp}_{uuid.uuid4().hex[:8]}"
        try:
            args = self.scan_arguments(output)
        except (ValueError, OSError) as exc:
            self.status.setText(f"Configuración inválida: {exc}")
            return
        self.report_path = output / "QC_REPORT.html"
        self.log.clear()
        self.settings.setEnabled(False)
        self.run_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.status.setText("Scanning… Source files are read-only.")
        self._running = True
        self.process.start(sys.executable, ["-u", "-m", "audio_qc", *args])

    def read_progress(self):
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        cursor = self.log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def scan_finished(self, code, *_):
        self.read_progress()
        self._running = False
        self._clear_snapshot()
        self.settings.setEnabled(True)
        self.run_button.setEnabled(True)
        self.progress.setRange(0, 1)
        completed = code in (0, 1) and self.report_path is not None and self.report_path.is_file()
        self.progress.setValue(1 if completed else 0)
        self.open_button.setEnabled(completed)
        self.status.setText(("Completed with QC failures. " if code == 1 else "Completed. ") + str(self.report_path)
                            if completed else "Scan could not complete. See the progress log for details.")

    def process_error(self, _):
        self.log.appendPlainText(self.process.errorString())
        if self.process.state() == QProcess.NotRunning:
            self.scan_finished(2)

    def open_report(self):
        if self.report_path and self.report_path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.report_path)))

    def closeEvent(self, event):
        if self.process.state() != QProcess.NotRunning:
            self.status.setText("A scan is running. Keep this window open until it finishes.")
            event.ignore()
        else:
            self._clear_snapshot()
            event.accept()
