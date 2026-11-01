#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
from shutil import which
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- this CI helper runs only resolved Git with fixed tracked-file enumeration arguments.
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterator


_MAX_FILE_BYTES = 2_000_000

_PUBLIC_BINDINGS = re.compile(
    r"\b(?:VITE_|NEXT_PUBLIC_|REACT_APP_|EXPO_PUBLIC_|PUBLIC_)"
    r"[A-Z0-9_]*(?:SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY|SERVICE_ROLE_KEY)[A-Z0-9_]*\b"
)
_BROWSER_KEYS = frozenset(
    {
        "NEXT_PUBLIC_FIREBASE_API_KEY",
        "VITE_FIREBASE_API_KEY",
        "REACT_APP_FIREBASE_API_KEY",
        "NEXT_PUBLIC_GOOGLE_MAPS_API_KEY",
        "VITE_GOOGLE_MAPS_API_KEY",
        "REACT_APP_GOOGLE_MAPS_API_KEY",
        "PUBLIC_CF_BEACON_TOKEN",
    }
)
_WRANGLER_BINDINGS = re.compile(
    r"""["']?((?=[A-Z])[A-Z0-9_]*(?:SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY|CREDENTIAL|DATABASE_URL|REDIS_URL|CONNECTION_STRING)[A-Z0-9_]*)["']?\s*[:=]\s*["']([^"'\n]+)["']"""
)
_PLACEHOLDER = re.compile(r"^(?:your[-_]|example|placeholder|test[-_]|fake[-_]|changeme|TBD)", re.IGNORECASE)
# PostHog documents phc_ project tokens as public ingestion identifiers; phx_,
# phs_, pha_ and phr_ credentials retain private read/write or OAuth authority.
_POSTHOG_PROJECT_TOKEN = re.compile(r"phc_[A-Za-z0-9_-]{32,128}")
_NATIVE_BINDINGS = re.compile(r"VOICE_API_KEY|TOOL_AUTH_TOKEN|voiceApiKey|toolAuthToken")
_EXCLUDED_SUFFIXES = frozenset({".md", ".mdx", ".lock", ".svg", ".map"})
_EXCLUDED_NAMES = frozenset({"check-public-config.py", "test_public_config.py"})


def main() -> int:
    errors = {finding for path in _tracked_paths() if _eligible(path) for finding in _findings(path)}
    if errors:
        sys.stderr.write("\n".join(sorted(errors)) + "\n")
        return 1
    sys.stdout.write("Public credential policy passed\n")
    return 0


def _tracked_paths() -> Iterator[Path]:
    git = which("git")
    if git is None:
        sys.stderr.write("Git executable is required\n")
        raise SystemExit(1)
    output = subprocess.check_output(  # ruff: ignore[subprocess-without-shell-equals-true] -- only resolved Git and fixed tracked-file enumeration arguments run without a shell.
        [git, "ls-files", "-z"]
    )
    for name in output.decode().split("\0"):
        if name:
            yield Path(name)


def _eligible(path: Path) -> bool:
    return (
        path.is_file()
        and path.stat().st_size <= _MAX_FILE_BYTES
        and path.suffix not in _EXCLUDED_SUFFIXES
        and "lock" not in path.name
        and path.name not in _EXCLUDED_NAMES
    )


def _findings(path: Path) -> Iterator[str]:
    source = path.read_text(encoding="utf-8", errors="ignore")
    if path.name.startswith("wrangler") and path.suffix in {".toml", ".json", ".jsonc"}:
        yield from _wrangler_findings(path, source)
    for variable in {match.group() for match in _PUBLIC_BINDINGS.finditer(source)} - _BROWSER_KEYS:
        yield f"{path}: {variable} is public client configuration and must not carry credentials"
    if path.suffix in {".swift", ".kt", ".kts", ".plist"} and _NATIVE_BINDINGS.search(source):
        yield f"{path}: shared voice/tool credentials must not be compiled into native apps"


def _wrangler_findings(path: Path, source: str) -> Iterator[str]:
    for match in _WRANGLER_BINDINGS.finditer(source):
        binding_name, value = match.groups()
        if binding_name in _BROWSER_KEYS or value.startswith(("${", "{{")) or _PLACEHOLDER.search(value):
            continue
        if binding_name == "POSTHOG_API_KEY" and _POSTHOG_PROJECT_TOKEN.fullmatch(value):
            continue
        yield f"{binding_name} in {path}: use an encrypted secret binding, not a literal configuration value"


if __name__ == "__main__":
    raise SystemExit(main())
