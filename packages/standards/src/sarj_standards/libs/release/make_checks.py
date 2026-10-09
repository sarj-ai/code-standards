from __future__ import annotations

from pathlib import Path
import sys
from typing import TYPE_CHECKING

from .process import ProcessFailureError, run_process
from .tags import ReleaseTargetId, current_release_tag


if TYPE_CHECKING:
    from .process import ProcessRunner


def check_tags(root: Path, command: tuple[str, ...], *, runner: ProcessRunner = run_process) -> int:
    arguments = (*command, "--root", ".", "maintain", "release", "check-tag")
    try:
        runner((*arguments, current_release_tag(ReleaseTargetId.TYPESCRIPT, root)), cwd=root)
    except ProcessFailureError as error:
        return error.returncode
    try:
        runner((*arguments, "typescript-v0.0.0"), cwd=root)
    except ProcessFailureError:
        return 0
    return 1


def main() -> int:
    return check_tags(Path.cwd(), tuple(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
