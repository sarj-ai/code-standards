from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed-argument git and Lefthook calls are required.
import sys
import sysconfig
from types import MappingProxyType
from typing import Final

from sarj_standards.libs.adoption import transaction


_VERSION: Final = "2.1.12"
_ARCHITECTURES: Final = MappingProxyType({"aarch64": "arm64", "amd64": "x86_64"})
_EXPORT_ASSIGNMENT_PARTS: Final = 2
_UVX_PATH_MARKER: Final = "# sarj-standards: uvx-path"


def install(root: Path) -> int:
    if not any((root / name).is_file() for name in ("lefthook.yml", "lefthook.yaml")):
        msg = f"no Lefthook configuration found in {root}"
        raise ValueError(msg)
    binary = _binary("lefthook")
    uvx = shutil.which(
        "uvx",
        path=os.environ.get("PATH", ""),  # ruff: ignore[banned-api] — capture install-time path for GUI Git clients.
    )
    if uvx is None:
        msg = "uvx is required by the managed repository hook command"
        raise OSError(msg)
    native_binary = _native_binary()
    durable_binary = _hook_path(root, "pre-commit").parent / f".sarj-lefthook{native_binary.suffix}"
    hook_targets = _hook_transaction_targets(durable_binary.parent)
    transaction.validate_targets(durable_binary.parent, hook_targets)
    hook_transaction = transaction.FileTransaction.capture(durable_binary.parent, hook_targets)
    try:
        _install_managed_hooks(root, binary, native_binary, durable_binary, Path(uvx))
    except BaseException as exc:
        rollback_error = hook_transaction.rollback().render()
        if rollback_error is not None:
            msg = f"hook installation failed and rollback was incomplete: {rollback_error}"
            raise OSError(msg) from exc
        raise
    return 0


def _install_managed_hooks(
    root: Path,
    binary: Path,
    native_binary: Path,
    durable_binary: Path,
    uvx: Path,
) -> None:
    subprocess.run([str(binary), "install", "-f"], cwd=root, check=True)  # ruff: ignore[subprocess-without-shell-equals-true]
    hook_paths = _hook_paths(root)
    if hook_paths:
        transaction.atomic_write_bytes(
            durable_binary.parent,
            durable_binary,
            native_binary.read_bytes(),
            mode=stat.S_IMODE(native_binary.stat(follow_symlinks=False).st_mode),
        )
        marker = f"export LEFTHOOK_BIN={shlex.quote(durable_binary.as_posix())}"
        uvx_path = f'export PATH={shlex.quote(uvx.parent.as_posix())}:"$PATH" {_UVX_PATH_MARKER}'
        for hook_path in hook_paths:
            lines = [
                line
                for line in hook_path.read_text(encoding="utf-8").splitlines()
                if "LEFTHOOK_BIN=" not in line and _UVX_PATH_MARKER not in line
            ]
            lines.insert(1, marker)
            lines.insert(2, uvx_path)
            transaction.atomic_write_text(hook_path.parent, hook_path, "\n".join(lines) + "\n")
    subprocess.run([str(binary), "validate"], cwd=root, check=True)  # ruff: ignore[subprocess-without-shell-equals-true]
    subprocess.run([str(binary), "check-install"], cwd=root, check=True)  # ruff: ignore[subprocess-without-shell-equals-true]


def _hook_transaction_targets(hooks_dir: Path) -> tuple[Path, ...]:
    return tuple(
        hooks_dir / name
        for name in (
            "pre-commit",
            "pre-commit.legacy",
            "commit-msg",
            "commit-msg.legacy",
            "pre-push",
            "pre-push.legacy",
            ".sarj-lefthook",
            ".sarj-lefthook.exe",
        )
    )


def run(argv: list[str] | None = None) -> int:
    try:
        return _run(list(sys.argv[1:] if argv is None else argv))
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2


def is_durable_binary(path: Path) -> bool:
    try:
        expected = _native_binary()
        if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
            return False
        if path.stat(follow_symlinks=False).st_size != expected.stat(follow_symlinks=False).st_size:
            return False
        return _sha256(path) == _sha256(expected)
    except OSError:
        return False


def has_durable_environment(path: Path) -> bool:
    try:
        contents = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    binary_markers = tuple(re.finditer(r"(?m)^export LEFTHOOK_BIN=(?P<value>.+)$", contents))
    path_markers = tuple(
        line
        for line in contents.splitlines()
        if line.endswith(f" {_UVX_PATH_MARKER}") and line.startswith("export PATH=")
    )
    if len(binary_markers) != 1 or len(path_markers) != 1:
        return False
    try:
        binary_values = shlex.split(binary_markers[0].group("value"))
        path_values = shlex.split(path_markers[0].removesuffix(f" {_UVX_PATH_MARKER}"))
    except ValueError:
        return False
    if len(binary_values) != 1 or len(path_values) != _EXPORT_ASSIGNMENT_PARTS or path_values[0] != "export":
        return False
    durable = Path(binary_values[0])
    assignment = path_values[1]
    if not assignment.startswith("PATH=") or not assignment.endswith(":$PATH"):
        return False
    return (
        durable.parent == path.parent
        and durable.name in {".sarj-lefthook", ".sarj-lefthook.exe"}
        and is_durable_binary(durable)
        and has_managed_uvx_environment(path)
    )


def has_managed_uvx_environment(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    markers = tuple(
        line for line in lines if line.startswith("export PATH=") and line.endswith(f" {_UVX_PATH_MARKER}")
    )
    if len(markers) != 1:
        return False
    try:
        values = shlex.split(markers[0].removesuffix(f" {_UVX_PATH_MARKER}"))
    except ValueError:
        return False
    if len(values) != _EXPORT_ASSIGNMENT_PARTS or values[0] != "export":
        return False
    assignment = values[1]
    if not assignment.startswith("PATH=") or not assignment.endswith(":$PATH"):
        return False
    directory = Path(assignment.removeprefix("PATH=").removesuffix(":$PATH"))
    uvx_names = ("uvx.exe",) if platform.system() == "Windows" else ("uvx",)
    return any((directory / name).is_file() and os.access(directory / name, os.X_OK) for name in uvx_names)


def _sha256(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def _run(args: list[str]) -> int:
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    binary = _binary("lefthook")
    if _installed_version(binary) != _VERSION:
        msg = f"lefthook {_VERSION} is required; reinstall code-standards"
        raise RuntimeError(msg)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [str(binary), *args], cwd=root, check=False
    ).returncode


def _binary(name: str) -> Path:
    executable = shutil.which(name, path=str(Path(sys.executable).parent))
    if executable is None:
        msg = f"{name} is missing from the code-standards environment"
        raise OSError(msg)
    return Path(executable)


def _native_binary() -> Path:
    system = platform.system().lower()
    machine = platform.machine().lower()
    architecture = _ARCHITECTURES.get(machine, machine)
    suffix = ".exe" if system == "windows" else ""
    binary = (
        Path(sysconfig.get_path("purelib"))
        / "lefthook"
        / "bin"
        / f"lefthook-{system}-{architecture}"
        / f"lefthook{suffix}"
    )
    if not binary.is_file():
        msg = f"native Lefthook binary is missing from the code-standards environment: {binary}"
        raise OSError(msg)
    return binary


def _hook_paths(root: Path) -> list[Path]:
    return [
        path
        for hook_name in ("pre-commit", "pre-push", "commit-msg")
        if (path := _hook_path(root, hook_name)).is_file()
    ]


def _hook_path(root: Path, hook_name: str) -> Path:
    path = Path(_git(root, "rev-parse", "--git-path", f"hooks/{hook_name}").strip())
    return path if path.is_absolute() else root / path


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
