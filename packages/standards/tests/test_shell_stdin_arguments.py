from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting import textlint
from sarj_standards.libs.linting.devops_programs import ProgramProjectionError


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("command", ["bash -s file.sh", "bash -s -- -c data", "bash -su data", "bash -os posix data"])
def test_shell_stdin_operands_do_not_hide_source(tmp_path: Path, command: str) -> None:
    path = tmp_path / ".github/workflows/fixture.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"jobs:\n  build:\n    steps:\n    - run: |\n        {command} <<'SOURCE'\n        printf fixture\n        SOURCE\n",
        encoding="utf-8",
    )
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
    assert [(finding.code, finding.line) for finding in findings] == [("SARJ310", 4)]


@pytest.mark.parametrize("command", ["bash -s -Z data", "bash -s --unknown data", "bash -s -o invalid data"])
def test_unproven_shell_options_fail_coverage(tmp_path: Path, command: str) -> None:
    path = tmp_path / ".github/workflows/fixture.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"jobs:\n  build:\n    steps:\n    - run: |\n        {command} <<'SOURCE'\n        printf fixture\n        SOURCE\n",
        encoding="utf-8",
    )
    with pytest.raises(ProgramProjectionError, match="grammar"):
        textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
