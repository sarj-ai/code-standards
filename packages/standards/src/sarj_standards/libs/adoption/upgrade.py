"""Plan and apply a coherent standards upgrade without clobbering user config."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
import shutil
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from packaging.version import Version

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.filesystem import is_link_like

from . import doctor, hooks, lifecycle, manifest, retired_suppressions, scaffold, transaction


if TYPE_CHECKING:
    from collections.abc import Sequence


_BUNDLE_LINE = re.compile(r'(?m)^bundle\s*=\s*"[^"]*"\s*$')
_INSTALL_REMEDIABLE_FINDING_IDS = frozenset(
    {
        "doctor.eslint.override",
        "doctor.eslint.peer",
        "doctor.python.legacy-in-project-tool",
    }
)
_MANUAL_POSTFLIGHT_FINDING_IDS = frozenset(
    {
        "doctor.eslint.shadowed-config",
        "doctor.ci.gate",
        "doctor.precommit.rev",
        "doctor.pyright.deprecated",
        "doctor.ruff.authority",
    }
)


_INSTALL_MUTATED_NAMES: Final = frozenset(
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
_CONFIG_SOURCES = MappingProxyType(
    {
        "ruff": ("ruff.strict.toml", "ruff.application.toml", ".ruff-strict.toml", "python"),
        "pyright": ("pyright.strict.json", "pyright.strict.json", ".pyright-strict.json", "python"),
        "eslint": ("eslint.strict.mjs", "eslint.application.mjs", "eslint.strict.mjs", "typescript"),
        "markdownlint": ("markdownlint.strict.yaml", "markdownlint.strict.yaml", ".markdownlint.yaml", "root"),
        "taplo": ("taplo.strict.toml", "taplo.strict.toml", ".taplo.toml", "root"),
        "yamllint": ("yamllint.strict.yaml", "yamllint.strict.yaml", ".yamllint.yaml", "root"),
    }
)


@dataclass(frozen=True)
class Change:
    """One deterministic file change in an upgrade preview."""

    path: Path
    reason: str


@dataclass
class UpgradePlan:
    """Validated upgrade state shared by check and apply modes."""

    root: Path
    adopted: manifest.Manifest
    ecosystems: scaffold.Ecosystems
    scaffold_plan: scaffold.Plan
    changes: list[Change]
    config_writes: list[tuple[Path, Path]]
    pin_writes: list[tuple[Path, str]]
    suppression_writes: list[tuple[Path, str]]
    manifest_text: str
    preconditions: dict[Path, bytes | None]
    preexisting_drift: frozenset[tuple[str, str]]


def build_plan(root: Path) -> UpgradePlan:  # ruff: ignore[too-many-locals] -- one plan resolves every owned site once
    """Build a non-mutating plan targeting the executing compatibility bundle."""
    root = root.resolve()
    if not root.is_dir():
        msg = f"repository root {root} is not a directory"
        raise ValueError(msg)
    adopted = manifest.load(root)
    if adopted is None:
        msg = "repository is not adopted; run `sarj-standards setup` first"
        raise ValueError(msg)
    executing_version = Version(manifest.adopted_version())
    declared_version = Version(adopted.version)
    if declared_version > executing_version:
        msg = (
            f"repository uses newer standards {adopted.version}; executing bundle is "
            f"{manifest.adopted_version()}. Install the newer sarj-standards release and rerun update"
        )
        raise ValueError(msg)
    path = manifest.manifest_path(root)
    current_text = path.read_text(encoding="utf-8")
    parsed: object = tomllib.loads(current_text)
    hooks_table = manifest.table_field(manifest.as_table(parsed), "hooks")
    hook_manager = adopted.hook_manager if "manager" in hooks_table else hooks.detect_manager(root)
    adopted = replace(adopted, hook_manager=hook_manager)
    detected_ecosystems = scaffold.detect(
        root,
        python_dest=adopted.python_dest if any(name in adopted.configs for name in manifest.PYTHON_CONFIGS) else None,
        typescript_dest=(
            adopted.typescript_dest if any(name in adopted.configs for name in manifest.TYPESCRIPT_CONFIGS) else None
        ),
    )
    scaffold_plan = scaffold.build_plan(
        root,
        force=False,
        configs=adopted.configs,
        python_dest=adopted.python_dest if detected_ecosystems.python else None,
        typescript_dest=adopted.typescript_dest if detected_ecosystems.typescript else None,
        profile=adopted.profile,
        hook_manager=adopted.hook_manager,
        allow_existing_nested_eslint=True,
    )
    if scaffold_plan.errors:
        raise ValueError("; ".join(scaffold_plan.errors))
    manifest_target = manifest.manifest_path(root)
    scaffold_plan.writes = [(path, contents) for path, contents in scaffold_plan.writes if path != manifest_target]
    ecosystems = _install_ecosystems(detected_ecosystems, adopted.configs)

    installed = manifest.installed_versions()
    pin_updates = doctor.plan_version_pin_updates(root, installed)
    # Compose pin migrations into scaffold rewrites of the same file.
    scaffold_plan.writes = [
        (path, doctor.rewrite_version_pins(contents, installed)[0]) for path, contents in scaffold_plan.writes
    ]
    scaffold_write_paths = {path for path, _contents in scaffold_plan.writes}
    pin_writes = [(update.path, update.contents) for update in pin_updates if update.path not in scaffold_write_paths]

    if not _BUNDLE_LINE.search(current_text):
        msg = f"{path} has no replaceable top-level bundle field"
        raise ValueError(msg)
    manifest_text = _BUNDLE_LINE.sub(f'bundle = "{manifest.adopted_version()}"', current_text, count=1)
    if "manager" not in hooks_table:
        separator = "" if manifest_text.endswith("\n\n") else "\n"
        manifest_text += f'{separator}[hooks]\nmanager = "{hook_manager}"\n'
    changes: list[Change] = []
    if manifest_text != current_text:
        changes.append(Change(path, f"adopt standards {manifest.adopted_version()}"))

    destinations = {
        "root": root,
        "python": (root / adopted.python_dest).resolve(),
        "typescript": (root / adopted.typescript_dest).resolve(),
    }
    config_writes: list[tuple[Path, Path]] = []
    for name in adopted.configs:
        spec = _CONFIG_SOURCES.get(name)
        if spec is None:
            msg = f"manifest declares unknown config {name!r}"
            raise ValueError(msg)
        standard, application, target_name, kind = spec
        destination = destinations[kind]
        try:
            destination.relative_to(root.resolve())
        except ValueError as exc:
            msg = f"manifest destination for {name} escapes repository root"
            raise ValueError(msg) from exc
        source = CONFIGS_DIR / (application if adopted.profile == "application" else standard)
        target = destination / target_name
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            changes.append(Change(target, f"sync {name} config"))
            config_writes.append((source, target))

    reserved_paths = {
        path,
        *(target for _source, target in config_writes),
        *(target for target, _contents in pin_writes),
        *(target for target, _contents in (*scaffold_plan.writes, *scaffold_plan.edits)),
    }
    suppression_writes = [
        (rewrite.path, rewrite.contents)
        for rewrite in retired_suppressions.plan(doctor.authored_files(root))
        if rewrite.path not in reserved_paths
    ]

    for target, _contents in (*scaffold_plan.writes, *scaffold_plan.edits):
        if target != path:
            changes.append(Change(target, "repair adoption wiring"))
    changes.extend(Change(update.path, f"refresh {'/'.join(update.packages)} version pin") for update in pin_updates)
    changes.extend(Change(path, "migrate retired source suppression") for path, _contents in suppression_writes)
    planned_paths = tuple(
        dict.fromkeys(
            [path]
            + [target for _source, target in config_writes]
            + [target for target, _contents in pin_writes]
            + [target for target, _contents in suppression_writes]
            + [target for target, _contents in (*scaffold_plan.writes, *scaffold_plan.edits)]
        )
    )
    transaction.validate_targets(root, planned_paths)
    preconditions = {target: target.read_bytes() if target.is_file() else None for target in planned_paths}
    preexisting_drift = frozenset(
        (finding.id, finding.where) for finding in doctor.diagnose(root) if finding.level is doctor.Level.DRIFT
    )
    return UpgradePlan(
        root,
        adopted,
        ecosystems,
        scaffold_plan,
        changes,
        config_writes,
        pin_writes,
        suppression_writes,
        manifest_text,
        preconditions,
        preexisting_drift,
    )


def _install_ecosystems(ecosystems: scaffold.Ecosystems, configs: Sequence[str]) -> scaffold.Ecosystems:
    """Keep install capabilities only for ecosystems explicitly adopted by the manifest."""
    python = ecosystems.python and any(name in manifest.PYTHON_CONFIGS for name in configs)
    typescript = ecosystems.typescript and any(name in manifest.TYPESCRIPT_CONFIGS for name in configs)
    return scaffold.Ecosystems(
        python=python,
        typescript=typescript,
        python_root=ecosystems.python_root if python else None,
        typescript_root=ecosystems.typescript_root if typescript else None,
        typescript_install_root=ecosystems.typescript_install_root if typescript else None,
        client=ecosystems.client,
        yarn=ecosystems.yarn,
    )


def unsafe_retired_findings(plan: UpgradePlan) -> list[doctor.Finding]:
    """Return consumer-authored blockers, excluding configs this plan replaces."""
    replaced = [target for _source, target in plan.config_writes]
    owned = {target.relative_to(plan.root).as_posix() for target in replaced}
    planned = {path.relative_to(plan.root).as_posix(): (path, contents) for path, contents in plan.suppression_writes}
    projected = {
        path.relative_to(plan.root).as_posix(): (path, contents) for path, contents in plan.scaffold_plan.writes
    }
    blockers: list[doctor.Finding] = []
    for finding in doctor.diagnose(plan.root):
        if finding.id != "doctor.rule.retired" or finding.level is not doctor.Level.DRIFT:
            continue
        relative, _, reference = finding.where.partition(": ")
        if relative in owned:
            continue
        rewrite = planned.get(relative)
        retired_id = reference.rsplit(" x", maxsplit=1)[0]
        if rewrite is not None and retired_id not in doctor.retired_rule_references(*rewrite):
            continue
        scaffold_write = projected.get(relative)
        if scaffold_write is not None and retired_id not in doctor.retired_rule_references(*scaffold_write):
            continue
        blockers.append(finding)
    return blockers


def apply(
    plan: UpgradePlan,
    *,
    install: bool = True,
    allow_retired_debt: bool = False,
) -> int:
    """Apply one validated plan and restore touched files if any step fails."""
    if Version(plan.adopted.version) > Version(manifest.adopted_version()):
        return 2
    blockers = unsafe_retired_findings(plan)
    if blockers and not allow_retired_debt:
        return 2
    try:
        transaction.validate_targets(plan.root, tuple(plan.preconditions))
        stale = any(
            (path.read_bytes() if path.is_file() else None) != expected for path, expected in plan.preconditions.items()
        )
    except OSError:
        return 2
    if stale:
        return 2

    paths = tuple(
        [manifest.manifest_path(plan.root)]
        + [target for _source, target in plan.config_writes]
        + [path for path, _contents in plan.pin_writes]
        + [path for path, _contents in plan.suppression_writes]
        + [path for path, _contents in (*plan.scaffold_plan.writes, *plan.scaffold_plan.edits)]
    )
    file_transaction = transaction.FileTransaction.capture(plan.root, paths)
    environment = None if plan.ecosystems.python_root is None else plan.ecosystems.python_root / ".venv"
    environment_existed = environment is not None and environment.exists()
    try:
        status = _apply_and_validate(
            plan,
            file_transaction,
            install=install,
            allow_retired_debt=allow_retired_debt,
        )
    except KeyboardInterrupt:
        _recover_or_raise(file_transaction, environment, environment_existed=environment_existed)
        return 130
    except OSError, TypeError, ValueError:
        _recover_or_raise(file_transaction, environment, environment_existed=environment_existed)
        return 2
    if status:
        _recover_or_raise(file_transaction, environment, environment_existed=environment_existed)
    return status


def _recover_or_raise(
    file_transaction: transaction.FileTransaction,
    environment: Path | None,
    *,
    environment_existed: bool,
) -> None:
    errors = tuple(
        detail
        for detail in (
            file_transaction.rollback().render(),
            None
            if _cleanup_new_environment(environment, existed=environment_existed)
            else "could not remove new environment",
        )
        if detail
    )
    if errors:
        raise OSError("upgrade recovery incomplete: " + "; ".join(errors))


def _cleanup_new_environment(environment: Path | None, *, existed: bool) -> bool:
    if existed or environment is None or not environment.is_dir():
        return True
    try:
        shutil.rmtree(environment)
    except OSError:
        return False
    return True


def _apply_and_validate(
    plan: UpgradePlan,
    file_transaction: transaction.FileTransaction,
    *,
    install: bool,
    allow_retired_debt: bool,
) -> int:
    """Apply the plan and return its install/postflight status."""
    _write_plan(plan, file_transaction)
    if install:
        status = lifecycle.execute(
            lifecycle.install_commands(
                plan.root,
                plan.ecosystems,
                hook_manager=plan.adopted.hook_manager,
            )
        )
        _mark_installer_writes(file_transaction)
        if status:
            return status
    findings = doctor.diagnose(plan.root)
    drifted = [finding for finding in findings if finding.level is doctor.Level.DRIFT]
    if not install:
        drifted = [finding for finding in drifted if not is_install_remediable(finding)]
    if not allow_retired_debt and any(finding.id == "doctor.rule.retired" for finding in drifted):
        return 1
    if allow_retired_debt:
        drifted = [finding for finding in drifted if finding.id != "doctor.rule.retired"]
    drifted = [finding for finding in drifted if (finding.id, finding.where) not in plan.preexisting_drift]
    drifted = [finding for finding in drifted if finding.id not in _MANUAL_POSTFLIGHT_FINDING_IDS]
    return 1 if drifted else 0


def changes_bundle_version(plan: UpgradePlan) -> bool:
    """Whether applying the plan crosses a rule-compatibility boundary."""
    return Version(plan.adopted.version) < Version(manifest.adopted_version())


def is_install_remediable(finding: doctor.Finding) -> bool:
    """Whether the setup commands skipped by ``--no-install`` fix a finding."""
    return finding.id in _INSTALL_REMEDIABLE_FINDING_IDS


def pending_install_findings(root: Path) -> list[doctor.Finding]:
    """Return truthful dependency drift left by a successful no-install update."""
    return [
        finding
        for finding in doctor.diagnose(root)
        if finding.level is doctor.Level.DRIFT and is_install_remediable(finding)
    ]


def _write_plan(plan: UpgradePlan, file_transaction: transaction.FileTransaction) -> None:
    """Write validated upgrade files; the caller owns rollback."""
    transaction.validate_targets(
        plan.root,
        tuple(
            [manifest.manifest_path(plan.root)]
            + [target for _source, target in plan.config_writes]
            + [path for path, _contents in plan.pin_writes]
            + [path for path, _contents in plan.suppression_writes]
            + [path for path, _contents in (*plan.scaffold_plan.writes, *plan.scaffold_plan.edits)]
        ),
    )
    manifest_target = manifest.manifest_path(plan.root)
    transaction.assert_expected(plan.root, manifest_target, plan.preconditions[manifest_target])
    transaction.atomic_write_text(plan.root, manifest_target, plan.manifest_text)
    _mark_direct_write(file_transaction, manifest_target)
    for source, target in plan.config_writes:
        if is_link_like(target) or (target.exists() and not target.is_file()):
            msg = f"refusing unsafe generated-config target {target}"
            raise OSError(msg)
        transaction.assert_expected(plan.root, target, plan.preconditions[target])
        transaction.atomic_write_bytes(plan.root, target, source.read_bytes())
        _mark_direct_write(file_transaction, target)
    for target, contents in plan.pin_writes:
        transaction.assert_expected(plan.root, target, plan.preconditions[target])
        transaction.atomic_write_text(plan.root, target, contents)
        _mark_direct_write(file_transaction, target)
    for target, contents in plan.suppression_writes:
        transaction.assert_expected(plan.root, target, plan.preconditions[target])
        transaction.atomic_write_text(plan.root, target, contents)
        _mark_direct_write(file_transaction, target)
    scaffold.apply(plan.scaffold_plan, preconditions=plan.preconditions)
    for target, _contents in (*plan.scaffold_plan.writes, *plan.scaffold_plan.edits):
        _mark_direct_write(file_transaction, target)


def _mark_direct_write(file_transaction: transaction.FileTransaction, path: Path) -> None:
    """Record each direct write before another planned mutation can fail."""
    file_transaction.mark_written(path)


def _mark_installer_writes(file_transaction: transaction.FileTransaction) -> None:
    """Accept controlled installer mutations as the transaction's latest writes."""
    file_transaction.mark_written(*(path for path in file_transaction.before if path.name in _INSTALL_MUTATED_NAMES))


def render(changes: Sequence[Change]) -> str:
    """Render a deterministic human-readable preview."""
    return "\n".join(f"update: {change.path} -- {change.reason}" for change in changes)
