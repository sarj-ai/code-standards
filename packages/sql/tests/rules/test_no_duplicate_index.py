from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules._index_analysis import parse_indexes
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


def test_shared_parser_supports_quoted_and_unnamed_indexes() -> None:
    source = """
CREATE INDEX ON "audit" . "Event Log"("owner id");
CREATE INDEX ON "audit"."Event Log"("owner id");
"""
    assert [finding.line for finding in _check(source)] == [3]


def test_shared_parser_ignores_stored_routine_body_text() -> None:
    source = """
CREATE PROCEDURE build_indexes() LANGUAGE plpgsql AS $body$
BEGIN
  CREATE INDEX first_idx ON event(owner_id);
  CREATE INDEX second_idx ON event(owner_id);
END
$body$;
"""
    assert _check(source) == []


def test_dollar_quoted_predicate_semicolon_does_not_truncate_signature() -> None:
    source = """
CREATE INDEX first_idx ON event(owner_id) WHERE value = $q$x;y$q$;
CREATE INDEX second_idx ON event(owner_id) WHERE value = $q$x;z$q$;
"""
    assert _check(source) == []


@pytest.mark.parametrize("delimiter", ["$$", "$q$"])
def test_dollar_quoted_predicate_body_case_is_preserved(delimiter: str) -> None:
    source = (
        f"CREATE INDEX first_idx ON event(owner_id) WHERE status = {delimiter}Open{delimiter};\n"
        f"CREATE INDEX second_idx ON event(owner_id) WHERE status = {delimiter}open{delimiter};\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize("key", ["field$tag$Open$tag$", "field$$Open$$"])
def test_dollar_delimiter_text_inside_unquoted_identifier_is_not_a_literal(key: str) -> None:
    source = f"CREATE INDEX first_idx ON event({key});\nCREATE INDEX second_idx ON event({key.lower()});\n"
    assert [finding.line for finding in _check(source)] == [2]


@pytest.mark.parametrize("predicate", ["(active", "active)", '"unterminated'])
def test_unbalanced_partial_index_predicate_is_not_treated_as_an_index(predicate: str) -> None:
    source = f"CREATE INDEX first_idx ON event(owner_id) WHERE {predicate};\n"
    if predicate != '"unterminated':
        source += f"CREATE INDEX second_idx ON event(owner_id) WHERE {predicate};\n"
    assert parse_indexes(source) == ()
    assert _check(source) == []


def test_create_index_text_inside_quoted_identifier_is_not_an_operation() -> None:
    source = """SELECT "CREATE INDEX fake_a ON event(owner_id);";
SELECT "CREATE INDEX fake_b ON event(owner_id);";
"""
    assert parse_indexes(source) == ()
    assert _check(source) == []


def test_drop_index_text_inside_quoted_identifier_does_not_clear_active_index() -> None:
    source = """CREATE INDEX old_idx ON event(owner_id);
SELECT "DROP INDEX old_idx;";
CREATE INDEX new_idx ON event(owner_id);
"""
    assert [finding.line for finding in _check(source)] == [3]


def test_unreserved_clause_word_can_be_a_predicate_identifier() -> None:
    source = "\n".join(f"CREATE INDEX index_{column} ON event({column}) WHERE include;" for column in "abcd")
    assert len(_check(source)) == 0


def test_quoted_access_method_case_is_preserved() -> None:
    source = """
CREATE INDEX first_idx ON event USING "MyMethod" (owner_id);
CREATE INDEX second_idx ON event USING "mymethod" (owner_id);
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "definitions",
    [
        (
            "CREATE INDEX first_idx ON ONLY event(owner_id);",
            "CREATE INDEX second_idx ON event(owner_id);",
        ),
        (
            "CREATE INDEX first_idx ON event(owner_id) WITH (fillfactor = 70);",
            "CREATE INDEX second_idx ON event(owner_id) WITH (fillfactor = 80);",
        ),
        (
            "CREATE INDEX first_idx ON event(owner_id) TABLESPACE fast;",
            "CREATE INDEX second_idx ON event(owner_id) TABLESPACE slow;",
        ),
        (
            "CREATE UNIQUE INDEX first_idx ON event(owner_id) NULLS DISTINCT;",
            "CREATE UNIQUE INDEX second_idx ON event(owner_id) NULLS NOT DISTINCT;",
        ),
    ],
    ids=["only-partitions", "storage-parameters", "tablespace", "nulls-mode"],
)
def test_material_index_options_distinguish_signatures(definitions: tuple[str, str]) -> None:
    assert _check("\n".join(definitions)) == []


def test_explicit_default_nulls_distinct_matches_implicit_unique_default() -> None:
    source = """
CREATE UNIQUE INDEX first_idx ON event(owner_id);
CREATE UNIQUE INDEX second_idx ON event(owner_id) NULLS DISTINCT;
"""
    assert [finding.line for finding in _check(source)] == [3]


def test_drop_removes_index_from_duplicate_comparison() -> None:
    source = """
CREATE INDEX old_idx ON event(owner_id);
DROP INDEX old_idx;
CREATE INDEX new_idx ON event(owner_id);
"""
    assert _check(source) == []


def test_same_name_idempotent_create_preserves_existing_definition() -> None:
    source = (
        "CREATE INDEX original ON event(owner_id);\n"
        "CREATE INDEX IF NOT EXISTS original ON event(created_at);\n"
        "CREATE INDEX duplicate ON event(owner_id);\n"
    )
    assert [finding.line for finding in _check(source)] == [3]


def test_create_before_drop_leaves_only_the_replacement_active() -> None:
    source = """
CREATE INDEX old_idx ON event(owner_id);
CREATE INDEX new_idx ON event(owner_id);
DROP INDEX old_idx;
"""
    assert _check(source) == []


def test_transient_duplicate_dropped_before_migration_end_is_not_reported() -> None:
    source = """
CREATE INDEX durable_idx ON event(owner_id);
CREATE INDEX transient_idx ON event(owner_id);
DROP INDEX transient_idx;
"""
    assert _check(source) == []


def test_only_surviving_duplicate_pair_is_reported() -> None:
    source = """
CREATE INDEX first_idx ON event(owner_id);
CREATE INDEX transient_idx ON event(owner_id);
CREATE INDEX last_idx ON event(owner_id);
DROP INDEX transient_idx;
"""
    assert [finding.line for finding in _check(source)] == [4]


def test_schema_qualified_drop_removes_only_matching_index() -> None:
    source = """
CREATE INDEX old_idx ON one.event(owner_id);
CREATE INDEX old_idx ON two.event(owner_id);
DROP INDEX one.old_idx;
CREATE INDEX new_idx ON one.event(owner_id);
"""
    assert _check(source) == []


def test_quoted_clause_words_and_parentheses_preserve_duplicate_signature() -> None:
    source = """
CREATE INDEX first_idx ON event("a)b") INCLUDE ("where") WHERE "include";
CREATE INDEX second_idx ON event("a)b") INCLUDE ("where") WHERE "include";
"""
    assert [finding.line for finding in _check(source)] == [3]


def test_quoted_comma_and_semicolon_index_name_can_be_dropped() -> None:
    source = """
CREATE INDEX "a,b;index" ON event(owner_id);
DROP INDEX "a,b;index";
CREATE INDEX replacement ON event(owner_id);
"""
    assert _check(source) == []
