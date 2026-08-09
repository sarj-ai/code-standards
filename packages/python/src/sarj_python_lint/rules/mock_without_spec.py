"""SARJ040 — A mock built without `spec=` accepts any attribute — spec it or fake it.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_mock_without_spec.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
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


# Positional arity reveals when each mock constructor already received its spec or replacement.
_REPLACEMENT_ARITY = MappingProxyType({"Mock": 1, "MagicMock": 1, "AsyncMock": 1, "patch": 2, "patch.object": 3})

# Attributes every mock answers regardless of what it stands in for.
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

# Keywords that canned-answer a *call*.
_CANNED_RESULT_KEYWORDS = frozenset({"return_value", "side_effect"})

_PYTEST_MOCK_FIXTURES = frozenset({"mocker", "class_mocker", "module_mocker", "package_mocker", "session_mocker"})

type _ScopedName = tuple[int, str]


class MockWithoutSpec(Rule):
    id: str = "mock-without-spec"
    code: str = "SARJ040"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Mock built without `spec=`/`autospec=` — it accepts any attribute and cannot rot loudly.",
        rationale="An unrestricted mock keeps accepting calls after the real collaborator's interface changes.",
        remediation="Pass `spec=`, `spec_set=`, or `autospec=True`, or use a small fake implementing the real contract.",
        category=RuleCategory.TESTING,
        limitations=(
            "Only test files and statically resolved `unittest.mock` or pytest-mock constructors are analyzed.",
            "Mocks used only for their built-in assertion API are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="mock-without-contract",
                title="Mock accepts any attribute",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        "from unittest.mock import Mock\n\ndef test_service():\n    client = Mock()\n    assert client\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="mock-with-spec",
                title="Mock follows the collaborator contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        "from unittest.mock import Mock\n\ndef test_service():\n    client = Mock(spec=Client)\n    assert client\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag `unittest.mock` constructions in test files that carry no spec argument."""
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        names = _MockNames.from_tree(tree)
        pytest_mocker = _pytest_mocker_calls(tree)
        if not names.any_import and not pytest_mocker:
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
            for node, label in _unspecced_calls(tree, names, pytest_mocker, _FileFacts.from_tree(tree))
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _MockNames:
    """The local names through which `unittest.mock` is reachable in one file."""

    def __init__(self) -> None:
        self.modules: set[str] = set()
        self.factories: dict[str, str] = {}
        self.shadowed: set[str] = set()

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
        found.shadowed = _shadowed_mock_bindings(tree, found.modules | set(found.factories))
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
            if func.id in self.shadowed:
                return None
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
            return node.id in self.modules and node.id not in self.shadowed
        # `unittest.mock.Mock(...)` — the receiver is itself an attribute chain.
        if isinstance(node, ast.Attribute) and node.attr == "mock":
            return (
                isinstance(node.value, ast.Name)
                and node.value.id in self.modules
                and node.value.id not in self.shadowed
            )
        return False


class _FileFacts:
    """Per-file context the false-positive guards need."""

    def __init__(self) -> None:
        self.bound_name: dict[ast.Call, _ScopedName] = {}
        self.reads: dict[_ScopedName, set[str]] = {}
        self.called: set[_ScopedName] = set()
        self.escaped: set[_ScopedName] = set()
        self.import_fallbacks: set[ast.Call] = set()
        self.attribute_target: dict[ast.Call, _ScopedName] = {}
        self.path_reads: dict[_ScopedName, set[str]] = {}
        self.path_calls: set[_ScopedName] = set()

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _FileFacts:
        """Collect the name bindings, attribute reads, and import-failure arms of one file."""
        found = cls()
        scopes = _top_function_scopes(tree)
        for node in nodes(tree, ast.Assign, ast.AnnAssign, ast.Attribute, ast.Call, ast.ExceptHandler):
            scope = scopes[id(node)]
            if isinstance(node, ast.Assign):
                found._bind(scope, node.targets[0] if len(node.targets) == 1 else None, node.value)
            elif isinstance(node, ast.AnnAssign):
                found._bind(scope, node.target, node.value)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    found.reads.setdefault((scope, node.value.id), set()).add(node.attr)
                found._record_path_read(scope, node)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    found.called.add((scope, node.func.id))
                for argument in [*node.args, *(kw.value for kw in node.keywords)]:
                    found.escaped.update((scope, name) for name in _escaped_names(argument))
                found._record_path_call(scope, node)
            elif _catches_import_failure(node):
                found.import_fallbacks.update(child for child in walk(node) if isinstance(child, ast.Call))
        return found

    def _bind(self, scope: int, target: ast.expr | None, value: ast.expr | None) -> None:
        if not isinstance(value, ast.Call):
            return
        if isinstance(target, ast.Name):
            self.bound_name[value] = (scope, target.id)
        elif isinstance(target, ast.Attribute):
            path = _dotted_path(target)
            if path is not None:
                self.attribute_target[value] = (scope, path)

    def _record_path_read(self, scope: int, node: ast.Attribute) -> None:
        # Load context only.
        if not isinstance(node.ctx, ast.Load):
            return
        path = _dotted_path(node.value)
        if path is not None:
            self.path_reads.setdefault((scope, path), set()).add(node.attr)

    def _record_path_call(self, scope: int, node: ast.Call) -> None:
        path = _dotted_path(node.func)
        if path is not None:
            self.path_calls.add((scope, path))

    def is_call_recorder(self, node: ast.Call) -> bool:
        """Report whether the double bound by `node` is only ever called and introspected."""
        name = self.bound_name.get(node)
        if name is None or name not in self.called or name in self.escaped:
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


def _escaped_names(argument: ast.expr) -> set[str]:
    """Find names passed as values while ignoring reads of the mock assertion API."""
    escaped: set[str] = set()

    class _EscapeVisitor(ast.NodeVisitor):
        def visit_Attribute(self, node: ast.Attribute) -> None:
            if isinstance(node.value, ast.Name) and node.attr in _MOCK_API_ATTRS:
                return
            self.generic_visit(node)

        @override
        def visit_Name(self, node: ast.Name) -> None:
            escaped.add(node.id)

    _EscapeVisitor().visit(argument)
    return escaped


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


def _shadowed_mock_bindings(tree: ast.Module, imported: set[str]) -> set[str]:
    """Conservatively reject imported mock names rebound anywhere in the file."""
    rebound: set[str] = set()
    for node in nodes(tree, ast.Name, ast.arg, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler):
        match node:
            case ast.Name(id=name, ctx=ast.Store()) | ast.arg(arg=name):
                rebound.add(name)
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                rebound.add(node.name)
            case ast.ExceptHandler(name=str(name)):
                rebound.add(name)
            case _:
                pass
    return rebound & imported


def _top_function_scopes(tree: ast.Module) -> dict[int, int]:
    """Map nodes to their outermost function so same-named locals cannot bleed across tests."""
    scopes: dict[int, int] = {}

    def visit(node: ast.AST, scope: int, function_scope: int | None) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and function_scope is None:
            scope = id(node)
            function_scope = scope
        scopes[id(node)] = scope
        for child in ast.iter_child_nodes(node):
            visit(child, scope, function_scope)

    visit(tree, id(tree), None)
    return scopes


def _pytest_mocker_calls(tree: ast.Module) -> dict[ast.Call, str]:
    """Resolve constructors reached through an actual pytest-mock fixture parameter."""
    found: dict[ast.Call, str] = {}

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.fixtures: list[frozenset[str]] = []

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            positional = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            own = frozenset(arg.arg for arg in positional if arg.arg in _PYTEST_MOCK_FIXTURES)
            inherited: frozenset[str] = self.fixtures[-1] if self.fixtures else frozenset()
            self.fixtures.append(inherited | own)
            self.generic_visit(node)
            self.fixtures.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)

        def visit_Call(self, node: ast.Call) -> None:
            fixtures: frozenset[str] = self.fixtures[-1] if self.fixtures else frozenset()
            symbol = _resolve_pytest_mocker(node.func, fixtures)
            if symbol is not None:
                found[node] = symbol
            self.generic_visit(node)

    _Visitor().visit(tree)
    return found


def _resolve_pytest_mocker(func: ast.expr, fixtures: frozenset[str]) -> str | None:
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr == "object":
        parent = _resolve_pytest_mocker(func.value, fixtures)
        return parent if parent in _PATCHERS else None
    if func.attr not in _UNSPECCED_FACTORIES and func.attr not in _PATCHERS:
        return None
    return func.attr if isinstance(func.value, ast.Name) and func.value.id in fixtures else None


def _catches_import_failure(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    if caught is None:
        return False
    parts = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(isinstance(p, ast.Name) and p.id in _IMPORT_FAILURES for p in parts)


def _unspecced_calls(
    tree: ast.Module,
    names: _MockNames,
    pytest_mocker: dict[ast.Call, str],
    facts: _FileFacts,
) -> list[tuple[ast.Call, str]]:
    hits: list[tuple[ast.Call, str]] = []
    for node in nodes(tree, ast.Call):
        symbol = names.resolve(node.func) or pytest_mocker.get(node)
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
