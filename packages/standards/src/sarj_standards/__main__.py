from __future__ import annotations

from pathlib import Path
import sys

from sarj_standards import __version__


_ROOTED_VERSION_ARGUMENT_COUNT = 3
_COMMIT_MESSAGE_ARGUMENT_COUNT = 2


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
    if (
        len(arguments) == _COMMIT_MESSAGE_ARGUMENT_COUNT
        and arguments[0] == "commit-message"
        and not arguments[1].startswith("-")
    ):
        from repo_standards.core.commit_message import check_commit_message_file  # ruff: ignore[import-outside-top-level] -- reuse the canonical validator without loading unrelated commands.

        try:
            accepted = (
                Path.cwd().resolve().is_dir()
                and (
                    result := check_commit_message_file(Path(arguments[1]), fix_safe=False, allow_temporary=True)
                ).satisfied
                and result.replacement_header is None
            )
        except KeyboardInterrupt:
            sys.stderr.write("error: interrupted\n")
            return 130
        except OSError, ValueError:
            accepted = False
        if accepted:
            return 0
    from sarj_standards.cli.main import main as cli_main  # ruff: ignore[import-outside-top-level] -- installed metadata probes do not need the command graph.

    return cli_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
