import hashlib
from pathlib import Path


def source_signature(path):
    """Cheap identity checkpoint; not a content hash or a filesystem lock."""
    stat = Path(path).stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def source_identity_error(path, expected):
    """Accept JSON round-tripped checkpoints, fail closed when unavailable."""
    if (not isinstance(expected, (list, tuple)) or len(expected) != 3
            or any(type(value) is not int for value in expected)):
        return "Source identity from analysis is missing or invalid; rescan a stable copy"
    try:
        if source_signature(path) != tuple(expected):
            return "Source changed since analysis; rescan a stable copy"
    except OSError as exc:
        return f"Cannot verify source identity: {exc}"
    return None


def sha256_file(path: Path, progress=None, *, cancel=None) -> str:
    digest = hashlib.sha256()
    size = path.stat().st_size
    done = 0
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            if cancel:
                cancel.raise_if_cancelled()
            digest.update(block)
            done += len(block)
            if progress:
                progress(done / size if size else 1)
    return digest.hexdigest()
