"""Shared pytest-shape predicates for the assertion-quality rules.

A pytest-benchmark test measures wall-clock time; verifying is not its job, and
every rule that judges a test's assertions needs the same carve-out for it —
SARJ043 (`zero-assertion-test`) because a benchmark asserts nothing, SARJ057
(`no-tautological-expect`) because the idiomatic way to benchmark a *failing*
path is `try: ...; assert False; except Err: assert True` inside the timed
callable. Keeping the predicate in one module is what stops the two copies from
drifting apart.
"""

from __future__ import annotations

import ast

from sarj_python_lint.rules._ast_index import walk


# The pytest-benchmark fixture: the test measures time, it does not verify.
_BENCHMARK = "benchmark"


def uses_benchmark_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether `node` both declares and uses the pytest-benchmark fixture.

    `def test_x(benchmark)` then `benchmark(fn, arg)` or `@benchmark` on a nested
    function. The fixture times the callable; a benchmark that asserted on the
    result would be measuring the assertion. Requiring the name to be *used*, not
    just declared, keeps an unrelated parameter that happens to be called
    `benchmark` from silencing the rule.

    """
    args = node.args
    declared = any(arg.arg == _BENCHMARK for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))
    return declared and any(isinstance(child, ast.Name) and child.id == _BENCHMARK for child in walk(node))


def has_benchmark_marker(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether `node` carries `@pytest.mark.benchmark`, called or bare.

    The marker form is the other half of pytest-benchmark's surface: a test can
    take the fixture, wear the marker, or both.

    """
    return any(_decorator_attr(dec) == _BENCHMARK for dec in node.decorator_list)


def _decorator_attr(dec: ast.expr) -> str | None:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if not isinstance(target, ast.Attribute):
        return None
    # Only `*.mark.<name>`, so a `@benchmark.something` helper is not mistaken
    # for a pytest marker.
    parent = target.value
    if isinstance(parent, ast.Attribute) and parent.attr == "mark":
        return target.attr
    return None
