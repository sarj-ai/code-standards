from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_sql_lint.__main__ import main
from sarj_sql_lint.rule_base import DefaultLevel
from sarj_sql_lint.rules.no_duplicate_index import NoDuplicateIndex


if TYPE_CHECKING:
    from pathlib import Path


def test_exact_duplicate_blocks_and_prefix_advice_stays_warning(tmp_path: Path) -> None:
    path = tmp_path / "migrations/002_indexes.sql"
    path.parent.mkdir()
    path.write_text("CREATE INDEX first_idx ON event(a);\nCREATE INDEX second_idx ON event(a);\n")
    rule = NoDuplicateIndex()
    exact = rule.check(path, path.read_text())
    assert len(exact) == 1
    assert exact[0].severity is DefaultLevel.ERROR
    assert main(["check", "--rule", rule.id, str(path)]) == 1
    path.write_text("CREATE INDEX first_idx ON event(a);\nCREATE INDEX second_idx ON event(a, b);\n")
    prefix = rule.check(path, path.read_text())
    assert len(prefix) == 1
    assert prefix[0].severity is DefaultLevel.WARNING
    assert main(["check", "--rule", rule.id, str(path)]) == 0
