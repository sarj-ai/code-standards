from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shutil
import tempfile
from typing import Final
from urllib.request import Request, urlopen


VERSION: Final = "2026.10.8"
# Official raw-asset digests: https://api.github.com/repos/jdx/mise/releases/tags/v2026.10.8
_DIGESTS: Final = {
    "linux-x64": "c72477ae6c3a8e7d817a322f43da70e4643e75ee5c21265f1c19c894273b7428",
    "linux-arm64": "6ee0bd8173f1347514f4974d55fb1fae13aa7f6de0a55338adbefa0667cad7e5",
    "macos-x64": "a122fd04db5f2da07d24528ed61109bc82142ca44e821d4faafa05650f6ba627",
    "macos-arm64": "dd77de9a7574e38d8409fb06fa85e1581415896639d075987791d8c4e5a57b73",
}


def main() -> None:
    executable = provision(_cache_root())
    with Path(os.environ["GITHUB_PATH"]).open("a", encoding="utf-8") as stream:  # ruff: ignore[banned-api] -- GitHub's runner-owned path handoff.
        stream.write(f"{executable.parent}\n")


def provision(cache: Path) -> Path:
    target = _target()
    expected = _DIGESTS[target]
    destination = cache / VERSION / target / "bin" / "mise"
    if not _matches(destination, expected):
        destination.parent.mkdir(parents=True, exist_ok=True)
        _download(destination, target=target, expected=expected)
    destination.chmod(0o755)
    return destination.resolve()


def _cache_root() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME", "").strip()  # ruff: ignore[banned-api] -- standard cache location.
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return base / "code-standards" / "native-bootstrap"


def _target() -> str:
    system = {"Linux": "linux", "Darwin": "macos"}.get(platform.system())
    architecture = {"x86_64": "x64", "AMD64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    target = f"{system}-{architecture}"
    if target not in _DIGESTS:
        message = f"pinned mise bootstrap does not support {platform.system()} {platform.machine()}"
        raise ValueError(message)
    return target


def _matches(path: Path, expected: str) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == expected


def _download(destination: Path, *, target: str, expected: str) -> None:
    url = f"https://github.com/jdx/mise/releases/download/v{VERSION}/mise-v{VERSION}-{target}"
    request = Request(url, headers={"User-Agent": "code-standards-native-bootstrap/1"})
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".mise-") as temporary:
        downloaded = Path(temporary) / "mise"
        with (
            urlopen(request, timeout=120) as response,  # ruff: ignore[suspicious-url-open-usage]  # pyright: ignore[reportAny] -- fixed HTTPS release origin.
            downloaded.open("wb") as stream,
        ):
            shutil.copyfileobj(response, stream)  # pyright: ignore[reportAny] -- urllib's bytes stream is consumed without executing it.
        if not _matches(downloaded, expected):
            message = "pinned mise download checksum mismatch"
            raise OSError(message)
        downloaded.chmod(0o755)
        downloaded.replace(destination)


if __name__ == "__main__":
    main()
