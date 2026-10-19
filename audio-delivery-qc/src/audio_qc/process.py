"""Local-only subprocesses, bounded diagnostic tails, and optional deadlines."""
from collections import deque
from contextlib import contextmanager
import os
import shutil
import subprocess
from threading import Event, Thread, Timer


class ScanCancelled(KeyboardInterrupt):
    """Control flow, never an acoustic or measurement error."""


class CancellationToken:
    def __init__(self):
        self._event = Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set()

    def raise_if_cancelled(self):
        if self.cancelled:
            raise ScanCancelled()


class ToolError(RuntimeError):
    pass


def environment() -> dict:
    env = {**os.environ, "LC_ALL": "C", "AV_LOG_FORCE_NOCOLOR": "1"}
    env.pop("FFREPORT", None)  # never create a log beside a source file
    return env


def check_tools() -> dict:
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise ToolError("Missing " + ", ".join(missing) +
                        ". On macOS install Homebrew from https://brew.sh, then run: brew install ffmpeg")
    versions = {}
    for name in ("ffmpeg", "ffprobe"):
        try:
            result = subprocess.run([name, "-version"], capture_output=True, timeout=10,
                                    env=environment(), check=True, text=True)
            versions[name] = result.stdout.splitlines()[0]
        except (OSError, subprocess.SubprocessError) as exc:
            raise ToolError(f"Cannot run {name}: {exc}") from exc
    return versions


@contextmanager
def stream_process(args: list[str], timeout=None, line_callback=None, *, cancel=None):
    """Drain stderr concurrently so a full pipe cannot deadlock an audio read."""
    tail = deque(maxlen=32)
    callback_errors = []
    timed_out = []
    if cancel:
        cancel.raise_if_cancelled()
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=environment())

    def drain():
        while line := proc.stderr.readline(8192):
            text = line.decode("utf-8", errors="replace").rstrip()
            tail.append(text)
            if line_callback and not callback_errors:
                try:
                    line_callback(text)
                except Exception as exc:
                    callback_errors.append(exc)

    def expire():
        timed_out.append(True)
        if proc.poll() is None:
            proc.kill()

    finished = Event()

    def watch_cancel():
        while not finished.wait(.05):
            if cancel.cancelled:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                return

    watcher = Thread(target=watch_cancel, daemon=True) if cancel else None
    if watcher:
        watcher.start()

    thread = Thread(target=drain, daemon=True)
    thread.start()
    timer = Timer(timeout, expire) if timeout else None
    if timer:
        timer.daemon = True
        timer.start()
    try:
        yield proc.stdout
        result = proc.wait()
        thread.join()
        if cancel:
            cancel.raise_if_cancelled()
        if timed_out:
            raise ToolError(f"Process exceeded configured timeout ({timeout}s)")
        if result:
            raise ToolError("\n".join(tail)[-8192:] or f"Process exited with code {result}")
        if callback_errors:
            raise ToolError(f"Measurement parser failed: {callback_errors[0]}")
    except Exception:
        if cancel:
            cancel.raise_if_cancelled()
        raise
    finally:
        finished.set()
        if timer:
            timer.cancel()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        if watcher:
            watcher.join(timeout=3)
        thread.join(timeout=2)
        proc.stdout.close()
        proc.stderr.close()


def ffmpeg_input(path, loglevel="error") -> list[str]:
    return ["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-v", loglevel,
            "-xerror", "-protocol_whitelist", "file,pipe", "-guess_layout_max", "0",
            "-i", str(path), "-map", "0:a:0", "-vn", "-sn", "-dn"]
