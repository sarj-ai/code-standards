from __future__ import annotations

import sys

from sarj_standards import __version__


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["--version"]:
        sys.stdout.write(f"code-standards {__version__}\n")
        return 0
    from sarj_standards.cli.main import main as cli_main  # ruff: ignore[import-outside-top-level] -- installed metadata probes do not need the command graph.

    return cli_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
