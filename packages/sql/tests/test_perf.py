from __future__ import annotations

from pathlib import Path
import time

import pytest
from sarj_rule_contracts import RuleId

from sarj_sql_lint.rules import REGISTRY
from sarj_sql_lint.rules.no_analytical_queries_in_transactional_db import NoAnalyticalQueriesInTransactionalDb


_STATEMENT_BLOCK = """\
-- migration {i}: orders table {i}
CREATE TABLE IF NOT EXISTS orders_{i} (
    id          BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    status      TEXT NOT NULL,
    note        VARCHAR(255),
    payload     JSON,
    created_at  TIMESTAMP NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_orders_{i}_customer ON orders_{i} (customer_id);
INSERT INTO orders_{i} (id, customer_id, status, created_at)
VALUES ({i}, {i}, 'pending', now());
SELECT id, status FROM orders_{i} WHERE customer_id = {i} LIMIT 50 OFFSET {i};
CREATE TYPE status_{i} AS ENUM ('pending', 'active', 'closed');
"""

_SYNTHETIC_SQL = "\n".join(_STATEMENT_BLOCK.format(i=i) for i in range(80))

_ABSOLUTE_MS_PER_KLOC = 200.0
_RELATIVE_OUTLIER_FACTOR = 10.0
_RELATIVE_SLACK_S = 0.003


def _best_time_s(rule_id: RuleId, path: Path, source: str, repeats: int = 5) -> float:
    rule = REGISTRY[rule_id]()
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        rule.check(path, source)
        best = min(best, time.perf_counter() - start)
    return best


@pytest.fixture(scope="module")
def rule_timings() -> dict[str, float]:
    # Both gates inspect the same five-repeat measurements; neither needs a second run.
    path = Path("synthetic.sql")
    return {rid: _best_time_s(RuleId(rid), path, _SYNTHETIC_SQL) for rid in sorted(REGISTRY)}


def test_no_rule_exceeds_absolute_budget(rule_timings: dict[str, float]) -> None:
    loc = _SYNTHETIC_SQL.count("\n") + 1
    for rule_id, seconds in rule_timings.items():
        ms_per_kloc = seconds / loc * 1_000_000
        assert ms_per_kloc < _ABSOLUTE_MS_PER_KLOC, (
            f"{rule_id}: {ms_per_kloc:.1f} ms/1k LOC exceeds {_ABSOLUTE_MS_PER_KLOC} ms budget"
        )


def test_no_rule_is_algorithmic_outlier(rule_timings: dict[str, float]) -> None:
    ordered = sorted(rule_timings.values())
    median = ordered[len(ordered) // 2]
    ceiling = median * _RELATIVE_OUTLIER_FACTOR + _RELATIVE_SLACK_S
    slow = {rid: t for rid, t in rule_timings.items() if t > ceiling}
    assert not slow, (
        "rule(s) more than "
        f"{_RELATIVE_OUTLIER_FACTOR:.0f}x the median ({median * 1000:.2f} ms) — likely an "
        f"algorithmic regression: { {k: f'{v * 1000:.2f}ms' for k, v in slow.items()} }"
    )


def test_analytical_policy_meets_existing_budgets_on_fresh_plain_sql(rule_timings: dict[str, float]) -> None:
    source = _SYNTHETIC_SQL.replace("orders_", "cold_orders_")
    seconds = _best_time_s(RuleId(NoAnalyticalQueriesInTransactionalDb.id), Path("fresh.sql"), source, repeats=1)
    ordered = sorted(rule_timings.values())
    ceiling = ordered[len(ordered) // 2] * _RELATIVE_OUTLIER_FACTOR + _RELATIVE_SLACK_S
    assert seconds < ceiling
    assert seconds / (source.count("\n") + 1) * 1_000_000 < _ABSOLUTE_MS_PER_KLOC
