from __future__ import annotations

from pathlib import Path
import sys

from sarj_standards import __version__


_ROOTED_VERSION_ARGUMENT_COUNT = 3


def main(argv: list[str] | None = None) -> int:
    # The launcher probes the exact version before typed Typer dispatch.
    arguments = sys.argv[1:] if argv is None else argv  # sarj-noqa: SARJ533 -- typed CLI forwarding
    if arguments == ["--version"] or (
        len(arguments) == _ROOTED_VERSION_ARGUMENT_COUNT
        and arguments[0] == "--root"
        and arguments[2] == "--version"
        and Path(arguments[1]).is_absolute()
    ):
        sys.stdout.write(f"code-standards {__version__}\n")
        return 0
    from sarj_standards.cli.main import main as cli_main  # ruff: ignore[import-outside-top-level] -- installed metadata probes do not need the command graph.

    return cli_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
