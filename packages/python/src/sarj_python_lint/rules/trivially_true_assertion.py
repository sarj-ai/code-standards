"""SARJ061: an assertion whose outcome the test itself already decided.

A test earns its keep by being able to go red. An assertion whose truth is
settled by the test's own source text cannot, so it adds a line to the coverage
report and nothing to the suite. The dominant real-world spelling is not
`assert True` — it is reading a constructor's keyword argument straight back
out::

    payload = EncryptedPayload(
        operation_key_id="key-123",
        jws_signature="sig-456",
        encrypted_payload="encrypted-data",
    )

    assert payload.operation_key_id == "key-123"
    assert payload.jws_signature == "sig-456"

Nothing in those three lines can fail unless pydantic stops assigning fields.
The test is named `test_encrypted_payload_fields`
(`noura-be/python/noura/tests/test_vb_auth_generic.py:372`) and it verifies the
language, not the model.

**What ruff already owns, and is therefore NOT duplicated here.** Every shape
below was checked against `ruff --select ALL --preview`, the configuration this
standard ships:

* `assert False` — B011 (`assert-false`) and PT015 (`pytest-assert-always-false`),
* `assert "x"` — PLW0129 (`assert-on-string-literal`),
* `assert (1, 2)` — F631 (`assert-tuple`),
* `assert 1 == 1`, `assert 2 > 1`, `assert True is True` — PLR0133
  (`comparison-of-constant`),
* `assert x == x`, `assert m is m` — PLR0124 (`comparison-with-itself`). This is
  the brief's "self-comparison of a mock" shape in full; it was implemented,
  found to be a straight duplicate, and **dropped**,
* `assert "a" in ["a", "b"]` — PLR6201 (`literal-membership`) fires on it, and
  an implementation of the always-true membership check found **zero**
  occurrences across all five corpora, so it too was **dropped**.

What survives is the set ruff has no rule for: a truthy non-string constant, a
non-empty collection display, and the two shapes that need to see what the test
constructed a line earlier.

Fires when any of these hold:

* the assertion's condition is a constant that is truthy and is not a string —
  `assert True`, `assert 1`, `assert ...` — or `not` applied to a falsy
  constant, or a non-empty list/set/dict display, which is truthy by being
  written non-empty,
* a local name is bound exactly once to `SomeClass(..., field=<literal>)` and
  the test then asserts `name.field == <structurally identical literal>` (or
  `is`, the house spelling for a boolean field),
* a local name is bound exactly once to `SomeClass(...)` and the test then
  asserts `isinstance(name, SomeClass)`.

Corpus evidence — 6,155 Python files across bulbul, noura-be, django, fastapi
and celery, containing roughly 25,500 bare `assert` statements. 28 findings:
bulbul 17, noura-be 6, celery 5, django 0, fastapi 0. django's suite is
`unittest`-style (70 bare asserts in 2,927 files), so zero there is arithmetic,
not silence; fastapi's 4,828 bare asserts are almost all about an HTTP response
the test did not construct, and zero findings on that population is the
strongest evidence the shape is targeted. Two of the 28 are false positives
(celery's `Bunch`, below) — a 7.1% rate on the full finding set. The
keyword-echo shape carries 27 of the 28; `isinstance` carries 1; the constant
shape earned **no** true positive in any corpus and is retained only because
`assert True` is the canonical LLM coverage-theatre marker, is a genuine gap in
ruff (which covers only `assert False`), and costs one expression test.

Deliberately NOT flagged:

* **anything but a class constructor.** The keyword-echo shape was originally
  written for any call, and 12 of the first 49 findings — a quarter — were
  functions whose *job* is to map their arguments onto a result, where the
  pass-through is exactly the behaviour under test: noura-be's
  `make_settings(monkeypatch, ENV="staging", ...)` then
  `assert settings.ENV == "staging"` reads an environment variable back through
  pydantic-settings (`noura/tests/test_core_config.py:52`),
  `service.get_onboarding_error_details(limit=25, offset=5)` then
  `assert result.limit == 25` checks a service echoes pagination into its
  response envelope (`dashboard/tests/test_bigquery_inline_service.py:534`),
  `collector.get_analytics(duration_ms=1234)`
  (`voice/tests/test_voice_services.py:371`),
  `factory.create_client(language="ar")`
  (`common/tests/test_vb_onboarding_client.py:638`), celery's
  `event.get_exchange(conn, name='custom')`
  (`t/unit/events/test_events.py:540`), and bulbul's `_worker_options(...)`
  (`agent/tests/test_main_wiring.py:53`) and `create_global_variables(...)`
  (`bulbul/tests/unit/test_formatter.py:212`). Only a callee whose final name
  component is capitalised — `Foo(...)`, `mod.Foo(...)`, `self.Backend(...)` —
  is treated as a constructor,
* **collaborator classes**, whose `__init__` normalises the configuration it is
  handed. celery's cache backends take `expires=` and run it through
  `prepare_expires`, so `CacheBackend(backend='memory://', expires=10)` then
  `assert tb.expires == 10` is a real coercion test named `test_expires_as_int`
  (`t/unit/backends/test_cache.py:126`, and the same shape at
  `test_couchbase.py:130` and `test_redis.py:1172`). A class whose name ends in
  `Backend`, `Client`, `Service`, `Store` and the like is a thing that does work,
  not a record that holds fields,
* **a field the same module proves is transformed.** bulbul's
  `GeminiLLMSettings` rewrites `model="lite"` to `"flash-lite-3.1"`; three
  functions down, `test_valid_model_unchanged` constructs it with
  `model="flash"` and asserts `settings.model == "flash"`
  (`bulbul/tests/unit/test_gemini_settings.py:17`). That assertion *can* fail —
  it is the negative half of a validator test — and only the sibling test four
  lines up reveals it. So when any construction of the same class in the same
  module asserts a field against a literal **different** from the one it was
  given, that class's field is known to coerce and every finding on it is
  dropped. The guard also clears celery's `CouchbaseBackend(expires=None)` then
  `assert b.expires == 10`,
* **dunder attributes.** `Proxy(real, __doc__='foo')` then
  `assert x.__doc__ == 'foo'` (celery `t/unit/utils/test_local.py:31`) is a real
  test: a lazy proxy resolving `__doc__` goes through descriptor machinery, not
  plain assignment,
* **`assert True` as one arm of a hand-rolled branch check.** celery writes
  `if <condition>: assert True; else: assert False`
  (`t/unit/concurrency/test_prefork.py:429`) — ugly, but the pair can fail, and
  it was the *only* `assert True` in all five corpora. A constant assertion
  whose sibling `if` branch always fails or raises is exempt,
* **an `isinstance` assertion that narrows for a later one.** basedpyright
  strict needs `assert isinstance(x, T)` to prove the assertions after it are
  well-typed; deleting it breaks the build. Any later assertion in the same
  function that mentions the name suppresses the finding, which is why celery's
  `test_from_message` (`t/unit/worker/test_request.py:1525`) is silent while
  `test_from_message_empty_args` twelve lines down, whose body is a construction
  and a bare `isinstance`, is not,
* **anything that touches the local between construction and assertion.** The
  name must be bound exactly once, must not be a parameter or declared
  `global`/`nonlocal`, and every read of it must be an attribute access inside
  an `assert`. Passing it to a function, calling a method on it, or simply
  reading it into another variable all disqualify it, because the object may no
  longer hold what the constructor was given,
* **a literal that changed shape.** Structural identity, not runtime equality:
  `Model(count=0)` then `assert m.count is False` compares equal at runtime but
  asserts a conversion, and `Email("A@B.com")` then
  `assert e.value == "a@b.com"` tests coercion. Neither fires. Nor does a
  differing attribute name — a pydantic alias or a derived field
  (`Model(name="A B")` then `assert m.slug == "a-b"`) — nor a round trip through
  serialisation (`assert Model(**d).model_dump() == d`), which binds no name at
  all,
* **a module pytest never collects.** `is_test_path` accepts everything under
  `tests/`; black keeps formatter fixtures in `tests/data/cases/` whose content
  is arbitrary Python, and `scripts/test_*.py` holds manual CLI probes.

Known residual false positive: celery's `Bunch(foo='foo', bar=2)` then
`assert x.foo == 'foo'` (`t/unit/utils/test_objects.py:8`). `Bunch` is a
kwargs-to-attributes bag, so storing keyword arguments *is* its whole behaviour
and the tautology is the test. Two findings; no syntactic signal distinguishes
it from the models above, and `# sarj-noqa: SARJ061` is the intended escape.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_TEST_PREFIX = "test_"

# pytest's default `python_files`. `is_test_path` is broader on purpose.
_COLLECTED_SUFFIX = "_test.py"

# Manual CLI probes carry `test_*.py` names but are never collected.
_UNCOLLECTED_DIR_NAMES = frozenset({"scripts"})

_ISINSTANCE = "isinstance"

_ISINSTANCE_ARITY = 2

_DUNDER_PREFIX = "__"

# Displays that are truthy purely by being written non-empty. `ast.Tuple` is
# absent because ruff's F631 (`assert-tuple`) already owns it.
_TRUTHY_DISPLAYS = (ast.List, ast.Set)

# Class-name endings that mark a collaborator rather than a record. Such a class
# does work in `__init__` — celery's cache backends run `expires=` through
# `prepare_expires` — so reading a constructor argument back out of one is a
# coercion test, not a tautology. `Backend` and `Client` are the endings the
# corpus actually produced; the rest are the same idea, spelled differently.
_COLLABORATOR_SUFFIXES = (
    "backend",
    "client",
    "service",
    "manager",
    "handler",
    "server",
    "session",
    "pool",
    "engine",
    "runner",
    "worker",
    "store",
    "repository",
    "factory",
    "builder",
    "adapter",
    "connection",
    "transport",
)

# Calls that end a branch in failure, so a sibling `assert True` is a marker for
# the branch that did not fail rather than an assertion in its own right.
_FAILING_CALL_NAMES = frozenset({"fail", "exit"})

# `assert result.passed is False` is the pytest house spelling for a boolean
# field, and it is the same tautology as `== False`. A non-singleton `is`
# comparison is ruff's F632 and stays that rule's problem.
_ECHO_OPS = (ast.Eq, ast.Is)

_CONSTANT_MESSAGE = (
    "this assertion's condition is a constant, so it passes no matter what the code under test does — "
    "it adds a covered line and nothing else. Assert on a value the code produced, or delete the test"
)

_KWARG_MESSAGE = (
    "this reads back the literal the test just handed the constructor, so it can only fail if attribute "
    "assignment stops working. Assert on something the constructor derived, or drop the assertion"
)

_ISINSTANCE_MESSAGE = (
    "the value was produced by calling this very class a line above, so the `isinstance` check pins the "
    "language rather than the code. Assert on the object's state instead, or drop the assertion"
)


@dataclass(frozen=True, slots=True)
class _KwargEcho:
    """One `assert name.field == <literal>` paired with how the name was built."""

    node: ast.Assert
    field: tuple[str, str]
    echoes: bool


@dataclass(slots=True)
class _Scope:
    """Everything one function body does with its local names."""

    asserts: list[ast.Assert]
    loads: dict[str, list[ast.Name]]
    binds: dict[str, int]
    calls: dict[str, ast.Call]
    shadowed: set[str]


@dataclass(frozen=True, slots=True)
class _Index:
    """One traversal's worth of facts about the module."""

    parents: dict[int, ast.AST]
    asserts: list[ast.Assert]
    scopes: list[_Scope]


class TriviallyTrueAssertion(Rule):
    """An assertion whose outcome is fixed by the test's own source text."""

    id: str = "trivially-true-assertion"
    code: str = "SARJ061"
    description: str = "Assertion cannot fail — its outcome is decided by the test's own literals, not by the code."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag assertions whose truth is settled by the test source itself.

        Returns:
            One diagnostic per unfalsifiable assertion, sorted by position.

        """
        if not is_test_path(path) or not _is_collected_module(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        index = _index_module(tree)
        findings: dict[int, tuple[ast.Assert, str]] = {}
        for node in index.asserts:
            if _is_always_true_constant(node.test) and not _is_branch_marker(node, index.parents):
                findings[id(node)] = (node, _CONSTANT_MESSAGE)
        for node, message in _construction_findings(index):
            _ = findings.setdefault(id(node), (node, message))

        diags = [
            Diagnostic(path=path, line=node.lineno, col=node.col_offset + 1, code=self.code, message=message)
            for node, message in findings.values()
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_collected_module(path: Path) -> bool:
    name = path.name
    matches_python_files = name.startswith(_TEST_PREFIX) or name.endswith(_COLLECTED_SUFFIX)
    return matches_python_files and not any(part in _UNCOLLECTED_DIR_NAMES for part in path.parts)


def _index_module(tree: ast.Module) -> _Index:
    """Walk the module once, recording everything all three shapes need.

    The perf gate is per rule, so the parent links, the assertion list and the
    per-function name bookkeeping all come out of a single descent rather than
    four `ast.walk` passes.

    Names are attributed to the **outermost** enclosing function, never the
    nested one. A closure that mentions a local therefore still disqualifies it,
    which is the conservative direction.

    Returns:
        The collected facts.

    """
    parents: dict[int, ast.AST] = {}
    asserts: list[ast.Assert] = []
    scopes: list[_Scope] = []
    stack: list[tuple[ast.AST, _Scope | None]] = [(tree, None)]
    while stack:
        node, scope = stack.pop()
        if scope is None and isinstance(node, _FUNC_NODES):
            scope = _Scope(asserts=[], loads={}, binds={}, calls={}, shadowed=set())
            scopes.append(scope)
        if isinstance(node, ast.Assert):
            asserts.append(node)
            if scope is not None:
                scope.asserts.append(node)
        elif scope is not None:
            _record_local(node, scope)
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
            stack.append((child, scope))
    return _Index(parents=parents, asserts=asserts, scopes=scopes)


def _record_local(node: ast.AST, scope: _Scope) -> None:
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load):
            scope.loads.setdefault(node.id, []).append(node)
        else:
            scope.binds[node.id] = scope.binds.get(node.id, 0) + 1
    elif isinstance(node, ast.arg):
        scope.shadowed.add(node.arg)
    elif isinstance(node, (ast.Global, ast.Nonlocal)):
        scope.shadowed.update(node.names)
    elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.value, ast.Call):
        target = node.targets[0]
        if isinstance(target, ast.Name):
            scope.calls[target.id] = node.value


# --------------------------------------------------------------------------- #
# Shape 1: the condition is a constant.                                        #
# --------------------------------------------------------------------------- #


def _is_always_true_constant(test: ast.expr) -> bool:
    if isinstance(test, ast.Constant):
        return _is_truthy_literal(test.value)
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return isinstance(test.operand, ast.Constant) and not test.operand.value
    if isinstance(test, _TRUTHY_DISPLAYS):
        return bool(test.elts) and not any(isinstance(elt, ast.Starred) for elt in test.elts)
    # `{**mapping}` can still come out empty, so a `None` key disqualifies.
    return isinstance(test, ast.Dict) and bool(test.keys) and all(key is not None for key in test.keys)


def _is_truthy_literal(value: object) -> bool:
    # `assert "x"` is ruff's PLW0129 and `assert None` fails loudly every run;
    # neither is this rule's business.
    if value is None or isinstance(value, str):
        return False
    return bool(value)


def _is_branch_marker(node: ast.Assert, parents: dict[int, ast.AST]) -> bool:
    """Report whether the constant assertion is one arm of a hand-rolled check.

    `if ok: assert True` / `else: assert False` is a clumsy but genuine
    verification: taken together the two arms can fail.

    Returns:
        True when a sibling branch of an enclosing `if` always fails.

    """
    current: ast.AST = node
    parent = parents.get(id(current))
    while parent is not None:
        if isinstance(parent, ast.If):
            siblings = parent.orelse if any(stmt is current for stmt in parent.body) else parent.body
            if any(_always_fails(stmt) for stmt in siblings):
                return True
        current = parent
        parent = parents.get(id(current))
    return False


def _always_fails(stmt: ast.stmt) -> bool:
    for node in ast.walk(stmt):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Assert) and isinstance(node.test, ast.Constant) and not node.test.value:
            return True
        if isinstance(node, ast.Call) and _called_name(node.func) in _FAILING_CALL_NAMES:
            return True
    return False


def _called_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


# --------------------------------------------------------------------------- #
# Shapes 2 and 3: what the test constructed a line earlier.                    #
# --------------------------------------------------------------------------- #


def _construction_findings(index: _Index) -> list[tuple[ast.Assert, str]]:
    """Find assertions that only read back what the test handed a constructor.

    Resolved module-wide rather than per function, because a sibling test is
    what reveals that a field coerces.

    Returns:
        Pairs of assertion node and message.

    """
    echoes: list[_KwargEcho] = []
    hits: list[tuple[ast.Assert, str]] = []
    for scope in index.scopes:
        if not scope.asserts or not scope.calls:
            continue
        constructed = _constructed_locals(scope, index.parents)
        if not constructed:
            continue
        for node in scope.asserts:
            echo = _kwarg_echo(node, constructed)
            if echo is not None:
                echoes.append(echo)
            elif _is_isinstance_echo(node, constructed, scope.asserts):
                hits.append((node, _ISINSTANCE_MESSAGE))

    coercing = {echo.field for echo in echoes if not echo.echoes}
    hits.extend((echo.node, _KWARG_MESSAGE) for echo in echoes if echo.echoes and echo.field not in coercing)
    return hits


def _constructed_locals(scope: _Scope, parents: dict[int, ast.AST]) -> dict[str, ast.Call]:
    """Keep the locals bound exactly once to a call and never touched since.

    Any other mention of the name — a rebind, a `del`, being passed to a
    function, having a method called on it, or simply being read outside an
    assertion — disqualifies it, because the object may no longer hold what the
    constructor was given.

    Returns:
        Name to the call that produced it.

    """
    return {
        name: call
        for name, call in scope.calls.items()
        if name not in scope.shadowed
        and scope.binds.get(name) == 1
        and all(_is_assertion_read(load, parents) for load in scope.loads.get(name, []))
    }


def _is_assertion_read(node: ast.Name, parents: dict[int, ast.AST]) -> bool:
    """Report whether this mention of the name only reads it inside an assertion.

    Returns:
        True for `assert x.attr ...` and `assert isinstance(x, ...)`; False for
        every other mention, a method call included — that one may mutate.

    """
    parent = parents.get(id(node))
    if isinstance(parent, ast.Attribute):
        grandparent = parents.get(id(parent))
        if isinstance(grandparent, ast.Call) and grandparent.func is parent:
            return False
        return _under_assert(parent, parents)
    if isinstance(parent, ast.Call) and _is_isinstance_call(parent) and parent.args and parent.args[0] is node:
        return _under_assert(parent, parents)
    return False


def _under_assert(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.Assert):
            return True
        current = parents.get(id(current))
    return False


def _is_isinstance_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == _ISINSTANCE


def _constructor_name(call: ast.Call) -> str | None:
    """Name the class this call instantiates, if it plausibly is one.

    A lowercase callee is a function, and a function that maps its arguments
    onto a result is doing the work the test is there to check.

    Returns:
        The capitalised final name component, or None.

    """
    name = _called_name(call.func)
    if name is None or not name[:1].isupper():
        return None
    lowered = name.lower()
    return None if lowered.endswith(_COLLABORATOR_SUFFIXES) else name


def _kwarg_echo(node: ast.Assert, constructed: dict[str, ast.Call]) -> _KwargEcho | None:
    """Pair `x = C(field=<literal>)` with a later `assert x.field == <literal>`.

    The result records whether the two literals match; a mismatch is the
    evidence that `C.field` coerces, which suppresses the matches elsewhere.

    Returns:
        The pairing, or None when this assertion is not of that shape.

    """
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], _ECHO_OPS):
        return None
    left, right = test.left, test.comparators[0]
    for attribute, literal in ((left, right), (right, left)):
        if not isinstance(attribute, ast.Attribute) or not isinstance(attribute.value, ast.Name):
            continue
        if attribute.attr.startswith(_DUNDER_PREFIX):
            continue
        call = constructed.get(attribute.value.id)
        if call is None or node.lineno <= call.lineno:
            continue
        name = _constructor_name(call)
        if name is None or not _is_pure_literal(literal):
            continue
        for keyword in call.keywords:
            if keyword.arg == attribute.attr and _is_pure_literal(keyword.value):
                echoes = ast.dump(keyword.value) == ast.dump(literal)
                return _KwargEcho(node=node, field=(name, attribute.attr), echoes=echoes)
    return None


def _is_pure_literal(node: ast.expr) -> bool:
    """Report whether `node` is a literal built entirely out of source text.

    Structural identity of two such literals, rather than runtime equality, is
    what makes the echo check safe: `0` and `False` compare equal but a test
    writing one and reading back the other asserts a conversion.

    Returns:
        True when no name lookup or call is involved in evaluating it.

    """
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _is_pure_literal(node.operand)
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return all(_is_pure_literal(elt) for elt in node.elts)
    if isinstance(node, ast.Dict):
        keys_ok = all(key is not None and _is_pure_literal(key) for key in node.keys)
        return keys_ok and all(_is_pure_literal(value) for value in node.values)
    return False


def _is_isinstance_echo(node: ast.Assert, constructed: dict[str, ast.Call], asserts: list[ast.Assert]) -> bool:
    """Detect `x = Foo(...)` followed by `assert isinstance(x, Foo)`.

    The class expression must be the callee itself: `x = Foo.build()` then
    `assert isinstance(x, Foo)` checks what a factory returns, which is real.

    Returns:
        True when the check restates the constructor that was just called.

    """
    test = node.test
    if not isinstance(test, ast.Call) or not _is_isinstance_call(test) or len(test.args) != _ISINSTANCE_ARITY:
        return False
    target, cls = test.args
    if not isinstance(target, ast.Name):
        return False
    call = constructed.get(target.id)
    if call is None or node.lineno <= call.lineno or ast.dump(call.func) != ast.dump(cls):
        return False
    return not _narrows_for_a_later_assertion(node, target.id, asserts)


def _narrows_for_a_later_assertion(node: ast.Assert, name: str, asserts: list[ast.Assert]) -> bool:
    """Report whether a following assertion uses the name this one narrows.

    `assert isinstance(x, T)` ahead of real assertions on `x` is the idiom a
    strict type checker requires to prove the later reads are well-typed.
    Removing it breaks the build, so it is never a finding.

    Returns:
        True when a later assertion in the same function mentions `name`.

    """
    for other in asserts:
        if other.lineno <= node.lineno:
            continue
        if any(isinstance(child, ast.Name) and child.id == name for child in ast.walk(other)):
            return True
    return False
