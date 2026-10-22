from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from sarj_standards.libs.diagnostics import Completion, Diagnostic, ExecutionIssue
from sarj_standards.libs.release.process import ProcessFailureError, run_binary_process
from sarj_standards.libs.repository.immutable_git import git_argv
from sarj_standards.libs.rules import RuleSelection

from .analysis import analyze


if TYPE_CHECKING:
    from sarj_standards.libs.diagnostics import Position
    from sarj_standards.libs.diagnostics.baseline import Provenance


_RULE = "no-excessive-cognitive-complexity"
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_CONTRIBUTOR_LINE = re.compile(r"\bL\d+(?= \+\d+ )")


@dataclass(frozen=True, slots=True)
class _Owner:
    identity: tuple[tuple[str, str], ...]
    tree: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class _ProvenanceFindings:
    owners: tuple[_Owner, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


class _ProvenanceAnalysisError(RuntimeError):
    def __init__(self, issues: tuple[ExecutionIssue, ...]) -> None:
        super().__init__("provenance complexity analysis failed")
        self.issues = issues


def _owners(source: bytes) -> tuple[_Owner, ...]:
    result: list[_Owner] = []

    def visit(node: ast.AST, parents: tuple[tuple[str, str], ...]) -> None:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            parents = (*parents, (type(node).__name__, node.name))
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                result.append(_Owner(parents, ast.dump(node, include_attributes=False), node.lineno, node.col_offset))
        for child in ast.iter_child_nodes(node):
            visit(child, parents)

    visit(ast.parse(source), ())
    return tuple(result)


def _matching_owner(current: tuple[_Owner, ...], original: tuple[_Owner, ...], position: Position) -> _Owner | None:
    owners = [item for item in current if (item.line, item.column) == (position.line + 1, position.character)]
    if len(owners) != 1:
        return None
    owner = owners[0]
    # Repeated definitions with the same qualified identity are ambiguous, even when equal.
    if sum(item.identity == owner.identity for item in current) != 1:
        return None
    matches = [item for item in original if item.identity == owner.identity]
    return matches[0] if len(matches) == 1 and matches[0].tree == owner.tree else None


@lru_cache(maxsize=32)
def _provenance_findings(source: bytes, path: str, _engine_version: str, _catalog_digest: str) -> _ProvenanceFindings:
    # Version and policy are part of the immutable cache key, even when the source repeats.
    owners = _owners(source)
    with TemporaryDirectory(prefix="sarj-complexity-") as directory:
        root = Path(directory)
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source)
        report = analyze([path], root=root, rule_selection=RuleSelection.from_values((f"python:{_RULE}",)))
    if report.issues or report.completion is not Completion.COMPLETE:
        # Failed executions are not immutable results and must not enter the cache.
        issues = report.issues or (
            ExecutionIssue(
                "sarj-standards", "baseline-compatibility-incomplete", "provenance analysis did not complete"
            ),
        )
        raise _ProvenanceAnalysisError(issues)
    return _ProvenanceFindings(owners, report.diagnostics)


class ComplexityBaselineResolver:
    def __init__(self, root: Path, provenance: Provenance) -> None:
        self.root = root
        self.provenance = provenance
        self.issues: list[ExecutionIssue] = []
        self._current: dict[str, tuple[_Owner, ...]] = {}
        self._original: dict[str, _ProvenanceFindings] = {}

    def resolve(self, diagnostic: Diagnostic) -> str | None:
        if diagnostic.source != "sarj-python-lint" or diagnostic.rule_id != _RULE:
            return None
        position = diagnostic.location.position
        if position is None:
            return None
        path = diagnostic.location.path
        try:
            current = self._current_owners(path)
            original = self._original_findings(path)
        except _ProvenanceAnalysisError as error:
            self.issues.extend(error.issues)
            return None
        except (OSError, ValueError, SyntaxError, RecursionError, ProcessFailureError, PackageNotFoundError) as error:
            self.issues.append(ExecutionIssue("sarj-standards", "baseline-compatibility-failure", str(error)))
            return None
        previous = _matching_owner(current, original.owners, position)
        if previous is None:
            return None
        for finding in original.diagnostics:
            old_position = finding.location.position
            if old_position is None or (old_position.line + 1, old_position.character) != (
                previous.line,
                previous.column,
            ):
                continue
            if _CONTRIBUTOR_LINE.sub("L", finding.message) == _CONTRIBUTOR_LINE.sub("L", diagnostic.message):
                return finding.fingerprint
        return None

    def _current_owners(self, path: str) -> tuple[_Owner, ...]:
        if path not in self._current:
            with (self.root / path).open("rb") as stream:
                source = stream.read(_MAX_SOURCE_BYTES + 1)
            self._current[path] = _owners(source) if len(source) <= _MAX_SOURCE_BYTES else ()
        return self._current[path]

    def _original_findings(self, path: str) -> _ProvenanceFindings:
        if path not in self._original:
            self._original[path] = self._read_original(path)
        return self._original[path]

    def _read_original(self, path: str) -> _ProvenanceFindings:
        commit = self.provenance.consumer_base_sha
        presence = run_binary_process(
            git_argv("cat-file", "--batch-check=%(objectname) %(objecttype)"),
            cwd=self.root,
            input_bytes=f"{commit}\n".encode("ascii"),
        )
        if presence.stdout == f"{commit} missing\n".encode("ascii"):
            return _ProvenanceFindings()
        if presence.stdout != f"{commit} commit\n".encode("ascii"):
            msg = "baseline provenance is not a commit"
            raise ValueError(msg)
        metadata = run_binary_process(
            git_argv("--literal-pathspecs", "ls-tree", "-z", "--long", commit, "--", path), cwd=self.root
        )
        records = metadata.stdout.removesuffix(b"\0").split(b"\0")
        if not metadata.stdout.endswith(b"\0") or len(records) != 1 or not records[0]:
            return _ProvenanceFindings()
        header, filename = records[0].split(b"\t", 1)
        mode, kind, oid, size = header.split()
        if (
            mode not in {b"100644", b"100755"}
            or kind != b"blob"
            or filename != path.encode()
            or int(size) > _MAX_SOURCE_BYTES
        ):
            return _ProvenanceFindings()
        blob = run_binary_process(git_argv("cat-file", "blob", oid.decode("ascii")), cwd=self.root)
        if len(blob.stdout) > _MAX_SOURCE_BYTES:
            return _ProvenanceFindings()
        return _provenance_findings(blob.stdout, path, version("sarj-python-lint"), self.provenance.catalog_digest)
