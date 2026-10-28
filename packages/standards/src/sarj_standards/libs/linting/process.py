from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import math
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ProcessOutput:
    returncode: int
    stdout: str
    stderr: str


class OutputLimitError(OSError):
    pass


class ToolResolution(StrEnum):
    LOCAL = "local"
    PROVIDED = "provided"


@dataclass(frozen=True, slots=True)
class ProcessCapabilities:
    tool_resolution: ToolResolution = ToolResolution.LOCAL

    def __post_init__(self) -> None:
        if not isinstance(self.tool_resolution, ToolResolution):  # pyright: ignore[reportUnnecessaryIsInstance] -- untyped callers and dataclasses.replace must satisfy the runtime enum boundary.
            message = "process capabilities require an explicit ToolResolution"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ProcessRequest:
    argv: tuple[str, ...] = field(repr=False)
    cwd: Path = field(repr=False)
    environment: Mapping[str, str] = field(repr=False)
    timeout_seconds: float = 900
    deadline: float | None = None
    input_bytes: bytes | None = field(default=None, repr=False)
    max_input_bytes: int | None = None
    max_stdout_bytes: int = 16 * 1024 * 1024
    max_stderr_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", tuple(self.argv))
        if not self.argv:
            message = "process request requires a nonempty argv"
            raise ValueError(message)
        if self.input_bytes is not None and type(self.input_bytes) is not bytes:
            message = "process input requires immutable bytes or None"
            raise TypeError(message)
        _validate_time(self.timeout_seconds, "timeout", nonnegative=True)
        if self.deadline is not None:
            _validate_time(self.deadline, "deadline", nonnegative=False)
        _validate_byte_limit(self.max_stdout_bytes, "stdout")
        _validate_byte_limit(self.max_stderr_bytes, "stderr")
        if self.max_input_bytes is not None:
            _validate_byte_limit(self.max_input_bytes, "input")
            if self.input_bytes is not None and len(self.input_bytes) > self.max_input_bytes:
                message = f"analyzer source exceeds the {self.max_input_bytes} byte input limit"
                raise OutputLimitError(message)
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))


def _validate_time(value: float, label: str, *, nonnegative: bool) -> None:
    if type(value) is not int and type(value) is not float:
        message = f"process {label} must be a non-bool number"
        raise TypeError(message)
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or (nonnegative and value < 0):
        message = f"process {label} must be finite" + (" and nonnegative" if nonnegative else "")
        raise ValueError(message)


def _validate_byte_limit(value: int, label: str) -> None:
    if type(value) is not int:
        message = f"process {label} byte limit must be a non-bool integer"
        raise TypeError(message)
    if value < 0:
        message = f"process {label} byte limit must be nonnegative"
        raise ValueError(message)


@runtime_checkable
class ProcessExecutor(Protocol):
    @property
    def capabilities(self) -> ProcessCapabilities: ...

    def run(self, request: ProcessRequest) -> ProcessOutput: ...


def executor_capabilities(executor: ProcessExecutor) -> ProcessCapabilities:
    if not isinstance(executor, ProcessExecutor) or not isinstance(executor.capabilities, ProcessCapabilities):  # pyright: ignore[reportUnnecessaryIsInstance] -- reject untyped legacy callables and malformed executor policy before dispatch.
        message = "process executor must expose run(ProcessRequest) and explicit ProcessCapabilities"
        raise TypeError(message)
    return executor.capabilities


@dataclass(frozen=True, slots=True)
class RequestExecutor:
    execute: Callable[[ProcessRequest], ProcessOutput]
    capabilities: ProcessCapabilities

    def run(self, request: ProcessRequest) -> ProcessOutput:
        return self.execute(request)
