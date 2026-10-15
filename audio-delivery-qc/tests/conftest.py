import shutil
import pytest

from audio_qc.config import load_config
from audio_qc.synthetic import sine, write_wav


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def wav(tmp_path):
    return write_wav(tmp_path/"48k mono.wav", sine(), bext=True)


@pytest.fixture(autouse=True)
def ffmpeg_requirement(request):
    if request.node.get_closest_marker("integration"):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            pytest.skip("Integration tests require local FFmpeg and ffprobe")


@pytest.fixture(scope="session")
def qapp():
    """Keep one Qt application alive until all GUI widgets have been released."""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    # Destroy Qt while Python and its wrappers are still alive, rather than
    # leaving QApplication teardown to interpreter finalization.
    app.shutdown()


@pytest.fixture
def make_window(qapp):
    from PySide6.QtCore import QCoreApplication, QEvent, QProcess
    from shiboken6 import isValid
    from audio_qc.gui_window import QCWindow

    windows = []

    def create():
        window = QCWindow()
        windows.append(window)
        return window

    yield create
    for window in reversed(windows):
        if window.process.state() != QProcess.NotRunning:
            window.process.kill()
            window.process.waitForFinished(5000)
        window.close()
        window.deleteLater()
    # processEvents alone does not deliver DeferredDelete without app.exec().
    # Keep Python references alive until Qt has deleted every window/child.
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    assert all(not isValid(window) for window in windows)


@pytest.fixture
def window(make_window):
    return make_window()
