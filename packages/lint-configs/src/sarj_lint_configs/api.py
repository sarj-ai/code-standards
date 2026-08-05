"""Public API for standards adoption, checking, setup, and release policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
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
from .libs.adoption.lifecycle import Command, Inspection, execute, format_commands, inspect, verification_commands
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
from .libs.adoption.upgrade import UpgradePlan
from .libs.adoption.upgrade import apply as apply_upgrade
from .libs.adoption.upgrade import build_plan as plan_upgrade
from .libs.linting.library_policy import Finding as LibraryPolicyFinding
from .libs.linting.library_policy import scan as check_library_policy
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


class Status(StrEnum):
    """Stable outcome shared by every consumer-facing operation."""

    OK = "ok"
    CHANGED = "changed"
    DRIFT = "drift"
    INVALID = "invalid"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


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
        plan = plan_init(
            self.root,
            profile=profile,
            configs=configs,
            python_dest=python_root,
            typescript_dest=typescript_root,
            force=force,
        )
        changes = _init_changes(plan, install=install)
        if dry_run:
            return Result(Status.CHANGED if changes else Status.OK, changes=changes)
        applied = apply_init(plan, install=install)
        return _operation_result(applied.status, changes)

    def check(self, paths: Sequence[str] | None = None) -> Result:
        if paths is not None:
            return _operation_result(check([str(self.root / path) for path in paths]))
        return _operation_result(_verify(self.root))

    def fix(self) -> Result:
        return _operation_result(fix(self.root))

    def doctor(self) -> Result:
        diagnosed = diagnose(self.root)
        findings = tuple(
            Finding(item.id, item.level.value, item.detail, item.where, item.remediation) for item in diagnosed
        )
        status = _doctor_status(diagnosed)
        return _operation_result(status, findings=findings)

    def update(self, *, install: bool = True, check_only: bool = False) -> Result:
        plan = plan_upgrade(self.root)
        changes = tuple(Change("update", change.reason, change.path) for change in plan.changes)
        if check_only:
            doctor_status = _doctor_status(diagnose(self.root))
            status = doctor_status or (1 if changes else 0)
            return _operation_result(status, changes)
        return _operation_result(apply_upgrade(plan, install=install), changes)

    def inspect(self) -> Inspection:
        return inspect(self.root)


def _doctor_status(findings: Sequence[DoctorFinding]) -> int:
    if any(finding.id.endswith(".invalid") for finding in findings):
        return _INVALID_EXIT
    return 1 if any(finding.level is DoctorLevel.DRIFT for finding in findings) else 0


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
        root,
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
        root,
        configs=configs,
        profile=profile,
        python_dest=python_root,
        typescript_dest=typescript_root,
    )
    return apply_sync(plan, force=force, check=check_only)


def update(root: Path, *, install: bool = True) -> int:
    """Apply the executing package's coherent upgrade plan."""
    return apply_upgrade(plan_upgrade(root), install=install)


def fix(root: Path) -> int:
    """Apply safe formatters and lint fixes to one detected repository."""
    resolved = root.resolve()
    return execute(format_commands(detect(resolved)))


check_rules = check
doctor = diagnose
show_state = inspect

__all__ = [
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
    "Change",
    "Command",
    "ConfigSyncOutcome",
    "ConfigSyncPlan",
    "ConfigSyncResult",
    "DoctorFinding",
    "DoctorLevel",
    "Finding",
    "GroupedPaths",
    "InitPlan",
    "InitResult",
    "Inspection",
    "LedgerSyncResult",
    "LibraryPolicyFinding",
    "Manifest",
    "PackedArtifact",
    "ReleaseAgePolicy",
    "ReleaseAgeReport",
    "ReleaseTarget",
    "RepositoryFinding",
    "RepositoryPolicy",
    "Result",
    "ScaffoldPlan",
    "SetupPlan",
    "Standards",
    "Status",
    "TagSyncResult",
    "TextFinding",
    "UpgradePlan",
    "ValidatedReleaseTag",
    "__version__",
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
    "update",
    "validate_release_tag",
    "verify_package_tarball",
]
