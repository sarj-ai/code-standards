"""Plan and apply transactional standards synchronization and adoption."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from sarj_lint_configs._meta import CONFIGS_DIR

from . import lifecycle, manifest, scaffold, transaction
from .configs import APPLICATION_CONFIG_NAMES, CONFIG_NAMES, PYTHON_CONFIGS


if TYPE_CHECKING:
    from collections.abc import Sequence


class SyncOutcome(StrEnum):
    OK = "ok"
    WRITTEN = "written"
    SKIPPED = "skipped"
    DRIFT = "drift"
    INVALID = "invalid"


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
    destinations: dict[str, Path] = {}

    def destination(kind: str, override: str | None) -> Path:
        if kind not in destinations:
            recorded = None
            if adopted is not None:
                recorded = adopted.typescript_dest if kind == "typescript" else adopted.python_dest
            requested = override or (str(resolved) if recorded is None else str(resolved / recorded))
            destinations[kind] = _contained_destination(resolved, requested, label=kind)
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
            base = destination("typescript", typescript_dest)
        elif name in PYTHON_CONFIGS:
            base = destination("python", python_dest)
        else:
            base = destination("default", None)
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
) -> InitPlan:
    """Plan the complete init operation, including configs and installation."""
    resolved = root.resolve()
    scaffold_plan = scaffold.build_plan(
        resolved,
        force=force,
        configs=configs,
        python_dest=python_dest,
        typescript_dest=typescript_dest,
        profile=profile,
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
    mutations = tuple(path for path, _contents in (*scaffold_plan.writes, *scaffold_plan.edits)) + tuple(
        target.destination for target in sync_plan.targets
    )
    transaction.validate_targets(resolved, mutations)
    commands = tuple(lifecycle.install_commands(resolved, scaffold_plan.ecosystems))
    return InitPlan(scaffold_plan, sync_plan, commands)


def apply_init(plan: InitPlan, *, install: bool = True) -> InitResult:
    """Apply a complete init plan atomically, rolling files back on failure."""
    if plan.sync is None:
        return InitResult(2, failure=InitFailure.APPLY, error="init plan is not applicable")
    scaffold_targets = tuple(path for path, _contents in (*plan.scaffold.writes, *plan.scaffold.edits))
    file_transaction: transaction.FileTransaction | None = None
    try:
        file_transaction = transaction.FileTransaction.capture(plan.sync.root, scaffold_targets)
        return _apply_init_transaction(plan, file_transaction, install=install)
    except KeyboardInterrupt:
        if file_transaction is not None:
            file_transaction.rollback()
        return InitResult(130, failure=InitFailure.INTERRUPTED)
    except OSError as exc:
        if file_transaction is not None:
            file_transaction.rollback()
        return InitResult(2, failure=InitFailure.APPLY, error=str(exc))


def _apply_init_transaction(
    plan: InitPlan,
    file_transaction: transaction.FileTransaction,
    *,
    install: bool,
) -> InitResult:
    if plan.sync is None:
        return InitResult(2, failure=InitFailure.APPLY, error="init plan is not applicable")
    file_transaction.track(*(target.destination for target in plan.sync.targets))
    sync_result = apply_sync(plan.sync, force=True)
    if sync_result.status:
        file_transaction.rollback()
        return InitResult(sync_result.status, sync_result, InitFailure.SYNC)
    scaffold.apply(plan.scaffold)
    if install:
        install_status = lifecycle.execute(plan.install_commands)
        if install_status:
            file_transaction.rollback()
            return InitResult(install_status, sync_result, InitFailure.INSTALL)
    return InitResult(0, sync_result)


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
    if configs:
        return tuple(dict.fromkeys(configs))
    if adopted is not None:
        known = tuple(name for name in adopted.configs if name in CONFIG_NAMES)
        if known:
            return known
    return tuple(CONFIG_NAMES)


def _load_optional_manifest(root: Path) -> manifest.Manifest | None:
    try:
        return manifest.load(root)
    except TypeError, ValueError, SystemExit:
        return None


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
    if destination.is_symlink():
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
    if check:
        if not destination.is_file() or destination.read_bytes() != target.source.read_bytes():
            return SyncOutcome.DRIFT
        return SyncOutcome.OK
    if destination.exists() and not force:
        return SyncOutcome.SKIPPED
    _ = shutil.copyfile(target.source, destination)
    return SyncOutcome.WRITTEN
