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


def test_explicit_unique_indexes_consume_the_physical_index_budget() -> None:
    source = "\n".join(f"CREATE UNIQUE INDEX event_{column}_key ON event({column});" for column in "abcdefghi")
    assert [finding.line for finding in _check(source)] == [4, 5, 6, 7, 8, 9]


def test_uniqueness_justification_applies_only_to_unique_index() -> None:
    prefix = "CREATE INDEX a_idx ON event(a);\nCREATE INDEX b_idx ON event(b);\nCREATE INDEX c_idx ON event(c);\n"
    comment = "-- index-justification: uniqueness-constraint: external account identity; ticket: APP-812\n"
    assert _check(f"{prefix}{comment}CREATE UNIQUE INDEX d_idx ON event(d);\n") == []
    [finding] = _check(f"{prefix}{comment}CREATE INDEX d_idx ON event(d);\n")
    assert "uniqueness-constraint" not in finding.message


def test_unique_index_diagnostic_offers_uniqueness_justification() -> None:
    source = (
        "CREATE UNIQUE INDEX a_idx ON event(a);\n"
        "CREATE UNIQUE INDEX b_idx ON event(b);\n"
        "CREATE UNIQUE INDEX c_idx ON event(c);\n"
        "CREATE UNIQUE INDEX d_idx ON event(d);\n"
    )
    [finding] = _check(source)
    assert "uniqueness-constraint" in finding.message


def test_exact_table_and_file_boundaries_are_allowed() -> None:
    source = "\n".join(f"CREATE INDEX table_{i}_idx ON table_{i}(owner_id);" for i in range(1, 9))
    assert _check(source) == []


def test_duplicate_shapes_and_same_name_replacements_do_not_consume_budget() -> None:
    source = """
CREATE INDEX event_a_idx ON event(a);
CREATE INDEX duplicate_a_idx ON event(a);
CREATE INDEX event_b_idx ON event(b);
CREATE INDEX event_c_idx ON event(c);
DROP INDEX event_a_idx;
CREATE INDEX event_a_idx ON event(a, created_at);
"""
    assert _check(source) == []


def test_supports_quoted_qualified_identifiers_and_unnamed_indexes() -> None:
    source = """
CREATE INDEX "event a" ON "audit" . "Event Log"("owner id");
CREATE INDEX "event b" ON "audit"."Event Log"("created at");
CREATE INDEX ON "audit"."Event Log"("updated at");
CREATE INDEX "event d" ON "audit"."Event Log"("deleted at");
"""
    assert [finding.line for finding in _check(source)] == [5]


def test_each_unnamed_index_consumes_the_budget() -> None:
    source = "\n".join(f"CREATE INDEX ON event(column_{position});" for position in range(1, 5))
    assert [finding.line for finding in _check(source)] == [4]


def test_equivalent_quoted_lowercase_table_cannot_bypass_per_table_budget() -> None:
    source = """
CREATE INDEX event_a ON event(a);
CREATE INDEX event_b ON event(b);
CREATE INDEX event_c ON event(c);
CREATE INDEX event_d ON "event"(d);
"""
    assert [finding.line for finding in _check(source)] == [5]


def test_same_index_name_in_distinct_schemas_does_not_hide_table_budget() -> None:
    source = """
CREATE INDEX idx_status ON one.event(a);
CREATE INDEX idx_status ON two.event(a);
CREATE INDEX two_b ON two.event(b);
CREATE INDEX two_c ON two.event(c);
CREATE INDEX two_d ON two.event(d);
"""
    assert [finding.line for finding in _check(source)] == [6]


def test_ignores_create_index_text_in_stored_routine_bodies() -> None:
    source = """
CREATE FUNCTION build_indexes() RETURNS void AS $fn$
BEGIN
  CREATE INDEX body_a ON event(a);
  CREATE INDEX body_b ON event(b);
  CREATE INDEX body_c ON event(c);
  CREATE INDEX body_d ON event(d);
END
$fn$ LANGUAGE plpgsql;
"""
    assert _check(source) == []


def test_comment_before_anonymous_program_body_remains_irrelevant() -> None:
    source = """
-- CREATE FUNCTION fake() RETURNS void AS
DO $fn$
BEGIN
  CREATE INDEX body_a ON event(a);
  CREATE INDEX body_b ON event(b);
  CREATE INDEX body_c ON event(c);
  CREATE INDEX body_d ON event(d);
END
$fn$;
"""
    assert _check(source) == []


def test_does_not_infer_indexes_from_anonymous_program_body() -> None:
    source = """
DO $fn$
BEGIN
  CREATE INDEX body_a ON event(a);
  CREATE INDEX body_b ON event(b);
  CREATE INDEX body_c ON event(c);
  CREATE INDEX body_d ON event(d);
END
$fn$;
"""
    assert _check(source) == []


def test_ordinary_dollar_quoted_literal_cannot_create_indexes() -> None:
    source = """
COMMENT ON TABLE event IS $tag$
CREATE INDEX body_a ON event(a);
CREATE INDEX body_b ON event(b);
CREATE INDEX body_c ON event(c);
CREATE INDEX body_d ON event(d);
$tag$;
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "suffix",
    [
        "INCLUDE (payload) INCLUDE (created_at)",
        "WITH (fillfactor = 80) WITH (deduplicate_items = on)",
        "NULLS DISTINCT NULLS NOT DISTINCT",
        "TABLESPACE fast TABLESPACE slow",
    ],
)
def test_repeated_index_clauses_do_not_consume_budget(suffix: str) -> None:
    source = "\n".join(f"CREATE INDEX event_{column}_idx ON event({column}) {suffix};" for column in "abcdef")
    assert _check(source) == []


def test_clause_words_and_parentheses_inside_quoted_identifiers_are_data() -> None:
    source = "\n".join(
        f'CREATE INDEX event_{column}_idx ON event("{column})value") INCLUDE ("where") WHERE "include";'
        for column in "abcdef"
    )
    assert [finding.line for finding in _check(source)] == [4, 5, 6]


def test_unreserved_clause_word_in_predicate_does_not_hide_index() -> None:
    source = "\n".join(f"CREATE INDEX event_{column}_idx ON event({column}) WHERE include;" for column in "abcd")
    assert [finding.line for finding in _check(source)] == [4]


@pytest.mark.parametrize("dialect", ["mysql", "sqlite"])
def test_explicit_non_postgres_dialects_are_excluded(dialect: str) -> None:
    source = f"-- dialect: {dialect}\n" + "\n".join(
        f"CREATE INDEX event_{column}_idx ON event({column});" for column in "abcdef"
    )
    assert _check(source) == []


def test_malformed_create_index_tail_does_not_consume_budget() -> None:
    source = "\n".join(f"CREATE INDEX event_{column}_idx ON event({column}) THIS IS NOT SQL;" for column in "abcdef")
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(Path("tests/migrations/001.sql"), id="tests-directory"),
        pytest.param(Path("__tests__/migrations/001.sql"), id="dunder-tests-directory"),
    ],
)
def test_test_migrations_are_excluded(path: Path) -> None:
    source = "\n".join(f"CREATE INDEX event_{column}_idx ON event({column});" for column in "abcdef")
    assert _check(source, path) == []


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
