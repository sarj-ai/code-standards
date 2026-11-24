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


VERSION: Final = "2026.11.14"
_ROUNDS: Final = 3
_BACKOFF_SECONDS: Final = 2.0
_TRANSIENT_STATUSES: Final = frozenset({HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.TOO_MANY_REQUESTS})
_DIGESTS: Final = {
    "linux-x64": "6fa596291e9758106f761fea4f8e7fac6c3e7ff4714d5c0b9a76e16068db14f6",
    "linux-arm64": "7bd3b2d5ffff077a7662ba186c09600e5b40c1eee9df0c264ed67642ce0a8698",
    "macos-x64": "7f38115f28c6cef9d344bc528670d1033d24a9385455013768e78ad6203d9791",
    "macos-arm64": "ad39dddb61236cc546ecbd0294aa3fc72a5ae7f1f8c7e6dc6fd4211f99eb3b79",
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
