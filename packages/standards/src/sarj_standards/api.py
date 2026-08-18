from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import os
from pathlib import Path
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- latest updates execute a fixed uvx argv.
from typing import TYPE_CHECKING

from ._meta import (
    __version__,
)
from .libs.adoption import launcher
from .libs.adoption.doctor import Finding as DoctorFinding
from .libs.adoption.doctor import Level as DoctorLevel
from .libs.adoption.doctor import diagnose
from .libs.adoption.lifecycle import (
    Inspection,
    execute,
    inspect,
    selected_eslint_commands,
    verification_commands,
)
from .libs.adoption.manifest import load as load_manifest
from .libs.adoption.scaffold import detect
from .libs.adoption.service import (
    InitPlan,
    apply_init,
    apply_sync,
    plan_init,
    plan_sync,
)
from .libs.diagnostics import (
    AnalysisReport,
    Completion,
    Conclusion,
    CoverageDisposition,
    CoverageNotice,
    Diagnostic,
    ExecutionIssue,
    Fix,
    FixSafety,
    Location,
    Position,
    Region,
    RelatedLocation,
    Severity,
    SourceDocument,
    TextEdit,
    ToolReport,
    TrustMode,
    to_github,
    to_json,
    to_sarif,
    to_text,
)
from .libs.diagnostics import baseline as diagnostic_baseline
from .libs.filesystem import is_link_like
from .libs.linting.analysis import analyze as analyze_paths
from .libs.linting.analysis import report_from_tools
from .libs.linting.external import analyze_external
from .libs.linting.library_policy import ManifestPolicyError
from .libs.linting.library_policy import accepts_path as library_policy_accepts_path
from .libs.linting.library_policy import scan as check_library_policy
from .libs.linting.library_policy import scan_paths as check_selected_library_policy
from .libs.linting.policy import Policy
from .libs.linting.runner import group_paths
from .libs.linting.runner import run as check
from .libs.rules import RuleEngine, RuleId, RuleSelection, RuleSelector


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
    CORPUS = "corpus"
    OBSERVE = "observe"
    RAW = "raw"


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    level: str
    message: str
    path: str | None = None
    remediation: str | None = None


@dataclass(frozen=True, slots=True)
class Change:
    action: str
    description: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class Result:
    status: Status
    findings: tuple[Finding, ...] = ()
    changes: tuple[Change, ...] = ()
    exit_code: int = 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class Standards:
    def __init__(self, root: str | Path = ".") -> None:
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            msg = f"repository root {resolved} is not a directory"
            raise ValueError(msg)
        self.root: Path = resolved

    def setup(
        self,
        *,
        profile: Profile | None = None,
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
                findings=(Finding("setup.input.invalid", "error", str(exc)),),
                exit_code=_INVALID_EXIT,
            )
        changes = _init_changes(plan, install=install)
        if plan.scaffold.errors or plan.sync is None:
            detail = "; ".join(plan.scaffold.errors) or "setup plan is not applicable"
            return Result(
                Status.INVALID,
                findings=(Finding("setup.plan.invalid", "error", detail),),
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
                    f"setup.{applied.failure.value if applied.failure is not None else 'apply'}.failed",
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
                policy = Policy.from_manifest(self.root, adopted)
                selected = list(policy.filter_paths(selected))
            except (OSError, TypeError, ValueError, ManifestPolicyError) as exc:
                return Result(
                    Status.INVALID,
                    findings=(Finding("check.policy.invalid", "error", str(exc)),),
                    exit_code=_INVALID_EXIT,
                )
            try:
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
            source_status = check(selected, policy=policy)
            eslint_status = execute(selected_eslint_commands(self.root, selected))
            return _operation_result(max(source_status, eslint_status, 1 if findings else 0), findings=findings)
        return _operation_result(_verify(self.root))

    def analyze(  # ruff: ignore[too-many-locals] -- one boundary coordinates routing, policy, and coverage.
        self,
        paths: Sequence[str] | None = None,
        *,
        external: bool = False,
        trust: TrustMode | str = TrustMode.SAFE,
        mode: AnalysisMode | str = AnalysisMode.POLICY,
        rules: Sequence[str | RuleSelector] | None = None,
        staged: bool = False,
    ) -> AnalysisReport:
        try:
            normalized_trust = TrustMode(trust)
            normalized_mode = AnalysisMode(mode)
        except ValueError as exc:
            return _failed_analysis(self.root, "invalid-input", str(exc))
        try:
            adopted = load_manifest(self.root) if normalized_mode is not AnalysisMode.RAW else None
            selection_policy = (
                Policy.corpus_from_manifest(self.root, adopted)
                if normalized_mode is AnalysisMode.CORPUS
                else (
                    Policy.observe_from_manifest(self.root, adopted)
                    if normalized_mode is AnalysisMode.OBSERVE
                    else Policy.from_manifest(self.root, adopted)
                )
            )
            rule_selection = _rule_selection(rules)
            selected = _analysis_inputs(self.root, paths, mode=normalized_mode)
        except (OSError, TypeError, ValueError) as exc:
            return _failed_analysis(self.root, "invalid-input", str(exc))
        try:
            baseline_counts: dict[str, int]
            baseline_counts = (
                diagnostic_baseline.load(self.root / adopted.diagnostic_baseline)
                if normalized_mode is AnalysisMode.POLICY
                and adopted is not None
                and adopted.diagnostic_baseline is not None
                else {}
            )
        except (OSError, TypeError, ValueError) as exc:
            return _failed_analysis(self.root, "baseline-failure", str(exc))
        try:
            active_selected = list(selection_policy.filter_paths(selected))
            selected_groups = group_paths(active_selected, policy=selection_policy)
        except (OSError, TypeError, ValueError) as exc:
            return _failed_analysis(self.root, "invalid-input", str(exc))
        native = analyze_paths(
            active_selected,
            root=self.root,
            policy=selection_policy,
            grouped=selected_groups,
            rule_selection=rule_selection,
        )
        if adopted is not None and adopted.profile == "application" and rule_selection is None:
            try:
                policy = _filter_tool_report(_policy_report(self.root, active_selected), selection_policy)
            except (OSError, TypeError, ValueError, ManifestPolicyError) as exc:
                issue = ExecutionIssue("sarj-library-policy", "policy-failure", f"{type(exc).__name__}: {exc}")
                policy = ToolReport("sarj-library-policy", Completion.FAILED, issues=(issue,))
            native = report_from_tools(self.root, (*native.tools, policy))
        coverage: list[CoverageNotice] = []
        excluded = sum(Path(item).is_file() and item not in active_selected for item in selected)
        if excluded:
            coverage.append(
                CoverageNotice(
                    "sarj-standards",
                    "excluded by repository policy",
                    excluded,
                    CoverageDisposition.EXCLUDED,
                )
            )
        routed = _routed_for_selection(selected_groups, rule_selection)
        if adopted is not None and adopted.profile == "application":
            routed.update(
                item
                for item in active_selected
                if Path(item).is_file() and library_policy_accepts_path(Path(item), self.root)
            )
        unsupported = sum(Path(item).is_file() and item not in routed for item in active_selected)
        if unsupported:
            coverage.append(
                CoverageNotice(
                    "sarj-standards",
                    "no bundled analyzer accepts the selected file type",
                    unsupported,
                )
            )
        if not external:
            if selected_groups.typescript and (rule_selection is None or RuleEngine.ESLINT in rule_selection.engines):
                eslint_enabled = adopted is None or "eslint" in adopted.configs
                coverage.append(
                    CoverageNotice(
                        "eslint",
                        (
                            "native analysis does not run TypeScript; use check or external trusted analysis"
                            if eslint_enabled
                            else "disabled by repository capabilities"
                        ),
                        len(selected_groups.typescript),
                        CoverageDisposition.FAILED if eslint_enabled else CoverageDisposition.NOT_REQUESTED,
                    )
                )
            if normalized_mode in {AnalysisMode.POLICY, AnalysisMode.OBSERVE}:
                native = _with_warning_severity(native, _warning_rule_keys())
            return _with_coverage(_without_baselined_diagnostics(native, baseline_counts), coverage)
        if selected_groups.typescript and adopted is not None and "eslint" not in adopted.configs:
            coverage.append(
                CoverageNotice(
                    "eslint",
                    "disabled by repository capabilities",
                    len(selected_groups.typescript),
                    CoverageDisposition.NOT_REQUESTED,
                )
            )
        run_eslint = rule_selection is None or RuleEngine.ESLINT in rule_selection.engines
        external_reports = (
            (
                analyze_external(
                    active_selected,
                    root=self.root,
                    trust=normalized_trust,
                    policy=selection_policy,
                    capabilities=(frozenset({"eslint"}) if rule_selection is not None else frozenset(adopted.configs)),
                    grouped=selected_groups,
                    include_react_doctor=(paths is None or staged) and rule_selection is None,
                    react_doctor_staged=staged,
                )
                if adopted is not None
                else analyze_external(
                    active_selected,
                    root=self.root,
                    trust=normalized_trust,
                    grouped=selected_groups,
                    include_react_doctor=(paths is None or staged) and rule_selection is None,
                    react_doctor_staged=staged,
                )
            )
            if run_eslint
            else ()
        )
        if rule_selection is not None:
            external_reports = tuple(_filter_report_selectors(report, rule_selection) for report in external_reports)
        if (
            selected_groups.typescript
            and run_eslint
            and (adopted is None or "eslint" in adopted.configs)
            and not any(report.name == "eslint" for report in external_reports)
        ):
            issue = ExecutionIssue(
                "eslint", "coverage-missing", "no ESLint project accepted the selected TypeScript files"
            )
            external_reports = (*external_reports, ToolReport("eslint", Completion.FAILED, issues=(issue,)))
        combined = report_from_tools(self.root, (*native.tools, *external_reports))
        if normalized_mode in {AnalysisMode.POLICY, AnalysisMode.OBSERVE}:
            combined = _with_warning_severity(combined, _warning_rule_keys())
        return _with_coverage(_without_baselined_diagnostics(combined, baseline_counts), coverage)

    def run(
        self,
        paths: Sequence[str] | None = None,
        *,
        external: bool = False,
        trust: TrustMode | str = TrustMode.SAFE,
        mode: AnalysisMode | str = AnalysisMode.POLICY,
        rules: Sequence[str | RuleSelector] | None = None,
        staged: bool = False,
    ) -> AnalysisReport:
        return self.analyze(paths, external=external, trust=trust, mode=mode, rules=rules, staged=staged)

    def fix(self) -> Result:
        from .libs.adoption import (  # ruff: ignore[import-outside-top-level] -- selected operation only
            lifecycle,
            scaffold,
        )

        try:
            adopted = load_manifest(self.root)
            ecosystems = scaffold.detect(self.root) if adopted is None else scaffold.detect_adopted(self.root, adopted)
        except (OSError, TypeError, ValueError) as exc:
            return Result(
                Status.INVALID,
                findings=(Finding("fix.input.invalid", "error", str(exc)),),
                exit_code=_INVALID_EXIT,
            )
        return _operation_result(lifecycle.execute(lifecycle.format_commands(ecosystems)))

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
        version: str | None = None,
        offline: bool = False,
        install: bool = True,
        check_only: bool = False,
    ) -> Result:
        return self._update_target(version=version, offline=offline, install=install, check_only=check_only)

    def _update_target(self, *, version: str | None, offline: bool, install: bool, check_only: bool) -> Result:
        executable = shutil.which("uvx")
        if executable is None:
            finding = Finding(
                "update.latest.unavailable",
                "error",
                "uvx is required to resolve the latest Standards release; install uv and retry",
            )
            return Result(Status.FAILED, findings=(finding,), exit_code=_INVALID_EXIT)
        try:
            launch_argv = launcher.argv(executable=executable, version=version, refresh=not offline)
        except ValueError as exc:
            finding = Finding("update.version.invalid", "error", str(exc))
            return Result(Status.INVALID, findings=(finding,), exit_code=_INVALID_EXIT)
        command = [
            *launch_argv,
            "--root",
            str(self.root),
            "update",
            "--offline",
        ]
        if version is not None:
            command.extend(("--to", version))
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
            )
        except OSError as exc:
            finding = Finding("update.latest.failed", "error", str(exc))
            return Result(Status.FAILED, findings=(finding,), exit_code=_INVALID_EXIT)
        output = (completed.stderr or completed.stdout).strip()
        if completed.returncode == 0:
            status = Status.OK if check_only else Status.CHANGED
            changes = () if check_only else (Change("update", "applied the latest coherent Standards bundle"),)
            return Result(status, changes=changes)
        if completed.returncode == 1:
            if check_only:
                finding = Finding("update.latest.available", "warning", output or "a standards update is available")
                return Result(Status.DRIFT, findings=(finding,), exit_code=1)
            finding = Finding(
                "update.latest.failed",
                "error",
                output or "the latest standards update did not converge; tracked configuration files were restored",
            )
            return Result(Status.FAILED, findings=(finding,), exit_code=1)
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
    policy = Policy.from_manifest(root, adopted)
    if check(
        [str(root / path) for path in verify_paths],
        policy=policy,
    ):
        return 1
    if adopted is not None and adopted.profile == "application" and check_library_policy(root):
        return 1
    return execute(verification_commands(detect(root)))


def _init_changes(plan: InitPlan, *, install: bool) -> tuple[Change, ...]:
    scaffold = plan.scaffold
    return (
        *(Change("create", "write adoption file", path) for path, _contents in scaffold.writes),
        *(Change("update", "extend adoption file", path) for path, _contents in scaffold.edits),
        *(Change("delete", "remove retired repository launcher", path) for path in scaffold.deletes),
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


def _without_baselined_diagnostics(report: AnalysisReport, counts: dict[str, int]) -> AnalysisReport:
    if not counts:
        return report
    remaining = counts.copy()

    def active(diagnostic: Diagnostic) -> bool:
        if not diagnostic_baseline.is_baselineable(diagnostic) or diagnostic.code == "SARJ206":
            return True
        fingerprint = diagnostic.fingerprint
        budget = 0 if fingerprint is None else remaining.get(fingerprint, 0)
        if budget < 1 or fingerprint is None:
            return True
        remaining[fingerprint] = budget - 1
        return False

    tools = tuple(
        ToolReport(
            item.name,
            item.completion,
            diagnostics=tuple(diagnostic for diagnostic in item.diagnostics if active(diagnostic)),
            issues=item.issues,
            analyzer_id=item.analyzer_id,
            invocation_id=item.invocation_id,
            version=item.version,
            duration_ms=item.duration_ms,
            file_count=item.file_count,
            cache_status=item.cache_status,
        )
        for item in report.tools
    )
    return report_from_tools(report.root, tools)


def _with_coverage(report: AnalysisReport, coverage: Sequence[CoverageNotice]) -> AnalysisReport:
    notices = tuple(coverage)
    if not notices:
        return report
    blocking = any(item.blocking for item in notices)
    completion = Completion.PARTIAL if blocking and report.completion is Completion.COMPLETE else report.completion
    conclusion = report.conclusion if report.diagnostics or not blocking else Conclusion.INCONCLUSIVE
    return AnalysisReport(report.root, completion, conclusion, report.tools, notices)


def _analysis_inputs(root: Path, paths: Sequence[str] | None, *, mode: AnalysisMode = AnalysisMode.POLICY) -> list[str]:
    if paths is not None:
        selected = _contained_paths(root, paths)
        return selected if mode is AnalysisMode.RAW else _with_tracked_terraform_tests(root, selected)
    if mode is AnalysisMode.RAW:
        return [str(root)]
    adopted = load_manifest(root)
    verify_paths = adopted.verify_paths if adopted is not None else (".",)
    return _with_tracked_terraform_tests(root, [str(root / path) for path in verify_paths])


def _with_tracked_terraform_tests(root: Path, selected: list[str]) -> list[str]:
    git = shutil.which("git")
    if git is None:
        return selected
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed git argv.
        (git, "-C", str(root), "ls-files", "-z"),
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        return selected
    tracked = [
        str(root / item)
        for item in completed.stdout.decode("utf-8", errors="replace").split("\0")
        if item.casefold().endswith((".tftest.hcl", ".tftest.json"))
    ]
    return list(dict.fromkeys((*selected, *tracked)))


def _rule_selection(values: Sequence[str | RuleSelector] | None) -> RuleSelection | None:
    if values is None:
        return None
    if isinstance(values, str):
        msg = "rules must be a sequence of canonical selectors, not one string"
        raise TypeError(msg)
    from sarj_standards.libs.repository import rule_catalog_artifact  # ruff: ignore[import-outside-top-level]

    catalog = rule_catalog_artifact.load()
    raw_rules = _object_list(catalog.get("rules"), "shipped rule catalog rules")
    live: set[RuleSelector] = set()
    for value in raw_rules:
        key: object = value.get("key") if isinstance(value, dict) else None  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        if isinstance(key, str):
            live.add(RuleSelector.parse(key))
    selected: set[RuleSelector] = set()
    for value in values:
        selector = value if isinstance(value, RuleSelector) else RuleSelector.parse(value)
        if selector not in live:
            msg = f"unknown or invalid rule selector: {value}"
            raise ValueError(msg)
        selected.add(selector)
    return RuleSelection(frozenset(selected))


def _routed_for_selection(grouped: object, selected: RuleSelection | None) -> set[str]:
    from sarj_standards.libs.linting.runner import GroupedPaths  # ruff: ignore[import-outside-top-level]

    if not isinstance(grouped, GroupedPaths):
        msg = "analysis routing has an invalid internal type"
        raise TypeError(msg)
    engines = frozenset(RuleEngine) if selected is None else selected.engines
    routed: set[str] = set()
    if RuleEngine.PYTHON in engines:
        routed.update(grouped.python)
    if RuleEngine.SQL in engines:
        routed.update(grouped.sql)
    if RuleEngine.IAC in engines:
        routed.update(grouped.iac)
    if RuleEngine.TEXT in engines:
        routed.update(grouped.text)
    if RuleEngine.ESLINT in engines:
        routed.update(grouped.typescript)
    return routed


def _filter_report_selectors(
    report: ToolReport,
    selected: RuleSelection,
) -> ToolReport:
    engine = RuleEngine.ESLINT if report.name == "eslint" else None
    allowed: frozenset[str] = frozenset() if engine is None else selected.native_ids_for(engine)
    return ToolReport(
        report.name,
        report.completion,
        diagnostics=tuple(item for item in report.diagnostics if item.rule_id in allowed),
        issues=report.issues,
        analyzer_id=report.analyzer_id,
        invocation_id=report.invocation_id,
        version=report.version,
        duration_ms=report.duration_ms,
        file_count=report.file_count,
        cache_status=report.cache_status,
    )


def _warning_rule_keys() -> frozenset[RuleSelector]:
    from sarj_standards.libs.linting.policy import (  # ruff: ignore[import-outside-top-level]
        warning_selectors,
    )

    return warning_selectors()


def _with_warning_severity(report: AnalysisReport, selectors: frozenset[RuleSelector]) -> AnalysisReport:
    if not selectors:
        return report
    tools = tuple(
        ToolReport(
            tool.name,
            tool.completion,
            diagnostics=tuple(
                replace(item, severity=Severity.WARNING) if _selector_for_diagnostic(item) in selectors else item
                for item in tool.diagnostics
            ),
            issues=tool.issues,
            analyzer_id=tool.analyzer_id,
            invocation_id=tool.invocation_id,
            version=tool.version,
            duration_ms=tool.duration_ms,
            file_count=tool.file_count,
            cache_status=tool.cache_status,
        )
        for tool in report.tools
    )
    return report_from_tools(report.root, tools)


def _selector_for_diagnostic(item: Diagnostic) -> RuleSelector | None:
    engine = _engine_for_diagnostic(item)
    if engine is None:
        return None
    identity = item.rule_id or item.code
    if engine is RuleEngine.ESLINT and identity.startswith("@sarj/"):
        identity = identity.removeprefix("@sarj/")
    try:
        return RuleSelector(engine, RuleId(identity))
    except ValueError:
        return None


def _engine_for_diagnostic(item: Diagnostic) -> RuleEngine | None:
    return {
        "sarj-python-lint": RuleEngine.PYTHON,
        "sarj-sql-lint": RuleEngine.SQL,
        "sarj-iac-lint": RuleEngine.IAC,
        "sarj-text-lint": RuleEngine.TEXT,
        "python": RuleEngine.PYTHON,
        "sql": RuleEngine.SQL,
        "iac": RuleEngine.IAC,
        "text": RuleEngine.TEXT,
        "eslint": RuleEngine.ESLINT,
    }.get(item.source)


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


def _filter_tool_report(report: ToolReport, policy: Policy) -> ToolReport:
    return ToolReport(
        report.name,
        report.completion,
        diagnostics=policy.filter_diagnostics(report.diagnostics),
        issues=report.issues,
        analyzer_id=report.analyzer_id,
        invocation_id=report.invocation_id,
        version=report.version,
        duration_ms=report.duration_ms,
        file_count=report.file_count,
        cache_status=report.cache_status,
    )


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


def _object_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        msg = f"{label} must be an array"
        raise TypeError(msg)
    return value  # pyright: ignore[reportUnknownVariableType]


__all__ = [
    "AnalysisMode",
    "AnalysisReport",
    "Change",
    "Completion",
    "Conclusion",
    "CoverageNotice",
    "Diagnostic",
    "ExecutionIssue",
    "Finding",
    "Fix",
    "FixSafety",
    "Location",
    "Position",
    "Region",
    "RelatedLocation",
    "Result",
    "Severity",
    "Standards",
    "Status",
    "TextEdit",
    "ToolReport",
    "TrustMode",
    "__version__",
    "to_github",
    "to_json",
    "to_sarif",
    "to_text",
]
