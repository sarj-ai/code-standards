"""CLI for syncing bundled lint configs into a consumer repository."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

from . import CONFIGS_DIR, __version__


CONFIG_NAMES: dict[str, tuple[str, str]] = {
    "ruff":         ("ruff.strict.toml", ".ruff-strict.toml"),
    "pyright":      ("pyright.strict.json", ".pyright-strict.json"),
    "eslint":       ("eslint.strict.mjs", "eslint.strict.mjs"),
    "markdownlint": ("markdownlint.strict.yaml", ".markdownlint.yaml"),
    "taplo":        ("taplo.strict.toml", ".taplo.toml"),
}

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
    name: str = ""


def _resolve_dest(dest_arg: str) -> Path:
    dest = Path(dest_arg).resolve()
    if not dest.is_dir():
        msg = f"error: --dest {dest} is not a directory"
        raise SystemExit(msg)
    return dest


def cmd_sync(args: _Args) -> int:
    dest = _resolve_dest(args.dest)
    targets = [args.only] if args.only else list(CONFIG_NAMES)

    written = 0
    skipped = 0
    for name in targets:
        src_name, dst_name = CONFIG_NAMES[name]
        src = CONFIGS_DIR / src_name
        dst = dest / dst_name
        if dst.exists() and not args.force:
            print(f"skip:  {dst}  (exists; pass --force to overwrite)")
            skipped += 1
            continue
        _ = shutil.copyfile(src, dst)
        print(f"wrote: {dst}")
        written += 1

    print(f"\nsynced {written}/{len(targets)} config(s); {skipped} skipped.")
    if written and "ruff" in targets:
        print(_NEXT_STEPS)
    return 0


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sarj-lint-configs",
        description=f"sarj-ai maximally-strict lint configs (v{__version__})",
    )
    parser.add_argument("--version", action="version", version=f"sarj-lint-configs {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sync = sub.add_parser("sync", help="copy bundled configs into a repo")
    p_sync.add_argument("--dest", default=".", help="destination directory (default: cwd)")
    p_sync.add_argument("--only", choices=sorted(CONFIG_NAMES), help="sync just one config")
    p_sync.add_argument("--force", action="store_true", help="overwrite existing files")

    sub.add_parser("list", help="show available configs and target filenames")

    p_path = sub.add_parser("path", help="print the absolute path of a bundled config")
    p_path.add_argument("name", choices=sorted(CONFIG_NAMES))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv, namespace=_Args())
    match args.cmd:
        case "sync":
            return cmd_sync(args)
        case "list":
            return cmd_list()
        case "path":
            return cmd_path(args)
        case _:  # argparse enforces `required=True`, so this is unreachable
            return 2


if __name__ == "__main__":
    sys.exit(main())
