from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity, is_suppressed
from sarj_python_lint.rules.prefer_one_for_required_row import PreferOneForRequiredRow


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


PATH = Path("app/settings_store.py")


def _check(source: str, path: Path = PATH) -> list[Diagnostic]:
    return PreferOneForRequiredRow().check(path, source)


@pytest.mark.parametrize(
    "example",
    PreferOneForRequiredRow.public_examples(),
    ids=tuple(example.example_id for example in PreferOneForRequiredRow.public_examples()),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, Path(focus.path))) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        "async def save(cursor):\n    row = await cursor.fetchone()\n    assert row is not None\n    return row\n",
        "def save(cursor):\n    row = cursor.fetchone()\n    assert None is not row, 'required'\n    return row\n",
        "async def save(cursor):\n    row: Row = await cursor.fetchone()\n    assert row is not None\n    return row\n",
        "async def save(cursor):\n    async with connection.cursor() as cursor:\n        row = await cursor.fetchone()\n        assert row is not None\n        return row\n",
    ],
)
def test_reports_exact_required_row_assertions(source: str) -> None:
    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.WARNING
    assert "required-row helper" in diagnostics[0].message


def test_remediation_preserves_the_actual_fetch_expression() -> None:
    diagnostic = _check(
        "async def save(db):\n    row = await db.cursor.fetchone()\n    assert row is not None\n    return row\n"
    )[0]

    assert "row = one(await db.cursor.fetchone())" in diagnostic.message


@pytest.mark.parametrize(
    "source",
    [
        "async def find(cursor):\n    row = await cursor.fetchone()\n    return row\n",
        "async def save(cursor):\n    row = await cursor.fetchone()\n    validate(row)\n    assert row is not None\n    return row\n",
        "async def save(cursor):\n    row = await cursor.fetchone()\n    assert row\n    return row\n",
        "async def save(cursor):\n    row = await cursor.fetchone()\n    assert row.id is not None\n    return row\n",
        "async def save(cursor):\n    row = await cursor.fetchone(limit=1)\n    assert row is not None\n    return row\n",
        "async def save(cursor):\n    return one(await cursor.fetchone())\n",
        "async def save(cursor):\n    rows = await cursor.fetchall()\n    assert rows is not None\n    return rows\n",
    ],
)
def test_allows_optional_or_noncanonical_fetches(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        Path("tests/test_settings_store.py"),
        Path("app/settings_service.py"),
        Path("generated/settings_store.py"),
    ],
    ids=("test", "non-store", "generated"),
)
def test_ignores_excluded_paths(path: Path) -> None:
    source = "async def save(cursor):\n    row = await cursor.fetchone()\n    assert row is not None\n    return row\n"

    assert _check(source, path) == []


def test_exact_suppression_applies_on_assignment_line() -> None:
    source = (
        "async def save(cursor):\n"
        "    row = await cursor.fetchone()  # sarj-noqa: SARJ422 — external cursor has no shared helper\n"
        "    assert row is not None\n"
        "    return row\n"
    )

    diagnostic = _check(source)[0]

    assert is_suppressed(source.splitlines(), diagnostic.line, diagnostic.code)


def test_malformed_source_is_ignored() -> None:
    assert _check("async def save(:") == []
