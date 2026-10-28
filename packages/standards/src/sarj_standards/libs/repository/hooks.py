from __future__ import annotations

from datetime import timedelta
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

from sarj_standards.libs.adoption import hooks as adoption_hooks, transaction
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.typed_containers import is_object_mapping


_VERSION: Final = "2.2.2"
_CORE_HOOKS: Final = ("pre-commit", "pre-push", "commit-msg")
_LFS_POST_HOOKS: Final = ("post-checkout", "post-commit", "post-merge")
_DISCOVERY_TIMEOUT: Final = timedelta(seconds=5)
_ARCHITECTURES: Final = MappingProxyType({"aarch64": "arm64", "amd64": "x86_64"})
_EXPORT_ASSIGNMENT_PARTS: Final = 2
_UVX_PATH_MARKER: Final = "# sarj-standards: uvx-path"
_EMPTY_INDEX_MARKER: Final = "# sarj-standards: empty-index gate"
_PRECOMMIT_CALL: Final = 'call_lefthook run "pre-commit" --no-auto-install "$@"'


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
    hook_transaction = capture_transaction(root)
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
    subprocess.run([str(binary), "install", "-f"], cwd=root, check=True)  # ruff: ignore[subprocess-without-shell-equals-true] -- pass the fixed executable as an argv sequence with shell execution disabled.
    configured = _configured_hooks(root, binary)
    hook_paths = [path for path in _hook_paths(root) if path.name in configured]
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
            contents = "\n".join(lines) + "\n"
            contents = _harden_managed_call(contents, hook_type=hook_path.name)
            if hook_path.name == "pre-commit":
                contents = _harden_precommit_entry(contents, root)
            transaction.atomic_write_text(hook_path.parent, hook_path, contents)
    subprocess.run([str(binary), "validate"], cwd=root, check=True)  # ruff: ignore[subprocess-without-shell-equals-true] -- pass the fixed executable as an argv sequence with shell execution disabled.
    subprocess.run([str(binary), "check-install"], cwd=root, check=True)  # ruff: ignore[subprocess-without-shell-equals-true] -- pass the fixed executable as an argv sequence with shell execution disabled.


def _configured_hooks(root: Path, binary: Path) -> frozenset[str]:
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- pass the fixed executable as an argv sequence with shell execution disabled.
        [str(binary), "dump", "--format", "json"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=_DISCOVERY_TIMEOUT.total_seconds(),
    )
    configuration = parse_json(completed.stdout)
    if not is_object_mapping(configuration):
        msg = "Lefthook resolved configuration must be a JSON object"
        raise ValueError(msg)
    configured = frozenset(name for name in configuration if isinstance(name, str))
    # Native install refreshes remotes, so only local post hooks have stable ownership before installation.
    return configured.difference(_LFS_POST_HOOKS) if configuration.get("remotes") else configured


def _harden_precommit_entry(contents: str, root: Path) -> str:
    expected = empty_index_gate(root) + _PRECOMMIT_CALL
    if contents.count(_EMPTY_INDEX_MARKER) == 1 and expected in contents:
        return contents
    if _EMPTY_INDEX_MARKER in contents or contents.count(_PRECOMMIT_CALL) != 1:
        msg = "installed Lefthook hook has no unique pre-commit entry point"
        raise OSError(msg)
    return contents.replace(_PRECOMMIT_CALL, expected, 1)


def managed_hook_call(hook_type: str) -> str:
    return f'call_lefthook run "{hook_type}" --no-auto-install "$@"'


def _harden_managed_call(contents: str, *, hook_type: str) -> str:
    expected = managed_hook_call(hook_type)
    if contents.count(expected) == 1:
        return contents
    original = f'call_lefthook run "{hook_type}" "$@"'
    if contents.count(original) != 1:
        msg = f"installed Lefthook hook has no unique {hook_type} entry point"
        raise OSError(msg)
    return contents.replace(original, expected, 1)


def capture_transaction(root: Path) -> transaction.FileTransaction:
    hooks_dir = _hook_path(root, "pre-commit").parent
    transaction.validate_targets(hooks_dir, _hook_transaction_targets(hooks_dir, frozenset()))
    configured = _configured_hooks(root, _binary("lefthook"))
    paths = _hook_transaction_targets(hooks_dir, configured)
    transaction.validate_targets(hooks_dir, paths)
    return transaction.FileTransaction.capture(hooks_dir, paths)


def _hook_transaction_targets(hooks_dir: Path, configured: frozenset[str]) -> tuple[Path, ...]:
    post_hooks = tuple(name for name in _LFS_POST_HOOKS if name in configured)
    return (
        *(hooks_dir / name for hook in _CORE_HOOKS for name in (hook, f"{hook}.legacy")),
        *(hooks_dir / name for hook in post_hooks for name in (hook, f"{hook}.legacy", f"{hook}.old")),
        hooks_dir / ".sarj-lefthook",
        hooks_dir / ".sarj-lefthook.exe",
    )


def run(argv: list[str] | None = None) -> int:
    try:
        # The native hook manager owns this protocol rather than domain CLI fields.
        return _run(
            list(sys.argv[1:] if argv is None else argv)  # sarj-noqa: SARJ533 -- native hook forwarding
        )
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
        and contents.count(managed_hook_call(path.name.removesuffix(".legacy"))) == 1
        and (path.name.removesuffix(".legacy") != "pre-commit" or _has_empty_index_gate(contents))
    )


def empty_index_gate(root: Path | None = None, *, command: str | None = None) -> str:
    selected_command = adoption_hooks.canonical_staged_command(root) if command is None else command
    return (
        f"{_EMPTY_INDEX_MARKER}\n"
        "git diff --cached --quiet --exit-code\n"
        "SARJ_STANDARDS_INDEX_STATUS=$?\n"
        'case "$SARJ_STANDARDS_INDEX_STATUS" in\n'
        f'  0) {selected_command} || exit "$?" ;;\n'
        "  1) ;;\n"
        '  *) exit "$SARJ_STANDARDS_INDEX_STATUS" ;;\n'
        "esac\n"
    )


def _has_empty_index_gate(contents: str) -> bool:
    return contents.count(_EMPTY_INDEX_MARKER) == 1 and any(
        f"{gate}{_PRECOMMIT_CALL}" in contents
        for gate in (empty_index_gate(), empty_index_gate(command=adoption_hooks.SOURCE_STAGED_COMMAND))
    )


def has_managed_uvx_environment(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    markers = tuple(line for line in lines if line.startswith("export PATH=") and line.endswith(f" {_UVX_PATH_MARKER}"))
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
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- pass the fixed executable as an argv sequence with shell execution disabled.
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
    return [path for hook_name in (*_CORE_HOOKS, *_LFS_POST_HOOKS) if (path := _hook_path(root, hook_name)).is_file()]


def _hook_path(root: Path, hook_name: str) -> Path:
    path = Path(_git(root, "rev-parse", "--git-path", f"hooks/{hook_name}").strip())
    return path if path.is_absolute() else root / path


def _installed_version(binary: Path) -> str | None:
    if not binary.is_file():
        return None
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- pass the fixed executable as an argv sequence with shell execution disabled.
        [str(binary), "version"], check=False, capture_output=True, text=True
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        msg = "git is required to manage repository hooks"
        raise OSError(msg)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- pass the fixed executable as an argv sequence with shell execution disabled.
        [executable, *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=_DISCOVERY_TIMEOUT.total_seconds(),
    ).stdout
