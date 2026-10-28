from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import shlex
import sys
from typing import TYPE_CHECKING

from sarj_standards.__main__ import main as cli_main
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.typed_containers import is_object_list


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from typing import TextIO


def validate(
    examples: Sequence[  # sarj-noqa: SARJ528 -- Reject nontext decoded command examples before execution.
        object
    ],
    *,
    invoke: Callable[[list[str]], int],
    output: TextIO,
) -> int:
    for index, example in enumerate(examples):
        output.write(f"{index}\n")
        output.flush()
        if not isinstance(example, str):
            return 1
        try:
            command = shlex.split(example)
        except ValueError:
            return 1
        if not command or command[0] != "code-standards":
            return 1
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            status: int | str | None
            try:
                status = invoke([*command[1:], "--help"])
            except SystemExit as exc:
                status = exc.code
        if status not in {0, None}:
            return 1
    return 0


def main() -> int:
    examples = parse_json(sys.stdin.read())
    if not is_object_list(examples):
        return 1
    return validate(examples, invoke=cli_main, output=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
