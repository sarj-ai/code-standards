from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_sequential_await import NoSequentialAwait


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


PROD_PATH = "python/bulbul/bulbul/calls/call_store.py"


def _check(source: str, path: str = PROD_PATH) -> list[Diagnostic]:
    return NoSequentialAwait().check(Path(path), source)


def _wrap(body: str) -> str:
    """Embed a `for`-loop body (indented relative to the loop) under a prod async function.

    Returns:
        The wrapped async-function source.

    """
    indented = "\n".join(f"        {line}" if line else "" for line in body.splitlines())
    return f"async def f(items):\n    for x in items:\n{indented}\n"


_SEQUENTIAL_LOOP = """
async def f(items):
    for x in items:
        result = await call(x)
"""


# --------------------------------------------------------------------------- #
# Test-path exemptions: the rule never fires for test modules.                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "test_call_store.py",
        "call_store_test.py",
        "tests/conftest.py",
        "conftest.py",
        "python/bulbul/tests/stores/seed.py",
        "a/b/test/helper.py",
        "deeply/nested/tests/data/factory.py",
    ],
)
def test_skips_test_paths(path: str):
    assert _check(_SEQUENTIAL_LOOP, path) == []


@pytest.mark.parametrize(
    "path",
    [
        PROD_PATH,
        "src/service.py",
        "a/testing/thing.py",
        "a/contest.py",
        "attestation.py",
    ],
)
def test_still_flags_non_test_paths(path: str):
    assert len(_check(_SEQUENTIAL_LOOP, path)) == 1


def test_conftest_named_directory_is_not_exempt():
    assert len(_check(_SEQUENTIAL_LOOP, "conftest/service.py")) == 1


# --------------------------------------------------------------------------- #
# Positive: straight-line `for` bodies that await a call using the loop var.  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "body",
    [
        "result = await call(x)",
        "await call(x)",
        "await x.save()",
        "await x",
        "r = await call(x, extra)",
        "r = await mod.deep.call(x)",
        "r = await call(transform(x))",
        "r = await call(kw=x)",
        "r = await call(x)\nout.append(r)",
        "a = await one(x)\nb = await two(x)",
        "a = await one(x)\nlog(a)\nb = await two(x)",
        "r: int = await call(x)",
        "r += await call(x)",
        "(y := await call(x))",
    ],
)
def test_flags_straight_line_for_body(body: str):
    assert len(_check(_wrap(body))) == 1


@pytest.mark.parametrize(
    ("target", "iterable", "await_expr"),
    [
        ("x", "items", "await f(x)"),
        ("(a, b)", "pairs", "await f(a)"),
        ("(a, b)", "pairs", "await f(b)"),
        ("i, v", "enumerate(items)", "await f(v)"),
        ("i, v", "enumerate(items)", "await f(i)"),
        ("[a, b]", "pairs", "await f(a)"),
    ],
)
def test_flags_various_targets(target: str, iterable: str, await_expr: str):
    src = f"async def f(items, pairs):\n    for {target} in {iterable}:\n        {await_expr}\n"
    assert len(_check(src)) == 1


def test_flags_sequential_await_code_and_message():
    diags = _check(_SEQUENTIAL_LOOP)
    assert len(diags) == 1
    assert diags[0].code == "SARJ001"
    assert "gather" in diags[0].message


def test_one_diagnostic_per_loop_not_per_await():
    src = """
async def f(items):
    for x in items:
        a = await one(x)
        b = await two(x)
        c = await three(x)
"""
    assert len(_check(src)) == 1


def test_flags_straight_line_multi_statement_body():
    src = """
async def f(items):
    out = []
    for x in items:
        r = await call(x)
        out.append(r)
    return out
"""
    assert len(_check(src)) == 1


def test_data_dependent_awaits_in_flat_body_still_fire():
    """Fire on a flat body awaiting the loop var by structural heuristic.

    The rule fires even when the second await depends on the first (it does not
    inspect data-dependency).
    """
    src = """
async def f(items):
    for x in items:
        a = await one(x)
        b = await two(a)
"""
    assert len(_check(src)) == 1


def test_side_effecting_code_between_awaits_still_fires():
    src = """
async def f(items):
    for x in items:
        a = await one(x)
        record(a)
        b = await two(x)
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Positive: comprehensions / generator expressions.                           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "expr",
    [
        "[await f(x) for x in items]",
        "{await f(x) for x in items}",
        "any(await ok(x) for x in items)",
        "list(await f(x) for x in items)",
        "{await k(x): x for x in items}",
        "{x: await v(x) for x in items}",
        "{await k(x): await v(x) for x in items}",
        "[x for x in items if await ok(x)]",
        "[await tick() for x in items]",
        "[y for x in items for y in await g(x)]",
        "[await f(y) for x in items for y in x]",
    ],
)
def test_flags_comprehension_awaits(expr: str):
    src = f"async def f(items):\n    return {expr}\n"
    assert len(_check(src)) == 1


def test_flags_comprehension_code():
    src = "async def f(items):\n    return [await call(x) for x in items]\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ001"


def test_nested_comprehension_flags_only_inner_owner_of_await():
    """Flag only the inner comprehension that owns the per-element `await`.

    The outer comprehension has no `await` of its own, so a single diagnostic
    (for the inner loop) is emitted.
    """
    src = "async def f(rows):\n    return [[await f(c) for c in r] for r in rows]\n"
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Iterable is evaluated once in the enclosing scope — awaiting it is free.    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "expr",
    [
        "[x for x in await one()]",
        "{x for x in await one()}",
        "list(y for y in await two())",
        "{row.id: row for row in await store.fetch_all()}",
    ],
)
def test_allows_await_in_comprehension_iterable(expr: str):
    src = f"async def f():\n    return {expr}\n"
    assert _check(src) == []


def test_allows_await_in_for_iterable():
    src = """
async def f():
    for trunk in (await client.list_trunks()).rules:
        register(trunk)
"""
    assert _check(src) == []


def test_still_flags_element_await_even_with_awaited_iterable():
    src = """
async def f():
    return [await enrich(x) for x in await fetch()]
"""
    assert len(_check(src)) == 1


def test_still_flags_for_body_when_iter_also_awaits():
    src = """
async def f():
    for x in await fetch():
        await process(x)
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Negative: `for` bodies containing control flow are not the gather map.      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "body",
    [
        "if ready(x):\n    await call(x)",
        "try:\n    await call(x)\nexcept Exception:\n    log(x)",
        "with lock:\n    await call(x)",
        "async with lock:\n    await call(x)",
        "while retry:\n    await call(x)",
        "await call(x)\nif done:\n    return",
        "await call(x)\nreturn",
        "await call(x)\nraise Stop",
        "await call(x)\nbreak",
        "await call(x)\ncontinue",
        "match x:\n    case _:\n        await call(x)",
        "async for y in x:\n    await use(y)",
    ],
)
def test_allows_for_body_with_control_flow(body: str):
    assert _check(_wrap(body)) == []


def test_allows_for_await_not_using_loop_variable():
    src = """
async def f(items):
    for _ in items:
        await tick()
"""
    assert _check(src) == []


def test_allows_for_body_calling_but_not_awaiting_loop_var():
    src = """
async def f(items):
    for x in items:
        use(x)
        await tick()
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Negative: while / async-for / gather / no-await shapes.                     #
# --------------------------------------------------------------------------- #


def test_allows_await_in_while_loop():
    src = """
async def f(q):
    while not q.empty():
        item = await q.get()
"""
    assert _check(src) == []


def test_allows_async_for():
    src = """
async def f(stream):
    async for chunk in stream:
        process(chunk)
"""
    assert _check(src) == []


def test_allows_async_for_with_await_body():
    src = """
async def f(stream):
    async for chunk in stream:
        await process(chunk)
"""
    assert _check(src) == []


def test_allows_gather_pattern():
    src = """
import asyncio

async def f(items):
    await asyncio.gather(*[call(x) for x in items])
"""
    assert _check(src) == []


def test_allows_await_outside_loop():
    src = """
async def f():
    x = await call()
    y = await other()
    return x, y
"""
    assert _check(src) == []


def test_allows_comprehension_without_await():
    src = "async def f(items):\n    return [g(x) for x in items]\n"
    assert _check(src) == []


def test_allows_for_without_await():
    src = """
async def f(items):
    for x in items:
        process(x)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Multiple loops: counts and scope boundaries.                                #
# --------------------------------------------------------------------------- #


def test_flags_each_distinct_loop_once():
    src = """
async def f(rows, cols):
    for r in rows:
        a = await one(r)
    for c in cols:
        b = await two(c)
"""
    assert len(_check(src)) == 2


def test_nested_loops_flag_only_inner():
    src = """
async def f(matrix):
    for row in matrix:
        for cell in row:
            v = await load(cell)
"""
    assert len(_check(src)) == 1


def test_allows_outer_for_whose_body_is_nested_loop_without_await():
    src = """
async def f(groups):
    for g in groups:
        for item in other:
            use(item)
"""
    assert _check(src) == []


def test_allows_for_whose_body_is_nested_awaited_iterable_loop():
    src = """
async def f(groups):
    for g in groups:
        for item in await load(g):
            use(item)
"""
    assert _check(src) == []


def test_does_not_escape_nested_function_boundary():
    src = """
async def outer(items):
    for x in items:
        def inner():
            return helper()

    async def sibling():
        return await call()
"""
    assert _check(src) == []


def test_sibling_async_defs_flagged_independently():
    src = """
async def a(items):
    for x in items:
        await one(x)

async def b(items):
    for x in items:
        await two(x)
"""
    assert len(_check(src)) == 2


def test_inner_async_def_loop_flagged_not_outer():
    src = """
async def outer(items):
    for x in items:
        helper(x)

        async def inner(rows):
            for r in rows:
                await load(r)
"""
    assert len(_check(src)) == 1


def test_await_in_nested_def_not_claimed_by_outer_loop():
    src = """
async def outer(items):
    for x in items:
        async def inner():
            return await call()
        schedule(inner)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Edge cases: empty / whitespace / syntax error / non-async.                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", ["", "   ", "\n\n", "# just a comment\n"])
def test_empty_or_trivial_source(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "async def f(:\n    pass",
        "def f(:\n",
        "for x in\n",
        "async def f(items):\n    for x in items:\n    await call(x)\n",
    ],
)
def test_syntax_error_returns_empty(source: str):
    assert _check(source) == []


def test_sync_code_with_for_loop_not_flagged():
    src = """
def f(items):
    for x in items:
        process(x)
"""
    assert _check(src) == []


def test_module_level_for_without_await():
    src = "for x in items:\n    process(x)\n"
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# try / async-with / async-for around awaits do not fire.                     #
# --------------------------------------------------------------------------- #


def test_try_except_around_awaits_not_flagged():
    src = """
async def f(items):
    for x in items:
        try:
            await call(x)
        except Exception:
            continue
"""
    assert _check(src) == []


def test_async_with_body_not_flagged():
    src = """
async def f(items):
    for x in items:
        async with sem:
            await call(x)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Line / column correctness.                                                  #
# --------------------------------------------------------------------------- #


def test_line_col_for_loop_body_await():
    src = "async def f(items):\n    for x in items:\n        result = await call(x)\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3
    assert diags[0].col == 18


def test_line_col_comprehension_await():
    src = "async def f(items):\n    return [await call(x) for x in items]\n"
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 13


def test_diagnostic_path_preserved():
    diags = _check(_SEQUENTIAL_LOOP)
    assert diags[0].path == Path(PROD_PATH)


# --------------------------------------------------------------------------- #
# Multiple violations are returned sorted by (line, col).                     #
# --------------------------------------------------------------------------- #


def test_multi_violation_sorted_by_line():
    src = """
async def f(rows, cols, keys):
    for r in rows:
        await one(r)
    for c in cols:
        await two(c)
    for k in keys:
        await three(k)
"""
    diags = _check(src)
    assert len(diags) == 3
    assert [d.line for d in diags] == sorted(d.line for d in diags)


def test_multi_violation_all_same_code():
    src = """
async def f(rows, cols):
    for r in rows:
        await one(r)
    return [await two(c) for c in cols]
"""
    diags = _check(src)
    assert len(diags) == 2
    assert {d.code for d in diags} == {"SARJ001"}


# --------------------------------------------------------------------------- #
# Adversarial: constructs not covered above that the rule handles correctly.  #
# --------------------------------------------------------------------------- #


def test_nested_comprehension_in_for_body_flags_only_comprehension():
    """Flag only the comprehension, not the enclosing `for`.

    The inner comprehension's `await` uses its own var (`c`), not the loop var
    (`x`), so the `for` is not the antipattern; only the gatherable comprehension
    fires.
    """
    src = """
async def f(items):
    for x in items:
        ys = [await g(c) for c in x]
"""
    assert len(_check(src)) == 1


def test_starred_unpacking_target_flags():
    src = """
async def f(pairs):
    for a, *rest in pairs:
        await use(rest)
"""
    assert len(_check(src)) == 1


def test_taskgroup_create_task_not_awaited_not_flagged():
    src = """
import asyncio

async def f(items):
    async with asyncio.TaskGroup() as tg:
        for x in items:
            tg.create_task(process(x))
"""
    assert _check(src) == []


def test_for_else_await_counts_loop_once():
    src = """
async def f(items):
    for x in items:
        await use(x)
    else:
        await finish()
"""
    assert len(_check(src)) == 1


def test_assert_with_await_using_loop_var_flags():
    src = """
async def f(items):
    for x in items:
        assert await check(x)
"""
    assert len(_check(src)) == 1


def test_decorated_nested_async_def_await_not_using_loop_var_not_flagged():
    src = """
async def outer(items):
    for x in items:
        @deco
        async def inner():
            return await call()
        register(inner)
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Adversarial: genuine defects (xfail, strict).                               #
# --------------------------------------------------------------------------- #


def test_async_generator_yield_await_should_not_flag():
    src = """
async def f(items):
    for x in items:
        yield await fetch(x)
"""
    assert _check(src) == []


def test_nested_scope_await_using_loop_var_should_not_flag_invariant_await():
    src = """
async def outer(items):
    for x in items:
        async def inner():
            return await call(x)
        await tick()
"""
    assert _check(src) == []


@pytest.mark.xfail(
    strict=True,
    reason="left xfailed: detecting a loop var laundered through a local needs data-flow tracking; a clean fix risks new FPs, so we keep the miss over guessing",
)
def test_loop_var_laundered_through_local_should_flag():
    src = """
async def f(items):
    for x in items:
        key = x.id
        await fetch(key)
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP-hardening (famous-repo sweep): trio/anyio modules have no asyncio.gather. #
# --------------------------------------------------------------------------- #


def test_trio_module_is_exempt():
    # Minimized from trio's docs channel examples: sequential channel sends are
    # the deliberate norm under structured concurrency; gather does not exist.
    src = """
import trio

async def producer(send_channel, names):
    for name in names:
        await send_channel.send(name)
"""
    assert _check(src) == []


def test_anyio_module_is_exempt():
    src = """
from anyio import sleep

async def f(xs):
    for x in xs:
        await handle(x)
"""
    assert _check(src) == []


def test_trio_submodule_import_is_exempt():
    src = """
import trio.lowlevel

async def f(xs):
    for x in xs:
        await handle(x)
"""
    assert _check(src) == []


def test_asyncio_module_still_fires():
    src = """
import asyncio

async def f(xs):
    for x in xs:
        await handle(x)
"""
    assert len(_check(src)) == 1
