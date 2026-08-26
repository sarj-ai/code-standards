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

from . import doctor, hooks, lifecycle, manifest, packagemanager, retired_suppressions, scaffold, transaction, uvtool
from .configs import PYTHON_COMPANION_CONFIGS, TYPESCRIPT_COMPANION_CONFIGS


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


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
_MIRROR_EXCLUDED_PARTS: Final = frozenset({"example", "examples", "fixture", "fixtures", "test", "tests"})


@dataclass(frozen=True)
class Change:
    path: Path
    reason: str


@dataclass
class UpgradePlan:
    root: Path
    adopted: manifest.Manifest
    ecosystems: scaffold.Ecosystems
    scaffold_plan: scaffold.Plan
    changes: list[Change]
    config_writes: list[tuple[Path, Path]]
    pin_writes: list[tuple[Path, str]]
    lockfiles: tuple[Path, ...]
    javascript_install_roots: tuple[Path, ...]
    javascript_lockfiles: tuple[Path, ...]
    suppression_writes: list[tuple[Path, str]]
    manifest_text: str
    preconditions: dict[Path, bytes | None]
    preexisting_drift: frozenset[tuple[str, str]]


def build_plan(root: Path) -> UpgradePlan:  # ruff: ignore[too-many-locals] -- one plan resolves every owned site once
    root = root.resolve()
    if not root.is_dir():
        msg = f"repository root {root} is not a directory"
        raise ValueError(msg)
    adopted = manifest.load(root)
    if adopted is None:
        msg = "repository is not adopted; run `code-standards setup` first"
        raise ValueError(msg)
    executing_version = Version(manifest.adopted_version())
    declared_version = Version(adopted.version)
    if declared_version > executing_version:
        msg = (
            f"repository uses newer standards {adopted.version}; executing bundle is "
            f"{manifest.adopted_version()}. Install the newer code-standards release and rerun update"
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
    lockfile_candidates: set[Path] = set()
    for update in pin_updates:
        sibling_lock = update.path.with_name("uv.lock")
        if update.path.name == "pyproject.toml" and sibling_lock.is_file():
            lockfile_candidates.add(sibling_lock)
    lockfiles = tuple(sorted(lockfile_candidates))
    primary_javascript_root = ecosystems.typescript_install_root or ecosystems.typescript_root
    javascript_install_roots = tuple(
        sorted(
            {
                install_root
                for update in pin_updates
                if update.path.name == "package.json"
                and (install_root := packagemanager.workspace_root(update.path.parent, root)) != primary_javascript_root
                and any((install_root / name).is_file() for name, _manager in packagemanager.LOCKFILES)
            }
        )
    )
    javascript_lockfiles = tuple(
        sorted(
            lockfile
            for install_root in javascript_install_roots
            for name, _manager in packagemanager.LOCKFILES
            if (lockfile := install_root / name).is_file()
        )
    )

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
            targets = (target, *_identical_config_mirrors(root, target))
            for config_target in targets:
                changes.append(Change(config_target, f"sync {name} config"))
                config_writes.append((source, config_target))
        companions: Mapping[str, tuple[str, str]] = {}
        if name == "pyright":
            companions = PYTHON_COMPANION_CONFIGS
        elif name == "eslint":
            companions = TYPESCRIPT_COMPANION_CONFIGS
        for companion_name, (companion_source, companion_target) in companions.items():
            companion_source_path = CONFIGS_DIR / companion_source
            companion_target_path = destination / companion_target
            if (
                not companion_target_path.is_file()
                or companion_target_path.read_bytes() != companion_source_path.read_bytes()
            ):
                changes.append(Change(companion_target_path, f"sync {companion_name} companion config"))
                config_writes.append((companion_source_path, companion_target_path))

    reserved_paths = {
        path,
        *(target for _source, target in config_writes),
        *(target for target, _contents in pin_writes),
        *(target for target, _contents in (*scaffold_plan.writes, *scaffold_plan.edits)),
        *scaffold_plan.deletes,
    }
    suppression_writes = [
        (rewrite.path, rewrite.contents)
        for rewrite in retired_suppressions.plan(doctor.authored_files(root))
        if rewrite.path not in reserved_paths
    ]

    for target, _contents in (*scaffold_plan.writes, *scaffold_plan.edits):
        if target != path:
            changes.append(Change(target, "repair adoption wiring"))
    changes.extend(Change(target, "remove retired repository launcher") for target in scaffold_plan.deletes)
    changes.extend(Change(update.path, f"refresh {'/'.join(update.packages)} version pin") for update in pin_updates)
    changes.extend(Change(lockfile, "refresh Python lockfile") for lockfile in lockfiles)
    changes.extend(Change(lockfile, "refresh JavaScript lockfile") for lockfile in javascript_lockfiles)
    changes.extend(Change(path, "migrate retired rule reference") for path, _contents in suppression_writes)
    planned_paths = tuple(
        dict.fromkeys(
            [path]
            + [target for _source, target in config_writes]
            + [target for target, _contents in pin_writes]
            + list(lockfiles)
            + list(javascript_lockfiles)
            + [target for target, _contents in suppression_writes]
            + [target for target, _contents in (*scaffold_plan.writes, *scaffold_plan.edits)]
            + list(scaffold_plan.deletes)
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
        lockfiles,
        javascript_install_roots,
        javascript_lockfiles,
        suppression_writes,
        manifest_text,
        preconditions,
        preexisting_drift,
    )


def _identical_config_mirrors(root: Path, target: Path) -> tuple[Path, ...]:
    if not target.is_file() or is_link_like(target):
        return ()
    expected = target.read_bytes()
    return tuple(
        path
        for path in doctor.authored_files(root)
        if path != target
        and path.name == target.name
        and not any(part.lower() in _MIRROR_EXCLUDED_PARTS for part in path.relative_to(root).parts)
        and path.read_bytes() == expected
    )


def _install_ecosystems(ecosystems: scaffold.Ecosystems, configs: Sequence[str]) -> scaffold.Ecosystems:
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
        + list(plan.lockfiles)
        + list(plan.javascript_lockfiles)
        + [path for path, _contents in plan.suppression_writes]
        + [path for path, _contents in (*plan.scaffold_plan.writes, *plan.scaffold_plan.edits)]
        + list(plan.scaffold_plan.deletes)
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
    _write_plan(plan, file_transaction)
    if install:
        status = lifecycle.execute(
            [
                *(
                    lifecycle.Command("Python lockfile", uvtool.lock_argv(lockfile.parent), lockfile.parent)
                    for lockfile in plan.lockfiles
                ),
                *(
                    lifecycle.Command(
                        "JavaScript lockfile",
                        packagemanager.install_argv(
                            (manager := packagemanager.detect(install_root)),
                            workspace=(
                                manager is packagemanager.PackageManager.PNPM
                                or (install_root / "pnpm-workspace.yaml").is_file()
                            ),
                            yarn=packagemanager.yarn_variant(install_root),
                        ),
                        install_root,
                    )
                    for install_root in plan.javascript_install_roots
                ),
                *lifecycle.install_commands(
                    plan.root,
                    plan.ecosystems,
                    hook_manager=plan.adopted.hook_manager,
                ),
            ]
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
    return Version(plan.adopted.version) < Version(manifest.adopted_version())


def is_install_remediable(finding: doctor.Finding) -> bool:
    return finding.id in _INSTALL_REMEDIABLE_FINDING_IDS


def pending_install_findings(root: Path) -> list[doctor.Finding]:
    return [
        finding
        for finding in doctor.diagnose(root)
        if finding.level is doctor.Level.DRIFT and is_install_remediable(finding)
    ]


def _write_plan(plan: UpgradePlan, file_transaction: transaction.FileTransaction) -> None:
    transaction.validate_targets(
        plan.root,
        tuple(
            [manifest.manifest_path(plan.root)]
            + [target for _source, target in plan.config_writes]
            + [path for path, _contents in plan.pin_writes]
            + [path for path, _contents in plan.suppression_writes]
            + [path for path, _contents in (*plan.scaffold_plan.writes, *plan.scaffold_plan.edits)]
            + list(plan.scaffold_plan.deletes)
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
    for target in plan.scaffold_plan.deletes:
        _mark_direct_write(file_transaction, target)


def _mark_direct_write(file_transaction: transaction.FileTransaction, path: Path) -> None:
    file_transaction.mark_written(path)


def _mark_installer_writes(file_transaction: transaction.FileTransaction) -> None:
    file_transaction.mark_written(*(path for path in file_transaction.before if path.name in _INSTALL_MUTATED_NAMES))


def render(changes: Sequence[Change]) -> str:
    return "\n".join(f"update: {change.path} -- {change.reason}" for change in changes)
