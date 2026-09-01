from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.index_budget import IndexBudget


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


MIGRATION = Path("db/migrations/004_indexes.sql")


def _check(source: str, path: Path = MIGRATION) -> list[Diagnostic]:
    return IndexBudget().check(path, source)


@pytest.mark.parametrize(
    "example",
    IndexBudget.public_examples(),
    ids=tuple(example.example_id for example in IndexBudget.public_examples()),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, Path(example.focus_file.path))) == example.expected_count


def test_reports_every_unjustified_index_beyond_per_table_budget() -> None:
    source = "\n".join(f"CREATE INDEX event_{column}_idx ON event({column});" for column in "abcdef")
    assert [finding.line for finding in _check(source)] == [4, 5, 6]


def test_reports_indexes_beyond_file_budget_across_tables() -> None:
    source = "\n".join(f"CREATE INDEX table_{i}_idx ON table_{i}(owner_id);" for i in range(1, 11))
    assert [finding.line for finding in _check(source)] == [9, 10]


@pytest.mark.parametrize(
    "comment",
    [
        "-- index-justification: app-read: delivery queue; evidence: https://metrics.example.test/reads/812",
        "-- index-justification: app-read: delivery queue; ticket: APP-812",
        "-- index-justification: referential-action: ON DELETE CASCADE",
        "-- index-justification: referential-action: SET NULL",
    ],
)
def test_accepts_exact_immediately_preceding_justification(comment: str) -> None:
    source = (
        "CREATE INDEX a_idx ON event(a);\nCREATE INDEX b_idx ON event(b);\nCREATE INDEX c_idx ON event(c);\n"
        f"{comment}\nCREATE INDEX d_idx ON event(d);\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "comment",
    [
        "-- app-read: delivery queue; ticket: APP-812",
        "-- index-justification: app-read: delivery queue",
        "-- index-justification: app-read: delivery queue; ticket: someday",
        "-- index-justification: app-read: delivery queue; ticket: app-812",
        "-- index-justification: app-read:  ; ticket: APP-812",
        "-- index-justification: this seems important",
        "-- index-justification: referential-action:",
    ],
)
def test_rejects_vague_or_incomplete_justification(comment: str) -> None:
    source = (
        "CREATE INDEX a_idx ON event(a);\nCREATE INDEX b_idx ON event(b);\nCREATE INDEX c_idx ON event(c);\n"
        f"{comment}\nCREATE INDEX d_idx ON event(d);\n"
    )
    assert len(_check(source)) == 1


def test_justification_is_local_to_the_immediately_following_index() -> None:
    source = (
        "CREATE INDEX a_idx ON event(a);\nCREATE INDEX b_idx ON event(b);\nCREATE INDEX c_idx ON event(c);\n"
        "-- index-justification: app-read: delivery queue; ticket: APP-812\n\n"
        "CREATE INDEX d_idx ON event(d);\n"
    )
    assert len(_check(source)) == 1


def test_unique_indexes_do_not_consume_the_secondary_index_budget() -> None:
    source = "\n".join(f"CREATE UNIQUE INDEX event_{column}_key ON event({column});" for column in "abcdefghi")
    assert _check(source) == []


@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        (Path("schema.sql"), "-- PostgreSQL database dump\n"),
        (Path("queries/read.sql"), ""),
        (Path("db/migrations/004.sql"), "--> statement-breakpoint\n"),
    ],
)
def test_excludes_dump_non_migration_and_generated_sources(path: Path, prefix: str) -> None:
    source = prefix + "\n".join(f"CREATE INDEX event_{column}_idx ON event({column});" for column in "abcdef")
    assert _check(source, path) == []


def test_comments_and_strings_cannot_create_indexes() -> None:
    source = """
-- CREATE INDEX fake_a ON event(a);
SELECT 'CREATE INDEX fake_b ON event(b)';
CREATE INDEX a_idx ON event(a);
CREATE INDEX b_idx ON event(b);
CREATE INDEX c_idx ON event(c);
CREATE INDEX d_idx ON event(d);
"""
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].line == 7
