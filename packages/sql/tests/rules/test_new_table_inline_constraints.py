from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_sql_lint.__main__ import analyze, main
from sarj_sql_lint.rule_base import DefaultLevel
from sarj_sql_lint.rules.add_constraint_requires_not_valid import AddConstraintRequiresNotValid
from sarj_sql_lint.rules.new_table_inline_constraints import NewTableInlineConstraints


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


P = Path("supabase/migrations/001_invite.sql")
_CREATE = "CREATE TABLE child (id BIGINT, parent_id BIGINT, email TEXT);\n"
_PARENT_KEY_DECLARATIONS = (
    "CREATE UNIQUE INDEX parent_key ON parent (id DESC);",
    "CREATE UNIQUE INDEX parent_key ON parent USING btree (id);",
    "CREATE UNIQUE INDEX parent_key ON parent (id) WITH (fillfactor = 50);",
    "CREATE UNIQUE INDEX IF NOT EXISTS parent_key ON parent (id);",
    "CREATE UNIQUE INDEX CONCURRENTLY parent_key ON parent (id);",
    "ALTER TABLE parent ADD CONSTRAINT parent_unique UNIQUE (id);",
    "ALTER TABLE parent ADD CONSTRAINT parent_pkey PRIMARY KEY (id);",
)


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return NewTableInlineConstraints().check(path, source)


def test_documented_examples() -> None:
    verify_native_rule(NewTableInlineConstraints, analyze)


@pytest.mark.parametrize(
    "action",
    [
        "ADD PRIMARY KEY (id)",
        "ADD CONSTRAINT child_pkey PRIMARY KEY (id)",
        "ADD UNIQUE (email)",
        "ADD CONSTRAINT child_unique UNIQUE (parent_id, email)",
        "ADD CONSTRAINT positive CHECK (id > 0)",
        "ADD CHECK (id > 0)",
        "ADD CONSTRAINT parent_fk FOREIGN KEY (parent_id) REFERENCES parent(id)",
        "ADD FOREIGN KEY (parent_id) REFERENCES parent",
        "ADD PRIMARY KEY (id) DEFERRABLE INITIALLY DEFERRED",
        "ADD UNIQUE (email) DEFERRABLE INITIALLY IMMEDIATE",
        "ADD UNIQUE NULLS NOT DISTINCT (email)",
        "ADD CONSTRAINT child_unique UNIQUE NULLS DISTINCT (email)",
        "ADD CONSTRAINT positive CHECK (id > 0), ADD UNIQUE (email)",
    ],
)
def test_original_columns_can_have_inline_constraints(action: str) -> None:
    findings = _check(_CREATE + f"ALTER TABLE child {action};")
    assert len(findings) == 1
    assert findings[0].code == "SARJ121"
    assert findings[0].severity is DefaultLevel.ERROR


def test_plain_unique_index_can_use_a_named_unique_constraint() -> None:
    assert len(_check(_CREATE + "CREATE UNIQUE INDEX child_email_key ON child (email);")) == 1


@pytest.mark.parametrize(
    "consumer",
    [
        "ALTER TABLE child ADD PRIMARY KEY USING INDEX child_key;",
        "ALTER TABLE child ADD CONSTRAINT child_unique UNIQUE USING INDEX child_key;",
        "ALTER TABLE other ADD PRIMARY KEY USING INDEX child_key;",
        "DROP INDEX child_key;",
        "DROP INDEX IF EXISTS child_key;",
        "DROP INDEX CONCURRENTLY child_key;",
        "DROP INDEX other_key, child_key;",
        "ALTER INDEX child_key RENAME TO renamed_key;",
        "-- migrate:down\nDROP INDEX child_key;",
    ],
)
def test_standalone_index_consumers_preserve_lifecycle_and_attachment(consumer: str) -> None:
    source = _CREATE + "CREATE UNIQUE INDEX child_key ON child(id);\n" + consumer
    assert _check(source) == []


@pytest.mark.parametrize(
    ("table", "consumer", "expected"),
    [
        ("app.child", "DROP INDEX app.child_key;", 0),
        ("app.child", "DROP INDEX child_key;", 0),
        ("app.child", "DROP INDEX other.child_key;", 1),
        ("child", "DROP INDEX other_key;", 1),
        ("child", 'DROP INDEX "Child_key";', 1),
    ],
)
def test_index_consumers_obey_schema_and_quoted_name_identity(table: str, consumer: str, expected: int) -> None:
    source = f"CREATE TABLE {table}(id int); CREATE UNIQUE INDEX child_key ON {table}(id); {consumer}"
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    "index",
    [
        "CREATE INDEX child_email ON child (email)",
        "CREATE UNIQUE INDEX child_email ON child (LOWER(email))",
        "CREATE UNIQUE INDEX child_email ON child (email) WHERE parent_id IS NULL",
        "CREATE UNIQUE INDEX child_email ON child (email DESC)",
        'CREATE UNIQUE INDEX child_email ON child (email COLLATE "C")',
        "CREATE UNIQUE INDEX child_email ON child (email text_pattern_ops)",
        "CREATE UNIQUE INDEX child_email ON child USING btree (email)",
        "CREATE UNIQUE INDEX child_email ON child (email) INCLUDE (id)",
        "CREATE UNIQUE INDEX child_email ON child (email) WITH (fillfactor = 50)",
        "CREATE UNIQUE INDEX child_email ON child (email) TABLESPACE fast",
        "CREATE UNIQUE INDEX child_email ON child (email) NULLS NOT DISTINCT",
        "CREATE UNIQUE INDEX CONCURRENTLY child_email ON child (email)",
        "CREATE UNIQUE INDEX IF NOT EXISTS child_email ON child (email)",
        "CREATE UNIQUE INDEX app.child_email ON child (email)",
        "CREATE UNIQUE INDEX child_email ON ONLY child (email)",
    ],
)
def test_indexes_with_different_contracts_stay_separate(index: str) -> None:
    assert _check(_CREATE + index + ";") == []


@pytest.mark.parametrize(
    "between",
    [
        "INSERT INTO child (id) VALUES (1);",
        "UPDATE child SET id = 2;",
        "DELETE FROM child;",
        "WITH inserted AS (INSERT INTO child(id) VALUES (1) RETURNING *) SELECT * FROM inserted;",
        "SELECT populate_child();",
        "CALL populate_child();",
        "COPY child FROM '/data/child.csv';",
        "COMMIT; BEGIN;",
        "SET search_path = other;",
        "ALTER TABLE child ADD COLUMN age BIGINT;",
        "ALTER TABLE child RENAME TO old_child; ALTER TABLE existing RENAME TO child;",
        "ALTER TABLE child ATTACH PARTITION existing FOR VALUES FROM (0) TO (10);",
        "DROP TABLE child;",
        "DO $$ BEGIN INSERT INTO child(id) VALUES (1); END $$;",
        "DO $$ BEGIN ALTER TABLE child ADD PRIMARY KEY (id); END $$;",
        "unexpected SQL;",
    ],
)
def test_lost_empty_table_proof_preserves_later_migrations(between: str) -> None:
    assert _check(_CREATE + between + "\nALTER TABLE child ADD PRIMARY KEY (id);") == []


@pytest.mark.parametrize(
    "action",
    [
        "ADD CHECK (id > 0) NOT VALID",
        "ADD CONSTRAINT positive CHECK (id > 0) NOT ENFORCED",
        "ADD FOREIGN KEY (parent_id) REFERENCES parent(id) NOT VALID",
        "ADD PRIMARY KEY USING INDEX existing_idx",
        "ADD UNIQUE USING INDEX existing_idx",
        "ADD COLUMN another BIGINT, ADD PRIMARY KEY (another)",
        "ADD PRIMARY KEY (unknown_column)",
        "ADD FOREIGN KEY (unknown_column) REFERENCES parent(id)",
        "VALIDATE CONSTRAINT positive",
    ],
)
def test_validation_and_existing_object_contracts_stay_separate(action: str) -> None:
    assert _check(_CREATE + f"ALTER TABLE child {action};") == []


@pytest.mark.parametrize(
    "creation",
    [
        "CREATE TABLE IF NOT EXISTS child (id BIGINT)",
        "CREATE TABLE child AS SELECT 1 AS id",
        "CREATE TABLE child (LIKE existing INCLUDING ALL)",
        "CREATE TABLE child (id BIGINT) INHERITS (existing)",
        "CREATE TABLE child (id BIGINT) PARTITION BY RANGE (id)",
        "CREATE TABLE child PARTITION OF parent FOR VALUES FROM (0) TO (10)",
    ],
)
def test_conditional_or_inherited_creation_is_not_proven_fresh(creation: str) -> None:
    assert _check(f"{creation}; ALTER TABLE child ADD PRIMARY KEY (id);") == []


@pytest.mark.parametrize("prefix", ["CREATE TEMP TABLE", "CREATE TEMPORARY TABLE", "CREATE UNLOGGED TABLE"])
def test_unconditional_empty_table_variants(prefix: str) -> None:
    assert len(_check(f"{prefix} child (id BIGINT); ALTER TABLE child ADD PRIMARY KEY(id);")) == 1


@pytest.mark.parametrize(
    ("create_name", "alter_name", "expected"),
    [
        ("public.child", "public.child", 1),
        ('"child"', "child", 1),
        ('"Child"', "child", 0),
        ("public.child", "other.child", 0),
        ("public.child", "child", 0),
        ('"tenant.name"."child;archive"', '"tenant.name"."child;archive"', 1),
        ('"child""archive"', '"child""archive"', 1),
    ],
)
def test_relation_identity_and_quoted_separators(create_name: str, alter_name: str, expected: int) -> None:
    source = f"CREATE TABLE {create_name} (id BIGINT); ALTER TABLE {alter_name} ADD PRIMARY KEY (id);"
    assert len(_check(source)) == expected


def test_forward_and_cyclic_foreign_keys_do_not_require_table_reordering() -> None:
    source = (
        _CREATE
        + "CREATE TABLE parent (id BIGINT); ALTER TABLE child ADD FOREIGN KEY (parent_id) REFERENCES parent(id);"
    )
    assert _check(source) == []
    assert (
        len(
            _check(
                "CREATE TABLE parent (id BIGINT);"
                + _CREATE
                + "ALTER TABLE child ADD FOREIGN KEY (parent_id) REFERENCES parent(id);"
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    ("created_name", "referenced_name"),
    [
        ("parent", "public.parent"),
        ("public.parent", "parent"),
        ("public.parent", "currentdb.public.parent"),
        ("currentdb.public.parent", "public.parent"),
    ],
)
def test_mixed_qualification_cannot_prove_a_forward_reference_is_available(
    created_name: str, referenced_name: str
) -> None:
    source = (
        _CREATE
        + f"CREATE TABLE {created_name} (id BIGINT); "
        + f"ALTER TABLE child ADD FOREIGN KEY (parent_id) REFERENCES {referenced_name}(id);"
    )
    assert _check(source) == []


@pytest.mark.parametrize("key_statement", _PARENT_KEY_DECLARATIONS)
def test_referenced_key_declared_after_child_cannot_be_moved_before_it(key_statement: str) -> None:
    source = (
        "CREATE TABLE parent (id BIGINT);\n"
        + _CREATE
        + key_statement
        + "\nALTER TABLE child ADD FOREIGN KEY (parent_id) REFERENCES parent(id);"
    )
    findings = _check(source)
    assert not any(finding.line == source.count("\n") + 1 for finding in findings)


@pytest.mark.parametrize("key_statement", _PARENT_KEY_DECLARATIONS)
def test_referenced_key_declared_before_child_allows_inline_foreign_key(key_statement: str) -> None:
    source = (
        "CREATE TABLE parent (id BIGINT);\n"
        + key_statement
        + "\n"
        + _CREATE
        + "ALTER TABLE child ADD FOREIGN KEY (parent_id) REFERENCES parent(id);"
    )
    assert any(finding.line == source.count("\n") + 1 for finding in _check(source))


def test_self_reference_waits_for_a_later_unique_index() -> None:
    source = (
        _CREATE
        + "CREATE UNIQUE INDEX child_key ON child (id DESC);\n"
        + "ALTER TABLE child ADD FOREIGN KEY (parent_id) REFERENCES child(id);"
    )
    assert _check(source) == []


def test_self_reference_to_an_inline_primary_key_is_eligible() -> None:
    source = (
        "CREATE TABLE child (id BIGINT PRIMARY KEY, parent_id BIGINT);\n"
        "ALTER TABLE child ADD FOREIGN KEY (parent_id) REFERENCES child(id);"
    )
    assert len(_check(source)) == 1


def test_later_unrelated_unique_key_does_not_hide_available_referenced_key() -> None:
    source = (
        "CREATE TABLE parent(id int PRIMARY KEY, other int);\n"
        + _CREATE
        + "CREATE UNIQUE INDEX other_key ON parent(other);\n"
        "ALTER TABLE child ADD FOREIGN KEY(parent_id) REFERENCES parent(id);"
    )
    findings = _check(source)
    assert [finding.line for finding in findings] == [3, 4]


def test_same_named_creation_in_down_section_cannot_change_up_advice() -> None:
    source = (
        "-- migrate:up\n" + _CREATE + "ALTER TABLE child ADD FOREIGN KEY (parent_id) REFERENCES parent(id);\n"
        "-- migrate:down\nCREATE TABLE parent (id BIGINT);\n"
    )
    assert len(_check(source)) == 1


def test_up_section_cannot_prove_down_table_is_new() -> None:
    source = "-- migrate:up\n" + _CREATE + "-- migrate:down\nALTER TABLE child ADD PRIMARY KEY(id);"
    assert _check(source) == []


@pytest.mark.parametrize(
    ("header", "boundary"),
    [
        ("-- +goose Up\n", "-- +goose Down\n"),
        ("--liquibase formatted sql\n--changeset owner:1\n", "--changeset owner:2\n"),
    ],
)
def test_goose_sections_and_liquibase_changesets_keep_separate_empty_table_proofs(header: str, boundary: str) -> None:
    assert len(_check(header + _CREATE + "ALTER TABLE child ADD PRIMARY KEY(id);")) == 1
    assert _check(header + _CREATE + boundary + "ALTER TABLE child ADD PRIMARY KEY(id);") == []


def test_timeout_settings_and_separate_indexes_do_not_erase_empty_proof() -> None:
    source = (
        _CREATE
        + "SET LOCAL lock_timeout = '5s'; CREATE INDEX child_email ON child(email); ALTER TABLE child ADD PRIMARY KEY(id);"
    )
    assert len(_check(source)) == 1


def test_same_line_diagnostic_uses_original_column() -> None:
    source = "CREATE TABLE child (id BIGINT); ALTER TABLE child ADD PRIMARY KEY(id);"
    findings = _check(source)
    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (1, source.index("ALTER") + 1)


def test_comments_strings_and_dollar_data_are_not_statements() -> None:
    source = (
        "-- CREATE TABLE child(id BIGINT); ALTER TABLE child ADD PRIMARY KEY(id);\n"
        "SELECT 'CREATE TABLE child(id BIGINT); ALTER TABLE child ADD PRIMARY KEY(id)';\n"
        "SELECT $data$CREATE TABLE child(id BIGINT); ALTER TABLE child ADD PRIMARY KEY(id)$data$;\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "CREATE TABLE child(id BIGINT; ALTER TABLE child ADD PRIMARY KEY(id);",
        _CREATE + "ALTER TABLE child ADD PRIMARY KEY();",
        _CREATE + "ALTER TABLE child ADD CONSTRAINT . PRIMARY KEY(id);",
        _CREATE + "ALTER TABLE child ADD CONSTRAINT . UNIQUE(id);",
        _CREATE + "ALTER TABLE child ADD FOREIGN KEY(parent_id) REFERENCES;",
        _CREATE + "ALTER TABLE child ADD CHECK ();",
        _CREATE + "CREATE UNIQUE INDEX broken ON child();",
    ],
)
def test_malformed_input_is_not_inferred(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        (Path("schema.sql"), ""),
        (Path("tests/migrations/001.sql"), ""),
        (Path("fixtures/migrations/001.sql"), ""),
        (P, "-- dialect: sqlite\n"),
        (P, "-- PostgreSQL database dump\n"),
        (P, "--> statement-breakpoint\n"),
    ],
)
def test_unsupported_or_external_ownership_is_excluded(path: Path, prefix: str) -> None:
    source = prefix + "-- dialect: postgres\n" + _CREATE + "ALTER TABLE child ADD PRIMARY KEY (id);"
    assert _check(source, path) == []


def test_existing_table_not_valid_rule_retains_ownership() -> None:
    source = "ALTER TABLE child ADD CHECK (id > 0);"
    assert _check(source) == []
    assert len(AddConstraintRequiresNotValid().check(P, source)) == 1
    fresh = _CREATE + "ALTER TABLE child ADD CHECK (id > 0);"
    assert len(_check(fresh)) == 1
    assert AddConstraintRequiresNotValid().check(P, fresh) == []


def test_error_exit_and_exact_code_suppression(tmp_path: Path) -> None:
    target = tmp_path / "supabase/migrations/001.sql"
    target.parent.mkdir(parents=True)
    source = _CREATE + "ALTER TABLE child ADD PRIMARY KEY(id);"
    target.write_text(source)
    assert main(["check", "--rule", NewTableInlineConstraints.id, str(target)]) == 1
    target.write_text(
        source + " -- sarj-noqa: SARJ121 -- existing catalog compatibility requires the separate statement\n"
    )
    assert main(["check", "--rule", NewTableInlineConstraints.id, str(target)]) == 0
