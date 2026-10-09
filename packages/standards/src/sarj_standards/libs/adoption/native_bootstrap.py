from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shutil
import tempfile
from typing import Final
from urllib.request import Request, urlopen


VERSION: Final = "2026.10.6"
# Official raw-asset digests: https://api.github.com/repos/jdx/mise/releases/tags/v2026.10.6
_DIGESTS: Final = {
    "linux-x64": "3f44343eebc7e0d6623bcea46e304864f02dff648edd75c82871b53cc697b366",
    "linux-arm64": "5f3187febbe9ff98e4c78b3596c7bbfde0e3ef8e4b1820494d03efd499de7b6e",
    "macos-x64": "70e1407e2fdc7a19f94db35745a8e5885b0e4bbdbfb34bfb7e3619d6230a8f70",
    "macos-arm64": "bbcea7b0f844d026424a4c8335357a15a2f5c9e9132c9408de990d9be6f26101",
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
