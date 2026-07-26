"""SARJ040: a mock built without `spec=` accepts any attribute — spec it or fake it.

An unspecced `Mock()` is the reason mock-based suites go green while production
breaks. It answers *every* attribute access with a fresh child mock, so a test
keeps passing after the collaborator it stands in for has been renamed, had a
parameter added, or lost the method entirely. The mock has no contract, so
nothing about it can rot loudly. `spec=`/`autospec=` restores the contract:
attribute access outside the real object's surface raises `AttributeError`, and
the double fails the moment the real type moves.

This is genuinely uncovered. The `flake8-tidy-imports` ban in the shared strict
config gates the *import* of `unittest.mock`, never the call-site keywords, and
ruff has no rule for spec discipline at any severity. In the audited corpora
only 60 of 556 mock constructions in one repo, and 0 of 59 in the other, passed
any spec argument.

Fires when ALL of these hold:

* the file is a test file (`test_*.py`, `*_test.py`, `conftest.py`, or under a
  `tests`/`test` directory) — spec discipline outside tests is a different
  argument, and production `Mock` use is already banned outright,
* the file actually imports `unittest.mock` in some form, and the callee
  resolves through that import to `Mock`, `MagicMock`, `AsyncMock`, `patch`, or
  `patch.object` — a locally-defined class that happens to be named `Mock` is
  never flagged, because the name is only trusted when the import backs it,
* and the call passes none of `spec=`, `spec_set=`, `autospec=`, `new=`,
  `new_callable=`, or `wraps=`.

Deliberately NOT flagged:

* `new=` / `new_callable=` on `patch` — the replacement is already a concrete
  object or factory chosen by the author, so autospec has nothing left to
  constrain,
* the SAME arguments passed positionally, which is how they are almost always
  spelled — see the exemptions below,
* `wraps=` — the double delegates to a real object, which supplies the same
  attribute-surface enforcement `spec=` would,
* `create_autospec(...)`, `mock.ANY`, `mock.sentinel`, `mock.call` — specced by
  construction or not doubles at all,
* bare `Mock` referenced without being called (annotations, `isinstance`
  checks) — only a construction can carry a spec argument.

The import-backed name check is the load-bearing false-positive guard. Test
suites routinely define their own `Mock`-suffixed fakes (`MockVisionBankClient`,
`MockSession`); those are hand-written doubles implementing a real interface,
which is precisely the pattern this rule steers toward, and flagging them would
invert the rule's intent.

EXEMPTIONS, WITH CORPUS EVIDENCE
--------------------------------

Measured over 2,657 files of popular third-party Python (fastapi, pydantic,
black, sqlmodel, rich, flask, httpx, requests, anyio), the keyword-only version
of this rule reported 137 hits, of which 38 were false positives:

1. **The replacement/spec passed POSITIONALLY (35 hits, 26%).** Every one of
   these signatures takes the escape hatch as a positional parameter:

       Mock(spec=None, wraps=None, ...)             # arg 1 is `spec`
       patch(target, new=DEFAULT, ...)              # arg 2 is `new`
       patch.object(target, attribute, new=DEFAULT) # arg 3 is `new`

   so `patch("black.dump_to_file", dump_to_stderr)` IS `new=dump_to_stderr` and
   `Mock(Process)` IS `spec=Process`. Checking only `node.keywords` made the
   rule's own documented `new=`/`spec=` carve-outs unreachable for the spelling
   authors actually use. Evidence: `black/tests/test_black.py:149` (`@patch(
   "black.dump_to_file", dump_to_stderr)`, 29 hits in that file alone),
   `anyio/tests/test_to_process.py:127` (`Mock(Process)`),
   `anyio/tests/test_sockets.py:1133` (`MagicMock(SocketListener)`),
   `requests/tests/test_requests.py:1020` (`mock.patch("os.environ", env)`),
   `anyio/tests/test_tempfile.py:71` (`patch.object(stf, "rollover",
   fake_rollover)`). Guard: an arity check per callee.

2. **The double is a stub function / call recorder (2 hits).** A mock that the
   file only ever *calls*, reading back nothing but the mock API
   (`assert_called_once_with`, `call_args_list`, `reset_mock`, ...), is not
   standing in for a typed object — it is the test's own recording apparatus,
   and `spec=<RealType>` has no referent to name. Evidence:
   `pydantic/tests/test_validators.py:1755` (`check_values = MagicMock()`,
   invoked from inside a field validator and read back only through
   `assert_called_once_with`) and `:1812` (`validate_stub`). Guard: exempt a
   double bound to a name that is called at least once and whose every
   attribute read belongs to the mock API. A double that is *handed to* the
   system under test stays flagged — production code can attribute-access it
   where the test cannot see, which is exactly what `spec=` guards.

3. **An import-failure stand-in (1 hit).** A mock built inside `except
   ImportError:` substitutes for a module that is *definitionally absent* on
   this platform; there is no importable type to spec against, by construction.
   Evidence: `anyio/tests/conftest.py:37` (`uvloop = Mock()` in the
   `except ImportError` arm of the uvloop/winloop probe). Guard: exempt
   constructions lexically inside an `ImportError`/`ModuleNotFoundError`
   handler.

The 99 survivors are true positives: unspecced `MagicMock()` doubles for real
types (`black/tests/test_black.py:2933`, a `MagicMock()` standing in for `Path`
and answering `.relative_to`/`.resolve`/`.is_dir`/`.is_file`), and
`patch.object(mod, "func")` replacements that `autospec=True` would give a
signature to (29 in `rich/tests/test_win32_console.py`). Not flagged as a false
positive after review: `patch()` used only as a context-manager side effect
(`black/tests/test_blackd.py:34`, `with patch("blackd.web.run_app"):`) — the
target is importable and `autospec=True` applies to it unchanged.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MOCK_MODULE = "unittest.mock"

# Constructors whose default is an attribute-permissive double.
_UNSPECCED_FACTORIES = frozenset({"Mock", "MagicMock", "AsyncMock"})

# `patch`/`patch.object` install a MagicMock unless told otherwise.
_PATCHERS = frozenset({"patch"})

# Any one of these gives the double a real contract to honour.
_SPEC_KEYWORDS = frozenset({"spec", "spec_set", "autospec", "new", "new_callable", "wraps"})

# How many positional arguments a callee must receive before the spec/new
# parameter is filled. `Mock(spec, wraps, ...)`, `patch(target, new, ...)` and
# `patch.object(target, attribute, new, ...)` all take it positionally, and that
# is how it is nearly always spelled, so an arity check is the only way to see
# the author's own escape hatch.
_REPLACEMENT_ARITY = {"Mock": 1, "MagicMock": 1, "AsyncMock": 1, "patch": 2, "patch.object": 3}

# Attributes every mock answers regardless of what it stands in for. A double
# read back only through these is a call recorder, not a stand-in for a type.
_MOCK_API_ATTRS = frozenset(
    {
        "assert_any_await",
        "assert_any_call",
        "assert_awaited",
        "assert_awaited_once",
        "assert_awaited_once_with",
        "assert_awaited_with",
        "assert_called",
        "assert_called_once",
        "assert_called_once_with",
        "assert_called_with",
        "assert_has_awaits",
        "assert_has_calls",
        "assert_not_awaited",
        "assert_not_called",
        "attach_mock",
        "await_args",
        "await_args_list",
        "await_count",
        "awaited",
        "call_args",
        "call_args_list",
        "call_count",
        "called",
        "configure_mock",
        "method_calls",
        "mock_add_spec",
        "mock_calls",
        "reset_mock",
        "return_value",
        "side_effect",
    }
)

# An import that failed leaves nothing importable to spec against.
_IMPORT_FAILURES = frozenset({"ImportError", "ModuleNotFoundError"})


class MockWithoutSpec(Rule):
    """A `unittest.mock` double built with no `spec=` accepts any attribute."""

    id: str = "mock-without-spec"
    code: str = "SARJ040"
    description: str = "Mock built without `spec=`/`autospec=` — it accepts any attribute and cannot rot loudly."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag `unittest.mock` constructions in test files that carry no spec argument.

        Returns:
            One diagnostic per unspecced mock construction, sorted by position.

        """
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        names = _MockNames.from_tree(tree)
        if not names.any_import:
            return []

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"`{label}` has no `spec=`/`autospec=` — it answers every attribute with a new "
                    "mock, so this test keeps passing after the real collaborator changes. Pass "
                    "`spec=<RealType>` (or `autospec=True`), or hand-roll a fake implementing the ABC."
                ),
            )
            for node, label in _unspecced_calls(tree, names, _FileFacts.from_tree(tree))
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _MockNames:
    """The local names through which `unittest.mock` is reachable in one file.

    `unittest.mock` is nearly always imported as a module (`from unittest import
    mock`) in the audited corpora, but the direct-symbol and aliased forms are
    equally valid, so all three are resolved. Names are only trusted when an
    import backs them — that is what keeps hand-written `MockFoo` doubles out.
    """

    def __init__(self) -> None:
        self.modules: set[str] = set()
        self.factories: dict[str, str] = {}

    @property
    def any_import(self) -> bool:
        """Report whether the file reaches `unittest.mock` at all.

        Returns:
            True when either a module alias or a direct symbol import was found.

        """
        return bool(self.modules or self.factories)

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
        # `import unittest.mock` binds `unittest`; `import unittest.mock as m` binds `m`.
        for alias in node.names:
            if alias.name == _MOCK_MODULE:
                self.modules.add(alias.asname or "unittest")

    def _add_from_import(self, node: ast.ImportFrom) -> None:
        if node.module == "unittest":
            # `from unittest import mock [as m]`
            for alias in node.names:
                if alias.name == "mock":
                    self.modules.add(alias.asname or "mock")
        elif node.module == _MOCK_MODULE:
            # `from unittest.mock import Mock [as m], patch`
            for alias in node.names:
                if alias.name in _UNSPECCED_FACTORIES or alias.name in _PATCHERS:
                    self.factories[alias.asname or alias.name] = alias.name

    def resolve(self, func: ast.expr) -> str | None:
        """Map a call's callee onto the `unittest.mock` symbol it invokes.

        Handles the bare (`Mock(...)`), module-qualified (`mock.Mock(...)`,
        `unittest.mock.Mock(...)`) and `patch.object(...)` spellings.

        Returns:
            The canonical symbol name, or None when the callee is unrelated.

        """
        if isinstance(func, ast.Name):
            return self.factories.get(func.id)
        if not isinstance(func, ast.Attribute):
            return None
        # `patch.object(...)` / `mock.patch.object(...)` — the patcher is the parent.
        if func.attr == "object":
            parent = self.resolve(func.value)
            return parent if parent in _PATCHERS else None
        if func.attr not in _UNSPECCED_FACTORIES and func.attr not in _PATCHERS:
            return None
        return func.attr if self._is_mock_module(func.value) else None

    def _is_mock_module(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.modules
        # `unittest.mock.Mock(...)` — the receiver is itself an attribute chain.
        if isinstance(node, ast.Attribute) and node.attr == "mock":
            return isinstance(node.value, ast.Name) and node.value.id in self.modules
        return False


class _FileFacts:
    """Per-file context the false-positive guards need.

    Two of the three guards are about how a double is *used*, not how it is
    built, so they need a whole-file view: which name each construction is bound
    to, what is read back off that name, and which constructions sit inside an
    import-failure handler.
    """

    def __init__(self) -> None:
        self.bound_name: dict[ast.Call, str] = {}
        self.reads: dict[str, set[str]] = {}
        self.called: set[str] = set()
        self.import_fallbacks: set[ast.Call] = set()

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _FileFacts:
        """Collect the name bindings, attribute reads, and import-failure arms of one file.

        Returns:
            The populated fact table.

        """
        found = cls()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                found._bind(node.targets[0] if len(node.targets) == 1 else None, node.value)
            elif isinstance(node, ast.AnnAssign):
                found._bind(node.target, node.value)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    found.reads.setdefault(node.value.id, set()).add(node.attr)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    found.called.add(node.func.id)
            elif isinstance(node, ast.ExceptHandler) and _catches_import_failure(node):
                found.import_fallbacks.update(child for child in ast.walk(node) if isinstance(child, ast.Call))
        return found

    def _bind(self, target: ast.expr | None, value: ast.expr | None) -> None:
        if isinstance(target, ast.Name) and isinstance(value, ast.Call):
            self.bound_name[value] = target.id

    def is_call_recorder(self, node: ast.Call) -> bool:
        """Report whether the double bound by `node` is only ever called and introspected.

        Such a double is a stub function / call recorder: the file invokes it and
        reads back nothing but the mock API, so there is no collaborator type for
        `spec=` to name. A double merely *handed* somewhere (a `return_value=`, an
        argument to the system under test) is not covered — production code can
        attribute-access it out of this file's sight.

        Returns:
            True when the bound name is called and read back only via the mock API.

        """
        name = self.bound_name.get(node)
        if name is None or name not in self.called:
            return False
        return self.reads.get(name, set()) <= _MOCK_API_ATTRS


def _catches_import_failure(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    if caught is None:
        return False
    parts = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(isinstance(p, ast.Name) and p.id in _IMPORT_FAILURES for p in parts)


def _unspecced_calls(tree: ast.Module, names: _MockNames, facts: _FileFacts) -> list[tuple[ast.Call, str]]:
    hits: list[tuple[ast.Call, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        symbol = names.resolve(node.func)
        if symbol is None:
            continue
        label = _render_callee(node.func, symbol)
        if _has_spec_argument(node) or _has_positional_replacement(node, label):
            continue
        if node in facts.import_fallbacks or facts.is_call_recorder(node):
            continue
        hits.append((node, label))
    return hits


def _has_spec_argument(node: ast.Call) -> bool:
    # `**kwargs` forwarding could smuggle a spec in; treat it as specced rather
    # than guess, since the call site no longer states its own contract.
    return any(kw.arg is None or kw.arg in _SPEC_KEYWORDS for kw in node.keywords)


def _has_positional_replacement(node: ast.Call, label: str) -> bool:
    # `spec` / `new` are positional parameters of these signatures, and that is
    # how they are nearly always spelled — `patch("mod.fn", replacement)` is
    # `new=replacement`, `Mock(Process)` is `spec=Process`.
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        # `*args` forwarding: the arity is unknown, so decline to guess.
        return True
    return len(node.args) >= _REPLACEMENT_ARITY[label]


def _render_callee(func: ast.expr, symbol: str) -> str:
    if isinstance(func, ast.Attribute) and func.attr == "object":
        return f"{symbol}.object"
    return symbol
