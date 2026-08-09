"""CLI for syncing bundled lint configs into a consumer repository."""

from __future__ import annotations

import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- repository commands report failures from fixed-argument child processes.
import sys
import tempfile
from typing import TYPE_CHECKING, NoReturn

from sarj_standards import __version__
from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.adoption.configs import (
    APPLICATION_CONFIG_NAMES,
    CONFIG_NAMES,
)
from sarj_standards.libs.filesystem import is_link_like


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sarj_standards.libs.adoption import service


_NEXT_STEPS = (
    "\nnext: in your pyproject.toml, add:\n"
    "  [tool.ruff]\n"
    '  extend = ".ruff-strict.toml"\n'
    "\n(or run `sarj-standards setup`, which writes that and the rest of the wiring)\n"
)
_BOOTSTRAP_TIMEOUT = timedelta(seconds=120)
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


class _Args(argparse.Namespace):
    """Provide typed defaults for the parsed command namespace."""

    cmd: str = ""
    dest: str = "."
    only: list[str]
    force: bool = False
    check: bool = False
    dry_run: bool = False
    python_dest: str | None = None
    typescript_dest: str | None = None
    configs: list[str]
    name: str = ""
    files: list[str]
    repo_cmd: str = ""
    repo_only: list[str]
    commits: str | None = None
    policy_dest: str | None = None
    private_refs_file: str | None = None
    quiet: bool = False
    roots: list[Path]
    include_text: Path | None = None
    rules_cmd: str = ""
    reference_cmd: str = ""
    docs_cmd: str = ""
    hooks_cmd: str = ""
    no_install: bool = False
    repair: bool = False
    profile: manifest.Profile | None = None
    output_format: str = "text"
    offline: bool = False
    release_cmd: str = ""
    release_mode: str = ""
    tag: str = ""
    lockfile: Path | None = None
    minimum_age: timedelta | None = None
    release_exclude: list[str]
    release_exclude_file: list[Path]
    output: Path | None = None
    external: bool = False
    trust: str = "safe"
    trust_repository_code: bool = False
    before: str = ""
    after: str = ""
    github_output: Path | None = None
    release_target: str = ""
    release_targets: list[str]
    wheels: list[Path]
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

    def __init__(self) -> None:
        super().__init__()
        # `None` and `[]` mean the same thing for a list of choices, so these
        # default to empty rather than nullable; argparse replaces them when the
        # flag is given.
        self.files = []
        self.only = []
        self.configs = []
        self.repo_only = []
        self.roots = []
        self.release_exclude = []
        self.release_exclude_file = []
        self.release_targets = []
        self.wheels = []


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
    """Render invalid command input with argparse's conventional exit status."""
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


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
    standard_src_name, _ = CONFIG_NAMES[args.name]
    src_name = (
        APPLICATION_CONFIG_NAMES.get(args.name, standard_src_name)
        if args.profile == "application"
        else standard_src_name
    )
    print(CONFIGS_DIR / src_name)
    return 0


def cmd_peers(args: _Args) -> int:
    """Print the npm packages `eslint.strict.mjs` needs, at versions that resolve."""
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


def cmd_doctor(args: _Args) -> int:
    """Report every version pin site in a repo and whether it agrees with the rest."""
    from sarj_standards.libs.adoption import doctor, upgrade  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    repair = args.repair
    no_install: bool = args.no_install
    repair_status = 0
    if repair:
        try:
            adopted = manifest.load(root)
        except (OSError, TypeError, ValueError) as exc:
            try:
                adopted = _repair_legacy_manifest(root, install=not no_install)
            except (OSError, TypeError, ValueError) as migration_error:
                print(f"error: cannot repair invalid adoption manifest: {exc}; {migration_error}", file=sys.stderr)
                return 2
        if adopted is None:
            print("error: repository is not adopted; run `sarj-standards setup`", file=sys.stderr)
            return 2
        plan = upgrade.build_plan(root)
        blockers = upgrade.unsafe_retired_findings(plan) if upgrade.changes_bundle_version(plan) else []
        if blockers:
            repair_status = 2
            print("error: automatic repair is blocked by retired rule references:", file=sys.stderr)
            for finding in blockers:
                print(f"error: {finding.where} -- {finding.detail}", file=sys.stderr)
        else:
            repair_status = upgrade.apply(plan, install=not no_install)
        if repair_status and not blockers:
            print(
                "error: automatic repair did not converge; tracked configuration changes were restored",
                file=sys.stderr,
            )
    findings = doctor.diagnose(root)
    if repair and no_install:
        findings = [
            doctor.Finding(
                doctor.Level.WARN,
                finding.where,
                f"{finding.detail}; installation intentionally skipped",
                finding.id,
                finding.remediation,
            )
            if finding.level is doctor.Level.DRIFT and upgrade.is_install_remediable(finding)
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
            ["run `sarj-standards setup`"]
            if unadopted
            else list(
                dict.fromkeys(
                    finding.remediation
                    for finding in findings
                    if finding.level is doctor.Level.DRIFT and finding.remediation
                )
            )
        )
        for remediation in remediations:
            print(f"fix: {remediation}")
    if invalid:
        return max(repair_status, 2)
    return max(repair_status, 1 if drifted or unadopted else 0)


def _repair_legacy_manifest(root: Path, *, install: bool) -> manifest.Manifest:
    from sarj_standards.libs.adoption import service  # ruff: ignore[import-outside-top-level]

    legacy = manifest.load_for_setup(root)
    if legacy is None:
        msg = "repository is not adopted; run `sarj-standards setup`"
        raise ValueError(msg)
    migration = service.plan_init(
        root,
        configs=legacy.configs,
        python_dest=legacy.python_dest,
        typescript_dest=legacy.typescript_dest,
        profile=legacy.profile,
        hook_manager=legacy.hook_manager,
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


def cmd_update(args: _Args) -> int:
    """Preview or apply the latest coherent bundle."""
    from sarj_standards.libs.adoption import doctor, lifecycle, upgrade  # ruff: ignore[import-outside-top-level]

    if (
        not args.offline
        and os.environ.get(  # ruff: ignore[banned-api] -- private recursion sentinel, not application settings
            "SARJ_STANDARDS_BOOTSTRAPPED"
        )
        != "1"
    ):
        executable = shutil.which("uvx")
        if executable is None:
            print(
                "error: uvx is required to resolve the latest standards release; install uv or pass --offline",
                file=sys.stderr,
            )
            return 2
        from sarj_standards.libs.adoption import launcher  # ruff: ignore[import-outside-top-level] -- lazy route

        command = [
            *launcher.argv(executable=executable, refresh=True),
            "--root",
            str(_resolve_dest(args.dest)),
            "update",
            "--offline",
        ]
        if args.check:
            command.append("--check")
        if args.no_install:
            command.append("--no-install")
        environment = dict(os.environ)  # ruff: ignore[banned-api] -- preserve the caller environment for uvx
        environment["SARJ_STANDARDS_BOOTSTRAPPED"] = "1"
        try:
            return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed executable and argv
                command,
                check=False,
                env=environment,
                timeout=_BOOTSTRAP_TIMEOUT.total_seconds(),
            ).returncode
        except subprocess.TimeoutExpired:
            print(
                "error: resolving the latest standards release timed out; check the network or pass --offline",
                file=sys.stderr,
            )
            return 2

    root = _resolve_dest(args.dest)
    try:
        plan = upgrade.build_plan(root)
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: cannot plan upgrade: {exc}", file=sys.stderr)
        return 2
    blockers = upgrade.unsafe_retired_findings(plan) if upgrade.changes_bundle_version(plan) else []
    if blockers:
        for finding in blockers:
            print(f"error: {finding.where} -- {finding.detail}", file=sys.stderr)
        return 2
    preview = upgrade.render(plan.changes)
    if args.check:
        drifted = [finding for finding in doctor.diagnose(root) if finding.level is doctor.Level.DRIFT]
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
    pending = upgrade.pending_install_findings(root) if args.no_install else []
    skipped_commands = (
        lifecycle.install_commands(root, plan.ecosystems, hook_manager=plan.adopted.hook_manager)
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
        print("next: run the skipped setup command(s), then `sarj-standards doctor`:")
        for command in skipped_commands:
            print(f"      {shlex.join(command.argv)}  (in {command.cwd})")
        return 0
    print(f"updated: {root} now uses standards {__version__}")
    return 0


def cmd_setup(args: _Args) -> int:
    """Scaffold a repo's whole adoption in one command."""
    from sarj_standards.libs.adoption import scaffold, service  # ruff: ignore[import-outside-top-level] -- lazy route

    root = _resolve_dest(args.dest)
    selected_configs = tuple(dict.fromkeys((*args.configs, *args.only)))
    try:
        init_plan = service.plan_init(
            root,
            force=args.force,
            configs=selected_configs or None,
            python_dest=args.python_dest,
            typescript_dest=args.typescript_dest,
            profile=args.profile,
            hook_manager=args.hooks,
        )
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
        for name, present in (("python", plan.ecosystems.python), ("typescript", plan.ecosystems.typescript))
        if present
    ]
    print(f"detected: {', '.join(detected) or 'nothing'}")
    if not plan.ecosystems.any and not selected_configs:
        for note in plan.notes:
            print(f"note:  {note}")
        return 1

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

    verb_write = "would write" if args.dry_run else "wrote"
    verb_edit = "would append to" if args.dry_run else "appended to"
    for path, _contents in plan.writes:
        print(f"{verb_write}: {path}")
    for path, _addition in plan.edits:
        print(f"{verb_edit}: {path}")
    for path, reason in plan.skips:
        print(f"skip:  {path}  ({reason})")

    for note in plan.notes:
        print(f"\nnote:  {note}")
    if args.no_install and init_plan.install_commands:
        print("\nnext:  dependency and hook installation was skipped; run:")
        for command in init_plan.install_commands:
            print(f"       {shlex.join(command.argv)}  (in {command.cwd})")
    workflows = scaffold.standards_check_workflows(root)
    if workflows:
        rendered = ", ".join(path.relative_to(root).as_posix() for path in workflows)
        print(f"\nCI:    {rendered} runs the pinned quality gate")
    else:
        print("\nCI:    would write .github/workflows/standards.yml")
    return 0


def cmd_verify(args: _Args) -> int:
    root = _resolve_dest(args.dest)
    if cmd_doctor(args):
        return 1
    sync_args = _Args()
    sync_args.dest = str(root)
    sync_args.check = True
    if cmd_sync(sync_args, next_steps=False):
        return 1
    adopted = _declared_manifest(args)
    return _run_canonical_check(
        root,
        None if adopted is None else adopted.verify_paths,
        raw=adopted is None,
        trusted=args.trust_repository_code,
    )


def _declared_manifest(args: _Args) -> manifest.Manifest | None:
    """Read the project adoption recorded by `setup`."""
    try:
        return manifest.load(_resolve_dest(args.dest))
    except TypeError, ValueError, SystemExit:
        return None


def cmd_library_policy(args: _Args, *, selected_paths: Iterable[str] | None = None) -> int:
    """Enforce the application profile's direct-dependency policy."""
    from sarj_standards.libs.linting import library_policy  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    try:
        adopted = manifest.load(root)
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: invalid standards manifest: {exc}", file=sys.stderr)
        return 2
    profile = args.profile or (adopted.profile if adopted is not None else "standard")
    if profile != "application":
        if args.output_format == "json":
            print(json.dumps({"profile": profile, "findings": []}))
        elif not args.quiet:
            print("library policy skipped (standard profile)")
        return 0
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


def cmd_check(args: _Args) -> int:
    """Run the complete quality gate or the selected paths."""
    from sarj_standards.libs.linting import runner  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    if args.staged:
        try:
            staged = _staged_files(root)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"error: cannot read staged files: {exc}", file=sys.stderr)
            return 2
        if args.files:
            staged_set = frozenset(staged)
            args.files = [path for path in _safe_staged_paths(root, args.files) if path in staged_set]
        else:
            args.files = staged
        drifted = _unstaged_versions(root, args.files)
        if drifted:
            print(
                "error: --staged found files with unstaged content; run through pre-commit "
                "(which safely stashes it) or stage the intended versions: " + ", ".join(drifted),
                file=sys.stderr,
            )
            return 2
    elif args.files:
        try:
            args.files = _selected_paths(root, args.files)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if len(args.files) == 1 and Path(args.files[0]).resolve() == root:
        args.files = []
    if args.staged:
        health_status = _check_staged_adoption_health(root, args.files, output_format=args.output_format)
        if health_status:
            return health_status
        args.files = [path for path in args.files if runner.accepts_hook_path(Path(path))]
        if not args.files:
            return 0
    if args.output_format != "text":
        if _validate_analysis_output(args, root):
            return 2
        args.external = True
        args.trust = "trusted" if args.trust_repository_code else "safe"
        args.analysis_mode = "policy"
        if not args.files:
            adoption_report = _machine_adoption_gate(root)
            if adoption_report is not None:
                return _emit_analysis_report(args, root, adoption_report)
        return cmd_analyze(args)
    if not args.files:
        return cmd_verify(args)
    return _run_canonical_check(root, list(args.files), trusted=args.trust_repository_code)


def _run_canonical_check(root: Path, paths: Sequence[str] | None, *, raw: bool = False, trusted: bool = False) -> int:
    """Run every engine through one policy-aware diagnostic boundary."""
    from sarj_standards.api import AnalysisMode, Standards, TrustMode  # ruff: ignore[import-outside-top-level]
    from sarj_standards.libs.diagnostics import to_text  # ruff: ignore[import-outside-top-level]

    report = Standards(root).analyze(
        paths,
        external=True,
        trust=TrustMode.TRUSTED if trusted else TrustMode.SAFE,
        mode=AnalysisMode.RAW if raw else AnalysisMode.POLICY,
    )
    rendered = to_text(report)
    if rendered:
        print(rendered, end="" if rendered.endswith("\n") else "\n")
    return report.exit_code


def cmd_analyze(args: _Args) -> int:
    """Render canonical native diagnostics for CI and programmatic consumers."""
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
    )
    return _emit_analysis_report(args, root, report)


def _emit_analysis_report(args: _Args, root: Path, report: object) -> int:
    """Render one canonical report, including pre-analysis configuration gates."""
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
            _report_destination(root, args.output, output_format=args.output_format)
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if args.output_format == "github":
        payload = to_github(report, max_annotations_per_level=args.max_annotations_per_level)
    elif args.output_format == "json":
        payload = to_json(report)
    else:
        payload = {"sarif": to_sarif, "text": to_text}[args.output_format](report)
    if args.output is None or str(args.output) == "-":
        print(payload, end="")
    else:
        _write_report(root, args.output, payload, output_format=args.output_format)
    return report.exit_code


def _validate_analysis_output(args: _Args, root: Path) -> bool:
    """Reject unsafe or unsupported report targets before any analysis runs."""
    if args.output is None or str(args.output) == "-":
        return False
    if args.output_format not in {"json", "sarif"}:
        print("error: --output is supported only with --format json or sarif", file=sys.stderr)
        return True
    try:
        _report_destination(root, args.output, output_format=args.output_format)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return True
    return False


def _machine_adoption_gate(root: Path) -> object | None:
    """Return canonical diagnostics when full-check adoption/config gates fail."""
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
                    help="run `sarj-standards update --offline`",
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


def _doctor_location(root: Path, where: str) -> str:
    """Turn a human doctor site into a safe repository-relative location."""
    rendered = where.split(":", 1)[0]
    candidate = Path(rendered)
    if not candidate.is_absolute() and ".." not in candidate.parts and (root / candidate).exists():
        return candidate.as_posix()
    return manifest.MANIFEST_NAME


def _report_destination(root: Path, output: Path, *, output_format: str) -> Path:
    """Validate a report target without creating it or running analysis."""
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
    output_format: str = "text",
) -> int:
    """Keep the staged fast path from bypassing generated config and pin drift."""
    from sarj_standards.libs.adoption import doctor  # ruff: ignore[import-outside-top-level]

    selected = tuple(Path(path) for path in staged_paths)
    drifted = [
        finding for finding in doctor.diagnose_adoption_health(root, selected) if finding.level is doctor.Level.DRIFT
    ]
    invalid = any(finding.id in {"doctor.manifest.invalid", "doctor.package-json.invalid"} for finding in drifted)
    status = 2 if invalid else 1 if drifted else 0
    if output_format == "json" and status:
        print(
            json.dumps(
                {
                    "schema": 1,
                    "command": "check",
                    "phase": "adoption-health",
                    "status": status,
                    "root": str(root),
                    "findings": [finding.as_dict() for finding in drifted],
                },
                indent=2,
            )
        )
        return status
    for finding in drifted:
        print(f"drift: {finding.id} {finding.where} -- {finding.detail}")
    remediations = list(dict.fromkeys(finding.remediation for finding in drifted if finding.remediation))
    for remediation in remediations:
        print(f"fix: {remediation}")
    if invalid:
        return 2
    return 1 if drifted else 0


def _staged_files(root: Path) -> list[str]:
    """Return staged, non-deleted files as absolute paths safe for any caller CWD."""
    git = shutil.which("git")
    if git is None:
        msg = "git is required for --staged"
        raise OSError(msg)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed argv, no shell.
        [git, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
        env=_git_environment(),
    )
    names = (part.decode("utf-8", errors="surrogateescape") for part in completed.stdout.split(b"\0"))
    return _safe_staged_paths(root, names)


def _safe_staged_paths(root: Path, paths: Iterable[str]) -> list[str]:
    """Keep hook-supplied paths inside the repository and reject symlink aliases."""
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
    """Refuse direct staged checks when they would read different worktree bytes."""
    if not (root / ".git").exists():
        return ()
    git = shutil.which("git")
    if git is None:
        msg = "git is required for --staged"
        raise OSError(msg)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed argv, no shell.
        [git, "diff", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
        env=_git_environment(),
    )
    unstaged = {part.decode("utf-8", errors="surrogateescape") for part in completed.stdout.split(b"\0") if part}
    repository = root.resolve()
    selected = {
        resolved.relative_to(repository).as_posix()
        for path in staged_paths
        if (resolved := Path(path).resolve()).is_relative_to(repository)
    }
    return tuple(sorted(unstaged & selected))


def _git_environment() -> dict[str, str]:
    """Discard hook-local routing so `--root` remains the Git repository authority."""
    return {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- intentionally sanitize Git hook routing.
        if name in _GIT_SAFE_ENV
    }


def _selected_paths(root: Path, paths: Iterable[str]) -> list[str]:
    """Resolve explicit inputs without allowing repository-boundary aliases."""
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
    from sarj_standards.libs.adoption import lifecycle, scaffold  # ruff: ignore[import-outside-top-level]

    root = _resolve_dest(args.dest)
    return lifecycle.execute(lifecycle.format_commands(scaffold.detect(root)))


def cmd_inspect(args: _Args) -> int:
    from sarj_standards.libs.adoption import lifecycle  # ruff: ignore[import-outside-top-level]

    sys.stdout.write(lifecycle.inspection_json(_resolve_dest(args.dest)))
    return 0


def cmd_show(args: _Args) -> int:
    """Render read-only package and adoption information."""
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
            rendered = scaffold.github_ci_workflow(root, version=__version__)
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
    """Inspect or change the repository's explicit path and rule denylist."""
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


def main(argv: list[str] | None = None) -> int:
    raw_argv = _root_option_first(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_argv, namespace=_Args())
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _root_option_first(argv: list[str]) -> list[str]:
    """Let the one global repository option appear before or after the verb."""
    positions = [index for index, value in enumerate(argv) if value == "--root"]
    if not positions or positions == [0] or len(positions) != 1:
        return argv
    index = positions[0]
    if index + 1 >= len(argv):
        return argv
    return ["--root", argv[index + 1], *argv[:index], *argv[index + 2 :]]


def _dispatch(args: _Args) -> int:
    """Route one parsed command behind the consumer-facing error boundary."""
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
        case "show":
            return cmd_show(args)
        case "exclude":
            return cmd_exclude(args)
        case "maintain":
            return _cmd_repo(args)
        case _:  # argparse enforces `required=True`, so this is unreachable
            return 2


def build_parser() -> argparse.ArgumentParser:
    """Build the public parser graph used by the CLI and derived references."""
    parser = argparse.ArgumentParser(
        prog="sarj-standards",
        description=f"Adopt, check, fix, diagnose, and update sarj-ai standards (v{__version__}).",
        epilog="Start with `sarj-standards setup`, then use `sarj-standards check`.",
    )
    parser.add_argument("--version", action="version", version=f"sarj-standards {__version__}")
    parser.add_argument(
        "--root",
        dest="dest",
        default=".",
        help="repository root shared by the selected command (default: current directory)",
    )
    sub = parser.add_subparsers(
        dest="cmd",
        required=True,
        metavar="{setup,check,fix,doctor,update,exclude,show,maintain}",
        title="commands",
    )

    p_doctor = sub.add_parser(
        "doctor",
        help="diagnose adoption health and optionally repair safe drift",
    )
    p_doctor.add_argument(
        "--format",
        dest="output_format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    p_doctor.add_argument(
        "--repair",
        action="store_true",
        help="transactionally repair safe drift with the executing bundle, then re-diagnose",
    )
    p_doctor.add_argument(
        "--no-install",
        action="store_true",
        help="with --repair, update configuration without installing dependencies or hooks",
    )

    setup = sub.add_parser("setup", help="adopt or converge the repository in one idempotent operation")
    setup.add_argument(
        "--hooks",
        choices=manifest.HOOK_MANAGERS,
        help="hook manager (default: detect Lefthook, otherwise pre-commit)",
    )
    setup.add_argument(
        "--python-dest",
        help="the directory that owns pyproject.toml (default: detected)",
    )
    setup.add_argument(
        "--typescript-dest",
        help="the directory that owns the npm lockfile (default: detected)",
    )
    setup.add_argument("--dry-run", action="store_true", help="print the complete plan without writing")
    setup.add_argument(
        "--profile",
        choices=manifest.PROFILES,
        help="policy profile to adopt (default: existing value, otherwise standard)",
    )
    setup.add_argument(
        "--no-install", action="store_true", help="write wiring without installing dependencies or hooks"
    )
    setup.add_argument(
        "--config",
        dest="only",
        action="append",
        choices=sorted(CONFIG_NAMES),
        default=[],
        help="select one config explicitly (repeatable)",
    )

    p_check = sub.add_parser(
        "check",
        help="run the complete quality gate or check selected paths",
    )
    p_check.add_argument(
        "--trust-repository-code",
        action="store_true",
        help="allow executable repository ESLint configuration (generated hooks and CI set this explicitly)",
    )
    p_check.add_argument(
        "--staged",
        action="store_true",
        help="run custom rules on hook-supplied paths, or discover staged files when none are supplied",
    )
    p_check.add_argument(
        "--format",
        dest="output_format",
        choices=("text", "json", "sarif", "github"),
        default="text",
    )
    p_check.add_argument("--output", type=Path, help="write JSON or SARIF atomically to PATH")
    p_check.add_argument(
        "--max-annotations-per-level",
        dest="max_annotations_per_level",
        type=int,
        choices=range(11),
        default=10,
    )
    p_check.add_argument(
        "files",
        nargs="*",
        help="selected paths; when omitted, check the complete repository",
    )

    sub.add_parser("fix", help="apply safe formatting and lint fixes")

    update = sub.add_parser("update", help="upgrade the complete coherent Standards bundle")
    update.add_argument("--check", action="store_true", help="preview without writing; exit 1 when changes exist")
    update.add_argument("--offline", action="store_true", help="use the executing bundle without resolving latest")
    update.add_argument("--no-install", action="store_true", help="do not install dependencies or hooks")

    exclude = sub.add_parser("exclude", help="inspect or change explicit path and rule exclusions")
    exclude_commands = exclude.add_subparsers(dest="exclude_cmd", required=True)
    exclude_commands.add_parser("list", help="list the complete denylist")
    for action in ("add", "remove"):
        mutation = exclude_commands.add_parser(action, help=f"{action} one exact denylist entry")
        mutation.add_argument("exclude_kind", choices=("path", "rule"), metavar="{path,rule}")
        mutation.add_argument("value", help="repository-relative glob or canonical engine:rule selector")

    show = sub.add_parser("show", help="print read-only package and adoption information")
    show_commands = show.add_subparsers(dest="show_cmd", required=True)
    show_commands.add_parser("state", help="print detected adoption state as JSON")
    show_commands.add_parser("configs", help="list bundled configurations")
    config = show_commands.add_parser("config", help="print one bundled configuration path")
    config.add_argument("name", choices=sorted(CONFIG_NAMES))
    config.add_argument("--profile", choices=manifest.PROFILES, default="standard")
    show_commands.add_parser("peers", help="show tested ESLint peer dependencies and install command")
    show_commands.add_parser("rules", help="print the machine-readable custom-rule inventory")
    ci = show_commands.add_parser("ci", help="print a complete pinned GitHub Actions standards workflow")
    ci.add_argument("--output", type=Path, help="write a managed workflow inside the repository")

    _add_repo_parsers(sub.add_parser("maintain", help="repository policy, hooks, rule ledgers, and releases"))

    return parser


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
            missing = release.missing_remote_release_tags(root)
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
            if mode == "check":
                release_mode = "check"
            elif mode == "pack":
                release_mode = "pack"
            elif mode == "publish":
                release_mode = "publish"
            else:
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
            if target == "typescript":
                publish_target = "typescript"
            elif target == "python":
                publish_target = "python"
            elif target == "sql":
                publish_target = "sql"
            elif target == "iac":
                publish_target = "iac"
            elif target == "standards":
                publish_target = "standards"
            elif target == "tsconfig":
                publish_target = "tsconfig"
            else:
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
            print("documentation is current" if not result.changed else "run `sarj-standards maintain docs sync`")
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

        result = cli_reference_artifact.sync(
            _resolve_dest(args.dest), build_parser(), check=args.reference_cmd == "check"
        )
        print(result.message)
        return result.status
    return 2


def _add_repo_parsers(repo: argparse.ArgumentParser) -> None:  # ruff: ignore[too-many-locals] -- argparse requires one variable per subparser.
    commands = repo.add_subparsers(dest="repo_cmd", required=True)
    setup = commands.add_parser("setup", help="install every standards development environment and repository hook")
    setup.add_argument("--check", action="store_true", help="print the deterministic setup plan without executing it")
    release = commands.add_parser("release", help="validate and build publishable release artifacts")
    release_commands = release.add_subparsers(dest="release_cmd", required=True)
    tag = release_commands.add_parser("check-tag", help="require a release tag to match its package manifest")
    tag.add_argument("tag")
    release_commands.add_parser("verify-tags", help="verify all manifest release tags on origin")
    create_tags = release_commands.add_parser("create-tags", help="create and push manifest release tags")
    create_tags.add_argument(
        "release_targets",
        nargs="+",
        choices=("typescript", "python", "sql", "iac", "standards", "tsconfig"),
    )
    create_tags.add_argument("--commit", dest="release_commit", required=True, help="exact commit that was published")
    create_tags.add_argument("--attempts", type=int, default=6)
    create_tags.add_argument(
        "--delay-seconds",
        type=lambda value: timedelta(seconds=float(value)),
        default=timedelta(seconds=10),
    )
    changes = release_commands.add_parser("changes", help="emit package version changes between Git revisions")
    changes.add_argument("--before", required=True)
    changes.add_argument("--after", required=True)
    changes.add_argument("--github-output", type=Path, required=True)
    causality = release_commands.add_parser(
        "causality",
        help="require every publishable package change to bump its version",
    )
    causality.add_argument("--before", required=True)
    causality.add_argument("--after", required=True)
    age = release_commands.add_parser("lock-age", help="enforce npm lockfile minimum release age")
    age.add_argument("lockfile", type=Path)
    age.add_argument("--minimum-days", dest="minimum_age", type=lambda value: timedelta(days=int(value)))
    age.add_argument("--exclude", dest="release_exclude", action="append", default=[])
    age.add_argument(
        "--exclude-file",
        dest="release_exclude_file",
        action="append",
        type=Path,
        default=[],
        help="line-oriented exact package@version exceptions (repeatable)",
    )
    typescript = release_commands.add_parser("typescript", help="check, pack, or publish the TypeScript package")
    typescript.add_argument("release_mode", choices=("check", "pack", "publish"))
    typescript.add_argument("--output", type=Path, help="artifact directory (required for pack)")
    verify_wheel = release_commands.add_parser(
        "verify-wheel", help="require non-empty license text in built Python wheels"
    )
    verify_wheel.add_argument("wheels", nargs="+", type=Path)
    publications = release_commands.add_parser(
        "verify-publications", help="wait for every exact sibling publication required by Standards"
    )
    publications.add_argument("--attempts", type=int, default=6)
    publications.add_argument(
        "--delay-seconds",
        type=lambda value: timedelta(seconds=float(value)),
        default=timedelta(seconds=10),
    )
    publish = release_commands.add_parser("publish", help="build and publish one package through its native client")
    publish.add_argument(
        "release_target",
        choices=("typescript", "python", "sql", "iac", "standards", "tsconfig"),
    )
    check = commands.add_parser("check", help="run repository policy gates")
    check.add_argument(
        "--only",
        dest="repo_only",
        action="append",
        choices=("ci-history", "file-conventions", "private-refs", "versions"),
        default=[],
    )
    check.add_argument("--commits", help="also inspect commit messages in this revision range")
    check.add_argument(
        "--policy-root",
        dest="policy_dest",
        help="trusted repository policy root (default: --root)",
    )
    check.add_argument("--private-refs-file", help="private-reference TOML outside the scanned repository")
    check.add_argument("--quiet", action="store_true", help="hide finding details")
    ledger = commands.add_parser("sync-ledger", help="synchronize the rule compatibility ledger")
    ledger.add_argument("--check", action="store_true", help="report drift without writing")
    docs = commands.add_parser("docs", help="check or synchronize source-derived documentation")
    docs_commands = docs.add_subparsers(dest="docs_cmd", required=True)
    for action in ("check", "sync"):
        docs_commands.add_parser(action)
    corpus = commands.add_parser("comment-corpus", help="extract comments for calibration")
    corpus.add_argument("roots", nargs="+", type=Path)
    corpus.add_argument(
        "--include-text",
        type=Path,
        metavar="PRIVATE_JSONL",
        help="write sensitive comment text to a new owner-readable file",
    )
    hook_commands = commands.add_parser("hooks", help="manage the pinned repository hooks").add_subparsers(
        dest="hooks_cmd", required=True
    )
    hook_commands.add_parser("install", help="install Lefthook")
    rule_commands = commands.add_parser("rules", help="inspect live custom rules").add_subparsers(
        dest="rules_cmd", required=True
    )
    rule_commands.add_parser("manifest", help="print the shipped rule inventory")
    rule_commands.add_parser("check", help="verify the shipped rule inventory matches live registries")
    rule_commands.add_parser("sync", help="update the shipped rule inventory from live registries")
    catalog_commands = commands.add_parser(
        "catalog", help="maintain the source-derived public rule catalog"
    ).add_subparsers(dest="catalog_cmd", required=True)
    catalog_commands.add_parser("check", help="verify the public catalog matches every live rule")
    catalog_commands.add_parser("sync", help="update the public catalog from source-owned rule metadata")
    reference_commands = commands.add_parser(
        "cli-reference", help="maintain the source-derived CLI reference"
    ).add_subparsers(dest="reference_cmd", required=True)
    reference_commands.add_parser("check", help="verify the shipped reference matches the parser graph")
    reference_commands.add_parser("sync", help="update the shipped reference from the parser graph")


if __name__ == "__main__":
    raise SystemExit(main())
