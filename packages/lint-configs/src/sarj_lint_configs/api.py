"""Public API for standards adoption, checking, setup, and release policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- latest updates execute a fixed uvx argv.
from typing import TYPE_CHECKING

from ._meta import (
    CONFIGS_DIR,
    ESLINT_APPLICATION,
    ESLINT_PEERS,
    ESLINT_STRICT,
    MARKDOWNLINT_STRICT,
    PYRIGHT_STRICT,
    RUFF_APPLICATION,
    RUFF_STRICT,
    TAPLO_STRICT,
    YAMLLINT_STRICT,
    __version__,
)
from .libs.adoption.doctor import Finding as DoctorFinding
from .libs.adoption.doctor import Level as DoctorLevel
from .libs.adoption.doctor import diagnose
from .libs.adoption.lifecycle import (
    Command,
    Inspection,
    execute,
    format_commands,
    inspect,
    selected_eslint_commands,
    verification_commands,
)
from .libs.adoption.manifest import Manifest
from .libs.adoption.manifest import load as load_manifest
from .libs.adoption.scaffold import Plan as ScaffoldPlan
from .libs.adoption.scaffold import apply as apply_scaffold
from .libs.adoption.scaffold import build_plan as plan_scaffold
from .libs.adoption.scaffold import detect
from .libs.adoption.service import (
    InitPlan,
    InitResult,
    apply_init,
    apply_sync,
    plan_init,
    plan_sync,
)
from .libs.adoption.service import (
    SyncOutcome as ConfigSyncOutcome,
)
from .libs.adoption.service import (
    SyncPlan as ConfigSyncPlan,
)
from .libs.adoption.service import (
    SyncResult as ConfigSyncResult,
)
from .libs.adoption.upgrade import UpgradePlan, is_install_remediable
from .libs.adoption.upgrade import apply as apply_upgrade
from .libs.adoption.upgrade import build_plan as plan_upgrade
from .libs.diagnostics import (
    ANALYSIS_SCHEMA,
    AnalysisReport,
    Completion,
    Conclusion,
    CoverageNotice,
    Diagnostic,
    ExecutionIssue,
    Location,
    Position,
    Region,
    Severity,
    SourceDocument,
    ToolReport,
    TrustMode,
    to_github,
    to_json,
    to_sarif,
    to_text,
)
from .libs.filesystem import is_link_like
from .libs.linting.analysis import analyze as analyze_paths
from .libs.linting.analysis import report_from_tools
from .libs.linting.external import analyze_external
from .libs.linting.library_policy import Finding as LibraryPolicyFinding
from .libs.linting.library_policy import ManifestPolicyError
from .libs.linting.library_policy import scan as check_library_policy
from .libs.linting.library_policy import scan_paths as check_selected_library_policy
from .libs.linting.runner import GroupedPaths, group_paths
from .libs.linting.runner import run as check
from .libs.linting.textlint import Finding as TextFinding
from .libs.linting.textlint import check_paths as check_text
from .libs.release import (
    PackedArtifact,
    ReleaseAgePolicy,
    ReleaseAgeReport,
    ReleaseTarget,
    TagSyncResult,
    ValidatedReleaseTag,
    changed_release_targets,
    check_lockfile_release_age,
    create_release_tags,
    load_exact_exclusions,
    missing_remote_release_tags,
    pack_typescript,
    publish_target,
    run_typescript_release,
    validate_release_tag,
    verify_package_tarball,
)
from .libs.repository.hooks import run as run_hooks
from .libs.repository.repository import Finding as RepositoryFinding
from .libs.repository.repository import RepositoryPolicy
from .libs.repository.repository import check as check_repository
from .libs.repository.rule_maintenance import SyncResult as LedgerSyncResult
from .libs.repository.rule_maintenance import inventory as rule_inventory
from .libs.repository.rule_maintenance import sync_ledger
from .libs.setup import SetupPlan, apply_setup, plan_setup


if TYPE_CHECKING:
    from collections.abc import Sequence

    from .libs.adoption.manifest import Profile


_INVALID_EXIT = 2
_INTERRUPTED_EXIT = 130
_INVALID_DOCTOR_FINDING_IDS = frozenset(
    {"doctor.manifest.destination", "doctor.config.unknown", "doctor.package-json.invalid"}
)


class Status(StrEnum):
    """Stable outcome shared by every consumer-facing operation."""

    OK = "ok"
    CHANGED = "changed"
    DRIFT = "drift"
    INVALID = "invalid"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class AnalysisMode(StrEnum):
    """Whether analysis follows adopted policy or scans the requested native corpus raw."""

    POLICY = "policy"
    RAW = "raw"


class UpdateTarget(StrEnum):
    """Which compatibility bundle an update should apply."""

    LATEST = "latest"
    INSTALLED = "installed"


@dataclass(frozen=True, slots=True)
class Finding:
    """One normalized diagnostic suitable for automation and presentation."""

    id: str
    level: str
    message: str
    path: str | None = None
    remediation: str | None = None


@dataclass(frozen=True, slots=True)
class Change:
    """One planned or applied repository change."""

    action: str
    description: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class Result:
    """Normalized result returned by the stable consumer facade."""

    status: Status
    findings: tuple[Finding, ...] = ()
    changes: tuple[Change, ...] = ()
    exit_code: int = 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class Standards:
    """Small, state-free facade for one consumer repository."""

    def __init__(self, root: str | Path = ".") -> None:
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            msg = f"repository root {resolved} is not a directory"
            raise ValueError(msg)
        self.root: Path = resolved

    def init(
        self,
        *,
        profile: Profile = "standard",
        configs: Sequence[str] | None = None,
        python_root: str | None = None,
        typescript_root: str | None = None,
        force: bool = False,
        install: bool = True,
        dry_run: bool = False,
    ) -> Result:
        try:
            plan = plan_init(
                self.root,
                profile=profile,
                configs=configs,
                python_dest=python_root,
                typescript_dest=typescript_root,
                force=force,
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return Result(
                Status.INVALID,
                findings=(Finding("init.input.invalid", "error", str(exc)),),
                exit_code=_INVALID_EXIT,
            )
        changes = _init_changes(plan, install=install)
        if plan.scaffold.errors or plan.sync is None:
            detail = "; ".join(plan.scaffold.errors) or "init plan is not applicable"
            return Result(
                Status.INVALID,
                findings=(Finding("init.plan.invalid", "error", detail),),
                changes=changes,
                exit_code=_INVALID_EXIT,
            )
        if dry_run:
            return Result(Status.CHANGED if changes else Status.OK, changes=changes)
        applied = apply_init(plan, install=install)
        findings = (
            ()
            if applied.error is None
            else (
                Finding(
                    f"init.{applied.failure.value if applied.failure is not None else 'apply'}.failed",
                    "error",
                    applied.error,
                ),
            )
        )
        if applied.status:
            status = Status.INTERRUPTED if applied.status == _INTERRUPTED_EXIT else Status.FAILED
            return Result(status, findings, changes, applied.status)
        diagnosed = diagnose(self.root)
        return _operation_result(_doctor_status(diagnosed), changes, findings=_doctor_findings(diagnosed))

    def check(self, paths: Sequence[str] | None = None) -> Result:
        if paths is not None:
            try:
                selected = _contained_paths(self.root, paths)
            except ValueError as exc:
                return Result(
                    Status.INVALID,
                    findings=(Finding("check.input.invalid", "error", str(exc)),),
                    exit_code=_INVALID_EXIT,
                )
            try:
                adopted = load_manifest(self.root)
                policy_findings = (
                    check_selected_library_policy(self.root, selected)
                    if adopted is not None and adopted.profile == "application"
                    else ()
                )
            except (OSError, TypeError, ValueError, ManifestPolicyError) as exc:
                return Result(
                    Status.INVALID,
                    findings=(Finding("check.policy.invalid", "error", str(exc)),),
                    exit_code=_INVALID_EXIT,
                )
            findings = tuple(
                Finding(item.id, "error", item.message, str(item.path), f"use {item.replacement}")
                for item in policy_findings
            )
            source_status = check(selected)
            eslint_status = execute(selected_eslint_commands(self.root, selected))
            return _operation_result(max(source_status, eslint_status, 1 if findings else 0), findings=findings)
        return _operation_result(_verify(self.root))

    def analyze(
        self,
        paths: Sequence[str] | None = None,
        *,
        external: bool = False,
        trust: TrustMode | str = TrustMode.SAFE,
        mode: AnalysisMode | str = AnalysisMode.POLICY,
    ) -> AnalysisReport:
        """Return native source findings through the versioned diagnostic protocol.

        Unlike :meth:`check`, this method never renders analyzer output and keeps
        execution failures separate from code findings. External tool adapters
        can therefore be added without changing the report contract.
        """
        try:
            normalized_trust = TrustMode(trust)
            normalized_mode = AnalysisMode(mode)
        except ValueError as exc:
            return _failed_analysis(self.root, "invalid-input", str(exc))
        try:
            adopted = load_manifest(self.root) if normalized_mode is AnalysisMode.POLICY else None
            selected = _analysis_inputs(self.root, paths, mode=normalized_mode)
        except (OSError, TypeError, ValueError) as exc:
            return _failed_analysis(self.root, "invalid-input", str(exc))
        try:
            selected_groups = group_paths(selected)
        except (OSError, TypeError, ValueError) as exc:
            return _failed_analysis(self.root, "invalid-input", str(exc))
        baseline = None if adopted is None or adopted.python_baseline is None else self.root / adopted.python_baseline
        native = analyze_paths(selected, root=self.root, python_baseline=baseline)
        if adopted is not None and adopted.profile == "application":
            try:
                policy = _policy_report(self.root, selected)
            except (OSError, TypeError, ValueError, ManifestPolicyError) as exc:
                issue = ExecutionIssue("sarj-library-policy", "policy-failure", f"{type(exc).__name__}: {exc}")
                policy = ToolReport("sarj-library-policy", Completion.FAILED, issues=(issue,))
            native = report_from_tools(self.root, (*native.tools, policy))
        coverage: list[CoverageNotice] = []
        routed = {
            *selected_groups.python,
            *selected_groups.sql,
            *selected_groups.iac,
            *selected_groups.text,
            *selected_groups.typescript,
        }
        unsupported = sum(Path(item).is_file() and item not in routed for item in selected)
        if unsupported:
            coverage.append(
                CoverageNotice(
                    "sarj-standards",
                    "no bundled analyzer accepts the selected file type",
                    unsupported,
                )
            )
        if not external:
            if selected_groups.typescript:
                coverage.append(
                    CoverageNotice(
                        "eslint",
                        "native analysis does not run TypeScript; use check or external trusted analysis",
                        len(selected_groups.typescript),
                    )
                )
            return _with_coverage(native, coverage)
        external_reports = analyze_external(selected, root=self.root, trust=normalized_trust)
        if selected_groups.typescript and not any(report.name == "eslint" for report in external_reports):
            issue = ExecutionIssue(
                "eslint", "coverage-missing", "no ESLint project accepted the selected TypeScript files"
            )
            external_reports = (*external_reports, ToolReport("eslint", Completion.FAILED, issues=(issue,)))
        combined = report_from_tools(self.root, (*native.tools, *external_reports))
        return _with_coverage(combined, coverage)

    def fix(self) -> Result:
        return _operation_result(fix(self.root))

    def doctor(self) -> Result:
        diagnosed = diagnose(self.root)
        findings = tuple(
            Finding(item.id, item.level.value, item.detail, item.where, item.remediation) for item in diagnosed
        )
        status = _doctor_status(diagnosed)
        return _operation_result(status, findings=findings)

    def update(
        self,
        *,
        install: bool = True,
        check_only: bool = False,
        target: UpdateTarget | str = UpdateTarget.LATEST,
    ) -> Result:
        try:
            selected_target = UpdateTarget(target)
        except ValueError:
            finding = Finding("update.target.invalid", "error", f"unknown update target {target!r}")
            return Result(Status.INVALID, findings=(finding,), exit_code=_INVALID_EXIT)
        if selected_target is UpdateTarget.LATEST:
            return self._update_latest(install=install, check_only=check_only)
        try:
            plan = plan_upgrade(self.root)
        except (OSError, TypeError, ValueError) as exc:
            return Result(
                Status.INVALID,
                findings=(Finding("update.plan.invalid", "error", str(exc)),),
                exit_code=_INVALID_EXIT,
            )
        planned = tuple(Change("plan", change.reason, change.path) for change in plan.changes)
        if check_only:
            diagnosed = diagnose(self.root)
            findings = _doctor_findings(diagnosed)
            doctor_status = _doctor_status(diagnosed)
            status = doctor_status or (1 if planned else 0)
            return _operation_result(status, planned, findings=findings)
        try:
            applied = apply_upgrade(plan, install=install)
        except KeyboardInterrupt:
            return Result(Status.INTERRUPTED, changes=planned, exit_code=_INTERRUPTED_EXIT)
        except (OSError, TypeError, ValueError) as exc:
            finding = Finding("update.apply.failed", "error", str(exc))
            return Result(Status.FAILED, (finding,), planned, _INVALID_EXIT)
        if applied == _INTERRUPTED_EXIT:
            return Result(Status.INTERRUPTED, changes=planned, exit_code=_INTERRUPTED_EXIT)
        if applied:
            finding = Finding("update.apply.failed", "error", f"upgrade exited with status {applied}")
            return Result(Status.FAILED, (finding,), planned, applied)
        diagnosed = diagnose(self.root)
        if not install:
            diagnosed = [
                DoctorFinding(
                    DoctorLevel.WARN,
                    finding.where,
                    f"{finding.detail}; installation intentionally skipped",
                    finding.id,
                    finding.remediation,
                )
                if finding.level is DoctorLevel.DRIFT and is_install_remediable(finding)
                else finding
                for finding in diagnosed
            ]
        changes = tuple(Change("update", change.reason, change.path) for change in plan.changes)
        return _operation_result(_doctor_status(diagnosed), changes, findings=_doctor_findings(diagnosed))

    def _update_latest(self, *, install: bool, check_only: bool) -> Result:
        executable = shutil.which("uvx")
        if executable is None:
            finding = Finding(
                "update.latest.unavailable",
                "error",
                "uvx is required to resolve the latest standards release; install uv or target='installed'",
            )
            return Result(Status.FAILED, findings=(finding,), exit_code=_INVALID_EXIT)
        command = [
            executable,
            "--refresh",
            "--from",
            "sarj-lint-configs",
            "sarj-standards",
            "update",
            "--offline",
            "--dest",
            str(self.root),
        ]
        if check_only:
            command.append("--check")
        if not install:
            command.append("--no-install")
        environment = dict(os.environ)  # ruff: ignore[banned-api] -- preserve caller environment for the fixed uvx process.
        environment["SARJ_STANDARDS_BOOTSTRAPPED"] = "1"
        try:
            completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed executable and argv.
                command,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            finding = Finding("update.latest.failed", "error", str(exc))
            return Result(Status.FAILED, findings=(finding,), exit_code=_INVALID_EXIT)
        output = (completed.stderr or completed.stdout).strip()
        if completed.returncode == 0:
            status = Status.OK if check_only else Status.CHANGED
            changes = () if check_only else (Change("update", "applied the latest resolved compatibility bundle"),)
            return Result(status, changes=changes)
        if completed.returncode == 1:
            finding = Finding("update.latest.available", "warning", output or "a standards update is available")
            return Result(Status.DRIFT, findings=(finding,), exit_code=1)
        finding = Finding("update.latest.failed", "error", output or "latest standards update failed")
        return Result(Status.FAILED, findings=(finding,), exit_code=completed.returncode)

    def inspect(self) -> Inspection:
        return inspect(self.root)


def _doctor_status(findings: Sequence[DoctorFinding]) -> int:
    if any(finding.id.endswith(".invalid") or finding.id in _INVALID_DOCTOR_FINDING_IDS for finding in findings):
        return _INVALID_EXIT
    return (
        1
        if any(finding.level is DoctorLevel.DRIFT or finding.id == "doctor.manifest.absent" for finding in findings)
        else 0
    )


def _doctor_findings(findings: Sequence[DoctorFinding]) -> tuple[Finding, ...]:
    return tuple(Finding(item.id, item.level.value, item.detail, item.where, item.remediation) for item in findings)


def _verify(root: Path) -> int:
    status = _doctor_status(diagnose(root))
    if status:
        return status
    sync_result = apply_sync(plan_sync(root), check=True)
    if sync_result.status:
        return sync_result.status
    try:
        adopted = load_manifest(root)
    except OSError, TypeError, ValueError:
        return _INVALID_EXIT
    verify_paths = adopted.verify_paths if adopted is not None else (".",)
    if check([str(root / path) for path in verify_paths]):
        return 1
    if adopted is not None and adopted.profile == "application" and check_library_policy(root):
        return 1
    return execute(verification_commands(detect(root)))


def _init_changes(plan: InitPlan, *, install: bool) -> tuple[Change, ...]:
    scaffold = plan.scaffold
    return (
        *(Change("create", "write adoption file", path) for path, _contents in scaffold.writes),
        *(Change("update", "extend adoption file", path) for path, _contents in scaffold.edits),
        *(
            Change(
                "create" if not target.destination.exists() else "update",
                f"sync {target.name} config",
                target.destination,
            )
            for target in (() if plan.sync is None else plan.sync.targets)
            if _sync_target_changes(target.source, target.destination)
        ),
        *(Change("run", command.label) for command in plan.install_commands if install),
    )


def _operation_result(
    exit_code: int,
    changes: tuple[Change, ...] = (),
    *,
    findings: tuple[Finding, ...] = (),
) -> Result:
    if exit_code == 0:
        status = Status.CHANGED if changes else Status.OK
    elif exit_code == 1:
        status = Status.DRIFT
    elif exit_code == _INVALID_EXIT:
        status = Status.INVALID
    elif exit_code == _INTERRUPTED_EXIT:
        status = Status.INTERRUPTED
    else:
        status = Status.FAILED
    return Result(status, findings, changes, exit_code)


def _failed_analysis(root: Path, kind: str, message: str) -> AnalysisReport:
    issue = ExecutionIssue("sarj-standards", kind, message)
    tool = ToolReport("sarj-standards", Completion.FAILED, issues=(issue,))
    return AnalysisReport(root, Completion.FAILED, Conclusion.INCONCLUSIVE, (tool,))


def _with_coverage(report: AnalysisReport, coverage: Sequence[CoverageNotice]) -> AnalysisReport:
    notices = tuple(coverage)
    if not notices:
        return report
    completion = Completion.PARTIAL if report.completion is Completion.COMPLETE else report.completion
    conclusion = report.conclusion if report.diagnostics else Conclusion.INCONCLUSIVE
    return AnalysisReport(report.root, completion, conclusion, report.tools, notices)


def _analysis_inputs(root: Path, paths: Sequence[str] | None, *, mode: AnalysisMode = AnalysisMode.POLICY) -> list[str]:
    if paths is not None:
        return _contained_paths(root, paths)
    if mode is AnalysisMode.RAW:
        return [str(root)]
    adopted = load_manifest(root)
    verify_paths = adopted.verify_paths if adopted is not None else (".",)
    return [str(root / path) for path in verify_paths]


def _policy_report(root: Path, selected: Sequence[str]) -> ToolReport:
    findings = check_selected_library_policy(root, selected)
    documents: dict[Path, SourceDocument] = {}
    diagnostics: list[Diagnostic] = []
    for finding in findings:
        resolved = (root / finding.path).resolve()
        relative = resolved.relative_to(root)
        if resolved not in documents:
            documents[resolved] = SourceDocument.read(resolved)
        position = documents[resolved].point(line=finding.line, column=finding.column)
        diagnostics.append(
            Diagnostic(
                finding.id,
                finding.message,
                Severity.ERROR,
                "sarj-library-policy",
                Location(relative.as_posix(), position=position),
                rule_id=finding.id,
                help=f"Replace {finding.package} with {finding.replacement}",
            )
        )
    return ToolReport("sarj-library-policy", Completion.COMPLETE, diagnostics=tuple(diagnostics))


def initialize(
    root: Path,
    *,
    profile: Profile = "standard",
    configs: Sequence[str] | None = None,
    python_root: str | None = None,
    typescript_root: str | None = None,
    force: bool = False,
    install: bool = True,
) -> InitResult:
    """Adopt standards completely through the same transactional service as the CLI."""
    plan = plan_init(
        _repository_root(root),
        profile=profile,
        configs=configs,
        python_dest=python_root,
        typescript_dest=typescript_root,
        force=force,
    )
    return apply_init(plan, install=install)


def sync_configs(
    root: Path,
    *,
    configs: Sequence[str] | None = None,
    profile: Profile | None = None,
    python_root: str | None = None,
    typescript_root: str | None = None,
    force: bool = False,
    check_only: bool = False,
) -> ConfigSyncResult:
    """Refresh or check bundled configuration files without upgrading dependencies."""
    plan = plan_sync(
        _repository_root(root),
        configs=configs,
        profile=profile,
        python_dest=python_root,
        typescript_dest=typescript_root,
    )
    return apply_sync(plan, force=force, check=check_only)


def update(root: Path, *, install: bool = True) -> int:
    """Apply the executing package's coherent upgrade plan."""
    resolved = _repository_root(root)
    return apply_upgrade(plan_upgrade(resolved), install=install)


def fix(root: Path) -> int:
    """Apply safe formatters and lint fixes to one detected repository."""
    resolved = root.resolve()
    return execute(format_commands(detect(resolved)))


check_rules = check


def doctor(root: Path) -> list[DoctorFinding]:
    """Diagnose an existing repository through the same root contract as the facade."""
    return diagnose(_repository_root(root))


def show_state(root: Path) -> Inspection:
    """Inspect an existing repository through the same root contract as the facade."""
    return inspect(_repository_root(root))


def _repository_root(root: str | Path) -> Path:
    resolved = Path(root).resolve()
    if not resolved.is_dir():
        msg = f"repository root {resolved} is not a directory"
        raise ValueError(msg)
    return resolved


def _contained_paths(root: Path, paths: Sequence[str]) -> list[str]:
    selected: list[str] = []
    for raw in paths:
        supplied = Path(raw)
        candidate = supplied if supplied.is_absolute() else root / supplied
        try:
            relative = candidate.absolute().relative_to(root)
        except ValueError as exc:
            msg = f"input must exist inside repository root: {raw}"
            raise ValueError(msg) from exc
        cursor = root
        if any(is_link_like(cursor := cursor / part) for part in relative.parts):
            msg = f"input must not traverse a symlink: {raw}"
            raise ValueError(msg)
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root) or not resolved.exists():
            msg = f"input must exist inside repository root: {raw}"
            raise ValueError(msg)
        selected.append(str(resolved))
    return list(dict.fromkeys(selected))


def _sync_target_changes(source: Path, destination: Path) -> bool:
    try:
        return not destination.is_file() or source.read_bytes() != destination.read_bytes()
    except OSError:
        return True


__all__ = [
    "ANALYSIS_SCHEMA",
    "CONFIGS_DIR",
    "ESLINT_APPLICATION",
    "ESLINT_PEERS",
    "ESLINT_STRICT",
    "MARKDOWNLINT_STRICT",
    "PYRIGHT_STRICT",
    "RUFF_APPLICATION",
    "RUFF_STRICT",
    "TAPLO_STRICT",
    "YAMLLINT_STRICT",
    "AnalysisMode",
    "AnalysisReport",
    "Change",
    "Command",
    "Completion",
    "Conclusion",
    "ConfigSyncOutcome",
    "ConfigSyncPlan",
    "ConfigSyncResult",
    "CoverageNotice",
    "Diagnostic",
    "DoctorFinding",
    "DoctorLevel",
    "ExecutionIssue",
    "Finding",
    "GroupedPaths",
    "InitPlan",
    "InitResult",
    "Inspection",
    "LedgerSyncResult",
    "LibraryPolicyFinding",
    "Location",
    "Manifest",
    "PackedArtifact",
    "Position",
    "Region",
    "ReleaseAgePolicy",
    "ReleaseAgeReport",
    "ReleaseTarget",
    "RepositoryFinding",
    "RepositoryPolicy",
    "Result",
    "ScaffoldPlan",
    "SetupPlan",
    "Severity",
    "SourceDocument",
    "Standards",
    "Status",
    "TagSyncResult",
    "TextFinding",
    "ToolReport",
    "TrustMode",
    "UpdateTarget",
    "UpgradePlan",
    "ValidatedReleaseTag",
    "__version__",
    "analyze_paths",
    "apply_init",
    "apply_scaffold",
    "apply_setup",
    "apply_sync",
    "apply_upgrade",
    "changed_release_targets",
    "check",
    "check_library_policy",
    "check_lockfile_release_age",
    "check_repository",
    "check_rules",
    "check_text",
    "create_release_tags",
    "diagnose",
    "doctor",
    "fix",
    "group_paths",
    "initialize",
    "inspect",
    "load_exact_exclusions",
    "load_manifest",
    "missing_remote_release_tags",
    "pack_typescript",
    "plan_init",
    "plan_scaffold",
    "plan_setup",
    "plan_sync",
    "plan_upgrade",
    "publish_target",
    "rule_inventory",
    "run_hooks",
    "run_typescript_release",
    "show_state",
    "sync_configs",
    "sync_ledger",
    "to_github",
    "to_json",
    "to_sarif",
    "to_text",
    "update",
    "validate_release_tag",
    "verify_package_tarball",
]
