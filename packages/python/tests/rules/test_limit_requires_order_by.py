from pathlib import Path

import pytest

from sarj_python_lint.rules.limit_requires_order_by import LimitRequiresOrderBy


def _check(source: str, path: str = "query_store.py"):
    return LimitRequiresOrderBy().check(Path(path), source)


@pytest.mark.parametrize(
    "source",
    [
        'q = "SELECT id FROM run LIMIT 10"',
        'q = "SELECT id FROM run LIMIT 1"',
        'q = f"SELECT id FROM run WHERE org_id = {org_id} LIMIT {limit}"',
        'q = SQL("SELECT id FROM run LIMIT %s").format(Identifier("id"))',
        'q = "WITH x AS (SELECT id FROM run ORDER BY id LIMIT 5) SELECT id FROM x LIMIT 2"',
    ],
)
def test_flags_unordered_row_limits(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'q = "SELECT id FROM run ORDER BY created_at, id LIMIT 10"',
        'q = "SELECT id FROM run FETCH FIRST 10 ROWS ONLY ORDER BY id"',
        'q = "SELECT id FROM run"',
        "q = \"SELECT note FROM run WHERE note = 'LIMIT 10'\"",
    ],
)
def test_allows_deterministic_or_single_row_queries(source: str) -> None:
    assert _check(source) == []


def test_feature_local_store_is_in_scope() -> None:
    assert len(_check('q = "SELECT id FROM run LIMIT 10"', "feature/store.py")) == 1


def test_nested_aggregate_does_not_exempt_the_outer_limit() -> None:
    source = 'q = "SELECT id, (SELECT COUNT(*) FROM event) FROM run LIMIT 10"'
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "q = \"SELECT id FROM run WHERE status = 'queued' LIMIT 1\"",
        'q = "SELECT COUNT(*) OVER (), id FROM run LIMIT 10"',
    ],
)
def test_single_row_claims_and_window_aggregates_still_need_order(source: str) -> None:
    assert len(_check(source)) == 1


def test_non_store_and_test_paths_are_out_of_scope() -> None:
    assert _check('q = "SELECT id FROM run LIMIT 1"', "views.py") == []
    assert _check('q = "SELECT id FROM run LIMIT 1"', "tests/store.py") == []


def test_reports_error_with_stable_code() -> None:
    (diag,) = _check('q = "SELECT id FROM run LIMIT 10"')
    assert diag.code == "SARJ095"
    assert diag.severity.value == "warning"
