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
    app.quit()
