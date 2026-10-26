from __future__ import annotations

import ast
from hashlib import sha256
from typing import TYPE_CHECKING

from sarj_python_lint.rule_base import AutofixPolicy


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sarj_python_lint.rule_base import Fix


def python_source_hash(source: str) -> str:
    canonical = source.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return sha256(canonical.encode("utf-8")).hexdigest()


def apply_fixes(source: str, fixes: Sequence[Fix]) -> str:
    if not fixes:
        return source
    digest = python_source_hash(source)
    prefix = "\ufeff" if source.startswith("\ufeff") else ""
    raw = source[len(prefix) :].encode("utf-8")
    lines = raw.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    if not lines or lines[-1].endswith((b"\n", b"\r")):
        lines.append(b"")

    def offset(line: int, col: int) -> int:
        if line < 1 or line > len(lines) or col < 1 or col > len(lines[line - 1].rstrip(b"\r\n")) + 1:
            msg = "fix position is outside the source"
            raise ValueError(msg)
        prefix = lines[line - 1][: col - 1]
        prefix.decode("utf-8")
        return offsets[line - 1] + len(prefix)

    edits: list[tuple[int, int, bytes]] = []
    for fix in fixes:
        if fix.safety is not AutofixPolicy.SAFE or fix.source_hash != digest or not fix.edits:
            msg = "fix must be safe, nonempty and match the complete source revision"
            raise ValueError(msg)
        for edit in fix.edits:
            start = offset(edit.start_line, edit.start_col)
            end = offset(edit.end_line, edit.end_col)
            if end < start:
                msg = "fix range runs backwards"
                raise ValueError(msg)
            edits.append((start, end, edit.replacement.encode("utf-8")))
    edits.sort()
    result: list[bytes] = []
    previous = 0
    previous_start: int | None = None
    for start, end, replacement in edits:
        if start < previous or start == previous_start:
            msg = "fix groups overlap"
            raise ValueError(msg)
        result.extend((raw[previous:start], replacement))
        previous = end
        previous_start = start
    result.append(raw[previous:])
    fixed = b"".join(result).decode("utf-8")
    tree = ast.parse(fixed)
    compile(tree, "<native-fix>", "exec")
    return prefix + fixed
