from pathlib import Path

import pytest

from sarj_python_lint.rules.unbounded_order_by import UnboundedOrderBy


def _check(source: str):
    return UnboundedOrderBy().check(Path("query_store.py"), source)


@pytest.mark.parametrize(
    "source",
    [
        'q = "SELECT id FROM run ORDER BY created_at"',
        'q = f"SELECT id FROM run WHERE org_id = {org_id} ORDER BY created_at, id"',
        'q = SQL("SELECT id FROM run ORDER BY created_at")',
        'q = "SELECT id FROM run ORDER BY created_at LIMIT 2 BY org_id"',
        'q = "SELECT id FROM run ORDER BY created_at LIMIT 5, 2 BY org_id"',
        'q = "SELECT id FROM run ORDER BY created_at LIMIT ALL"',
        'q = "SELECT id FROM run ORDER BY created_at LIMIT NULL"',
    ],
)
def test_warns_on_uncapped_result_sorts(source: str) -> None:
    (diag,) = _check(source)
    assert diag.code == "SARJ096"
    assert diag.severity.value == "warning"


@pytest.mark.parametrize(
    "source",
    [
        'q = "SELECT id FROM run ORDER BY created_at LIMIT 50"',
        'q = "SELECT id FROM run ORDER BY created_at LIMIT 2 BY org_id LIMIT 50"',
        'q = "SELECT id FROM run ORDER BY id FOR UPDATE"',
        'q = "SELECT array_agg(id ORDER BY created_at) FROM run"',
        'q = "SELECT id FROM run"',
    ],
)
def test_allows_bounded_nested_or_lock_ordering(source: str) -> None:
    assert _check(source) == []
