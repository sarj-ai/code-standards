from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release.make_checks import check_tags
from sarj_standards.libs.release.process import ProcessFailureError, ProcessResult


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@pytest.mark.parametrize(("statuses", "expected", "count"), [((0, 2), 0, 2), ((0, 0), 1, 2), ((7,), 7, 1)])
def test_make_tag_checks_preserve_current_and_negative_control_status(
    tmp_path: Path, statuses: Sequence[int], expected: int, count: int
) -> None:
    package = tmp_path / "packages/typescript/package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"version":"1.2.3"}', encoding="utf-8")
    calls: list[tuple[str, ...]] = []
    results = iter(statuses)
    command = ("configured-tool", "--argument", "value with spaces")

    def run(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        assert cwd == tmp_path
        assert not capture_output
        calls.append(argv)
        status = next(results)
        if status:
            raise ProcessFailureError(argv, status)
        return ProcessResult(0)

    assert check_tags(tmp_path, command, runner=run) == expected
    assert len(calls) == count
    arguments = (*command, "--root", ".", "maintain", "release", "check-tag")
    assert calls[0] == (*arguments, "typescript-v1.2.3")
    if count == 2:
        assert calls[1] == (*arguments, "typescript-v0.0.0")
