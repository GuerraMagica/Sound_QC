"""Optional local desktop entry point; the CLI needs no Qt dependency."""
import sys


def main():
    try:
        from PySide6.QtWidgets import QApplication
        from .gui_window import QCWindow
    except ImportError:
        print('The desktop interface needs PySide6. In the project environment run: python -m pip install -e ".[gui]"', file=sys.stderr)
        return 2
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("Audio Delivery QC Inspector")
    window = QCWindow()
    window.show()
    return app.exec()
