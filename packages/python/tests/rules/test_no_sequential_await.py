from pathlib import Path

from sarj_python_lint.rules.no_sequential_await import NoSequentialAwait


def _check(source: str) -> list:
    return NoSequentialAwait().check(Path("<test>.py"), source)


def test_flags_sequential_await():
    src = """
async def f(items):
    for x in items:
        result = await call(x)
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ001"


def test_allows_async_for_with_no_await_in_body():
    src = """
async def f(stream):
    async for chunk in stream:
        process(chunk)
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
"""
    assert _check(src) == []


def test_one_diagnostic_per_loop_not_per_await():
    """Multi-await loops emit a single diagnostic to avoid noise."""
    src = """
async def f(items):
    for x in items:
        a = await one(x)
        b = await two(x)
"""
    assert len(_check(src)) == 1


def test_fp_iter_expression():
    src = """
async def f():
    for x in await get_items():
        pass
"""
    assert _check(src) == []


def test_fp_else_block():
    src = """
async def f(items):
    for x in items:
        pass
    else:
        await cleanup()
"""
    assert _check(src) == []


def test_fp_async_for_nested():
    src = """
async def f(items):
    for x in items:
        async for y in stream():
            pass
"""
    assert _check(src) == []


def test_fp_gather_in_loop():
    src = """
async def f(chunks):
    for chunk in chunks:
        await asyncio.gather(*[call(x) for x in chunk])
"""
    assert _check(src) == []


def test_fp_sleep_in_loop():
    src = """
async def f(items):
    for x in items:
        await asyncio.sleep(1)
"""
    assert _check(src) == []


def test_fp_early_exit_break():
    src = """
async def f(items):
    for x in items:
        await call(x)
        if cond:
            break
"""
    assert _check(src) == []


def test_fp_early_exit_return():
    src = """
async def f(items):
    for x in items:
        await call(x)
        if cond:
            return
"""
    assert _check(src) == []
