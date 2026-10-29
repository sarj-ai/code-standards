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
