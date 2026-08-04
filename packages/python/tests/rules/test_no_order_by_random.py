from pathlib import Path

import pytest

from sarj_python_lint.rules.no_order_by_random import NoOrderByRandom


def _check(source: str):
    return NoOrderByRandom().check(Path("query_store.py"), source)


@pytest.mark.parametrize(
    "source",
    [
        'q = "SELECT id FROM run ORDER BY RANDOM() LIMIT 1"',
        'q = "SELECT id FROM run ORDER BY rand() LIMIT 1"',
        'q = "SELECT id FROM run ORDER BY org_id, RANDOM() LIMIT 1"',
        'q = f"SELECT id FROM run WHERE org_id = {org_id} ORDER BY RANDOM()"',
    ],
)
def test_warns_on_random_sort(source: str) -> None:
    (diag,) = _check(source)
    assert diag.code == "SARJ097"
    assert diag.severity.value == "warning"


@pytest.mark.parametrize(
    "source",
    [
        'q = "SELECT id FROM run ORDER BY sample_key LIMIT 1"',
        "q = \"SELECT id FROM run WHERE note = 'ORDER BY RANDOM()'\"",
        'q = "SELECT random_value FROM run ORDER BY random_value"',
    ],
)
def test_allows_nonvolatile_sampling(source: str) -> None:
    assert _check(source) == []
