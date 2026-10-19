import hashlib
from pathlib import Path


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
