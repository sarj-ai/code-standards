#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import tempfile


def main() -> None:
    environment = os.environ  # ruff: ignore[banned-api] -- GitHub runner-owned inputs and environment handoffs.
    root = Path(__file__).resolve().parents[2]
    tracked_version = (root / ".python-version").read_text(encoding="utf-8").strip().split(".")
    if environment["UV_PYTHON"].split(".")[: len(tracked_version)] != tracked_version:
        message = "native verification must use the tracked Python version"
        raise ValueError(message)
    temporary = Path(environment["RUNNER_TEMP"]).resolve() / "native-verify"
    for ancestor in (temporary, *temporary.parents):
        if (ancestor / ".git").exists() or (ancestor / "pyproject.toml").exists():
            message = f"native fixture temporary directory has a project ancestor: {ancestor}"
            raise ValueError(message)
    temporary.mkdir(mode=0o700)
    environment["TMPDIR"] = str(temporary)
    if Path(tempfile.gettempdir()) != temporary:
        message = "Python did not select the requested fixture temporary directory"
        raise ValueError(message)
    with tempfile.TemporaryDirectory(dir=temporary) as directory:
        probe = Path(directory) / "access"
        probe.write_text("ok", encoding="utf-8")
        if probe.read_text(encoding="utf-8") != "ok":
            message = "native fixture temporary directory is not readable"
            raise OSError(message)
        probe.unlink()
    with Path(environment["GITHUB_ENV"]).open("a", encoding="utf-8") as stream:
        stream.write(f"TMPDIR={temporary}\n")


if __name__ == "__main__":
    main()
