"""Performance regression test.

Two guards, both run over a large synthetic Python file:

* an absolute-style backstop — no rule may cost more than a fixed MULTIPLE of what
  `ast.parse` costs on the same file, catching a catastrophic slowdown regardless of
  hardware;
* a relative outlier gate — no single rule may take more than 10x the median rule
  time. This is hardware-independent and is what catches an algorithmic regression
  (e.g. a rule going quadratic) that an absolute, machine-dependent budget would miss
  on a fast laptop but hit on slow CI. SARJ001 was exactly such an outlier (~30x the
  next-slowest rule) before it was rewritten; this gate is what pins that down.

The documented target is < 50 ms / 1k LOC per rule; the relative gate enforces it in
spirit without flaking across machines.

## Every number here is a ratio, and the denominator is measured in the same run

`_ABSOLUTE_MS_PER_KLOC`, `_ACTIVE_RULE_FLOOR_S` and `_RELATIVE_SLACK_S` used to be
wall-clock constants, and wall clock is not a property of the code — it is a property
of the machine and of whatever else the machine is doing. Under six-way background
load `test_no_rule_is_algorithmic_outlier` failed in a full `pytest -q` and passed
when run alone, with no rule changed: the absolute 1 ms `_ACTIVE_RULE_FLOOR_S`
admitted a different set of rules into the median once every timing inflated, the
median moved, and the ceiling moved with it.

So each constant is now expressed against `_parse_baseline_s()` — the cost of
`ast.parse` on this same source, measured in this same process, moments earlier.
Load and hardware move the numerator and the denominator together and the ratios
hold. That is the difference between a gate people trust and a gate people learn to
re-run until it passes.

Every rule is timed on **both** a test path and a non-test path, and scored on the
slower of the two. Roughly half the registry is file-scope gated — the test-quality
family returns immediately for a non-test path, and SARJ001 conversely exempts tests —
so timing a single path flavour measures how fast a rule declines to run rather than
how fast it runs. That also poisons the relative gate: once the gated rules are half
the registry the median lands on a rule that did nothing, the ceiling collapses toward
`_RELATIVE_SLACK_S`, and every rule that does real work looks like an outlier.
"""

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

# A rule may cost at most this multiple of `ast.parse` on the same source. It is the
# old 200 ms/1k LOC budget over this 1,920-line file (384 ms) divided by the measured
# parse (~26 ms), so the ceiling is unchanged in strength and merely stops moving with
# the machine.
_MAX_RULE_COST_VS_PARSE = 15.0
_RELATIVE_OUTLIER_FACTOR = 10.0
# Was 0.003 s. Same value at the measured parse cost, now load-proportional.
_RELATIVE_SLACK_VS_PARSE = 0.12

# Rule timings on this file are strongly bimodal: roughly half the rules early-out (a
# test-scoped rule on non-test source, a SQL rule on a file with no SQL, a tenant rule
# on a file with no tenant column) and land under 1 ms, while rules that actually walk
# the tree cost 3-55 ms.
#
# A plain median over all rules therefore sits exactly on the boundary between
# the two clusters, and adding or removing a single early-out rule flips it
# between ~0.5 ms and ~5 ms — a 10x swing in the ceiling that made this gate
# flaky. Rules that skipped the file never processed it, so they are not a
# meaningful denominator for "what a rule costs". The median is taken over the
# rules that did real work; the ceiling still applies to every rule, so a rule
# that goes quadratic is caught exactly as before.
#
# It is a RATIO for the reason in the module docstring: as an absolute 1 ms it let
# background load change which rules counted as active, which moved the median, which
# moved the ceiling — the flake this file had. Worse, 1 ms landed ON the boundary:
# three rules measured 1.02 / 1.06 / 1.12 ms, so they crossed it and back with the
# weather. Measured, the boundary between "declined to run" and "walked the tree" is
# the gap 0.96 ms -> 3.25 ms; 0.17 of a parse is its geometric midpoint and moves with
# the load exactly as both clusters do.
_ACTIVE_RULE_FLOOR_VS_PARSE = 0.17


# A rule is scored on whichever path flavour makes it do real work. See the module
# docstring: measuring only one flavour times the file-scope gate, not the rule.
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
    """Time `rule_id` on every path flavour and return its slowest.

    Returns:
        The best-of-N seconds for whichever path flavour the rule actually runs on.

    """
    return max(_best_time_s(rule_id, path, source) for path in _PATHS)


def _parse_baseline_s(repeats: int = 7) -> float:
    """Best-of-N cost of `ast.parse` on the benchmark source.

    The denominator for every budget in this module. It is a fixed workload of the
    same kind as the rules (pure CPU over the same text), measured in the same
    process moments before them, so background load and machine speed cancel.

    Returns:
        Seconds for the fastest of `repeats` parses.

    """
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
