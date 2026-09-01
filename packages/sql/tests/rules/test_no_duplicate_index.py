from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.no_duplicate_index import NoDuplicateIndex


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


MIGRATION = Path("db/migrations/002_indexes.sql")


def _check(source: str, path: Path = MIGRATION) -> list[Diagnostic]:
    return NoDuplicateIndex().check(path, source)


@pytest.mark.parametrize(
    "example",
    NoDuplicateIndex.public_examples(),
    ids=tuple(example.example_id for example in NoDuplicateIndex.public_examples()),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, Path(example.focus_file.path))) == example.expected_count


def test_normalizes_table_method_whitespace_order_and_operator_class() -> None:
    source = """
CREATE INDEX first_idx ON public.event USING BTREE (owner_id DESC NULLS LAST, name text_pattern_ops);
CREATE INDEX second_idx ON PUBLIC.event ( owner_id desc nulls last, name TEXT_PATTERN_OPS );
"""
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].line == 3
    assert "second_idx" in findings[0].message
    assert "first_idx" in findings[0].message


@pytest.mark.parametrize(
    "second",
    [
        "CREATE INDEX second_idx ON event(b, a);",
        "CREATE INDEX second_idx ON event(a DESC, b);",
        "CREATE INDEX second_idx ON event(a int4_ops, b);",
        "CREATE INDEX second_idx ON event(a, b) INCLUDE (payload);",
        "CREATE INDEX second_idx ON event(a, b) WHERE active;",
        "CREATE INDEX second_idx ON event USING hash (a, b);",
        "CREATE INDEX second_idx ON other_event(a, b);",
    ],
)
def test_distinct_structural_shape_is_not_reported(second: str) -> None:
    assert _check(f"CREATE INDEX first_idx ON event(a, b);\n{second}\n") == []


def test_identical_include_and_predicate_are_reported() -> None:
    source = """
CREATE INDEX first_idx ON event(owner_id) INCLUDE (payload, created_at) WHERE status = 'open';
CREATE INDEX second_idx ON event (owner_id) INCLUDE(payload, created_at) WHERE status = 'open';
"""
    assert len(_check(source)) == 1


def test_string_literal_case_is_preserved_in_predicate_identity() -> None:
    source = """
CREATE INDEX first_idx ON event(owner_id) WHERE status = 'Open';
CREATE INDEX second_idx ON event(owner_id) WHERE status = 'open';
"""
    assert _check(source) == []


def test_three_equivalent_indexes_report_only_each_later_definition() -> None:
    source = "\n".join(f"CREATE INDEX index_{i} ON event(owner_id);" for i in range(3))
    assert [finding.line for finding in _check(source)] == [2, 3]


def test_duplicate_unique_indexes_are_reported_but_unique_and_nonunique_are_distinct() -> None:
    source = """
CREATE UNIQUE INDEX unique_a ON event(external_id);
CREATE UNIQUE INDEX unique_b ON event(external_id);
CREATE INDEX lookup_a ON event(external_id);
"""

    assert [finding.line for finding in _check(source)] == [3]


@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        (Path("structure.sql"), "-- Dumped by pg_dump version 16\n"),
        (Path("queries/read.sql"), ""),
        (Path("db/migrations/002.sql"), "--> statement-breakpoint\n"),
    ],
)
def test_excludes_dump_non_migration_and_generated_sources(path: Path, prefix: str) -> None:
    source = f"{prefix}CREATE INDEX first_idx ON event(a);\nCREATE INDEX second_idx ON event(a);\n"
    assert _check(source, path) == []


def test_comments_and_strings_do_not_form_duplicate_indexes() -> None:
    source = """
-- CREATE INDEX fake_idx ON event(owner_id);
SELECT 'CREATE INDEX fake_idx ON event(owner_id)';
CREATE INDEX real_idx ON event(owner_id);
"""
    assert _check(source) == []
