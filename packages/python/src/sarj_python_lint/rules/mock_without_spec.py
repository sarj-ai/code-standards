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
            for node, label in _unspecced_calls(tree, names)
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


def _unspecced_calls(tree: ast.Module, names: _MockNames) -> list[tuple[ast.Call, str]]:
    hits: list[tuple[ast.Call, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        symbol = names.resolve(node.func)
        if symbol is None or _has_spec_argument(node):
            continue
        hits.append((node, _render_callee(node.func, symbol)))
    return hits


def _has_spec_argument(node: ast.Call) -> bool:
    # `**kwargs` forwarding could smuggle a spec in; treat it as specced rather
    # than guess, since the call site no longer states its own contract.
    return any(kw.arg is None or kw.arg in _SPEC_KEYWORDS for kw in node.keywords)


def _render_callee(func: ast.expr, symbol: str) -> str:
    if isinstance(func, ast.Attribute) and func.attr == "object":
        return f"{symbol}.object"
    return symbol
