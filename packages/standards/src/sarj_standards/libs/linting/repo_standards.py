from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import version
import os
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed read-only Git query.

from repo_standards.core.models import (
    Diagnostic as RepositoryDiagnostic,
    InputProvenance,
    Mode,
    RatchetClassification,
    SourceLocation as RepositoryLocation,
)
from repo_standards.repository import (
    RepositoryAnalysisRequest,
    analyze_repository,
    parse_manifest_bytes,
    read_tracked_blob_contents,
)

from sarj_standards.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    Position,
    Region,
    RelatedLocation,
    Severity,
    ToolReport,
)
from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.typed_containers import is_object_mapping


_MANIFEST = Path(".repo-standards/repository.toml")
_ADOPTED = Path(".sarj-standards.toml")
_BASELINE = Path(".repo-standards/baseline.json")
_MAKEFILE_GROWTH_RULE = "repository/artifacts/makefile-growth"
_MAX_EVENT_BYTES = 1024 * 1024
_GIT_READ_OPTIONS = ("--no-replace-objects", "--no-lazy-fetch", "--no-optional-locks")


def analyze(root: Path, *, staged: bool) -> ToolReport | None:
    # A committed-tree check has no repository snapshot before the first commit.
    # The staged pre-commit path still analyzes the exact index for an initial commit.
    if (staged and not _is_git_worktree(root)) or (not staged and not _has_committed_tree(root)):
        return None
    selected_manifest = _selected_path_exists(root, _MANIFEST, staged=staged)
    selected_adopted = _selected_path_exists(root, _ADOPTED, staged=staged)
    if not selected_manifest and not selected_adopted:
        return None
    has_baseline = _selected_path_exists(root, _BASELINE, staged=staged)
    report = analyze_repository(
        RepositoryAnalysisRequest(
            root=root,
            baseline_path=_BASELINE.as_posix() if has_baseline else None,
            mode=Mode.RATCHET if has_baseline else Mode.STRICT,
            staged=staged,
            base_revision=_comparison_base(root) if not staged else None,
            as_of=datetime.now(UTC).date(),
        )
    )
    issues = tuple(
        ExecutionIssue(
            "repo-standards",
            issue.code,
            f"{issue.phase}: {issue.message}",
            exit_code=2,
        )
        for issue in report.execution_issues
    )
    known: frozenset[str] = (
        frozenset(report.ratchet.fingerprints(RatchetClassification.KNOWN))
        if report.ratchet is not None
        else frozenset[str]()
    )
    known -= frozenset(item.fingerprint for item in report.diagnostics if str(item.rule_id) == _MAKEFILE_GROWTH_RULE)
    diagnostics = tuple(
        _diagnostic(
            item,
            baselined=item.fingerprint in known,
            comparison_notes=_comparison_notes(report.input_provenance)
            if str(item.rule_id) == _MAKEFILE_GROWTH_RULE
            else (),
        )
        for item in report.diagnostics
    )
    return ToolReport(
        "repo-standards",
        Completion.FAILED if issues else Completion.COMPLETE,
        diagnostics=diagnostics,
        issues=issues,
        version=version("repo-standards"),
        baselined_count=len(known),
    )


def _comparison_notes(provenance: InputProvenance | None) -> tuple[str, ...]:
    if provenance is None or provenance.comparison_basis is None:
        return ()
    return (
        (
            f"Git comparison: {provenance.comparison_basis}; "
            f"base {provenance.comparison_base_revision}/{provenance.comparison_base_tree_digest}; "
            f"head {provenance.mode} {provenance.source_revision}/{provenance.tree_digest}"
        ),
    )


def _diagnostic(item: object, *, baselined: bool, comparison_notes: tuple[str, ...] = ()) -> Diagnostic:
    if not isinstance(item, RepositoryDiagnostic):
        msg = "Repo Standards returned an invalid diagnostic type"
        raise TypeError(msg)
    baselined = baselined and str(item.rule_id) != _MAKEFILE_GROWTH_RULE
    severity = (
        Severity.INFO
        if baselined or item.disposition == "excepted"
        else Severity.ERROR
        if item.severity == "error"
        else Severity.WARNING
    )
    location = _location(item.location, fallback=item.path or _MANIFEST.as_posix())
    help_text = " ".join(
        (
            item.remediation.summary,
            *item.remediation.steps,
            *item.remediation.validation,
        )
    )
    notes = (
        f"rule version: {item.rule_version}",
        f"evidence: {item.evidence_level}",
        f"component: {item.component_id}",
        f"observed: {item.observed}",
        f"expected: {item.expected}",
        *comparison_notes,
        *(("ratchet: known",) if baselined else ()),
        *(f"manifest pointer: {item.location.pointer}" for _ in (0,) if item.location and item.location.pointer),
    )
    return Diagnostic(
        str(item.rule_id),
        item.message,
        severity,
        "repo-standards",
        location,
        rule_id=str(item.rule_id),
        help=help_text,
        notes=notes,
        related=tuple(
            RelatedLocation(
                f"{related.relationship}: {related.message}",
                _location(related.location, fallback=location.path),
            )
            for related in item.related_locations
        ),
        fingerprint=item.fingerprint,
    )


def _location(item: RepositoryLocation | None, *, fallback: str) -> Location:
    if item is None:
        return Location(fallback)
    start = _position(item.line, item.column)
    end = _position(item.end_line, item.end_column)
    if start is not None and end is not None:
        return Location(item.path, region=Region(start, end))
    return Location(item.path, position=start)


def _position(line: int | None, column: int | None) -> Position | None:
    if line is None:
        return None
    return Position(line - 1, (column or 1) - 1, 0)


def _is_git_worktree(root: Path) -> bool:
    git = shutil.which("git")
    if git is None:
        return False
    worktree = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (git, *_GIT_READ_OPTIONS, "rev-parse", "--is-inside-work-tree"),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return worktree.returncode == 0 and worktree.stdout.strip() == "true"


def _has_committed_tree(root: Path) -> bool:
    git = shutil.which("git")
    if git is None or not _is_git_worktree(root):
        return False
    head = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (git, *_GIT_READ_OPTIONS, "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if head.returncode == 0:
        return True
    symbolic_head = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (git, *_GIT_READ_OPTIONS, "symbolic-ref", "--quiet", "HEAD"),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if symbolic_head.returncode != 0:
        return True
    referenced = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (git, *_GIT_READ_OPTIONS, "show-ref", "--verify", "--quiet", symbolic_head.stdout.strip()),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Only an absent branch reference proves an unborn repository. A present or
    # unreadable reference must reach Repo Standards and fail analysis closed.
    return referenced.returncode != 1


def _comparison_base(root: Path) -> str | None:
    try:
        selected = read_tracked_blob_contents(root, (_MANIFEST.as_posix(),))
        configured = parse_manifest_bytes(selected[0].content)
    except OSError, TypeError, ValueError:
        # The engine reports missing or invalid selected manifests itself.
        return None
    if _MAKEFILE_GROWTH_RULE not in configured.enabled_rules:
        return None
    explicit = os.environ.get("SARJ_STANDARDS_BASE", "").strip()  # ruff: ignore[banned-api] -- explicit CI boundary.
    if explicit:
        return _validated_revision(explicit)
    event = os.environ.get("GITHUB_EVENT_NAME", "").strip()  # ruff: ignore[banned-api] -- GitHub event boundary.
    keys = {
        "pull_request": ("pull_request", "base", "sha"),
        "pull_request_target": ("pull_request", "base", "sha"),
        "merge_group": ("merge_group", "base_sha"),
        "push": ("before",),
    }.get(event)
    if keys is None:
        return None
    event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()  # ruff: ignore[banned-api] -- GitHub event boundary.
    if not event_path:
        msg = f"{event} repository analysis requires GITHUB_EVENT_PATH or SARJ_STANDARDS_BASE"
        raise ValueError(msg)
    with Path(event_path).open("rb") as event_file:
        data = event_file.read(_MAX_EVENT_BYTES + 1)
    if len(data) > _MAX_EVENT_BYTES:
        msg = "GitHub event exceeds the 1 MiB repository comparison limit"
        raise ValueError(msg)
    value: object = parse_unique_json(data.decode("utf-8"))
    for key in keys:
        if not is_object_mapping(value) or key not in value:
            msg = f"GitHub {event} event has no exact comparison base"
            raise ValueError(msg)
        value = value[key]
    if not isinstance(value, str):
        msg = f"GitHub {event} comparison base must be a full commit ID"
        raise TypeError(msg)
    return _validated_revision(value)


def _validated_revision(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is None:
        msg = "repository comparison base must be a full lowercase Git commit ID"
        raise ValueError(msg)
    return value


def _selected_path_exists(root: Path, path: Path, *, staged: bool) -> bool:
    git = shutil.which("git")
    if git is None:
        return False
    command = (
        (git, *_GIT_READ_OPTIONS, "ls-files", "--cached", "--", path.as_posix())
        if staged
        else (git, *_GIT_READ_OPTIONS, "ls-tree", "--name-only", "HEAD", "--", path.as_posix())
    )
    selected = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        command,
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return path.as_posix() in selected.stdout.splitlines()
