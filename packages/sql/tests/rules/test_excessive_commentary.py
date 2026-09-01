from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.excessive_commentary import ExcessiveCommentary


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import RuleExample


_PUBLIC_EXAMPLES = ExcessiveCommentary.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(ExcessiveCommentary().check(Path(focus.path), focus.source)) == example.expected_count


def test_dump_and_non_migration_sources_are_excluded() -> None:
    prose = "\n".join(f"-- Narrative sentence number {index} explains the next statement." for index in range(5))
    assert ExcessiveCommentary().check(Path("schema.sql"), f"-- PostgreSQL database dump\n{prose}\n") == []
    assert ExcessiveCommentary().check(Path("queries/report.sql"), f"{prose}\nSELECT 1;\n") == []


def test_operational_constraint_is_preserved() -> None:
    source = """-- This backfill processes 1000 rows per transaction.
-- Keep lock_timeout at 3 seconds while API-812 writes continue.
-- Roll back by restoring the snapshot before dropping the column.
-- Security review requires the permission change to remain atomic.
SELECT 1;
"""
    assert ExcessiveCommentary().check(Path("migrations/001.sql"), source) == []
