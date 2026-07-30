"""SARJ007: `try` block with more than 3 top-level statements that can raise.

A fat `try` body obscures which statement is actually expected to raise and
widens the blast radius of the `except` handlers: unrelated failures get
caught (and often swallowed or mis-reported) by handlers written for a
different operation. Keep the `try` skinny — isolate the throwing
statement(s) and move the non-throwing setup and follow-up work outside.

Two refinements keep the count aligned with that intent and avoid the
false-positive patterns that dominated real-world suppressions:

* Only top-level statements that *can raise* are counted — a statement counts
  toward the limit only if its subtree contains a call or `await`. Pure
  assignments / name-rebinds (`self.x = y`, `a = b.c`) don't obscure a throwing
  statement and are free. Statements nested inside an `if` / `with` / loop
  count as the single compound statement that contains them. Nested `try`
  blocks are checked independently. `try*` (PEP 654) is held to the same limit.
* OBSERVABILITY STATEMENTS ARE FREE for the same reason pure assignments are.
  A statement whose calls are all instrumentation — a logger call, a Prometheus /
  statsd / OpenTelemetry recorder (`counter.labels(...).inc()`,
  `hist.observe(elapsed)`, `span.set_attribute(...)`), a monotonic clock read, or
  a value-shaping builtin used to format an argument (`len`, `round`, `type`) —
  does not obscure which statement the handler was written for: nobody catches a
  failed `logger.info`. It is also, being success-path bookkeeping, exactly what
  must stay INSIDE the `try` so it does not run on the except path — so the rule
  was asking for a change that cannot be made. A statement mixing a real call
  with logging still counts.

  Evidence, bulbul PR #4111 (all suppressed at PR head, none a defect):
  `python/agent/agent/lk/cache_primer.py:47` and `:110` — both suppressions read
  "success-only bookkeeping (elapsed/metrics/log) must stay inside try so it does
  not run on the except path"; of the 6 and 5 statements counted there, only 2
  and 1 were real operations (`get_static_prompt`, `llm.chat`), the rest were
  `time.monotonic()`, two `cache_primer_*.labels(...).inc()/.observe()` recorders
  and a `logger.info`. Likewise
  `python/agent/agent/lk/builder/tool_builder.py:118` (4 counted, the 4th a
  `logger.info`).
* `try` blocks that carry an `else` or `finally` clause are exempt. Those
  clauses are a deliberate success/cleanup contract that couples the body to
  the handler (a `finally` that tears down a resource, an `else`/`finally` that
  reads a status the body set) — statements can't be freely hoisted out without
  changing semantics, so the length check is counterproductive there.
* `try` blocks whose every `except` handler re-raises (bare `raise`, or
  `raise Wrapped from e`) are exempt. The fat-try smell is over-broad
  *swallowing*; when no handler swallows, the width is deliberate uniform
  error-context / metric wrapping and isolating one call would change which
  failures are reported. A handler that returns / continues / passes /
  logs-without-raise is swallowing and keeps the block in scope.

Instead of:
    try:
        payload = build_payload(order)
        response = client.send(payload)
        record = parse(response)
        store.save(record)
    except HTTPError:
        ...

Prefer:
    payload = build_payload(order)
    try:
        response = client.send(payload)
    except HTTPError:
        ...
    record = parse(response)
    store.save(record)

References:
- https://docs.python.org/3/tutorial/errors.html#handling-exceptions
- https://docs.python.org/3/library/ast.html#ast.Try

* **generated files** (`_paths.is_generated_source`). Their layout is the
  generator's, and re-running the generator discards any edit, so a finding
  there can never be acted on in place. Measured on the 69 `DO NOT EDIT`
  files git-tracked across bulbul and noura-be — Speakeasy's
  `python/sdk/src/sarj_platform_sdk/` accounts for all of them.

"""

from __future__ import annotations

import ast
import enum
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, nodes
from sarj_python_lint.rules._logging import is_logger_expr
from sarj_python_lint.rules._paths import is_generated_source


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_MAX_TRY_BODY_STATEMENTS = 3


def _walk_same_scope(node: ast.AST) -> Iterator[ast.AST]:
    """Walk `node` without descending into nested `def` / `async def` / `lambda` bodies.

    Those bodies do not run when the enclosing `try` executes, so calls inside
    them must not count as throwing. Decorators and default-argument expressions
    still run at definition time, so their fields are walked normally.

    Yields:
        Each AST node in the same execution scope as `node`.

    """
    stack: list[ast.AST] = [node]
    while stack:
        current = stack.pop()
        yield current
        skipped_body = _nested_scope_body_ids(current)
        stack.extend(child for child in children(current) if id(child) not in skipped_body)


def _nested_scope_body_ids(node: ast.AST) -> frozenset[int]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return frozenset(id(stmt) for stmt in node.body)
    if isinstance(node, ast.Lambda):
        return frozenset({id(node.body)})
    return frozenset()


#: Terminal method names of the metrics/tracing recorders. Prometheus counters and
#: histograms (`counter.labels(...).inc()`, `hist.observe(x)`, `gauge.set(x)`),
#: statsd (`.increment`, `.timing`), and OpenTelemetry spans
#: (`span.set_attribute(...)`, `span.record_exception(e)`) are all fire-and-forget
#: recorders — see `_is_observability_call`.
#: `set` and `record` are deliberately ABSENT — `cache.set(k, v)` /
#: `store.record(row)` collide with them and are real work whose failure a handler
#: is plausibly written for.
_OBSERVABILITY_METHODS = frozenset(
    {
        "inc",
        "dec",
        "observe",
        "set_to_current_time",
        "labels",
        "increment",
        "decrement",
        "gauge",
        "timing",
        "histogram",
        "record_exception",
        "add_event",
        "set_attribute",
        "set_attributes",
        "set_status",
    }
)

#: Clock reads. `time.monotonic()` / `perf_counter()` / `time()` and
#: `datetime.now()` / `utcnow()` cannot raise at all, but they are the calls that
#: turn an elapsed-time bookkeeping line into a "throwing" statement.
_CLOCK_ROOTS = frozenset({"time", "datetime", "date"})
_CLOCK_METHODS = frozenset(
    {
        "monotonic",
        "monotonic_ns",
        "perf_counter",
        "perf_counter_ns",
        "time",
        "time_ns",
        "now",
        "utcnow",
    }
)

#: Value-shaping builtins. These are what an instrumentation line calls on its
#: arguments — `logger.info(..., n=len(items), elapsed_s=round(t, 2))`,
#: `tool_name=type(tool).__name__`. They are pure and total on the values a log
#: line passes them, so they don't make the statement a candidate for the
#: handler. Builtins that genuinely do work and raise (`open`, `eval`, `next`,
#: `getattr`) are deliberately absent.
_INERT_BUILTINS = frozenset(
    {
        "abs",
        "bool",
        "float",
        "format",
        "id",
        "int",
        "len",
        "list",
        "repr",
        "round",
        "str",
        "tuple",
        "type",
    }
)


def _attr_root(expr: ast.expr) -> str | None:
    """Find the leftmost identifier of an attribute chain (`a.b.c` -> `a`).

    Returns:
        The root identifier name, or None when the chain is not rooted in a Name.

    """
    current = expr
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _is_observability_call(call: ast.Call) -> bool:
    """Report whether `call` is instrumentation — logging, metrics/tracing, or a clock read.

    No `except` handler is ever written *for* one of these: a logger call is
    swallow-by-design (loguru/`logging` route their own failures to the handler's
    error stream), a Prometheus/OTel recorder mutates an in-process counter, and a
    monotonic clock read cannot raise. They are exactly the statements engineers
    keep inside a `try` so they run only on the success path, which is why they
    dominate the rule's suppressions.

    Returns:
        True when the call is an observability/instrumentation call.

    """
    func = call.func
    if is_logger_expr(func):
        return True
    if isinstance(func, ast.Name):
        return func.id in _INERT_BUILTINS
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in _CLOCK_METHODS and _attr_root(func) in _CLOCK_ROOTS:
        return True
    # A metrics/tracing recorder — including `counter.labels(...).inc()`, whose
    # receiver is itself an observability call.
    if func.attr in _OBSERVABILITY_METHODS:
        receiver = func.value
        return not isinstance(receiver, ast.Call) or _is_observability_call(receiver)
    return False


def _can_raise(stmt: ast.stmt) -> bool:
    """Report whether the statement can plausibly raise when the `try` runs.

    A statement can raise when its same-scope subtree contains a call or `await`.
    Pure assignments / rebinds and inert `def` / `lambda` definitions (whose
    bodies never execute here) are free.

    So is a statement whose calls are ALL observability — logging, metrics,
    tracing, a clock read. Those don't obscure which statement the handler was
    written for (nobody catches a failed `logger.info`), and, being success-path
    bookkeeping, they are precisely what must stay inside the `try` so it does not
    run on the except path. Treating them as free is the same argument that
    already makes pure assignments free. A statement that MIXES a real call with
    logging still counts.

    Returns:
        True when the statement may throw.

    """
    calls = [n for n in _walk_same_scope(stmt) if isinstance(n, (ast.Call, ast.Await))]
    if not calls:
        return False
    return not all(isinstance(n, ast.Call) and _is_observability_call(n) for n in calls)


class _Exit(enum.Enum):
    RAISE = enum.auto()
    SWALLOW = enum.auto()
    FALL = enum.auto()


def _stmt_exits(stmt: ast.stmt) -> set[_Exit]:
    """Compute the set of ways control can leave `stmt`.

    Control can propagate an exception (`RAISE`), diverge without raising via
    return/break/continue (`SWALLOW`), or complete normally and fall through to
    the next statement (`FALL`).

    Returns:
        The set of exit modes for `stmt`.

    """
    match stmt:
        case ast.Raise():
            return {_Exit.RAISE}
        case ast.Return() | ast.Break() | ast.Continue():
            return {_Exit.SWALLOW}
        case ast.If(body=body, orelse=orelse):
            else_exits = _body_exits(orelse) if orelse else {_Exit.FALL}
            return _body_exits(body) | else_exits
        case ast.With(body=body) | ast.AsyncWith(body=body):
            return _body_exits(body)
        case _:
            return {_Exit.FALL}


def _body_exits(stmts: list[ast.stmt]) -> set[_Exit]:
    exits: set[_Exit] = set()
    for stmt in stmts:
        stmt_exits = _stmt_exits(stmt)
        exits |= stmt_exits - {_Exit.FALL}
        if _Exit.FALL not in stmt_exits:
            return exits
    exits.add(_Exit.FALL)
    return exits


def _all_handlers_reraise(handlers: list[ast.ExceptHandler]) -> bool:
    """Report whether every `except` handler is guaranteed to re-raise on all paths.

    When it does, the block is uniform error-context/metric wrapping, not
    swallowing, so its width is intentional. A handler with any path that returns
    / continues / passes / falls through (including a conditional early return
    before a tail `raise`) is swallowing and makes this False, so the block still
    fires.

    Returns:
        True when all handlers unconditionally re-raise.

    """
    return bool(handlers) and all(_body_exits(h.body) == {_Exit.RAISE} for h in handlers)


class NoFatTryBlocks(Rule):
    """Try body with too many throwing statements — isolate the one that raises."""

    id: str = "no-fat-try-blocks"
    code: str = "SARJ007"
    description: str = "Try block has too many throwing statements — keep try blocks skinny."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated_source(source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for node in nodes(tree, ast.Try, ast.TryStar):
            # An `else`/`finally` clause is a deliberate success/cleanup contract
            # that couples the body to the handler — don't fight it on length.
            if node.orelse or node.finalbody:
                continue
            # When every `except` re-raises, the wide body is a deliberate
            # error-context/metric wrapper, not an over-broad swallow — exempt.
            if _all_handlers_reraise(node.handlers):
                continue
            throwing = sum(_can_raise(stmt) for stmt in node.body)
            if throwing <= _MAX_TRY_BODY_STATEMENTS:
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"try block has {throwing} statements that can raise "
                        f"(max {_MAX_TRY_BODY_STATEMENTS}) — try blocks should "
                        "isolate the throwing statement(s); move non-throwing "
                        "work outside the try."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
