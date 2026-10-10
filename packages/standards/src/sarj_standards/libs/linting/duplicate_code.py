from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
import re
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- only catch bounded runner timeout failures.
import tempfile
from typing import TYPE_CHECKING, ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field

from sarj_standards.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Region,
    RelatedLocation,
    Severity,
    SourceDocument,
    ToolReport,
    diagnostic_fingerprint,
)
from sarj_standards.libs.linting.devops_tools import NativeTool, checked_tool, invoke
from sarj_standards.libs.linting.external import ProcessRunner, read_bounded_report, redact_message, run_process


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


SOURCE: Final = "jscpd"
RULE: Final = "duplicate-code"
MIN_TOKENS: Final = 50
FORMATS: Final = ("python", "typescript", "tsx", "swift", "kotlin")
# Tests repeat arrange-act-assert shapes by design; the duplicate-test-body rules own them.
TEST_GLOBS: Final = (
    "**/test/**",
    "**/tests/**",
    "**/__tests__/**",
    "**/e2e/**",
    "**/fixtures/**",
    "**/*.test.*",
    "**/*.spec.*",
    "**/test_*.py",
    "**/*_test.py",
    "**/conftest.py",
    "**/*Test.kt",
    "**/*Tests.swift",
)
_REPORT_NAME: Final = "jscpd-report.json"
_LINE_BREAK: Final = re.compile(r"\r\n|\r|\n")
_HELP: Final = (
    "Move the shared behavior into one function, component, or dependency and call it from each copy. "
    "Keep separate copies only when they are expected to change independently."
)


class _Side(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    name: str = Field(min_length=1)
    start: int = Field(ge=1)
    end: int = Field(ge=1)


class _Clone(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    first_file: _Side = Field(alias="firstFile")
    second_file: _Side = Field(alias="secondFile")


class _Report(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    duplicates: tuple[_Clone, ...]


@dataclass(frozen=True, slots=True, order=True)
class _Block:
    path: str
    start: int
    end: int

    def __str__(self) -> str:
        return f"{self.path}:{self.start}-{self.end}"


@dataclass(frozen=True, slots=True)
class _Source:
    document: SourceDocument
    lines: tuple[str, ...]

    def lines_of(self, block: _Block) -> tuple[str, ...]:
        if block.end > len(self.lines):
            message = f"jscpd reported lines outside {block.path}"
            raise ValueError(message)
        return self.lines[block.start - 1 : block.end]

    def region(self, block: _Block) -> Region:
        start = self.document.point(line=block.start, column=1)
        end = self.document.point(line=block.end, column=len(self.lines_of(block)[-1]) + 1)
        if start is None or end is None:
            message = f"jscpd reported lines outside {block.path}"
            raise ValueError(message)
        return Region(start, end)


def analyze_duplicates(
    *,
    root: Path,
    paths: Sequence[str],
    allows_path: Callable[[str], bool],
    runner: ProcessRunner = run_process,
) -> ToolReport:
    root = root.resolve()
    try:
        tool = checked_tool(SOURCE, root=root, runner=runner)
        diagnostics = parse_jscpd(_run(tool, root=root, paths=paths, runner=runner), root, allows_path=allows_path)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        issue = ExecutionIssue(SOURCE, "tool-failure", redact_message(str(error), root))
        return ToolReport(SOURCE, Completion.FAILED, issues=(issue,))
    return ToolReport(SOURCE, Completion.COMPLETE, diagnostics=diagnostics, version=tool.version)


def _run(tool: NativeTool, *, root: Path, paths: Sequence[str], runner: ProcessRunner) -> str:
    with tempfile.TemporaryDirectory(prefix="code-standards-jscpd-") as directory:
        # An explicit config stops jscpd from merging the repository's .jscpd.json or package.json settings.
        config = Path(directory) / "config.json"
        config.write_text("{}", encoding="utf-8")
        invoke(tool, (*_arguments(directory, config), *paths), root=root, runner=runner)
        return read_bounded_report(Path(directory) / _REPORT_NAME, tool=SOURCE)


def _arguments(output: str, config: Path) -> tuple[str, ...]:
    return (
        "--config",
        str(config),
        "--min-tokens",
        str(MIN_TOKENS),
        "--mode",
        "weak",
        "--format",
        ",".join(FORMATS),
        "--ignore",
        ",".join(TEST_GLOBS),
        "--reporters",
        "json",
        "--output",
        output,
        "--absolute",
        "--silent",
        "--no-tips",
    )


def parse_jscpd(payload: str, root: Path, *, allows_path: Callable[[str], bool]) -> tuple[Diagnostic, ...]:
    root = root.resolve()
    # One diagnostic per copied block, naming every other copy, lets the changed-line baseline
    # report a duplicate when any of its copies is edited.
    copies: defaultdict[_Block, set[_Block]] = defaultdict(set)
    for clone in _Report.model_validate_json(payload).duplicates:
        first, second = _block(root, clone.first_file), _block(root, clone.second_file)
        if allows_path(first.path) and allows_path(second.path):
            copies[first].add(second)
            copies[second].add(first)

    @cache
    def source(path: str) -> _Source:
        document = SourceDocument.read(root / path)
        return _Source(document, tuple(_LINE_BREAK.split(document.text)))

    return tuple(_diagnostic(block, sorted(others), source) for block, others in sorted(copies.items()))


def _block(root: Path, side: _Side) -> _Block:
    path = Path(side.name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        message = "jscpd reported a copy outside the repository's files"
        raise ValueError(message)
    relative = path.relative_to(root).as_posix()
    if side.end < side.start:
        message = f"jscpd reported a reversed line range in {relative}"
        raise ValueError(message)
    return _Block(relative, side.start, side.end)


def _diagnostic(block: _Block, others: Sequence[_Block], source: Callable[[str], _Source]) -> Diagnostic:
    def location(item: _Block) -> Location:
        return Location(item.path, region=source(item.path).region(item))

    diagnostic = Diagnostic(
        RULE,
        f"This {block.end - block.start + 1}-line block also appears at {', '.join(map(str, others))}.",
        Severity.WARNING,
        SOURCE,
        location(block),
        rule_id=RULE,
        help=_HELP,
        related=tuple(RelatedLocation("copy", location(other)) for other in others),
    )
    # Anchor on the block's own text so moving or reindenting it, or changing where its copies live, keeps its baseline identity.
    anchor = " ".join(" ".join(source(block.path).lines_of(block)).split())
    return replace(diagnostic, fingerprint=diagnostic_fingerprint(diagnostic, anchor=anchor))
