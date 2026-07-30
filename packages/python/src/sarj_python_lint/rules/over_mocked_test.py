"""SARJ062: a test that substitutes six collaborators exercises the mock wiring, not the code.

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
* mock-shaped fixture parameters — `mock_*`, `*_mock`, `*_mocks`.

A collaborator is an **object, not one of its methods, and not one of the names
that point at it**. Four reductions make that true, and every one was forced by
a measured false positive:

* a dotted patch target loses its last segment, so `patch("os.fork")`,
  `patch("os.setsid")` and `patch("os.dup2")` are one substituted collaborator —
  the OS. Without this, `celery/t/unit/utils/test_platforms.py:467`
  (`test_open`, eleven `@patch`es of `os.*` around a `DaemonContext`) scored 14
  and `:220` (`test_with_uid`) scored 10, and both are *correct* code: those
  syscalls are the true external boundary this rule tells you to mock. They now
  score 4 and 3 and never fire,
* an attribute chain assigned a double collapses to its root, because
  `ctx.api.room.delete_room = AsyncMock()` does not add a collaborator — it
  fills in one more corner of the double already bound to `ctx`. Without this,
  `bulbul/agent/tests/test_main_helpers.py:138`
  (`test_timeout_marks_call_failed_with_no_answer`) scored 6 for building out a
  single `mock.Mock(spec=JobContext)` in six statements, while using a **real**
  `PsqlCallStore` against a real database — the exact test this rule wants
  people to write. Five of its sibling tests scored 6 the same way. It now
  scores 1. `self`/`cls` is the exception: it is the test case, not a double, so
  `self.client` and `self.session` stay two collaborators,
* **a name hoisted out of an object graph is that graph.** `mock_room = Mock()`
  followed by `ctx.room = mock_room` is one object written in two statements,
  and the attribute-chain collapse above cannot see it because the double is
  bound to a local first. Every wiring edge is therefore resolved to a fixpoint
  before the count is taken: `A.b = n`, `A.b.return_value = n`,
  `A.b.side_effect = [n1, n2]`, `A.b = Mock(return_value=n)` and
  `A.b.return_value = ok(n)` (a name handed to a one-level wrapper call is
  still placed inside `A`), the chained `a = b.c = Mock()`, the handle of a
  `with patch.object(store, "m") as h`, and the parameter a `@patch` decorator
  injects. Without this,
  `superset/tests/unit_tests/utils/webdriver_test.py:847` scored 9 for one
  Playwright chain (`browser` → `context` → `page` → locators) and
  `mlflow/.../test_unity_catalog_rest_store.py:900` scored 6 for five
  `patch.object(store, ...)` handles and the response objects hung off them.
  This is the single largest correction: it removes 300 of the 597 findings the
  uncorrected counter produced,
* **a bare name is resolved through the file's import table.** `from app import
  gateway` then `patch.object(gateway, "call")` names the same collaborator as
  `patch("app.gateway.send")`; counting `gateway` and `app.gateway` separately
  reported one object twice. A *relative* import is not resolved — `.app` is not
  the top-level `app`, and rewriting onto it would merge two different objects.

`patch(f"{MODULE}.Client")` is reconstructed as `MODULE.Client` rather than
collapsing to an opaque `?`. The old behaviour made every f-string target in a
file the same anonymous collaborator, which both under-counted files that
templated several distinct targets and mis-keyed the infrastructure filter
(`patch(f"{MODULE}.sleep")` is a clock knob and has to read as one). At the
shipping threshold this changes no finding either way; it is here so the
identity model has no hole in it.

MEASURED DISTRIBUTION, AND WHERE THE THRESHOLD CAME FROM
--------------------------------------------------------

Distinct collaborators per collected test function, over 170,354 collected
tests in 19 repositories (bulbul, noura-be, digital-bank, submissions, ai and
14 large OSS Python suites):

    corpus         tests       0      1     2     3     4    5   6  7  8 9+  >5
    bulbul         4,279   3,989    201    64    20     3    2   -  -  -  -   0
    noura-be       2,861   2,593    264     4     -     -    -   -  -  -  -   0
    digital-bank     521     485     36     -     -     -    -   -  -  -  -   0
    submissions      113     112      1     -     -     -    -   -  -  -  -   0
    ai               259     198     50     7     1     2    1   -  -  -  -   0
    airflow       27,827  15,573  8,657 2,678   668   172   58  16  4  1  -  21
    dagster       11,196   9,971    976   143    60    14   11  14  7  -  -  21
    litellm       32,880  22,328  6,168 2,751 1,003   362  155  61 28 12 12 113
    saleor        12,669   9,910  2,128   449   129    45    4   4  -  -  -   4
    django        18,044  17,643    354    39     7     -    1   -  -  -  -   0
    mlflow        13,718   9,743  2,500 1,070   286    79   23   9  3  4  1  17
    langchain      5,427   4,955    379    63    26     3    -   1  -  -  -   1
    superset      10,931   6,514  2,582 1,008   503   233   54  23  8  4  2  37
    zulip          4,384   3,855    470    44    12     2    -   -  -  -  1   1
    prefect       13,784  11,298  1,463   584   251   103   62  12  9  -  2  23
    fastapi        2,290   2,260     27     2     -     1    -   -  -  -  -   0
    warehouse      3,524   2,704    703    94    21     2    -   -  -  -  -   0
    sentry-python  2,443   1,920    466    29    17     9    2   -  -  -  -   0
    celery         3,204   2,162    772   190    46    24    9   -  -  1  -   1
    ALL          170,354 128,213 28,197 9,219 3,050 1,054  382 140 59 22 18 239

75.3% of tests substitute nothing at all, and 99.86% stay at five or below. The
rule fires **above five**: 239 findings in 170,354 tests (0.14%).

The previous table in this docstring was wrong and has been replaced. It was
built by a counter that read one object graph as several — a hoisted
`mock_room = Mock(); ctx.room = mock_room` scored 2, pytest-mock's `mocker`
handle scored as a collaborator of its own, and every f-string target in a file
collapsed onto the same key. Its tail was inflated, so the "99.96th percentile"
it reported was an artefact. Correcting the counter took the corpus from 597
findings to 239 without introducing a single new one.

Re-deriving the threshold from the corrected distribution:

    fire above   findings   % of tests   first-party findings
    >6                 99      0.058%    0
    >5                239      0.140%    0
    >4                621      0.365%    3  (bulbul 2, ai 1)
    >3              1,675      0.983%    8  (bulbul 5, ai 3)

`>5` survives, for a reason the corrected data still supports: firing above
four drags in honest tests. django's only test in the 5 band is
`tests/backends/sqlite/test_creation.py:47`, which uses a *real* connection and
a real creation class and mocks the three `sqlite3.connect` calls under it;
bulbul's are `test_agent_tools.py:662` and `test_collect_digits_tool.py:598`,
five doubles apiece around a real tool object. Five is still where honest tests
live.

What has changed is the rule's standing in the first-party repositories: at `>5`
it now finds **nothing** in bulbul, noura-be, digital-bank, submissions or ai,
so it is a **ratchet** — like `no-patching-system-under-test`. Nothing has to be
fixed to adopt it, and nothing may regress past it. It earns its place on the
OSS evidence, where 239 findings concentrate in the suites that are mostly mock
by volume (litellm 113, superset 37, prefect 23, airflow 21, dagster 21) —
exactly the population the rule exists to name. celery's worst,
`t/unit/test_loops.py:9`, still scores 8: eight bare `Mock()`s named `obj`,
`connection`, `consumer`, `blueprint`, `hub`, `qos`, `heartbeat` and `clock`,
and then an assertion that `synloop` called them.

The two bulbul findings that used to justify the threshold were both counting
one hoisted object graph twice — the shape this docstring says must collapse,
merely written with the mock hoisted. They are correctly gone.

DELIBERATELY NOT COUNTED
------------------------

* **`monkeypatch.setenv` / `delenv`.** That is the environment, not a
  collaborator. Only `monkeypatch.setattr` counts. `setitem`/`delitem` (editing
  a settings dict), `chdir` and `syspath_prepend` are likewise process state.
* **`patch.dict(...)`.** It edits a mapping in place — `os.environ`, a settings
  dict, a handler registry — rather than replacing a collaborator; django alone
  uses `@mock.patch.dict(os.environ, ...)` as a class decorator on the very
  tests this rule looks at.
* **`mocker` itself.** pytest-mock's `mocker` fixture is the handle you patch
  *through*, not a collaborator that got replaced; what it patches is counted at
  the `mocker.patch(...)` call. Counting the handle as well added a phantom
  substitution to every pytest-mock test: putting it back adds 30 findings.
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
  first N parameters are skipped so a five-patch test scores 5, not 10. Each
  such parameter is also aliased to the target its decorator replaced, so a
  double wired onto it (`mock_browser_manager.get_browser.return_value =
  mock_browser`) joins that collaborator rather than starting a new one; that
  alias alone accounts for 47 findings.
* **Composition-root tests.** A test whose name, class, or path says `wiring`,
  `startup`, `lifespan`, `bootstrap`, `container`, `di` or `smoke` must stub
  every adapter — that is the point of it. This exempts 1,133 tests across the
  corpora (celery's whole `t/smoke/` suite, bulbul's `test_main_wiring.py`,
  `test_logto_smoke.py` and `TestCollectDigitsToolWiring`, fastapi's lifespan
  tests). Four of the 1,133 would otherwise fire, and three are the guard
  working as intended — litellm's `test_proxy_cli.py:518`, `:1814` and `:1881`
  stub the world around the proxy's startup path. The fourth,
  prefect's `test_container_instance.py:2212`, is a name collision: `container`
  there is an Azure Container Instance, not a DI container. The token list is
  the cost of matching on names; it errs toward suppression.

  The path arm reads only from the **test root** down — the first `t` / `test` /
  `tests` component and everything below it. It used to tokenise the whole
  absolute path, which meant an ancestor directory nobody chose could exempt a
  file: the identical test fires at `app/tests/test_billing.py` and was silent
  at `my-container-app/tests/test_billing.py`, under `~/di/svc/`, or on a CI
  runner whose workspace directory is `smoke-repo`. That disabled the rule for
  an entire checkout, and since it reports zero on compliant code the silence
  was indistinguishable from success. Scoping to the test root keeps every real
  case (celery's `t/smoke/tests/` still reads `smoke` two levels up) and changes
  no finding in any corpus.
* A `test_*` nested inside another function — pytest collects only module-level
  functions and class methods, so a nested one is a callback.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, NamedTuple, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
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

# `patch(target, new)` supplies the replacement itself and injects no parameter;
# `patch.object(target, attribute, new)` needs one more positional to say so.
_PATCH_REPLACEMENT_ARITY = 2
_PATCH_OBJECT_REPLACEMENT_ARITY = 3

# `monkeypatch.setattr(target, name, value)` names the attribute separately;
# the two-argument form spells it into the dotted target instead.
_SETATTR_SPLIT_ARITY = 3

# pytest-mock's fixture. `mocker.patch(...)` is `unittest.mock.patch` renamed.
_MOCKER = "mocker"

_MONKEYPATCH = "monkeypatch"

# `monkeypatch.setenv`/`delenv` are environment, not substitution; `setitem`/
# `delitem` edit a config dict; `syspath_prepend`/`chdir` are process state.
_MONKEYPATCH_SUBSTITUTION = "setattr"

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_TEST_PREFIX = "test"

# The receiver of an attribute chain that is the test case rather than a double.
_TEST_CASE_RECEIVERS = frozenset({"self", "cls"})

# `self.client` is a collaborator hung off the test case; `self` alone is not.
_TEST_CASE_DEPTH = 2

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
    code: str = "SARJ062"
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
    path_tokens = _seam_path_tokens(path)
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


# The directory a test suite is rooted at. Everything below one of these is the
# author's organisation of their tests; everything above is where the repo lives.
_TEST_ROOT_NAMES = frozenset({"t", "test", "tests"})


def _seam_path_tokens(path: Path) -> frozenset[str]:
    """Tokenise the part of `path` that the author chose, not the whole checkout.

    The seam exemption reads the path because a composition-root suite is often
    a *directory* rather than a suffixed filename — celery's `t/smoke/` is the
    motivating case. Tokenising `str(path)` reads the absolute path, so any
    ancestor supplied by whoever cloned the repo counts too: the identical file
    fires at `app/tests/test_billing.py` and is silent at
    `my-container-app/tests/test_billing.py`, under `~/di/svc/`, or on a CI
    runner whose workspace is `smoke-repo`. That turns the rule off for a whole
    checkout, and because it reports zero on compliant code the silence is
    indistinguishable from success.

    The dividing line is the test root: everything from the first `t` / `test` /
    `tests` component downward is how the author organised their suite, and
    everything above it is where the repository happens to sit on disk. So
    `t/smoke/tests/test_worker.py` still reads `smoke` (celery's layout, where
    the marker is two levels up), while `my-container-app/tests/test_billing.py`
    reads only `test_billing.py`.

    `t` is included as a marker because celery's suite is rooted there. It is
    short enough to appear as an ordinary directory name, so a repository stored
    under a path component named exactly `t` would still read its descendants —
    a much narrower leak than reading the whole path, and one no corpus exhibits.

    Returns:
        The tokens of the path from its test root down, or of the filename alone
        when no test root appears.

    """
    parts = path.parts
    start = next((i for i, part in enumerate(parts) if part in _TEST_ROOT_NAMES), len(parts) - 1)
    tokens: set[str] = set()
    for part in parts[start:]:
        tokens |= _tokens(part)
    return frozenset(tokens)


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
    """The local names through which `unittest.mock` and the imports are reachable.

    Name resolution is load-bearing, not decoration: `client.patch("/items/1")`
    is an HTTP PATCH request and appears all over FastAPI/Django/DRF suites, so
    a bare `.patch` attribute is only a substitution when its receiver is an
    import-backed mock module (or pytest-mock's `mocker`). The same table
    carries every other import, so that `patch.object(gateway, "call")` and
    `patch("app.gateway.send")` name one collaborator rather than two.
    """

    def __init__(self) -> None:
        self.modules: set[str] = set()
        self.symbols: dict[str, str] = {}
        self.qualified: dict[str, str] = {}

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _MockNames:
        """Collect every local binding that resolves to `unittest.mock`, and the import table.

        Returns:
            The populated name table.

        """
        found = cls()
        for node in nodes(tree, ast.Import, ast.ImportFrom):
            if isinstance(node, ast.Import):
                found._add_plain_import(node)
            else:
                found._add_from_import(node)
        return found

    def _add_plain_import(self, node: ast.Import) -> None:
        for alias in node.names:
            # `import unittest.mock` binds `unittest`; `import mock` is the backport.
            if alias.name == _MOCK_MODULE:
                self.modules.add(alias.asname or "unittest")
            elif alias.name == _MOCK_BACKPORT:
                self.modules.add(alias.asname or _MOCK_BACKPORT)
            if alias.asname is not None:
                self.qualified[alias.asname] = alias.name

    def _add_from_import(self, node: ast.ImportFrom) -> None:
        if node.module == "unittest":
            for alias in node.names:
                if alias.name == _MOCK_BACKPORT:
                    self.modules.add(alias.asname or _MOCK_BACKPORT)
        elif node.module in {_MOCK_MODULE, _MOCK_BACKPORT}:
            for alias in node.names:
                if alias.name == _PATCH or alias.name in _MOCK_FACTORIES:
                    self.symbols[alias.asname or alias.name] = alias.name
        # A relative import has no absolute path to resolve a bare name onto.
        if node.module is not None and node.level == 0:
            for alias in node.names:
                self.qualified[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    def qualify(self, owner: str) -> str:
        """Rewrite a bare-name collaborator to the dotted path it was imported from.

        Returns:
            `owner` with its leading segment replaced by the import it names, or
            `owner` unchanged when no import binds that name.

        """
        head, dot, rest = owner.partition(".")
        full = self.qualified.get(head)
        if full is None:
            return owner
        return f"{full}.{rest}" if dot else full

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


class _BodyScan(NamedTuple):
    """One pass over a test body: what it substituted, and how the names are wired.

    `facets` maps a name onto the object it is merely a part of, so that a
    hoisted `mock_room = Mock(); ctx.room = mock_room` resolves to one
    collaborator instead of two.
    """

    subs: set[tuple[str, str]]
    facets: dict[str, str]


def _substitutions(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    names: _MockNames,
) -> frozenset[str]:
    """Collect the distinct collaborators this test replaces with a double.

    A substitution is recorded as `(replaced target, owning object)`: the target
    decides whether it is an infrastructure knob, the owner decides identity.
    Three patches of three methods on one client replace one collaborator, not
    three, and so do three names pointing into one object graph.

    Returns:
        One key per distinct substituted collaborator.

    """
    subs: set[tuple[str, str]] = set()
    injected: list[str | None] = []
    for dec in reversed(func.decorator_list):
        if isinstance(dec, ast.Call):
            subform = names.patch_subform(dec.func)
            if subform is not None:
                subs.update(_patch_keys(dec, subform, names))
                injected += _injected_owners(dec, subform, names)
    # A class-level `@patch` is the TestCase's shared fixture, not something
    # this test asked for; its substitutions are not counted. Its injected
    # parameters still have to be skipped, or they would be recounted as mock
    # fixtures. They wrap the method's own patches, so they arrive last.
    injected += _class_injected_owners(owner, names)

    scan = _body_substitutions(func, names)
    subs |= scan.subs
    subs.update((name, name) for name in _mock_parameters(func, len(injected)))
    facets = scan.facets | _injected_facets(func, injected)
    return frozenset(names.qualify(_resolve(owning, facets)) for target, owning in subs if not _is_infra_target(target))


def _resolve(name: str, facets: Mapping[str, str]) -> str:
    """Follow the wiring edges from `name` to the object it is a facet of.

    Returns:
        The root of the chain; `name` itself when nothing points it elsewhere.
        A cyclic chain stops at the first repeat rather than spinning.

    """
    seen = {name}
    while (nxt := facets.get(name)) is not None and nxt not in seen:
        seen.add(nxt)
        name = nxt
    return name


def _class_injected_owners(owner: ast.ClassDef | None, names: _MockNames) -> list[str | None]:
    if owner is None:
        return []
    injected: list[str | None] = []
    for dec in reversed(owner.decorator_list):
        if isinstance(dec, ast.Call):
            subform = names.patch_subform(dec.func)
            if subform is not None:
                injected += _injected_owners(dec, subform, names)
    return injected


def _injected_owners(call: ast.Call, subform: str, names: _MockNames) -> list[str | None]:
    """Say which collaborator each parameter this decorator prepends stands for.

    A `@patch`/`@patch.object` decorator prepends one positional argument to the
    test signature, and it is conventionally named `mock_*`; those parameters
    must not be counted a second time as mock fixtures. `patch.multiple` injects
    one per replaced attribute, by keyword, so which is which is not knowable
    from the signature.

    Returns:
        One entry per injected parameter, naming its collaborator where the
        mapping is unambiguous and None otherwise.

    """
    if subform in {_PATCH, "object"}:
        if _has_replacement(call, subform):
            return []
        keys = _patch_keys(call, subform, names)
        return [keys[0][1] if len(keys) == 1 else None]
    if subform == "multiple":
        return [None] * len(_replaced_attributes(call))
    return []


def _has_replacement(call: ast.Call, subform: str) -> bool:
    # `patch(target, new)` / `patch.object(target, attr, new)` supply the
    # replacement themselves, so nothing is injected into the signature.
    positional = _PATCH_REPLACEMENT_ARITY if subform == _PATCH else _PATCH_OBJECT_REPLACEMENT_ARITY
    return len(call.args) >= positional or any(kw.arg == "new" for kw in call.keywords)


def _injected_facets(func: ast.FunctionDef | ast.AsyncFunctionDef, injected: list[str | None]) -> dict[str, str]:
    """Alias each `@patch`-injected parameter onto the collaborator it replaced.

    Returns:
        A wiring edge per injected parameter whose collaborator is known.

    """
    positional = [
        name for arg in (*func.args.posonlyargs, *func.args.args) if (name := arg.arg) not in _TEST_CASE_RECEIVERS
    ]
    return {param: owning for param, owning in zip(positional, injected, strict=False) if owning is not None}


def _body_substitutions(func: ast.AST, names: _MockNames) -> _BodyScan:
    """Walk a test body once, collecting substitutions and the wiring between them.

    Returns:
        The substitution keys and the name-to-object wiring edges.

    """
    scan = _BodyScan(subs=set(), facets={})
    for node in walk(func):
        if isinstance(node, ast.Call):
            scan.subs.update(_call_substitutions(node, names))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                scan.subs.update(_binding_keys(target, node.value, names))
            _record_facets(node.targets, node.value, names, scan.facets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            scan.subs.update(_binding_keys(node.target, node.value, names))
            _record_facets([node.target], node.value, names, scan.facets)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            scan.subs.update(_binding_keys(node.optional_vars, node.context_expr, names))
            _record_handle_facet([node.optional_vars], node.context_expr, names, scan.facets)
    return scan


def _record_facets(targets: list[ast.expr], value: ast.expr, names: _MockNames, facets: dict[str, str]) -> None:
    """Note that a name assigned into another object's attribute is part of that object.

    `ctx.room = mock_room` and `mock_call.side_effect = [first, second]` both
    say the right-hand names are corners of the left-hand object graph, as does
    the chained `consumer = app.amqp.TaskConsumer.return_value = Mock()`.
    """
    roots = {root for target in targets if isinstance(target, ast.Attribute) and (root := _object_of(target, names))}
    if roots:
        sources = [*_assigned_names(value), *(t.id for t in targets if isinstance(t, ast.Name))]
        for root in roots:
            for source in sources:
                if source != root:
                    facets.setdefault(source, root)
    _record_handle_facet(targets, value, names, facets)


def _assigned_names(value: ast.expr) -> list[str]:
    """List the names the assigned expression places inside the target's object graph.

    Returns:
        The name assigned directly, the names in a sequence of them, or the
        names handed to a one-level wrapper call — `Mock(return_value=stub)`
        and `ok(stub)` both put `stub` inside the object being configured.

    """
    if isinstance(value, ast.Name):
        return [value.id]
    if isinstance(value, ast.List | ast.Tuple):
        return [elt.id for elt in value.elts if isinstance(elt, ast.Name)]
    if isinstance(value, ast.Call):
        return [
            *(arg.id for arg in value.args if isinstance(arg, ast.Name)),
            *(val.id for kw in value.keywords if isinstance(val := kw.value, ast.Name)),
        ]
    return []


def _record_handle_facet(targets: list[ast.expr], value: ast.expr, names: _MockNames, facets: dict[str, str]) -> None:
    """Note that a `patch(...)` handle names the collaborator that patch replaced.

    `with patch.object(store, "_call_endpoint") as mock_call:` binds a name to a
    substitution already counted against `store`; anything wired onto it belongs
    to `store` too.
    """
    if not isinstance(value, ast.Call):
        return
    subform = names.patch_subform(value.func)
    if subform is None:
        return
    keys = _patch_keys(value, subform, names)
    if len(keys) != 1:
        return
    owning = keys[0][1]
    for target in targets:
        if isinstance(target, ast.Name) and target.id != owning:
            facets.setdefault(target.id, owning)


def _call_substitutions(node: ast.Call, names: _MockNames) -> list[tuple[str, str]]:
    subform = names.patch_subform(node.func)
    if subform is not None:
        return _patch_keys(node, subform, names)
    return _monkeypatch_keys(node, names)


def _binding_keys(target: ast.expr, value: ast.expr, names: _MockNames) -> list[tuple[str, str]]:
    """Key a `x = MagicMock()` binding by the name the double is bound to.

    Returns:
        The bound name as both target and owner, or nothing when the value is
        not a mock construction.

    """
    if not isinstance(value, ast.Call) or names.factory(value.func) is None:
        return []
    bound = _bound_name(target, names)
    return [(bound, bound)] if bound is not None else []


def _bound_name(target: ast.expr, names: _MockNames) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    # `self.client = MagicMock()` inside a unittest method.
    return _object_of(target, names) if isinstance(target, ast.Attribute) else None


def _object_of(node: ast.expr, names: _MockNames) -> str | None:
    """Name the collaborator an expression reaches into, resolved through imports.

    Returns:
        The root object's qualified name, or None when the expression is not a
        plain `a.b.c` of identifiers.

    """
    root = _collaborator_of(node)
    return None if root is None else names.qualify(root)


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
    if parts[0] in _TEST_CASE_RECEIVERS:
        return ".".join(parts[:_TEST_CASE_DEPTH])
    return parts[0]


def _patch_keys(call: ast.Call, subform: str, names: _MockNames) -> list[tuple[str, str]]:
    """Name the collaborator(s) a `patch`-family call replaces.

    Returns:
        A `(replaced target, owning object)` pair per replaced attribute; empty
        for `patch.dict`, which edits a mapping (`os.environ`, a settings dict,
        a handler registry) rather than substituting a collaborator.

    """
    if subform == "dict":
        return []
    if subform in {"object", "multiple"}:
        if not call.args:
            return []
        base, owning = _receiver(call.args[0], names)
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


def _receiver(node: ast.expr, names: _MockNames) -> tuple[str, str]:
    """Render the object a `patch.object` / `monkeypatch.setattr` call targets.

    Returns:
        Its readable name, paired with the collaborator it belongs to.

    """
    text = _target_text(node)
    if isinstance(node, ast.Constant):
        return text, _owner_of(text)
    return text, _object_of(node, names) or text


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
    return [arg for kw in call.keywords if (arg := kw.arg) is not None and arg not in _PATCH_CONFIG_KWARGS]


def _monkeypatch_keys(call: ast.Call, names: _MockNames) -> list[tuple[str, str]]:
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
    base, owning = _receiver(call.args[0], names)
    # `monkeypatch.setattr(mod, "attr", value)` vs `setattr("mod.attr", value)`:
    # in the two-argument form the second argument is the replacement, and
    # reading it as an attribute name would key the target off the stub.
    if len(call.args) >= _SETATTR_SPLIT_ARITY:
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
    positional = [name for arg in (*args.posonlyargs, *args.args) if (name := arg.arg) not in _TEST_CASE_RECEIVERS]
    candidates = [*positional[injected:], *(arg.arg for arg in args.kwonlyargs)]
    return [name for name in candidates if _is_mock_fixture(name)]


def _is_mock_fixture(name: str) -> bool:
    # `mocker` itself is pytest-mock's handle, not a collaborator: what it
    # patches is counted at the `mocker.patch(...)` call site.
    return name.startswith("mock_") or name.endswith(("_mock", "_mocks"))


def _target_text(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return _joined_text(node)
    return _dotted(node) or "?"


def _joined_text(node: ast.JoinedStr) -> str:
    """Rebuild an f-string patch target as a dotted name.

    `patch(f"{MODULE}.Client")` names `MODULE.Client`. Collapsing it to an
    opaque placeholder instead made every templated target in a file the same
    anonymous collaborator.

    Returns:
        The literal parts joined with the dotted text of each interpolation.

    """
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            parts.append(_dotted(value.value) or "?")
    return "".join(parts)


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
