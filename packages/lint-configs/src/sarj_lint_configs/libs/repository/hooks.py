"""Install and invoke the repository's pinned Lefthook binary."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed-argument git and Lefthook calls are required.
import sys
from typing import Final


_VERSION: Final = "2.1.10"


def install(root: Path) -> int:
    if not any((root / name).is_file() for name in ("lefthook.yml", "lefthook.yaml")):
        msg = f"no Lefthook configuration found in {root}"
        raise ValueError(msg)
    binary = _binary("lefthook")
    subprocess.run([str(binary), "install", "-f"], cwd=root, check=True)  # ruff: ignore[subprocess-without-shell-equals-true]
    marker = f'export LEFTHOOK_BIN="{_binary("sarj-lefthook").as_posix()}"'
    for hook_name in ("pre-commit", "pre-push"):
        hook_path = Path(_git(root, "rev-parse", "--git-path", f"hooks/{hook_name}").strip())
        if not hook_path.is_absolute():
            hook_path = root / hook_path
        if not hook_path.is_file():
            continue
        lines = [line for line in hook_path.read_text(encoding="utf-8").splitlines() if "LEFTHOOK_BIN=" not in line]
        lines.insert(1, marker)
        hook_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run([str(binary), "validate"], cwd=root, check=True)  # ruff: ignore[subprocess-without-shell-equals-true]
    subprocess.run([str(binary), "check-install"], cwd=root, check=True)  # ruff: ignore[subprocess-without-shell-equals-true]
    return 0


def run(argv: list[str] | None = None) -> int:
    try:
        return _run(list(sys.argv[1:] if argv is None else argv))
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2


def _run(args: list[str]) -> int:
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    binary = _binary("lefthook")
    if _installed_version(binary) != _VERSION:
        msg = f"lefthook {_VERSION} is required; reinstall sarj-lint-configs"
        raise RuntimeError(msg)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [str(binary), *args], cwd=root, check=False
    ).returncode


def _binary(name: str) -> Path:
    executable = shutil.which(name, path=str(Path(sys.executable).parent))
    if executable is None:
        msg = f"{name} is missing from the sarj-lint-configs environment"
        raise OSError(msg)
    return Path(executable)


def _installed_version(binary: Path) -> str | None:
    if not binary.is_file():
        return None
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [str(binary), "version"], check=False, capture_output=True, text=True
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        msg = "git is required to manage repository hooks"
        raise OSError(msg)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [executable, *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout
