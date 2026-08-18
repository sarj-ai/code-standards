from __future__ import annotations

import ast
from pathlib import Path
import time

from sarj_python_lint.rules import REGISTRY


_FUNCTION_BLOCK = """\
async def handler_{i}(items: list[int]) -> str:
    acc_{i} = ""
    total_{i} = 0
    for item in items:
        acc_{i} = acc_{i} + str(item)
        row_{i} = await fetch(item)
        total_{i} += 1
        try:
            data_{i} = await row_{i}.json()
            logger.info(f"got {{data_{i}}}")
        except ValueError:
            return None
    while total_{i} > 0:
        total_{i} -= 1
    return acc_{i}
"""

_SYNTHETIC_PY = "\n".join(_FUNCTION_BLOCK.format(i=i) for i in range(120))

# A rule may cost at most this multiple of `ast.parse` on the same source.
_MAX_RULE_COST_VS_PARSE = 15.0
_RELATIVE_OUTLIER_FACTOR = 10.0
# Was 0.003 s.
_RELATIVE_SLACK_VS_PARSE = 0.12

# Rule timings on this file are strongly bimodal: roughly half the rules early-out (a test-scoped rule on non-test source, a SQL rule on a file with no SQL, a tenant rule on a file with no tenant column) and land under 1 ms, while rules that actually walk the tree cost 3-55 ms.
_ACTIVE_RULE_FLOOR_VS_PARSE = 0.17


# A rule is scored on whichever path flavour makes it do real work.
_PATHS = (Path("synthetic.py"), Path("tests/test_synthetic.py"))


def _best_time_s(rule_id: str, path: Path, source: str, repeats: int = 5) -> float:
    rule = REGISTRY[rule_id]()
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        _ = rule.check(path, source)
        best = min(best, time.perf_counter() - start)
    return best


def _worst_path_time_s(rule_id: str, source: str) -> float:
    return max(_best_time_s(rule_id, path, source) for path in _PATHS)


def _parse_baseline_s(repeats: int = 7) -> float:
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        _ = ast.parse(_SYNTHETIC_PY)
        best = min(best, time.perf_counter() - start)
    return best


def test_no_rule_exceeds_absolute_budget() -> None:
    parse_s = _parse_baseline_s()
    assert parse_s > 0, "parse baseline did not register — the timer or the source is wrong"
    for rule_id in sorted(REGISTRY):
        seconds = _worst_path_time_s(rule_id, _SYNTHETIC_PY)
        ratio = seconds / parse_s
        assert ratio < _MAX_RULE_COST_VS_PARSE, (
            f"{rule_id}: {seconds * 1000:.1f} ms is {ratio:.1f}x the {parse_s * 1000:.1f} ms "
            f"cost of parsing the same file, budget {_MAX_RULE_COST_VS_PARSE}x"
        )


def test_no_rule_is_algorithmic_outlier() -> None:
    # Every rule is timed on the path flavour where it does real work (see the
    # module docstring), so the "active" floor below is a canary on the benchmark
    # source rather than a filter on gated rules: with per-path timing there is no
    # rule that legitimately sits at zero, so anything that does means the
    # synthetic module stopped exercising the registry.
    parse_s = _parse_baseline_s()
    floor = parse_s * _ACTIVE_RULE_FLOOR_VS_PARSE
    timings = {rid: _worst_path_time_s(rid, _SYNTHETIC_PY) for rid in REGISTRY}
    active = sorted(t for t in timings.values() if t >= floor)
    assert active, "no rule did measurable work — the benchmark source stopped exercising the rules"
    median = active[len(active) // 2]
    ceiling = median * _RELATIVE_OUTLIER_FACTOR + parse_s * _RELATIVE_SLACK_VS_PARSE
    slow = {rid: t for rid, t in timings.items() if t > ceiling}
    assert not slow, (
        "rule(s) more than "
        f"{_RELATIVE_OUTLIER_FACTOR:.0f}x the median ({median * 1000:.2f} ms) — likely an "
        f"algorithmic regression: { {k: f'{v * 1000:.2f}ms' for k, v in slow.items()} }"
    )
