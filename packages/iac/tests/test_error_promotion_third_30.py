from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_iac_lint.__main__ import baseline_counts, main
from sarj_iac_lint.rule_base import DefaultLevel
from sarj_iac_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_rule_contracts import RuleId


@pytest.mark.parametrize(
    ("rule_id", "resource_type", "attribute"),
    [
        pytest.param("require-deletion-protection", "aws_db_instance", "deletion_protection", id="database"),
        pytest.param(
            "require-prevent-destroy-on-irreplaceable",
            "google_secret_manager_secret",
            "deletion_protection",
            id="secret",
        ),
    ],
)
def test_unresolved_provider_guard_is_nonblocking(
    rule_id: RuleId, resource_type: str, attribute: str, tmp_path: Path
) -> None:
    path = tmp_path / "storage.tf"
    rule = REGISTRY[rule_id]()
    path.write_text(f'resource "{resource_type}" "records" {{\n  {attribute} = false\n}}\n')
    disabled = rule.check(path, path.read_text())
    assert len(disabled) == 1
    assert disabled[0].severity is DefaultLevel.ERROR
    assert main(["check", "--rule", rule_id, str(path)]) == 1
    path.write_text(f'resource "{resource_type}" "records" {{\n  {attribute} = var.protect\n}}\n')
    unresolved = rule.check(path, path.read_text())
    assert len(unresolved) == 1
    assert unresolved[0].severity is DefaultLevel.WARNING
    assert rule.check(path, path.read_text()) == unresolved
    assert main(["check", "--rule", rule_id, str(path)]) == 0
    assert baseline_counts(unresolved) == {}
