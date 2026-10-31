from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.autofix import fix_source


if TYPE_CHECKING:
    from sqlglot import exp


_PATH = Path("migrations/001.sql")
_RULE = "idempotent-ddl"


@pytest.fixture
def validated_sql(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    validated: list[str] = []

    def parse(text: str) -> list[exp.Expr | None]:
        validated.append(text)
        return parse_postgres(text)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe actual validation dispatch; injecting a parser would bypass it.
        "sarj_sql_lint.autofix.parse_postgres", parse
    )
    return validated


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("SELECT 1;\n", id="clean"),
        pytest.param("", id="empty"),
        pytest.param("CREATE TABLE users (id INT;\n", id="malformed"),
        pytest.param("CREATE TABLE users (id INT); -- sarj-noqa: SARJ102\n", id="suppressed"),
    ],
)
def test_unchanged_sql_is_validated_once(source: str, validated_sql: list[str]) -> None:
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source
    assert validated_sql == [source]


def test_edited_sql_still_validates_the_original_and_replacement(validated_sql: list[str]) -> None:
    source = "CREATE TABLE users (id INT);\n"
    expected = "CREATE TABLE IF NOT EXISTS users (id INT);\n"
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == expected
    assert validated_sql == [source, expected]


def test_unknown_rule_still_fails_before_no_edit_validation(validated_sql: list[str]) -> None:
    with pytest.raises(ValueError, match="unknown SQL rules: missing-rule"):
        fix_source(_PATH, "SELECT 1;\n", rule_ids=["missing-rule"])
    assert validated_sql == []
