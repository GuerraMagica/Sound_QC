"""Qt lifecycle for one disposable preview process and the latest pending request."""
from copy import deepcopy
import json
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .group_preview import MAX_OUTPUT_BYTES, MAX_REQUEST_BYTES, error_response


class GroupPreviewController(QObject):
    result_ready = Signal(object)
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._generation = 0
        self._pending = None
        self._process = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._start_pending)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.setInterval(300)
        self._kill_timer.timeout.connect(self._kill)

    @property
    def is_idle(self):
        return self._process is None and self._pending is None and not self._debounce.isActive()

    def cancel(self):
        self._generation += 1
        self._pending = None
        self._debounce.stop()
        if self._process is not None:
            self._aborted = True
            self._process.terminate()
            if not self._kill_timer.isActive():
                self._kill_timer.start()

    def request(self, source, settings):
        self.cancel()
        try:
            job = dict(request_id=self._generation, source=source, settings=deepcopy(settings))
            payload = json.dumps(job, ensure_ascii=True, allow_nan=False).encode('ascii')
            if len(payload) > MAX_REQUEST_BYTES:
                raise ValueError('Preview request exceeds 4 MiB; QC remains available')
        except (TypeError, ValueError) as exc:
            self.result_ready.emit(error_response(self._generation, exc))
            return
        self._pending = (self._generation, payload)
        self._debounce.start()

    def _start_pending(self):
        if self._process is not None or self._pending is None or self._debounce.isActive():
            return
        request_id, payload = self._pending
        self._pending = None
        process = QProcess(self)
        self._process = process
        self._aborted, self._fault = False, None
        self._stdout, self._stderr = bytearray(), bytearray()
        process.started.connect(lambda: self._send(process, payload))
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.readyReadStandardError.connect(lambda: self._read(process))
        process.finished.connect(lambda code, status: self._finished(process, request_id, code, status))
        process.errorOccurred.connect(lambda error: self._error(process, request_id, error))
        process.start(sys.executable, ['-m', 'audio_qc.group_preview'])

    def _send(self, process, payload):
        if process is not self._process or self._aborted:
            return
        if process.write(payload) != len(payload):
            self._fault = 'Could not send preview request'
            self._kill()
        process.closeWriteChannel()

    def _read(self, process):
        if process is not self._process:
            return
        # Bound retained output on both channels, and kill noisy auxiliaries.
        for buffer, raw in ((self._stdout, process.readAllStandardOutput()),
                            (self._stderr, process.readAllStandardError())):
            remaining = MAX_OUTPUT_BYTES - len(buffer)
            buffer.extend(bytes(raw[:remaining]))
            if raw.size() > remaining:
                self._fault = 'Preview output exceeded its safety limit'
                self._kill()

    def _kill(self):
        if self._process is not None:
            self._process.kill()

    def _error(self, process, request_id, error):
        if process is not self._process:
            return
        self._fault = self._fault or process.errorString()
        if error == QProcess.FailedToStart:
            # Qt emits no finished signal when the executable cannot start.
            self._finished(process, request_id, -1, QProcess.CrashExit)

    def _response(self, request_id, code, status):
        if self._fault or status != QProcess.NormalExit or code not in (0, 2):
            detail = self._fault or bytes(self._stderr[:4000]).decode('utf-8', errors='replace')
            return error_response(request_id, detail or f'Preview process exited with code {code}')
        try:
            result = json.loads(self._stdout)
            if (not isinstance(result, dict) or type(result.get('request_id')) is not int
                    or result['request_id'] != request_id
                    or result.get('status') not in ('SUCCESS', 'PARTIAL', 'ERROR')
                    or not isinstance(result.get('text'), str)
                    or type(result.get('truncated')) is not bool
                    or type(result.get('notice_count')) is not int or result['notice_count'] < 0
                    or (result['status'] != 'ERROR' and
                        (type(result.get('group_count')) is not int or result['group_count'] < 0))
                    or (code == 2 and result['status'] != 'ERROR')):
                raise ValueError('Invalid preview response')
            return result
        except (ValueError, TypeError, UnicodeError) as exc:
            return error_response(request_id, f'Invalid preview response: {exc}')

    def _finished(self, process, request_id, code, status):
        if process is not self._process:
            return
        self._read(process)
        current = not self._aborted and request_id == self._generation
        result = self._response(request_id, code, status) if current else None
        self._kill_timer.stop()
        self._process = None
        self._stdout.clear()
        self._stderr.clear()
        process.deleteLater()
        if result is not None:
            self.result_ready.emit(result)
        self._start_pending()
        if self.is_idle:
            self.idle.emit()
