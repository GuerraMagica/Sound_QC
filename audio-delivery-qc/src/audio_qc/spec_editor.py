"""Spanish specification controls: configuration projection, never QC evaluation."""
from copy import deepcopy
import re

from PySide6.QtWidgets import QComboBox, QGridLayout, QGroupBox, QLabel, QLineEdit

from .config import BIT_DEPTHS, ConfigError, resolve_config


def numeric(text, label, integer=False):
    text = text.strip()
    pattern = r"[+-]?\d+" if integer else r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)"
    if not re.fullmatch(pattern, text):
        raise ConfigError(f"{label}: introduzca un número válido" + (" entero" if integer else " (coma o punto decimal)"))
    return int(text) if integer else float(text.replace(",", "."))


class SpecificationEditor(QGroupBox):
    def __init__(self):
        super().__init__("Especificación CUSTOM")
        grid = QGridLayout(self)

        def combo(name, options):
            box = QComboBox()
            for text, data in options:
                box.addItem(text, data)
            setattr(self, name, box)
            return box

        def entry(name, label):
            field = QLineEdit()
            field.setAccessibleName(label)
            field.setToolTip("Sin separadores de miles. Se acepta coma o punto decimal.")
            setattr(self, name, field)
            return field

        def row(n, label, widget, extra=None):
            caption = QLabel(label)
            caption.setBuddy(widget)
            widget.setAccessibleName(label)
            grid.addWidget(caption, n, 0)
            grid.addWidget(widget, n, 1)
            if extra is not None:
                grid.addWidget(extra, n, 2)

        row(0, "Sample Rate (Hz)", combo("rate_mode", [("Sin requisito", False), ("Requerido", True)]),
            entry("rate_value", "Sample Rate requerido"))
        depths = [("Sin requisito", None)] + [(str(n), n) for n in BIT_DEPTHS]
        row(1, "Bit Depth requerido", combo("bits_required", depths))
        row(2, "Bit Depth preferido", combo("bits_preferred", [("Sin preferencia", None)] + depths[1:]))
        row(3, "Loudness integrado", combo("loudness_mode", [("Desactivado", "disabled"),
            ("Solo informe (sin objetivo)", "report"), ("Objetivo LUFS ± tolerancia LU", "target")]),
            entry("target", "Objetivo LUFS"))
        row(4, "Tolerancia (± LU)", entry("tolerance", "Tolerancia LU"))
        row(5, "True Peak (dBTP)", combo("peak_mode", [("Solo informe (sin máximo)", False), ("Máximo permitido", True)]),
            entry("peak_value", "Máximo True Peak dBTP"))
        row(6, "BWF / BEXT", combo("bwf_mode", [("Ignorar", "ignored"), ("WARNING si falta", "warning"), ("Requerido", "required")]))
        row(7, "Canales físicos permitidos", entry("channels", "Canales físicos permitidos"))
        self.channels.setPlaceholderText("Por archivo: 1 (multiple-mono), 6 (5.1 interleaved); vacío = sin restricción")
        self.channels.setToolTip("Número de canales físicos DENTRO de cada archivo. Un programa 5.1 multiple-mono tiene seis archivos de 1 canal; el layout lógico se valida en Programme groups.")
        row(8, "Clipping", combo("clipping", [("FAIL si cumple el criterio", True), ("WARNING si cumple el criterio", False)]))
        self.hint = QLabel("True Peak es un límite superior. Sin objetivo/máximo no hay fallo numérico. "
                           "La medición de True Peak se ejecuta si Loudness está activo o hay un máximo.")
        self.hint.setWordWrap(True)
        grid.addWidget(self.hint, 9, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        self.peak_value.textChanged.connect(self.update_enabled)
        for box in (self.rate_mode, self.loudness_mode, self.peak_mode):
            box.currentIndexChanged.connect(self.update_enabled)

    @staticmethod
    def select(box, value):
        box.setCurrentIndex(box.findData(value))

    def update_enabled(self, *_):
        self.rate_value.setEnabled(self.rate_mode.currentData())
        self.target.setEnabled(self.loudness_mode.currentData() == "target")
        self.tolerance.setEnabled(self.loudness_mode.currentData() == "target")
        self.peak_value.setEnabled(self.peak_mode.currentData())
        if self.peak_mode.currentData():
            try:
                peak = f"máximo {numeric(self.peak_value.text(), 'True Peak'):g} dBTP"
            except ConfigError:
                peak = "máximo pendiente / inválido; el análisis no puede iniciarse"
        else:
            peak = "sin máximo; el valor desactivado no se aplica"
        self.hint.setText(f"True Peak efectivo: {peak}. La medición se ejecuta si Loudness está activo o hay un máximo. "
                          "Los objetivos y canales físicos se aplican por archivo. Un 5.1 multiple-mono usa seis archivos de 1 canal; "
                          "el loudness integrado de cada mono no determina cumplimiento del programa (no evaluado en M5).")

    def set_config(self, config):
        self.select(self.rate_mode, config["sample_rate"]["required"] is not None)
        self.rate_value.setText(str(config["sample_rate"]["required"]) if config["sample_rate"]["required"] is not None else "")
        for key in ("required", "preferred"):
            self.select(getattr(self, "bits_"+key), config["bit_depth"][key])
        loudness = config["loudness"]
        self.select(self.loudness_mode, "disabled" if not loudness["enabled"] else "report" if loudness["target_lufs"] is None else "target")
        self.target.setText("" if loudness["target_lufs"] is None else str(loudness["target_lufs"]))
        self.tolerance.setText("" if loudness["tolerance"] is None else str(loudness["tolerance"]))
        maximum = config["true_peak"]["maximum"]
        self.select(self.peak_mode, maximum is not None)
        self.peak_value.setText("" if maximum is None else str(maximum))
        self.select(self.bwf_mode, "required" if config["bwf"]["required"] else "warning" if config["bwf"]["warn_if_missing"] else "ignored")
        self.channels.setText(", ".join(map(str, config["channels"]["allowed"] or [])))
        self.select(self.clipping, config["clipping"]["fail"])
        self.update_enabled()

    def resolve(self, base):
        result = deepcopy(base)
        result["sample_rate"]["required"] = numeric(self.rate_value.text(), "Sample Rate", True) if self.rate_mode.currentData() else None
        result["bit_depth"] = {key: getattr(self, "bits_"+key).currentData() for key in ("required", "preferred")}
        mode = self.loudness_mode.currentData()
        result["loudness"] = {"enabled": mode != "disabled",
                              "target_lufs": numeric(self.target.text(), "Objetivo LUFS") if mode == "target" else None,
                              "tolerance": numeric(self.tolerance.text(), "Tolerancia LU") if mode == "target" else None}
        result["true_peak"]["maximum"] = numeric(self.peak_value.text(), "Máximo True Peak") if self.peak_mode.currentData() else None
        bwf = self.bwf_mode.currentData()
        result["bwf"]["required"] = bwf == "required"
        if bwf != "required":
            result["bwf"]["warn_if_missing"] = bwf == "warning"
        text = self.channels.text().strip()
        result["channels"]["allowed"] = [numeric(n.strip(), "Canales", True) for n in text.split(",")] if text else None
        result["clipping"]["fail"] = self.clipping.currentData()
        return resolve_config(result, preset="CUSTOM")
