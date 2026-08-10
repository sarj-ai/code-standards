from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.insert_requires_on_conflict import InsertRequiresOnConflict


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


P = Path("supabase/migrations/001_seed.sql")


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return InsertRequiresOnConflict().check(path, source)


_PUBLIC_EXAMPLES = InsertRequiresOnConflict.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(InsertRequiresOnConflict().check(Path(focus.path), focus.source)) == example.expected_count


def test_flags_bare_insert():
    src = "INSERT INTO plan (name) VALUES ('free');"
    diags = _check(src)
    assert len(diags) == 1
    assert "ON CONFLICT" in diags[0].message


def test_allows_insert_with_on_conflict_same_line():
    src = "INSERT INTO plan (name) VALUES ('free') ON CONFLICT (name) DO NOTHING;"
    assert _check(src) == []


def test_allows_multiline_insert_with_on_conflict_later_in_statement():
    src = """
INSERT INTO plan (name, price)
VALUES
    ('free', 0),
    ('pro', 99)
ON CONFLICT (name)
DO UPDATE SET price = EXCLUDED.price;
"""
    assert _check(src) == []


def test_flags_multiline_insert_without_on_conflict():
    src = """
INSERT INTO plan (name, price)
VALUES
    ('free', 0),
    ('pro', 99);
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2


def test_on_conflict_in_next_statement_does_not_excuse_previous():
    src = """
INSERT INTO plan (name) VALUES ('free');
INSERT INTO plan (name) VALUES ('pro') ON CONFLICT (name) DO NOTHING;
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2


def test_flags_each_bare_insert_statement():
    src = """
INSERT INTO plan (name) VALUES ('free');
INSERT INTO plan (name) VALUES ('pro');
"""
    assert len(_check(src)) == 2


def test_on_conflict_in_trailing_comment_does_not_count():
    src = "INSERT INTO plan (name) VALUES ('free'); -- TODO add ON CONFLICT"
    assert len(_check(src)) == 1


def test_on_conflict_inside_string_does_not_excuse_insert():
    source = "INSERT INTO plan(name) VALUES ('ON CONFLICT');"
    assert len(_check(source)) == 1


def test_insert_select_guarded_against_its_target_is_idempotent() -> None:
    source = """
    INSERT INTO plan (name)
    SELECT source.name FROM source
    WHERE NOT EXISTS (SELECT 1 FROM plan WHERE plan.name = source.name);
    """
    assert _check(source) == []


def test_insert_select_guarded_against_an_unrelated_table_still_fires() -> None:
    source = """
    INSERT INTO plan (name)
    SELECT source.name FROM source
    WHERE NOT EXISTS (SELECT 1 FROM audit WHERE audit.name = source.name);
    """
    assert len(_check(source)) == 1


def test_commented_not_exists_guard_does_not_excuse_insert_select() -> None:
    source = """
    INSERT INTO plan (name)
    SELECT source.name FROM source
    -- WHERE NOT EXISTS (SELECT 1 FROM plan WHERE plan.name = source.name)
    ;
    """
    assert len(_check(source)) == 1


def test_semicolon_inside_string_does_not_mis_split():
    src = "INSERT INTO plan (name) VALUES ('a;b') ON CONFLICT (name) DO NOTHING;"
    assert _check(src) == []


def test_semicolon_inside_string_keeps_single_violation():
    src = "INSERT INTO plan (name) VALUES ('a;b');"
    assert len(_check(src)) == 1


def test_skips_pure_comment_lines():
    src = """
-- INSERT INTO plan must always be an upsert;
/* not a real statement */
"""
    assert _check(src) == []


def test_is_case_insensitive():
    src = """
insert into plan (name)
values ('free')
on conflict (name) do nothing;
"""
    assert _check(src) == []


def test_statement_without_trailing_semicolon_is_still_checked():
    src = "INSERT INTO plan (name) VALUES ('free')"
    assert len(_check(src)) == 1


# These fixtures keep this rule aligned with Python SARJ018 and its TypeScript twin.

ALREADY_IDEMPOTENT = {
    "postgres_on_conflict": "INSERT INTO t (a) VALUES (1) ON CONFLICT (a) DO NOTHING;",
    "mysql_on_duplicate_key": ("INSERT INTO t (a, b) VALUES (1, 2) ON DUPLICATE KEY UPDATE b = VALUES(b);"),
    "sqlite_insert_or_ignore": "INSERT OR IGNORE INTO t (a) VALUES (1);",
    "sqlite_insert_or_replace": "INSERT OR REPLACE INTO t (a) VALUES (1);",
}


@pytest.mark.parametrize("source", ALREADY_IDEMPOTENT.values(), ids=list(ALREADY_IDEMPOTENT))
def test_every_idempotent_insert_form_is_excused(source: str):
    assert _check(source) == []


def test_insert_or_abort_is_not_excused():
    """`OR IGNORE`/`OR REPLACE` survive replay; `OR ABORT` does not."""
    assert len(_check("INSERT OR ABORT INTO t (a) VALUES (1);")) == 1


WRITE_VERB_REQUIRED = {
    "grant_insert": "GRANT INSERT ON TABLE t TO app_role;",
    "insert_without_write_verb": "INSERT INTO t;",
}


@pytest.mark.parametrize("source", WRITE_VERB_REQUIRED.values(), ids=list(WRITE_VERB_REQUIRED))
def test_insert_keyword_without_a_write_verb_does_not_fire(source: str):
    """A bare `INSERT INTO` used to be enough here — the loosest of the three."""
    assert _check(source) == []


_GUARDED_SEED = """
DO $$
DECLARE
    raw_key TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM partner WHERE code = 'exp') THEN
        RETURN;
    END IF;

    INSERT INTO partner (name, code, api_key)
    VALUES ('Example Partner', 'exp', raw_key);
END $$;
"""

_UNGUARDED_SEED = """
DO $$
BEGIN
    INSERT INTO partner (name, code)
    VALUES ('Example Partner', 'exp');
END $$;
"""


def test_guarded_dollar_quoted_seed_block_is_exempt():
    assert _check(_GUARDED_SEED) == []


def test_unguarded_dollar_quoted_insert_still_fires():
    """The exemption is for blocks that guard their own replay, not for `DO` blocks."""
    diags = _check(_UNGUARDED_SEED)
    assert len(diags) == 1
    assert "idempotent upserts" in diags[0].message


def test_guard_in_one_block_does_not_excuse_another_block():
    """Contiguous-run grouping is per body, so one guarded block cannot cover a sibling."""
    diags = _check(f"{_GUARDED_SEED}\n{_UNGUARDED_SEED}")
    assert len(diags) == 1


def test_commented_out_guard_does_not_excuse_the_block():
    """The guard is read from masked text, so a `--`'d guard does not count."""
    src = """
DO $$
BEGIN
    -- IF EXISTS (SELECT 1 FROM partner WHERE code = 'exp') THEN RETURN; END IF;
    INSERT INTO partner (name, code) VALUES ('Example Partner', 'exp');
END $$;
"""
    assert len(_check(src)) == 1


def test_bare_insert_outside_any_dollar_body_still_fires():
    src = f"{_GUARDED_SEED}\nINSERT INTO plan (name) VALUES ('free');"
    diags = _check(src)
    assert len(diags) == 1


@pytest.mark.parametrize(
    "path",
    [
        Path("queries/create_plan.sql"),
        Path("testdata/insert_plan.sql"),
        Path("fixtures/migrations/001_seed.sql"),
        Path("mocks/migrations/001_seed.sql"),
        Path("snapshots/migrations/001_seed.sql"),
    ],
    ids=["query", "testdata", "fixture", "mock", "snapshot"],
)
def test_non_migration_and_non_production_sql_are_out_of_scope(path: Path) -> None:
    assert _check("INSERT INTO plan (name) VALUES ('free');", path) == []


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (Path("clickhouse/migrations/001.sql"), "-- migrate:up\nINSERT INTO plan (name) VALUES ('free');"),
        (Path("d1/migrations/001.sql"), "INSERT INTO plan (name) VALUES ('free');"),
        (Path("migrations/001.sql"), "-- dialect: sqlite\nINSERT INTO plan (name) VALUES ('free');"),
        (Path("migrations/001.sql"), "-- dialect: mysql\nINSERT INTO plan (name) VALUES ('free');"),
        (Path("migrations/001.sql"), "INSERT INTO plan (name) VALUES ('free');"),
    ],
)
def test_ambiguous_or_non_postgres_migrations_are_out_of_scope(path: Path, source: str) -> None:
    assert _check(source, path) == []


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (Path("stdin"), "-- migrate:up\nINSERT INTO plan (name) VALUES ('free');"),
        (Path("db/migrations/001.sql"), "-- dialect: postgresql\nINSERT INTO plan (name) VALUES ('free');"),
        (Path("db/migrations/001.sql"), "CREATE TABLE events (id UUID); INSERT INTO plan (name) VALUES ('free');"),
    ],
)
def test_positive_migration_and_postgres_evidence_preserves_detection(path: Path, source: str) -> None:
    assert len(_check(source, path)) == 1
