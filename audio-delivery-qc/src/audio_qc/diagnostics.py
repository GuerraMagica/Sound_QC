"""Per-run logging that cannot replace a QC error with a logging traceback."""
from copy import copy
import logging
from logging.handlers import RotatingFileHandler
import sys


class ConsoleFormatter(logging.Formatter):
    def format(self, record):
        record = copy(record)
        record.exc_info = record.exc_text = record.stack_info = None
        return super().format(record)


class SafeFileHandler(RotatingFileHandler):
    def __init__(self, path):
        super().__init__(path, maxBytes=2 * 1024 * 1024, backupCount=2,
                         encoding="utf-8", delay=True)
        self.failure = None

    def handleError(self, record):
        # logging's default handler prints a traceback when a disk fills up.
        self.failure = str(sys.exc_info()[1]) or "Log write failed"
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError:
                pass
            self.stream = None

    def emit(self, record):
        if self.failure is None:
            super().emit(record)


class RunLog:
    def __init__(self, verbose=False):
        self.logger = logging.Logger("audio_qc.scan", logging.DEBUG)
        self.logger.propagate = False
        self.files = []
        self.notified = set()
        self.error_handler = None
        self.stderr = sys.stderr
        for stream, level, predicate in (
            (sys.stdout, logging.DEBUG if verbose else logging.INFO, lambda r: r.levelno < logging.WARNING),
            (sys.stderr, logging.WARNING, lambda r: r.levelno >= logging.WARNING),
        ):
            handler = logging.StreamHandler(stream)
            handler.setLevel(level)
            handler.addFilter(predicate)
            handler.setFormatter(ConsoleFormatter("%(message)s"))
            self.logger.addHandler(handler)

    def attach(self, output):
        for name, level in (("scan.log", logging.DEBUG), ("error.log", logging.ERROR)):
            handler = SafeFileHandler(output / name)
            handler.set_name(name)
            if name == "error.log":
                self.error_handler = handler
            handler.setLevel(level)
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.logger.addHandler(handler)
            self.files.append(handler)

    def warnings(self):
        errors = []
        for handler in self.files:
            if handler.failure:
                message = f"Cannot write {handler.baseFilename}: {handler.failure}"
                errors.append(message)
                if handler.baseFilename not in self.notified:
                    self.notified.add(handler.baseFilename)
                    self.console_warning(message)
        return errors

    def console_warning(self, message):
        # No file logging here: diagnostic failures must not cause more writes.
        try:
            print(message, file=self.stderr)
        except (OSError, ValueError):
            pass

    def error_saved(self):
        handler = self.error_handler
        return bool(handler is not None and handler.stream is not None and handler.failure is None)

    def close(self):
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            try:
                handler.close()
            except OSError as exc:
                self.console_warning(f"Cannot close diagnostic log: {exc}")
