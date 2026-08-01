"""Exhaustive tests for SARJ010 `no-unreachable-after-terminal`.

The rule is a pure structural check: for every statement-list field
(`body`/`orelse`/`finalbody`) on every AST node, if a terminal
(`return`/`raise`/`break`/`continue`) appears before the last element of that
list, the statement immediately after the FIRST such terminal is flagged as
unreachable — at most one diagnostic per list. It is intentionally naive:

  * `sys.exit()` / `os._exit()` are function calls (`ast.Expr`), NOT terminal
    AST nodes, so code after them is NOT flagged.
  * `break`/`continue` outside a loop still parse (no semantic check) and are
    flagged structurally.
  * A trailing `...` or string-literal "docstring" after a terminal IS an
    `ast.Expr` statement, so it IS flagged.
  * Comments are not AST statements, so a terminal followed only by a comment
    is the last statement of its list and is NOT flagged.
  * Diagnostics come out in `ast.walk` (breadth-first) order, which is source
    order for sibling blocks but outer-before-inner for nested blocks — it is
    not globally line-sorted.
"""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_unreachable_after_terminal import (
    NoUnreachableAfterTerminal,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return NoUnreachableAfterTerminal().check(Path("<test>.py"), source)


# --------------------------------------------------------------------------- #
# Positive: a statement after each terminal type is flagged.                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "terminal",
    [
        "return",
        "return None",
        "return 1",
        "return a, b",
        "raise ValueError('boom')",
        "raise",
        "raise RuntimeError() from err",
        "break",
        "continue",
    ],
)
def test_flags_statement_after_each_terminal_in_loop(terminal: str):
    # A loop body is the one block where all four terminal kinds are legal.
    src = f"""
def f(items, a, b, err):
    for x in items:
        {terminal}
        process(x)
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ010"


@pytest.mark.parametrize(
    "terminal",
    ["return 1", "raise ValueError('x')"],
)
def test_flags_statement_after_return_or_raise_in_function_body(terminal: str):
    src = f"""
def f():
    {terminal}
    dead()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ010"


# --------------------------------------------------------------------------- #
# Positive: terminal-before-last is flagged in every block-bearing construct.  #
# Covers the body / orelse / finalbody fields across node types.               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "src"),
    [
        (
            "function-body",
            "def f():\n    return 1\n    dead()\n",
        ),
        (
            "async-function-body",
            "async def f():\n    return 1\n    dead()\n",
        ),
        (
            "method-body",
            "class C:\n    def m(self):\n        return 1\n        dead()\n",
        ),
        (
            "module-body",
            "raise ValueError()\ndead()\n",
        ),
        (
            "if-body",
            "def f(x):\n    if x:\n        return 1\n        dead()\n",
        ),
        (
            "if-orelse",
            "def f(x):\n    if x:\n        pass\n    else:\n        return 1\n        dead()\n",
        ),
        (
            "elif-orelse",
            "def f(x):\n    if x:\n        pass\n    elif x == 2:\n        return 1\n        dead()\n",
        ),
        (
            "for-body",
            "def f(xs):\n    for x in xs:\n        break\n        dead()\n",
        ),
        (
            "for-orelse",
            "def f(xs):\n    for x in xs:\n        pass\n    else:\n        return 1\n        dead()\n",
        ),
        (
            "async-for-body",
            "async def f(xs):\n    async for x in xs:\n        continue\n        dead()\n",
        ),
        (
            "while-body",
            "def f(x):\n    while x:\n        break\n        dead()\n",
        ),
        (
            "while-orelse",
            "def f(x):\n    while x:\n        pass\n    else:\n        return 1\n        dead()\n",
        ),
        (
            "with-body",
            "def f():\n    with open('x') as fh:\n        return 1\n        dead()\n",
        ),
        (
            "async-with-body",
            "async def f():\n    async with ctx() as c:\n        return 1\n        dead()\n",
        ),
        (
            "try-body",
            "def f():\n    try:\n        return 1\n        dead()\n    except Exception:\n        pass\n",
        ),
        (
            "except-handler-body",
            "def f():\n    try:\n        pass\n    except Exception:\n        return 1\n        dead()\n",
        ),
        (
            "try-orelse",
            "def f():\n    try:\n        pass\n    except Exception:\n        pass\n    else:\n        return 1\n        dead()\n",
        ),
        (
            "try-finalbody",
            "def f():\n    try:\n        pass\n    finally:\n        return 1\n        dead()\n",
        ),
        (
            "match-case-body",
            "def f(x):\n    match x:\n        case 1:\n            return 1\n            dead()\n",
        ),
    ],
)
def test_flags_terminal_before_last_in_block(label: str, src: str):
    diags = _check(src)
    assert len(diags) == 1, label
    assert diags[0].code == "SARJ010"


# --------------------------------------------------------------------------- #
# Negative: terminal is the LAST statement of its block -> nothing flagged.    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "src"),
    [
        (
            "return-last-function",
            "def f(x):\n    if x:\n        return 1\n    return 2\n",
        ),
        (
            "return-last-if-body",
            "def f(x):\n    if x:\n        do()\n        return 1\n    return 2\n",
        ),
        (
            "break-last-loop",
            "def f(xs):\n    for x in xs:\n        if x:\n            break\n",
        ),
        (
            "continue-last-loop",
            "def f(xs):\n    for x in xs:\n        if not x:\n            continue\n        work(x)\n",
        ),
        (
            "raise-last-except",
            "def f():\n    try:\n        risky()\n    except Exception:\n        raise\n",
        ),
        (
            "return-last-with",
            "def f():\n    with open('x') as fh:\n        return fh.read()\n",
        ),
        (
            "return-last-finally",
            "def f():\n    try:\n        pass\n    finally:\n        return 1\n",
        ),
        (
            "return-last-module",
            "x = 1\nreturn x\n",
        ),
        (
            "nested-continue-last",
            "def f(rows):\n    for r in rows:\n        for c in r:\n            continue\n",
        ),
    ],
)
def test_terminal_as_last_statement_is_allowed(label: str, src: str):
    assert _check(src) == [], label


# --------------------------------------------------------------------------- #
# Negative: terminal confined to one branch / nested block; sibling code is    #
# genuinely reachable, so it must NOT be flagged.                              #
# --------------------------------------------------------------------------- #


def test_return_in_one_branch_then_code_after_if():
    src = """
def f(x):
    if x:
        return 1
    do_more()
    return 2
"""
    assert _check(src) == []


def test_return_in_else_branch_only():
    src = """
def f(x):
    if x:
        do()
    else:
        return 1
"""
    assert _check(src) == []


def test_terminal_in_nested_block_code_after_outer_block_reachable():
    src = """
def f(xs):
    for i in xs:
        if i:
            break
    cleanup()
"""
    assert _check(src) == []


def test_raise_in_nested_if_code_after_if_reachable():
    src = """
def f(x):
    if x:
        raise ValueError()
    y = 1
    return y
"""
    assert _check(src) == []


def test_guard_clause_pattern_is_clean():
    src = """
def f(x, y):
    if x:
        return 1
    if y:
        return 2
    return 3
"""
    assert _check(src) == []


def test_try_returns_finally_cleanup_is_reachable():
    src = """
def f():
    try:
        return compute()
    finally:
        cleanup()
"""
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# False-positive guards: non-terminal "exits" must NOT be treated as terminal. #
# The rule is structural on AST node types only.                               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "src"),
    [
        (
            "sys-exit",
            "import sys\ndef f():\n    sys.exit(1)\n    unreachable_but_not_flagged()\n",
        ),
        (
            "os-_exit",
            "import os\ndef f():\n    os._exit(1)\n    unreachable_but_not_flagged()\n",
        ),
        (
            "plain-call",
            "def f():\n    do_something()\n    do_more()\n",
        ),
    ],
)
def test_non_terminal_exit_calls_are_not_flagged(label: str, src: str):
    assert _check(src) == [], label


def test_conditional_return_expression_does_not_terminate_list():
    # A ternary that may or may not "exit" is still one Return statement; the
    # statement after it in the same list IS unreachable and flagged. Guard is
    # that we don't over- or under-count: exactly one diagnostic.
    src = """
def f(x):
    return 1 if x else 2
    dead()
"""
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# False-positive guard: `yield` / `yield from` after a terminal is the idiom    #
# that forces a function to be a generator even when the path is unreachable.   #
# It is load-bearing (removing it changes the function type) -> NOT flagged.    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "src"),
    [
        (
            "async-gen-return-then-yield",
            "async def _gen():\n    return\n    yield\n",
        ),
        (
            "sync-gen-return-then-yield",
            "def _gen():\n    return\n    yield\n",
        ),
        (
            "return-then-yield-value",
            "def _gen():\n    return\n    yield 1\n",
        ),
        (
            "return-then-yield-from",
            "def _gen():\n    return\n    yield from ()\n",
        ),
        (
            "raise-then-yield",
            "def _gen():\n    raise RuntimeError()\n    yield\n",
        ),
    ],
)
def test_yield_after_terminal_is_not_flagged(label: str, src: str):
    assert _check(src) == [], label


def test_non_yield_after_terminal_still_flagged_regression():
    # Regression: only the yield case is exempt; a plain statement after a
    # terminal in a generator-shaped function still fires.
    src = """
def _gen():
    return
    dead()
    yield
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ010"
    assert diags[0].line == 4  # points at `dead()`, not the later `yield`


# --------------------------------------------------------------------------- #
# Edge: comments, docstrings, ellipsis, empty, whitespace, syntax errors.      #
# --------------------------------------------------------------------------- #


def test_comment_after_terminal_is_not_flagged():
    # A comment is not an AST statement, so the terminal is the last element.
    src = """
def f():
    return 1
    # trailing comment, not dead code
"""
    assert _check(src) == []


@pytest.mark.parametrize("trailing", ["...", "'a docstring-like string'", '"""doc"""'])
def test_expr_statement_after_terminal_is_flagged(trailing: str):
    # `...` and bare string literals parse to ast.Expr statements, which DO
    # follow the terminal and therefore ARE flagged.
    src = f"""
def f():
    return 1
    {trailing}
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ010"


@pytest.mark.parametrize(
    "src",
    ["", "   \n  \n", "# just a comment\n# another\n", "\n\n\n"],
)
def test_empty_or_commentless_sources_yield_nothing(src: str):
    assert _check(src) == []


@pytest.mark.parametrize(
    "src",
    [
        "def f(:\n    pass",
        "def f():\nreturn 1",
        "class C\n    pass",
        "for x in :\n    pass",
        "if True\n    pass",
    ],
)
def test_syntax_errors_return_empty(src: str):
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Context: a terminal only ends the block where Python allows it. `return`      #
# outside a function and `break`/`continue` outside a loop are SyntaxErrors —   #
# the file never runs, so nothing after them is meaningfully dead.              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("terminal", ["break", "continue"])
def test_break_continue_outside_loop_is_not_flagged(terminal: str):
    src = f"""
def f():
    {terminal}
    dead()
"""
    assert _check(src) == []


@pytest.mark.parametrize("terminal", ["break", "continue"])
def test_break_continue_inside_loop_still_flagged(terminal: str):
    src = f"""
def f(xs):
    for x in xs:
        {terminal}
        dead()
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ010"


def test_break_in_loop_else_clause_is_not_flagged():
    # `break` in a `for ... else:` binds to an ENCLOSING loop, not this one, so
    # at function scope it is a SyntaxError rather than a terminal.
    src = """
def f(xs):
    for x in xs:
        pass
    else:
        break
        dead()
"""
    assert _check(src) == []


def test_break_inside_nested_def_in_a_loop_is_not_flagged():
    src = """
def f(xs):
    for x in xs:
        def inner():
            break
            dead()
"""
    assert _check(src) == []


def test_module_level_return_is_not_flagged():
    src = "return 1\ndead()\n"
    assert _check(src) == []


def test_class_body_return_is_not_flagged():
    src = """
class C:
    return 1
    dead()
"""
    assert _check(src) == []


def test_module_level_raise_is_still_flagged():
    src = "raise ValueError()\ndead()\n"
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# Counting: at most one diagnostic per statement list (the first terminal).    #
# --------------------------------------------------------------------------- #


def test_only_first_unreachable_in_a_list_is_flagged():
    src = """
def f():
    return 1
    a = 2
    b = 3
    c = 4
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 4  # points at `a = 2`, the first unreachable stmt


def test_two_terminals_in_one_list_still_one_diagnostic():
    src = """
def f(x):
    return 1
    return 2
    return 3
"""
    assert len(_check(src)) == 1


def test_separate_lists_each_flagged():
    src = """
def f(x):
    if x:
        return 1
        dead_a()
    else:
        return 2
        dead_b()
"""
    assert len(_check(src)) == 2


def test_nested_function_bodies_each_flagged():
    src = """
def outer():
    def inner():
        return 1
        dead_inner()
    return inner
    dead_outer()
"""
    assert len(_check(src)) == 2


# --------------------------------------------------------------------------- #
# Line / column reporting: diag points at the unreachable statement, col+1.    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("src", "line", "col"),
    [
        ("def f():\n    return 1\n    dead()\n", 3, 5),
        (
            "def f():\n    if True:\n        if True:\n            return 1\n            dead()\n",
            5,
            13,
        ),
        (
            "def f(x):\n    match x:\n        case 1:\n            return 1\n            dead()\n",
            5,
            13,
        ),
        ("raise ValueError()\ndead()\n", 2, 1),
    ],
)
def test_diagnostic_line_and_col(src: str, line: int, col: int):
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == line
    assert diags[0].col == col


def test_col_is_one_based_offset_plus_one():
    # `dead()` sits at 4-space indent -> col_offset 4 -> reported col 5.
    src = "def f():\n    return 1\n    dead()\n"
    assert _check(src)[0].col == 5


# --------------------------------------------------------------------------- #
# Ordering: sibling blocks appear in source order; nesting follows walk order  #
# (outer body before inner body), i.e. not globally line-sorted.               #
# --------------------------------------------------------------------------- #


def test_sibling_top_level_blocks_in_source_order():
    src = """
def a():
    return 1
    dead_a()
def b():
    return 2
    dead_b()
"""
    diags = _check(src)
    assert [d.line for d in diags] == [4, 7]


def test_nested_blocks_report_in_line_order():
    src = """
def outer():
    def inner():
        return 1
        dead_inner()
    return inner
    dead_outer()
"""
    diags = _check(src)
    assert [d.line for d in diags] == [5, 7]


# --------------------------------------------------------------------------- #
# Regression pins for the original hand-written cases.                         #
# --------------------------------------------------------------------------- #


def test_flags_statement_after_return():
    src = """
def f():
    return 1
    print("dead")
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ010"


def test_flags_statement_after_break():
    src = """
def f(items):
    for x in items:
        break
        process(x)
"""
    assert len(_check(src)) == 1


def test_allows_terminal_as_last_statement():
    src = """
def f(x):
    if x:
        return 1
    return 2
"""
    assert _check(src) == []


def test_handles_syntax_error():
    assert _check("def f(:\n    pass") == []


# --------------------------------------------------------------------------- #
# Adversarial: yield-exemption edges + terminal detection in exotic blocks.    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "src"),
    [
        (
            "raise-then-yield-from",
            "def _gen():\n    raise RuntimeError()\n    yield from ()\n",
        ),
        (
            "yield-in-match-case-body",
            "def _gen(x):\n    match x:\n        case 1:\n            return\n            yield\n",
        ),
        (
            "yield-in-try-body",
            "def _gen():\n    try:\n        return\n        yield\n    except Exception:\n        pass\n",
        ),
        (
            "yield-in-finally",
            "def _gen():\n    try:\n        pass\n    finally:\n        return\n        yield\n",
        ),
        (
            "break-then-yield-in-loop",
            "def _gen():\n    for i in ():\n        break\n        yield\n",
        ),
        (
            "continue-then-yield-in-loop",
            "def _gen():\n    for i in ():\n        continue\n        yield\n",
        ),
        (
            "two-yields-after-terminal",
            "def _gen():\n    return\n    yield\n    yield 2\n",
        ),
    ],
)
def test_yield_marker_exempt_across_block_kinds(label: str, src: str):
    assert _check(src) == [], label


@pytest.mark.parametrize(
    ("label", "src"),
    [
        (
            "def-after-return",
            "def f():\n    return 1\n    def g():\n        pass\n",
        ),
        (
            "class-after-return",
            "def f():\n    return 1\n    class C:\n        pass\n",
        ),
        (
            "walrus-expr-after-return",
            "def f():\n    return 1\n    (x := 5)\n",
        ),
        (
            "nested-yield-block-after-return",
            "def _gen():\n    return\n    if True:\n        yield\n",
        ),
    ],
)
def test_non_bare_yield_after_terminal_is_flagged(label: str, src: str):
    # The exemption is deliberately shallow: only a direct bare `yield` /
    # `yield from` Expr statement is spared. A `def`/`class`/walrus, or a yield
    # wrapped in control flow, is still flagged as unreachable.
    diags = _check(src)
    assert len(diags) == 1, label
    assert diags[0].code == "SARJ010"


@pytest.mark.parametrize(
    "src",
    [
        "def _gen():\n    return\n    yield\n    dead()\n",
        "async def _gen():\n    return\n    yield\n    dead()\n",
    ],
)
def test_dead_code_after_exempt_yield_should_still_flag(src: str):
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ010"


@pytest.mark.parametrize(
    "src",
    [
        "def _gen():\n    return\n    x = yield\n",
        "def _gen():\n    return\n    x = yield from ()\n",
        "def _gen():\n    x = 0\n    return\n    x += yield\n",
    ],
)
def test_assigned_yield_marker_should_be_exempt(src: str):
    assert _check(src) == []
