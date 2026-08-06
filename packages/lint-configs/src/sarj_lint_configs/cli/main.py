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

from sarj_lint_configs import CONFIGS_DIR, __version__, manifest
from sarj_lint_configs.libs.adoption.configs import (
    APPLICATION_CONFIG_NAMES,
    CONFIG_NAMES,
)
from sarj_lint_configs.libs.filesystem import is_link_like


if TYPE_CHECKING:
    from collections.abc import Iterable

    from sarj_lint_configs.libs.adoption import service


_NEXT_STEPS = (
    "\nnext: in your pyproject.toml, add:\n"
    "  [tool.ruff]\n"
    '  extend = ".ruff-strict.toml"\n'
    "\n(or run `sarj-lint-configs init`, which writes that and the rest of the wiring)\n"
)
_BOOTSTRAP_TIMEOUT_SECONDS = 120
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
    noise_only: bool = False
    python_baseline: str | None = None
    create_baseline: str | None = None
    repo_cmd: str = ""
    repo_only: list[str]
    commits: str | None = None
    policy_dest: str | None = None
    private_refs_file: str | None = None
    quiet: bool = False
    roots: list[Path]
    include_text: Path | None = None
    rules_cmd: str = ""
    hooks_cmd: str = ""
    no_install: bool = False
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
    before: str = ""
    after: str = ""
    github_output: Path | None = None
    release_target: str = ""
    release_targets: list[str]
    wheels: list[Path]
    root: str | None = None
    configs_only: bool = False
    hooks: manifest.HookManager | None = None
    dependencies: bool = False
    show_cmd: str = ""
    staged: bool = False
    release_commit: str = ""
    max_annotations_per_level: int = 10
    analysis_mode: str = "policy"

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
    from sarj_lint_configs.libs.adoption import service  # ruff: ignore[import-outside-top-level] -- lazy route

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
        _user_error(f"--dest {dest} is not a directory")
    return dest


def _user_error(message: str) -> NoReturn:
    """Render invalid command input with argparse's conventional exit status."""
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def _render_sync(result: service.SyncResult) -> None:
    from sarj_lint_configs.libs.adoption import service  # ruff: ignore[import-outside-top-level] -- typed lazy route

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
    from sarj_lint_configs import packagemanager, scaffold  # ruff: ignore[import-outside-top-level] — lazy route

    peers = manifest.eslint_peers()
    for name, pin in sorted(peers.items()):
        print(f"{name:50s} {pin}")
    root = _resolve_dest(args.dest)
    adopted = manifest.load(root)
    detected = scaffold.detect(root, typescript_dest=adopted.typescript_dest if adopted is not None else None)
    install_root = detected.typescript_install_root or detected.typescript_root or root
    client = packagemanager.detect(install_root)
    overrides = packagemanager.overrides_for(client)
    workspace = install_root != (detected.typescript_root or root) or (install_root / "pnpm-workspace.yaml").is_file()
    print(
        f"\ndetected {client} at {install_root}; install with:\n{packagemanager.install_command(client, workspace=workspace)}"
    )
    if client is packagemanager.PackageManager.PNPM and (install_root / "pnpm-workspace.yaml").is_file():
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
    from sarj_lint_configs import doctor  # ruff: ignore[import-outside-top-level] — lazy route

    root = _resolve_dest(args.dest)
    findings = doctor.diagnose(root)
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
            ["run `sarj-standards init`"]
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
        return 2
    return 1 if drifted or unadopted else 0


def cmd_upgrade(args: _Args) -> int:
    """Preview or apply the latest coherent compatibility bundle."""
    from sarj_lint_configs import (  # ruff: ignore[import-outside-top-level] — lazy route
        doctor,
        lifecycle,
        upgrade,
    )

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
        command = [
            executable,
            "--refresh",
            "--from",
            "sarj-lint-configs",
            "sarj-standards",
            "upgrade",
            "--offline",
            "--dest",
            str(_resolve_dest(args.dest)),
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
                timeout=_BOOTSTRAP_TIMEOUT_SECONDS,
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
    blockers = upgrade.unsafe_retired_findings(plan)
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
        print("error: upgrade failed; tracked configuration files were restored", file=sys.stderr)
        return status
    pending = upgrade.pending_install_findings(root) if args.no_install else []
    if pending:
        print(
            f"updated configuration: {root} now uses standards {__version__};"
            f" setup is incomplete ({len(pending)} dependency finding(s))"
        )
        for finding in pending:
            print(f"pending: {finding.id} {finding.where} -- {finding.detail}")
        print("next: run the skipped setup command(s), then `sarj-standards doctor`:")
        for command in lifecycle.install_commands(
            root,
            plan.ecosystems,
            hook_manager=plan.adopted.hook_manager,
        ):
            print(f"      {shlex.join(command.argv)}  (in {command.cwd})")
        return 0
    print(f"upgraded: {root} now uses standards {__version__}")
    return 0


def cmd_init(args: _Args) -> int:
    """Scaffold a repo's whole adoption in one command."""
    from sarj_lint_configs.libs.adoption import service  # ruff: ignore[import-outside-top-level] -- lazy route

    root = _resolve_dest(args.dest)
    selected_configs = tuple(dict.fromkeys((*args.configs, *args.only)))
    try:
        init_plan = service.plan_init(
            root,
            force=args.force,
            configs=selected_configs or None,
            python_dest=args.python_dest,
            typescript_dest=args.typescript_dest,
            profile=args.profile or "standard",
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
        print("init made no changes; resolve the wiring errors above and rerun", file=sys.stderr)
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
            for target in init_plan.sync.targets:
                print(f"would sync:  {target.destination}")
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
    print("\nafter checkout and frozen dependency installation, add this CI step:\n")
    print(service.scaffold.ci_snippet(plan, version=manifest.adopted_version()))
    return 0


def cmd_verify(args: _Args) -> int:
    from sarj_lint_configs import (  # ruff: ignore[import-outside-top-level] — lazy command route
        lifecycle,
        scaffold,
    )

    root = _resolve_dest(args.dest)
    if cmd_doctor(args):
        return 1
    sync_args = _Args()
    sync_args.dest = str(root)
    sync_args.check = True
    if cmd_sync(sync_args, next_steps=False):
        return 1
    adopted = _declared_manifest(args)
    if lifecycle.verify_custom_rules(root, paths=(".",) if adopted is None else adopted.verify_paths):
        return 1
    policy_args = _Args()
    policy_args.dest = str(root)
    if adopted is not None and adopted.profile == "application" and cmd_library_policy(policy_args):
        return 1
    return lifecycle.execute(lifecycle.verification_commands(scaffold.detect(root)))


def _declared_manifest(args: _Args) -> manifest.Manifest | None:
    """Read the project adoption recorded by `init`."""
    try:
        return manifest.load(_resolve_dest(args.dest))
    except TypeError, ValueError, SystemExit:
        return None


def cmd_library_policy(args: _Args, *, selected_paths: Iterable[str] | None = None) -> int:
    """Enforce the application profile's direct-dependency policy."""
    from sarj_lint_configs import library_policy  # ruff: ignore[import-outside-top-level] — lazy route

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


def cmd_check(args: _Args) -> int:  # ruff: ignore[too-many-locals] -- one command coordinates compatible lint phases.
    """Run source rules and the application dependency policy together."""
    from sarj_lint_configs import runner  # ruff: ignore[import-outside-top-level] — lazy route

    _validate_check_mode(args)
    root = _resolve_dest(args.dest)
    if args.output_format == "json" and not args.dependencies:
        print(
            "error: --format json is currently supported only with --dependencies; refusing mixed output",
            file=sys.stderr,
        )
        return 2
    if args.dependencies:
        return cmd_library_policy(args)
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
    if (
        len(args.files) == 1
        and Path(args.files[0]).resolve() == root
        and not args.noise_only
        and args.create_baseline is None
    ):
        args.files = []
    try:
        adopted = manifest.load(root)
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.create_baseline is not None:
        output = (root / args.create_baseline).resolve()
        try:
            relative = output.relative_to(root).as_posix()
        except ValueError:
            print("error: baseline path must stay inside the repository", file=sys.stderr)
            return 2
        if adopted is None:
            print("error: run `sarj-standards init` before creating a gradual baseline", file=sys.stderr)
            return 2
        selected = args.files or list(adopted.verify_paths)
        inputs = [str(Path(path) if Path(path).is_absolute() else root / path) for path in selected]
        try:
            status = runner.create_python_baseline(inputs, str(output))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if status:
            return status
        manifest.record_python_baseline(root, relative)
        print(f"created shrink-only baseline: {relative}")
        print("future `sarj-standards check` and pre-commit runs apply it automatically")
        return 0
    if args.staged:
        health_status = _check_staged_adoption_health(root, output_format=args.output_format)
        if health_status:
            return health_status
        if not args.files:
            return 0
    configured_baseline = (
        None if adopted is None or adopted.python_baseline is None else str(root / adopted.python_baseline)
    )
    if not args.files:
        if args.noise_only:
            from sarj_lint_configs import scaffold  # ruff: ignore[import-outside-top-level] -- lazy mode guard

            if scaffold.detect(root).typescript:
                print(
                    "error: --noise-only has no TypeScript rule subset; select Python paths or remove the option",
                    file=sys.stderr,
                )
                return 2
            selected = list(adopted.verify_paths) if adopted is not None else ["."]
            return runner.run(
                [str(root / path) for path in selected],
                noise_only=True,
                python_baseline=args.python_baseline or configured_baseline,
            )
        return cmd_verify(args)
    selected_paths = list(args.files)
    try:
        source_status = runner.run(
            selected_paths,
            noise_only=args.noise_only,
            python_baseline=args.python_baseline or configured_baseline,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    from sarj_lint_configs import lifecycle  # ruff: ignore[import-outside-top-level] — lazy selected route

    try:
        eslint_commands = lifecycle.selected_eslint_commands(
            root,
            selected_paths,
            label="staged" if args.staged else "selected",
        )
        if args.noise_only and eslint_commands:
            print("error: --noise-only has no TypeScript rule subset; remove the option", file=sys.stderr)
            return 2
        eslint_status = lifecycle.execute(eslint_commands)
    except ValueError as exc:
        print(f"error: cannot run selected ESLint: {exc}", file=sys.stderr)
        return 2
    policy_args = _Args()
    policy_args.dest = str(root)
    policy_args.quiet = True
    policy_status = cmd_library_policy(policy_args, selected_paths=selected_paths)
    return max(source_status, eslint_status, policy_status)


def cmd_analyze(args: _Args) -> int:
    """Render canonical native diagnostics for CI and programmatic consumers."""
    from sarj_lint_configs.api import (  # ruff: ignore[import-outside-top-level] -- keep CLI startup cheap
        AnalysisMode,
        Standards,
    )
    from sarj_lint_configs.libs.diagnostics import (  # ruff: ignore[import-outside-top-level] -- selected command only
        to_github,
        to_json,
        to_sarif,
        to_text,
    )

    if args.output is not None and str(args.output) != "-" and args.output_format not in {"json", "sarif"}:
        print("error: --output is supported only with --format json or sarif", file=sys.stderr)
        return 2
    report = Standards(_resolve_dest(args.dest)).analyze(
        args.files or None,
        external=args.external,
        trust=args.trust,
        mode=AnalysisMode(args.analysis_mode),
    )
    payload = (
        to_github(report, max_annotations_per_level=args.max_annotations_per_level)
        if args.output_format == "github"
        else {"json": to_json, "sarif": to_sarif, "text": to_text}[args.output_format](report)
    )
    if args.output is None or str(args.output) == "-":
        print(payload, end="")
    else:
        _write_report(_resolve_dest(args.dest), args.output, payload, output_format=args.output_format)
    return report.exit_code


def _write_report(root: Path, output: Path, payload: str, *, output_format: str) -> None:
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


def _validate_check_mode(args: _Args) -> None:
    """Reject option combinations whose values would otherwise be ignored."""
    if args.dependencies:
        incompatible = (
            (args.files, "selected paths"),
            (args.staged, "--staged"),
            (args.noise_only, "--noise-only"),
            (args.python_baseline is not None, "--baseline"),
            (args.create_baseline is not None, "--create-baseline"),
        )
        for enabled, label in incompatible:
            if enabled:
                _user_error(f"{label} cannot be combined with --dependencies")
    if args.create_baseline is not None and args.python_baseline is not None:
        _user_error("--create-baseline cannot be combined with --baseline")
    if args.create_baseline is not None and args.noise_only:
        _user_error("--create-baseline cannot be combined with --noise-only")
    if args.profile is not None and not args.dependencies:
        _user_error("--profile requires --dependencies")


def _check_staged_adoption_health(root: Path, *, output_format: str = "text") -> int:
    """Keep the staged fast path from bypassing generated config and pin drift."""
    from sarj_lint_configs import doctor  # ruff: ignore[import-outside-top-level] — lazy staged route

    drifted = [finding for finding in doctor.diagnose(root) if finding.level is doctor.Level.DRIFT]
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
    )
    unstaged = {part.decode("utf-8", errors="surrogateescape") for part in completed.stdout.split(b"\0") if part}
    repository = root.resolve()
    selected = {
        resolved.relative_to(repository).as_posix()
        for path in staged_paths
        if (resolved := Path(path).resolve()).is_relative_to(repository)
    }
    return tuple(sorted(unstaged & selected))


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
    from sarj_lint_configs import (  # ruff: ignore[import-outside-top-level] — lazy command route
        lifecycle,
        scaffold,
    )

    root = _resolve_dest(args.dest)
    return lifecycle.execute(lifecycle.format_commands(scaffold.detect(root)))


def cmd_inspect(args: _Args) -> int:
    from sarj_lint_configs import lifecycle  # ruff: ignore[import-outside-top-level] — lazy route

    sys.stdout.write(lifecycle.inspection_json(_resolve_dest(args.dest)))
    return 0


def cmd_update(args: _Args) -> int:
    """Update the coherent bundle, or only its generated configuration files."""
    config_options = args.only or args.force or args.profile is not None or args.python_dest or args.typescript_dest
    if config_options and not args.configs_only:
        _user_error("--config, --force, --profile, and config destinations require --configs-only")
    if args.configs_only and (args.offline or args.no_install):
        _user_error("--offline and --no-install cannot be combined with --configs-only")
    return cmd_sync(args) if args.configs_only else cmd_upgrade(args)


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
            args.repo_cmd = "rules"
            args.rules_cmd = "manifest"
            return _cmd_repo(args)
        case _:
            return 2


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else argv
    args = _build_parser().parse_args(raw_argv, namespace=_Args())
    if args.root is not None:
        if any(argument == "--dest" or argument.startswith("--dest=") for argument in raw_argv):
            _user_error("pass either positional ROOT or --dest, not both")
        args.dest = args.root
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: _Args) -> int:
    """Route one parsed command behind the consumer-facing error boundary."""
    match args.cmd:
        case "sync":
            return cmd_sync(args)
        case "list":
            return cmd_list()
        case "path":
            return cmd_path(args)
        case "peers":
            return cmd_peers(args)
        case "doctor":
            return cmd_doctor(args)
        case "upgrade":
            return cmd_upgrade(args)
        case "update":
            return cmd_update(args)
        case "init":
            return cmd_init(args)
        case "verify":
            return cmd_verify(args)
        case "format" | "fix":
            return cmd_format(args)
        case "inspect":
            return cmd_inspect(args)
        case "library-policy":
            return cmd_library_policy(args)
        case "check":
            return cmd_check(args)
        case "analyze":
            return cmd_analyze(args)
        case "show":
            return cmd_show(args)
        case "repo" | "maintain":
            return _cmd_repo(args)
        case _:  # argparse enforces `required=True`, so this is unreachable
            return 2


def _build_parser() -> argparse.ArgumentParser:  # ruff: ignore[too-many-locals] -- argparse keeps each command's contract explicit.
    parser = argparse.ArgumentParser(
        prog="sarj-standards",
        description=f"Adopt, check, fix, diagnose, and update sarj-ai standards (v{__version__}).",
        epilog=(
            "Start with `sarj-standards init`, then use `sarj-standards check`. "
            "Run `sarj-standards COMMAND --help` for command-specific examples."
        ),
    )
    parser.add_argument("--version", action="version", version=f"sarj-standards {__version__}")
    sub = parser.add_subparsers(
        dest="cmd",
        required=True,
        metavar="{init,check,analyze,fix,doctor,update,show,maintain}",
        title="commands",
    )

    p_sync = sub.add_parser("sync")
    p_sync.add_argument(
        "--dest",
        default=".",
        help="fallback destination for every config (default: cwd)",
    )
    p_sync.add_argument(
        "--profile",
        choices=manifest.PROFILES,
        help="config profile (default: manifest profile, else standard)",
    )
    p_sync.add_argument(
        "--python-dest",
        help="destination for Ruff/Pyright configs (for example: python)",
    )
    p_sync.add_argument(
        "--typescript-dest",
        help="destination for the ESLint config (for example: typescript)",
    )
    p_sync.add_argument(
        "--only",
        nargs="+",
        choices=sorted(CONFIG_NAMES),
        default=[],
        help="sync just these configs (default: the set in .sarj-standards.toml, else all)",
    )
    p_sync.add_argument("--force", action="store_true", help="overwrite existing files")
    p_sync.add_argument(
        "--check",
        action="store_true",
        help="report drift without writing; exit nonzero when a config differs",
    )

    sub.add_parser("list")

    p_path = sub.add_parser("path")
    p_path.add_argument("name", choices=sorted(CONFIG_NAMES))
    p_path.add_argument("--profile", choices=manifest.PROFILES, default="standard")

    p_peers = sub.add_parser("peers")
    p_peers.add_argument("--dest", default=".", help="project whose package manager to speak (default: cwd)")

    p_doctor = sub.add_parser(
        "doctor",
        help="report version drift across pyproject, pre-commit, CI and package.json",
    )
    p_doctor.add_argument("--dest", default=".", help="repo root to inspect (default: cwd)")
    p_doctor.add_argument("root", nargs="?", help="repository root (default: current directory)")
    p_doctor.add_argument(
        "--format",
        dest="output_format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )

    p_upgrade = sub.add_parser("upgrade")
    p_upgrade.add_argument("--dest", default=".", help="repo root to upgrade (default: cwd)")
    p_upgrade.add_argument("--check", action="store_true", help="preview without writing; exit 1 when updates exist")
    p_upgrade.add_argument(
        "--offline",
        action="store_true",
        help="target the executing bundle without resolving the latest release",
    )
    p_upgrade.add_argument(
        "--no-install",
        action="store_true",
        help="update configuration without installing dependencies or hooks",
    )

    p_init = sub.add_parser("init", help="scaffold the whole adoption: configs, wiring, hooks, CI")
    p_init.add_argument("--dest", default=".", help="repo root to scaffold (default: cwd)")
    p_init.add_argument("root", nargs="?", help="repository root (default: current directory)")
    p_init.add_argument(
        "--hooks",
        choices=manifest.HOOK_MANAGERS,
        help="hook manager (default: detect Lefthook, otherwise pre-commit)",
    )
    p_init.add_argument(
        "--python-dest",
        help="the directory that owns pyproject.toml (default: detected)",
    )
    p_init.add_argument(
        "--typescript-dest",
        help="the directory that owns the npm lockfile (default: detected)",
    )
    p_init.add_argument("--force", action="store_true", help="overwrite files that already exist")
    p_init.add_argument("--dry-run", action="store_true", help="print the plan without writing")
    p_init.add_argument(
        "--profile",
        choices=manifest.PROFILES,
        default="standard",
        help="policy profile to adopt (default: standard)",
    )
    p_init.add_argument(
        "--no-install", action="store_true", help="write wiring without installing dependencies or hooks"
    )
    p_init.add_argument(
        "--configs",
        nargs="+",
        choices=sorted(CONFIG_NAMES),
        default=[],
        help="legacy multi-value config selection; prefer repeatable --config",
    )
    p_init.add_argument(
        "--config",
        dest="only",
        action="append",
        choices=sorted(CONFIG_NAMES),
        default=[],
        help="select one config explicitly (repeatable)",
    )

    p_check = sub.add_parser(
        "check",
        help="check the complete repository, or applicable rules for selected paths",
    )
    p_check.add_argument(
        "--noise-only",
        action="store_true",
        help="run Python, config-prose, and AI-artifact noise rules (TypeScript uses the ESLint plugin)",
    )
    p_check.add_argument(
        "--baseline",
        "--python-baseline",
        dest="python_baseline",
        help="apply a shrink-only baseline (the Python-specific spelling remains compatible)",
    )
    p_check.add_argument(
        "--create-baseline",
        nargs="?",
        const=".sarj-standards-baseline.json",
        metavar="PATH",
        help="snapshot existing Python findings and make later checks enforce only-new findings",
    )
    p_check.add_argument("--dest", default=".", help="repository root for a complete check (default: cwd)")
    p_check.add_argument(
        "--dependencies",
        action="store_true",
        help="check only application-profile dependency policy",
    )
    p_check.add_argument(
        "--staged",
        action="store_true",
        help="run custom rules on hook-supplied paths, or discover staged files when none are supplied",
    )
    p_check.add_argument(
        "--profile",
        choices=manifest.PROFILES,
        help="override the adopted profile with --dependencies",
    )
    p_check.add_argument(
        "--format",
        dest="output_format",
        choices=("text", "json"),
        default="text",
    )
    p_check.add_argument(
        "files",
        nargs="*",
        help="selected paths; when omitted, check the complete repository",
    )

    analyze = sub.add_parser(
        "analyze",
        help="emit canonical native diagnostics for CI and editor integrations",
    )
    analyze.add_argument("--dest", default=".", help="repository root (default: cwd)")
    analyze.add_argument(
        "--format",
        dest="output_format",
        choices=("text", "json", "sarif", "github"),
        default="text",
        help="diagnostic output format (default: text)",
    )
    analyze.add_argument(
        "--mode",
        dest="analysis_mode",
        choices=("policy", "raw"),
        default="policy",
        help="apply adopted native policy, or scan the requested native corpus raw (default: policy)",
    )
    analyze.add_argument(
        "--external",
        action="store_true",
        help="also run installed Ruff/BasedPyright and applicable ESLint projects",
    )
    analyze.add_argument(
        "--trust",
        choices=("safe", "trusted"),
        default="safe",
        help="allow executable repository ESLint config only for a trusted checkout (default: safe)",
    )
    analyze.add_argument(
        "--output",
        type=Path,
        help="write JSON or SARIF atomically to PATH; use - for stdout",
    )
    analyze.add_argument(
        "--max-annotations-per-level",
        dest="max_annotations_per_level",
        type=int,
        choices=range(11),
        default=10,
        help="maximum GitHub annotations per severity, 0-10 (default: 10)",
    )
    analyze.add_argument(
        "files",
        nargs="*",
        metavar="PATH",
        help="selected contained paths; omitted uses adopted verify paths",
    )

    p_library_policy = sub.add_parser("library-policy")
    p_library_policy.add_argument("--dest", default=".", help="repository root (default: cwd)")
    p_library_policy.add_argument(
        "--profile",
        choices=manifest.PROFILES,
        help="override the adopted profile (useful for corpus measurement)",
    )
    p_library_policy.add_argument(
        "--format",
        dest="output_format",
        choices=("text", "json"),
        default="text",
    )

    for name in ("verify", "format", "inspect"):
        command = sub.add_parser(name)
        command.add_argument("--dest", default=".", help="repository root (default: cwd)")

    fix = sub.add_parser("fix", help="apply safe formatting and lint fixes")
    fix.add_argument("root", nargs="?", help="repository root (default: current directory)")
    fix.add_argument("--dest", default=".", help=argparse.SUPPRESS)

    update = sub.add_parser("update", help="upgrade standards or refresh bundled configurations")
    update.add_argument("root", nargs="?", help="repository root (default: current directory)")
    update.add_argument("--dest", default=".", help=argparse.SUPPRESS)
    update.add_argument("--check", action="store_true", help="preview without writing; exit 1 when changes exist")
    update.add_argument("--offline", action="store_true", help="use the executing bundle without resolving latest")
    update.add_argument("--no-install", action="store_true", help="do not install dependencies or hooks")
    update.add_argument(
        "--configs-only",
        action="store_true",
        help="refresh bundled configuration files without changing dependency versions",
    )
    update.add_argument("--force", action="store_true", help="overwrite existing configs with --configs-only")
    update.add_argument("--profile", choices=manifest.PROFILES, help="config profile with --configs-only")
    update.add_argument("--python-dest", help="Ruff/Pyright config destination with --configs-only")
    update.add_argument("--typescript-dest", help="ESLint config destination with --configs-only")
    update.add_argument(
        "--config",
        dest="only",
        action="append",
        choices=sorted(CONFIG_NAMES),
        default=[],
        help="refresh one config with --configs-only (repeatable)",
    )

    show = sub.add_parser("show", help="print read-only package and adoption information")
    show_commands = show.add_subparsers(dest="show_cmd", required=True)
    state = show_commands.add_parser("state", help="print detected adoption state as JSON")
    state.add_argument("root", nargs="?", help="repository root (default: current directory)")
    state.add_argument("--dest", default=".", help=argparse.SUPPRESS)
    show_commands.add_parser("configs", help="list bundled configurations")
    config = show_commands.add_parser("config", help="print one bundled configuration path")
    config.add_argument("name", choices=sorted(CONFIG_NAMES))
    config.add_argument("--profile", choices=manifest.PROFILES, default="standard")
    peers = show_commands.add_parser("peers", help="show tested ESLint peer dependencies and install command")
    peers.add_argument("root", nargs="?", help="repository root (default: current directory)")
    peers.add_argument("--dest", default=".", help=argparse.SUPPRESS)
    rules = show_commands.add_parser("rules", help="print the machine-readable custom-rule inventory")
    rules.add_argument("root", nargs="?", help="repository root (default: current directory)")
    rules.add_argument("--dest", default=".", help=argparse.SUPPRESS)

    _add_repo_parsers(sub.add_parser("maintain", help="repository policy, hooks, rule ledgers, and releases"))
    _add_repo_parsers(sub.add_parser("repo"))

    return parser


def _cmd_repo(args: _Args) -> int:
    try:
        return _run_repo(args)
    except (OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run_repo(args: _Args) -> int:  # ruff: ignore[too-many-locals] -- one lazy CLI router covers independent repository subcommands.
    if args.repo_cmd == "setup":
        from sarj_lint_configs.libs.setup import apply_setup, plan_setup  # ruff: ignore[import-outside-top-level]

        plan = plan_setup(_resolve_dest(args.dest))
        if args.check:
            if plan.install_hooks:
                print(f"would install: Lefthook repository hooks  (in {plan.root})")
            for command in plan.commands:
                print(f"would run: {shlex.join(command.argv)}  (in {command.cwd})")
            return 0
        return apply_setup(plan)
    if args.repo_cmd == "release":
        from sarj_lint_configs.libs import release  # ruff: ignore[import-outside-top-level] -- lazy route

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
            result = release.create_release_tags(root, tuple(args.release_targets), commit=args.release_commit)
            for tag_name in result.existing:
                print(f"release tag already exists: {tag_name}")
            for tag_name in result.created:
                print(f"created release tag: {tag_name}")
            return 0
        if args.release_cmd == "changes" and args.github_output is not None:
            changed = release.changed_release_targets(root, before=args.before, after=args.after)
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
            elif target == "lint-configs":
                publish_target = "lint-configs"
            elif target == "tsconfig":
                publish_target = "tsconfig"
            else:
                return 2
            release.publish_target(root, publish_target)
            return 0
        return 2
    if args.repo_cmd == "check":
        from sarj_lint_configs import repository  # ruff: ignore[import-outside-top-level] — lazy route

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
        from sarj_lint_configs import rule_maintenance  # ruff: ignore[import-outside-top-level] — lazy route

        result = rule_maintenance.sync_ledger(_resolve_dest(args.dest), check=args.check)
        print(result.message)
        return result.status
    if args.repo_cmd == "comment-corpus":
        from sarj_lint_configs import comment_corpus  # ruff: ignore[import-outside-top-level] — lazy route

        if args.include_text is not None:
            return comment_corpus.write_records(args.roots, args.include_text)
        return comment_corpus.emit_summary(args.roots, sys.stdout)
    if args.repo_cmd == "hooks" and args.hooks_cmd == "install":
        from sarj_lint_configs import hooks  # ruff: ignore[import-outside-top-level] — lazy route

        return hooks.install(_resolve_dest(args.dest))
    if args.repo_cmd == "rules" and args.rules_cmd == "manifest":
        from sarj_lint_configs import rule_maintenance  # ruff: ignore[import-outside-top-level] — lazy route

        print(json.dumps(rule_maintenance.inventory(_resolve_dest(args.dest)), indent=2))
        return 0
    return 2


def _add_repo_parsers(repo: argparse.ArgumentParser) -> None:  # ruff: ignore[too-many-locals] -- argparse requires one variable per subparser.
    commands = repo.add_subparsers(dest="repo_cmd", required=True)
    setup = commands.add_parser("setup", help="install every standards development environment and repository hook")
    setup.add_argument("--dest", default=".", help="standards repository root (default: cwd)")
    setup.add_argument("--check", action="store_true", help="print the deterministic setup plan without executing it")
    release = commands.add_parser("release", help="validate and build publishable release artifacts")
    release_commands = release.add_subparsers(dest="release_cmd", required=True)
    tag = release_commands.add_parser("check-tag", help="require a release tag to match its package manifest")
    tag.add_argument("tag")
    tag.add_argument("--dest", default=".", help="standards repository root (default: cwd)")
    verify_tags = release_commands.add_parser("verify-tags", help="verify all manifest release tags on origin")
    verify_tags.add_argument("--dest", default=".", help="standards repository root (default: cwd)")
    create_tags = release_commands.add_parser("create-tags", help="create and push manifest release tags")
    create_tags.add_argument(
        "release_targets",
        nargs="+",
        choices=("typescript", "python", "sql", "iac", "lint-configs", "tsconfig"),
    )
    create_tags.add_argument("--dest", default=".", help="standards repository root (default: cwd)")
    create_tags.add_argument("--commit", dest="release_commit", required=True, help="exact commit that was published")
    changes = release_commands.add_parser("changes", help="emit package version changes between Git revisions")
    changes.add_argument("--before", required=True)
    changes.add_argument("--after", required=True)
    changes.add_argument("--github-output", type=Path, required=True)
    changes.add_argument("--dest", default=".", help="standards repository root (default: cwd)")
    causality = release_commands.add_parser(
        "causality",
        help="require every publishable package change to bump its version",
    )
    causality.add_argument("--before", required=True)
    causality.add_argument("--after", required=True)
    causality.add_argument("--dest", default=".", help="standards repository root (default: cwd)")
    age = release_commands.add_parser("lock-age", help="enforce npm lockfile minimum release age")
    age.add_argument("lockfile", type=Path)
    age.add_argument("--dest", default=".", help="standards repository root (default: cwd)")
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
    typescript.add_argument("--dest", default=".", help="standards repository root (default: cwd)")
    typescript.add_argument("--output", type=Path, help="artifact directory (required for pack)")
    verify_wheel = release_commands.add_parser(
        "verify-wheel", help="require non-empty license text in built Python wheels"
    )
    verify_wheel.add_argument("wheels", nargs="+", type=Path)
    publish = release_commands.add_parser("publish", help="build and publish one package through its native client")
    publish.add_argument(
        "release_target",
        choices=("typescript", "python", "sql", "iac", "lint-configs", "tsconfig"),
    )
    publish.add_argument("--dest", default=".", help="standards repository root (default: cwd)")
    check = commands.add_parser("check", help="run repository policy gates")
    check.add_argument("--dest", default=".", help="repository root (default: cwd)")
    check.add_argument(
        "--only",
        dest="repo_only",
        action="append",
        choices=("ci-history", "file-conventions", "private-refs", "versions"),
        default=[],
    )
    check.add_argument("--commits", help="also inspect commit messages in this revision range")
    check.add_argument("--policy-dest", help="trusted repository policy root (default: --dest)")
    check.add_argument("--private-refs-file", help="private-reference TOML outside the scanned repository")
    check.add_argument("--quiet", action="store_true", help="hide finding details")
    ledger = commands.add_parser("sync-ledger", help="synchronize the rule compatibility ledger")
    ledger.add_argument("--dest", default=".", help="repository root (default: cwd)")
    ledger.add_argument("--check", action="store_true", help="report drift without writing")
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
    hook_commands.add_parser("install", help="install Lefthook").add_argument(
        "--dest", default=".", help="repository root (default: cwd)"
    )
    rule_commands = commands.add_parser("rules", help="inspect live custom rules").add_subparsers(
        dest="rules_cmd", required=True
    )
    rule_commands.add_parser("manifest", help="print a machine-readable rule inventory").add_argument(
        "--dest", default=".", help="repository root (default: cwd)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
