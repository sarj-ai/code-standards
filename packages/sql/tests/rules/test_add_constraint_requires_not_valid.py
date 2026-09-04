from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.add_constraint_requires_not_valid import AddConstraintRequiresNotValid


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


P = Path("supabase/migrations/001.sql")


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return AddConstraintRequiresNotValid().check(path, source)


_PUBLIC_EXAMPLES = AddConstraintRequiresNotValid.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(AddConstraintRequiresNotValid().check(Path(focus.path), focus.source)) == example.expected_count


def test_check_constraint_without_not_valid_is_reported() -> None:
    diags = _check("ALTER TABLE users ADD CONSTRAINT check_age CHECK (age >= 18);")
    assert len(diags) == 1
    assert diags[0].code == "SARJ111"


def test_not_valid_silences_the_check_constraint() -> None:
    assert _check("ALTER TABLE users ADD CONSTRAINT check_age CHECK (age >= 18) NOT VALID;") == []


def test_not_valid_silences_foreign_key_constraint() -> None:
    source = "ALTER TABLE child ADD FOREIGN KEY (parent_id) REFERENCES parent(id) NOT VALID;"
    assert _check(source) == []


def test_sqlite_migration_is_not_given_postgres_advice() -> None:
    source = "-- dialect: sqlite\nALTER TABLE users ADD CONSTRAINT check_age CHECK (age >= 18);"
    assert _check(source, Path("db/migrations/001.sql")) == []


def test_generated_migration_is_not_reported() -> None:
    source = "--> statement-breakpoint\nALTER TABLE users ADD CHECK (age >= 18);"
    assert _check(source) == []


def test_table_created_earlier_in_same_migration_needs_no_deferred_validation() -> None:
    source = "CREATE TABLE users (age INTEGER);\nALTER TABLE users ADD CONSTRAINT check_age CHECK (age >= 18);"
    assert _check(source) == []


def test_reports_unnamed_check_and_foreign_key_constraints() -> None:
    source = (
        "ALTER TABLE users ADD CHECK (age >= 18);\nALTER TABLE users ADD FOREIGN KEY (team_id) REFERENCES teams(id);"
    )
    assert len(_check(source)) == 2


def test_reports_multiline_add_constraint() -> None:
    source = "ALTER TABLE users\nADD CONSTRAINT check_age\nCHECK (age >= 18);"
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].line == 2


def test_unique_constraint_is_not_a_validating_constraint() -> None:
    assert _check("ALTER TABLE t ADD CONSTRAINT uq UNIQUE (check);") == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "ALTER TABLE IF EXISTS users ADD CONSTRAINT users_age CHECK (age >= 18);",
            id="if-exists",
        ),
        pytest.param(
            "ALTER TABLE ONLY users ADD CONSTRAINT users_age CHECK (age >= 18);",
            id="only",
        ),
        pytest.param(
            "ALTER TABLE users * ADD CONSTRAINT users_age CHECK (age >= 18);",
            id="including-descendants",
        ),
        pytest.param(
            "ALTER TABLE IF EXISTS ONLY users * ADD FOREIGN KEY (team_id) REFERENCES teams(id);",
            id="if-exists-only-including-descendants",
        ),
    ],
)
def test_reports_supported_alter_table_variants(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'ALTER TABLE app."User Accounts" ADD CONSTRAINT "valid age" CHECK (age >= 18);',
            id="schema-qualified-space",
        ),
        pytest.param(
            'ALTER TABLE "tenant.schema"."user""accounts" ADD CHECK (age >= 18);',
            id="quoted-dot-and-escaped-quote",
        ),
        pytest.param(
            'ALTER TABLE "MixedCase" ADD FOREIGN KEY (team_id) REFERENCES "Team Directory"(id);',
            id="case-sensitive-table",
        ),
    ],
)
def test_reports_schema_qualified_and_quoted_identifiers(source: str) -> None:
    assert len(_check(source)) == 1


def test_reports_each_validating_constraint_in_a_multi_action_statement() -> None:
    source = """
ALTER TABLE users
    ADD CONSTRAINT users_age CHECK (age >= 18),
    ADD CONSTRAINT users_team FOREIGN KEY (team_id) REFERENCES teams(id);
"""
    diags = _check(source)
    assert len(diags) == 2
    assert {(diag.line, diag.col) for diag in diags} == {(3, 5), (4, 5)}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
ALTER TABLE users
    ADD CONSTRAINT users_age CHECK (age >= 18) NOT VALID,
    ADD CONSTRAINT users_team FOREIGN KEY (team_id) REFERENCES teams(id);
""",
            id="safe-check-before-validating-foreign-key",
        ),
        pytest.param(
            """
ALTER TABLE users
    ADD CONSTRAINT users_age CHECK (age >= 18),
    ADD CONSTRAINT users_team FOREIGN KEY (team_id) REFERENCES teams(id) NOT VALID;
""",
            id="validating-check-before-safe-foreign-key",
        ),
        pytest.param(
            """
ALTER TABLE users
    ALTER COLUMN age SET DEFAULT 18,
    ADD CONSTRAINT users_age CHECK (age >= 18);
""",
            id="unrelated-action-before-validating-check",
        ),
    ],
)
def test_not_valid_is_scoped_to_its_own_alter_action(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("ALTER TABLE users ADD CONSTRAINT users_age CHECK;", id="check-without-expression"),
        pytest.param("ALTER TABLE users ADD CONSTRAINT users_age CHECK ();", id="empty-check-expression"),
        pytest.param("ALTER TABLE users ADD CHECK (age >= 18;", id="unterminated-check-expression"),
        pytest.param("ALTER TABLE users ADD FOREIGN KEY;", id="foreign-key-without-columns"),
        pytest.param(
            "ALTER TABLE users ADD FOREIGN KEY (team_id);",
            id="foreign-key-without-reference",
        ),
        pytest.param(
            "ALTER TABLE users ADD FOREIGN KEY () REFERENCES teams(id);",
            id="foreign-key-with-empty-columns",
        ),
        pytest.param(
            "ALTER TABLE users ADD CONSTRAINT app.users_age CHECK (age >= 18);",
            id="schema-qualified-constraint-name",
        ),
        pytest.param(
            "ALTER TABLE users ADD FOREIGN KEY (team_id + 1) REFERENCES teams(id);",
            id="foreign-key-expression-in-columns",
        ),
        pytest.param(
            "ALTER TABLE users ADD FOREIGN KEY (team_id) REFERENCES teams(id + 1);",
            id="foreign-key-expression-in-referenced-columns",
        ),
    ],
)
def test_malformed_constraint_syntax_is_ignored(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "CREATE TABLE users (age INTEGER); ALTER TABLE users ADD CHECK (age >= 18);",
            id="unqualified-table",
        ),
        pytest.param(
            'CREATE TABLE app."User Accounts" (age INTEGER); ALTER TABLE app."User Accounts" ADD CHECK (age >= 18);',
            id="schema-qualified-quoted-table",
        ),
        pytest.param(
            "CREATE UNLOGGED TABLE users (age INTEGER); ALTER TABLE users ADD CHECK (age >= 18);",
            id="unlogged-table",
        ),
    ],
)
def test_unconditional_fresh_empty_table_is_exempt(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "CREATE TABLE IF NOT EXISTS users (age INTEGER); ALTER TABLE users ADD CHECK (age >= 18);",
            id="create-if-not-exists-may-preserve-old-rows",
        ),
        pytest.param(
            "CREATE TABLE users AS SELECT age FROM old_users; ALTER TABLE users ADD CHECK (age >= 18);",
            id="create-table-as-select",
        ),
        pytest.param(
            "CREATE TABLE users (age INTEGER); INSERT INTO users VALUES (21); ALTER TABLE users ADD CHECK (age >= 18);",
            id="insert-values",
        ),
        pytest.param(
            "CREATE TABLE users (age INTEGER); INSERT INTO users SELECT age FROM old_users; "
            "ALTER TABLE users ADD CHECK (age >= 18);",
            id="insert-select-backfill",
        ),
        pytest.param(
            "CREATE TABLE users (age INTEGER); COPY users (age) FROM '/tmp/users.csv'; "
            "ALTER TABLE users ADD CHECK (age >= 18);",
            id="copy-from-backfill",
        ),
        pytest.param(
            "CREATE TABLE users (age INTEGER) PARTITION BY RANGE (age); "
            "ALTER TABLE users ATTACH PARTITION old_users FOR VALUES FROM (0) TO (100); "
            "ALTER TABLE users ADD CHECK (age >= 18);",
            id="attach-populated-partition",
        ),
    ],
)
def test_potentially_populated_table_is_not_treated_as_fresh(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "-- ALTER TABLE users ADD CHECK (age >= 18);\nSELECT 1;",
            id="line-comment",
        ),
        pytest.param(
            "/* ALTER TABLE users ADD FOREIGN KEY (team_id) REFERENCES teams(id); */\nSELECT 1;",
            id="block-comment",
        ),
        pytest.param(
            "SELECT 'ALTER TABLE users ADD CHECK (age >= 18);';",
            id="single-quoted-string",
        ),
        pytest.param(
            "DO $$ BEGIN RAISE NOTICE 'ALTER TABLE users ADD CHECK (age >= 18);'; END $$;",
            id="dollar-quoted-body",
        ),
    ],
)
def test_non_executable_constraint_text_is_ignored(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "ALTER /* deployment comment */ TABLE users ADD CHECK (age >= 18);",
            id="comment-between-keywords",
        ),
        pytest.param(
            "ALTER TABLE users ADD CHECK (note <> 'NOT VALID');",
            id="not-valid-inside-string",
        ),
        pytest.param(
            "ALTER TABLE users ADD CHECK (note <> $$NOT VALID$$);",
            id="not-valid-inside-dollar-quoted-string",
        ),
        pytest.param(
            "ALTER TABLE users ADD CHECK (age >= 18) /* NOT VALID */;",
            id="not-valid-inside-comment",
        ),
    ],
)
def test_comments_and_strings_do_not_hide_a_validating_constraint(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("ALTER TABLE users ADD CONSTRAINT users_email UNIQUE (email);", id="unique"),
        pytest.param("ALTER TABLE users ADD CONSTRAINT users_pk PRIMARY KEY (id);", id="primary-key"),
        pytest.param(
            "ALTER TABLE bookings ADD CONSTRAINT no_overlap EXCLUDE USING gist (room WITH =);",
            id="exclude",
        ),
    ],
)
def test_constraint_types_that_do_not_support_not_valid_are_excluded(source: str) -> None:
    assert _check(source) == []
