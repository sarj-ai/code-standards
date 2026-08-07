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

from sarj_lint_configs._meta import CONFIGS_DIR
from sarj_lint_configs.libs.filesystem import is_link_like

from . import doctor, hooks, lifecycle, manifest, scaffold, transaction


if TYPE_CHECKING:
    from collections.abc import Sequence


_VERSION_LINE = re.compile(r'(?m)^version\s*=\s*"[^"]*"\s*$')
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
        "doctor.precommit.rev",
        "doctor.pyright.deprecated",
        "doctor.ruff.authority",
        "doctor.rule.retired",
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
    manifest_text: str


def build_plan(root: Path) -> UpgradePlan:  # ruff: ignore[too-many-locals] -- one plan resolves every owned site once
    """Build a non-mutating plan targeting the executing compatibility bundle."""
    root = root.resolve()
    if not root.is_dir():
        msg = f"repository root {root} is not a directory"
        raise ValueError(msg)
    adopted = manifest.load(root)
    if adopted is None:
        msg = "repository is not adopted; run `sarj-standards init` first"
        raise ValueError(msg)
    executing_version = Version(manifest.adopted_version())
    declared_version = Version(adopted.version)
    if declared_version > executing_version:
        msg = (
            f"repository uses newer standards {adopted.version}; executing bundle is "
            f"{manifest.adopted_version()}. Install the newer sarj-lint-configs release and rerun update"
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
    )
    if scaffold_plan.errors:
        raise ValueError("; ".join(scaffold_plan.errors))
    ecosystems = _install_ecosystems(detected_ecosystems, adopted.configs)

    installed = manifest.installed_versions()
    pin_updates = doctor.plan_version_pin_updates(root, installed)
    # Compose pin migrations into scaffold rewrites of the same file.
    scaffold_plan.writes = [
        (path, doctor.rewrite_version_pins(contents, installed)[0]) for path, contents in scaffold_plan.writes
    ]
    scaffold_write_paths = {path for path, _contents in scaffold_plan.writes}
    pin_writes = [(update.path, update.contents) for update in pin_updates if update.path not in scaffold_write_paths]

    if not _VERSION_LINE.search(current_text):
        msg = f"{path} has no replaceable top-level version field"
        raise ValueError(msg)
    manifest_text = _VERSION_LINE.sub(f'version = "{manifest.adopted_version()}"', current_text, count=1)
    if "manager" not in hooks_table:
        separator = "" if manifest_text.endswith("\n\n") else "\n"
        manifest_text += f'{separator}[hooks]\nmanager = "{hook_manager}"\n'
    changes: list[Change] = []
    if manifest_text != current_text:
        changes.append(Change(path, f"adopt lint-configs {manifest.adopted_version()}"))

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

    for target, _contents in (*scaffold_plan.writes, *scaffold_plan.edits):
        if target != path:
            changes.append(Change(target, "repair adoption wiring"))
    changes.extend(Change(update.path, f"refresh {'/'.join(update.packages)} version pin") for update in pin_updates)
    return UpgradePlan(root, adopted, ecosystems, scaffold_plan, changes, config_writes, pin_writes, manifest_text)


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
    owned = {target.relative_to(plan.root).as_posix() for _source, target in plan.config_writes}
    return [
        finding
        for finding in doctor.diagnose(plan.root)
        if finding.id == "doctor.rule.retired"
        and finding.level is doctor.Level.DRIFT
        and finding.where.split(": ", 1)[0] not in owned
    ]


def apply(plan: UpgradePlan, *, install: bool = True) -> int:
    """Apply one validated plan and restore touched files if any step fails."""
    if Version(plan.adopted.version) > Version(manifest.adopted_version()):
        return 2
    blockers = unsafe_retired_findings(plan) if changes_bundle_version(plan) else []
    if blockers:
        return 2

    paths = tuple(
        [manifest.manifest_path(plan.root)]
        + [target for _source, target in plan.config_writes]
        + [path for path, _contents in plan.pin_writes]
        + [path for path, _contents in (*plan.scaffold_plan.writes, *plan.scaffold_plan.edits)]
    )
    file_transaction = transaction.FileTransaction.capture(plan.root, paths)
    environment = None if plan.ecosystems.python_root is None else plan.ecosystems.python_root / ".venv"
    environment_existed = environment is not None and environment.exists()
    try:
        status = _apply_and_validate(plan, file_transaction, install=install)
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
) -> int:
    """Apply the plan and return its install/postflight status."""
    _write_plan(plan)
    file_transaction.mark_written(
        *(
            path
            for path in (
                manifest.manifest_path(plan.root),
                *(target for _source, target in plan.config_writes),
                *(path for path, _contents in (*plan.scaffold_plan.writes, *plan.scaffold_plan.edits)),
            )
            if path.name not in _INSTALL_MUTATED_NAMES
        )
    )
    if install:
        status = lifecycle.execute(
            lifecycle.install_commands(
                plan.root,
                plan.ecosystems,
                hook_manager=plan.adopted.hook_manager,
            )
        )
        if status:
            return status
    findings = doctor.diagnose(plan.root)
    drifted = [finding for finding in findings if finding.level is doctor.Level.DRIFT]
    if not install:
        drifted = [finding for finding in drifted if not is_install_remediable(finding)]
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


def _write_plan(plan: UpgradePlan) -> None:
    """Write validated upgrade files; the caller owns rollback."""
    transaction.validate_targets(
        plan.root,
        tuple(
            [manifest.manifest_path(plan.root)]
            + [target for _source, target in plan.config_writes]
            + [path for path, _contents in plan.pin_writes]
            + [path for path, _contents in (*plan.scaffold_plan.writes, *plan.scaffold_plan.edits)]
        ),
    )
    manifest.manifest_path(plan.root).write_text(plan.manifest_text, encoding="utf-8")
    for source, target in plan.config_writes:
        if is_link_like(target) or (target.exists() and not target.is_file()):
            msg = f"refusing unsafe generated-config target {target}"
            raise OSError(msg)
        _ = shutil.copyfile(source, target)
    for target, contents in plan.pin_writes:
        target.write_text(contents, encoding="utf-8")
    scaffold.apply(plan.scaffold_plan)


def render(changes: Sequence[Change]) -> str:
    """Render a deterministic human-readable preview."""
    return "\n".join(f"update: {change.path} -- {change.reason}" for change in changes)
