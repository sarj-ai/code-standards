"""SARJ057: an assertion whose outcome is decided by the literal it was handed.

`assert True`, `assert ["..."]`, `self.assertEqual(1, 1)` — the condition
contains no value the code under test produced, so the assertion passes before
the program runs. It is not a weak test, it is a *non*-test: deleting the
function under test entirely would not change the result.

Two shapes dominate, and neither looks wrong at a glance:

* **the placeholder that was never replaced** — `expect(true).toBe(true)` in
  TypeScript, `assert True` in Python, left behind when a test file was
  scaffolded and the body never written;
* **the assertion whose real condition slid out of the condition slot.** This is
  the dangerous one, because it was a working assertion when it was typed. Home
  Assistant has the same six-line condition twice in
  `tests/helpers/test_device_registry.py` (:3711, :3777), wrapped in braces
  rather than parentheses::

      assert {
          "calls `device_registry.async_get_or_create` "
          "referencing a non existing `via_device` " in caplog.text
      }

  The braces make it a one-element **set display**, which is truthy whatever the
  `in` test inside it evaluates to. Airflow has the list-literal spelling in
  `providers/apache/hdfs/.../log/test_hdfs_task_handler.py:170`,
  `assert [f"No logs found on hdfs for ti={ti}"]`, where the `== messages` was
  lost. And Home Assistant's `emulated_hue/test_hue_api.py:1078` shows the third
  variant, where the value slid into the assertion-*message* slot:
  `assert True, cover_result_json[0]["success"][...]` — a `KeyError` there would
  still be raised, so it half-works, which is why it survived review.

Fires on exactly four shapes, all of them syntactically decidable:

1. `assert <always-truthy literal>` — `True`, a nonzero number (signed or not), a
   non-empty string, `not <falsy scalar constant>` (`not False`, `not 0`,
   `not ""`, `not None`), or a non-empty list/set/dict/tuple **display**;
2. `assert <literal> == <textually identical literal>` (and `is`);
3. `assertTrue(<truthy literal>)` / `assertFalse(<falsy literal>)`;
4. `assertEqual(<literal>, <textually identical literal>)` (and `assertIs`).

**Boundary with SARJ064 `trivially-true-assertion`.** This rule owns every
assertion whose fixed outcome is visible in the assertion syntax itself: bare
constants, `not <falsy constant>`, container displays, identical-literal
comparisons and the `unittest` assertion calls. SARJ064 starts where
cross-statement construction tracking is required — reading a constructor
keyword straight back out, or asserting that an object produced by calling a
class is an instance of that same class. The two rules used to overlap on bare
truthy constants and non-empty displays, which cost a doubled diagnostic on 42
positions across a 21-repository, 42,761-file census; SARJ064 ceded the shape
because this rule reaches further (production code, modules pytest never
collects, signed constants) and carries carve-outs SARJ064 lacked for the
`except`-handler marker and pytest-benchmark bodies.

**The narrowness is the rule.** The obvious generalisation — "flag a comparison
of a thing with itself" — was measured and is ~95% false positives.
`assert i == i`, `assert x is x`, `expect(hash([o])).toEqual(hash([o]))` are
*reflexivity, determinism and memoization* tests: for a type with a custom
`__eq__` or `__hash__`, `x == x` is precisely the property under test and can
genuinely fail. So an operand that is an identifier, an attribute or a call is
never enough; both sides must be literals, and textually identical ones.

Deliberately NOT flagged:

* **`assert True` as the sole statement of an `except` handler** — the
  deliberate "reaching here is the acceptable outcome" marker, the mirror image
  of the `assert False` that precedes it in the `try`. It reads as a tautology
  in isolation and is a real assertion in context: it asserts *which branch ran*.
  Both known Python false positives are this shape —
  `pydantic-core/tests/benchmarks/test_micro_benchmarks.py:716` and
  `core/tests/components/mqtt/test_client.py:1353`;
* **`assert <constant>` in a `match` arm when a sibling arm always fails** —
  the same reasoning as the `except` marker above, one construct along. In::

      match PROCESSOR.process(source_file=protected, password="not right"):
          case PDFProcessError(error=DecryptionError.INCORRECT_PASSWORD):
              assert True
          case _:
              raise AssertionError

  the *pattern* is the assertion: the test goes red the moment the result stops
  matching, so the marker records which arm ran rather than claiming a literal is
  true. Found against `faris`
  (`falltime/tests/services/test_pdf_processor.py:96` and `:112`), a first-party
  repo that was not in this rule's original 28,608-file corpus — so the "0 false
  positives" measured there held only because `faris` was absent. A `match` with
  no failing arm proves nothing and still fires, as does a constant assertion
  outside the `match`;
* **anything inside a pytest-benchmark test**, whether it takes the `benchmark`
  fixture or wears `@pytest.mark.benchmark` — the same carve-out SARJ043 needs,
  shared through `_pytest.py`. The try/`assert False`/except/`assert True`
  sandwich above is the idiomatic way to time a *failing* validation path;
* `assert False` — the standard unreachable-branch marker, and an assertion that
  always fails is a loud problem, not a silent one;
* an empty container (`assert []`), which is always *falsy* — that is a failing
  assertion, again loud;
* a container display with a `*splat` or `**unpack` element (`assert [*items]`),
  whose emptiness depends on the runtime value;
* an f-string, whose truth depends on the interpolated values.

Measured before shipping: **4 findings across 28,608 files** — 26,346 of
pydantic, trio, attrs, Airflow and Home Assistant plus 2,262 first-party files
in bulbul, noura-be, kpi-hub, ai and demo-gateway. All 4 are the true positives
named above; 0 false positives. The `except`/benchmark carve-outs are
load-bearing rather than defensive: with `_exempt_nodes` neutered the sweep
gains exactly the two known false positives and nothing else.

Re-measured on the corpus this standard now tracks — 21 repositories and 42,761
files, first-party bulbul, noura-be, digital-bank, submissions, ai, faris and
summer plus 14 OSS suites: **61 findings**, spread litellm 29, django 8,
dagster 7, prefect 7, sentry-python 3, celery 2, superset 2, airflow 1,
langchain 1, summer 1, and zero in the other eleven. Taking over
`not <falsy scalar constant>` from SARJ064 added **0** findings to that total —
the shape is rare enough that nobody in 42,761 files writes it — so it is here as
a contract this rule now owns rather than as a source of volume.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._pytest import has_benchmark_marker, uses_benchmark_fixture


if TYPE_CHECKING:
    from pathlib import Path


_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

# `pytest.fail(...)` / `self.fail(...)` — an arm that calls it cannot pass.
_FAIL = "fail"

# unittest methods whose single argument fixes the outcome on its own.
_TRUTHY_ARG_METHODS = frozenset({"assertTrue"})
_FALSY_ARG_METHODS = frozenset({"assertFalse"})

# unittest methods that compare two operands for sameness.
_EQUALITY_METHODS = frozenset({"assertEqual", "assertEquals", "assertIs"})

# unittest's failure-text parameter — present or not, the outcome is the same.
_UNITTEST_MSG_KWARG = "msg"

# `assertEqual(first, second)` and friends: the two operands compared.
_EQUALITY_ARITY = 2

# Comparison operators whose two-identical-literals form is a tautology. `<=`
# and `>=` are too, but nobody writes them by accident; `!=`/`is not` on
# identical literals always *fails*, which is loud rather than silent.
_SAMENESS_OPS = (ast.Eq, ast.Is)

# Enough of the operand to identify it in the message without pasting a screenful.
_OPERAND_PREVIEW_CHARS = 40

_CONTAINER_KINDS: dict[type[ast.expr], str] = {
    ast.List: "list",
    ast.Set: "set",
    ast.Dict: "dict",
    ast.Tuple: "tuple",
}


class NoTautologicalExpect(Rule):
    """An assertion on a literal can never fail — it tests the literal, not the code."""

    id: str = "no-tautological-expect"
    code: str = "SARJ057"
    description: str = "Assertion whose operands are all literals — its outcome is fixed before the code runs."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag assertions whose truth is decided by their own literals.

        Returns:
            One diagnostic per never-failing assertion, sorted by position.

        """
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        exempt = _exempt_nodes(tree)
        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=_message(node, reason),
            )
            for node, reason in _tautologies(tree, exempt)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _exempt_nodes(tree: ast.Module) -> set[ast.AST]:
    """Collect the nodes the carve-outs put out of reach.

    Every node under a pytest-benchmark test, plus the lone `assert` that forms
    an `except` handler's whole body — the "this exception is the acceptable
    outcome" marker, which is a statement about control flow rather than about a
    literal.

    Returns:
        The nodes this rule must not report.

    """
    exempt: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, _FUNC_NODES) and (uses_benchmark_fixture(node) or has_benchmark_marker(node)):
            exempt.update(ast.walk(node))
        elif isinstance(node, ast.ExceptHandler) and len(node.body) == 1 and isinstance(node.body[0], ast.Assert):
            exempt.add(node.body[0])
        elif isinstance(node, ast.Match):
            exempt.update(_match_arm_markers(node))
    return exempt


def _match_arm_markers(node: ast.Match) -> set[ast.AST]:
    """Collect `assert <constant>` statements marking which arm of a `match` ran.

    The `except`-handler carve-out above generalises: when one arm of a `match`
    always fails, a constant assertion in another arm is a statement about which
    pattern matched, not about the literal. The pattern *is* the assertion, and
    the test goes red the moment the subject stops matching it.

    Returns:
        The constant assertions in arms other than the failing one, or an empty
        set when no arm always fails.

    """
    if not any(all(_always_fails(stmt) for stmt in case.body) for case in node.cases):
        return set()
    return {
        stmt for case in node.cases for stmt in case.body if isinstance(stmt, ast.Assert) and not _always_fails(stmt)
    }


def _always_fails(stmt: ast.stmt) -> bool:
    """Report whether `stmt` cannot complete without failing the test.

    Returns:
        True for `raise ...`, `assert <falsy literal>`, and a bare `pytest.fail`
        or `self.fail` call.

    """
    if isinstance(stmt, ast.Raise):
        return True
    if isinstance(stmt, ast.Assert):
        return _is_always_falsy_literal(stmt.test)
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and _called_method(stmt.value) == _FAIL


def _tautologies(tree: ast.Module, exempt: set[ast.AST]) -> list[tuple[ast.Assert | ast.Call, str]]:
    """Find every assertion in `tree` whose outcome its own literals decide.

    Returns:
        Pairs of offending node and the phrase describing why it cannot fail.

    """
    found: list[tuple[ast.Assert | ast.Call, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assert, ast.Call)) or node in exempt:
            continue
        reason = _fixed_truth_reason(node.test) if isinstance(node, ast.Assert) else _unittest_reason(node)
        if reason is not None:
            found.append((node, reason))
    return found


def _unittest_reason(node: ast.Call) -> str | None:
    """Describe why a `unittest` assertion call cannot fail, if it cannot.

    Returns:
        The reason phrase, or None when the call is not a fixed-outcome assertion.

    """
    name = _called_method(node)
    # `msg=` is unittest's failure text and changes nothing about the outcome;
    # any other keyword means this is not the method we think it is.
    if name is None or any(kw.arg != _UNITTEST_MSG_KWARG for kw in node.keywords):
        return None
    args = node.args
    if name in _EQUALITY_METHODS and len(args) >= _EQUALITY_ARITY and _is_same_literal(args[0], args[1]):
        return f"`{_preview(args[0])}` is compared with an identical literal"
    if len(args) < 1:
        return None
    if name in _TRUTHY_ARG_METHODS:
        return _fixed_truth_reason(args[0])
    if name in _FALSY_ARG_METHODS and _is_always_falsy_literal(args[0]):
        return f"`{_preview(args[0])}` is a literal that is always falsy"
    return None


def _fixed_truth_reason(test: ast.expr) -> str | None:
    """Describe why `test` is always truthy, if it is.

    Returns:
        The reason phrase, or None when the value depends on the code.

    """
    if _constant_truth(test) is True:
        return f"`{_preview(test)}` is a constant truthy value"
    kind = _nonempty_container_kind(test)
    if kind is not None:
        return f"a non-empty {kind} display is truthy whatever it contains"
    if _is_identical_literal_comparison(test):
        return f"`{_preview(test)}` compares a literal with an identical literal"
    return None


def _constant_truth(node: ast.expr) -> bool | None:
    """Evaluate the truthiness of a scalar constant, `-1`, `+0` and `not 0` included.

    `not <falsy scalar constant>` is the spelling SARJ064 used to own; it arrived
    here with the literal-only tautologies. A `not` on anything the syntax cannot
    evaluate — a name, a call, a display — stays unknown, because `assert not x`
    is an ordinary assertion.

    Returns:
        The constant's truth value, or None when `node` is not a scalar constant.

    """
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, (ast.USub, ast.UAdd)):
            return _constant_truth(node.operand)
        if isinstance(node.op, ast.Not):
            operand_truth = _constant_truth(node.operand)
            return None if operand_truth is None else not operand_truth
    return None


def _nonempty_container_kind(node: ast.expr) -> str | None:
    """Name the container display kind when `node` is a provably non-empty one.

    A `*splat`/`**unpack` element makes emptiness a runtime question, so those
    are excluded — `assert [*items]` really can fail.

    Returns:
        "list"/"set"/"dict"/"tuple", or None.

    """
    if isinstance(node, ast.Dict):
        if not node.keys or any(key is None for key in node.keys):
            return None
        return _CONTAINER_KINDS[ast.Dict]
    if not isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return None
    if not node.elts or any(isinstance(elt, ast.Starred) for elt in node.elts):
        return None
    return _CONTAINER_KINDS[type(node)]


def _is_identical_literal_comparison(node: ast.expr) -> bool:
    """Report whether `node` compares one literal with a textually identical one.

    Single-operator comparisons only, and only `==`/`is`. Both operands must be
    literals: `assert i == i` and `assert x is x` are reflexivity tests on a
    real object and are the false positives this rule exists to avoid.

    Returns:
        True for `1 == 1`, `"a" is "a"`; False for `i == i`, `f(x) == f(x)`.

    """
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return False
    if not isinstance(node.ops[0], _SAMENESS_OPS):
        return False
    return _is_same_literal(node.left, node.comparators[0])


def _is_same_literal(left: ast.expr, right: ast.expr) -> bool:
    """Report whether both operands are literals with identical syntax.

    Returns:
        True when both are literals and unparse to the same source.

    """
    return _is_literal(left) and _is_literal(right) and ast.dump(left) == ast.dump(right)


def _is_literal(node: ast.expr) -> bool:
    """Report whether `node` is a literal built entirely from constants.

    An identifier, attribute, call or f-string is not — its value comes from
    somewhere the syntax cannot see, which is exactly what makes an assertion on
    it a real assertion.

    Returns:
        True for constants, negated numeric constants, and displays of literals.

    """
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp):
        # `-1` is a negation of a constant, not a constant; without this,
        # `assertEqual(-1, -1)` would slip through.
        return isinstance(node.op, (ast.USub, ast.UAdd)) and _is_literal(node.operand)
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return all(_is_literal(elt) for elt in node.elts)
    if isinstance(node, ast.Dict):
        return all(key is not None and _is_literal(key) for key in node.keys) and all(
            _is_literal(value) for value in node.values
        )
    return False


def _is_always_falsy_literal(node: ast.expr) -> bool:
    """Report whether `node` is a literal that is always falsy.

    Returns:
        True for `False`, `0`, `""`, `None` and empty displays.

    """
    if _constant_truth(node) is False:
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _called_method(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _preview(node: ast.expr) -> str:
    """Render `node` back to source, truncated so the message stays one line.

    Returns:
        The unparsed operand, elided past `_OPERAND_PREVIEW_CHARS`.

    """
    text = " ".join(ast.unparse(node).split())
    if len(text) > _OPERAND_PREVIEW_CHARS:
        return f"{text[:_OPERAND_PREVIEW_CHARS]}…"
    return text


def _message(node: ast.Assert | ast.Call, reason: str) -> str:
    """Compose the diagnostic, adding the message-slot hint where it applies.

    Returns:
        The full diagnostic message.

    """
    slid_into_message_slot = isinstance(node, ast.Assert) and node.msg is not None
    hint = (
        " The expression you meant to assert on is sitting in the assertion-message slot — move it into the condition."
        if slid_into_message_slot
        else " Assert on a value the code produced, or delete the test."
    )
    return f"This assertion can never fail: {reason}.{hint}"
