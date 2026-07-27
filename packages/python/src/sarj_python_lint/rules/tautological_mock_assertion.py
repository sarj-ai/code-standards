"""SARJ057: a test whose only assertion is the value it fed the mock verifies nothing.

```python
def test_prompt_config_awaits_pool_then_loads(monkeypatch):
    monkeypatch.setattr(main, "load_config_or_empty", AsyncMock(return_value="prompt-cfg"))
    result = await _load_prompt_config_after_pool(pool_task=done, global_prompt_service=Mock())
    assert result == "prompt-cfg"
```

The test's name promises it awaits the pool *and then* loads. Nothing in the body
checks either half: the sole assertion says the string handed to the stub came
back out of it. Nobody is told when the ordering breaks, when the pool task is
dropped, or when the service is never consulted — the assertion holds for every
one of those regressions. That is the shape this rule looks for, and only that
shape: a test in which **every** assertion is a mock echo and **nothing else**
is verified.

Fires when, inside one `test_*` function body, ALL of these hold:

* the body configures a stub value — `m.get.return_value = X`,
  `patch(..., return_value=X)`, `AsyncMock(side_effect=X)`, or a hand-rolled
  `monkeypatch.setattr(mod, "fn", lambda: X)`,
* the stubbed value is **non-trivial** (not `None`/`True`/`False`/`0`/`1`/`""`/
  `[]`/`{}`) — `return_value = None` followed by `assert result is None` pins a
  code path that genuinely could have returned something else,
* every `assert` in the function is a single `==`/`is` comparison whose one side
  is structurally identical to that stubbed value (compared by `ast.dump`, so
  dict/list/tuple literals match cheaply) — or is a bare read of
  `<mock>.return_value`,
* the other side of the comparison is the **whole** result (`result`,
  `svc.get(1)`, `await svc.get(1)`), not a piece of it,
* the stubbed value is mentioned exactly twice in the body: the stub and the
  assertion,
* and the function contains **no other verification at all** — no
  `mock.assert_called_with(...)`, no `pytest.raises`, no `self.assertEqual`, no
  project-local `_assert_*` helper.

**The guards are the rule, and the last one is most of it.** Measured over
22,388 collected test functions in bulbul, noura-be, django, fastapi and celery:
958 tests configure a stub in their own body, 866 with a non-trivial value, 462
of those also assert — yet only 44 assertions structurally compare against the
stubbed value at all. Narrowing those 44 to the ones that are genuinely
zero-value takes four separate guards and leaves 2. A version of this rule
without them would be wrong roughly four times in five.

Deliberately NOT flagged:

* **an assertion that reaches into the result**, whether it does so inline or
  through a local. `assert result.name == X` or
  `assert response.json()["data"]["url"] == X` asserts *where the value ended
  up*, which is behaviour the stub does not decide — the code could have put it
  in the wrong field, dropped it, or transformed it. The same is true written
  across two statements, so a local bound exactly once to an attribute or
  subscript expression is resolved back to it before the exemption is applied
  (`data = content["data"]["shop"][...]` / `assert data == external_auths`).
  A name the function binds more than once is left alone: the alias is then
  ambiguous and the rule does not guess. Measured over 19 repositories this
  costs one finding — saleor's
  `saleor/graphql/shop/tests/queries/test_shop.py:515`, a full GraphQL round
  trip through `user_api_client.post_graphql` whose parametrized
  `external_auths` list is stubbed onto `PluginsManager` and then compared
  against the serialized envelope — and it is a false positive; total 138 -> 137,
  with bulbul unchanged at 2 and noura-be at 0. 16 of the 44 structural
  matches are this shape and every one was a real assertion, including
  `bulbul/python/agent/tests/test_ivr_navigation.py:163`
  (`assert tool._last_send_time == post_send_sentinel` after patching
  `time.time` — it checks the debounce timestamp was recorded) and
  `bulbul/python/webserver/tests/public_api/test_calls.py:608`
  (`assert r.json()["data"]["recording_url"] == "https://signed.example/abc.mp4"`
  with a stubbed `object_store.sign`, driven through a FastAPI `TestClient` —
  a real end-to-end assertion about the serialized envelope),
* **a round trip.** `assert store.save(record) == record` is not a mock echo:
  the value is also handed to the code under test, so the comparison pins a
  passthrough the code could have broken. Detected by counting mentions —
  exactly two means stub-then-assert. Uses as the receiver of an attribute or
  subscript do not count towards it, because
  `participant.identity = "caller-1"` and `room.disconnect.assert_awaited()`
  configure or interrogate the double rather than feed it to the code,
* **a test that also verifies what the code did.** A `mock.assert_called_once_with(user_id)`
  next to the echo pins the arguments the code passed, and a
  `pytest.raises` pins a failure path; neither is decided by the stub, so the
  test is not zero-value even if one of its assertions is redundant. Also
  covers the *delegation* test, where the passthrough itself is the behaviour
  under test — `celery/t/unit/app/test_app.py:2075`
  (`test_acquire_connection_without_pool`: `assert result == mock_conn.return_value`
  next to `mock_conn.assert_called_once()`, checking that `pool=False` takes the
  non-pooled branch) and `celery/t/unit/backends/test_elasticsearch.py:922`
  (`test_decode_not_dict`) are exactly this, as is
  `fastapi/tests/test_tutorial/test_dependencies/test_tutorial007.py:23`, whose
  `dbsession_moock.close.assert_called_once()` checks the dependency closes the
  session. All three would otherwise be false positives, one of them in mature
  OSS,
* **a test with a real assertion alongside the echo.** Every assertion must be
  an echo. `bulbul/python/agent/tests/test_main_helpers.py:260`
  (`test_builds_request_and_returns_response`) opens with `assert result is
  sip_response` and then checks `request.sip_call_to` and
  `request.headers["X-S-CallId"]` off the captured call args — the echo is a
  redundant first line in a test that does real work,
* **`return_value = None` / `= []` / `= 0`** and the other trivial stubs, where
  the assertion usually distinguishes a real code path,
* an `==` comparison with a value the body never stubbed (a `parametrize`
  `expected` column, a fixture, a hand-built expectation) — only a structural
  match against the stubbed value counts,
* a chained or non-equality comparison (`a < b < c`, `x in y`), and any
  assertion that is not a comparison at all,
* a `test_*` nested inside another function, a non-collected module, and
  anything under `scripts/` — pytest runs none of them.

**Known limit: precedence claims.** A test that stubs two collaborators and
asserts the result equals *one* of them is asserting which source wins, not
echoing a stub — mlflow's
`tests/tracking/_model_registry/test_utils.py:172`
(`test_registry_uri_from_spark_session_overrides_databricks_default`) stubs both
`get_tracking_uri` and `_get_registry_uri_from_spark_session` and asserts the
Spark URI is the one that comes back. The rule reports it. No narrow predicate
separates it from a genuine echo: "two or more stubbed values exempts" was
measured over the 137 surviving findings and would silence 33 of them (24%),
most of which stub the same value twice or stub an unrelated collaborator, so
the cure is far worse than the disease. The shape is left firing and recorded
here.

Note that this standard's own ruff config bans `unittest.mock` outright, so the
`return_value` spelling is rare in the audited first-party code by construction;
the `monkeypatch.setattr(..., lambda: X)` spelling is the one it will meet most
often, and it is treated identically.
"""

from __future__ import annotations

import ast
from collections import Counter
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# The two `unittest.mock` knobs that decide what a stubbed call hands back. Both
# appear as assignment targets (`m.get.return_value = X`) and as keyword
# arguments (`patch(..., return_value=X)`, `AsyncMock(side_effect=X)`).
_MOCK_VALUE_ATTRS = frozenset({"return_value", "side_effect"})

# A call whose name starts with this verifies something in its own right:
# `mock.assert_called_once_with(...)`, `self.assertEqual(...)`, `_assert_shape(...)`.
_ASSERT_PREFIX = "assert"

# Verification spelled without the `assert` prefix.
_VERIFICATION_NAMES = frozenset({"raises", "warns", "deprecated_call", "fail"})

# Calls that swap a real callable for a stand-in, so a `lambda` handed to one is
# a hand-rolled `return_value` (`monkeypatch.setattr(mod, "fn", lambda: X)`).
_REPLACEMENT_INSTALLERS = frozenset({"setattr", "setitem", "patch", "object"})

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_TEST_PREFIX = "test_"

# pytest's default `python_files`. `is_test_path` is broader on purpose — it
# accepts everything under `tests/` — and a module pytest never imports as a
# test cannot hold a weak assertion.
_COLLECTED_SUFFIX = "_test.py"

# Manual CLI probes carry `test_*.py` names but are never collected.
_UNCOLLECTED_DIR_NAMES = frozenset({"scripts"})

# Expression shapes that stand for "the whole thing the code under test
# produced". `Attribute` (`result.name`) and `Subscript` (`result["id"]`) are
# deliberately absent: reaching into the result asserts where a value ended up,
# which is behaviour the stub does not decide.
_WHOLE_RESULT_NODES = (ast.Name, ast.Call, ast.Await)

# Exactly two: the stub setup and the assertion. A third mention means the value
# also flows into the call under test, making the comparison a round trip.
_EXPECTED_OCCURRENCES = 2

# `0`/`1` double as False/True, counts, and indexes; stubbing one and asserting
# on it is usually a real code-path check.
_TRIVIAL_NUMBERS = frozenset({0, 1})


class TautologicalMockAssertion(Rule):
    """A test whose every assertion echoes a value the test itself stubbed."""

    id: str = "tautological-mock-assertion"
    code: str = "SARJ057"
    description: str = "Test's only assertion compares against the value it configured the mock to return."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag tests that verify nothing but their own stub.

        Returns:
            One diagnostic per tautological test, sorted by position.

        """
        if not is_test_path(path) or not _is_collected_module(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    "this is the test's only assertion and it compares against the value the test itself "
                    "configured the mock to return, so it holds however the code under test behaves — it "
                    "verifies `unittest.mock`, not this codebase. Assert on what the code *did*: the "
                    "arguments it passed, the transformation it applied, or the effect it performed."
                ),
            )
            for node in _tautological_assertions(tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_collected_module(path: Path) -> bool:
    name = path.name
    collected = name.startswith(_TEST_PREFIX) or name.endswith(_COLLECTED_SUFFIX)
    return collected and not any(part in _UNCOLLECTED_DIR_NAMES for part in path.parts)


def _tautological_assertions(tree: ast.Module) -> list[ast.Assert]:
    hits: list[ast.Assert] = []
    for func in _collectible_tests(tree):
        hit = _tautology_in(func)
        if hit is not None:
            hits.append(hit)
    return hits


def _collectible_tests(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Collect the `test_*` functions pytest would actually run.

    Only module-level functions and methods of a class qualify; a `test_*`
    nested inside another function is a callback, not a test.

    Returns:
        The test functions, in source order.

    """
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    containers: list[ast.Module | ast.ClassDef] = [tree]
    while containers:
        for stmt in containers.pop().body:
            if isinstance(stmt, ast.ClassDef):
                containers.append(stmt)
            elif isinstance(stmt, _FUNC_NODES) and stmt.name.startswith(_TEST_PREFIX):
                found.append(stmt)
    found.sort(key=lambda n: (n.lineno, n.col_offset))
    return found


def _tautology_in(func: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Assert | None:
    """Decide whether every assertion in `func` merely echoes a stubbed value.

    Returns:
        The first tautological assertion, or None when the test verifies
        anything the code under test could get wrong.

    """
    asserts: list[ast.Assert] = []
    provided: dict[str, ast.expr] = {}
    receivers: set[int] = set()
    assigned: dict[str, ast.expr] = {}
    bindings: Counter[str] = Counter()
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            asserts.append(node)
        elif isinstance(node, ast.Assign):
            _record_attribute_stub(node, provided)
            _record_alias(node, assigned)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                bindings[node.id] += 1
        elif isinstance(node, ast.Attribute | ast.Subscript):
            receivers.add(id(node.value))
        elif isinstance(node, ast.Call):
            if _is_verification_call(node):
                return None
            _record_call_stubs(node, provided)
    if not asserts:
        return None

    aliases = {name: value for name, value in assigned.items() if bindings[name] == 1}
    signatures = {_signature(value) for value in provided.values()}
    matched: list[ast.Assert] = []
    for node in asserts:
        target = _echoed_operand(node, provided, signatures, aliases)
        if target is None or not _appears_only_at_the_stub(func, target, receivers):
            return None
        matched.append(node)
    return matched[0]


def _record_alias(node: ast.Assign, assigned: dict[str, ast.expr]) -> None:
    """Note that `x = <expr>` binds a local to an expression.

    Only plain-name targets are recorded — a tuple unpack binds a piece of the
    value, not the value. The caller then discards every name the function binds
    more than once, so what survives is an unambiguous alias.
    """
    for target in node.targets:
        if isinstance(target, ast.Name):
            assigned[target.id] = node.value


def _record_attribute_stub(node: ast.Assign, provided: dict[str, ast.expr]) -> None:
    if any(isinstance(target, ast.Attribute) and target.attr in _MOCK_VALUE_ATTRS for target in node.targets):
        _record(node.value, provided)


def _record_call_stubs(node: ast.Call, provided: dict[str, ast.expr]) -> None:
    for kw in node.keywords:
        if kw.arg in _MOCK_VALUE_ATTRS:
            _record(kw.value, provided)
    if _installs_a_replacement(node):
        for arg in node.args:
            if isinstance(arg, ast.Lambda):
                _record(arg.body, provided)


def _installs_a_replacement(node: ast.Call) -> bool:
    """Report whether this call swaps a real callable for a stand-in.

    `monkeypatch.setattr(mod, "fn", lambda: X)` and `patch("mod.fn", lambda: X)`
    are the mock-free spelling of `return_value=X`, and this standard's ruff
    config bans `unittest.mock`, so it is the spelling the rule meets most.

    Returns:
        True for `setattr`/`setitem`/`patch`-shaped installers.

    """
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
    return name in _REPLACEMENT_INSTALLERS


def _record(value: ast.expr, provided: dict[str, ast.expr]) -> None:
    if _is_trivial(value) or not _signature(value):
        return
    provided.setdefault(ast.dump(value), value)


def _is_trivial(value: ast.expr) -> bool:
    """Report whether a stubbed value is too weak to build a tautology on.

    `return_value = None` followed by `assert result is None` genuinely pins a
    code path that could have returned something; so does an empty list.

    Returns:
        True for None, bools, 0/1, empty strings and empty containers.

    """
    if isinstance(value, ast.Constant):
        literal = value.value
        if literal is None or isinstance(literal, bool):
            return True
        if isinstance(literal, int | float) and literal in _TRIVIAL_NUMBERS:
            return True
        return isinstance(literal, str | bytes) and not literal
    if isinstance(value, ast.List | ast.Tuple | ast.Set):
        return not value.elts
    if isinstance(value, ast.Dict):
        return not value.keys
    return False


def _echoed_operand(
    node: ast.Assert,
    provided: dict[str, ast.expr],
    signatures: set[str],
    aliases: dict[str, ast.expr],
) -> ast.expr | None:
    """Find the operand of `node` that the test itself stubbed.

    Returns:
        The stubbed operand, or None when the assertion checks something else.

    """
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    if not isinstance(test.ops[0], ast.Eq | ast.Is):
        return None
    left, right = test.left, test.comparators[0]
    for value, other in ((right, left), (left, right)):
        if not _is_stubbed(value, provided, signatures):
            continue
        if not isinstance(other, _WHOLE_RESULT_NODES) or _reaches_into_the_result(other, aliases):
            continue
        if not _is_stubbed(other, provided, signatures):
            return value
    return None


def _reaches_into_the_result(node: ast.expr, aliases: dict[str, ast.expr]) -> bool:
    """Report whether `node` is a local bound to a piece of something bigger.

    `data = content["data"]["shop"]["availableExternalAuthentications"]` followed by
    `assert data == external_auths` is the subscript exemption written across two
    statements — the assertion still says *where the value ended up*, which is
    behaviour the stub does not decide. Resolving the alias is what lets the
    exemption see it (saleor
    `saleor/graphql/shop/tests/queries/test_shop.py:515`, a full GraphQL round
    trip through `user_api_client.post_graphql`).

    Returns:
        True when following single-assignment aliases lands on an attribute or
        subscript read.

    """
    seen: set[str] = set()
    while isinstance(node, ast.Name) and node.id in aliases and node.id not in seen:
        seen.add(node.id)
        node = aliases[node.id]
    return isinstance(node, ast.Attribute | ast.Subscript)


def _is_stubbed(node: ast.expr, provided: dict[str, ast.expr], signatures: set[str]) -> bool:
    # The signature check is a cheap pre-filter so the vast majority of
    # assertions in a suite never pay for an `ast.dump`.
    if _reads_a_stub_attribute(node):
        return True
    return _signature(node) in signatures and ast.dump(node) in provided


def _reads_a_stub_attribute(node: ast.expr) -> bool:
    # `assert result == client.fetch.return_value` — the mock hands the test the
    # very object it hands the code under test.
    return isinstance(node, ast.Attribute) and node.attr in _MOCK_VALUE_ATTRS


def _appears_only_at_the_stub(func: ast.AST, target: ast.expr, receivers: set[int]) -> bool:
    """Report whether `target` occurs only twice: the stub and the assertion.

    A third occurrence means the value is also handed to the code under test —
    `assert store.save(record) == record` is a round trip, and the stub is not
    the sole reason the comparison holds. Uses as the receiver of an attribute
    or subscript (`participant.identity = "caller-1"`,
    `room.disconnect.assert_awaited_once()`) do not count: those configure or
    interrogate the double, they do not feed it to the code under test.

    Returns:
        True when the value is mentioned exactly twice, or is a `.return_value`
        read, which has no separate setup site to count.

    """
    if _reads_a_stub_attribute(target):
        return True
    signature = _signature(target)
    dumped = ast.dump(target)
    count = 0
    for node in ast.walk(func):
        if not isinstance(node, ast.expr) or id(node) in receivers or not _is_read(node):
            continue
        if _signature(node) == signature and ast.dump(node) == dumped:
            count += 1
            if count > _EXPECTED_OCCURRENCES:
                return False
    return count == _EXPECTED_OCCURRENCES


def _is_read(node: ast.expr) -> bool:
    if isinstance(node, ast.Name | ast.Attribute | ast.Subscript | ast.List | ast.Tuple | ast.Starred):
        return isinstance(node.ctx, ast.Load)
    return True


def _signature(node: ast.expr) -> str:
    """Summarize `node` cheaply so full `ast.dump` comparisons stay rare.

    Returns:
        A short discriminator, or "" for expression kinds this rule ignores.

    """
    if isinstance(node, ast.Name):
        return f"N:{node.id}"
    if isinstance(node, ast.Constant):
        return f"C:{node.value!r}"
    if isinstance(node, ast.Attribute):
        return f"A:{node.attr}"
    if isinstance(node, ast.Dict):
        return f"D:{len(node.keys)}"
    if isinstance(node, ast.List):
        return f"L:{len(node.elts)}"
    if isinstance(node, ast.Tuple):
        return f"T:{len(node.elts)}"
    if isinstance(node, ast.Set):
        return f"S:{len(node.elts)}"
    if isinstance(node, ast.Call):
        return f"K:{len(node.args)}"
    # `-1` parses as a unary minus over a constant, not as a negative literal.
    if isinstance(node, ast.UnaryOp):
        return f"U:{type(node.op).__name__}"
    return ""


def _is_verification_call(node: ast.Call) -> bool:
    """Report whether this call checks something the stub does not decide.

    `mock.assert_called_once_with(user_id)` pins the arguments the code passed,
    `pytest.raises(ValueError)` pins a failure path, `self.assertEqual(a, b)`
    and a project-local `_assert_shape(result)` pin whatever they were written
    to pin. A test carrying any of them is not zero-value, even if one of its
    assertions is a redundant echo. Bare call-count checks
    (`mock.assert_called_once()`) count too: on the audited corpora they mark
    *delegation* tests, where the passthrough is itself the behaviour under
    test, and treating them as noise produced false positives in celery and
    fastapi.

    Returns:
        True when the call verifies behaviour independently of the stub value.

    """
    func = node.func
    if isinstance(func, ast.Attribute):
        name = func.attr
    elif isinstance(func, ast.Name):
        name = func.id
    else:
        return False
    return name.lstrip("_").startswith(_ASSERT_PREFIX) or name in _VERIFICATION_NAMES
