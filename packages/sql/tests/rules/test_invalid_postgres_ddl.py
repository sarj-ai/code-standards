from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_sql_lint.__main__ import analyze
from sarj_sql_lint.rule_base import DefaultLevel
from sarj_sql_lint.rules.invalid_postgres_ddl import InvalidPostgresDdl


P = Path("supabase/migrations/001_index.sql")


def test_documented_examples() -> None:
    verify_native_rule(InvalidPostgresDdl, analyze)


@pytest.mark.parametrize("method", ["hash", "gist", "spgist", "gin", "brin", '"hash"'])
def test_known_builtin_methods_cannot_create_unique_indexes(method: str) -> None:
    source = f"CREATE UNIQUE INDEX item_key ON item USING {method} (id);"
    findings = InvalidPostgresDdl().check(P, source)
    assert len(findings) == 1
    assert "UNIQUE" in findings[0].message
    assert findings[0].severity is DefaultLevel.WARNING


@pytest.mark.parametrize("method", ["btree", "bloom", "custom_hash", '"HASH"'])
def test_supported_or_unknown_unique_methods_remain_outside_non_unique_check(method: str) -> None:
    source = f"CREATE UNIQUE INDEX item_key ON item USING {method} (id);"
    assert InvalidPostgresDdl().check(P, source) == []


@pytest.mark.parametrize("method", ["hash", "spgist", '"spgist"'])
def test_single_key_methods_cannot_take_multiple_keys(method: str) -> None:
    source = f"CREATE INDEX item_key ON item USING {method} (a, b);"
    findings = InvalidPostgresDdl().check(P, source)
    assert len(findings) == 1
    assert "one key column" in findings[0].message


@pytest.mark.parametrize("method", ["btree", "gist", "gin", "brin", "custom_method"])
def test_multicolumn_or_unknown_methods(method: str) -> None:
    source = f"CREATE INDEX item_key ON item USING {method} (a, b);"
    assert InvalidPostgresDdl().check(P, source) == []


@pytest.mark.parametrize(
    "definition",
    [
        "CREATE INDEX item_key ON item USING spgist (point) INCLUDE (label, id)",
        "CREATE INDEX item_key ON item USING hash ((a+b))",
        "CREATE INDEX item_key ON item USING hash (function_with_arguments(a,b))",
        'CREATE INDEX item_key ON item USING hash ("a,b")',
    ],
)
def test_includes_and_expression_arguments_do_not_inflate_key_count(definition: str) -> None:
    assert InvalidPostgresDdl().check(P, definition + ";") == []


@pytest.mark.parametrize("included", ["LOWER(label)", "(label)", "label || suffix", "1", "app.label", "label DESC"])
def test_include_accepts_only_column_names(included: str) -> None:
    source = f"CREATE INDEX item_key ON item (id) INCLUDE ({included});"
    findings = InvalidPostgresDdl().check(P, source)
    assert len(findings) == 1
    assert "INCLUDE" in findings[0].message


@pytest.mark.parametrize(
    "included", ["label", '"label"', '"a,b"', '"a.b"', '"label""old"', "\u00e9tiquette", '"a\nname"']
)
def test_plain_unicode_and_quoted_include_columns(included: str) -> None:
    source = f"CREATE INDEX item_key ON item (id) INCLUDE ({included});"
    assert InvalidPostgresDdl().check(P, source) == []


@pytest.mark.parametrize("name", ["app.item_key", '"app"."item_key"', '"schema.name"."item_key"'])
def test_index_name_cannot_be_schema_qualified(name: str) -> None:
    source = f"CREATE INDEX {name} ON app.item(id);"
    findings = InvalidPostgresDdl().check(P, source)
    assert len(findings) == 1
    assert "schema-qualified" in findings[0].message


@pytest.mark.parametrize("name", ["item_key", '"app.item_key"', "\u00e9tiquette", '"item;key"'])
def test_single_index_names_may_have_quoted_punctuation(name: str) -> None:
    source = f"CREATE INDEX {name} ON app.item(id);"
    assert InvalidPostgresDdl().check(P, source) == []


@pytest.mark.parametrize(
    "action",
    [
        "ADD UNIQUE(id) NOT VALID",
        "ADD CONSTRAINT item_key UNIQUE(id) NOT VALID",
        "ADD CONSTRAINT item_key UNIQUE NULLS NOT DISTINCT(id) NOT VALID",
        "ADD PRIMARY KEY(id) NOT VALID",
        'ADD CONSTRAINT "item;key" PRIMARY KEY(id) DEFERRABLE NOT VALID',
        "ADD UNIQUE USING INDEX existing_key NOT VALID",
    ],
)
def test_unique_and_primary_keys_do_not_support_not_valid(action: str) -> None:
    findings = InvalidPostgresDdl().check(P, f"ALTER TABLE app.item {action};")
    assert len(findings) == 1
    assert "NOT VALID" in findings[0].message


@pytest.mark.parametrize(
    "action",
    [
        "ADD CONSTRAINT item_key UNIQUE(id)",
        "ADD PRIMARY KEY(id)",
        "ADD CONSTRAINT item_fk FOREIGN KEY(parent_id) REFERENCES parent(id) NOT VALID",
        "ADD CONSTRAINT item_check CHECK(id > 0) NOT VALID",
        "ADD CONSTRAINT item_not_null NOT NULL id NOT VALID",
        'ADD CONSTRAINT "NOT VALID" UNIQUE(id)',
        'ADD UNIQUE("NOT VALID")',
        "ADD COLUMN note TEXT CHECK (note <> 'NOT VALID')",
        "VALIDATE CONSTRAINT item_check",
        "DROP CONSTRAINT IF EXISTS item_key",
    ],
)
def test_eligible_validation_and_quoted_words_remain_valid(action: str) -> None:
    assert InvalidPostgresDdl().check(P, f"ALTER TABLE item {action};") == []


def test_one_index_diagnostic_combines_all_proven_errors() -> None:
    source = "CREATE UNIQUE INDEX app.item_key ON item USING hash(a,b) INCLUDE(lower(c));"
    findings = InvalidPostgresDdl().check(P, source)
    assert len(findings) == 1
    assert all(word in findings[0].message for word in ("UNIQUE", "one key", "INCLUDE", "schema-qualified"))


def test_multiple_actions_have_distinct_original_offsets() -> None:
    source = "-- migration\r\nALTER TABLE item\r\n  ADD UNIQUE(a) NOT VALID,\r\n  ADD PRIMARY KEY(b) NOT VALID;"
    findings = InvalidPostgresDdl().check(P, source)
    assert [(finding.line, finding.col) for finding in findings] == [(3, 3), (4, 3)]


def test_same_line_original_index_position() -> None:
    source = "SELECT 1; CREATE INDEX app.item_key ON item(id);"
    findings = InvalidPostgresDdl().check(P, source)
    assert [(finding.line, finding.col) for finding in findings] == [(1, 11)]


@pytest.mark.parametrize(
    "source",
    [
        "-- CREATE INDEX app.item_key ON item(id);\nSELECT 1;",
        "SELECT 'CREATE INDEX app.item_key ON item(id);';",
        "SELECT $$CREATE INDEX app.item_key ON item(id);$$;",
        "DO $$ BEGIN CREATE INDEX app.item_key ON item(id); END $$;",
        "DO $$ BEGIN ALTER TABLE item ADD UNIQUE(id) NOT VALID; END $$;",
        "CREATE INDEX item_key ON item USING hash (a, b;",
        "ALTER TABLE item ADD CONSTRAINT",
    ],
)
def test_comments_literals_bodies_and_incomplete_definitions(source: str) -> None:
    assert InvalidPostgresDdl().check(P, source) == []


@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        (Path("schema.sql"), ""),
        (Path("tests/migrations/001.sql"), ""),
        (Path("fixtures/migrations/001.sql"), ""),
        (Path("sqlite/migrations/001.sql"), ""),
        (Path("migrations/001.generated.sql"), ""),
        (P, "-- dialect: sqlite\n"),
        (P, "-- dialect: mysql\n"),
        (P, "-- @generated\n"),
        (P, "-- PostgreSQL database dump\n"),
        (P, "--> statement-breakpoint\n"),
    ],
)
def test_non_authored_or_other_dialects_are_excluded(path: Path, prefix: str) -> None:
    assert InvalidPostgresDdl().check(path, prefix + "CREATE INDEX app.item_key ON item(id);") == []


def test_exact_suppression_through_public_analyzer(tmp_path: Path) -> None:
    target = tmp_path / "001.sql"
    source = "CREATE INDEX app.item_key ON item(id);"
    target.write_text(source)
    assert len(analyze([InvalidPostgresDdl.id], [target])) == 1
    target.write_text(f"{source} -- sarj-noqa: SARJ126 -- fixture targets a compatible database fork\n")
    assert analyze([InvalidPostgresDdl.id], [target]) == []


@pytest.mark.parametrize("method", ["hash", "gin", "brin", '"hash"'])
def test_known_builtin_methods_cannot_include_columns(method: str) -> None:
    source = f"CREATE INDEX item_key ON item USING {method} (id) INCLUDE (label);"
    findings = InvalidPostgresDdl().check(P, source)
    assert len(findings) == 1
    assert "does not support INCLUDE" in findings[0].message
    assert findings[0].severity is DefaultLevel.WARNING


@pytest.mark.parametrize("method", ["btree", "gist", "spgist", "custom_method", '"HASH"'])
def test_supported_or_unknown_methods_can_include_columns(method: str) -> None:
    source = f"CREATE INDEX item_key ON item USING {method} (id) INCLUDE (label);"
    assert InvalidPostgresDdl().check(P, source) == []


@pytest.mark.parametrize("included", ["{{ column }}", "label {{ suffix }}", "label {% if extra %}, extra {% endif %}"])
def test_template_include_entries_remain_outside_identifier_validation(included: str) -> None:
    source = f"CREATE INDEX item_key ON item (id) INCLUDE ({included});"
    assert InvalidPostgresDdl().check(P, source) == []


def test_template_include_entry_does_not_hide_a_separate_invalid_expression() -> None:
    source = "CREATE INDEX item_key ON item (id) INCLUDE ({{ column }}, lower(label));"
    findings = InvalidPostgresDdl().check(P, source)
    assert len(findings) == 1
    assert "column names only" in findings[0].message


def test_template_include_entry_preserves_proven_access_method_error() -> None:
    source = "CREATE INDEX item_key ON item USING hash (id) INCLUDE ({{ column }});"
    findings = InvalidPostgresDdl().check(P, source)
    assert len(findings) == 1
    assert "does not support INCLUDE" in findings[0].message
    assert "column names only" not in findings[0].message


@pytest.mark.parametrize(
    "header",
    [
        "COPY item FROM stdin",
        'COPY "app"."item" (id, "label") FROM STDIN',
        "COPY BINARY item FROM STDIN",
        "COPY étoile FROM STDIN",
        "COPY item FROM STDIN WITH (FORMAT csv, DELIMITER '(')",
    ],
)
def test_copy_stdin_payload_and_following_commands_are_outside_analysis(header: str) -> None:
    source = (
        f"{header};\nCREATE UNIQUE INDEX item_key ON item USING hash(id);\n"
        "ALTER TABLE item ADD UNIQUE(id) NOT VALID;\n\\.\n"
        "CREATE UNIQUE INDEX later_key ON item USING hash(id);"
    )
    assert InvalidPostgresDdl().check(P, source) == []


def test_copy_cutoff_preserves_same_line_prefix_and_quoted_semicolons() -> None:
    prefix = 'CREATE UNIQUE INDEX "item;key" ON item USING hash(id); '
    source = prefix + ("COPY item FROM STDIN;\nCREATE UNIQUE INDEX payload_key ON item USING hash(id);\n\\.\n")
    findings = InvalidPostgresDdl().check(P, source)
    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (1, 1)


@pytest.mark.parametrize(
    "prefix",
    [
        "SELECT 'COPY item FROM STDIN;';",
        "-- COPY item FROM STDIN;\n",
        'SELECT "COPY item FROM STDIN;";',
        "DO $$ COPY item FROM STDIN; $$;",
        "COPY item TO STDOUT;",
        "COPY item FROM '/tmp/input.csv';",
        "COPY item FROM PROGRAM 'reader';",
    ],
)
def test_copy_word_and_non_stdin_commands_do_not_hide_later_indexes(prefix: str) -> None:
    source = f"{prefix}\nCREATE UNIQUE INDEX item_key ON item USING hash(id);"
    assert len(InvalidPostgresDdl().check(P, source)) == 1
