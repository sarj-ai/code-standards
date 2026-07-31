"""CLI for syncing bundled lint configs into a consumer repository."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
from typing import Final

from . import CONFIGS_DIR, __version__, doctor, manifest, runner, scaffold


CONFIG_NAMES: Final[dict[str, tuple[str, str]]] = {
    "ruff":         ("ruff.strict.toml", ".ruff-strict.toml"),
    "pyright":      ("pyright.strict.json", ".pyright-strict.json"),
    "eslint":       ("eslint.strict.mjs", "eslint.strict.mjs"),
    "markdownlint": ("markdownlint.strict.yaml", ".markdownlint.yaml"),
    "taplo":        ("taplo.strict.toml", ".taplo.toml"),
    "yamllint":     ("yamllint.strict.yaml", ".yamllint.yaml"),
}
_PYTHON_CONFIGS: Final = frozenset({"ruff", "pyright"})

_NEXT_STEPS = (
    "\nnext: in your pyproject.toml, add:\n"
     "  [tool.ruff]\n"
     '  extend = ".ruff-strict.toml"\n'
     "\n(or run `sarj-lint-configs init`, which writes that and the rest of the wiring)\n"
)


class _Args(argparse.Namespace):
    """Typed view over the parsed namespace so attribute access isn't `Any`.

    Defaults mirror the argparse defaults; argparse overwrites them at parse time.
    """

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

    def __init__(self) -> None:
        super().__init__()
        # `None` and `[]` mean the same thing for a list of choices, so these
        # default to empty rather than nullable; argparse replaces them when the
        # flag is given.
        self.files = []
        self.only = []
        self.configs = []


def cmd_sync(args: _Args, *, next_steps: bool = True) -> int:
    targets = _sync_targets(args)
    destinations: dict[str, Path] = {}

    def resolve_destination(kind: str, override: str | None) -> Path:
        if kind not in destinations:
            destinations[kind] = _resolve_dest(override or args.dest)
        return destinations[kind]

    results: list[str] = []
    for name in targets:
        src_name, dst_name = CONFIG_NAMES[name]
        src = CONFIGS_DIR / src_name
        if name == "eslint":
            dest = resolve_destination("typescript", args.typescript_dest)
        elif name in _PYTHON_CONFIGS:
            dest = resolve_destination("python", args.python_dest)
        else:
            dest = resolve_destination("default", None)
        dst = dest / dst_name
        results.append(_sync_one(src=src, dst=dst, force=args.force, check=args.check))

    if args.check:
        drift = results.count("drift")
        invalid = results.count("invalid")
        if invalid:
            print(f"\nchecked {len(targets)} config(s); {drift} drifted; {invalid} invalid.")
            return 2
        print(f"\nchecked {len(targets)} config(s); {drift} drifted.")
        return 1 if drift else 0

    written = results.count("written")
    skipped = results.count("skipped")
    invalid = results.count("invalid")
    if invalid:
        print(f"\nsynced {written}/{len(targets)} config(s); {skipped} skipped; {invalid} invalid.")
        return 2
    print(f"\nsynced {written}/{len(targets)} config(s); {skipped} skipped.")
    if written and next_steps and "ruff" in targets:
        print(_NEXT_STEPS)
    return 0


def _sync_targets(args: _Args) -> list[str]:
    """Decide which configs a `sync` or `sync --check` run covers.

    `--only` wins; otherwise a repo that ran `init` gets exactly the configs it
    declared. Falling back to all six matters: without the manifest, a Python
    repo had to commit `eslint.strict.mjs` and keep it byte-identical forever,
    or `sync --check` reported permanent drift and CI could never use it.

    Returns:
        Config names in canonical order.

    """
    if args.only:
        return list(dict.fromkeys(args.only))
    try:
        found = manifest.load(_resolve_dest(args.dest))
    except (ValueError, SystemExit):
        return list(CONFIG_NAMES)
    if found is None:
        return list(CONFIG_NAMES)
    known = [name for name in found.configs if name in CONFIG_NAMES]
    return known or list(CONFIG_NAMES)


def _resolve_dest(dest_arg: str) -> Path:
    unresolved = Path(dest_arg).absolute()
    dest = unresolved.resolve()
    paths = (unresolved, *unresolved.parents)
    if any(path.is_symlink() for path in paths) or not dest.is_dir():
        msg = f"error: --dest {dest} is not a directory"
        raise SystemExit(msg)
    return dest


def _sync_one(*, src: Path, dst: Path, force: bool, check: bool) -> str:
    if dst.is_symlink() or (dst.exists() and not dst.is_file()):
        print(f"invalid: {dst}  (destination must be a regular file)")
        return "invalid"
    if check:
        if not dst.is_file() or dst.read_bytes() != src.read_bytes():
            print(f"drift: {dst}")
            return "drift"
        print(f"ok:    {dst}")
        return "ok"
    if dst.exists() and not force:
        print(f"skip:  {dst}  (exists; pass --force to overwrite)")
        return "skipped"
    _ = shutil.copyfile(src, dst)
    print(f"wrote: {dst}")
    return "written"


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


def cmd_peers() -> int:
    """Print the npm packages `eslint.strict.mjs` needs, at versions that resolve.

    Returns:
        Zero; the command only reports.

    """
    peers = manifest.eslint_peers()
    for name, pin in sorted(peers.items()):
        print(f"{name:50s} {pin}")
    print(f"\n{manifest.eslint_install_command()}")
    return 0


def cmd_doctor(args: _Args) -> int:
    """Report every version pin site in a repo and whether it agrees with the rest.

    Returns:
        0 when every pin agrees, 1 on drift.

    """
    root = _resolve_dest(args.dest)
    findings = doctor.diagnose(root)
    for finding in findings:
        print(f"{finding.level.value:6s} {finding.where}  --  {finding.detail}")

    drifted = sum(1 for finding in findings if finding.level is doctor.Level.DRIFT)
    warned = sum(1 for finding in findings if finding.level is doctor.Level.WARN)
    print(f"\nchecked {len(findings)} version site(s); {drifted} drifted; {warned} unverified.")
    if drifted:
        print("fix: make every site match, then re-run. `init --force` rewrites the ones it owns.")
    return 1 if drifted else 0


def cmd_init(args: _Args) -> int:
    """Scaffold a repo's whole adoption in one command.

    Returns:
        0 on success, 1 when nothing could be detected.

    """
    root = _resolve_dest(args.dest)
    plan = scaffold.build_plan(root, force=args.force, configs=args.configs)

    detected = [
        name
        for name, present in (("python", plan.ecosystems.python), ("typescript", plan.ecosystems.typescript))
        if present
    ]
    print(f"detected: {', '.join(detected) or 'nothing'}")
    if not plan.ecosystems.any and not args.configs:
        for note in plan.notes:
            print(f"note:  {note}")
        return 1

    print(f"configs: {', '.join(plan.configs)}")
    if args.dry_run:
        print("\n-- dry run; nothing is written --")
        for name in plan.configs:
            print(f"would sync:  {root / CONFIG_NAMES[name][1]}")
    else:
        sync_args = _Args()
        sync_args.dest = str(root)
        sync_args.only = list(plan.configs)
        sync_args.force = args.force
        _ = cmd_sync(sync_args, next_steps=False)

    verb_write = "would write" if args.dry_run else "wrote"
    verb_edit = "would append to" if args.dry_run else "appended to"
    for path, _contents in plan.writes:
        print(f"{verb_write}: {path}")
    for path, _addition in plan.edits:
        print(f"{verb_edit}: {path}")
    for path, reason in plan.skips:
        print(f"skip:  {path}  ({reason})")

    if not args.dry_run:
        scaffold.apply(plan)

    for note in plan.notes:
        print(f"\nnote:  {note}")
    print("\nadd this to your CI workflow:\n")
    print(scaffold.ci_snippet(plan, version=manifest.adopted_version()))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv, namespace=_Args())
    match args.cmd:
        case "sync":
            return cmd_sync(args)
        case "list":
            return cmd_list()
        case "path":
            return cmd_path(args)
        case "peers":
            return cmd_peers()
        case "doctor":
            return cmd_doctor(args)
        case "init":
            return cmd_init(args)
        case "check":
            try:
                return runner.run(args.files)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        case _:  # argparse enforces `required=True`, so this is unreachable
            return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sarj-lint-configs",
        description=f"sarj-ai maximally-strict lint configs (v{__version__})",
    )
    parser.add_argument("--version", action="version", version=f"sarj-lint-configs {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sync = sub.add_parser("sync", help="copy bundled configs into a repo")
    p_sync.add_argument(
        "--dest",
        default=".",
        help="fallback destination for every config (default: cwd)",
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

    sub.add_parser("list", help="show available configs and target filenames")

    p_path = sub.add_parser("path", help="print the absolute path of a bundled config")
    p_path.add_argument("name", choices=sorted(CONFIG_NAMES))

    sub.add_parser("peers", help="print the npm packages eslint.strict.mjs needs, at tested versions")

    p_doctor = sub.add_parser(
        "doctor",
        help="report version drift across pyproject, pre-commit, CI and package.json",
    )
    p_doctor.add_argument("--dest", default=".", help="repo root to inspect (default: cwd)")

    p_init = sub.add_parser("init", help="scaffold the whole adoption: configs, wiring, hooks, CI")
    p_init.add_argument("--dest", default=".", help="repo root to scaffold (default: cwd)")
    p_init.add_argument("--force", action="store_true", help="overwrite files that already exist")
    p_init.add_argument("--dry-run", action="store_true", help="print the plan without writing")
    p_init.add_argument(
        "--configs",
        nargs="+",
        choices=sorted(CONFIG_NAMES),
        default=[],
        help="override the auto-detected config set",
    )

    p_check = sub.add_parser(
        "check",
        help="run every installed Sarj Python, SQL, and IaC rule",
    )
    runner.add_arguments(p_check)

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
