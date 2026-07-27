"""Performance regression test.

Two guards, both run over a large synthetic Python file:

* an absolute backstop — no rule may blow a generous ms/1k-LOC ceiling, catching a
  catastrophic slowdown regardless of hardware;
* a relative outlier gate — no single rule may take more than 10x the median rule
  time. This is hardware-independent and is what catches an algorithmic regression
  (e.g. a rule going quadratic) that an absolute, machine-dependent budget would miss
  on a fast laptop but hit on slow CI. SARJ001 was exactly such an outlier (~30x the
  next-slowest rule) before it was rewritten; this gate is what pins that down.

The documented target is < 50 ms / 1k LOC per rule; the relative gate enforces it in
spirit without flaking across machines.

Every rule is timed on **both** a test path and a non-test path, and scored on the
slower of the two. Roughly half the registry is file-scope gated — the test-quality
family returns immediately for a non-test path, and SARJ001 conversely exempts tests —
so timing a single path flavour measures how fast a rule declines to run rather than
how fast it runs. That also poisons the relative gate: once the gated rules are half
the registry the median lands on a rule that did nothing, the ceiling collapses toward
`_RELATIVE_SLACK_S`, and every rule that does real work looks like an outlier.
"""

from __future__ import annotations

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

_ABSOLUTE_MS_PER_KLOC = 200.0
_RELATIVE_OUTLIER_FACTOR = 10.0
_RELATIVE_SLACK_S = 0.003

# Rule timings on this file are strongly bimodal: roughly half the rules
# early-out (a test-scoped rule on non-test source, a SQL rule on a file with no
# SQL, a tenant rule on a file with no tenant column) and land at ~0.001 ms,
# while rules that actually walk the tree cost 5-60 ms. There is a ~10x gap and
# nothing in between.
#
# A plain median over all rules therefore sits exactly on the boundary between
# the two clusters, and adding or removing a single early-out rule flips it
# between ~0.5 ms and ~5 ms — a 10x swing in the ceiling that made this gate
# flaky. Rules that skipped the file never processed it, so they are not a
# meaningful denominator for "what a rule costs". The median is taken over the
# rules that did real work; the ceiling still applies to every rule, so a rule
# that goes quadratic is caught exactly as before.
_ACTIVE_RULE_FLOOR_S = 0.001


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


def test_no_rule_exceeds_absolute_budget() -> None:
    loc = _SYNTHETIC_PY.count("\n") + 1
    for rule_id in sorted(REGISTRY):
        seconds = _worst_path_time_s(rule_id, _SYNTHETIC_PY)
        ms_per_kloc = seconds / loc * 1_000_000
        assert ms_per_kloc < _ABSOLUTE_MS_PER_KLOC, (
            f"{rule_id}: {ms_per_kloc:.1f} ms/1k LOC exceeds {_ABSOLUTE_MS_PER_KLOC} ms budget"
        )


def test_no_rule_is_algorithmic_outlier() -> None:
    # Every rule is timed on the path flavour where it does real work (see the
    # module docstring), so the "active" floor below is a canary on the benchmark
    # source rather than a filter on gated rules: with per-path timing there is no
    # rule that legitimately sits at zero, so anything that does means the
    # synthetic module stopped exercising the registry.
    timings = {rid: _worst_path_time_s(rid, _SYNTHETIC_PY) for rid in REGISTRY}
    active = sorted(t for t in timings.values() if t >= _ACTIVE_RULE_FLOOR_S)
    assert active, "no rule did measurable work — the benchmark source stopped exercising the rules"
    median = active[len(active) // 2]
    ceiling = median * _RELATIVE_OUTLIER_FACTOR + _RELATIVE_SLACK_S
    slow = {rid: t for rid, t in timings.items() if t > ceiling}
    assert not slow, (
        "rule(s) more than "
        f"{_RELATIVE_OUTLIER_FACTOR:.0f}x the median ({median * 1000:.2f} ms) — likely an "
        f"algorithmic regression: { {k: f'{v * 1000:.2f}ms' for k, v in slow.items()} }"
    )
