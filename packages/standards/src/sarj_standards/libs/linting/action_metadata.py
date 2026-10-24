from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, distribution
import json
from pathlib import Path
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- normalize bounded native parser failures.
import sys
import tempfile
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, RootModel

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Severity,
    SourceDocument,
    ToolReport,
)
from sarj_standards.libs.filesystem import read_prefix
from sarj_standards.libs.linting.external import run_process


if TYPE_CHECKING:
    from sarj_standards.libs.linting.external import ProcessRunner

_SHA256 = "7408ae0434ecd92441b1bd32a267e181231493e3f8319ad94655fa781c8ba26a"
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_BATCH_BYTES = 8 * 1024 * 1024
_MAX_BATCH_FILES = 256
_MAX_FAILURE_CHARS = 2_000


class _Error(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str = Field(min_length=1)
    line: int = Field(ge=1)
    column: int = Field(ge=1)


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str
    errors: list[_Error]


class _Results(RootModel[list[_Result]]):
    model_config = ConfigDict(strict=True)


def analyze_actions(
    *, root: Path, paths: tuple[str, ...], runner: ProcessRunner = run_process
) -> tuple[ToolReport, ...]:
    selected = tuple(dict.fromkeys(name for name in paths if Path(name).name in {"action.yml", "action.yaml"}))
    if not selected:
        return ()
    try:
        return _analyze_selected(root, selected, runner=runner)
    except (OSError, ValueError, PackageNotFoundError, subprocess.SubprocessError, RecursionError) as error:
        return (
            ToolReport(
                "action-schema",
                Completion.FAILED,
                issues=(ExecutionIssue("action-schema", "coverage-failure", str(error)),),
                file_count=len(selected),
            ),
        )


def _analyze_selected(root: Path, selected: tuple[str, ...], *, runner: ProcessRunner) -> tuple[ToolReport, ...]:
    reports: list[ToolReport] = []
    documents: dict[str, SourceDocument] = {}
    size = 0
    for name in selected:
        document = _document(root, name)
        document_size = len(document.text.encode("utf-8"))
        if documents and (size + document_size > _MAX_BATCH_BYTES or len(documents) >= _MAX_BATCH_FILES):
            reports.extend(_analyze_batch(root, documents, runner=runner))
            documents = {}
            size = 0
        documents[name] = document
        size += document_size
    if documents:
        reports.extend(_analyze_batch(root, documents, runner=runner))
    return tuple(reports)


def _document(root: Path, name: str) -> SourceDocument:
    path = (root / name).resolve()
    path.relative_to(root.resolve())
    if not path.is_file():
        message = "Action metadata must be a regular file"
        raise ValueError(message)
    content = read_prefix(path, _MAX_SOURCE_BYTES + 1)
    if len(content) > _MAX_SOURCE_BYTES:
        message = "Action metadata exceeds the 2 MiB source bound"
        raise ValueError(message)
    return SourceDocument(path, content.decode("utf-8"))


def _analyze_batch(
    root: Path, documents: dict[str, SourceDocument], *, runner: ProcessRunner
) -> tuple[ToolReport, ...]:
    bundle = CONFIGS_DIR / "action-parser.cjs"
    if hashlib.sha256(bundle.read_bytes()).hexdigest() != _SHA256:
        message = "Pinned GitHub action parser bundle digest does not match"
        raise ValueError(message)
    # BasedPyright already installs this runtime in the core environment. Resolve
    # its distribution directly; standalone action checks need no npm project.
    binary = "nodejs_wheel/node.exe" if sys.platform == "win32" else "nodejs_wheel/bin/node"
    node = distribution("nodejs-wheel-binaries").locate_file(binary)
    with tempfile.TemporaryDirectory(prefix="sarj-action-parser-") as directory:
        source = Path(directory) / "sources.json"
        source.write_text(
            json.dumps([{"path": name, "content": document.text} for name, document in documents.items()]),
            encoding="utf-8",
        )
        argv = (str(node), str(bundle), str(source))
        output = run_process(argv, cwd=root, timeout_seconds=30) if runner is run_process else runner(argv, cwd=root)
    if output.returncode:
        message = f"GitHub action parser failed: {output.stderr.strip()[-_MAX_FAILURE_CHARS:]}"
        raise ValueError(message)
    results = _Results.model_validate_json(output.stdout).root
    if [item.path for item in results] != list(documents):
        message = "GitHub action parser omitted, duplicated or reordered selected files"
        raise ValueError(message)
    return tuple(_report(item, documents[item.path], root=root) for item in results)


def _report(result: _Result, document: SourceDocument, *, root: Path) -> ToolReport:
    diagnostics: list[Diagnostic] = []
    for error in result.errors:
        point = document.utf16_point(line=error.line - 1, character=error.column - 1)
        if point is None:
            message = "GitHub action parser reported a position outside its source document"
            raise ValueError(message)
        diagnostics.append(
            Diagnostic(
                "schema",
                error.message,
                Severity.ERROR,
                "action-schema",
                Location(document.path.relative_to(root.resolve()).as_posix(), position=point),
                rule_id="action-schema",
            )
        )
    return ToolReport(
        "action-schema", Completion.COMPLETE, diagnostics=tuple(diagnostics), version="0.3.61", file_count=1
    )
