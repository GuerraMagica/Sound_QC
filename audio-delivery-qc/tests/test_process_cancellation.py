import os
import sys
from threading import Timer
import pytest
from audio_qc import process


def test_cancel_blocked_reader_reaps_child(tmp_path):
    token = process.CancellationToken()
    pidfile = tmp_path / 'pid'
    timer = Timer(.25, token.cancel)
    timer.start()
    try:
        with pytest.raises(process.ScanCancelled):
            with process.stream_process([sys.executable, '-c',
                 'import os,time,pathlib;pathlib.Path('+repr(str(pidfile))+').write_text(str(os.getpid()));time.sleep(30)'],
                 cancel=token) as pipe:
                pipe.read()
    finally:
        timer.join()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)


def test_cancel_before_spawn():
    token = process.CancellationToken()
    token.cancel()
    token.cancel()
    with pytest.raises(process.ScanCancelled):
        with process.stream_process(['nonexistent-child-should-not-start'], cancel=token):
            pass


def test_timeout_remains_tool_error():
    with pytest.raises(process.ToolError, match='timeout'):
        with process.stream_process([sys.executable, '-c', 'import time;time.sleep(30)'], timeout=.1) as pipe:
            pipe.read()


def test_parser_failure_remains_tool_error():
    def bad(line):
        raise ValueError('malformed')
    with pytest.raises(process.ToolError, match='parser failed'):
        with process.stream_process([sys.executable, '-c', 'import sys;print("x", file=sys.stderr)'], line_callback=bad) as pipe:
            pipe.read()


def test_cancel_hash(tmp_path):
    from audio_qc.hashing import sha256_file
    path = tmp_path / 'hash'; path.write_bytes(b'x'*2000000)
    token = process.CancellationToken()
    with pytest.raises(process.ScanCancelled):
        sha256_file(path, lambda _: token.cancel(), cancel=token)


def test_cancel_wins_over_consumer_failure():
    token=process.CancellationToken()
    with pytest.raises(process.ScanCancelled):
        with process.stream_process([sys.executable,'-c','import time;time.sleep(30)'],cancel=token):
            token.cancel()
            raise process.ToolError('concurrent read failure')
