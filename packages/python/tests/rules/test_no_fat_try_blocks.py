from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_fat_try_blocks import NoFatTryBlocks


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


THRESHOLD = 3


def _check(source: str, path: str = "<t>.py") -> list[Diagnostic]:
    return NoFatTryBlocks().check(Path(path), source)


def _try_with_n_calls(n: int, *, indent: str = "") -> str:
    body = "\n".join(f"{indent}    v{i} = call{i}()" for i in range(n))
    return f"{indent}try:\n{body}\n{indent}except ValueError:\n{indent}    pass\n"


# ---- Positive: try bodies at/above the throwing-statement threshold fire ----


@pytest.mark.parametrize("n", [4, 5, 6, 10])
def test_fires_when_throwing_statements_exceed_threshold(n: int):
    diags = _check(_try_with_n_calls(n))
    assert len(diags) == 1
    assert diags[0].code == "SARJ007"


def test_message_reports_actual_count_and_max():
    diags = _check(_try_with_n_calls(5))
    assert len(diags) == 1
    msg = diags[0].message
    assert "5 statements that can raise" in msg
    assert f"max {THRESHOLD}" in msg


@pytest.mark.parametrize(
    "stmt",
    [
        "vN = callN()",
        "callN()",
        "raise ErrN()",
        "assert probeN()",
        "total += addN()",
        'label = f"{fmtN()}"',
        "items = [x for x in genN()]",
        "with mgrN() as h:\n        pass",
    ],
    ids=[
        "assign-call",
        "bare-expr-call",
        "raise-with-call",
        "assert-call",
        "augassign-call",
        "fstring-call",
        "comprehension-call",
        "with-call-ctx",
    ],
)
def test_each_throwing_statement_form_counts_toward_limit(stmt: str):
    body = "\n".join("    " + stmt.replace("N", str(i)) for i in range(4))
    src = f"try:\n{body}\nexcept ValueError:\n    pass\n"
    assert len(_check(src)) == 1


def test_await_statements_count_in_async_function():
    src = """
async def handler():
    try:
        a = await one()
        b = await two()
        c = await three()
        d = await four()
    except ValueError:
        pass
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ007"


def test_async_with_body_counts_and_fires():
    src = """
async def handler():
    try:
        async with a() as p:
            pass
        async with b() as q:
            pass
        async with c() as r:
            pass
        async with d() as s:
            pass
    except ValueError:
        pass
"""
    assert len(_check(src)) == 1


def test_try_star_held_to_same_limit():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except* ValueError:
    pass
"""
    assert len(_check(src)) == 1


# ---- Negative: at/below threshold, or throwing work outside node.body ----


@pytest.mark.parametrize("n", [1, 2, 3])
def test_clean_when_throwing_statements_at_or_below_threshold(n: int):
    assert _check(_try_with_n_calls(n)) == []


def test_try_with_no_throwing_statements_is_clean():
    src = "try:\n    pass\nexcept ValueError:\n    pass\n"
    assert _check(src) == []


def test_single_statement_try_is_clean():
    src = """
try:
    result = risky()
except ValueError:
    result = None
"""
    assert _check(src) == []


def test_pure_assignments_are_free():
    src = """
try:
    self.a = 1
    self.b = self.a
    self.c = 2
    self.d = other
    self.e = 3
except ValueError:
    raise
"""
    assert _check(src) == []


def test_non_throwing_statements_free_around_calls():
    src = """
try:
    a = 1
    b = 2
    c = 3
    d = risky()
except ValueError:
    pass
"""
    assert _check(src) == []


def test_bare_raise_without_call_does_not_count():
    src = """
try:
    raise A
    raise B
    raise C
    raise D
except Exception:
    pass
"""
    assert _check(src) == []


def test_statements_in_multiple_excepts_not_counted():
    src = """
try:
    x = risky()
except ValueError:
    a = one()
    b = two()
    c = three()
    d = four()
except KeyError:
    e = five()
    f = six()
    g = seven()
    h = eight()
"""
    assert _check(src) == []


# ---- Compound statements count as a single top-level statement ----


def test_throwing_if_counts_as_one_statement():
    src = """
try:
    a = load()
    if cond():
        b = build()
        c = extend(b)
        d = persist(c)
        e = log(d)
    f = save()
except ValueError:
    pass
"""
    assert _check(src) == []


def test_throwing_for_loop_counts_as_one_statement():
    src = """
try:
    for i in items():
        a = p(i)
        b = q(i)
        c = r(i)
        d = s(i)
    z = t()
except ValueError:
    pass
"""
    assert _check(src) == []


def test_match_statement_counts_as_one():
    src = """
try:
    a = load()
    match probe():
        case 1:
            b = one()
            c = two()
            d = three()
        case _:
            e = four()
except ValueError:
    pass
"""
    assert _check(src) == []


def test_four_compound_statements_each_count_once_and_fire():
    src = """
try:
    with a() as p:
        pass
    with b() as q:
        pass
    with c() as r:
        pass
    with d() as s:
        pass
except ValueError:
    pass
"""
    assert len(_check(src)) == 1


# ---- else / finally exempt the block regardless of body size ----


def test_else_clause_exempts_fat_block():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except ValueError:
    pass
else:
    use(a, b, c, d)
"""
    assert _check(src) == []


def test_finally_clause_exempts_fat_block():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
finally:
    cleanup()
"""
    assert _check(src) == []


def test_else_and_finally_together_exempt_fat_block():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except ValueError:
    pass
else:
    ok()
finally:
    cleanup()
"""
    assert _check(src) == []


# ---- Re-raising except handlers exempt the block (wrapping, not swallowing) ----


def test_bare_reraise_handler_exempts_fat_block():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except ValueError:
    log()
    raise
"""
    assert _check(src) == []


def test_raise_from_wrapped_handler_exempts_fat_block():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except ValueError as e:
    raise Wrapped("context") from e
"""
    assert _check(src) == []


def test_all_handlers_reraise_across_multiple_excepts_exempts():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except ValueError as e:
    raise Wrapped() from e
except KeyError:
    raise
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "tail",
    ["return None", "pass", "continue", "log_error()"],
    ids=["return", "pass", "continue", "log-no-raise"],
)
def test_swallowing_handler_still_fires(tail: str):
    src = f"""
def outer():
    for _ in items():
        try:
            a = one()
            b = two()
            c = three()
            d = four()
        except ValueError:
            {tail}
"""
    assert len(_check(src)) == 1


def test_mixed_handlers_one_reraises_one_swallows_still_fires():
    src = """
def outer():
    try:
        a = one()
        b = two()
        c = three()
        d = four()
    except ValueError as e:
        raise Wrapped() from e
    except KeyError:
        return None
"""
    assert len(_check(src)) == 1


def test_reraise_not_at_handler_tail_still_fires():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except ValueError:
    if fatal():
        raise
    recovered()
"""
    assert len(_check(src)) == 1


# ---- Nested try blocks are checked independently ----


def test_only_inner_try_fat_flags_inner():
    src = """
try:
    try:
        a = one()
        b = two()
        c = three()
        d = four()
    except KeyError:
        pass
except ValueError:
    pass
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3


def test_both_nested_and_outer_flagged_when_both_fat():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
    try:
        w = five()
        x = six()
        y = seven()
        z = eight()
    except KeyError:
        pass
except ValueError:
    pass
"""
    assert len(_check(src)) == 2


# ---- Line / column reporting ----


def test_reports_line_and_col_for_top_level_try():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except ValueError:
    pass
"""
    diags = _check(src)
    assert len(diags) == 1
    assert (diags[0].line, diags[0].col) == (2, 1)


def test_reports_line_and_col_for_indented_try():
    src = """
def outer():
    if flag:
        try:
            a = one()
            b = two()
            c = three()
            d = four()
        except ValueError:
            pass
"""
    diags = _check(src)
    assert len(diags) == 1
    assert (diags[0].line, diags[0].col) == (4, 9)


# ---- Multiple violations ----


def test_two_sibling_fat_trys_report_both_in_order():
    src = _try_with_n_calls(4) + "\n" + _try_with_n_calls(5)
    diags = _check(src)
    lines = [d.line for d in diags]
    assert len(diags) == 2
    assert lines == sorted(lines)


def test_multi_violation_is_position_sorted():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
    try:
        e = n1()
        f = n2()
        g = n3()
        h = n4()
    except KeyError:
        pass
except ValueError:
    pass
try:
    i = s1()
    j = s2()
    k = s3()
    l = s4()
except ValueError:
    pass
"""
    lines = [d.line for d in _check(src)]
    assert lines == sorted(lines)


# ---- False-positive guards ----


def test_small_try_with_large_except_is_clean():
    src = """
try:
    x = risky()
except ValueError:
    a = one()
    b = two()
    c = three()
    d = four()
    e = five()
"""
    assert _check(src) == []


def test_small_try_with_large_finally_is_clean():
    src = """
try:
    x = risky()
finally:
    a = one()
    b = two()
    c = three()
    d = four()
    e = five()
"""
    assert _check(src) == []


def test_comments_and_blank_lines_are_not_statements():
    src = """
try:
    a = one()

    # setup finished

    b = two()
    # follow-up
    c = three()
except ValueError:
    pass
"""
    assert _check(src) == []


def test_comments_between_four_calls_still_fires():
    src = """
try:
    a = one()

    # a comment
    b = two()
    c = three()
    # another
    d = four()
except ValueError:
    pass
"""
    assert len(_check(src)) == 1


# ---- Parse edge cases ----


def test_empty_source_returns_empty():
    assert _check("") == []


def test_whitespace_only_source_returns_empty():
    assert _check("\n\n   \n") == []


def test_module_without_try_returns_empty():
    src = """
def f():
    a = one()
    b = two()
    c = three()
    d = four()
"""
    assert _check(src) == []


def test_syntax_error_returns_empty():
    assert _check("def broken(:\n    pass") == []


def test_try_with_multiple_excepts_and_fat_body_fires_once():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except ValueError:
    pass
except KeyError:
    pass
"""
    assert len(_check(src)) == 1


# ---- Adversarial: re-raise exemption, TryStar, and subtree-walk edges ----


def test_trystar_all_handlers_reraise_exempts():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except* ValueError:
    raise
"""
    assert _check(src) == []


def test_trystar_mixed_reraise_and_swallow_still_fires():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except* ValueError:
    raise
except* KeyError:
    pass
"""
    assert len(_check(src)) == 1


def test_many_calls_in_single_comprehension_statement_count_once():
    src = """
try:
    a = [f(x) for x in g() if h(x)]
    b = two()
    c = three()
except ValueError:
    pass
"""
    assert _check(src) == []


def test_for_loop_raise_handler_can_skip_body_so_still_fires():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except ValueError:
    for x in y():
        raise
"""
    assert len(_check(src)) == 1


def test_conditional_return_before_tail_reraise_should_still_fire():
    src = """
def outer():
    try:
        a = one()
        b = two()
        c = three()
        d = four()
    except ValueError:
        if recoverable():
            return None
        raise
"""
    assert len(_check(src)) == 1


def test_if_else_both_branches_reraise_should_be_exempt():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except ValueError:
    if x():
        raise A
    else:
        raise B
"""
    assert _check(src) == []


def test_nested_def_bodies_do_not_execute_so_should_be_clean():
    src = """
try:
    def a(): return one()
    def b(): return two()
    def c(): return three()
    def d(): return four()
except ValueError:
    pass
"""
    assert _check(src) == []


def test_lambda_bodies_do_not_execute_so_should_be_clean():
    src = """
try:
    a = lambda: one()
    b = lambda: two()
    c = lambda: three()
    d = lambda: four()
except ValueError:
    pass
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "definition",
    [
        pytest.param("@decorateN()\ndef fN(): pass", id="decorators"),
        pytest.param("def fN(value=defaultN()): pass", id="function-defaults"),
        pytest.param("fN = lambda value=defaultN(): value", id="lambda-defaults"),
    ],
)
def test_definition_time_calls_count(definition: str):
    body = "\n".join(
        "\n".join(f"    {line}" for line in definition.replace("N", str(i)).splitlines())
        for i in range(4)
    )
    src = f"try:\n{body}\nexcept ValueError:\n    pass\n"
    assert len(_check(src)) == 1


def test_with_wrapped_reraise_handler_should_be_exempt():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
except ValueError:
    with ctx():
        raise
"""
    assert _check(src) == []


# Observability is success-only bookkeeping and does not count.


def test_cache_priming_shape_is_clean():
    src = """
start_time = time.monotonic()
try:
    async for _ in llm.chat(chat_ctx=ctx):
        break

    elapsed = time.monotonic() - start_time
    cache_warm_total.labels(result="success", phase="scenario").inc()
    cache_warm_duration.labels(phase="scenario").observe(elapsed)
    logger.info(
        "[CACHE] Primed LLM cache (scenario)",
        prefix_length=len(prefix),
        elapsed_s=round(elapsed, 2),
    )
except Exception:
    logger.warning("failed")
"""
    assert _check(src) == []


def test_cache_priming_static_shape_is_clean():
    src = """
try:
    static_prompt = await global_config_service.get_static_prompt(language=language)

    async for _ in llm.chat(chat_ctx=ctx):
        break

    elapsed = time.monotonic() - start_time
    cache_warm_total.labels(result="success", phase="static").inc()
    cache_warm_duration.labels(phase="static").observe(elapsed)
    logger.info("[CACHE] Primed", prompt_length=len(static_prompt))
except Exception:
    logger.warning("failed")
"""
    assert _check(src) == []


def test_builder_shape_is_clean():
    src = """
try:
    function_tools = await default_tool.init()
    agent_tools.extend(function_tools)
    if fragment := default_tool.prompt_fragment():
        prompt_fragments.append(fragment)
    logger.info(
        "[TOOL] instantiated default tool",
        tool_name=type(default_tool).__name__,
        function_count=len(function_tools),
    )
except Exception as e:
    errors_total.labels(provider="agent", error_type=type(e).__name__).inc()
    logger.exception("[TOOL] failed")
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "stmt",
    [
        pytest.param('logger.info("msg", n=len(items))', id="logger"),
        pytest.param('log.bind(k=1).warning("msg")', id="logger-builder-chain"),
        pytest.param('logging.getLogger(__name__).error("msg")', id="stdlib-logger-factory"),
        pytest.param("elapsed = time.monotonic() - start", id="monotonic-clock"),
        pytest.param("t = time.perf_counter()", id="perf-counter"),
        pytest.param("now = datetime.now()", id="datetime-now"),
        pytest.param('requests_total.labels(route="/x").inc()', id="prometheus-counter"),
        pytest.param("latency.observe(elapsed)", id="prometheus-histogram"),
        pytest.param('statsd.timing("x", elapsed)', id="statsd"),
        pytest.param('span.set_attribute("k", "v")', id="otel-set-attribute"),
        pytest.param("span.record_exception(e)", id="otel-record-exception"),
        pytest.param("n = len(items)", id="inert-builtin"),
    ],
)
def test_observability_statements_do_not_count(stmt: str):
    """Three real throwing statements plus one instrumentation statement stays at the limit."""
    src = f"""
try:
    a = one()
    b = two()
    c = three()
    {stmt}
except ValueError:
    pass
"""
    assert _check(src) == []


@pytest.mark.parametrize(
    "stmt",
    [
        pytest.param('logger.info("msg", user=fetch_user())', id="logger-with-real-call-arg"),
        pytest.param("cache.set(key, value)", id="cache-set-is-not-a-metric"),
        pytest.param("store.record(row)", id="store-record-is-not-a-metric"),
        pytest.param('data = open("f").read()', id="open-is-not-inert"),
        pytest.param("await emit_metric()", id="bare-await"),
    ],
)
def test_statements_mixing_real_work_still_count(stmt: str):
    """The guard must not become a blanket escape hatch for anything with a dot in it."""
    src = f"""
try:
    a = one()
    b = two()
    c = three()
    {stmt}
except ValueError:
    pass
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "4 statements that can raise" in diags[0].message


def test_a_try_full_of_only_logging_never_fires():
    src = """
try:
    logger.info("a")
    logger.info("b")
    logger.info("c")
    logger.info("d")
    logger.info("e")
except ValueError:
    pass
"""
    assert _check(src) == []


def test_genuinely_fat_try_still_fires():
    src = """
try:
    a = one()
    b = two()
    c = three()
    d = four()
    logger.info("done")
except ValueError:
    pass
"""
    diags = _check(src)
    assert len(diags) == 1
    assert "4 statements that can raise" in diags[0].message


@pytest.mark.parametrize(
    ("path", "header"),
    [
        pytest.param("app/service.py", "# Code generated by protoc. DO NOT EDIT.\n", id="header"),
        pytest.param("src/generated/service.py", "", id="generated-directory"),
    ],
)
def test_generated_files_are_exempt(path: str, header: str):
    assert _check(header + _try_with_n_calls(4), path) == []
