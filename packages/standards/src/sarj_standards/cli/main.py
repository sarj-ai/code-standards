from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- repository commands report failures from fixed-argument child processes.
import sys
import tempfile
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Final, NoReturn, TypeIs

from packaging.version import InvalidVersion, Version
from pydantic import TypeAdapter, ValidationError
from repo_standards.core.commit_message import check_local_commit_message_file
import typer

from sarj_standards import __version__
from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.adoption.configs import CONFIG_NAMES
from sarj_standards.libs.filesystem import is_link_like
from sarj_standards.libs.rules import RuleSelector


if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from sarj_standards.libs.adoption import service
    from sarj_standards.libs.diagnostics import AnalysisReport, Diagnostic
    from sarj_standards.libs.repository import rule_catalog_artifact


_NEXT_STEPS = (
    "\nnext: in your pyproject.toml, add:\n"
    "  [tool.ruff]\n"
    '  extend = ".ruff-strict.toml"\n'
    "\n(or run `code-standards setup`, which writes that and the rest of the wiring)\n"
)
_GIT_SAFE_ENV = frozenset(
    {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TMPDIR", "XDG_CONFIG_HOME"}
)
_INVALID_DOCTOR_IDS = frozenset(
    {
        "doctor.manifest.invalid",
        "doctor.manifest.destination",
        "doctor.config.unknown",
        "doctor.package-json.invalid",
    }
)
_HOOK_INSTALL_IDS: Final = frozenset(
    {
        "doctor.hooks.precommit-install",
        "doctor.hooks.lefthook-install",
        "doctor.hooks.commit-message-install",
    }
)
_REACT_DOCTOR_METADATA = frozenset(
    {
        "doctor.config.json",
        "eslint.config.js",
        "eslint.config.mjs",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "tsconfig.json",
        "yarn.lock",
    }
)
_REACT_DOCTOR_TYPESCRIPT_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"})
_BASELINE_RULE_SOURCE_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "sarj-iac-lint": "iac",
        "sarj-python-lint": "python",
        "sarj-sql-lint": "sql",
        "sarj-text-lint": "text",
    }
)
_BASELINE_RULE_ENGINE_SOURCES: Final[Mapping[str, str]] = MappingProxyType(
    {engine: source for source, engine in _BASELINE_RULE_SOURCE_ALIASES.items()}
)
_REACT_DOCTOR_RULE_SOURCES: Final = frozenset({"react-doctor", "react-hooks-js"})
_REACT_DOCTOR_RULE_PREFIXES: Final = tuple(f"{source}/" for source in sorted(_REACT_DOCTOR_RULE_SOURCES))


class _EvaluationScope(StrEnum):
    CORPUS = "corpus"
    EFFECTIVE = "effective"


@dataclass
class _Args:
    cmd: str = ""
    dest: str = "."
    only: list[str] = field(default_factory=list)
    force: bool = False
    check: bool = False
    dry_run: bool = False
    python_dest: str | None = None
    typescript_dest: str | None = None
    swift_dest: str | None = None
    kotlin_dest: str | None = None
    configs: list[str] = field(default_factory=list)
    name: str = ""
    files: list[str] = field(default_factory=list)
    repo_cmd: str = ""
    repo_only: list[str] = field(default_factory=list)
    commits: str | None = None
    policy_dest: str | None = None
    private_refs_file: str | None = None
    quiet: bool = False
    roots: list[Path] = field(default_factory=list)
    include_text: Path | None = None
    rules_cmd: str = ""
    rule_category: str = ""
    rule_summary: str = ""
    apply_rule: bool = False
    reference_cmd: str = ""
    docs_cmd: str = ""
    hooks_cmd: str = ""
    no_install: bool = False
    commit_policy_only: bool = False
    repair: bool = False
    message_file: Path | None = None
    profile: manifest.Profile | None = None
    output_format: str = "text"
    offline: bool = False
    target_version: str | None = None
    release_cmd: str = ""
    release_mode: str = ""
    tag: str = ""
    lockfile: Path | None = None
    minimum_age: timedelta | None = None
    release_exclude: list[str] = field(default_factory=list)
    release_exclude_file: list[Path] = field(default_factory=list)
    output: Path | None = None
    external: bool = False
    trust: str = "safe"
    trust_repository_code: bool = False
    before: str = ""
    after: str = ""
    github_output: Path | None = None
    release_target: str = ""
    release_targets: list[str] = field(default_factory=list)
    wheels: list[Path] = field(default_factory=list)
    hooks: manifest.HookManager | None = None
    show_cmd: str = ""
    catalog_cmd: str = ""
    exclude_cmd: str = ""
    exclude_kind: str = ""
    value: str = ""
    staged: bool = False
    release_commit: str = ""
    max_annotations_per_level: int = 10
    analysis_mode: str = "policy"
    attempts: int = 6
    delay_seconds: timedelta = timedelta(seconds=10)
    ratchet_cmd: str = ""
    baseline_cmd: str = ""
    selected_rules: list[RuleSelector] = field(default_factory=list)
    corpus_manifest: Path | None = None
    private_overlay: Path | None = None
    selector: RuleSelector | None = None
    evaluation_scope: _EvaluationScope = _EvaluationScope.CORPUS
    required_added_level: str | None = None
    baseline: Path | None = None
    baseline_rules: list[str] = field(default_factory=list)
    react_doctor_triggered: bool = False
    package: list[str] = field(default_factory=list)
    exclude_subtree: list[str] = field(default_factory=list)
    allow_increase: bool = False
    slack_catalog: Path = Path()


def cmd_sync(args: _Args, *, next_steps: bool = True) -> int:
    from sarj_standards.libs.adoption import service  # ruff: ignore[import-outside-top-level] -- lazy route

    root = _resolve_dest(args.dest)
    try:
        plan = service.plan_sync(
            root,
            configs=args.only or None,
            python_dest=args.python_dest,
            typescript_dest=args.typescript_dest,
            profile=args.profile,
        )
    except ValueError as exc:
        _user_error(str(exc))
    result = service.apply_sync(plan, force=args.force, check=args.check)
    _render_sync(result)
    if (
        result.count(service.SyncOutcome.WRITTEN)
        and next_steps
        and any(target.name == "ruff" for target in plan.targets)
    ):
        print(_NEXT_STEPS)
    return result.status


def _resolve_dest(dest_arg: str) -> Path:
    dest = Path(dest_arg).absolute().resolve()
    if not dest.is_dir():
        _user_error(f"--root {dest} is not a directory")
    return dest


def _user_error(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def _parse_rule_selector(value: str) -> RuleSelector:
    from sarj_standards.libs.rules import (  # ruff: ignore[import-outside-top-level] -- parser startup stays lazy
        RuleSelector,
    )

    try:
        return RuleSelector.parse(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _render_sync(result: service.SyncResult) -> None:
    from sarj_standards.libs.adoption import service  # ruff: ignore[import-outside-top-level] -- typed lazy route

    for record in result.records:
        destination = record.target.destination
        match record.outcome:
            case service.SyncOutcome.INVALID:
                print(f"invalid: {destination}  (destination must be a regular file)")
            case service.SyncOutcome.DRIFT:
                print(f"drift: {destination}")
            case service.SyncOutcome.OK:
                print(f"ok:    {destination}")
            case service.SyncOutcome.SKIPPED:
                print(f"skip:  {destination}  (exists; pass --force to overwrite)")
            case service.SyncOutcome.WRITTEN:
                print(f"wrote: {destination}")
    invalid = result.count(service.SyncOutcome.INVALID)
    if result.check:
        drift = result.count(service.SyncOutcome.DRIFT)
        suffix = f"; {invalid} invalid" if invalid else ""
        print(f"\nchecked {len(result.records)} config(s); {drift} drifted{suffix}.")
        return
    written = result.count(service.SyncOutcome.WRITTEN)
    skipped = result.count(service.SyncOutcome.SKIPPED)
    suffix = f"; {invalid} invalid" if invalid else ""
    print(f"\nsynced {written}/{len(result.records)} config(s); {skipped} skipped{suffix}.")


def cmd_list() -> int:
    for name, (src, dst) in CONFIG_NAMES.items():
        full = CONFIGS_DIR / src
        size = full.stat().st_size if full.exists() else 0
        print(f"{name:8s}  {src:25s}  -> {dst:25s}  ({size:>5d} bytes)")
    return 0


def cmd_path(args: _Args) -> int:
    src_name, _ = CONFIG_NAMES[args.name]
    print(CONFIGS_DIR / src_name)
    return 0


def cmd_peers(args: _Args) -> int:
    from sarj_standards.libs.adoption import packagemanager, scaffold  # ruff: ignore[import-outside-top-level]

    peers = manifest.eslint_peers()
    for name, pin in sorted(peers.items()):
        print(f"{name:50s} {pin}")
    root = _resolve_dest(args.dest)
    adopted = manifest.load(root)
    detected = scaffold.detect(root, typescript_dest=adopted.typescript_dest if adopted is not None else None)
    install_root = detected.typescript_install_root or detected.typescript_root or root
    client = packagemanager.detect(install_root)
    overrides = packagemanager.overrides_for(client)
    workspace = (
        client is packagemanager.PackageManager.PNPM
        or install_root != (detected.typescript_root or root)
        or (install_root / "pnpm-workspace.yaml").is_file()
    )
    yarn = packagemanager.yarn_variant(install_root)
    print(
        f"\ndetected {client} at {install_root}; install with:\n"
        f"{packagemanager.install_command(client, workspace=workspace, yarn=yarn)}"
    )
    if client is packagemanager.PackageManager.PNPM:
        rendered = "\n".join(f"  {json.dumps(key)}: {json.dumps(value)}" for key, value in overrides.entries.items())
        print(f"\n{client} also needs this in pnpm-workspace.yaml:\noverrides:\n{rendered}")
    else:
        print(
            f"\n{client} also needs this in package.json, or the tree does not resolve:\n"
            f"{json.dumps(overrides.as_document(), indent=2)}"
        )
    return 0


def cmd_doctor(args: _Args) -> int:  # ruff: ignore[too-many-locals] -- one command renders repair and diagnosis state.
    from sarj_standards.libs.adoption import doctor, hooks, service, upgrade  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    repair = args.repair
    no_install: bool = args.no_install
    repair_status = 0
    commit_policy_only = doctor.is_commit_policy_only(root)
    if repair:
        try:
            adopted = manifest.load(root)
        except (OSError, TypeError, ValueError) as exc:
            try:
                adopted = _repair_legacy_manifest(root, install=not no_install)
            except (OSError, TypeError, ValueError) as migration_error:
                details = str(exc)
                migration_details = str(migration_error)
                if migration_details != details:
                    details = f"{details}; {migration_details}"
                print(f"error: cannot repair invalid adoption manifest: {details}", file=sys.stderr)
                return 2
        if adopted is None and not commit_policy_only:
            print("error: repository is not adopted; run `code-standards setup`", file=sys.stderr)
            return 2
        if commit_policy_only:
            init_plan = service.plan_commit_policy(root, hook_manager=hooks.detect_manager(root))
            if init_plan.scaffold.errors:
                for error in init_plan.scaffold.errors:
                    print(f"error: {error}", file=sys.stderr)
                return 2
            current_findings = doctor.diagnose_commit_policy(root)
            current_drift = [finding for finding in current_findings if finding.level is doctor.Level.DRIFT]
            missing_hooks = not no_install and any(finding.id in _HOOK_INSTALL_IDS for finding in current_findings)
            needs_repair = bool(
                init_plan.scaffold.writes
                or init_plan.scaffold.edits
                or init_plan.scaffold.deletes
                or current_drift
                or missing_hooks
            )
            if needs_repair:
                repair_status = service.apply_init(init_plan, install=not no_install).status
        else:
            plan = upgrade.build_plan(root)
            blockers = upgrade.unsafe_retired_findings(plan)
            if blockers:
                print("warning: automatic repair cannot migrate these retired rule references:", file=sys.stderr)
                for finding in blockers:
                    print(f"warning: {finding.where} -- {finding.detail}", file=sys.stderr)
            current_findings = doctor.diagnose(root)
            current_drift = [finding for finding in current_findings if finding.level is doctor.Level.DRIFT]
            missing_hooks = not no_install and any(finding.id in _HOOK_INSTALL_IDS for finding in current_findings)
            repair_status = (
                0
                if not plan.changes and not current_drift and not missing_hooks
                else upgrade.apply(
                    plan,
                    install=not no_install,
                    allow_retired_debt=bool(blockers),
                )
            )
        if repair_status > 1:
            print(
                "error: automatic repair did not converge; tracked configuration changes were restored",
                file=sys.stderr,
            )
    findings = doctor.diagnose_commit_policy(root) if commit_policy_only else doctor.diagnose(root)
    if repair and no_install:
        findings = [
            doctor.Finding(
                doctor.Level.WARN,
                finding.where,
                f"{finding.detail}; installation intentionally skipped",
                finding.id,
                finding.remediation,
            )
            if (
                (finding.level is doctor.Level.DRIFT and upgrade.is_install_remediable(finding))
                or finding.id in _HOOK_INSTALL_IDS
            )
            else finding
            for finding in findings
        ]
    drifted = sum(1 for finding in findings if finding.level is doctor.Level.DRIFT)
    warned = sum(1 for finding in findings if finding.level is doctor.Level.WARN)
    invalid = sum(finding.id in _INVALID_DOCTOR_IDS for finding in findings)
    unadopted = any(finding.id == "doctor.manifest.absent" for finding in findings)
    if args.output_format == "json":
        print(
            json.dumps(
                {
                    "schema": 1,
                    "root": str(root),
                    "summary": {
                        "checked": len(findings),
                        "drifted": drifted,
                        "warnings": warned,
                        "invalid": invalid,
                    },
                    "findings": [finding.as_dict() for finding in findings],
                },
                indent=2,
            )
        )
    else:
        print(f"root:   {root}")
        for finding in findings:
            print(f"{finding.level.value:6s} {finding.id} {finding.where}  --  {finding.detail}")
        print(f"\nchecked {len(findings)} configuration site(s); {drifted} drifted; {warned} warning(s).")
        remediations = (
            ["run `code-standards setup`"]
            if unadopted
            else list(
                dict.fromkeys(
                    finding.remediation
                    for finding in findings
                    if (finding.level is doctor.Level.DRIFT or finding.id in _HOOK_INSTALL_IDS) and finding.remediation
                )
            )
        )
        for remediation in remediations:
            print(f"fix: {remediation}")
    if invalid:
        return max(repair_status, 2)
    unresolved_install = repair and not no_install and any(finding.id in _HOOK_INSTALL_IDS for finding in findings)
    return max(repair_status, 1 if drifted or unadopted or unresolved_install else 0)


def _repair_legacy_manifest(root: Path, *, install: bool) -> manifest.Manifest:
    from sarj_standards.libs.adoption import service  # ruff: ignore[import-outside-top-level]

    legacy = manifest.load_for_setup(root)
    if legacy is None:
        msg = "repository is not adopted; run `code-standards setup`"
        raise ValueError(msg)
    migration = service.plan_init(
        root,
        configs=legacy.configs,
        python_dest=legacy.python_dest,
        typescript_dest=legacy.typescript_dest,
        profile=legacy.profile,
        hook_manager=legacy.hook_manager,
        # A schema-three manifest already made an explicit TypeScript authority
        # choice. Preserve unrelated nested projects during its one-way schema
        # migration; the subsequent upgrade diagnoses the selected authority.
        allow_existing_nested_eslint=True,
    )
    if migration.scaffold.errors or migration.sync is None:
        detail = "; ".join(migration.scaffold.errors) or "setup plan is not applicable"
        msg = f"cannot repair legacy adoption: {detail}"
        raise ValueError(msg)
    migrated = service.apply_init(migration, install=install)
    if migrated.status:
        msg = f"cannot repair legacy adoption: {migrated.error}"
        raise ValueError(msg)
    adopted = manifest.load(root)
    if adopted is None:
        msg = "legacy manifest migration did not produce an adopted repository"
        raise ValueError(msg)
    return adopted


def cmd_update(args: _Args) -> int:  # ruff: ignore[too-many-locals] -- one command preserves preview/apply state.
    from sarj_standards.libs.adoption import doctor, lifecycle, upgrade  # ruff: ignore[import-outside-top-level]

    target_version: str | None = None
    if args.target_version is not None:
        try:
            target_version = str(Version(args.target_version))
        except InvalidVersion:
            print(f"error: invalid standards version: {args.target_version}", file=sys.stderr)
            return 2
        if target_version != args.target_version:
            print(
                f"error: standards version must be canonical ({target_version}), got {args.target_version}",
                file=sys.stderr,
            )
            return 2

    bootstrapped = (
        os.environ.get(  # ruff: ignore[banned-api] -- private recursion sentinel, not application settings
            "SARJ_STANDARDS_BOOTSTRAPPED"
        )
        == "1"
    )
    if (
        target_version is not None
        and (bootstrapped or args.offline)
        and Version(__version__) != Version(target_version)
    ):
        print(
            f"error: exact update requested standards {target_version}, but the executing bundle is {__version__}",
            file=sys.stderr,
        )
        return 2

    if not args.offline and not bootstrapped:
        executable = shutil.which("uvx")
        if executable is None:
            print(
                "error: uvx is required to resolve the latest standards release; install uv and retry "
                "(--offline only reconverges the executing bundle)",
                file=sys.stderr,
            )
            return 2
        from sarj_standards.libs.adoption import launcher  # ruff: ignore[import-outside-top-level] -- lazy route

        command = [
            *launcher.argv(executable=executable, version=target_version, refresh=True),
            "--root",
            str(_resolve_dest(args.dest)),
            "update",
        ]
        if target_version is None:
            command.append("--offline")
        else:
            command.extend(("--to", target_version))
        if args.check:
            command.append("--check")
        if args.no_install:
            command.append("--no-install")
        environment = dict(os.environ)  # ruff: ignore[banned-api] -- preserve the caller environment for uvx
        environment["SARJ_STANDARDS_BOOTSTRAPPED"] = "1"
        # The child owns the update transaction, installer deadlines, and rollback.
        # Timing out uvx here can orphan that child halfway through a valid install.
        return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed executable and argv
            command,
            check=False,
            env=environment,
        ).returncode

    if args.offline:
        args.no_install = True
    root = _resolve_dest(args.dest)
    migrated_legacy = False
    try:
        _ = manifest.load(root)
    except (OSError, TypeError, ValueError) as exc:
        migration_error: OSError | TypeError | ValueError | None = None
        try:
            legacy = manifest.load_for_setup(root)
        except (OSError, TypeError, ValueError) as legacy_error:
            legacy = None
            migration_error = legacy_error
        if legacy is None:
            print(f"error: cannot plan upgrade: {migration_error or exc}", file=sys.stderr)
            return 2
        if args.check:
            print(
                "error: the adoption manifest needs a one-way migration; run "
                "`code-standards doctor --repair --no-install`, then retry update",
                file=sys.stderr,
            )
            return 2
        try:
            # The normal upgrade transaction owns dependency installation.  A
            # legacy-manifest repair must only establish the current manifest
            # and wiring first, otherwise its installer runs before the
            # upgrade plan can refresh package-manager age-gate exemptions.
            _ = _repair_legacy_manifest(root, install=False)
            migrated_legacy = True
        except (OSError, TypeError, ValueError) as migration_error:
            print(f"error: cannot migrate legacy adoption before update: {migration_error}", file=sys.stderr)
            return 2
        print("migrated: legacy adoption manifest")
    try:
        plan = upgrade.build_plan(root)
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: cannot plan upgrade: {exc}", file=sys.stderr)
        return 2
    preflight_findings = doctor.diagnose(root)
    invalid = [finding for finding in preflight_findings if finding.id in _INVALID_DOCTOR_IDS]
    if invalid:
        for finding in invalid:
            print(f"error: {finding.id} {finding.where} -- {finding.detail}", file=sys.stderr)
            if finding.remediation:
                print(f"fix: {finding.remediation}", file=sys.stderr)
        return 2
    blockers = upgrade.unsafe_retired_findings(plan)
    if blockers:
        for finding in blockers:
            print(f"error: {finding.where} -- {finding.detail}", file=sys.stderr)
        return 2
    preview = upgrade.render(plan.changes)
    if args.check:
        drifted = [finding for finding in preflight_findings if finding.level is doctor.Level.DRIFT]
        if preview:
            print(preview)
        elif drifted:
            print(
                f"bundle current: {root} has standards {__version__},"
                f" but doctor found {len(drifted)} configuration drift(s)"
            )
        else:
            print(f"current: {root} already matches standards {__version__}")
        for finding in drifted:
            print(f"drift: {finding.id} {finding.where} -- {finding.detail}")
        remediations = list(dict.fromkeys(finding.remediation for finding in drifted if finding.remediation))
        for remediation in remediations:
            print(f"fix: {remediation}")
        return 1 if plan.changes or drifted else 0
    current_drift = [finding for finding in preflight_findings if finding.level is doctor.Level.DRIFT]
    missing_hooks = not args.no_install and any(finding.id in _HOOK_INSTALL_IDS for finding in preflight_findings)
    skipped_commands = (
        lifecycle.install_commands(root, plan.ecosystems, hook_manager=plan.adopted.hook_manager)
        if args.no_install
        else []
    )
    if not preview and not current_drift and not missing_hooks and not skipped_commands and not migrated_legacy:
        print(f"current: {root} already matches standards {__version__}")
        return 0
    print(preview or f"current: {root} already matches standards {__version__}")
    status = upgrade.apply(plan, install=not args.no_install)
    if status:
        print("error: update failed; tracked configuration files were restored", file=sys.stderr)
        remaining = [finding for finding in doctor.diagnose(root) if finding.level is doctor.Level.DRIFT]
        for finding in remaining:
            print(f"error: {finding.id} {finding.where} -- {finding.detail}", file=sys.stderr)
        for remediation in dict.fromkeys(finding.remediation for finding in remaining if finding.remediation):
            print(f"fix: {remediation}", file=sys.stderr)
        return status
    postflight_findings = doctor.diagnose(root)
    invalid = [finding for finding in postflight_findings if finding.id in _INVALID_DOCTOR_IDS]
    if invalid:
        for finding in invalid:
            print(f"error: {finding.id} {finding.where} -- {finding.detail}", file=sys.stderr)
        return 2
    unresolved_hooks = [finding for finding in postflight_findings if finding.id in _HOOK_INSTALL_IDS]
    if not args.no_install and unresolved_hooks:
        for finding in unresolved_hooks:
            print(f"error: {finding.id} {finding.where} -- {finding.detail}", file=sys.stderr)
        return 1
    pending = (
        [
            finding
            for finding in postflight_findings
            if finding.level is doctor.Level.DRIFT and upgrade.is_install_remediable(finding)
        ]
        if args.no_install
        else []
    )
    if pending or skipped_commands:
        print(
            f"updated configuration: {root} now uses standards {__version__};"
            f" setup is incomplete ({len(skipped_commands)} setup command(s) skipped;"
            f" {len(pending)} finding(s) pending)"
        )
        for finding in pending:
            print(f"pending: {finding.id} {finding.where} -- {finding.detail}")
        print("next: run the skipped setup command(s), then `code-standards doctor`:")
        for command in skipped_commands:
            print(f"      {shlex.join(command.argv)}  (in {command.cwd})")
        return 0
    print(f"updated: {root} now uses standards {__version__}")
    print("next: run `code-standards check --trust-repository-code` and review every new finding")
    return 0


def cmd_setup(args: _Args) -> int:
    from sarj_standards.libs.adoption import (  # ruff: ignore[import-outside-top-level] -- lazy route
        doctor,
        scaffold,
        service,
    )

    root = _resolve_dest(args.dest)
    selected_configs = tuple(dict.fromkeys((*args.configs, *args.only)))
    try:
        init_plan = _setup_plan(args, root, selected_configs)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: unsafe initialization plan: {exc}", file=sys.stderr)
        return 2
    plan = init_plan.scaffold
    if plan.errors:
        for error in plan.errors:
            print(f"error: {error}", file=sys.stderr)
        print("setup made no changes; resolve the wiring errors above and rerun", file=sys.stderr)
        return 2

    detected = [
        name
        for name, present in (
            ("python", plan.ecosystems.python),
            ("typescript", plan.ecosystems.typescript),
            ("swift", plan.ecosystems.swift),
            ("kotlin-mobile", plan.ecosystems.kotlin),
        )
        if present
    ]
    if args.commit_policy_only:
        print("scope: commit policy only (language tooling is untouched)")
    else:
        print(f"detected: {', '.join(detected) or 'nothing'}")
        print(f"configs: {', '.join(plan.configs)}")
    if args.dry_run:
        print("\n-- dry run; nothing is written --")
        if init_plan.sync is not None:
            pending_sync = 0
            for target in init_plan.sync.targets:
                if not target.destination.is_file() or target.destination.read_bytes() != target.source.read_bytes():
                    print(f"would sync:  {target.destination}")
                    pending_sync += 1
            if not pending_sync:
                print("configs are current")
        if not args.no_install:
            for command in init_plan.install_commands:
                print(f"would run:   {shlex.join(command.argv)}  (in {command.cwd})")
    else:
        result = service.apply_init(init_plan, install=not args.no_install)
        if result.status:
            event = "interrupted" if result.failure is service.InitFailure.INTERRUPTED else "failed"
            print(
                f"error: initialization {event}; rollback and generated-environment cleanup were attempted",
                file=sys.stderr,
            )
            if result.error:
                print(f"detail: {result.error}", file=sys.stderr)
            return result.status
        if result.sync is not None:
            _render_sync(result.sync)
        if not args.no_install:
            unresolved_hooks = [finding for finding in doctor.diagnose(root) if finding.id in _HOOK_INSTALL_IDS]
            if unresolved_hooks:
                for finding in unresolved_hooks:
                    print(
                        f"error: {finding.id} {finding.where} -- {finding.detail}",
                        file=sys.stderr,
                    )
                return 1

    verb_write = "would write" if args.dry_run else "wrote"
    verb_edit = "would append to" if args.dry_run else "appended to"
    verb_delete = "would remove" if args.dry_run else "removed"
    for path, _contents in plan.writes:
        print(f"{verb_write}: {path}")
    for path, _addition in plan.edits:
        print(f"{verb_edit}: {path}")
    for path in plan.deletes:
        print(f"{verb_delete}: {path}")
    for path, reason in plan.skips:
        print(f"skip:  {path}  ({reason})")

    for note in plan.notes:
        print(f"\nnote:  {note}")
    if args.no_install and init_plan.install_commands:
        print("\nnext:  dependency and hook installation was skipped; run:")
        for command in init_plan.install_commands:
            print(f"       {shlex.join(command.argv)}  (in {command.cwd})")
    if args.commit_policy_only:
        print("\nCI:    .github/workflows/commit-policy.yml runs the exact-base commit policy")
    else:
        workflows = scaffold.standards_check_workflows(root)
        if workflows:
            rendered = ", ".join(path.relative_to(root).as_posix() for path in workflows)
            print(f"\nCI:    {rendered} runs the pinned quality gate")
        else:
            print("\nCI:    would write .github/workflows/standards.yml")
    return 0


def _setup_plan(args: _Args, root: Path, selected_configs: tuple[str, ...]) -> service.InitPlan:
    from sarj_standards.libs.adoption import service  # ruff: ignore[import-outside-top-level] -- lazy route

    if args.commit_policy_only:
        incompatible = any(
            (
                selected_configs,
                args.python_dest,
                args.typescript_dest,
                args.swift_dest,
                args.kotlin_dest,
                args.profile,
            )
        )
        if incompatible:
            msg = "--commit-policy-only cannot be combined with config, destination, or profile options"
            raise ValueError(msg)
        return service.plan_commit_policy(root, force=args.force, hook_manager=args.hooks)
    return service.plan_init(
        root,
        force=args.force,
        configs=selected_configs or None,
        python_dest=args.python_dest,
        typescript_dest=args.typescript_dest,
        swift_dest=args.swift_dest,
        kotlin_dest=args.kotlin_dest,
        profile=args.profile,
        hook_manager=args.hooks,
    )


def cmd_verify(args: _Args) -> int:
    root = _resolve_dest(args.dest)
    doctor_status = cmd_doctor(args)
    if doctor_status:
        return doctor_status
    sync_args = _Args()
    sync_args.dest = str(root)
    sync_args.check = True
    sync_status = cmd_sync(sync_args, next_steps=False)
    if sync_status:
        return sync_status
    adopted = _declared_manifest(args)
    return _run_canonical_check(
        root,
        None if adopted is None else adopted.verify_paths,
        raw=adopted is None,
        trusted=args.trust_repository_code,
    )


def _declared_manifest(args: _Args) -> manifest.Manifest | None:
    try:
        return manifest.load(_resolve_dest(args.dest))
    except TypeError, ValueError, SystemExit:
        return None


def cmd_library_policy(args: _Args, *, selected_paths: Iterable[str] | None = None) -> int:
    from sarj_standards.libs.linting import library_policy  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    try:
        adopted = manifest.load(root)
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: invalid standards manifest: {exc}", file=sys.stderr)
        return 2
    profile = args.profile or (adopted.profile if adopted is not None else "standard")
    try:
        findings = (
            library_policy.scan(root) if selected_paths is None else library_policy.scan_paths(root, selected_paths)
        )
    except library_policy.ManifestPolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.output_format == "json":
        print(
            json.dumps(
                {
                    "profile": profile,
                    "findings": [
                        {
                            "id": finding.id,
                            "path": str(finding.path),
                            "line": finding.line,
                            "column": finding.column,
                            "package": finding.package,
                            "replacement": finding.replacement,
                            "message": finding.message,
                        }
                        for finding in findings
                    ],
                },
                indent=2,
            )
        )
    elif findings or not args.quiet:
        print("\n".join(finding.render() for finding in findings) or "library policy ✓")
    return 1 if findings else 0


def cmd_check(args: _Args) -> int:  # ruff: ignore[too-many-locals] -- staged and PR scopes retain Doctor triggers.
    from sarj_standards.libs.linting import external, runner  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    catalog_status = _check_conventional_slack_catalog(args, root)
    if catalog_status:
        return catalog_status
    repository_wide = not args.files
    pull_request_scoped = False
    react_doctor_triggered = False
    if args.staged:
        try:
            staged_names = _staged_file_names(root)
            react_doctor_triggered = _react_doctor_triggered_by(staged_names)
            staged = _safe_staged_paths(root, staged_names)
        except (OSError, subprocess.SubprocessError) as exc:
            if args.output_format != "text":
                return _emit_analysis_report(args, root, _machine_input_error(root, f"cannot read staged files: {exc}"))
            print(f"error: cannot read staged files: {exc}", file=sys.stderr)
            return 2
        if args.files:
            requested = frozenset(_repository_relative_names(root, args.files))
            selected_staged_names = [name for name in staged_names if name in requested]
            staged_set = frozenset(staged)
            args.files = [path for path in _safe_staged_paths(root, args.files) if path in staged_set]
        else:
            selected_staged_names = staged_names
            args.files = staged
        drifted = _unstaged_versions(root, selected_staged_names)
        if drifted:
            message = (
                "--staged found files with unstaged content; run through pre-commit "
                "(which safely stashes it) or stage the intended versions: " + ", ".join(drifted)
            )
            if args.output_format != "text":
                return _emit_analysis_report(args, root, _machine_input_error(root, message))
            print(f"error: {message}", file=sys.stderr)
            return 2
    elif args.files:
        try:
            args.files = _selected_paths(root, args.files)
        except ValueError as exc:
            if args.output_format != "text":
                return _emit_analysis_report(args, root, _machine_input_error(root, str(exc)))
            print(f"error: {exc}", file=sys.stderr)
            return 2
    elif (root / ".git").exists() and (base := external.change_scope_base()):
        try:
            changed_names = _changed_file_names(root, base)
            react_doctor_triggered = _react_doctor_triggered_by(changed_names)
            args.files = [
                path
                for path in _safe_staged_paths(root, changed_names)
                if runner.accepts_hook_path(Path(path), root=root)
            ]
            pull_request_scoped = True
        except (OSError, subprocess.SubprocessError) as exc:
            if args.output_format != "text":
                return _emit_analysis_report(
                    args,
                    root,
                    _machine_input_error(root, f"cannot read pull-request changes: {exc}"),
                )
            print(f"error: cannot read pull-request changes: {exc}", file=sys.stderr)
            return 2
    elif (root / ".git").exists() and external.is_non_default_github_push():
        args.files = []
        pull_request_scoped = True
    if len(args.files) == 1 and Path(args.files[0]).resolve() == root:
        args.files = []
        repository_wide = True
    if args.staged:
        health_status = _check_staged_adoption_health(root, args.files, args=args)
        if health_status:
            return health_status
        args.files = [path for path in args.files if runner.accepts_hook_path(Path(path), root=root)]
        if not args.files and not react_doctor_triggered:
            return 0
    if args.output_format != "text":
        if _validate_analysis_output(args, root):
            return 2
        args.external = True
        args.trust = "trusted" if args.trust_repository_code else "safe"
        args.analysis_mode = "policy"
        if repository_wide:
            adoption_report = _machine_adoption_gate(root)
            if adoption_report is not None:
                return _emit_analysis_report(args, root, adoption_report)
        if pull_request_scoped and not args.files:
            from sarj_standards.api import (  # ruff: ignore[import-outside-top-level]
                AnalysisMode,
                Standards,
                TrustMode,
            )

            report = Standards(root).analyze(
                (),
                external=True,
                trust=TrustMode.TRUSTED if args.trust_repository_code else TrustMode.SAFE,
                mode=AnalysisMode.POLICY,
                react_doctor_triggered=react_doctor_triggered,
            )
            return _emit_analysis_report(args, root, report)
        args.react_doctor_triggered = react_doctor_triggered
        return cmd_analyze(args)
    if pull_request_scoped:
        adoption_report = _machine_adoption_gate(root)
        if adoption_report is not None:
            return _emit_analysis_report(args, root, adoption_report)
        if not args.files:
            if react_doctor_triggered:
                return _run_canonical_check(
                    root,
                    (),
                    trusted=args.trust_repository_code,
                    react_doctor_triggered=True,
                )
            return _run_canonical_check(root, (), trusted=args.trust_repository_code)
    if not args.files:
        return cmd_verify(args)
    check_options: dict[str, bool] = {
        "trusted": args.trust_repository_code,
        "staged": args.staged,
    }
    if react_doctor_triggered:
        check_options["react_doctor_triggered"] = True
    return _run_canonical_check(root, list(args.files), **check_options)


def cmd_validate_slack_automations(args: _Args) -> int:
    root = _resolve_dest(args.dest)
    path = _catalog_path(root, args.slack_catalog)
    return _render_slack_catalog_findings(args, root, path)


def _check_conventional_slack_catalog(args: _Args, root: Path) -> int:
    from sarj_standards.libs.catalogs import CONVENTIONAL_PATH  # ruff: ignore[import-outside-top-level]

    path = root / CONVENTIONAL_PATH
    return _render_slack_catalog_findings(args, root, path) if path.exists() or path.is_symlink() else 0


def _catalog_path(root: Path, value: Path) -> Path:
    path = value if value.is_absolute() else root / value
    if not path.resolve().is_relative_to(root):
        _user_error(f"catalog path escapes repository root: {value}")
    if not path.is_file():
        _user_error(f"catalog path is not a file: {value}")
    return path


def _render_slack_catalog_findings(args: _Args, root: Path, path: Path) -> int:
    from sarj_standards.libs.catalogs import validate_catalog  # ruff: ignore[import-outside-top-level]

    findings = validate_catalog(path, root=root)
    if not findings:
        if args.cmd == "validate-slack-automations":
            print(f"Slack automation catalog ✓ ({path.relative_to(root).as_posix()})")
        return 0
    relative = path.relative_to(root)
    if args.output_format == "text":
        print("\n".join(finding.render(relative) for finding in findings))
        return 1
    from sarj_standards.libs.diagnostics import (  # ruff: ignore[import-outside-top-level]
        Completion,
        Diagnostic,
        Location,
        Severity,
        ToolReport,
    )
    from sarj_standards.libs.linting.analysis import report_from_tools  # ruff: ignore[import-outside-top-level]

    diagnostics = tuple(
        Diagnostic(
            "slack-automations.invalid",
            f"{finding.location}: {finding.message}",
            Severity.ERROR,
            "sarj-standards-slack-automations",
            Location(relative.as_posix()),
            rule_id="slack-automations.invalid",
            help="run `code-standards validate-slack-automations catalog/slack-automations.v1.json`",
        )
        for finding in findings
    )
    report = report_from_tools(
        root,
        (ToolReport("sarj-standards-slack-automations", Completion.COMPLETE, diagnostics=diagnostics),),
    )
    return _emit_analysis_report(args, root, report)


def _run_canonical_check(
    root: Path,
    paths: Sequence[str] | None,
    *,
    raw: bool = False,
    trusted: bool = False,
    staged: bool = False,
    react_doctor_triggered: bool = False,
) -> int:
    from sarj_standards.api import AnalysisMode, Standards, TrustMode  # ruff: ignore[import-outside-top-level]
    from sarj_standards.libs.diagnostics import to_text  # ruff: ignore[import-outside-top-level]

    report = Standards(root).analyze(
        paths,
        external=True,
        trust=TrustMode.TRUSTED if trusted else TrustMode.SAFE,
        mode=AnalysisMode.RAW if raw else AnalysisMode.POLICY,
        staged=staged,
        react_doctor_triggered=react_doctor_triggered,
    )
    rendered = to_text(report)
    if rendered:
        print(rendered, end="" if rendered.endswith("\n") else "\n")
    return report.exit_code


def cmd_analyze(args: _Args) -> int:
    from sarj_standards.api import (  # ruff: ignore[import-outside-top-level] -- keep CLI startup cheap
        AnalysisMode,
        Standards,
    )

    root = _resolve_dest(args.dest)
    if _validate_analysis_output(args, root):
        return 2
    report = Standards(root).analyze(
        args.files or None,
        external=args.external,
        trust=args.trust,
        mode=AnalysisMode(args.analysis_mode),
        staged=args.staged,
        react_doctor_triggered=args.react_doctor_triggered,
    )
    return _emit_analysis_report(args, root, report)


def cmd_rule_evaluate(args: _Args) -> int:
    from sarj_standards.api import AnalysisMode, Standards, TrustMode  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    if args.private_overlay is not None and args.corpus_manifest is None:
        print("error: --private-overlay requires --corpus-manifest", file=sys.stderr)
        return 2
    if args.corpus_manifest is not None:
        return _cmd_rule_evaluate_manifest(args, root)
    if _validate_analysis_output(args, root):
        return 2
    report = Standards(root).analyze(
        args.files or None,
        external=any(selector.engine.value == "eslint" for selector in args.selected_rules),
        trust=TrustMode.TRUSTED if args.trust_repository_code else TrustMode.SAFE,
        mode=(AnalysisMode.CORPUS if args.evaluation_scope is _EvaluationScope.CORPUS else AnalysisMode.POLICY),
        rules=args.selected_rules,
    )
    status = _emit_analysis_report(args, root, report)
    if args.output_format == "text" and not report.issues:
        print(_rule_evaluation_summary(report, args.selected_rules))
    return status


def _cmd_rule_evaluate_manifest(args: _Args, root: Path) -> int:
    from sarj_standards.libs.corpus import (  # ruff: ignore[import-outside-top-level]
        CorpusVisibility,
        load_manifest,
        load_private_overlay,
        merge_manifests,
    )
    from sarj_standards.libs.rules import (  # ruff: ignore[import-outside-top-level]
        CorpusLintError,
        run_isolated_corpora,
    )

    if args.files:
        print("error: positional files cannot be combined with --corpus-manifest", file=sys.stderr)
        return 2
    if args.evaluation_scope is not _EvaluationScope.CORPUS:
        print("error: --corpus-manifest requires --scope corpus", file=sys.stderr)
        return 2
    if _validate_analysis_output(args, root):
        return 2
    public_argument = args.corpus_manifest
    if public_argument is None:  # pragma: no cover - caller routes only manifest requests.
        msg = "corpus manifest routing lost its manifest"
        raise TypeError(msg)
    public_path = public_argument if public_argument.is_absolute() else root / public_argument
    private_path = args.private_overlay
    if private_path is not None and not private_path.is_absolute():
        private_path = root / private_path
    try:
        public = load_manifest(public_path)
        private = None if private_path is None else load_private_overlay(private_path)
        corpus_manifest = merge_manifests(public, private)
    except (OSError, PermissionError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    command = [
        sys.executable,
        "-I",
        "-m",
        "sarj_standards",
        "--root",
        ".",
        "maintain",
        "rules",
        "evaluate",
    ]
    for selector in args.selected_rules:
        command.extend(("--rule", str(selector)))
    command.extend(("--scope", "corpus", "--format", "json"))
    if args.trust_repository_code:
        command.append("--trust-repository-code")

    diagnostics: list[dict[str, object]] = []
    batches: list[dict[str, object]] = []

    def observe(source: object, batch: object, stdout: bytes, _stderr: bytes) -> None:
        from sarj_standards.libs.corpus import CorpusSource  # ruff: ignore[import-outside-top-level]
        from sarj_standards.libs.rules import CorpusBatchResult  # ruff: ignore[import-outside-top-level]

        if not isinstance(source, CorpusSource) or not isinstance(batch, CorpusBatchResult):
            msg = "corpus runner returned an invalid result"
            raise TypeError(msg)
        try:
            report_payload = TypeAdapter(dict[str, object]).validate_json(stdout)
            raw_diagnostics = TypeAdapter(list[dict[str, object]]).validate_python(report_payload.get("diagnostics"))
        except ValidationError as exc:
            msg = f"corpus {source.report_name} batch {batch.ordinal} returned invalid JSON"
            raise CorpusLintError(msg) from exc
        for raw in raw_diagnostics:
            if not raw:
                msg = f"corpus {source.report_name} batch {batch.ordinal} returned an invalid diagnostic"
                raise CorpusLintError(msg)
            diagnostic = _corpus_diagnostic(
                raw, source.report_name, private=source.visibility is CorpusVisibility.PRIVATE
            )
            diagnostics.append(diagnostic)
        batches.append(
            {
                "corpus": source.report_name,
                "ordinal": batch.ordinal,
                "files": batch.files,
                "findings": len(raw_diagnostics),
            }
        )

    try:
        report = run_isolated_corpora(corpus_manifest.sources, tuple(command), observer=observe)
    except (CorpusLintError, OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = {
        "schemaVersion": 1,
        "scope": "corpus",
        "rules": [str(selector) for selector in sorted(set(args.selected_rules))],
        "files": report.files,
        "batches": batches,
        "diagnostics": diagnostics,
        "exitCode": 1 if diagnostics else 0,
    }
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output_format == "text":
        lines = [
            f"{item.get('corpus')}: {item.get('findings')} finding(s) across {item.get('files')} file(s)"
            for item in batches
        ]
        lines.append(f"calibration summary: {len(diagnostics)} finding(s) across {report.files} file(s)")
        payload = "\n".join(lines) + "\n"
    if args.output is None or str(args.output) == "-":
        print(payload, end="")
    else:
        _write_report(root, args.output, payload, output_format=args.output_format)
    return 1 if diagnostics else 0


def _corpus_diagnostic(
    diagnostic: dict[str, object],
    corpus: str,
    *,
    private: bool,
) -> dict[str, object]:
    def rewrite(value: object) -> object:
        if _is_object_list(value):
            return [rewrite(item) for item in value]
        table = _object_table(value)
        if table is None:
            return value
        rewritten: dict[str, object] = {}
        for key, item in table.items():
            if key == "path" and isinstance(item, str):
                rewritten[key] = "<private-corpus-file>" if private else f"{corpus}/{item}"
            else:
                rewritten[key] = rewrite(item)
        return rewritten

    rendered = rewrite(diagnostic)
    table = _object_table(rendered)
    if table is None:  # pragma: no cover - input is a dictionary.
        msg = "corpus diagnostic rendering failed"
        raise TypeError(msg)
    return table


def _is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _object_table(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    table: dict[str, object] = {}
    for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
        if isinstance(key, str):
            table[key] = item  # ruff: ignore[manual-dict-comprehension] -- pyright needs explicit narrowing.
    return table


def cmd_observe(args: _Args) -> int:
    from sarj_standards.api import AnalysisMode, Standards, TrustMode  # ruff: ignore[import-outside-top-level]
    from sarj_standards.libs.linting.policy import warning_selectors  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    if _validate_analysis_output(args, root):
        return 2
    warning_rules = warning_selectors()
    invalid = sorted(set(args.selected_rules) - warning_rules)
    if invalid:
        rendered = ", ".join(map(str, invalid))
        print(
            f"error: observe accepts warning-stage rules only: {rendered}\n"
            f"next: code-standards maintain rules stage-warning {invalid[0]}",
            file=sys.stderr,
        )
        return 2
    report = Standards(root).analyze(
        args.files or None,
        external=any(selector.engine.value == "eslint" for selector in args.selected_rules),
        trust=TrustMode.TRUSTED if args.trust_repository_code else TrustMode.SAFE,
        mode=AnalysisMode.OBSERVE,
        rules=args.selected_rules,
    )
    return _emit_analysis_report(args, root, report)


def _rule_evaluation_summary(report: object, selectors: Sequence[RuleSelector]) -> str:
    from sarj_standards.libs.diagnostics import AnalysisReport  # ruff: ignore[import-outside-top-level]
    from sarj_standards.libs.rules import RuleEngine  # ruff: ignore[import-outside-top-level]

    if not isinstance(report, AnalysisReport):
        msg = "rule evaluation report has an invalid internal type"
        raise TypeError(msg)
    sources = {
        RuleEngine.ESLINT: frozenset(("eslint",)),
        RuleEngine.IAC: frozenset(("iac", "sarj-iac-lint")),
        RuleEngine.PYTHON: frozenset(("python", "sarj-python-lint")),
        RuleEngine.SQL: frozenset(("sql", "sarj-sql-lint")),
        RuleEngine.TEXT: frozenset(("text", "sarj-text-lint")),
    }
    lines = ["calibration summary:"]
    for selector in sorted(set(selectors)):
        count = sum(
            item.source in sources[selector.engine] and (item.rule_id or item.code) == selector.native_rule_id
            for item in report.diagnostics
        )
        noun = "finding" if count == 1 else "findings"
        lines.append(f"  {selector}: {count} {noun}")
    lines.extend(
        (
            "next: review these findings for false positives; stage an approved rule with:",
            f"  code-standards maintain rules stage-warning {min(selectors)}",
        )
    )
    return "\n".join(lines)


def _emit_analysis_report(args: _Args, root: Path, report: object) -> int:
    from sarj_standards.libs.diagnostics import (  # ruff: ignore[import-outside-top-level]
        AnalysisReport,
        to_github,
        to_json,
        to_sarif,
        to_text,
    )

    if not isinstance(report, AnalysisReport):
        msg = "analysis report has an invalid internal type"
        raise TypeError(msg)
    if args.output is not None and str(args.output) != "-" and args.output_format not in {"json", "sarif"}:
        print("error: --output is supported only with --format json or sarif", file=sys.stderr)
        return 2
    if args.output is not None and str(args.output) != "-":
        try:
            _prepare_report_parent(root, args.output)
            _report_destination(root, args.output, output_format=args.output_format)
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    match args.output_format:
        case "github":
            payload = to_github(report, max_annotations_per_level=args.max_annotations_per_level)
        case "json":
            payload = to_json(report)
        case _:
            payload = {"sarif": to_sarif, "text": to_text}[args.output_format](report)
    if args.output is None or str(args.output) == "-":
        print(payload, end="")
    else:
        _write_report(root, args.output, payload, output_format=args.output_format)
    return report.exit_code


def _validate_analysis_output(args: _Args, root: Path) -> bool:
    if args.output is None or str(args.output) == "-":
        return False
    if args.output_format not in {"json", "sarif"}:
        print("error: --output is supported only with --format json or sarif", file=sys.stderr)
        return True
    try:
        _prepare_report_parent(root, args.output)
        _report_destination(root, args.output, output_format=args.output_format)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return True
    return False


def _machine_adoption_gate(root: Path) -> object | None:
    from sarj_standards.libs.adoption import doctor, service  # ruff: ignore[import-outside-top-level]
    from sarj_standards.libs.diagnostics import (  # ruff: ignore[import-outside-top-level]
        Completion,
        Diagnostic,
        ExecutionIssue,
        Location,
        Severity,
        ToolReport,
    )
    from sarj_standards.libs.linting.analysis import report_from_tools  # ruff: ignore[import-outside-top-level]

    diagnosed = doctor.diagnose(root)
    absent = next((finding for finding in diagnosed if finding.id == "doctor.manifest.absent"), None)
    if absent is not None:
        diagnostic = Diagnostic(
            absent.id,
            absent.detail,
            Severity.ERROR,
            "sarj-standards-doctor",
            Location(manifest.MANIFEST_NAME),
            rule_id=absent.id,
            help=absent.remediation or "run `code-standards setup`",
        )
        return report_from_tools(
            root,
            (ToolReport("sarj-standards-adoption", Completion.COMPLETE, diagnostics=(diagnostic,)),),
        )
    drifted = [finding for finding in diagnosed if finding.level is doctor.Level.DRIFT]
    invalid_ids = _INVALID_DOCTOR_IDS
    issues = tuple(
        ExecutionIssue("sarj-standards-doctor", finding.id, f"{finding.where}: {finding.detail}", exit_code=2)
        for finding in drifted
        if finding.id in invalid_ids
    )
    diagnostics = tuple(
        Diagnostic(
            finding.id,
            finding.detail,
            Severity.ERROR,
            "sarj-standards-doctor",
            Location(_doctor_location(root, finding.where)),
            rule_id=finding.id,
            help=finding.remediation,
        )
        for finding in drifted
        if finding.id not in invalid_ids
    )
    try:
        sync = service.apply_sync(service.plan_sync(root), check=True)
    except (OSError, TypeError, ValueError) as exc:
        issues = (*issues, ExecutionIssue("sarj-standards-config", "config-sync-invalid", str(exc), exit_code=2))
    else:
        doctor_paths = {diagnostic.location.path for diagnostic in diagnostics}
        sync_diagnostics_list: list[Diagnostic] = []
        for record in sync.records:
            relative = record.target.destination.relative_to(root).as_posix()
            if record.outcome is not service.SyncOutcome.DRIFT or relative in doctor_paths:
                continue
            sync_diagnostics_list.append(
                Diagnostic(
                    "standards.config.sync",
                    "generated configuration differs from the installed Standards version",
                    Severity.ERROR,
                    "sarj-standards-config",
                    Location(relative),
                    rule_id="standards.config.sync",
                    help="run `code-standards update --offline`",
                )
            )
        sync_diagnostics = tuple(sync_diagnostics_list)
        diagnostics = (*diagnostics, *sync_diagnostics)
        if any(record.outcome is service.SyncOutcome.INVALID for record in sync.records):
            issues = (
                *issues,
                ExecutionIssue(
                    "sarj-standards-config",
                    "config-sync-invalid",
                    "a generated configuration destination is not a regular file",
                    exit_code=2,
                ),
            )
    if not diagnostics and not issues:
        return None
    completion = Completion.FAILED if issues else Completion.COMPLETE
    tool = ToolReport("sarj-standards-adoption", completion, diagnostics=diagnostics, issues=issues)
    return report_from_tools(root, (tool,))


def _machine_input_error(root: Path, message: str) -> object:
    from sarj_standards.libs.diagnostics import (  # ruff: ignore[import-outside-top-level] -- machine formats stay lazy
        Completion,
        ExecutionIssue,
        ToolReport,
    )
    from sarj_standards.libs.linting.analysis import (  # ruff: ignore[import-outside-top-level] -- machine formats stay lazy
        report_from_tools,
    )

    issue = ExecutionIssue("sarj-standards", "invalid-input", message, exit_code=2)
    return report_from_tools(root, (ToolReport("sarj-standards-input", Completion.FAILED, issues=(issue,)),))


def _doctor_location(root: Path, where: str) -> str:
    rendered = where.split(":", 1)[0]
    candidate = Path(rendered)
    if not candidate.is_absolute() and ".." not in candidate.parts and (root / candidate).exists():
        return candidate.as_posix()
    return manifest.MANIFEST_NAME


def _report_destination(root: Path, output: Path, *, output_format: str) -> Path:
    candidate = output if output.is_absolute() else root / output
    lexical = Path(os.path.abspath(candidate))  # ruff: ignore[os-path-abspath] -- preserve symlink components for rejection
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        msg = f"report output must stay inside repository root: {output}"
        raise OSError(msg) from exc
    current = root
    for part in relative.parent.parts:
        current /= part
        if is_link_like(current):
            msg = f"report output parent must not traverse a symlink: {current}"
            raise OSError(msg)
    destination = lexical.resolve(strict=False)
    try:
        destination.relative_to(root)
    except ValueError as exc:
        msg = f"report output must stay inside repository root: {output}"
        raise OSError(msg) from exc
    expected_suffix = destination.name.endswith(".sarif") or destination.name.endswith(".sarif.json")
    extension_matches = {
        "json": destination.suffix == ".json",
        "sarif": expected_suffix,
    }[output_format]
    if not extension_matches:
        msg = f"report output extension does not match {output_format}: {output}"
        raise OSError(msg)
    parent = destination.parent
    if not parent.is_dir():
        msg = f"report output parent does not exist: {parent}"
        raise OSError(msg)
    if destination.is_dir() or is_link_like(destination):
        msg = f"report output must be a regular file: {destination}"
        raise OSError(msg)
    return destination


def _prepare_report_parent(root: Path, output: Path) -> None:
    candidate = output if output.is_absolute() else root / output
    lexical = Path(os.path.abspath(candidate))  # ruff: ignore[os-path-abspath] -- inspect lexical parent components.
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        msg = f"report output must stay inside repository root: {output}"
        raise OSError(msg) from exc
    current = root
    for part in relative.parent.parts:
        current /= part
        if is_link_like(current):
            msg = f"report output parent must not traverse a symlink: {current}"
            raise OSError(msg)
        if current.exists() and not current.is_dir():
            msg = f"report output parent must be a directory: {current}"
            raise OSError(msg)
        current.mkdir(exist_ok=True)


def _write_report(root: Path, output: Path, payload: str, *, output_format: str) -> None:
    # Revalidate immediately before the write as a defense against a parent path
    # being replaced after the pre-analysis check.
    destination = _report_destination(root, output, output_format=output_format)
    parent = destination.parent
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            _ = handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _check_staged_adoption_health(
    root: Path,
    staged_paths: Iterable[str] = (),
    *,
    args: _Args,
) -> int:
    from sarj_standards.libs.adoption import doctor  # ruff: ignore[import-outside-top-level]

    selected = tuple(Path(path) for path in staged_paths)
    drifted = [
        finding for finding in doctor.diagnose_adoption_health(root, selected) if finding.level is doctor.Level.DRIFT
    ]
    invalid = any(finding.id in {"doctor.manifest.invalid", "doctor.package-json.invalid"} for finding in drifted)
    status = 2 if invalid else 1 if drifted else 0
    if args.output_format != "text" and status:
        from sarj_standards.libs.diagnostics import (  # ruff: ignore[import-outside-top-level]
            Completion,
            Diagnostic,
            ExecutionIssue,
            Location,
            Severity,
            ToolReport,
        )
        from sarj_standards.libs.linting.analysis import (  # ruff: ignore[import-outside-top-level]
            report_from_tools,
        )

        issues = tuple(
            ExecutionIssue("sarj-standards-doctor", finding.id, finding.detail, exit_code=2)
            for finding in drifted
            if finding.id in _INVALID_DOCTOR_IDS
        )
        diagnostics = tuple(
            Diagnostic(
                finding.id,
                finding.detail,
                Severity.ERROR,
                "sarj-standards-doctor",
                Location(_doctor_location(root, finding.where)),
                rule_id=finding.id,
                help=finding.remediation,
            )
            for finding in drifted
            if finding.id not in _INVALID_DOCTOR_IDS
        )
        completion = Completion.FAILED if issues else Completion.COMPLETE
        report = report_from_tools(
            root,
            (ToolReport("sarj-standards-adoption", completion, diagnostics=diagnostics, issues=issues),),
        )
        return _emit_analysis_report(args, root, report)
    for finding in drifted:
        print(f"drift: {finding.id} {finding.where} -- {finding.detail}")
    remediations = list(dict.fromkeys(finding.remediation for finding in drifted if finding.remediation))
    for remediation in remediations:
        print(f"fix: {remediation}")
    if invalid:
        return 2
    return 1 if drifted else 0


def _staged_file_names(root: Path) -> list[str]:
    git = shutil.which("git")
    if git is None:
        msg = "git is required for --staged"
        raise OSError(msg)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed argv, no shell.
        [git, "diff", "--cached", "--name-only", "--diff-filter=ACDMR", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
        env=_git_environment(),
    )
    names = [part.decode("utf-8", errors="surrogateescape") for part in completed.stdout.split(b"\0") if part]
    return list(dict.fromkeys(names))


def _changed_file_paths(root: Path, base: str) -> list[str]:
    return _safe_staged_paths(root, _changed_file_names(root, base))


def _changed_file_names(root: Path, base: str) -> list[str]:
    git = shutil.which("git")
    if git is None:
        msg = "git is required for pull-request change scoping"
        raise OSError(msg)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed argv, no shell.
        [git, "diff", "--name-only", "--diff-filter=ACDMR", "-z", f"{base}...HEAD", "--"],
        cwd=root,
        check=True,
        capture_output=True,
        env=_git_environment(),
    )
    return [part.decode("utf-8", errors="surrogateescape") for part in completed.stdout.split(b"\0") if part]


def _react_doctor_triggered_by(paths: Iterable[str]) -> bool:
    return any(
        Path(value).name in _REACT_DOCTOR_METADATA or Path(value).suffix.lower() in _REACT_DOCTOR_TYPESCRIPT_SUFFIXES
        for value in paths
    )


def _safe_staged_paths(root: Path, paths: Iterable[str]) -> list[str]:
    repository = root.resolve()
    safe: list[str] = []
    for raw in paths:
        if not raw:
            continue
        supplied = Path(raw)
        lexical = Path(
            os.path.abspath(  # ruff: ignore[os-path-abspath] -- preserve lexical symlink components before resolve.
                supplied if supplied.is_absolute() else repository / supplied
            )
        )
        try:
            relative = lexical.relative_to(repository)
        except ValueError:
            continue
        cursor = repository
        if any(is_link_like(cursor := cursor / part) for part in relative.parts):
            continue
        resolved = lexical.resolve()
        if resolved.is_relative_to(repository) and resolved.is_file():
            safe.append(str(resolved))
    return list(dict.fromkeys(safe))


def _unstaged_versions(root: Path, staged_paths: Iterable[str]) -> tuple[str, ...]:
    if not (root / ".git").exists():
        return ()
    git = shutil.which("git")
    if git is None:
        msg = "git is required for --staged"
        raise OSError(msg)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed argv, no shell.
        [git, "diff", "--name-only", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
        env=_git_environment(),
    )
    unstaged = {part.decode("utf-8", errors="surrogateescape") for part in completed.stdout.split(b"\0") if part}
    selected = set(_repository_relative_names(root, staged_paths))
    return tuple(sorted(unstaged & selected))


def _repository_relative_names(root: Path, paths: Iterable[str]) -> list[str]:
    repository = root.resolve()
    relative_names: list[str] = []
    for raw in paths:
        supplied = Path(raw)
        lexical = Path(
            os.path.abspath(  # ruff: ignore[os-path-abspath] -- preserve a missing worktree path lexically.
                supplied if supplied.is_absolute() else repository / supplied
            )
        )
        try:
            relative_names.append(lexical.relative_to(repository).as_posix())
        except ValueError:
            continue
    return list(dict.fromkeys(relative_names))


def _git_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- intentionally sanitize Git hook routing.
        if name in _GIT_SAFE_ENV
    }


def _selected_paths(root: Path, paths: Iterable[str]) -> list[str]:
    repository = root.resolve()
    selected: list[str] = []
    for raw in paths:
        supplied = Path(raw)
        lexical = Path(
            os.path.abspath(  # ruff: ignore[os-path-abspath] -- inspect lexical symlink components before resolve.
                supplied if supplied.is_absolute() else repository / supplied
            )
        )
        try:
            relative = lexical.relative_to(repository)
        except ValueError as exc:
            msg = f"input escapes repository root: {raw}"
            raise ValueError(msg) from exc
        cursor = repository
        if any(is_link_like(cursor := cursor / part) for part in relative.parts):
            msg = f"refusing symlink input: {raw}"
            raise ValueError(msg)
        resolved = lexical.resolve()
        if not resolved.is_relative_to(repository):
            msg = f"input escapes repository root: {raw}"
            raise ValueError(msg)
        if not resolved.exists():
            msg = f"input does not exist: {raw}"
            raise ValueError(msg)
        selected.append(str(resolved))
    return list(dict.fromkeys(selected))


def cmd_format(args: _Args) -> int:
    from sarj_standards.libs.adoption import doctor, lifecycle, scaffold  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    diagnosed = doctor.diagnose(root)
    if any(finding.id == "doctor.manifest.absent" for finding in diagnosed):
        print("error: repository is not adopted; run `code-standards setup`", file=sys.stderr)
        return 2
    drifted = [finding for finding in diagnosed if finding.level is doctor.Level.DRIFT]
    if drifted:
        for finding in drifted:
            print(f"error: {finding.id} {finding.where} -- {finding.detail}", file=sys.stderr)
        print("fix: run `code-standards doctor --repair`, then retry", file=sys.stderr)
        return 2 if any(finding.id in _INVALID_DOCTOR_IDS for finding in drifted) else 1
    if args.staged:
        try:
            args.files = _staged_files(root)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"error: cannot read staged files: {exc}", file=sys.stderr)
            return 2
    elif args.files:
        try:
            args.files = _selected_paths(root, args.files)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    adopted = _declared_manifest(args)
    ecosystems = scaffold.detect(root) if adopted is None else scaffold.detect_adopted(root, adopted)
    commands = (
        lifecycle.selected_format_commands(root, args.files) if args.files else lifecycle.format_commands(ecosystems)
    )
    return lifecycle.execute(commands)


def _staged_files(root: Path) -> list[str]:
    return _safe_staged_paths(root, _staged_file_names(root))


def cmd_inspect(args: _Args) -> int:
    from sarj_standards.libs.adoption import lifecycle  # ruff: ignore[import-outside-top-level]

    sys.stdout.write(lifecycle.inspection_json(_resolve_dest(args.dest)))
    return 0


def cmd_show(args: _Args) -> int:
    match args.show_cmd:
        case "state":
            return cmd_inspect(args)
        case "configs":
            return cmd_list()
        case "config":
            return cmd_path(args)
        case "peers":
            return cmd_peers(args)
        case "rules":
            from sarj_standards.libs.repository import rule_catalog_artifact  # ruff: ignore[import-outside-top-level]

            print(json.dumps(rule_catalog_artifact.load(), indent=2))
            return 0
        case "ci":
            from sarj_standards.libs.adoption import scaffold  # ruff: ignore[import-outside-top-level]

            root = _resolve_dest(args.dest)
            rendered = scaffold.github_ci_workflow(root)
            if args.output is None:
                print(rendered, end="")
            else:
                from sarj_standards.libs.adoption import transaction  # ruff: ignore[import-outside-top-level]

                output = args.output if args.output.is_absolute() else root / args.output
                transaction.atomic_write_text(root, output, rendered)
                print(f"wrote: {output}")
            return 0
        case _:
            return 2


def cmd_exclude(args: _Args) -> int:
    from sarj_standards.libs.adoption import exclusions  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    if args.exclude_cmd == "list":
        adopted = exclusions.read(root)
        if not adopted.excluded_paths and not adopted.excluded_rules:
            print("no exclusions; all rules apply to all paths")
            return 0
        for value in adopted.excluded_paths:
            print(f"path  {value}")
        for value in adopted.excluded_rules:
            print(f"rule  {value}")
        return 0

    kind: exclusions.ExclusionKind = "path" if args.exclude_kind == "path" else "rule"
    result = (
        exclusions.add(root, kind, args.value)
        if args.exclude_cmd == "add"
        else exclusions.remove(root, kind, args.value)
    )
    if result.changed:
        print(f"{'excluded' if result.added else 'included'} {result.kind}: {result.value}")
    else:
        print(f"already {'excluded' if result.added else 'included'} {result.kind}: {result.value}")
    return 0


def cmd_ratchet(args: _Args) -> int:
    from sarj_python_lint import run_ratchet  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    baseline = args.baseline if args.baseline is not None else root / "suppression-baseline.json"
    if args.ratchet_cmd == "init" and baseline.exists():
        print(
            f"error: suppression budget already exists: {baseline}; use `code-standards ratchet update`",
            file=sys.stderr,
        )
        return 2
    argv = [str(root), "--baseline", str(baseline)]
    for package in args.package:
        argv.extend(("--package", package))
    for subtree in args.exclude_subtree:
        argv.extend(("--exclude-subtree", subtree))
    if args.ratchet_cmd in {"init", "update"}:
        argv.append("--update")
    if args.allow_increase:
        argv.append("--allow-increase")
    return run_ratchet(argv)


_DEFAULT_DIAGNOSTIC_BASELINE = "diagnostic-baseline.json"


def cmd_baseline(args: _Args) -> int:
    from sarj_standards.api import AnalysisMode, Standards, TrustMode  # ruff: ignore[import-outside-top-level]
    from sarj_standards.libs.diagnostics import baseline  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    output = args.output if args.output is not None else root / _DEFAULT_DIAGNOSTIC_BASELINE
    if args.baseline_cmd == "init" and output.exists():
        print(
            f"error: diagnostic baseline already exists: {output}; use `code-standards baseline update`",
            file=sys.stderr,
        )
        return 2
    try:
        # `analyze` rejects anything outside the repository, so normalize the paths a
        # caller naturally types (absolute, or relative to the shell) before handing over.
        selected = _baseline_selected_paths(
            root,
            args.files,
            scoped=args.baseline_cmd == "update" and bool(args.baseline_rules),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    trust = TrustMode.TRUSTED if args.trust_repository_code else TrustMode.SAFE
    reports: list[AnalysisReport] = []
    scoped_rules = _analysis_rules_for_baseline(args.baseline_rules) if args.baseline_cmd == "update" else None
    if scoped_rules is None or scoped_rules:
        reports.append(
            Standards(root).analyze(
                selected,
                external=True,
                trust=trust,
                mode=AnalysisMode.RAW,
                rules=scoped_rules,
                include_react_doctor=False,
                pass_on_unpruned_eslint_suppressions=args.baseline_cmd == "update" and bool(args.baseline_rules),
            )
        )
    upstream_eslint = _upstream_eslint_rules_for_baseline(args.baseline_rules)
    if upstream_eslint:
        from sarj_standards.libs.linting.analysis import (  # ruff: ignore[import-outside-top-level]
            report_from_tools,
        )
        from sarj_standards.libs.linting.external import (  # ruff: ignore[import-outside-top-level]
            analyze_external,
        )

        external = report_from_tools(
            root,
            analyze_external(
                selected or [str(root)],
                root=root,
                trust=trust,
                capabilities=frozenset({"eslint"}),
                include_react_doctor=False,
                pass_on_unpruned_eslint_suppressions=True,
            ),
        )
        reports.append(external)
    if _react_doctor_rules_for_baseline(args.baseline_rules):
        reports.append(_react_doctor_baseline_report(root, selected, trust))
    if _shellcheck_rules_for_baseline(args.baseline_rules):
        from sarj_standards.libs.linting.analysis import (  # ruff: ignore[import-outside-top-level]
            report_from_tools,
        )
        from sarj_standards.libs.linting.external import (  # ruff: ignore[import-outside-top-level]
            analyze_external,
        )

        reports.append(
            report_from_tools(
                root,
                analyze_external(
                    selected or [str(root)],
                    root=root,
                    trust=trust,
                    capabilities=frozenset({"shellcheck"}),
                    include_react_doctor=False,
                ),
            )
        )
    blocked = [issue for report in reports for issue in report.issues if issue.kind != "baseline-failure"]
    if blocked:
        for issue in blocked:
            print(f"error: {issue.kind}: {issue.message}", file=sys.stderr)
        return 2
    eligible = _eligible_baseline_diagnostics(reports, args.baseline_rules)
    provenance = {
        "bundle_version": __version__,
        "consumer_base_sha": baseline.repository_base_sha(root),
        "catalog_digest": baseline.bundled_catalog_digest(),
    }
    if args.baseline_cmd == "update" and args.baseline_rules:
        if not output.is_file():
            print(f"error: scoped diagnostic baseline update requires an existing baseline: {output}", file=sys.stderr)
            return 2
        rendered = baseline.merge_scoped(
            output,
            eligible,
            selectors=_baseline_merge_selectors(args.baseline_rules),
            **provenance,
        )
    else:
        rendered = baseline.render(eligible, **provenance)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write diagnostic baseline {output}: {exc}", file=sys.stderr)
        return 2
    recorded = len(eligible)
    print(f"baseline written: {output} ({recorded} diagnostic(s) recorded)")
    adopted = manifest.load(root)
    if adopted is None or adopted.diagnostic_baseline is None:
        relative = output.relative_to(root) if output.is_relative_to(root) else output
        print(f'point the manifest at it: [baseline] diagnostics = "{relative}"')
    return 0


def _baseline_selected_paths(root: Path, files: Sequence[str], *, scoped: bool) -> list[str] | None:
    from sarj_standards.libs.diagnostics import baseline  # ruff: ignore[import-outside-top-level]

    selected = _selected_paths(root, files) if files else None
    if selected is not None or not scoped or (adopted := manifest.load(root)) is None:
        return selected
    verified = (str(root / path) for path in adopted.verify_paths)
    return list(dict.fromkeys((*verified, *baseline.tracked_terraform_test_paths(root))))


def _react_doctor_baseline_report(root: Path, selected: Sequence[str] | None, trust: str) -> AnalysisReport:
    from sarj_standards.libs.linting.analysis import (  # ruff: ignore[import-outside-top-level]
        report_from_tools,
    )
    from sarj_standards.libs.linting.external import (  # ruff: ignore[import-outside-top-level]
        analyze_external,
    )

    return report_from_tools(
        root,
        analyze_external(
            selected or [str(root)],
            root=root,
            trust=trust,
            capabilities=frozenset({"react-doctor"}),
            include_react_doctor=True,
            force_react_doctor=True,
            react_doctor_full_scan=True,
        ),
    )


def _eligible_baseline_diagnostics(
    reports: Sequence[AnalysisReport], selectors: Sequence[str]
) -> tuple[Diagnostic, ...]:
    from sarj_standards.libs.diagnostics import baseline  # ruff: ignore[import-outside-top-level]

    selected = frozenset(_baseline_merge_selectors(selectors))
    return tuple(
        item
        for report in reports
        for item in report.diagnostics
        if baseline.is_baselineable(item) and (not selectors or _diagnostic_matches(item, selected))
    )


def _analysis_rules_for_baseline(selectors: Sequence[str]) -> list[str] | None:
    if not selectors:
        return None
    normalized: list[str] = []
    for selector in selectors:
        source, separator, rule_id = selector.partition(":")
        if _is_react_doctor_selector(source=source, rule_id=rule_id, separator=bool(separator)):
            continue
        if selector == "shellcheck:*" or re.fullmatch(r"shellcheck:SC[0-9]{4}", selector) is not None:
            continue
        if separator and source in _BASELINE_RULE_SOURCE_ALIASES:
            normalized.append(f"{_BASELINE_RULE_SOURCE_ALIASES[source]}:{rule_id}")
        elif selector.startswith("eslint:@sarj/"):
            normalized.append("eslint:" + selector.removeprefix("eslint:@sarj/"))
        elif selector.startswith("eslint:"):
            if selector in _baseline_catalog_selectors():
                normalized.append(selector)
        else:
            normalized.append(selector)
    return normalized


def _upstream_eslint_rules_for_baseline(selectors: Sequence[str]) -> frozenset[str]:
    return frozenset(
        selector
        for selector in selectors
        if selector.startswith("eslint:")
        and not selector.startswith("eslint:@sarj/")
        and selector not in _baseline_catalog_selectors()
        and not _is_react_doctor_rule_id(selector.removeprefix("eslint:"))
    )


def _react_doctor_rules_for_baseline(selectors: Sequence[str]) -> frozenset[str]:
    return frozenset(
        selector
        for selector in selectors
        if (source := selector.partition(":")[0]) in _REACT_DOCTOR_RULE_SOURCES
        or (source == "eslint" and _is_react_doctor_rule_id(selector.partition(":")[2]))
    )


def _shellcheck_rules_for_baseline(selectors: Sequence[str]) -> frozenset[str]:
    return frozenset(
        selector
        for selector in selectors
        if selector == "shellcheck:*" or re.fullmatch(r"shellcheck:SC[0-9]{4}", selector) is not None
    )


def _is_react_doctor_selector(*, source: str, rule_id: str, separator: bool) -> bool:
    return separator and (
        source in _REACT_DOCTOR_RULE_SOURCES or (source == "eslint" and _is_react_doctor_rule_id(rule_id))
    )


def _is_react_doctor_rule_id(rule_id: str) -> bool:
    return rule_id.startswith(_REACT_DOCTOR_RULE_PREFIXES)


def _baseline_merge_selectors(selectors: Sequence[str]) -> tuple[str, ...]:
    resolved: list[str] = []
    catalog = _baseline_catalog()
    for requested in selectors:
        for selector in catalog.equivalents(requested):
            source, separator, rule_id = selector.partition(":")
            resolved.append(selector)
            native_source = _BASELINE_RULE_ENGINE_SOURCES.get(source)
            if selector == "react-doctor:*":
                continue
            if separator and source == "eslint" and _is_react_doctor_rule_id(rule_id):
                plugin, _, plugin_rule_id = rule_id.partition("/")
                resolved.extend((f"react-doctor:{rule_id}", f"{plugin}:{plugin_rule_id}"))
            elif separator and source == "react-hooks-js":
                resolved.append(f"react-doctor:react-hooks-js/{rule_id}")
            elif separator and source == "react-doctor" and not _is_react_doctor_rule_id(rule_id):
                resolved.append(f"react-doctor:react-doctor/{rule_id}")
            elif separator and native_source is not None:
                resolved.append(f"{native_source}:{rule_id}")
            elif separator and source == "eslint" and selector in catalog.canonical:
                resolved.append(f"eslint:@sarj/{rule_id}")
    return tuple(dict.fromkeys(resolved))


@lru_cache(maxsize=1)
def _baseline_catalog_selectors() -> frozenset[str]:
    return _baseline_catalog().canonical


@lru_cache(maxsize=1)
def _baseline_catalog() -> rule_catalog_artifact.SelectorIndex:
    from sarj_standards.libs.repository import rule_catalog_artifact  # ruff: ignore[import-outside-top-level]

    return rule_catalog_artifact.selector_index()


def _diagnostic_matches(item: Diagnostic, selectors: frozenset[str]) -> bool:
    return item.rule_id is not None and (
        f"{item.source}:*" in selectors or f"{item.source}:{item.rule_id}" in selectors
    )


def cmd_commit_message(args: _Args) -> int:
    if args.message_file is None:
        msg = "commit-message requires one message file"
        raise ValueError(msg)
    result = check_local_commit_message_file(
        args.message_file,
        root=_resolve_dest(args.dest),
        fix_safe=True,
    )
    if result.fix_applied:
        print("Commit message: safely normalized; validation passed.")
        return 0
    if result.satisfied:
        return 0
    finding = result.findings[0]
    print(f"Commit message: {finding.code}", file=sys.stderr)
    print(finding.message, file=sys.stderr)
    print(f"Fix: {finding.remediation}", file=sys.stderr)
    print(
        "Agent: preserve the body and trailers, rewrite only the subject after reviewing staged changes, "
        "then retry the original commit.",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    raw_argv = _root_option_first(sys.argv[1:] if argv is None else argv)
    status: int | None = None

    def dispatch(args: _Args) -> int:
        nonlocal status
        status = _dispatch(args)
        return status

    try:
        try:
            build_app(dispatch)(raw_argv, prog_name="code-standards")
        except SystemExit as exc:
            if status is None or exc.code != 0:
                raise
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    else:
        return status if status is not None else 0


def _root_option_first(argv: list[str]) -> list[str]:
    equals_positions = [index for index, value in enumerate(argv) if value.startswith("--root=")]
    if equals_positions:
        if len(equals_positions) != 1:
            return argv
        index = equals_positions[0]
        value = argv[index].partition("=")[2]
        return ["--root", value, *argv[:index], *argv[index + 1 :]]
    positions = [index for index, value in enumerate(argv) if value == "--root"]
    if not positions or positions == [0] or len(positions) != 1:
        return argv
    index = positions[0]
    if index + 1 >= len(argv):
        return argv
    return ["--root", argv[index + 1], *argv[:index], *argv[index + 2 :]]


def _dispatch(args: _Args) -> int:
    match args.cmd:
        case "doctor":
            return cmd_doctor(args)
        case "update":
            return cmd_update(args)
        case "setup":
            return cmd_setup(args)
        case "fix":
            return cmd_format(args)
        case "check":
            return cmd_check(args)
        case "commit-message":
            return cmd_commit_message(args)
        case "validate-slack-automations":
            return cmd_validate_slack_automations(args)
        case "observe":
            return cmd_observe(args)
        case "show":
            return cmd_show(args)
        case "exclude":
            return cmd_exclude(args)
        case "ratchet":
            return cmd_ratchet(args)
        case "baseline":
            return cmd_baseline(args)
        case "maintain":
            return _cmd_repo(args)
        case _:  # Typer requires a registered command before dispatch.
            return 2


class _ChoiceDoctorOutputFormat(StrEnum):
    VALUE_0 = "text"
    VALUE_1 = "json"


class _ChoiceSetupHooks(StrEnum):
    VALUE_0 = "pre-commit"
    VALUE_1 = "lefthook"
    VALUE_2 = "none"


class _ChoiceSetupProfile(StrEnum):
    VALUE_0 = "standard"
    VALUE_1 = "application"


class _ChoiceSetupOnly(StrEnum):
    VALUE_0 = "detekt"
    VALUE_1 = "eslint"
    VALUE_2 = "ktlint"
    VALUE_3 = "markdownlint"
    VALUE_4 = "mobile-security"
    VALUE_5 = "pyright"
    VALUE_6 = "ruff"
    VALUE_7 = "shellcheck"
    VALUE_8 = "swiftformat"
    VALUE_9 = "swiftlint"
    VALUE_10 = "taplo"
    VALUE_11 = "yamllint"


class _ChoiceCheckOutputFormat(StrEnum):
    VALUE_0 = "text"
    VALUE_1 = "json"
    VALUE_2 = "sarif"
    VALUE_3 = "github"


class _ChoiceObserveOutputFormat(StrEnum):
    VALUE_0 = "text"
    VALUE_1 = "json"
    VALUE_2 = "sarif"
    VALUE_3 = "github"


class _ChoiceExcludeAddExcludeKind(StrEnum):
    VALUE_0 = "path"
    VALUE_1 = "rule"


class _ChoiceExcludeRemoveExcludeKind(StrEnum):
    VALUE_0 = "path"
    VALUE_1 = "rule"


class _ChoiceShowConfigName(StrEnum):
    VALUE_0 = "detekt"
    VALUE_1 = "eslint"
    VALUE_2 = "ktlint"
    VALUE_3 = "markdownlint"
    VALUE_4 = "mobile-security"
    VALUE_5 = "pyright"
    VALUE_6 = "ruff"
    VALUE_7 = "shellcheck"
    VALUE_8 = "swiftformat"
    VALUE_9 = "swiftlint"
    VALUE_10 = "taplo"
    VALUE_11 = "yamllint"


class _ChoiceShowConfigProfile(StrEnum):
    VALUE_0 = "standard"
    VALUE_1 = "application"


class _ChoiceMaintainReleaseCreateTagsReleaseTargets(StrEnum):
    VALUE_0 = "typescript"
    VALUE_1 = "bootstrap"
    VALUE_2 = "python"
    VALUE_3 = "sql"
    VALUE_4 = "iac"
    VALUE_5 = "standards"
    VALUE_6 = "tsconfig"


class _ChoiceMaintainReleaseTypescriptReleaseMode(StrEnum):
    VALUE_0 = "check"
    VALUE_1 = "pack"
    VALUE_2 = "publish"


class _ChoiceMaintainReleasePublishReleaseTarget(StrEnum):
    VALUE_0 = "typescript"
    VALUE_1 = "bootstrap"
    VALUE_2 = "python"
    VALUE_3 = "sql"
    VALUE_4 = "iac"
    VALUE_5 = "standards"
    VALUE_6 = "tsconfig"


class _ChoiceMaintainCheckRepoOnly(StrEnum):
    VALUE_0 = "ci-history"
    VALUE_1 = "file-conventions"
    VALUE_2 = "private-refs"
    VALUE_3 = "versions"


class _ChoiceMaintainRulesNewRuleCategory(StrEnum):
    VALUE_0 = "architecture"
    VALUE_1 = "correctness"
    VALUE_2 = "maintainability"
    VALUE_3 = "performance"
    VALUE_4 = "security"
    VALUE_5 = "style"
    VALUE_6 = "testing"


class _ChoiceMaintainRulesChangesOutputFormat(StrEnum):
    VALUE_0 = "json"
    VALUE_1 = "text"


class _ChoiceMaintainRulesChangesRequiredAddedLevel(StrEnum):
    VALUE_0 = "warning"


class _ChoiceMaintainRulesEvaluateOutputFormat(StrEnum):
    VALUE_0 = "json"
    VALUE_1 = "text"


def _version_option(*, value: bool) -> None:
    if value:
        print(f"code-standards {__version__}")
        raise typer.Exit


def build_app(handler: Callable[[_Args], int] = _dispatch) -> typer.Typer:
    app = typer.Typer(
        name="code-standards",
        help=f"Adopt, check, fix, diagnose, and update sarj-ai standards (v{__version__}).",
        epilog="Start with `code-standards setup`, then use `code-standards check`.",
        no_args_is_help=False,
        add_completion=False,
        rich_markup_mode=None,
        pretty_exceptions_enable=False,
        context_settings={"help_option_names": ["-h", "--help"]},
    )

    @app.callback()
    def root(
        ctx: typer.Context,
        *,
        dest: Annotated[
            str,
            typer.Option("--root", help="repository root shared by the selected command (default: current directory)"),
        ] = ".",
        _version: Annotated[bool, typer.Option("--version", callback=_version_option, is_eager=True)] = False,
    ) -> None:
        ctx.obj = dest

    group_baseline = typer.Typer(no_args_is_help=False, help="grandfather today's findings so only new ones fail")
    app.add_typer(group_baseline, name="baseline")
    group_ratchet = typer.Typer(no_args_is_help=False, help="keep the Python suppression budget from growing")
    app.add_typer(group_ratchet, name="ratchet")
    group_exclude = typer.Typer(no_args_is_help=False, help="inspect or change explicit path and rule exclusions")
    app.add_typer(group_exclude, name="exclude")
    group_show = typer.Typer(no_args_is_help=False, help="print read-only package and adoption information")
    app.add_typer(group_show, name="show")
    group_maintain = typer.Typer(no_args_is_help=False, help="repository policy, hooks, rule ledgers, and releases")
    app.add_typer(group_maintain, name="maintain")
    group_maintain_release = typer.Typer(no_args_is_help=False, help="validate and build publishable release artifacts")
    group_maintain.add_typer(group_maintain_release, name="release")
    group_maintain_docs = typer.Typer(no_args_is_help=False, help="check or synchronize source-derived documentation")
    group_maintain.add_typer(group_maintain_docs, name="docs")
    group_maintain_hooks = typer.Typer(no_args_is_help=False, help="manage the pinned repository hooks")
    group_maintain.add_typer(group_maintain_hooks, name="hooks")
    group_maintain_rules = typer.Typer(no_args_is_help=False, help="inspect live custom rules")
    group_maintain.add_typer(group_maintain_rules, name="rules")
    group_maintain_catalog = typer.Typer(no_args_is_help=False, help="maintain the source-derived public rule catalog")
    group_maintain.add_typer(group_maintain_catalog, name="catalog")
    group_maintain_cli_reference = typer.Typer(no_args_is_help=False, help="maintain the source-derived CLI reference")
    group_maintain.add_typer(group_maintain_cli_reference, name="cli-reference")

    @app.command("commit-message", help="enforce [(i/N) ][TICKET] type(scope)!: description with safe mechanical fixes")
    def command_commit_message(
        ctx: typer.Context,
        *,
        message_file: Annotated[
            Path,
            typer.Argument(help="Git commit-message file supplied by the commit-msg hook", metavar="COMMIT_MSG_FILE"),
        ],
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="commit-message",
                message_file=message_file,
            )
        )

    @app.command("doctor", help="diagnose adoption health and optionally repair safe drift")
    def command_doctor(
        ctx: typer.Context,
        *,
        output_format: Annotated[
            _ChoiceDoctorOutputFormat, typer.Option("--format", help="output format (default: text)")
        ] = _ChoiceDoctorOutputFormat.VALUE_0,
        repair: Annotated[
            bool,
            typer.Option(
                "--repair",
                help="transactionally repair safe drift with the executing bundle, then re-diagnose",
            ),
        ] = False,
        no_install: Annotated[
            bool,
            typer.Option(
                "--no-install",
                help="with --repair, update configuration without installing dependencies or hooks",
            ),
        ] = False,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="doctor",
                output_format=output_format.value,
                repair=repair,
                no_install=no_install,
            )
        )

    @app.command("setup", help="adopt or converge the repository in one idempotent operation")
    def command_setup(
        ctx: typer.Context,
        *,
        hooks: Annotated[
            _ChoiceSetupHooks | None,
            typer.Option("--hooks", help="hook manager (default: detect Lefthook, otherwise pre-commit)"),
        ] = None,
        python_dest: Annotated[
            str | None, typer.Option("--python-dest", help="the directory that owns pyproject.toml (default: detected)")
        ] = None,
        typescript_dest: Annotated[
            str | None,
            typer.Option("--typescript-dest", help="the directory that owns the npm lockfile (default: detected)"),
        ] = None,
        swift_dest: Annotated[
            str | None,
            typer.Option(
                "--swift-dest",
                help="the directory that owns one reviewed Swift project (default: mobile project detection)",
            ),
        ] = None,
        kotlin_dest: Annotated[
            str | None,
            typer.Option(
                "--kotlin-dest", help="the directory that owns one reviewed Android/KMP project (default: detected)"
            ),
        ] = None,
        dry_run: Annotated[bool, typer.Option("--dry-run", help="print the complete plan without writing")] = False,
        force: Annotated[
            bool,
            typer.Option("--force", help="replace conflicting generated lint configuration after review"),
        ] = False,
        profile: Annotated[_ChoiceSetupProfile | None, typer.Option("--profile", hidden=True)] = None,
        no_install: Annotated[
            bool,
            typer.Option("--no-install", help="write wiring without installing dependencies or hooks"),
        ] = False,
        commit_policy_only: Annotated[
            bool,
            typer.Option(
                "--commit-policy-only",
                help="adopt only commit-message and PR-history policy without changing language tooling",
            ),
        ] = False,
        only: Annotated[
            list[_ChoiceSetupOnly] | None, typer.Option("--config", help="select one config explicitly (repeatable)")
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="setup",
                hooks=hooks.value if hooks is not None else None,
                python_dest=python_dest if python_dest is not None else None,
                typescript_dest=typescript_dest if typescript_dest is not None else None,
                swift_dest=swift_dest if swift_dest is not None else None,
                kotlin_dest=kotlin_dest if kotlin_dest is not None else None,
                dry_run=dry_run,
                force=force,
                profile=profile.value if profile is not None else None,
                no_install=no_install,
                commit_policy_only=commit_policy_only,
                only=[item.value for item in only] if only is not None else [],
            )
        )

    @app.command("check", help="run the complete quality gate or check selected paths")
    def command_check(
        ctx: typer.Context,
        *,
        trust_repository_code: Annotated[
            bool,
            typer.Option(
                "--trust-repository-code",
                help="allow executable repository ESLint configuration (generated hooks and CI set this explicitly)",
            ),
        ] = False,
        staged: Annotated[
            bool,
            typer.Option(
                "--staged",
                help="run custom rules on hook-supplied paths, or discover staged files when none are supplied",
            ),
        ] = False,
        output_format: Annotated[_ChoiceCheckOutputFormat, typer.Option("--format")] = _ChoiceCheckOutputFormat.VALUE_0,
        output: Annotated[Path | None, typer.Option("--output", help="write JSON or SARIF atomically to PATH")] = None,
        max_annotations_per_level: Annotated[int, typer.Option("--max-annotations-per-level", min=0, max=10)] = 10,
        files: Annotated[
            list[str] | None, typer.Argument(help="selected paths; when omitted, check the complete repository")
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="check",
                trust_repository_code=trust_repository_code,
                staged=staged,
                output_format=output_format.value,
                output=output if output is not None else None,
                max_annotations_per_level=max_annotations_per_level,
                files=files if files is not None else [],
            )
        )

    @app.command("validate-slack-automations", help="validate a versioned Slack automation catalog")
    def command_validate_slack_automations(
        ctx: typer.Context,
        *,
        slack_catalog: Annotated[Path, typer.Argument(metavar="PATH")],
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="validate-slack-automations",
                slack_catalog=slack_catalog,
            )
        )

    @app.command("observe", help="report warning-stage findings with exit 0; invalid input or execution still exits 2")
    def command_observe(
        ctx: typer.Context,
        *,
        selected_rules: Annotated[
            list[RuleSelector],
            typer.Option("--rule", parser=_parse_rule_selector, help="canonical ENGINE:ID selector (repeatable)"),
        ],
        output_format: Annotated[
            _ChoiceObserveOutputFormat, typer.Option("--format")
        ] = _ChoiceObserveOutputFormat.VALUE_0,
        output: Annotated[Path | None, typer.Option("--output")] = None,
        trust_repository_code: Annotated[
            bool,
            typer.Option("--trust-repository-code", help="allow repository ESLint configuration to execute"),
        ] = False,
        max_annotations_per_level: Annotated[int, typer.Option("--max-annotations-per-level")] = 10,
        files: Annotated[
            list[str] | None, typer.Argument(help="selected paths; defaults to adopted verification paths")
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="observe",
                selected_rules=selected_rules,
                output_format=output_format.value,
                output=output if output is not None else None,
                trust_repository_code=trust_repository_code,
                max_annotations_per_level=max_annotations_per_level,
                files=files if files is not None else [],
            )
        )

    @app.command("fix", help="apply safe formatting and lint fixes")
    def command_fix(
        ctx: typer.Context,
        *,
        staged: Annotated[bool, typer.Option("--staged", help="fix only files staged in Git")] = False,
        files: Annotated[
            list[str] | None, typer.Argument(help="selected paths; when omitted, fix the complete repository")
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="fix",
                staged=staged,
                files=files if files is not None else [],
            )
        )

    @app.command("update", help="upgrade to the latest published coherent Standards bundle")
    def command_update(
        ctx: typer.Context,
        *,
        check: Annotated[
            bool, typer.Option("--check", help="preview without writing; exit 1 when changes exist")
        ] = False,
        offline: Annotated[
            bool,
            typer.Option(
                "--offline",
                help="reconverge the executing bundle and skip every network-dependent install; does not resolve latest",
            ),
        ] = False,
        target_version: Annotated[
            str | None,
            typer.Option(
                "--to", help="resolve and apply exactly this immutable coherent bundle version", metavar="VERSION"
            ),
        ] = None,
        no_install: Annotated[bool, typer.Option("--no-install", help="do not install dependencies or hooks")] = False,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="update",
                check=check,
                offline=offline,
                target_version=target_version if target_version is not None else None,
                no_install=no_install,
            )
        )

    @group_baseline.command("init", help="record the first diagnostic baseline")
    def command_baseline_init(
        ctx: typer.Context,
        *,
        output: Annotated[
            Path | None, typer.Option("--output", help="baseline JSON (default: diagnostic-baseline.json)")
        ] = None,
        trust_repository_code: Annotated[
            bool,
            typer.Option("--trust-repository-code", help="run repository-local analyzers that execute project code"),
        ] = False,
        files: Annotated[
            list[str] | None, typer.Argument(help="paths to analyze (default: the whole repository)")
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="baseline",
                baseline_cmd="init",
                output=output if output is not None else None,
                trust_repository_code=trust_repository_code,
                files=files if files is not None else [],
            )
        )

    @group_baseline.command("update", help="re-record the diagnostic baseline after reviewed cleanup")
    def command_baseline_update(
        ctx: typer.Context,
        *,
        output: Annotated[
            Path | None, typer.Option("--output", help="baseline JSON (default: diagnostic-baseline.json)")
        ] = None,
        trust_repository_code: Annotated[
            bool,
            typer.Option("--trust-repository-code", help="run repository-local analyzers that execute project code"),
        ] = False,
        baseline_rules: Annotated[
            list[str] | None,
            typer.Option(
                "--rule",
                help="replace debt only for this newly promoted rule (repeatable; source:RULE is also accepted)",
            ),
        ] = None,
        files: Annotated[
            list[str] | None, typer.Argument(help="paths to analyze (default: the whole repository)")
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="baseline",
                baseline_cmd="update",
                output=output if output is not None else None,
                trust_repository_code=trust_repository_code,
                baseline_rules=baseline_rules if baseline_rules is not None else [],
                files=files if files is not None else [],
            )
        )

    @group_ratchet.command("init", help="create the first suppression budget")
    def command_ratchet_init(
        ctx: typer.Context,
        *,
        baseline: Annotated[
            Path | None, typer.Option("--baseline", help="budget JSON (default: suppression-baseline.json)")
        ] = None,
        package: Annotated[list[str] | None, typer.Option("--package", help="Python package root (repeatable)")] = None,
        exclude_subtree: Annotated[
            list[str] | None,
            typer.Option(
                "--exclude-subtree", help="generated or vendored subtree to persistently exclude (repeatable)"
            ),
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="ratchet",
                ratchet_cmd="init",
                baseline=baseline if baseline is not None else None,
                package=package if package is not None else [],
                exclude_subtree=exclude_subtree if exclude_subtree is not None else [],
            )
        )

    @group_ratchet.command("check", help="fail when suppression debt grows")
    def command_ratchet_check(
        ctx: typer.Context,
        *,
        baseline: Annotated[
            Path | None, typer.Option("--baseline", help="budget JSON (default: suppression-baseline.json)")
        ] = None,
        package: Annotated[list[str] | None, typer.Option("--package", help="Python package root (repeatable)")] = None,
        exclude_subtree: Annotated[
            list[str] | None,
            typer.Option(
                "--exclude-subtree", help="generated or vendored subtree to persistently exclude (repeatable)"
            ),
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="ratchet",
                ratchet_cmd="check",
                baseline=baseline if baseline is not None else None,
                package=package if package is not None else [],
                exclude_subtree=exclude_subtree if exclude_subtree is not None else [],
            )
        )

    @group_ratchet.command("status", help="show current suppression debt and available reductions")
    def command_ratchet_status(
        ctx: typer.Context,
        *,
        baseline: Annotated[
            Path | None, typer.Option("--baseline", help="budget JSON (default: suppression-baseline.json)")
        ] = None,
        package: Annotated[list[str] | None, typer.Option("--package", help="Python package root (repeatable)")] = None,
        exclude_subtree: Annotated[
            list[str] | None,
            typer.Option(
                "--exclude-subtree", help="generated or vendored subtree to persistently exclude (repeatable)"
            ),
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="ratchet",
                ratchet_cmd="status",
                baseline=baseline if baseline is not None else None,
                package=package if package is not None else [],
                exclude_subtree=exclude_subtree if exclude_subtree is not None else [],
            )
        )

    @group_ratchet.command("update", help="lock in reviewed suppression-budget changes")
    def command_ratchet_update(
        ctx: typer.Context,
        *,
        baseline: Annotated[
            Path | None, typer.Option("--baseline", help="budget JSON (default: suppression-baseline.json)")
        ] = None,
        package: Annotated[list[str] | None, typer.Option("--package", help="Python package root (repeatable)")] = None,
        exclude_subtree: Annotated[
            list[str] | None,
            typer.Option(
                "--exclude-subtree", help="generated or vendored subtree to persistently exclude (repeatable)"
            ),
        ] = None,
        allow_increase: Annotated[
            bool, typer.Option("--allow-increase", help="permit a reviewed increase in suppression debt")
        ] = False,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="ratchet",
                ratchet_cmd="update",
                baseline=baseline if baseline is not None else None,
                package=package if package is not None else [],
                exclude_subtree=exclude_subtree if exclude_subtree is not None else [],
                allow_increase=allow_increase,
            )
        )

    @group_exclude.command("list", help="list the complete denylist")
    def command_exclude_list(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="exclude",
                exclude_cmd="list",
            )
        )

    @group_exclude.command("add", help="add one exact denylist entry")
    def command_exclude_add(
        ctx: typer.Context,
        *,
        exclude_kind: Annotated[_ChoiceExcludeAddExcludeKind, typer.Argument(metavar="{path,rule}")],
        value: Annotated[str, typer.Argument(help="repository-relative glob or canonical engine:rule selector")],
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="exclude",
                exclude_cmd="add",
                exclude_kind=exclude_kind.value,
                value=value,
            )
        )

    @group_exclude.command("remove", help="remove one exact denylist entry")
    def command_exclude_remove(
        ctx: typer.Context,
        *,
        exclude_kind: Annotated[_ChoiceExcludeRemoveExcludeKind, typer.Argument(metavar="{path,rule}")],
        value: Annotated[str, typer.Argument(help="repository-relative glob or canonical engine:rule selector")],
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="exclude",
                exclude_cmd="remove",
                exclude_kind=exclude_kind.value,
                value=value,
            )
        )

    @group_show.command("state", help="print detected adoption state as JSON")
    def command_show_state(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="show",
                show_cmd="state",
            )
        )

    @group_show.command("configs", help="list bundled configurations")
    def command_show_configs(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="show",
                show_cmd="configs",
            )
        )

    @group_show.command("config", help="print one bundled configuration path")
    def command_show_config(
        ctx: typer.Context,
        *,
        name: Annotated[_ChoiceShowConfigName, typer.Argument()],
        profile: Annotated[
            _ChoiceShowConfigProfile, typer.Option("--profile", hidden=True)
        ] = _ChoiceShowConfigProfile.VALUE_0,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="show",
                show_cmd="config",
                name=name.value,
                profile=profile.value,
            )
        )

    @group_show.command("peers", help="show tested ESLint peer dependencies and install command")
    def command_show_peers(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="show",
                show_cmd="peers",
            )
        )

    @group_show.command("rules", help="print the machine-readable custom-rule inventory")
    def command_show_rules(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="show",
                show_cmd="rules",
            )
        )

    @group_show.command("ci", help="print a complete versioned GitHub Actions standards workflow")
    def command_show_ci(
        ctx: typer.Context,
        *,
        output: Annotated[
            Path | None, typer.Option("--output", help="write a managed workflow inside the repository")
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="show",
                show_cmd="ci",
                output=output if output is not None else None,
            )
        )

    @group_maintain.command("setup", help="install every standards development environment and repository hook")
    def command_maintain_setup(
        ctx: typer.Context,
        *,
        check: Annotated[
            bool, typer.Option("--check", help="print the deterministic setup plan without executing it")
        ] = False,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="setup",
                check=check,
            )
        )

    @group_maintain_release.command("check-tag", help="require a release tag to match its package manifest")
    def command_maintain_release_check_tag(
        ctx: typer.Context,
        *,
        tag: Annotated[str, typer.Argument()],
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="release",
                release_cmd="check-tag",
                tag=tag,
            )
        )

    @group_maintain_release.command("verify-tags", help="verify all manifest release tags on origin")
    def command_maintain_release_verify_tags(
        ctx: typer.Context,
        *,
        release_commit: Annotated[
            str | None,
            typer.Option(
                "--commit",
                help="also require existing tags to match this publishing commit or an unchanged package tree",
            ),
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="release",
                release_cmd="verify-tags",
                release_commit=release_commit or "",
            )
        )

    @group_maintain_release.command("create-tags", help="create and push manifest release tags")
    def command_maintain_release_create_tags(
        ctx: typer.Context,
        *,
        release_targets: Annotated[list[_ChoiceMaintainReleaseCreateTagsReleaseTargets], typer.Argument()],
        release_commit: Annotated[str, typer.Option("--commit", help="exact commit that was published")],
        attempts: Annotated[int, typer.Option("--attempts")] = 6,
        delay_seconds: Annotated[float, typer.Option("--delay-seconds")] = 10.0,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="release",
                release_cmd="create-tags",
                release_targets=[item.value for item in release_targets],
                release_commit=release_commit,
                attempts=attempts,
                delay_seconds=timedelta(seconds=delay_seconds),
            )
        )

    @group_maintain_release.command("changes", help="emit package version changes between Git revisions")
    def command_maintain_release_changes(
        ctx: typer.Context,
        *,
        before: Annotated[str, typer.Option("--before")],
        after: Annotated[str, typer.Option("--after")],
        github_output: Annotated[Path, typer.Option("--github-output")],
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="release",
                release_cmd="changes",
                before=before,
                after=after,
                github_output=github_output,
            )
        )

    @group_maintain_release.command("causality", help="require every publishable package change to bump its version")
    def command_maintain_release_causality(
        ctx: typer.Context,
        *,
        before: Annotated[str, typer.Option("--before")],
        after: Annotated[str, typer.Option("--after")],
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="release",
                release_cmd="causality",
                before=before,
                after=after,
            )
        )

    @group_maintain_release.command("lock-age", help="enforce npm lockfile minimum release age")
    def command_maintain_release_lock_age(
        ctx: typer.Context,
        *,
        lockfile: Annotated[Path, typer.Argument()],
        minimum_age: Annotated[int | None, typer.Option("--minimum-days")] = None,
        release_exclude: Annotated[list[str] | None, typer.Option("--exclude")] = None,
        release_exclude_file: Annotated[
            list[Path] | None,
            typer.Option("--exclude-file", help="line-oriented exact package@version exceptions (repeatable)"),
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="release",
                release_cmd="lock-age",
                lockfile=lockfile,
                minimum_age=timedelta(days=minimum_age) if minimum_age is not None else None,
                release_exclude=release_exclude if release_exclude is not None else [],
                release_exclude_file=release_exclude_file if release_exclude_file is not None else [],
            )
        )

    @group_maintain_release.command("typescript", help="check, pack, or publish the TypeScript package")
    def command_maintain_release_typescript(
        ctx: typer.Context,
        *,
        release_mode: Annotated[_ChoiceMaintainReleaseTypescriptReleaseMode, typer.Argument()],
        output: Annotated[Path | None, typer.Option("--output", help="artifact directory (required for pack)")] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="release",
                release_cmd="typescript",
                release_mode=release_mode.value,
                output=output if output is not None else None,
            )
        )

    @group_maintain_release.command("verify-wheel", help="require non-empty license text in built Python wheels")
    def command_maintain_release_verify_wheel(
        ctx: typer.Context,
        *,
        wheels: Annotated[list[Path], typer.Argument()],
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="release",
                release_cmd="verify-wheel",
                wheels=wheels,
            )
        )

    @group_maintain_release.command(
        "verify-publications", help="wait for every exact sibling publication required by Standards"
    )
    def command_maintain_release_verify_publications(
        ctx: typer.Context,
        *,
        attempts: Annotated[int, typer.Option("--attempts")] = 6,
        delay_seconds: Annotated[float, typer.Option("--delay-seconds")] = 10.0,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="release",
                release_cmd="verify-publications",
                attempts=attempts,
                delay_seconds=timedelta(seconds=delay_seconds),
            )
        )

    @group_maintain_release.command("publish", help="build and publish one package through its native client")
    def command_maintain_release_publish(
        ctx: typer.Context,
        *,
        release_target: Annotated[_ChoiceMaintainReleasePublishReleaseTarget, typer.Argument()],
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="release",
                release_cmd="publish",
                release_target=release_target.value,
            )
        )

    @group_maintain.command("check", help="run repository policy gates")
    def command_maintain_check(
        ctx: typer.Context,
        *,
        repo_only: Annotated[list[_ChoiceMaintainCheckRepoOnly] | None, typer.Option("--only")] = None,
        commits: Annotated[
            str | None, typer.Option("--commits", help="also inspect commit messages in this revision range")
        ] = None,
        policy_dest: Annotated[
            str | None, typer.Option("--policy-root", help="trusted repository policy root (default: --root)")
        ] = None,
        private_refs_file: Annotated[
            str | None,
            typer.Option("--private-refs-file", help="private-reference TOML outside the scanned repository"),
        ] = None,
        quiet: Annotated[bool, typer.Option("--quiet", help="hide finding details")] = False,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="check",
                repo_only=[item.value for item in repo_only] if repo_only is not None else [],
                commits=commits if commits is not None else None,
                policy_dest=policy_dest if policy_dest is not None else None,
                private_refs_file=private_refs_file if private_refs_file is not None else None,
                quiet=quiet,
            )
        )

    @group_maintain.command("sync-ledger", help="synchronize the rule compatibility ledger")
    def command_maintain_sync_ledger(
        ctx: typer.Context,
        *,
        check: Annotated[bool, typer.Option("--check", help="report drift without writing")] = False,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="sync-ledger",
                check=check,
            )
        )

    @group_maintain_docs.command("check", help="")
    def command_maintain_docs_check(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="docs",
                docs_cmd="check",
            )
        )

    @group_maintain_docs.command("sync", help="")
    def command_maintain_docs_sync(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="docs",
                docs_cmd="sync",
            )
        )

    @group_maintain.command("comment-corpus", help="extract comments for calibration")
    def command_maintain_comment_corpus(
        ctx: typer.Context,
        *,
        roots: Annotated[list[Path], typer.Argument()],
        include_text: Annotated[
            Path | None,
            typer.Option(
                "--include-text",
                help="write sensitive comment text to a new owner-readable file",
                metavar="PRIVATE_JSONL",
            ),
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="comment-corpus",
                roots=roots,
                include_text=include_text if include_text is not None else None,
            )
        )

    @group_maintain_hooks.command("install", help="install Lefthook")
    def command_maintain_hooks_install(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="hooks",
                hooks_cmd="install",
            )
        )

    @group_maintain_rules.command("manifest", help="print the shipped rule inventory")
    def command_maintain_rules_manifest(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="rules",
                rules_cmd="manifest",
            )
        )

    @group_maintain_rules.command("check", help="verify the shipped rule inventory matches live registries")
    def command_maintain_rules_check(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="rules",
                rules_cmd="check",
            )
        )

    @group_maintain_rules.command("sync", help="update the shipped rule inventory from live registries")
    def command_maintain_rules_sync(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="rules",
                rules_cmd="sync",
            )
        )

    @group_maintain_rules.command("new", help="plan or create author-owned rule and test skeletons")
    def command_maintain_rules_new(
        ctx: typer.Context,
        *,
        selector: Annotated[
            RuleSelector, typer.Argument(parser=_parse_rule_selector, help="canonical ENGINE:ID selector")
        ],
        rule_category: Annotated[_ChoiceMaintainRulesNewRuleCategory, typer.Option("--category")],
        rule_summary: Annotated[str, typer.Option("--summary")],
        apply_rule: Annotated[bool, typer.Option("--apply", help="create the planned files")] = False,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="rules",
                rules_cmd="new",
                selector=selector,
                rule_category=rule_category.value,
                rule_summary=rule_summary,
                apply_rule=apply_rule,
            )
        )

    @group_maintain_rules.command("stage-warning", help="prepare one registered rule for warning-first publication")
    def command_maintain_rules_stage_warning(
        ctx: typer.Context,
        *,
        selector: Annotated[
            RuleSelector, typer.Argument(parser=_parse_rule_selector, help="canonical ENGINE:ID selector")
        ],
        check: Annotated[bool, typer.Option("--check", help="report required staging without writing")] = False,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="rules",
                rules_cmd="stage-warning",
                selector=selector,
                check=check,
            )
        )

    @group_maintain_rules.command(
        "prepare", help="validate and prepare one registered rule for warning-first publication"
    )
    def command_maintain_rules_prepare(
        ctx: typer.Context,
        *,
        selector: Annotated[
            RuleSelector, typer.Argument(parser=_parse_rule_selector, help="canonical ENGINE:ID selector")
        ],
        check: Annotated[bool, typer.Option("--check", help="report required preparation without writing")] = False,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="rules",
                rules_cmd="prepare",
                selector=selector,
                check=check,
            )
        )

    @group_maintain_rules.command("verify", help="validate one registered rule's authored files and public examples")
    def command_maintain_rules_verify(
        ctx: typer.Context,
        *,
        selector: Annotated[
            RuleSelector, typer.Argument(parser=_parse_rule_selector, help="canonical ENGINE:ID selector")
        ],
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="rules",
                rules_cmd="verify",
                selector=selector,
            )
        )

    @group_maintain_rules.command("changes", help="compare rule inventory and policy between two Git revisions")
    def command_maintain_rules_changes(
        ctx: typer.Context,
        *,
        before: Annotated[str, typer.Option("--before")],
        after: Annotated[str, typer.Option("--after")],
        output_format: Annotated[
            _ChoiceMaintainRulesChangesOutputFormat, typer.Option("--format")
        ] = _ChoiceMaintainRulesChangesOutputFormat.VALUE_1,
        required_added_level: Annotated[
            _ChoiceMaintainRulesChangesRequiredAddedLevel | None,
            typer.Option("--require-added-level", help="fail when an added rule does not start at this level"),
        ] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="rules",
                rules_cmd="changes",
                before=before,
                after=after,
                output_format=output_format.value,
                required_added_level=required_added_level.value if required_added_level is not None else None,
            )
        )

    @group_maintain_rules.command(
        "evaluate", help="calibrate selected custom rules; findings exit 1 and invalid input or execution exits 2"
    )
    def command_maintain_rules_evaluate(
        ctx: typer.Context,
        *,
        selected_rules: Annotated[
            list[RuleSelector],
            typer.Option("--rule", parser=_parse_rule_selector, help="canonical ENGINE:ID selector (repeatable)"),
        ],
        corpus_manifest: Annotated[
            Path | None,
            typer.Option(
                "--corpus-manifest", help="evaluate immutable repositories declared by a public corpus manifest"
            ),
        ] = None,
        private_overlay: Annotated[
            Path | None,
            typer.Option(
                "--private-overlay", help="merge an owner-readable private corpus overlay (requires --corpus-manifest)"
            ),
        ] = None,
        evaluation_scope: Annotated[
            _EvaluationScope,
            typer.Option(
                "--scope", help="corpus ignores baselines/rule exclusions; effective applies adopted repository policy"
            ),
        ] = _EvaluationScope.CORPUS,
        output_format: Annotated[
            _ChoiceMaintainRulesEvaluateOutputFormat, typer.Option("--format")
        ] = _ChoiceMaintainRulesEvaluateOutputFormat.VALUE_0,
        output: Annotated[Path | None, typer.Option("--output")] = None,
        trust_repository_code: Annotated[
            bool,
            typer.Option("--trust-repository-code", help="allow executable repository ESLint configuration"),
        ] = False,
        files: Annotated[list[str] | None, typer.Argument()] = None,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="rules",
                rules_cmd="evaluate",
                selected_rules=selected_rules,
                corpus_manifest=corpus_manifest if corpus_manifest is not None else None,
                private_overlay=private_overlay if private_overlay is not None else None,
                evaluation_scope=evaluation_scope,
                output_format=output_format.value,
                output=output if output is not None else None,
                trust_repository_code=trust_repository_code,
                files=files if files is not None else [],
            )
        )

    @group_maintain_catalog.command("check", help="verify the public catalog matches every live rule")
    def command_maintain_catalog_check(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="catalog",
                catalog_cmd="check",
            )
        )

    @group_maintain_catalog.command("sync", help="update the public catalog from source-owned rule metadata")
    def command_maintain_catalog_sync(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="catalog",
                catalog_cmd="sync",
            )
        )

    @group_maintain_cli_reference.command("check", help="verify the shipped reference matches the parser graph")
    def command_maintain_cli_reference_check(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="cli-reference",
                reference_cmd="check",
            )
        )

    @group_maintain_cli_reference.command("sync", help="update the shipped reference from the parser graph")
    def command_maintain_cli_reference_sync(
        ctx: typer.Context,
    ) -> int:
        return handler(
            _Args(
                dest=_command_root(ctx),
                cmd="maintain",
                repo_cmd="cli-reference",
                reference_cmd="sync",
            )
        )

    return app


def _command_root(ctx: typer.Context) -> str:
    value = ctx.find_object(str)
    if not isinstance(value, str):
        msg = "CLI root context is missing"
        raise TypeError(msg)
    return value


def _cmd_repo(args: _Args) -> int:
    try:
        return _run_repo(args)
    except (OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run_repo(args: _Args) -> int:  # ruff: ignore[too-many-locals] -- one lazy CLI router covers independent repository subcommands.
    if args.repo_cmd == "setup":
        from sarj_standards.libs.setup import apply_setup, plan_setup  # ruff: ignore[import-outside-top-level]

        plan = plan_setup(_resolve_dest(args.dest))
        if args.check:
            if plan.install_hooks:
                print(f"would install: Lefthook repository hooks  (in {plan.root})")
            for command in plan.commands:
                print(f"would run: {shlex.join(command.argv)}  (in {command.cwd})")
            return 0
        return apply_setup(plan)
    if args.repo_cmd == "release":
        from sarj_standards.libs import release  # ruff: ignore[import-outside-top-level] -- lazy route

        root = _resolve_dest(args.dest)
        if args.release_cmd == "check-tag":
            validated = release.validate_release_tag(args.tag, root)
            print(f"{validated.tag} exactly matches {validated.manifest}")
            return 0
        if args.release_cmd == "verify-tags":
            missing = (
                release.verify_remote_release_tags(root, commit=args.release_commit)
                if args.release_commit
                else release.missing_remote_release_tags(root)
            )
            if missing:
                for tag_name in missing:
                    print(f"missing release tag: {tag_name}")
                return 1
            print("all current package versions have release tags")
            return 0
        if args.release_cmd == "create-tags":
            result = release.create_release_tags(
                root,
                tuple(args.release_targets),
                commit=args.release_commit,
                attempts=args.attempts,
                delay=args.delay_seconds,
            )
            for tag_name in result.existing:
                print(f"release tag already exists: {tag_name}")
            for tag_name in result.created:
                print(f"created release tag: {tag_name}")
            return 0
        if args.release_cmd == "changes" and args.github_output is not None:
            changed = release.pending_release_targets(root, before=args.before, after=args.after)
            with args.github_output.open("a", encoding="utf-8") as output:
                for target, value in changed.items():
                    _ = output.write(f"{target}={'true' if value else 'false'}\n")
            return 0
        if args.release_cmd == "causality":
            report = release.check_release_causality(root, before=args.before, after=args.after)
            if report.violations:
                print("\n".join(violation.render() for violation in report.violations))
                return 1
            changed = ", ".join(report.changed_targets) or "none"
            print(f"release causality ✓ (publishable targets changed: {changed})")
            return 0
        if args.release_cmd == "lock-age" and args.lockfile is not None:
            environment_policy = release.ReleaseAgePolicy.from_strings(
                os.environ.get("MIN_RELEASE_AGE_DAYS"),  # ruff: ignore[banned-api] -- compatibility with the retired release script.
                os.environ.get("MIN_RELEASE_AGE_EXCLUDE"),  # ruff: ignore[banned-api] -- compatibility with the retired release script.
            )
            policy = release.ReleaseAgePolicy(
                args.minimum_age if args.minimum_age is not None else environment_policy.minimum_age,
                environment_policy.exclusions
                | frozenset(args.release_exclude)
                | frozenset(
                    exclusion
                    for exclusion_file in args.release_exclude_file
                    for exclusion in release.load_exact_exclusions((root / exclusion_file).resolve())
                ),
            )
            report = release.check_lockfile_release_age((root / args.lockfile).resolve(), policy)
            if report.failures:
                print("\n".join(str(failure) for failure in report.failures))
                return 1
            print(f"release-age policy ✓ ({len(report.checked)} package versions checked)")
            return 0
        if args.release_cmd == "typescript":
            mode = args.release_mode
            match mode:
                case "check" | "pack" | "publish":
                    release_mode = mode
                case _:
                    return 2
            artifact = release.run_typescript_release(
                release_mode,
                root / "packages" / "typescript",
                destination=args.output,
            )
            if artifact is not None:
                print(f"packed and verified {artifact.path}")
            return 0
        if args.release_cmd == "verify-wheel":
            for wheel in args.wheels:
                release.verify_python_wheel_license(wheel.resolve())
                print(f"verified wheel license: {wheel}")
            return 0
        if args.release_cmd == "verify-publications":
            from sarj_standards.libs.release import registry  # ruff: ignore[import-outside-top-level]

            return registry.main(
                [
                    "--root",
                    str(root),
                    "--attempts",
                    str(args.attempts),
                    "--delay-seconds",
                    str(args.delay_seconds.total_seconds()),
                ]
            )
        if args.release_cmd == "publish":
            target = args.release_target
            match target:
                case "typescript" | "bootstrap" | "python" | "sql" | "iac" | "standards" | "tsconfig":
                    publish_target = target
                case _:
                    return 2
            release.publish_target(root, publish_target)
            return 0
        return 2
    if args.repo_cmd == "check":
        from sarj_standards.libs.repository import repository  # ruff: ignore[import-outside-top-level]

        findings = repository.check(
            _resolve_dest(args.dest),
            selected=frozenset(args.repo_only),
            commits=args.commits,
            policy_root=_resolve_dest(args.policy_dest) if args.policy_dest else None,
            private_refs_path=Path(args.private_refs_file).resolve() if args.private_refs_file else None,
        )
        if args.quiet:
            print("repository policy failed" if findings else "repository policy ✓")
        else:
            print("\n".join(finding.render() for finding in findings) or "repository policy ✓")
        return 1 if findings else 0
    if args.repo_cmd == "sync-ledger":
        from sarj_standards.libs.repository import rule_maintenance  # ruff: ignore[import-outside-top-level]

        result = rule_maintenance.sync_ledger(_resolve_dest(args.dest), check=args.check)
        print(result.message)
        return result.status
    if args.repo_cmd == "docs":
        from sarj_standards.libs.repository import docs  # ruff: ignore[import-outside-top-level]

        root = _resolve_dest(args.dest)
        if args.docs_cmd == "check":
            result = docs.check(root)
            for path in result.changed:
                print(f"drift: {path.relative_to(root)}")
            print("documentation is current" if not result.changed else "run `code-standards maintain docs sync`")
            return result.status
        result = docs.sync(root)
        for path in result.changed:
            print(f"wrote: {path.relative_to(root)}")
        return 0
    if args.repo_cmd == "comment-corpus":
        from sarj_standards.libs.repository import comment_corpus  # ruff: ignore[import-outside-top-level]

        if args.include_text is not None:
            return comment_corpus.write_records(args.roots, args.include_text)
        return comment_corpus.emit_summary(args.roots, sys.stdout)
    if args.repo_cmd == "hooks" and args.hooks_cmd == "install":
        from sarj_standards.libs.repository import hooks  # ruff: ignore[import-outside-top-level]

        return hooks.install(_resolve_dest(args.dest))
    if args.repo_cmd == "rules":
        from sarj_standards.libs.repository import rule_inventory_artifact  # ruff: ignore[import-outside-top-level]

        if args.rules_cmd == "manifest":
            print(json.dumps(rule_inventory_artifact.load(), indent=2))
            return 0
        if args.rules_cmd == "changes":
            from sarj_standards.libs.release.process import (  # ruff: ignore[import-outside-top-level]
                ProcessFailureError,
            )
            from sarj_standards.libs.repository import rule_changes  # ruff: ignore[import-outside-top-level]

            try:
                comparison = rule_changes.compare(
                    _resolve_dest(args.dest),
                    before=args.before,
                    after=args.after,
                )
            except (OSError, TypeError, ValueError, ProcessFailureError) as exc:
                print(f"error: cannot compare rule revisions: {exc}", file=sys.stderr)
                return 2
            raw_required_level = args.required_added_level
            required_added_level: rule_changes.RuleLevel | None = "warning" if raw_required_level == "warning" else None
            if required_added_level is not None:
                invalid = rule_changes.added_rules_at_other_levels(
                    comparison,
                    required=required_added_level,
                )
                if invalid:
                    print(
                        f"error: new judgment rules must enter the fleet at {required_added_level} level",
                        file=sys.stderr,
                    )
                    for selector in invalid:
                        print(f"Run: code-standards --root . maintain rules stage-warning {selector}", file=sys.stderr)
                    return 1
            print(
                json.dumps(comparison, indent=2)
                if args.output_format == "json"
                else rule_changes.render_text(comparison)
            )
            return 0
        if args.rules_cmd == "evaluate":
            return cmd_rule_evaluate(args)
        if args.rules_cmd == "new":
            from sarj_standards.libs.repository import rule_authoring  # ruff: ignore[import-outside-top-level]

            if args.selector is None:  # pragma: no cover - Typer requires the positional value
                msg = "new requires a rule selector"
                raise TypeError(msg)
            try:
                plan = rule_authoring.plan_new(
                    _resolve_dest(args.dest), args.selector, category=args.rule_category, summary=args.rule_summary
                )
                if args.apply_rule:
                    rule_authoring.apply(plan, _resolve_dest(args.dest))
            except (OSError, TypeError, ValueError) as exc:
                print(f"error: cannot scaffold rule: {exc}", file=sys.stderr)
                return 2
            print(plan.render(_resolve_dest(args.dest)))
            return 0
        if args.rules_cmd == "verify":
            from sarj_standards.libs.repository import rule_authoring  # ruff: ignore[import-outside-top-level]

            if args.selector is None:  # pragma: no cover - Typer requires the positional value
                msg = "verify requires a rule selector"
                raise TypeError(msg)
            try:
                result = rule_authoring.verify(_resolve_dest(args.dest), args.selector)
            except (OSError, TypeError, ValueError, RuntimeError) as exc:
                print(f"error: cannot verify rule: {exc}", file=sys.stderr)
                return 2
            print(result.message)
            return result.status
        if args.rules_cmd in {"stage-warning", "prepare"}:
            from sarj_standards.libs.repository import rule_lifecycle  # ruff: ignore[import-outside-top-level]

            if args.selector is None:  # pragma: no cover - Typer requires the positional value
                msg = f"{args.rules_cmd} requires a rule selector"
                raise TypeError(msg)
            if args.rules_cmd == "prepare":
                from sarj_standards.libs.repository import (  # ruff: ignore[import-outside-top-level]
                    rule_authoring,
                )

                try:
                    verified = rule_authoring.verify(_resolve_dest(args.dest), args.selector)
                except (OSError, TypeError, ValueError, RuntimeError) as exc:
                    print(f"error: cannot verify rule before preparation: {exc}", file=sys.stderr)
                    return 2
                if verified.status != 0:
                    print(verified.message)
                    return verified.status
            try:
                result = rule_lifecycle.stage_warning(_resolve_dest(args.dest), args.selector, check=args.check)
            except (OSError, TypeError, ValueError, RuntimeError) as exc:
                print(f"error: cannot stage warning rule: {exc}", file=sys.stderr)
                return 2
            print(result.message)
            if result.status == 0:
                print(_rule_author_next_steps(args.selector))
            return result.status
        result = rule_inventory_artifact.sync(_resolve_dest(args.dest), check=args.rules_cmd == "check")
        print(result.message)
        return result.status
    if args.repo_cmd == "catalog":
        from sarj_standards.libs.repository import rule_catalog_artifact  # ruff: ignore[import-outside-top-level]

        result = rule_catalog_artifact.sync(_resolve_dest(args.dest), check=args.catalog_cmd == "check")
        print(result.message)
        return result.status
    if args.repo_cmd == "cli-reference":
        from sarj_standards.libs.repository import cli_reference_artifact  # ruff: ignore[import-outside-top-level]

        result = cli_reference_artifact.sync(_resolve_dest(args.dest), build_app(), check=args.reference_cmd == "check")
        print(result.message)
        return result.status
    return 2


def _rule_author_next_steps(selector: RuleSelector) -> str:
    return (
        "next: validate the staged rule locally\n"
        f"  code-standards --root . maintain rules evaluate --rule {selector} --scope corpus\n"
        "  make verify\n"
        "after committing the result:\n"
        "  code-standards --root . maintain rules changes --before origin/main --after HEAD"
    )


if __name__ == "__main__":
    raise SystemExit(main())
