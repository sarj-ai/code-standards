from __future__ import annotations

import hashlib
from http import HTTPStatus
from http.client import HTTPException
import os
from pathlib import Path
import platform
from random import SystemRandom
import shutil
import tempfile
from time import sleep
from typing import Final
from urllib.error import HTTPError
from urllib.request import Request, urlopen


VERSION: Final = "2026.11.13"
_ROUNDS: Final = 3
_BACKOFF_SECONDS: Final = 2.0
_TRANSIENT_STATUSES: Final = frozenset({HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.TOO_MANY_REQUESTS})
_DIGESTS: Final = {
    "linux-x64": "9c8cc9e10886fe1b1ae2ff625f34905f3bd94e47ee5c9b0d3d597e6629d43d20",
    "linux-arm64": "1d87e6bc2a069869d7f5fe4a6353429b83cd8cb9c12fea0782dae5f30b2a3683",
    "macos-x64": "7e0b50348e00ad9a3ed9efe30012dd6e5f7fb29b4debac8edd93cc3efedded2d",
    "macos-arm64": "973eb467ec9671f73a96a4c6c39f175703dde49523a5532157e659afcc5f2eca",
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
    headers = {"User-Agent": "code-standards-native-bootstrap/1"}
    sources = [
        Request(f"https://mise.jdx.dev/v{VERSION}/mise-v{VERSION}-{target}", headers=headers),
        Request(f"https://github.com/jdx/mise/releases/download/v{VERSION}/mise-v{VERSION}-{target}", headers=headers),
    ]
    failure: OSError | HTTPException = OSError("pinned mise download failed")
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".mise-") as temporary:
        downloaded = Path(temporary) / "mise"
        for attempt in range(_ROUNDS):
            if attempt and sources:
                sleep(SystemRandom().uniform(0, _BACKOFF_SECONDS * 2.0 ** (attempt - 1)))
            for request in list(sources):
                try:
                    _fetch_verified(request, downloaded, expected)
                except _RetiredSourceError as error:
                    failure = error
                    sources.remove(request)
                    continue
                except (OSError, HTTPException) as error:
                    failure = error
                    continue
                downloaded.chmod(0o755)
                downloaded.replace(destination)
                return
    raise failure


class _RetiredSourceError(OSError):
    pass


def _fetch_verified(request: Request, downloaded: Path, expected: str) -> None:
    try:
        with (
            urlopen(request, timeout=120) as response,  # ruff: ignore[suspicious-url-open-usage]  # pyright: ignore[reportAny] -- fixed official HTTPS mirror and release origin.
            downloaded.open("wb") as stream,
        ):
            shutil.copyfileobj(response, stream)  # pyright: ignore[reportAny] -- urllib's bytes stream is consumed without executing it.
    except HTTPError as error:
        if error.code < HTTPStatus.INTERNAL_SERVER_ERROR and error.code not in _TRANSIENT_STATUSES:
            raise _RetiredSourceError(str(error)) from error
        raise
    if not _matches(downloaded, expected):
        message = "pinned mise download checksum mismatch"
        raise _RetiredSourceError(message)


if __name__ == "__main__":
    main()
