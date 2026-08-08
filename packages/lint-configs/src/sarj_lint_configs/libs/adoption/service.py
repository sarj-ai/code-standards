"""Plan and apply transactional standards synchronization and adoption."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from sarj_lint_configs._meta import CONFIGS_DIR
from sarj_lint_configs.libs.filesystem import is_link_like

from . import lifecycle, manifest, scaffold, transaction
from .configs import APPLICATION_CONFIG_NAMES, CONFIG_NAMES, PYTHON_CONFIGS


if TYPE_CHECKING:
    from collections.abc import Sequence


_INSTALL_MUTATED_NAMES = frozenset(
    {
        "bun.lock",
        "bun.lockb",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "pyproject.toml",
        "uv.lock",
        "yarn.lock",
    }
)


class SyncOutcome(StrEnum):
    OK = "ok"
    WRITTEN = "written"
    SKIPPED = "skipped"
    DRIFT = "drift"
    INVALID = "invalid"


class _DestinationKind(StrEnum):
    DEFAULT = "default"
    PYTHON = "python"
    TYPESCRIPT = "typescript"


@dataclass(frozen=True, slots=True)
class SyncTarget:
    name: str
    source: Path
    destination: Path


@dataclass(frozen=True, slots=True)
class SyncPlan:
    root: Path
    profile: manifest.Profile
    targets: tuple[SyncTarget, ...]


@dataclass(frozen=True, slots=True)
class SyncRecord:
    target: SyncTarget
    outcome: SyncOutcome


@dataclass(frozen=True, slots=True)
class SyncResult:
    records: tuple[SyncRecord, ...]
    check: bool

    @property
    def status(self) -> int:
        if self.count(SyncOutcome.INVALID):
            return 2
        if self.check and self.count(SyncOutcome.DRIFT):
            return 1
        return 0

    def count(self, outcome: SyncOutcome) -> int:
        return sum(record.outcome is outcome for record in self.records)


class InitFailure(StrEnum):
    SYNC = "sync"
    INSTALL = "install"
    INTERRUPTED = "interrupted"
    APPLY = "apply"


@dataclass(frozen=True, slots=True)
class InitPlan:
    scaffold: scaffold.Plan
    sync: SyncPlan | None
    install_commands: tuple[lifecycle.Command, ...]
    preconditions: dict[Path, bytes | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InitResult:
    status: int
    sync: SyncResult | None = None
    failure: InitFailure | None = None
    error: str | None = None


def plan_sync(
    root: Path,
    *,
    configs: Sequence[str] | None = None,
    python_dest: str | None = None,
    typescript_dest: str | None = None,
    profile: manifest.Profile | None = None,
) -> SyncPlan:
    """Resolve every bundled config source and repository-contained target."""
    resolved = root.resolve()
    if not resolved.is_dir():
        msg = f"destination {resolved} is not a directory"
        raise ValueError(msg)
    adopted = _load_optional_manifest(resolved)
    selected = _selected_configs(configs, adopted)
    selected_profile = profile or (adopted.profile if adopted is not None else "standard")
    destinations: dict[_DestinationKind, Path] = {}

    def destination(kind: _DestinationKind, override: str | None) -> Path:
        if kind not in destinations:
            recorded = None
            if adopted is not None:
                match kind:
                    case _DestinationKind.TYPESCRIPT:
                        recorded = adopted.typescript_dest
                    case _DestinationKind.PYTHON:
                        recorded = adopted.python_dest
                    case _DestinationKind.DEFAULT:
                        pass
            requested = override or (str(resolved) if recorded is None else str(resolved / recorded))
            destinations[kind] = _contained_destination(resolved, requested, label=kind.value)
        return destinations[kind]

    targets: list[SyncTarget] = []
    for name in selected:
        standard_source, target_name = CONFIG_NAMES[name]
        source_name = (
            APPLICATION_CONFIG_NAMES.get(name, standard_source)
            if selected_profile == "application"
            else standard_source
        )
        if name == "eslint":
            base = destination(_DestinationKind.TYPESCRIPT, typescript_dest)
        elif name in PYTHON_CONFIGS:
            base = destination(_DestinationKind.PYTHON, python_dest)
        else:
            base = destination(_DestinationKind.DEFAULT, None)
        targets.append(SyncTarget(name, CONFIGS_DIR / source_name, base / target_name))
    return SyncPlan(resolved, selected_profile, tuple(targets))


def apply_sync(plan: SyncPlan, *, force: bool = False, check: bool = False) -> SyncResult:
    """Apply or check a config synchronization plan without producing output."""
    records = tuple(
        SyncRecord(target, _sync_one(target, root=plan.root, force=force, check=check)) for target in plan.targets
    )
    return SyncResult(records, check)


def plan_init(
    root: Path,
    *,
    force: bool = False,
    configs: Sequence[str] | None = None,
    python_dest: str | None = None,
    typescript_dest: str | None = None,
    profile: manifest.Profile = "standard",
    hook_manager: manifest.HookManager | None = None,
) -> InitPlan:
    """Plan the complete init operation, including configs and installation."""
    if profile not in manifest.PROFILES:
        msg = f"profile must be one of: {', '.join(manifest.PROFILES)}"
        raise ValueError(msg)
    resolved = root.resolve()
    already_adopted = manifest.manifest_path(resolved).is_file()
    scaffold_plan = scaffold.build_plan(
        resolved,
        force=force,
        configs=configs,
        python_dest=python_dest,
        typescript_dest=typescript_dest,
        profile=profile,
        hook_manager=hook_manager,
    )
    if scaffold_plan.errors or (not scaffold_plan.ecosystems.any and configs is None):
        return InitPlan(scaffold_plan, None, ())
    python_target = scaffold.dest_of(resolved, scaffold_plan.ecosystems.python_root)
    typescript_target = scaffold.dest_of(resolved, scaffold_plan.ecosystems.typescript_root)
    sync_plan = plan_sync(
        resolved,
        configs=scaffold_plan.configs,
        python_dest=python_target,
        typescript_dest=typescript_target,
        profile=scaffold_plan.profile,
    )
    if not force and not already_adopted:
        conflicts = tuple(
            target.destination
            for target in sync_plan.targets
            if target.destination.is_file() and target.destination.read_bytes() != target.source.read_bytes()
        )
        if conflicts:
            names = ", ".join(str(path.relative_to(resolved)) for path in conflicts)
            scaffold_plan.errors.append(
                "refusing to overwrite pre-existing lint configuration in an unadopted repository: "
                f"{names}; review the files and rerun with --force"
            )
            return InitPlan(scaffold_plan, None, ())
    mutations = tuple(path for path, _contents in (*scaffold_plan.writes, *scaffold_plan.edits)) + tuple(
        target.destination for target in sync_plan.targets
    )
    transaction.validate_targets(resolved, mutations)
    commands = tuple(
        lifecycle.install_commands(
            resolved,
            scaffold_plan.ecosystems,
            hook_manager=scaffold_plan.hook_manager,
        )
    )
    preconditions = {path: path.read_bytes() if path.is_file() else None for path in mutations}
    return InitPlan(scaffold_plan, sync_plan, commands, preconditions)


def apply_init(plan: InitPlan, *, install: bool = True) -> InitResult:
    """Apply a complete init plan atomically, rolling files back on failure."""
    if plan.sync is None:
        return InitResult(2, failure=InitFailure.APPLY, error="init plan is not applicable")
    try:
        transaction.validate_targets(plan.sync.root, tuple(plan.preconditions))
        stale = any(
            (path.read_bytes() if path.is_file() else None) != expected for path, expected in plan.preconditions.items()
        )
    except OSError as exc:
        return InitResult(2, failure=InitFailure.APPLY, error=str(exc))
    if stale:
        return InitResult(2, failure=InitFailure.APPLY, error="init plan is stale; rerun init")
    scaffold_targets = tuple(path for path, _contents in (*plan.scaffold.writes, *plan.scaffold.edits))
    python_environment = (
        None if plan.scaffold.ecosystems.python_root is None else plan.scaffold.ecosystems.python_root / ".venv"
    )
    typescript_root = plan.scaffold.ecosystems.typescript_install_root or plan.scaffold.ecosystems.typescript_root
    node_modules = None if typescript_root is None else typescript_root / "node_modules"
    generated_trees = tuple((path, path.exists()) for path in (python_environment, node_modules) if path is not None)
    file_transaction: transaction.FileTransaction | None = None
    try:
        file_transaction = transaction.FileTransaction.capture(plan.sync.root, scaffold_targets)
        result = _apply_init_transaction(plan, file_transaction, install=install)
    except KeyboardInterrupt:
        rollback_error = _rollback_error(file_transaction)
        cleanup_error = _cleanup_new_trees(generated_trees, failed=True)
        return InitResult(
            130,
            failure=InitFailure.INTERRUPTED,
            error=_join_errors(rollback_error, cleanup_error),
        )
    except OSError as exc:
        rollback_error = _rollback_error(file_transaction)
        cleanup_error = _cleanup_new_trees(generated_trees, failed=True)
        return InitResult(
            2,
            failure=InitFailure.APPLY,
            error=_join_errors(str(exc), rollback_error, cleanup_error),
        )
    else:
        if result.status:
            rollback_error = _rollback_error(file_transaction)
            cleanup_error = _cleanup_new_trees(generated_trees, failed=True)
            error = _join_errors(result.error, rollback_error, cleanup_error)
            status = 2 if error or result.failure is InitFailure.INSTALL else result.status
            return InitResult(status, result.sync, result.failure, error)
        return result


def _rollback_error(file_transaction: transaction.FileTransaction | None) -> str | None:
    if file_transaction is None:
        return None
    return file_transaction.rollback().render()


def _cleanup_new_trees(trees: tuple[tuple[Path, bool], ...], *, failed: bool) -> str | None:
    if not failed:
        return None
    failures: list[str] = []
    for path, existed in trees:
        if existed or not path.is_dir():
            continue
        try:
            shutil.rmtree(path)
        except OSError as exc:
            failures.append(f"could not remove newly created environment {path}: {exc}")
    return "; ".join(failures) or None


def _join_errors(*errors: str | None) -> str | None:
    return "; ".join(error for error in errors if error) or None


def _apply_init_transaction(
    plan: InitPlan,
    file_transaction: transaction.FileTransaction,
    *,
    install: bool,
) -> InitResult:
    if plan.sync is None:
        return InitResult(2, failure=InitFailure.APPLY, error="init plan is not applicable")
    file_transaction.track(*(target.destination for target in plan.sync.targets))
    sync_result = _apply_planned_sync(plan.sync, plan.preconditions)
    if sync_result.status:
        return InitResult(sync_result.status, sync_result, InitFailure.SYNC)
    scaffold.apply(plan.scaffold, preconditions=plan.preconditions)
    direct_targets = (
        *(target.destination for target in plan.sync.targets),
        *(path for path, _contents in (*plan.scaffold.writes, *plan.scaffold.edits)),
    )
    file_transaction.mark_written(*(path for path in direct_targets if path.name not in _INSTALL_MUTATED_NAMES))
    if install:
        install_status = lifecycle.execute(plan.install_commands)
        if install_status:
            return InitResult(
                2,
                sync_result,
                InitFailure.INSTALL,
                f"dependency or hook installer exited with status {install_status}",
            )
    return InitResult(0, sync_result)


def _apply_planned_sync(plan: SyncPlan, preconditions: dict[Path, bytes | None]) -> SyncResult:
    records: list[SyncRecord] = []
    for target in plan.targets:
        transaction.assert_expected(plan.root, target.destination, preconditions[target.destination])
        records.append(SyncRecord(target, _sync_one(target, root=plan.root, force=True, check=False)))
    return SyncResult(records=tuple(records), check=False)


def init_destination(root: Path, name: str, *, python_dest: str, typescript_dest: str) -> Path:
    """Return the destination of one config in a planned adoption."""
    if name == "eslint":
        base = root / typescript_dest
    elif name in PYTHON_CONFIGS:
        base = root / python_dest
    else:
        base = root
    return base / CONFIG_NAMES[name][1]


def _selected_configs(configs: Sequence[str] | None, adopted: manifest.Manifest | None) -> tuple[str, ...]:
    if configs is not None:
        if isinstance(configs, str):
            msg = "configs must be a sequence of config names, not a string"
            raise TypeError(msg)
        selected = tuple(dict.fromkeys(configs))
        if not selected:
            msg = "configs must contain at least one config name"
            raise ValueError(msg)
        unknown = sorted(set(selected) - set(CONFIG_NAMES))
        if unknown:
            msg = f"unknown configs: {', '.join(unknown)}"
            raise ValueError(msg)
        return selected
    if adopted is not None:
        known = tuple(name for name in adopted.configs if name in CONFIG_NAMES)
        if known:
            return known
    return tuple(CONFIG_NAMES)


def _load_optional_manifest(root: Path) -> manifest.Manifest | None:
    return manifest.load(root)


def _contained_destination(root: Path, requested: str, *, label: str) -> Path:
    candidate = Path(requested)
    destination = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        msg = f"{label} destination {destination} escapes repository root {root}"
        raise ValueError(msg) from exc
    if not destination.is_dir():
        msg = f"{label} destination {destination} is not a directory"
        raise ValueError(msg)
    return destination


def _sync_one(target: SyncTarget, *, root: Path, force: bool, check: bool) -> SyncOutcome:
    destination = target.destination
    if is_link_like(destination):
        if not check:
            return SyncOutcome.INVALID
        try:
            resolved = destination.resolve(strict=True)
            resolved.relative_to(root)
        except OSError, ValueError:
            return SyncOutcome.INVALID
        if not resolved.is_file() or resolved.read_bytes() != target.source.read_bytes():
            return SyncOutcome.DRIFT
        return SyncOutcome.OK
    if destination.exists() and not destination.is_file():
        return SyncOutcome.INVALID
    if destination.is_file() and destination.read_bytes() == target.source.read_bytes():
        return SyncOutcome.OK
    if check:
        return SyncOutcome.DRIFT
    if destination.exists() and not force:
        return SyncOutcome.SKIPPED
    transaction.atomic_write_bytes(root, destination, target.source.read_bytes())
    return SyncOutcome.WRITTEN
