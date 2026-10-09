from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from sarj_standards.libs.release.changes import pending_release_targets


if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)

    @app.command()
    def detect(
        *,
        root: Annotated[Path, typer.Option("--root")],
        before: Annotated[str, typer.Option("--before")],
        after: Annotated[str, typer.Option("--after")],
        github_output: Annotated[Path, typer.Option("--github-output")],
    ) -> None:
        pending = pending_release_targets(root.resolve(), before=before, after=after)
        with github_output.open("a", encoding="utf-8") as stream:
            for target, value in pending.items():
                stream.write(f"{target}={str(value).lower()}\n")

    app(args=None if argv is None else list(argv), prog_name="release-detect", standalone_mode=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
