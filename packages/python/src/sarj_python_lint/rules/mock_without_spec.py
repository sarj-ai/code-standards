"""SARJ040 — A mock built without `spec=` accepts any attribute — spec it or fake it.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_mock_without_spec.py
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk
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

# Keywords that canned-answer a *call*. You only say what a double returns, or
# raises, when something is going to invoke it — so their presence is positive
# evidence that the double stands in for one callable rather than an object.
_CANNED_RESULT_KEYWORDS = frozenset({"return_value", "side_effect"})


class MockWithoutSpec(Rule):
    id: str = "mock-without-spec"
    code: str = "SARJ040"
    description: str = "Mock built without `spec=`/`autospec=` — it accepts any attribute and cannot rot loudly."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag `unittest.mock` constructions in test files that carry no spec argument."""
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
    """The local names through which `unittest.mock` is reachable in one file."""

    def __init__(self) -> None:
        self.modules: set[str] = set()
        self.factories: dict[str, str] = {}

    @property
    def any_import(self) -> bool:
        """Report whether the file reaches `unittest.mock` at all."""
        return bool(self.modules or self.factories)

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _MockNames:
        """Collect every local binding that resolves to `unittest.mock`."""
        found = cls()
        for node in nodes(tree, ast.Import, ast.ImportFrom):
            if isinstance(node, ast.Import):
                found._add_plain_import(node)
            else:
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
        """Map a call's callee onto the `unittest.mock` symbol it invokes."""
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
    """Per-file context the false-positive guards need."""

    def __init__(self) -> None:
        self.bound_name: dict[ast.Call, str] = {}
        self.reads: dict[str, set[str]] = {}
        self.called: set[str] = set()
        self.import_fallbacks: set[ast.Call] = set()
        self.attribute_target: dict[ast.Call, str] = {}
        self.path_reads: dict[str, set[str]] = {}
        self.path_calls: set[str] = set()

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _FileFacts:
        """Collect the name bindings, attribute reads, and import-failure arms of one file."""
        found = cls()
        for node in nodes(tree, ast.Assign, ast.AnnAssign, ast.Attribute, ast.Call, ast.ExceptHandler):
            if isinstance(node, ast.Assign):
                found._bind(node.targets[0] if len(node.targets) == 1 else None, node.value)
            elif isinstance(node, ast.AnnAssign):
                found._bind(node.target, node.value)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    found.reads.setdefault(node.value.id, set()).add(node.attr)
                found._record_path_read(node)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    found.called.add(node.func.id)
                found._record_path_call(node)
            elif _catches_import_failure(node):
                found.import_fallbacks.update(child for child in walk(node) if isinstance(child, ast.Call))
        return found

    def _bind(self, target: ast.expr | None, value: ast.expr | None) -> None:
        if not isinstance(value, ast.Call):
            return
        if isinstance(target, ast.Name):
            self.bound_name[value] = target.id
        elif isinstance(target, ast.Attribute):
            path = _dotted_path(target)
            if path is not None:
                self.attribute_target[value] = path

    def _record_path_read(self, node: ast.Attribute) -> None:
        # Load context only. `recv.method = Mock()` is a *store* through
        # `recv.method`; counting it would make every stub look like a namespace
        # double read back through its own name.
        if not isinstance(node.ctx, ast.Load):
            return
        path = _dotted_path(node.value)
        if path is not None:
            self.path_reads.setdefault(path, set()).add(node.attr)

    def _record_path_call(self, node: ast.Call) -> None:
        path = _dotted_path(node.func)
        if path is not None:
            self.path_calls.add(path)

    def is_call_recorder(self, node: ast.Call) -> bool:
        """Report whether the double bound by `node` is only ever called and introspected."""
        name = self.bound_name.get(node)
        if name is None or name not in self.called:
            return False
        return self.reads.get(name, set()) <= _MOCK_API_ATTRS

    def is_method_stub(self, node: ast.Call) -> bool:
        """Report whether `node` is a canned stub for one method of some receiver."""
        path = self.attribute_target.get(node)
        if path is None:
            return False
        seen = self.path_reads.get(path, set())
        if not seen <= _MOCK_API_ATTRS:
            return False
        canned = any(kw.arg in _CANNED_RESULT_KEYWORDS for kw in node.keywords)
        return canned or bool(seen) or path in self.path_calls


def _dotted_path(expr: ast.expr) -> str | None:
    """Render a pure `name.attr.attr` chain as a dotted string."""
    parts: list[str] = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name):
        return None
    parts.append(expr.id)
    return ".".join(reversed(parts))


def _catches_import_failure(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    if caught is None:
        return False
    parts = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(isinstance(p, ast.Name) and p.id in _IMPORT_FAILURES for p in parts)


def _unspecced_calls(tree: ast.Module, names: _MockNames, facts: _FileFacts) -> list[tuple[ast.Call, str]]:
    hits: list[tuple[ast.Call, str]] = []
    for node in nodes(tree, ast.Call):
        symbol = names.resolve(node.func)
        if symbol is None:
            continue
        label = _render_callee(node.func, symbol)
        if _has_spec_argument(node) or _has_positional_replacement(node, label):
            continue
        if node in facts.import_fallbacks or facts.is_call_recorder(node) or facts.is_method_stub(node):
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
