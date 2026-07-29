"""CLI for syncing bundled lint configs into a consumer repository."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
from typing import Final

from . import CONFIGS_DIR, __version__, runner


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
)


class _Args(argparse.Namespace):
    """Typed view over the parsed namespace so attribute access isn't `Any`.

    Defaults mirror the argparse defaults; argparse overwrites them at parse time.
    """

    cmd: str = ""
    dest: str = "."
    only: str | None = None
    force: bool = False
    check: bool = False
    python_dest: str | None = None
    typescript_dest: str | None = None
    name: str = ""
    files: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.files = []


def cmd_sync(args: _Args) -> int:
    targets = [args.only] if args.only else list(CONFIG_NAMES)
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
    if written and "ruff" in targets:
        print(_NEXT_STEPS)
    return 0


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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv, namespace=_Args())
    match args.cmd:
        case "sync":
            return cmd_sync(args)
        case "list":
            return cmd_list()
        case "path":
            return cmd_path(args)
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
    p_sync.add_argument("--only", choices=sorted(CONFIG_NAMES), help="sync just one config")
    p_sync.add_argument("--force", action="store_true", help="overwrite existing files")
    p_sync.add_argument(
        "--check",
        action="store_true",
        help="report drift without writing; exit nonzero when a config differs",
    )

    sub.add_parser("list", help="show available configs and target filenames")

    p_path = sub.add_parser("path", help="print the absolute path of a bundled config")
    p_path.add_argument("name", choices=sorted(CONFIG_NAMES))

    p_check = sub.add_parser(
        "check",
        help="run every installed Sarj Python, SQL, and IaC rule",
    )
    runner.add_arguments(p_check)

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
