"""Performance regression test for rule execution."""

from __future__ import annotations

from pathlib import Path
import time

from sarj_sql_lint.rules import REGISTRY


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


def _best_time_s(rule_id: str, path: Path, source: str, repeats: int = 5) -> float:
    rule = REGISTRY[rule_id]()
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        _ = rule.check(path, source)
        best = min(best, time.perf_counter() - start)
    return best


def test_no_rule_exceeds_absolute_budget() -> None:
    path = Path("synthetic.sql")
    loc = _SYNTHETIC_SQL.count("\n") + 1
    for rule_id in sorted(REGISTRY):
        seconds = _best_time_s(rule_id, path, _SYNTHETIC_SQL)
        ms_per_kloc = seconds / loc * 1_000_000
        assert ms_per_kloc < _ABSOLUTE_MS_PER_KLOC, (
            f"{rule_id}: {ms_per_kloc:.1f} ms/1k LOC exceeds {_ABSOLUTE_MS_PER_KLOC} ms budget"
        )


def test_no_rule_is_algorithmic_outlier() -> None:
    path = Path("synthetic.sql")
    timings = {rid: _best_time_s(rid, path, _SYNTHETIC_SQL) for rid in REGISTRY}
    ordered = sorted(timings.values())
    median = ordered[len(ordered) // 2]
    ceiling = median * _RELATIVE_OUTLIER_FACTOR + _RELATIVE_SLACK_S
    slow = {rid: t for rid, t in timings.items() if t > ceiling}
    assert not slow, (
        "rule(s) more than "
        f"{_RELATIVE_OUTLIER_FACTOR:.0f}x the median ({median * 1000:.2f} ms) — likely an "
        f"algorithmic regression: { {k: f'{v * 1000:.2f}ms' for k, v in slow.items()} }"
    )
