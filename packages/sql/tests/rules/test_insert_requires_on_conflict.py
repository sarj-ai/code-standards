from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.insert_requires_on_conflict import InsertRequiresOnConflict


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return InsertRequiresOnConflict().check(Path("migration.sql"), source)


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


# --------------------------------------------------------------------------- #
# Cross-package parity with SARJ018 and the TS twin                            #
# (`packages/python/.../store_insert_requires_on_conflict.py`,                 #
#  `packages/typescript/src/rules/store-insert-requires-on-conflict.ts`).      #
# All three must share ONE definition of "already idempotent" and ONE          #
# definition of a real insert write. If one of these fails, the three          #
# implementations have drifted again — fix the drift, not the test.            #
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Dollar-quoted seed blocks. `mask_sql` keeps `DO $$ ... $$` bodies visible,    #
# which is what lets the rule see the DML inside them. A block that guards its  #
# own replay procedurally is exempt; an UNGUARDED one is still the defect this  #
# rule exists to catch, so the exemption must not be a blanket one.             #
# --------------------------------------------------------------------------- #

_GUARDED_SEED = """
DO $$
DECLARE
    raw_key TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM banks WHERE code = 'ajb') THEN
        RETURN;
    END IF;

    INSERT INTO banks (name, code, api_key)
    VALUES ('Aljazira Bank', 'ajb', raw_key);
END $$;
"""

_UNGUARDED_SEED = """
DO $$
BEGIN
    INSERT INTO banks (name, code)
    VALUES ('Aljazira Bank', 'ajb');
END $$;
"""


def test_guarded_dollar_quoted_seed_block_is_exempt():
    """A block that guards its own replay needs no ON CONFLICT.

    Evidence: `noura-be/digital-bank/banking-be/migrations/028_seed_ajb_bank.sql:21`
    and `022_seed_banks.sql:34` (the `CONTINUE` variant inside a `FOREACH` loop).
    An `ON CONFLICT` clause there would be dead code.
    """
    assert _check(_GUARDED_SEED) == []


def test_unguarded_dollar_quoted_insert_still_fires():
    """The exemption is for blocks that guard their own replay, not for `DO` blocks."""
    diags = _check(_UNGUARDED_SEED)
    assert len(diags) == 1
    assert "idempotent upserts" in diags[0].message


def test_guard_in_one_block_does_not_excuse_another_block():
    """Contiguous-run grouping is per body, so one guarded block cannot cover a sibling."""
    diags = _check(_GUARDED_SEED + "\n" + _UNGUARDED_SEED)
    assert len(diags) == 1


def test_commented_out_guard_does_not_excuse_the_block():
    """The guard is read from masked text, so a `--`'d guard does not count."""
    src = """
DO $$
BEGIN
    -- IF EXISTS (SELECT 1 FROM banks WHERE code = 'ajb') THEN RETURN; END IF;
    INSERT INTO banks (name, code) VALUES ('Aljazira Bank', 'ajb');
END $$;
"""
    assert len(_check(src)) == 1


def test_bare_insert_outside_any_dollar_body_still_fires():
    src = _GUARDED_SEED + "\nINSERT INTO plan (name) VALUES ('free');"
    diags = _check(src)
    assert len(diags) == 1
