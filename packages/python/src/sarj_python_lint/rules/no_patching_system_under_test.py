"""SARJ058: a test that mocks out the unit's own logic verifies the mock, not the unit.

Mocking is a boundary tool. Replacing a collaborator the unit *talks to* — an
HTTP client, a store, a clock — keeps the unit's own behaviour under test. Ripping
out a function or method the unit *is made of* does the opposite: the code path
the test claims to cover no longer runs. `patch.object(Paginator,
"validate_number")` followed by `paginator.get_elided_page_range(2)` proves only
that `get_elided_page_range` calls a mock the test installed a line earlier. Delete
the real `validate_number` and the test still passes.

The failure mode is quiet and permanent. The mock answers with whatever the test
said, so the assertions describe the test's own fixture data; the real branch,
its error handling, and every later change to it are unguarded. Worse, the test
now pins an *internal* call shape, so refactoring the unit — inlining the helper,
renaming it, moving the work — breaks a test that was supposed to be describing
behaviour.

**Cross-file resolution is impossible here, so the rule only fires on shapes it
can prove from one file.** Both are deliberately narrow.

Shape 1 — a sibling of the symbol under test:

* the test does `from <mod> import <names>` and patches `"<mod>.<attr>"` where
  `<attr>` is *itself* one of the names this test file imported from `<mod>` —
  which is the only local proof that `<attr>` is a member of that module rather
  than something the module imported from elsewhere, and
* **the enclosing function itself enters `<mod>`**, either by calling another of
  the names imported from it or through a module alias the file binds (`from
  airflow.security import kerberos` … `kerberos.run(...)`). The evidence has to be
  in the same function as the patch; see the pooled-evidence bullet below.

Shape 2 — the object under test, with a hole in it:

* `patch.object(X, "<attr>")` where the same function constructs `X(...)` (or binds
  a local from a constructor call), `X` is imported from a non-stdlib module, and
* the same function then calls some *other* attribute on that same object. The
  test builds the unit, cuts a method out of it, and exercises what is left.

Deliberately NOT flagged:

* **Patching the SUT module's reference to an external dependency** — the "patch
  where it's used" idiom, `patch("app.billing.requests")` /
  `patch("app.billing.stripe_client")`. The target string names the SUT module but
  the attribute is a third-party import the SUT happens to hold, and patching it is
  correct practice. This is the dominant population: relaxing shape 1 to "any
  attribute of an imported module" produced 86 celery, 14 django and 12 bulbul
  extra hits, and every one sampled was this idiom — `patch(
  "integration.task_executor.rtc")` (livekit's `rtc` module,
  `bulbul/integration/tests/unit/test_task_executor.py:188`), `patch(
  "agent.lk.call_manager.add_span_attributes")` (a telemetry helper,
  `bulbul/agent/tests/test_call_manager.py:475`), `patch(
  "bulbul.services.message_enqueuer.inject")` (a DI decorator,
  `bulbul/tests/services/test_message_enqueuer.py:49`), `patch(
  "django.contrib.auth.hashers.get_random_string")` (imported from
  `django.utils.crypto`, `django/tests/auth_tests/test_hashers.py:469`), `patch(
  "celery.backends.database.session.sessionmaker")` (SQLAlchemy,
  `celery/t/unit/backends/test_database.py:808`). Requiring the patched attribute
  to be a name the test file *itself* imported from that module removes all of
  them: a re-exported third-party symbol is not something a test imports from the
  wrapper module,
* **evidence borrowed from a sibling test.** The proof that `<mod>` is the unit
  under test must live in the same function as the patch. Pooling it file-wide let
  one test license another's unrelated patch:
  `litellm/tests/test_litellm/router_utils/test_health_check_allowed_fails_integration.py:661`
  patches `cooldown_handlers._set_cooldown_deployments` while exercising
  `proxy_server._write_health_state_to_router_cache` — a different module
  entirely — and the `from ...cooldown_handlers import _set_cooldown_deployments`
  that licensed it is a function-local import inside a sibling test 400 lines up.
  Test files that import a module in a dozen different test bodies made this the
  single largest false-positive class,
* **module singletons.** A snake_case target that the file only ever drives
  through its attributes and never calls is an object, not a function:
  `patch("...mcp_server_manager.global_mcp_server_manager")` (declared
  `global_mcp_server_manager: MCPServerManager = MCPServerManager()` and patched 83
  times across two litellm suites, always via `mock_mgr.expand_permission_list...`)
  and `patch("celery.platforms.signals")` (`celery/t/unit/utils/test_platforms.py`,
  used as `signals.supported('INT')`). Swapping a module-level singleton is the
  canonical dependency-injection seam — the opposite of the defect,
* **classes and constants.** Only a plain function-shaped name (`snake_case`,
  optionally one leading underscore) is a candidate. A CapWords target is a
  collaborator *type* being swapped for a double — the ordinary seam, e.g. `patch(
  "agent.lk.agent_tools.data_capture.collect_via_dtmf_tool._CollectViaDtmfTask")`
  in `bulbul/agent/tests/test_collect_digits_tool.py:663`, which stands in for a
  LiveKit task — and an ALL_CAPS target is a config knob, e.g. `monkeypatch.setattr(
  "bulbul.calls.batch_call_store.MAX_CONCURRENT_OUTBOUND_CALLS_PER_ORG", 2)`.
  Dunders (`__call__`, `__init__`) fall out of the same check: they are framework
  hooks, not the unit's logic,
* **boundary-shaped attribute names** — `*_client`, `*_session`, `connection`,
  `engine`, `pool`, `bucket`, `broker`, `socket`, `logger` and friends. A module
  global with that name is an I/O handle, and replacing it is the whole point of
  the seam,
* **a concrete replacement.** `new=` (keyword or positional — arg 2 of `patch`,
  arg 3 of `patch.object`), `new_callable=` and `wraps=` all mean the author wrote
  a substitute rather than accepting an auto-generated `MagicMock`. So does a
  `side_effect=` that delegates back to the real symbol, which is the spy idiom:
  `patch("django.db.models.sql.compiler.cursor_iter", side_effect=cursor_iter)`
  (`django/tests/queries/test_iterator.py:29`) and `patch.object(hasher, "encode",
  side_effect=hasher.encode)` (`django/tests/auth_tests/test_hashers.py:221`) both
  keep the real behaviour and only count calls,
* **`side_effect=<Exception>`.** A mock that raises is a tripwire or a fault
  injector, never a stand-in for the real answer, and the code path being proved is
  the *caller's* — which does run. `patch.object(handler, "format_subject",
  side_effect=AssertionError("Should not be called"))` proves `emit` short-circuits
  when `ADMINS` is empty (`django/tests/logging_tests/tests.py:570`);
  `patch.object(manager, "persist_parsing_result", side_effect=RuntimeError("boom"))`
  proves the parsing loop still records stats
  (`airflow/airflow-core/tests/unit/dag_processing/test_manager.py:1302`);
  `patch("prefect._internal.send_entrypoint_logs._send", side_effect=Exception(...))`
  is a test named `test_silently_swallows_exceptions`
  (`prefect/tests/_internal/test_send_entrypoint_logs.py:115`),
* **`monkeypatch.setattr` in every spelling.** pytest's `setattr` requires a
  replacement value, so it is *always* the concrete-replacement case above — a
  hand-written fake, which is the practice this rule steers toward. It is also the
  house idiom in the audited repos (464 call sites across bulbul and noura-be
  against 243 `mock.patch*` calls); flagging it would bury the signal,
* **stdlib types.** `out = StringIO(); patch.object(out, "flush")` while
  `management.call_command(...)` runs (`django/tests/user_commands/tests.py:454`)
  patches a stdlib buffer, not the unit. The constructor's import module is checked
  against `sys.stdlib_module_names`,
* **test-local classes and factories.** If the class, or the factory that built the
  instance, is defined in the test file, the object is a stub the suite wrote for
  itself, not the production unit: `DoNothingDecorator` in
  `django/tests/test_utils/tests.py:2460` (a two-method `TestContextDecorator`
  subclass declared right above the test) and `no_pool_connection()` in
  `django/tests/backends/postgresql/tests.py:478`,
* **an object that is patched but never exercised through its own surface.**
  `hasher = get_hasher("default"); patch.object(hasher, "verify"); check_password(...)`
  hands the hasher to a module-level function — there the hasher IS the
  collaborator. Shape 2 requires a call to another attribute *of the patched
  object* in the same function,
* `patch` reached through a name no `unittest.mock` import backs — a project's own
  `patch` helper is not this rule's business.

KNOWN LIMIT
-----------

The rule cannot separate a helper that *is* the unit's logic from an I/O boundary
the SUT happens to spell as a private function of its own module. Both are
snake_case members of the module under test, both are imported by the test, and
nothing syntactic tells them apart. `patch("sentry_sdk.utils.get_git_revision")`
(`sentry-python/tests/test_utils.py:704`) shells out to `git`;
`patch("corporate.lib.stripe.get_latest_seat_count")`
(`zulip/corporate/tests/test_stripe.py:3065`) is a database aggregate;
`patch("zerver.lib.send_email._send_messages")`
(`zulip/zerver/tests/test_send_email.py:210`) opens SMTP. Each is a legitimate
seam that this rule flags. A verb-prefix heuristic was measured and rejected: 43%
of all hits are I/O-verb-prefixed (`get_`, `send_`, `read_`, `write_`, `fetch_`),
so it would take most of the true positives with it. These are what
`# sarj-noqa: SARJ058` is for.

CORPUS EVIDENCE
---------------

Measured over 19 repos — bulbul, noura-be, digital-bank, submissions, ai and the
14 OSS corpora, 40,336 Python files. `before` is the rule as first written;
`after` is with the three guards above (function-local evidence, module
singletons, `side_effect=<Exception>`):

| corpus        | before | after |
|---------------|--------|-------|
| bulbul        | 0      | 0     |
| noura-be      | 0      | 0     |
| digital-bank  | 0      | 0     |
| submissions   | 0      | 0     |
| ai            | 1      | 1     |
| airflow       | 512    | 494   |
| dagster       | 34     | 26    |
| litellm       | 755    | 645   |
| saleor        | 0      | 0     |
| django        | 11     | 10    |
| mlflow        | 273    | 216   |
| langchain     | 2      | 2     |
| superset      | 115    | 102   |
| zulip         | 146    | 130   |
| prefect       | 36     | 34    |
| fastapi       | 0      | 0     |
| warehouse     | 0      | 0     |
| sentry-python | 5      | 5     |
| celery        | 78     | 71    |
| **total**     | 1968   | 1736  |

**Every guard costs zero first-party hits** — bulbul, noura-be, digital-bank and
submissions are 0 before and after, and `ai`'s single hit survives all three, so
all 232 removals are OSS. Applied on its own to the unguarded rule, the
function-local guard removes 196, the singleton guard 76 and the tripwire guard
30; they overlap heavily (63 of the singleton removals are also pooled-evidence
removals), so dropping one guard from the finished rule re-adds 126, 12 and 24
respectively.

The module-alias half of the function-local guard is what keeps it honest. The
naive form — "a bare call to another name imported from `<mod>`, in this
function" — removes a comparable 199, but 18 of those are real findings reached
through the module object rather than a bare name: `@mock.patch(
"airflow.security.kerberos.renew_from_kt")` on a test whose body runs
`kerberos.run(...)` and asserts `mock_renew_from_kt.mock_calls == [...]`
(`airflow/airflow-core/tests/unit/security/test_kerberos.py:306`), and
`mock.patch("mlflow.utils.databricks_utils.get_workspace_id")` around
`databricks_utils._print_databricks_deployment_job_url(...)`
(`mlflow/tests/utils/test_databricks_utils.py:964`). Resolving `kerberos` back to
`airflow.security.kerberos` recovers all 18 and still removes every one of the 96
litellm pooled-evidence hits.

All 11 original django hits and 10 sampled celery hits were read at the cited
line, as were every removal of the tripwire guard and a sample of the other two.
The remaining hits are the real pattern, and most of them assert on the mock and
nothing else: `django/tests/pagination/tests.py:597` (`patch.object(paginator,
"validate_number")` then `paginator.get_elided_page_range(2)`, whose only
assertion is `mock.assert_called_with(2)`),
`django/tests/backends/oracle/test_creation.py:43` and
`django/tests/backends/postgresql/test_creation.py:105` (`DatabaseCreation.
_create_test_db` exercised with `_test_user_create` / `_database_exists` mocked
out), `django/tests/auth_tests/test_hashers.py:462` (`check_password` called with
its module siblings `identify_hasher` and `make_password` both mocked),
`celery/t/unit/backends/test_gcs.py:105` (`GCSBackend(...).get(...)` with
`_get_blob` and `_is_firestore_ttl_policy_enabled` mocked, asserting
`mock_get_blob.assert_called_once_with("testkey1")`),
`celery/t/unit/contrib/test_migrate.py:209` (`move_by_taskmap(...)` with its own
module's `move` mocked, asserting `move.assert_called()`),
`celery/t/unit/utils/test_platforms.py:97` (`set_mp_process_title(...)` with the
sibling `set_process_title` mocked, asserting only that it was called) and
`celery/t/unit/tasks/test_chord.py:228` (`ch.apply_async()` with `ch.run`
replaced, asserting `run.assert_called_once_with(...)`).

celery's remaining 71 are concentrated: `t/unit/backends/test_gcs.py` (39) and
`t/unit/utils/test_platforms.py` (24) account for 63 of them, both suites that
mock a module's own functions and assert on the mock. The rule is a real finding
there, not noise, but a codebase adopting it mid-flight should expect to
`# sarj-noqa: SARJ058` the deliberate cases — a sibling that really is slow or
privileged (`celery.platforms.setuid`) is exactly what suppression is for.

The rule finds nothing in bulbul or noura-be today. Both reach for
`monkeypatch.setattr` with a hand-written replacement (464 sites) rather than an
auto-generated `MagicMock`, which is the practice this rule exists to protect, so
zero is the right answer there rather than evidence the rule is dead.
"""

from __future__ import annotations

import ast
import re
import sys
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MOCK_MODULE = "unittest.mock"
_PATCH = "patch"
_PATCH_OBJECT = "patch.object"
_OBJECT = "object"

# A plain function/method name: snake_case with at most one leading underscore.
# CapWords targets are collaborator *types* being doubled, ALL_CAPS targets are
# config knobs, and dunders are framework hooks — none is the unit's own logic.
_PLAIN_FUNCTION_RE = re.compile(r"^_?[a-z][a-z0-9_]*$")

# Module globals named like this are I/O handles. Replacing one IS the seam.
_BOUNDARY_NAME_RE = re.compile(
    r"(^|_)(client|session|conn|connection|engine|pool|db|api|bus|broker|transport"
    r"|channel|socket|http|requests|redis|s3|bucket|queue|producer|consumer|publisher"
    r"|logger|log|cache|store|repo|repository)s?$",
    re.IGNORECASE,
)

# A `side_effect=` naming one of these installs a mock that raises. That is a
# tripwire or a fault injector, not a stand-in for the real answer.
_EXCEPTION_NAME_RE = re.compile(r"(Error|Exception|Warning|Exit|Interrupt|Timeout|Abort)$")

# Any of these means the author supplied a substitute instead of taking a MagicMock.
_CONCRETE_REPLACEMENT_KEYWORDS = frozenset({"new", "new_callable", "wraps"})

# Positional slot that holds `new` in each signature: `patch(target, new, ...)`,
# `patch.object(target, attribute, new, ...)`.
_REPLACEMENT_ARITY = {_PATCH: 2, _PATCH_OBJECT: 3}

# `patch.object(target, attribute)` — both are needed before there is anything to judge.
_PATCH_OBJECT_MIN_ARGS = 2

_STDLIB_MODULES = frozenset(sys.stdlib_module_names)

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class NoPatchingSystemUnderTest(Rule):
    """Mocking a function or method of the unit under test verifies the mock."""

    id: str = "no-patching-system-under-test"
    code: str = "SARJ058"
    description: str = "Test patches a function/method of the unit it exercises — the real code path never runs."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag patches that replace part of the unit the test then exercises.

        Returns:
            One diagnostic per self-patch, sorted by position.

        """
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        facts = _ModuleFacts.from_tree(tree)
        if not facts.reaches_mock:
            return []

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"this patches `{target}`, which belongs to the unit this test then exercises, so "
                    "the real code path never runs and the assertions only describe the mock. Patch at "
                    "the boundary the unit talks to instead, or exercise the real method."
                ),
            )
            for node, target in _self_patches(tree, facts)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _ModuleFacts:
    """Whole-file context needed to decide what a patch target belongs to.

    Every judgement this rule makes is local: which module a name came from, which
    names the file imported from a given module, what the file defines itself, and
    how it uses each name. Cross-file resolution is out of reach, so these tables
    are the entire evidence base.
    """

    def __init__(self) -> None:
        self.patch_aliases: set[str] = set()
        self.mock_modules: set[str] = set()
        self.imported_from: dict[str, set[str]] = {}
        self.origin: dict[str, str] = {}
        self.module_aliases: dict[str, str] = {}
        self.local_defs: set[str] = set()
        self.called: set[str] = set()
        self.receivers: set[str] = set()

    @property
    def reaches_mock(self) -> bool:
        """Report whether the file can name `unittest.mock.patch` at all.

        Returns:
            True when either a module alias or a direct `patch` import was found.

        """
        return bool(self.patch_aliases or self.mock_modules)

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _ModuleFacts:
        """Collect the import, definition and usage tables of one module.

        Returns:
            The populated fact table.

        """
        found = cls()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found._add_import(node)
            elif isinstance(node, ast.ImportFrom):
                found._add_from_import(node)
            elif isinstance(node, (*_FUNC_NODES, ast.ClassDef)):
                found.local_defs.add(node.name)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                found.called.add(node.func.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                found.receivers.add(node.value.id)
        return found

    def _add_import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == _MOCK_MODULE:
                self.mock_modules.add(alias.asname or "unittest")
            if alias.asname:
                self.module_aliases[alias.asname] = alias.name

    def _add_from_import(self, node: ast.ImportFrom) -> None:
        if node.module == "unittest":
            self.mock_modules.update(a.asname or a.name for a in node.names if a.name == "mock")
            return
        if node.module == _MOCK_MODULE:
            self.patch_aliases.update(a.asname or a.name for a in node.names if a.name == _PATCH)
            return
        # A relative import cannot be turned into the absolute dotted path a
        # `patch("...")` target string uses, so it is not usable evidence.
        if node.module is None or node.level:
            return
        bound = {a.asname or a.name for a in node.names}
        self.imported_from.setdefault(node.module, set()).update(bound)
        for name in bound:
            self.origin[name] = node.module

    def patcher(self, func: ast.expr) -> str | None:
        """Map a callee onto the `unittest.mock` patcher it invokes.

        Returns:
            `"patch"`, `"patch.object"`, or None when the callee is something else.

        """
        if isinstance(func, ast.Name):
            return _PATCH if func.id in self.patch_aliases else None
        if not isinstance(func, ast.Attribute):
            return None
        if func.attr == _OBJECT:
            return _PATCH_OBJECT if self.patcher(func.value) == _PATCH else None
        if func.attr != _PATCH:
            return None
        return _PATCH if self._is_mock_module(func.value) else None

    def _is_mock_module(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.mock_modules
        # `unittest.mock.patch(...)` — the receiver is itself an attribute chain.
        return isinstance(node, ast.Attribute) and node.attr == "mock" and self._is_mock_module(node.value)

    def is_module_under_test(self, module: str, attr: str, scope: _Scope) -> bool:
        """Report whether `module.attr` is a symbol this file imports and *this function* exercises.

        Two conditions, and both matter. The file must import `attr` itself from
        `module` — that is the only local proof `attr` is a member of `module`
        rather than a third-party name `module` re-exports. And the function
        holding the patch must itself enter `module`, which is what makes `module`
        the unit under test rather than an incidental dependency of some other
        test in the same file. Entering it counts either way round: calling
        another name imported from it, or calling through a module alias.

        Returns:
            True when the patched symbol is a sibling of something this test runs.

        """
        names = self.imported_from.get(module)
        if names is None or attr not in names:
            return False
        if (names - {attr}) & scope.calls:
            return True
        return any(self.resolve_module(dotted) == module for dotted in scope.calls_through)

    def resolve_module(self, dotted: str) -> str:
        """Expand a call receiver into the dotted module path it stands for.

        `import a.b as x` makes `x.f()` a call into `a.b`; `from a import b` makes
        `b.f()` a call into `a.b` when `b` is a submodule. Anything else is already
        absolute or unresolvable, and is returned unchanged.

        Returns:
            The receiver with its head segment expanded.

        """
        head, _, rest = dotted.partition(".")
        base = self.module_aliases.get(head)
        if base is None:
            package = self.origin.get(head)
            base = f"{package}.{head}" if package else head
        return f"{base}.{rest}" if rest else base

    def is_module_singleton(self, attr: str) -> bool:
        """Report whether `attr` names an object the file drives rather than a function it calls.

        `global_mcp_server_manager.expand_permission_list(...)` with no bare
        `global_mcp_server_manager(...)` anywhere is a module-level instance, and
        swapping one is the dependency-injection seam this rule steers toward.

        Returns:
            True when the name is only ever an attribute receiver.

        """
        return attr in self.receivers and attr not in self.called

    def is_locally_manufactured(self, constructor: str) -> bool:
        """Report whether `constructor` names a class or factory this test file defines.

        Returns:
            True for a test-local stub class or helper factory, or an unimported name.

        """
        if constructor in self.local_defs:
            return True
        module = self.origin.get(constructor)
        return module is None or module.split(".")[0] in _STDLIB_MODULES


class _Scope:
    """What one function body does with its local names.

    Both shapes need facts confined to a single function: which names it calls and
    through which receivers (shape 1's proof that this test enters the module it
    patches), and which classes it constructs, which locals hold the result of a
    construction and which attributes it calls on each name (shape 2).
    """

    def __init__(self) -> None:
        self.built_by: dict[str, str] = {}
        self.attr_calls: dict[str, set[str]] = {}
        self.calls: set[str] = set()
        self.calls_through: set[str] = set()

    @classmethod
    def of(cls, func: ast.FunctionDef | ast.AsyncFunctionDef) -> _Scope:
        """Index the constructions and calls inside one function.

        Returns:
            The populated scope table.

        """
        found = cls()
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                found._bind(node.targets[0], node.value)
            elif isinstance(node, ast.Call):
                found._record_call(node)
        return found

    def _bind(self, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name) and isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            self.built_by[target.id] = value.func.id

    def _record_call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            self.calls.add(func.id)
        elif isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name):
                self.attr_calls.setdefault(func.value.id, set()).add(func.attr)
            receiver = _dotted_name(func.value)
            if receiver is not None:
                self.calls_through.add(receiver)

    def constructor_of(self, name: str) -> str | None:
        """Find the class or factory that produced the object `name` refers to.

        Returns:
            The constructor's name — `name` itself when the class is constructed
            directly in this function — or None when nothing local built it.

        """
        if name in self.built_by:
            return self.built_by[name]
        return name if name in self.calls else None

    def other_attrs_called_on(self, name: str, patched: str) -> bool:
        """Report whether the function calls some *other* attribute of the patched object.

        Covers both spellings: the local instance itself, and any instance built
        from a patched class in the same body.

        Returns:
            True when the object's remaining surface is exercised here.

        """
        exercised = set(self.attr_calls.get(name, ()))
        for local, constructor in self.built_by.items():
            if constructor == name:
                exercised |= self.attr_calls.get(local, set())
        return bool(exercised - {patched})


def _self_patches(tree: ast.Module, facts: _ModuleFacts) -> list[tuple[ast.Call, str]]:
    hits: list[tuple[ast.Call, str]] = []
    for func in _top_level_functions(tree):
        patches = _patch_calls(func, facts)
        if not patches:
            continue
        # `_Scope` costs a second walk of the body, so it is built only for the
        # minority of functions that actually reach for a patcher.
        scope = _Scope.of(func)
        for node, kind in patches:
            target = (
                _sibling_of_unit_under_test(node, facts, scope)
                if kind == _PATCH
                else _method_of_object_under_test(node, facts, scope)
            )
            if target is not None:
                hits.append((node, target))
    return hits


def _patch_calls(func: ast.FunctionDef | ast.AsyncFunctionDef, facts: _ModuleFacts) -> list[tuple[ast.Call, str]]:
    """Find the `unittest.mock` patcher calls inside one function, decorators included.

    Returns:
        Each call paired with the patcher it invokes.

    """
    found: list[tuple[ast.Call, str]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        kind = facts.patcher(node.func)
        if kind is not None:
            found.append((node, kind))
    return found


def _top_level_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Collect the module-level functions and class methods of one module.

    Walking these rather than every `FunctionDef` keeps the check to a single pass
    over each body — a nested closure is visited as part of its enclosing function,
    not a second time on its own.

    Returns:
        Every function whose parent is the module or a class.

    """
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    containers: list[ast.Module | ast.ClassDef] = [tree]
    while containers:
        for stmt in containers.pop().body:
            if isinstance(stmt, ast.ClassDef):
                containers.append(stmt)
            elif isinstance(stmt, _FUNC_NODES):
                found.append(stmt)
    return found


def _sibling_of_unit_under_test(node: ast.Call, facts: _ModuleFacts, scope: _Scope) -> str | None:
    """Match shape 1: `patch("<mod>.<attr>")` on a sibling of the symbol being tested.

    Returns:
        The dotted target when it names a member of the module under test.

    """
    dotted = _string_arg(node.args[0])
    if dotted is None:
        return None
    module, _, attr = dotted.rpartition(".")
    if not _is_own_logic(attr) or facts.is_module_singleton(attr):
        return None
    if _has_concrete_replacement(node, _PATCH, attr) or _raises_instead_of_answering(node):
        return None
    return dotted if facts.is_module_under_test(module, attr, scope) else None


def _method_of_object_under_test(node: ast.Call, facts: _ModuleFacts, scope: _Scope) -> str | None:
    """Match shape 2: `patch.object(X, "m")` on an object this function builds and drives.

    Returns:
        A `Class.method` label when the patched object is the unit under test.

    """
    if len(node.args) < _PATCH_OBJECT_MIN_ARGS or not isinstance(node.args[0], ast.Name):
        return None
    name = node.args[0].id
    attr = _string_arg(node.args[1])
    if attr is None or not _is_own_logic(attr) or _raises_instead_of_answering(node):
        return None
    if _has_concrete_replacement(node, _PATCH_OBJECT, attr, name):
        return None
    constructor = scope.constructor_of(name)
    if constructor is None or facts.is_locally_manufactured(constructor):
        return None
    return f"{constructor}.{attr}" if scope.other_attrs_called_on(name, attr) else None


def _is_own_logic(attr: str) -> bool:
    return bool(_PLAIN_FUNCTION_RE.match(attr)) and not _BOUNDARY_NAME_RE.search(attr)


def _has_concrete_replacement(node: ast.Call, patcher: str, attr: str, receiver: str | None = None) -> bool:
    """Report whether the patch installs an author-written substitute rather than a mock.

    Returns:
        True for `new=` (positional or keyword), `new_callable=`, `wraps=`, `**kwargs`
        forwarding, or a `side_effect=` that delegates back to the real symbol.

    """
    if any(isinstance(arg, ast.Starred) for arg in node.args) or len(node.args) >= _REPLACEMENT_ARITY[patcher]:
        return True
    return any(
        kw.arg is None
        or kw.arg in _CONCRETE_REPLACEMENT_KEYWORDS
        or (kw.arg == "side_effect" and _delegates_to_real(kw.value, attr, receiver))
        for kw in node.keywords
    )


def _raises_instead_of_answering(node: ast.Call) -> bool:
    """Report whether the patch installs a mock that raises rather than one that answers.

    `side_effect=AssertionError("Should not be called")` is a tripwire and
    `side_effect=RuntimeError("boom")` is a fault injector. Neither stands in for
    the unit's own logic, and the path being proved is the caller's, which runs.

    Returns:
        True when `side_effect=` names an exception class or builds an instance of one.

    """
    return any(kw.arg == "side_effect" and _names_an_exception(kw.value) for kw in node.keywords)


def _names_an_exception(value: ast.expr) -> bool:
    called = value.func if isinstance(value, ast.Call) else value
    name = called.attr if isinstance(called, ast.Attribute) else called.id if isinstance(called, ast.Name) else ""
    return bool(_EXCEPTION_NAME_RE.search(name))


def _delegates_to_real(value: ast.expr, attr: str, receiver: str | None) -> bool:
    # The spy idiom: `side_effect=cursor_iter` alongside
    # `patch("...compiler.cursor_iter")`, or `side_effect=hasher.encode` alongside
    # `patch.object(hasher, "encode")`. Real behaviour is kept; calls are counted.
    if isinstance(value, ast.Name):
        return value.id == attr
    if not isinstance(value, ast.Attribute) or value.attr != attr:
        return False
    return receiver is None or (isinstance(value.value, ast.Name) and value.value.id == receiver)


def _dotted_name(node: ast.expr) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _string_arg(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None
