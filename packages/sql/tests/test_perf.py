from __future__ import annotations

from pathlib import Path
import time
from typing import NamedTuple

import pytest
from sarj_rule_contracts import RuleId

from sarj_sql_lint.rules import REGISTRY
from sarj_sql_lint.rules.no_analytical_queries_in_transactional_db import NoAnalyticalQueriesInTransactionalDb
from sarj_sql_lint.rules.no_null_comparison import NoNullComparison


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


class _RuleTiming(NamedTuple):
    wall_s: float
    cpu_s: float


def _best_timing(rule_id: RuleId, path: Path, source: str, repeats: int = 5) -> _RuleTiming:
    rule = REGISTRY[rule_id]()
    best_wall = float("inf")
    best_cpu = float("inf")
    for _ in range(repeats):
        wall_start = time.perf_counter()
        cpu_start = time.thread_time()
        rule.check(path, source)
        cpu_s = time.thread_time() - cpu_start
        wall_s = time.perf_counter() - wall_start
        best_wall = min(best_wall, wall_s)
        best_cpu = min(best_cpu, cpu_s)
    # Both minima come from the same calls. Wall time caps latency; thread CPU
    # compares synchronous rule work without shared-VM scheduling delays.
    return _RuleTiming(best_wall, best_cpu)


@pytest.fixture(scope="module")
def rule_timings() -> dict[str, _RuleTiming]:
    # Both gates inspect the same five-repeat measurements; neither needs a second run.
    path = Path("synthetic.sql")
    return {rid: _best_timing(RuleId(rid), path, _SYNTHETIC_SQL) for rid in sorted(REGISTRY)}


@pytest.fixture(scope="module")
def cold_rule_timings() -> dict[str, _RuleTiming]:
    # Give every rule a fresh input so scanner caches cannot supply another
    # rule's baseline. Fresh-scan controls compare to this cold cohort.
    return {
        rid: _best_timing(
            RuleId(rid),
            Path("synthetic.sql"),
            _SYNTHETIC_SQL.replace("orders_", f"cold_{index}_orders_"),
            repeats=1,
        )
        for index, rid in enumerate(sorted(REGISTRY))
    }


def test_no_rule_exceeds_absolute_budget(rule_timings: dict[str, _RuleTiming]) -> None:
    loc = _SYNTHETIC_SQL.count("\n") + 1
    for rule_id, timing in rule_timings.items():
        ms_per_kloc = timing.wall_s / loc * 1_000_000
        assert ms_per_kloc < _ABSOLUTE_MS_PER_KLOC, (
            f"{rule_id}: {ms_per_kloc:.1f} ms/1k LOC exceeds {_ABSOLUTE_MS_PER_KLOC} ms budget"
        )


def test_no_rule_is_algorithmic_outlier(rule_timings: dict[str, _RuleTiming]) -> None:
    ordered = sorted(timing.cpu_s for timing in rule_timings.values())
    median = ordered[len(ordered) // 2]
    ceiling = median * _RELATIVE_OUTLIER_FACTOR + _RELATIVE_SLACK_S
    slow = {rid: timing.cpu_s for rid, timing in rule_timings.items() if timing.cpu_s > ceiling}
    assert not slow, (
        "rule(s) more than "
        f"{_RELATIVE_OUTLIER_FACTOR:.0f}x the CPU median ({median * 1000:.2f} ms) — likely an "
        f"algorithmic regression: { {k: f'{v * 1000:.2f}ms' for k, v in slow.items()} }"
    )


def test_analytical_policy_meets_existing_budgets_on_fresh_plain_sql(cold_rule_timings: dict[str, _RuleTiming]) -> None:
    source = _SYNTHETIC_SQL.replace("orders_", "cold_orders_")
    timing = _best_timing(RuleId(NoAnalyticalQueriesInTransactionalDb.id), Path("fresh.sql"), source, repeats=1)
    ordered = sorted(timing.cpu_s for timing in cold_rule_timings.values())
    ceiling = ordered[len(ordered) // 2] * _RELATIVE_OUTLIER_FACTOR + _RELATIVE_SLACK_S
    assert timing.cpu_s < ceiling
    assert timing.wall_s / (source.count("\n") + 1) * 1_000_000 < _ABSOLUTE_MS_PER_KLOC


def test_null_comparison_meets_existing_budgets_on_fresh_migration_sql(
    cold_rule_timings: dict[str, _RuleTiming],
) -> None:
    source = "\n".join(
        (
            _SYNTHETIC_SQL.replace("orders_", "null_gate_orders_"),
            "SELECT id FROM null_gate_orders_0 WHERE note = NULL;",
        )
    )
    path = Path("fresh_null.sql")
    timing = _best_timing(RuleId(NoNullComparison.id), path, source, repeats=1)
    ordered = sorted(timing.cpu_s for timing in cold_rule_timings.values())
    ceiling = ordered[len(ordered) // 2] * _RELATIVE_OUTLIER_FACTOR + _RELATIVE_SLACK_S
    assert timing.cpu_s < ceiling
    assert timing.wall_s / (source.count("\n") + 1) * 1_000_000 < _ABSOLUTE_MS_PER_KLOC
    assert len(NoNullComparison().check(path, source)) == 1
