"""SARJ111 — the CHECK/FK boundary, including a column literally named `check`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sarj_sql_lint.rules.add_constraint_not_valid import AddConstraintNotValid


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


P = Path("migration.sql")


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return AddConstraintNotValid().check(path, source)


def test_check_constraint_without_not_valid_is_reported() -> None:
    diags = _check("ALTER TABLE users ADD CONSTRAINT check_age CHECK (age >= 18);")
    assert len(diags) == 1
    assert diags[0].code == "SARJ111"


def test_not_valid_silences_the_check_constraint() -> None:
    assert _check("ALTER TABLE users ADD CONSTRAINT check_age CHECK (age >= 18) NOT VALID;") == []


def test_unique_constraint_is_not_a_validating_constraint() -> None:
    """The boundary: a UNIQUE column named `check` must not be read as a CHECK clause."""
    assert _check("ALTER TABLE t ADD CONSTRAINT uq UNIQUE (check);") == []
