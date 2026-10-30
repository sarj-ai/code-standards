from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rule_base import DefaultLevel
from sarj_sql_lint.rules.declared_column_bounds import DeclaredColumnBounds


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


_PATH = Path("supabase/migrations/001_retry.sql")


def _check(source: str, path: Path = _PATH) -> list[Diagnostic]:
    return DeclaredColumnBounds().check(path, source)


@pytest.mark.parametrize(
    "example",
    DeclaredColumnBounds.public_examples(),
    ids=tuple(item.example_id for item in DeclaredColumnBounds.public_examples()),
)
def test_documented_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, Path(example.focus_file.path))) == example.expected_count


def test_reports_declared_retry_count_and_interval_ranges_with_correct_locations() -> None:
    source = """-- migrate:up
CREATE TABLE retry (
  max_retries INTEGER NOT NULL, -- required; capped 1..10
  wait_between INTERVAL NOT NULL, -- required; 60s..30d
  signed_balance NUMERIC,
  expire_after INTERVAL
);
"""
    findings = _check(source)
    assert [(item.line, item.col) for item in findings] == [(3, 3), (4, 3)]
    assert all(item.code == "SARJ130" and item.severity is DefaultLevel.WARNING for item in findings)


@pytest.mark.parametrize(
    "check",
    [
        "n BETWEEN 1 AND 10",
        "n >= 1 AND n <= 10",
        "n > 0 AND n < 11",
        "1 <= n AND 10 >= n",
        "n BETWEEN 2 AND 9",
        "n >= 1 AND n <= 10 AND other IS NOT NULL",
    ],
)
def test_equivalent_or_stricter_literal_checks_satisfy_range(check: str) -> None:
    assert _check(f"CREATE TABLE t (\n n INTEGER, -- range: 1..10\n other TEXT, CHECK ({check}));") == []


@pytest.mark.parametrize("check", ["n >= 0 AND n <= 10", "n >= 1", "n <= 10", "other >= 1 AND other <= 10"])
def test_missing_or_weak_endpoints_are_reported(check: str) -> None:
    assert len(_check(f"CREATE TABLE t (\n n INTEGER, -- capped 1..10\n other INTEGER, CHECK ({check}));")) == 1


@pytest.mark.parametrize(
    "check",
    [
        "n BETWEEN INTERVAL '1 minute' AND INTERVAL '30 days'",
        "n >= '60 seconds'::interval AND n <= INTERVAL '720 hours'",
    ],
)
def test_interval_literals_preserve_units(check: str) -> None:
    assert _check(f"CREATE TABLE t (\n n INTERVAL, -- required; 60s..30d\n CHECK ({check}));") == []


@pytest.mark.parametrize(
    ("kind", "comment"), [("INTEGER", "must be positive"), ("NUMERIC", "non-negative"), ("INTERVAL", "positive")]
)
def test_explicit_positivity_requires_a_check(kind: str, comment: str) -> None:
    assert len(_check(f"CREATE TABLE t (n {kind} -- {comment}\n);")) == 1


@pytest.mark.parametrize("check", ["n > 0", "n >= 1"])
def test_positive_integer_checks_are_equivalent(check: str) -> None:
    assert _check(f"CREATE TABLE t (n INTEGER -- must be positive\n, CHECK ({check}));") == []


def test_decimal_bounds_do_not_use_integer_rounding() -> None:
    assert len(_check("CREATE TABLE t (n NUMERIC -- range 1..10\n, CHECK (n > 0 AND n < 11));")) == 1


@pytest.mark.parametrize(
    "check",
    [
        "n >= minimum AND n <= maximum",
        "valid_range(n)",
        "n::integer BETWEEN 1 AND 10",
        "n BETWEEN 1 AND 10 OR exempt",
        "n IS NOT NULL",
    ],
)
def test_unknown_constraints_cause_abstention_instead_of_false_claims(check: str) -> None:
    assert _check(f"CREATE TABLE t (n INTEGER -- range: 1..10\n, CHECK ({check}));") == []


@pytest.mark.parametrize(
    ("kind", "comment"),
    [
        ("INTEGER", "version 1..10"),
        ("TEXT", "range 1..10"),
        ("INTERVAL", "range 1..10"),
        ("INTEGER", "range 10..1"),
        ("INTERVAL", "1month..1year"),
        ("INTEGER", "required"),
    ],
)
def test_ambiguous_or_invalid_declarations_are_not_guessed(kind: str, comment: str) -> None:
    assert _check(f"CREATE TABLE t (max_retries {kind} -- {comment}\n);") == []


@pytest.mark.parametrize(
    ("kind", "comment"),
    [("INTERVAL", "1\u017f..10\u017f"), ("INTEGER", "mu\u017ft be positive"), ("INTEGER", "range \u0661..\u0669")],
)
def test_non_ascii_units_keywords_and_digits_are_not_declarations(kind: str, comment: str) -> None:
    assert _check(f"CREATE TABLE t (n {kind} -- {comment}\n);") == []


def test_names_defaults_and_nullability_alone_never_imply_positive_bounds() -> None:
    assert (
        _check(
            "CREATE TABLE t (count INTEGER NOT NULL DEFAULT 1, duration INTERVAL NOT NULL DEFAULT INTERVAL '1 hour');"
        )
        == []
    )


@pytest.mark.parametrize(
    "comment",
    [
        "must be positive when enabled",
        "previous valid range 1..10; now any signed integer",
        "not a valid range 1..10",
        "range 1..10 unless exempt",
    ],
)
def test_conditional_historical_and_negated_comments_do_not_declare_a_bound(comment: str) -> None:
    assert _check(f"CREATE TABLE t (n INTEGER -- {comment}\n, enabled BOOLEAN);") == []


def test_positive_qualifier_does_not_become_an_unconditional_bound() -> None:
    source = (
        "CREATE TABLE t (n INTEGER -- must be positive for enabled rows\n,"
        " enabled BOOLEAN NOT NULL CHECK (enabled = false));"
    )
    assert _check(source) == []


def test_historical_range_does_not_replace_a_correct_current_check() -> None:
    source = "CREATE TABLE t (n INTEGER CHECK (n BETWEEN 20 AND 100) -- once capped 1..10; current range 20..100\n);"
    assert _check(source) == []


def test_qualifying_prose_on_a_separate_comment_line_is_not_discarded() -> None:
    source = "CREATE TABLE t (n INTEGER -- must be positive\n -- for enabled rows\n, enabled BOOLEAN);"
    assert _check(source) == []


@pytest.mark.parametrize(
    "comment", ["capped 1..10 for legacy clients", "positive pending review", "range 1..10; additional qualification"]
)
def test_unrecognized_qualifying_prose_is_not_interpreted(comment: str) -> None:
    assert _check(f"CREATE TABLE t (n INTEGER -- {comment}\n);") == []


@pytest.mark.parametrize(
    "comment", ["required; capped 1..10", "optional; range: 1..10", "positive; required", "must be non-negative."]
)
def test_standalone_declarations_allow_explicit_nullability_clauses(comment: str) -> None:
    assert len(_check(f"CREATE TABLE t (n INTEGER -- {comment}\n);")) == 1


@pytest.mark.parametrize(("kind", "expression"), [("INTEGER", "1"), ("INTERVAL", "INTERVAL '1 second'")])
def test_computed_column_expressions_cause_conservative_abstention(kind: str, expression: str) -> None:
    source = f"CREATE TABLE t (n {kind} GENERATED ALWAYS AS ({expression}) STORED -- must be positive\n);"
    assert _check(source) == []


@pytest.mark.parametrize(
    "definition", ["INTEGER DEFAULT 1", "INTERVAL DEFAULT INTERVAL '1 second'", "INTEGER GENERATED ALWAYS AS IDENTITY"]
)
def test_defaults_and_identity_do_not_enforce_explicit_positive_contract(definition: str) -> None:
    assert len(_check(f"CREATE TABLE t (n {definition}, -- must be positive\n other INTEGER);")) == 1


def test_inherited_constraints_cause_conservative_abstention() -> None:
    source = (
        "CREATE TABLE parent (n INTEGER CHECK (n > 0));"
        "CREATE TABLE child (n INTEGER -- must be positive\n) INHERITS (parent);"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    ("kind", "low", "high"),
    [
        ("SMALLINT", -32768, 32767),
        ("INTEGER", -2147483648, 2147483647),
        ("BIGINT", -9223372036854775808, 9223372036854775807),
    ],
)
def test_native_integer_limits_already_enforce_their_full_range(kind: str, low: int, high: int) -> None:
    assert _check(f"CREATE TABLE t (n {kind} -- valid range {low}..{high}\n);") == []


@pytest.mark.parametrize(
    ("kind", "high"), [("SMALLINT", 32767), ("INTEGER", 2147483647), ("BIGINT", 9223372036854775807)]
)
def test_check_and_native_limits_jointly_cover_the_declared_range(kind: str, high: int) -> None:
    assert _check(f"CREATE TABLE t (n {kind} CHECK (n >= 0) -- valid range 0..{high}\n);") == []


def test_native_limits_do_not_satisfy_a_narrower_application_range() -> None:
    assert len(_check("CREATE TABLE t (n SMALLINT -- capped 1..10\n);")) == 1


def test_tinyint_is_a_user_defined_domain_in_postgres() -> None:
    source = (
        "CREATE DOMAIN tinyint AS SMALLINT CHECK (VALUE BETWEEN -128 AND 127);"
        "CREATE TABLE t (n tinyint -- valid range -128..127\n);"
    )
    assert _check(source) == []


def test_quoted_column_and_block_comment_preserve_identity() -> None:
    assert _check('CREATE TABLE t ("n)name" INTEGER /* capped 1..10 */, CHECK ("n)name" BETWEEN 1 AND 10));') == []


def test_other_column_or_string_comment_cannot_supply_range_evidence() -> None:
    assert _check("CREATE TABLE t (n INTEGER, note TEXT DEFAULT '-- range 1..10');") == []


def test_staged_alter_constraints_cause_conservative_abstention() -> None:
    source = (
        "CREATE TABLE t (n INTEGER -- range 1..10\n);"
        "CREATE INDEX t_n ON t(n);"
        "ALTER TABLE t ADD CONSTRAINT n_range CHECK (n BETWEEN 1 AND 10);"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    ["queries/retry.sql", "postgres/tests/migrations/retry.sql", "mysql/migrations/retry.sql", "supabase/schema.sql"],
)
def test_scope_exclusions(path: str) -> None:
    assert _check("CREATE TABLE t (n INTEGER -- capped 1..10\n);", Path(path)) == []


def test_malformed_statement_does_not_hide_a_following_proven_contract() -> None:
    source = "CREATE TABLE broken (; CREATE TABLE t (n INTEGER -- range 1..10\n);"
    assert len(_check(source)) == 1
