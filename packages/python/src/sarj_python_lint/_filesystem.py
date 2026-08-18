from __future__ import annotations

import os
from pathlib import Path
import tempfile


def atomic_write_text(path: Path, contents: str) -> None:
    if not path.parent.is_dir():
        msg = f"baseline parent does not exist: {path.parent}"
        raise OSError(msg)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
