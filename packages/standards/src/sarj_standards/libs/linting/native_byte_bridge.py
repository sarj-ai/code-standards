from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import TYPE_CHECKING, Literal

from sarj_standards.libs.adoption import lifecycle

from . import native_byte_process as process
from .native_byte_process import child_environment as child_environment


if TYPE_CHECKING:
    from collections.abc import Callable
    import subprocess


@dataclass(frozen=True, slots=True)
class NativeInvocation:
    tool: Literal["eslint", "biome", "prettier"]
    node: Path
    entrypoint: Path
    cwd: Path
    args: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NativeBytes:
    returncode: int
    stdout: bytes
    stderr: bytes


def resolve_node(
    cwd: Path,
    *,
    run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
) -> Path:
    if not cwd.is_absolute() or cwd.resolve() != cwd or not cwd.is_dir():
        message = "native runtime probe requires a canonical project directory"
        raise ValueError(message)
    bridge = Path(process.__file__).resolve()
    before = process.file_record(bridge, contents=True)
    command = lifecycle.Command(
        label="native Node runtime path",
        argv=(sys.executable, "-I", str(bridge), "--node-path"),
        cwd=cwd,
    )
    try:
        completed = run(command)
    finally:
        if process.file_record(bridge, contents=True) != before:
            message = "fixed native byte bridge changed during runtime resolution"
            raise ValueError(message)
    if completed.returncode != 0 or completed.stderr:
        message = "isolated native runtime path probe failed"
        if completed.returncode == process.REJECTED_EXIT_CODE and not completed.stdout:
            reason = process.node_path_failure_reason(completed.stderr)
            if reason is not None:
                message = f"{message}: {reason}"
        raise ValueError(message)
    return process.decode_node_path_text(completed.stdout)


def run_bytes(
    invocation: NativeInvocation,
    source: bytes,
    *,
    run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
) -> NativeBytes:
    request = process.make_request(
        {
            "tool": invocation.tool,
            "node": str(invocation.node),
            "entrypoint": str(invocation.entrypoint),
            "cwd": str(invocation.cwd),
            "args": list(invocation.args),
        },
        source,
    )
    raw = json.dumps(request, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    bridge = Path(process.__file__).resolve()
    bridge_before = process.file_record(bridge, contents=True)
    with tempfile.TemporaryDirectory(prefix="sarj-native-bytes-", dir=process.temp_base()) as temporary:
        directory = Path(temporary).resolve()
        directory.chmod(0o700)
        process.private_directory(directory)
        payload = directory / f"payload.{hashlib.sha256(raw).hexdigest()}.json"
        descriptor = os.open(
            payload,
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | getattr(  # sarj-noqa: SARJ557 -- Probe optional OS capabilities while preserving exclusive private payload creation.
                os, "O_NOFOLLOW", 0
            ),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        payload_before = process.payload_record(payload)
        directory_before = process.private_directory(directory)
        command = lifecycle.Command(
            label=f"{invocation.tool} isolated byte stdin",
            argv=(sys.executable, "-I", str(bridge), str(payload)),
            cwd=invocation.cwd,
        )
        try:
            completed = run(command)
        finally:
            if (
                process.payload_record(payload) != payload_before
                or process.private_directory(directory) != directory_before
            ):
                msg = "native byte bridge payload identity changed"
                raise ValueError(msg)
            if process.file_record(bridge, contents=True) != bridge_before:
                msg = "fixed native byte bridge changed during execution"
                raise ValueError(msg)
            process.validate_request(process.request_json(request))
        if completed.returncode != 0 or completed.stderr:
            msg = "isolated native byte transport failed"
            raise ValueError(msg)
        decoded = process.decode_response(process.load_json(completed.stdout))
        return NativeBytes(decoded.returncode, decoded.stdout, decoded.stderr)
