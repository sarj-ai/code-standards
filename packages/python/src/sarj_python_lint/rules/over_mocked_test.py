"""SARJ059: a test that substitutes six collaborators exercises the mock wiring, not the code.

Past a certain ratio the system under test is gone. Every collaborator answers
whatever the test told it to answer, so the assertions can only re-read the
script the test itself wrote: `mock_a.assert_called_once_with(...)` proves the
test called the test. Such a test goes green when the real collaborators change
shape, when the call order that mattered is wrong, and when the integration it
is named after has never worked. It is also the most expensive kind of test to
change, because every refactor of the real code invalidates the whole scaffold.

The remedy is a real dependency: a test database, an in-process app, `respx`
for HTTP, a hand-rolled fake implementing the ABC — with a double only at the
true external boundary (the payment provider, the LLM, the telephony vendor).
This is already the house position: the shared strict ruff config bans
`unittest.mock.Mock`/`MagicMock`/`AsyncMock`/`patch` and `pytest_mock` outright
via `flake8-tidy-imports`, so every mock in the audited repos already carries an
inline `# noqa: TID251 — <reason>`. That ban is per import; it cannot see that
six separately-justified doubles have added up to a test with no subject. This
rule measures the sum.

WHAT COUNTS AS ONE SUBSTITUTION
-------------------------------

Per collected test function, the **distinct collaborators** replaced:

* `@patch(...)`, `@patch.object(...)`, `@patch.multiple(...)` decorators on the
  test itself — `patch.multiple` expands to one target per replaced attribute
  rather than being read as a single opaque decorator, so its attributes are
  filtered and de-duplicated exactly like separately spelled `@patch`es,
* `patch(...)` / `patch.object(...)` / `mocker.patch(...)` /
  `monkeypatch.setattr(...)` anywhere in the body, `with` blocks included,
* `Mock()` / `MagicMock()` / `AsyncMock()` / `create_autospec()` bound to a
  name,
* mock-shaped fixture parameters — `mocker`, `mock_*`, `*_mock`, `*_mocks`.

A collaborator is an **object, not one of its methods**. Two reductions make
that true, and both were forced by the corpus:

* a dotted patch target loses its last segment, so `patch("os.fork")`,
  `patch("os.setsid")` and `patch("os.dup2")` are one substituted collaborator —
  the OS. Without this, `celery/t/unit/utils/test_platforms.py:467`
  (`test_open`, eleven `@patch`es of `os.*` around a `DaemonContext`) scored 14
  and `:220` (`test_with_uid`) scored 10, and both are *correct* code: those
  syscalls are the true external boundary this rule tells you to mock. They now
  score 5 and 3 and never fire,
* an attribute chain assigned a double collapses to its root, because
  `ctx.api.room.delete_room = AsyncMock()` does not add a collaborator — it
  fills in one more corner of the double already bound to `ctx`. Without this,
  `bulbul/agent/tests/test_main_helpers.py:138`
  (`test_timeout_marks_call_failed_with_no_answer`) scored 6 for building out a
  single `mock.Mock(spec=JobContext)` in six statements, while using a **real**
  `PsqlCallStore` against a real database — the exact test this rule wants
  people to write. Five of its sibling tests scored 6 the same way. It now
  scores 1. `self`/`cls` is the exception: it is the test case, not a double, so
  `self.client` and `self.session` stay two collaborators.

MEASURED DISTRIBUTION, AND WHERE THE THRESHOLD CAME FROM
--------------------------------------------------------

Distinct collaborators per collected test function, whole corpora:

    corpus      tests      0      1    2   3   4   5  6  7  8
    bulbul      4,279  3,989    184   78  18   7   1  2  -  -
    noura-be    2,861  2,593    264    4   -   -   -  -  -  -
    django     18,044 17,643    351   41   7   -   2  -  -  -
    fastapi     2,290  2,260     27    2   -   1   -  -  -  -
    celery      3,204  2,162    684  224  74  35  15  6  3  1
    ALL        30,678 28,647  1,510  349  99  43  18  8  3  1

93.4% of tests substitute nothing at all, and 99.96% stay at five or below. The
rule fires **above five**, which is the 99.96th percentile: 12 findings in
30,678 tests (0.04%) — celery 10, bulbul 2, django 0, fastapi 0, noura-be 0.
Firing above four would add 18 more, including django's
`tests/utils_tests/test_autoreload.py:404` (two patches plus three `MagicMock()`
arguments to `start_django` — an ordinary unit test) and celery's
`t/unit/security/test_certificate.py:84`; five is where honest tests still live.
Firing above six would leave zero findings in either audited repo.

All 12 findings were read and classified as true positives. The two in bulbul
are `agent/tests/test_collect_digits_tool.py:598` (mock session + mock room +
mock job context, plus patches of `Agent.session`, `get_job_context` and
LiveKit's `GetDtmfTask.on_exit` — the whole LiveKit surface is a double) and
`agent/tests/test_agent_tools.py:662` (four mock fixtures plus `mock_trunk`,
`mock_agent`, and a patched transfer strategy). Celery's worst,
`t/unit/test_loops.py:9`, opens with eight bare `Mock()`s named `obj`,
`connection`, `consumer`, `blueprint`, `hub`, `qos`, `heartbeat` and `clock`,
then asserts that `synloop` calls them.

DELIBERATELY NOT COUNTED
------------------------

* **`monkeypatch.setenv` / `delenv`.** That is the environment, not a
  collaborator. Only `monkeypatch.setattr` counts. `setitem`/`delitem` (editing
  a settings dict), `chdir` and `syspath_prepend` are likewise process state.
* **`patch.dict(...)`.** Its whole purpose is `os.environ` and settings
  mappings; django alone uses `@mock.patch.dict(os.environ, ...)` as a class
  decorator on the very tests this rule looks at.
* **Test-infrastructure knobs, by target name.** A target naming the
  environment, configuration, logging, the clock, or the retry/timeout dials
  (`env`, `settings`, `config`, `logger`, `time`, `sleep`, `now`, `datetime`,
  `timeout`, `retry`, `backoff`, `delay`, `interval`, `random`, `seed`, `uuid`,
  `stdout`, ...) is a dial the test turns, not a piece of the system it
  replaced. Shortening a timeout or freezing the clock is how you make a *real*
  integration test fast; counting it would penalise exactly the tests this rule
  is trying to produce.
* **`client.patch("/items/1")`.** An HTTP PATCH request, not a mock — the
  single most dangerous name collision in this rule's vocabulary, and endemic in
  fastapi's and django's suites. A `.patch` attribute only counts when its
  receiver is an import-backed `unittest.mock` alias or pytest-mock's `mocker`;
  a locally-defined `patch` helper never counts.
* **Class-level `@patch` decorators on a `TestCase`.** Those are the class's
  shared fixture — written once, amortised over every method — so attributing
  them to each method reports one design decision N times and points the
  diagnostic at the wrong line. django's `tests/backends/base/test_creation.py`
  is the proof: `TestDbCreationTests` carries four class-level patches
  (`connection.ensure_connection`, `connection.prepare_database`,
  `MigrationRecorder.has_table`, `Command.sync_apps`) that stub the database out
  of the database-creation machinery, and attributing them produced five
  findings in that one class (`:79`, `:104`, `:129`, `:154`, `:175`) for a
  single stack of decorators. Counting only what the test itself declares — its
  own decorators, its own signature, its own body — takes django to zero
  findings and changes nothing anywhere else in the corpus. The parameters those
  class decorators inject are still skipped, or they would be recounted as mock
  fixtures.
* **Parameters injected by the test's own `@patch` decorators.** A `@patch`
  prepends a positional argument that is conventionally named `mock_*`; the
  first N parameters are skipped so a five-patch test scores 5, not 10.
* **Composition-root tests.** A test whose name, class, or path says `wiring`,
  `startup`, `lifespan`, `bootstrap`, `container`, `di` or `smoke` must stub
  every adapter — that is the point of it. This exempts 130 tests across the
  corpora (celery's whole `t/smoke/` suite, bulbul's `test_main_wiring.py`,
  `test_logto_smoke.py` and `TestCollectDigitsToolWiring`, fastapi's lifespan
  tests); the highest substitution count among all 130 is 1, so the guard costs
  nothing today and is there for the app-startup test that would otherwise be
  punished for doing its job.
* A `test_*` nested inside another function — pytest collects only module-level
  functions and class methods, so a nested one is a callback.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_THRESHOLD = 5

_MOCK_MODULE = "unittest.mock"
_MOCK_BACKPORT = "mock"

# Constructors that mint a stand-in for a collaborator.
_MOCK_FACTORIES = frozenset(
    {"Mock", "MagicMock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock", "create_autospec"}
)

_PATCH = "patch"

# `patch.object` / `patch.multiple` / `patch.dict` — the sub-forms of `patch`.
_PATCH_SUBFORMS = frozenset({"object", "multiple", "dict"})

# `patch.multiple(target, spec=..., a=Mock())`: everything that is NOT one of
# these keywords names an attribute being replaced.
_PATCH_CONFIG_KWARGS = frozenset({"spec", "spec_set", "autospec", "new_callable", "create", "instance", "unsafe"})

# pytest-mock's fixture. `mocker.patch(...)` is `unittest.mock.patch` renamed.
_MOCKER = "mocker"

_MONKEYPATCH = "monkeypatch"

# `monkeypatch.setenv`/`delenv` are environment, not substitution; `setitem`/
# `delitem` edit a config dict; `syspath_prepend`/`chdir` are process state.
_MONKEYPATCH_SUBSTITUTION = "setattr"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_TEST_PREFIX = "test"

# Tokens naming test-infrastructure knobs rather than collaborators: the
# environment, configuration, logging, the clock, and the retry/timeout dials.
_INFRA_TOKENS = frozenset(
    {
        "argv",
        "backoff",
        "cfg",
        "clock",
        "conf",
        "config",
        "configs",
        "cwd",
        "date",
        "datetime",
        "delay",
        "delays",
        "env",
        "environ",
        "environment",
        "envs",
        "freeze",
        "getenv",
        "interval",
        "intervals",
        "log",
        "logger",
        "logging",
        "logs",
        "monotonic",
        "now",
        "poll",
        "random",
        "retries",
        "retry",
        "seed",
        "setenv",
        "setting",
        "settings",
        "sleep",
        "stderr",
        "stdout",
        "time",
        "timeout",
        "timeouts",
        "timezone",
        "today",
        "tz",
        "utcnow",
        "uuid",
        "uuid4",
        "uuid7",
    }
)

# A test whose name or location says it is the composition-root test: stubbing
# every adapter is the point of it.
_SEAM_TOKENS = frozenset(
    {
        "bootstrap",
        "container",
        "containers",
        "di",
        "lifespan",
        "smoke",
        "startup",
        "wiring",
    }
)

# Words inside a name, however it is cased: `MAX_RETRIES`, `RequestTimeout`,
# `test_main_wiring.py` and `TestAppStartup` all have to yield their words.
_TOKEN_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


class OverMockedTest(Rule):
    """A test that replaces most of its system under test verifies the mock wiring."""

    id: str = "over-mocked-test"
    code: str = "SARJ059"
    description: str = "Test substitutes too many collaborators — it exercises the mock wiring, not the code."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag test functions that substitute more collaborators than the threshold.

        Returns:
            One diagnostic per over-mocked test, sorted by position.

        """
        if not is_test_path(path):
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
                    f"`{node.name}` substitutes {count} collaborators — at that ratio it exercises the "
                    "mock wiring, not the code. Prefer a real dependency (a test database, an in-process "
                    "app, `respx` for HTTP) and mock only the true external boundary."
                ),
            )
            for node, count in _over_mocked_tests(path, tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _over_mocked_tests(
    path: Path, tree: ast.Module, threshold: int = _THRESHOLD
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, int]]:
    """Find the test functions whose substitution count exceeds `threshold`.

    `threshold` is a parameter so the corpus-calibration sweep can walk the
    whole distribution rather than only the tail.

    Returns:
        Each offending test paired with its distinct-substitution count.

    """
    names = _MockNames.from_tree(tree)
    path_tokens = _tokens(str(path))
    hits: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, int]] = []
    for owner, func in _test_functions(tree):
        if _is_seam_test(func, owner, path_tokens):
            continue
        count = len(_substitutions(func, owner, names))
        if count > threshold:
            hits.append((func, count))
    return hits


def _test_functions(
    tree: ast.Module,
) -> Iterator[tuple[ast.ClassDef | None, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Yield the `test*` callables pytest and unittest actually collect.

    Only module-level functions and direct methods of a class qualify; a
    `test_*` nested inside another function is a callback, never a test.

    Yields:
        The owning class (None at module level) paired with the test function.

    """
    for stmt in tree.body:
        if isinstance(stmt, _FUNC_NODES) and stmt.name.startswith(_TEST_PREFIX):
            yield None, stmt
        elif isinstance(stmt, ast.ClassDef):
            for inner in stmt.body:
                if isinstance(inner, _FUNC_NODES) and inner.name.startswith(_TEST_PREFIX):
                    yield stmt, inner


def _tokens(text: str) -> frozenset[str]:
    return frozenset(word[0].lower() for word in _TOKEN_RE.finditer(text))


def _is_seam_test(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    path_tokens: frozenset[str],
) -> bool:
    own = _tokens(func.name) | path_tokens
    if owner is not None:
        own |= _tokens(owner.name)
    return bool(own & _SEAM_TOKENS)


def _is_infra_target(key: str) -> bool:
    return bool(_tokens(key) & _INFRA_TOKENS)


class _MockNames:
    """The local names through which `unittest.mock` is reachable in one file.

    Name resolution is load-bearing, not decoration: `client.patch("/items/1")`
    is an HTTP PATCH request and appears all over FastAPI/Django/DRF suites, so
    a bare `.patch` attribute is only a substitution when its receiver is an
    import-backed mock module (or pytest-mock's `mocker`).
    """

    def __init__(self) -> None:
        self.modules: set[str] = set()
        self.symbols: dict[str, str] = {}

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _MockNames:
        """Collect every local binding that resolves to `unittest.mock`.

        Returns:
            The populated name table.

        """
        found = cls()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found._add_plain_import(node)
            elif isinstance(node, ast.ImportFrom):
                found._add_from_import(node)
        return found

    def _add_plain_import(self, node: ast.Import) -> None:
        for alias in node.names:
            # `import unittest.mock` binds `unittest`; `import mock` is the backport.
            if alias.name == _MOCK_MODULE:
                self.modules.add(alias.asname or "unittest")
            elif alias.name == _MOCK_BACKPORT:
                self.modules.add(alias.asname or _MOCK_BACKPORT)

    def _add_from_import(self, node: ast.ImportFrom) -> None:
        if node.module == "unittest":
            for alias in node.names:
                if alias.name == _MOCK_BACKPORT:
                    self.modules.add(alias.asname or _MOCK_BACKPORT)
        elif node.module in {_MOCK_MODULE, _MOCK_BACKPORT}:
            for alias in node.names:
                if alias.name == _PATCH or alias.name in _MOCK_FACTORIES:
                    self.symbols[alias.asname or alias.name] = alias.name

    def is_mock_module(self, node: ast.expr) -> bool:
        """Report whether `node` names the mock module (or pytest-mock's fixture).

        Returns:
            True when attribute access on `node` reaches `unittest.mock`.

        """
        if isinstance(node, ast.Name):
            return node.id in self.modules or node.id == _MOCKER
        # `unittest.mock.patch(...)` — the receiver is itself an attribute chain.
        if isinstance(node, ast.Attribute) and node.attr == _MOCK_BACKPORT:
            return isinstance(node.value, ast.Name) and node.value.id in self.modules
        return False

    def patch_subform(self, func: ast.expr) -> str | None:
        """Map a callee onto the `patch` form it invokes.

        Returns:
            "patch" for plain `patch(...)`, the sub-form name for
            `patch.object`/`multiple`/`dict`, or None when unrelated.

        """
        if isinstance(func, ast.Name):
            return _PATCH if self.symbols.get(func.id) == _PATCH else None
        if not isinstance(func, ast.Attribute):
            return None
        if func.attr in _PATCH_SUBFORMS:
            return func.attr if self._is_patch_ref(func.value) else None
        if func.attr == _PATCH:
            return _PATCH if self.is_mock_module(func.value) else None
        return None

    def _is_patch_ref(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return self.symbols.get(node.id) == _PATCH
        return isinstance(node, ast.Attribute) and node.attr == _PATCH and self.is_mock_module(node.value)

    def factory(self, func: ast.expr) -> str | None:
        """Map a callee onto the mock constructor it invokes.

        Returns:
            The canonical factory name, or None when the callee is unrelated.

        """
        if isinstance(func, ast.Name):
            symbol = self.symbols.get(func.id)
            return symbol if symbol in _MOCK_FACTORIES else None
        if isinstance(func, ast.Attribute) and func.attr in _MOCK_FACTORIES and self.is_mock_module(func.value):
            return func.attr
        return None


def _substitutions(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    names: _MockNames,
) -> frozenset[str]:
    """Collect the distinct collaborators this test replaces with a double.

    A substitution is recorded as `(replaced target, owning object)`: the target
    decides whether it is an infrastructure knob, the owner decides identity.
    Three patches of three methods on one client replace one collaborator, not
    three.

    Returns:
        One key per distinct substituted collaborator.

    """
    subs: set[tuple[str, str]] = set()
    injected = 0
    for dec in func.decorator_list:
        if isinstance(dec, ast.Call):
            subform = names.patch_subform(dec.func)
            if subform is not None:
                subs.update(_patch_keys(dec, subform))
                injected += _injected_arity(dec, subform)
    # A class-level `@patch` is the TestCase's shared fixture, not something
    # this test asked for; its substitutions are not counted. Its injected
    # parameters still have to be skipped, or they would be recounted as mock
    # fixtures.
    injected += _class_injected_arity(owner, names)

    subs.update(_body_substitutions(func, names))
    subs.update((name, name) for name in _mock_parameters(func, injected))
    return frozenset(owning for target, owning in subs if not _is_infra_target(target))


def _class_injected_arity(owner: ast.ClassDef | None, names: _MockNames) -> int:
    if owner is None:
        return 0
    total = 0
    for dec in owner.decorator_list:
        if isinstance(dec, ast.Call):
            subform = names.patch_subform(dec.func)
            if subform is not None:
                total += _injected_arity(dec, subform)
    return total


def _injected_arity(call: ast.Call, subform: str) -> int:
    # A `@patch`/`@patch.object` decorator prepends one positional argument to
    # the test signature, and it is conventionally named `mock_*`. Those
    # parameters must not be counted a second time as mock fixtures.
    if subform in {_PATCH, "object"}:
        return 0 if _has_replacement(call, subform) else 1
    if subform == "multiple":
        return len(_replaced_attributes(call))
    return 0


def _has_replacement(call: ast.Call, subform: str) -> bool:
    # `patch(target, new)` / `patch.object(target, attr, new)` supply the
    # replacement themselves, so nothing is injected into the signature.
    positional = 2 if subform == _PATCH else 3
    return len(call.args) >= positional or any(kw.arg == "new" for kw in call.keywords)


def _body_substitutions(func: ast.AST, names: _MockNames) -> set[tuple[str, str]]:
    subs: set[tuple[str, str]] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            subs.update(_call_substitutions(node, names))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                subs.update(_binding_keys(target, node.value, names))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            subs.update(_binding_keys(node.target, node.value, names))
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            subs.update(_binding_keys(node.optional_vars, node.context_expr, names))
    return subs


def _call_substitutions(node: ast.Call, names: _MockNames) -> list[tuple[str, str]]:
    subform = names.patch_subform(node.func)
    if subform is not None:
        return _patch_keys(node, subform)
    return _monkeypatch_keys(node)


def _binding_keys(target: ast.expr, value: ast.expr, names: _MockNames) -> list[tuple[str, str]]:
    """Key a `x = MagicMock()` binding by the name the double is bound to.

    Returns:
        The bound name as both target and owner, or nothing when the value is
        not a mock construction.

    """
    if not isinstance(value, ast.Call) or names.factory(value.func) is None:
        return []
    bound = _bound_name(target)
    return [(bound, bound)] if bound is not None else []


def _bound_name(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    # `self.client = MagicMock()` inside a unittest method.
    return _collaborator_of(target) if isinstance(target, ast.Attribute) else None


def _collaborator_of(node: ast.expr) -> str | None:
    """Name the collaborator an attribute chain reaches into.

    `ctx.api.room.delete_room = AsyncMock()` does not introduce a collaborator —
    it configures one more corner of the double already bound to `ctx`, and a
    six-line build-out of one mock's object graph must count once, not six
    times. So an attribute chain collapses to its root. `self`/`cls` is the
    exception: it is the test case, not a double, so `self.client` and
    `self.session` are two collaborators hung off it.

    Returns:
        The root object's name, or None when the chain is not a plain
        `a.b.c` of identifiers.

    """
    dotted = _dotted(node)
    if dotted is None:
        return None
    parts = dotted.split(".")
    if parts[0] in {"self", "cls"} and len(parts) > 1:
        return ".".join(parts[:2])
    return parts[0]


def _patch_keys(call: ast.Call, subform: str) -> list[tuple[str, str]]:
    """Name the collaborator(s) a `patch`-family call replaces.

    Returns:
        A `(replaced target, owning object)` pair per replaced attribute; empty
        for `patch.dict`, which edits a mapping (`os.environ`, a settings dict)
        rather than substituting a collaborator.

    """
    if subform == "dict":
        return []
    if subform in {"object", "multiple"}:
        if not call.args:
            return []
        base, owning = _receiver(call.args[0])
        attrs = (
            [_target_text(call.args[1]) if len(call.args) > 1 else _keyword_text(call, "attribute")]
            if subform == "object"
            else _replaced_attributes(call)
        )
        return [(f"{base}.{attr}", owning) for attr in attrs] if attrs else [(base, owning)]
    if not call.args:
        return []
    target = _target_text(call.args[0])
    return [(target, _owner_of(target))]


def _receiver(node: ast.expr) -> tuple[str, str]:
    """Render the object a `patch.object` / `monkeypatch.setattr` call targets.

    Returns:
        Its readable name, paired with the collaborator it belongs to.

    """
    text = _target_text(node)
    if isinstance(node, ast.Constant):
        return text, _owner_of(text)
    return text, _collaborator_of(node) or text


def _owner_of(target: str) -> str:
    """Reduce a dotted patch target to the object whose attribute is replaced.

    `patch("os.fork")`, `patch("os.setsid")` and `patch("os.dup2")` all replace
    parts of one collaborator — the OS — not three.

    Returns:
        The target with its final segment dropped, or the target itself when it
        has no dot.

    """
    head, dot, _ = target.rpartition(".")
    return head if dot else target


def _replaced_attributes(call: ast.Call) -> list[str]:
    return [kw.arg for kw in call.keywords if kw.arg is not None and kw.arg not in _PATCH_CONFIG_KWARGS]


def _monkeypatch_keys(call: ast.Call) -> list[tuple[str, str]]:
    """Name the target of a `monkeypatch.setattr(...)` call.

    Returns:
        The single substituted target and its owner, or nothing for any other
        monkeypatch method — `setenv`/`delenv` are the environment,
        `setitem`/`delitem` edit a mapping, `chdir`/`syspath_prepend` are
        process state.

    """
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != _MONKEYPATCH_SUBSTITUTION:
        return []
    if not (isinstance(func.value, ast.Name) and func.value.id == _MONKEYPATCH):
        return []
    if not call.args:
        return []
    base, owning = _receiver(call.args[0])
    # `monkeypatch.setattr(mod, "attr", value)` vs `setattr("mod.attr", value)`.
    two_part = 3
    if len(call.args) >= two_part:
        return [(f"{base}.{_target_text(call.args[1])}", owning)]
    return [(base, _owner_of(base))]


def _mock_parameters(func: ast.FunctionDef | ast.AsyncFunctionDef, injected: int) -> list[str]:
    """List the mock-shaped fixtures this test asks pytest to build for it.

    The first `injected` parameters are the ones `@patch` decorators prepend;
    they are conventionally named `mock_*` and are already counted.

    Returns:
        The names of the remaining mock-typed fixture parameters.

    """
    args = func.args
    positional = [arg.arg for arg in (*args.posonlyargs, *args.args) if arg.arg not in {"self", "cls"}]
    candidates = [*positional[injected:], *(arg.arg for arg in args.kwonlyargs)]
    return [name for name in candidates if _is_mock_fixture(name)]


def _is_mock_fixture(name: str) -> bool:
    return name == _MOCKER or name.startswith("mock_") or name.endswith(("_mock", "_mocks"))


def _target_text(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return _dotted(node) or "?"


def _keyword_text(call: ast.Call, name: str) -> str:
    for kw in call.keywords:
        if kw.arg == name:
            return _target_text(kw.value)
    return "?"


def _dotted(node: ast.expr) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))
