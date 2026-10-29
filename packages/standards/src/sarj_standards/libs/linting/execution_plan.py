from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

from sarj_standards.libs.diagnostics import InvocationId, ToolReport

from .process import ProcessExecutor


type AnalysisJobs = Literal[1, 2]
type AnalyzeGroup = Callable[[], tuple[ToolReport, ...]]


def analysis_jobs(value: int) -> AnalysisJobs:
    if type(value) is not int or value not in {1, 2}:
        msg = "analysis jobs must be 1 or 2"
        raise ValueError(msg)
    return 1 if value == 1 else 2


class GroupKind(StrEnum):
    NATIVE = "native"
    EXTERNAL = "external"


@dataclass(frozen=True, slots=True)
class GroupTask:
    kind: GroupKind
    analyze: AnalyzeGroup = field(repr=False)


@dataclass(frozen=True, slots=True)
class AnalysisPlan:
    native: GroupTask
    external: GroupTask
    jobs: AnalysisJobs


@dataclass(frozen=True, slots=True)
class RuffProjectPlan:
    root: Path
    project: Path
    config: Path | None
    files: tuple[str, ...]
    invocation_id: InvocationId | None
    executor: ProcessExecutor = field(repr=False)


@dataclass(frozen=True, slots=True)
class ShellCheckFamilyPlan:
    root: Path
    files: tuple[str, ...]
    unsupported_files: tuple[str, ...]
    attest_version: bool
    executor: ProcessExecutor = field(repr=False)
