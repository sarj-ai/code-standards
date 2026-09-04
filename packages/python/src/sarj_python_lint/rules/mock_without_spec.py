from __future__ import annotations

import ast
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, NamedTuple, Self, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_MOCK_MODULE = "unittest.mock"


class _UnspeccedCall(NamedTuple):
    call: ast.Call
    label: str


# Constructors whose default is an attribute-permissive double.
_UNSPECCED_FACTORIES = frozenset({"Mock", "MagicMock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock"})

# `patch`/`patch.object` install a MagicMock unless told otherwise.
_PATCHERS = frozenset({"patch"})

# Constructor and patcher keyword contracts differ. Mock accepts arbitrary
# keyword attributes, so patch-only controls such as autospec do not constrain it.
_CONSTRUCTOR_CONTRACT_KEYWORDS = frozenset({"spec", "spec_set", "wraps"})
_PATCH_CONTRACT_KEYWORDS = frozenset({"spec", "spec_set", "autospec", "wraps"})


# Positional arity reveals when each mock constructor already received its spec or replacement.
_REPLACEMENT_ARITY = MappingProxyType(
    {
        "Mock": 1,
        "MagicMock": 1,
        "AsyncMock": 1,
        "NonCallableMock": 1,
        "NonCallableMagicMock": 1,
        "patch": 2,
        "patch.object": 3,
    }
)

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


def _diagnostic_message(label: str) -> str:
    if label.startswith("patch"):
        return (
            f"`{label}` generates an unrestricted replacement. Use `autospec=True` or `spec=True`, or pass a "
            "concrete `new=` replacement."
        )
    return (
        f"`{label}` has no `spec=` or `spec_set=` and permits attributes outside the collaborator contract. "
        "Pass `spec_set=<RealType>`, use `create_autospec` when signatures matter, or implement a concrete fake."
    )


class MockWithoutSpec(Rule):
    id: str = "mock-without-spec"
    code: str = "SARJ040"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Unrestricted mock permits attributes outside the collaborator contract.",
        rationale=(
            "A mock without a spec permits removed or misspelled attributes; a callable mock without autospec may "
            "also accept stale call shapes."
        ),
        remediation=(
            "Use `spec_set=RealType` or a concrete fake for collaborators, `autospec=True` for patched callables, "
            "and `create_autospec` when direct-call signatures matter. Use `object()` or `mock.sentinel` for identity markers."
        ),
        category=RuleCategory.TESTING,
        limitations=(
            "Only non-generated test files and statically resolved `unittest.mock` or pytest-mock constructors are analyzed.",
            "Mocks used only for their built-in assertion API, import-loader `sys.modules` stubs, and untouched constructor placeholders are excluded.",
            "Unknown `new_callable=` factories are treated as concrete replacements; known Mock subclasses still require a spec.",
        ),
        examples=(
            RuleExample(
                example_id="mock-without-contract",
                title="Mock accepts any attribute",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        "from unittest.mock import Mock\n\ndef test_service():\n    client = Mock()\n    client.send()  # A typo or removed method still passes.\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=1,
                public=True,
                scenario="constructor",
            ),
            RuleExample(
                example_id="mock-with-spec",
                title="Autospecced mock follows attributes and signatures",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        "from unittest.mock import create_autospec\n\n"
                        "def test_service():\n"
                        "    client = create_autospec(Client, instance=True, spec_set=True)\n"
                        "    client.send()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=0,
                public=True,
                scenario="constructor",
            ),
            RuleExample(
                example_id="patch-without-contract",
                title="Patch generates an unrestricted replacement",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        "from unittest.mock import patch\n\n"
                        "def test_service():\n"
                        '    with patch("app.client.Client.send") as send:\n'
                        "        run_service()\n"
                        "        send.assert_called_once()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=1,
                public=True,
                scenario="patch",
            ),
            RuleExample(
                example_id="patch-with-autospec",
                title="Patch preserves the callable contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_service.py",
                        "from unittest.mock import patch\n\n"
                        "def test_service():\n"
                        '    with patch("app.client.Client.send", autospec=True) as send:\n'
                        "        run_service()\n"
                        "        send.assert_called_once()\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_service.py"),
                expected_count=0,
                public=True,
                scenario="patch",
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_test_path(path) or is_generated(path, source):
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
                message=_diagnostic_message(label),
                severity=Severity.WARNING,
            )
            for node, label in _unspecced_calls(tree, names, pytest_mocker, _FileFacts.from_tree(tree))
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


class _MockNames:
    def __init__(self) -> None:
        self.modules: set[str] = set()
        self.factories: dict[str, str] = {}
        self.defaults: set[str] = set()
        self.shadowed: set[str] = set()
        self.local_shadowed: dict[int, frozenset[str]] = {}
        self.scopes: dict[int, int] = {}

    @property
    def any_import(self) -> bool:
        """Report whether the file reaches `unittest.mock` at all."""
        return bool(self.modules or self.factories)

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _MockNames:
        found = cls()
        for node in nodes(tree, ast.Import, ast.ImportFrom):
            if isinstance(node, ast.Import):
                found._add_plain_import(node)
            else:
                found._add_from_import(node)
        imported = found.modules | set(found.factories) | found.defaults
        found.shadowed = _module_shadowed_bindings(tree, imported)
        found.scopes = _top_function_scopes(tree)
        local_shadowed: dict[int, set[str]] = {}
        for node in nodes(tree, ast.Name, ast.arg):
            if isinstance(node, ast.arg):
                name = node.arg
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                name = node.id
            else:
                continue
            scope = found.scopes[id(node)]
            if scope != id(tree) and name in imported:
                local_shadowed.setdefault(scope, set()).add(name)
        found.local_shadowed = {scope: frozenset(names) for scope, names in local_shadowed.items()}
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
                elif alias.name == "DEFAULT":
                    self.defaults.add(alias.asname or alias.name)

    def resolve(self, func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            if self._is_shadowed(func.id, func):
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
            return node.id in self.modules and not self._is_shadowed(node.id, node)
        # `unittest.mock.Mock(...)` — the receiver is itself an attribute chain.
        if isinstance(node, ast.Attribute) and node.attr == "mock":
            return (
                isinstance(node.value, ast.Name)
                and node.value.id in self.modules
                and not self._is_shadowed(node.value.id, node.value)
            )
        return False

    def is_default(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.defaults and not self._is_shadowed(node.id, node)
        return isinstance(node, ast.Attribute) and node.attr == "DEFAULT" and self._is_mock_module(node.value)

    def _is_shadowed(self, name: str, node: ast.AST) -> bool:
        scope = self.scopes.get(id(node))
        return name in self.shadowed or (scope is not None and name in self.local_shadowed.get(scope, frozenset()))


class _FileFacts:
    def __init__(self) -> None:
        self.bound_name: dict[ast.Call, _ScopedName] = {}
        self.reads: dict[_ScopedName, set[str]] = {}
        self.called: set[_ScopedName] = set()
        self.escaped: set[_ScopedName] = set()
        self.import_fallbacks: set[ast.Call] = set()
        self.sys_module_stubs: set[ast.Call] = set()
        self.attribute_target: dict[ast.Call, _ScopedName] = {}
        self.path_reads: dict[_ScopedName, set[str]] = {}
        self.path_calls: set[_ScopedName] = set()
        self.name_loads: dict[_ScopedName, list[ast.Name]] = {}
        self.constructor_argument_uses: dict[_ScopedName, list[ast.Name]] = {}
        self.spec_addition_lines: dict[_ScopedName, list[int]] = {}
        self.unsafe_use_lines: dict[_ScopedName, list[int]] = {}
        self.escape_lines: dict[_ScopedName, list[int]] = {}

    @classmethod
    def from_tree(cls, tree: ast.Module) -> _FileFacts:
        found = cls()
        scopes = _top_function_scopes(tree)
        constructors = _ImportedConstructors.from_tree(tree)
        sys_is_imported = _has_unshadowed_sys_import(tree)
        for node in nodes(tree, ast.Assign, ast.AnnAssign, ast.Attribute, ast.Call, ast.ExceptHandler):
            scope = scopes[id(node)]
            if isinstance(node, ast.Assign):
                target = node.targets[0] if len(node.targets) == 1 else None
                found._bind(scope, target, node.value, sys_is_imported=sys_is_imported)
                found._record_constructor_arguments(scope, target, node.value, constructors)
            elif isinstance(node, ast.AnnAssign):
                found._bind(scope, node.target, node.value, sys_is_imported=sys_is_imported)
                found._record_constructor_arguments(scope, node.target, node.value, constructors)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    name = (scope, node.value.id)
                    found.reads.setdefault(name, set()).add(node.attr)
                    if node.attr not in _MOCK_API_ATTRS:
                        found.unsafe_use_lines.setdefault(name, []).append(node.lineno)
                found._record_path_read(scope, node)
            elif isinstance(node, ast.Call):
                found._record_spec_addition(scope, node)
                if isinstance(node.func, ast.Name):
                    found.called.add((scope, node.func.id))
                for argument in [*node.args, *(kw.value for kw in node.keywords)]:
                    for name in _escaped_names(argument):
                        scoped = (scope, name)
                        found.escaped.add(scoped)
                        found.escape_lines.setdefault(scoped, []).append(argument.lineno)
                found._record_path_call(scope, node)
            elif _catches_import_failure(node):
                found.import_fallbacks.update(child for child in walk(node) if isinstance(child, ast.Call))
        for node in nodes(tree, ast.Name):
            if isinstance(node.ctx, ast.Load):
                found.name_loads.setdefault((scopes[id(node)], node.id), []).append(node)
        return found

    def _bind(
        self,
        scope: int,
        target: ast.expr | None,
        value: ast.expr | None,
        *,
        sys_is_imported: bool,
    ) -> None:
        if not isinstance(value, ast.Call):
            return
        if isinstance(target, ast.Name):
            self.bound_name[value] = (scope, target.id)
        elif isinstance(target, ast.Attribute):
            path = _dotted_path(target)
            if path is not None:
                self.attribute_target[value] = (scope, path)
        elif sys_is_imported and _is_sys_modules_subscript(target):
            self.sys_module_stubs.add(value)

    def _record_constructor_arguments(
        self,
        scope: int,
        target: ast.expr | None,
        value: ast.expr | None,
        constructors: _ImportedConstructors,
    ) -> None:
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Call) or not constructors.resolves(value.func):
            return
        direct_arguments = [argument for argument in value.args if isinstance(argument, ast.Name)]
        direct_arguments.extend(
            keyword.value
            for keyword in value.keywords
            if keyword.arg is not None and isinstance(keyword.value, ast.Name)
        )
        for argument in direct_arguments:
            self.constructor_argument_uses.setdefault((scope, argument.id), []).append(argument)

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

    def _record_spec_addition(self, scope: int, node: ast.Call) -> None:
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "mock_add_spec"
            and isinstance(node.func.value, ast.Name)
            and _mock_add_spec_has_contract(node)
        ):
            return
        name = (scope, node.func.value.id)
        self.spec_addition_lines.setdefault(name, []).append(node.lineno)

    def is_call_recorder(self, node: ast.Call) -> bool:
        name = self.bound_name.get(node)
        if name is None or name not in self.called or name in self.escaped:
            return False
        return self.reads.get(name, set()) <= _MOCK_API_ATTRS

    def is_method_stub(self, node: ast.Call) -> bool:
        path = self.attribute_target.get(node)
        if path is None:
            return False
        seen = self.path_reads.get(path, set())
        if not seen <= _MOCK_API_ATTRS:
            return False
        canned = any(kw.arg in _CANNED_RESULT_KEYWORDS for kw in node.keywords)
        return canned or bool(seen) or path in self.path_calls

    def is_inert_constructor_placeholder(self, node: ast.Call) -> bool:
        name = self.bound_name.get(node)
        if name is None:
            return False
        loads = self.name_loads.get(name, [])
        constructor_uses = self.constructor_argument_uses.get(name, [])
        return len(loads) == 1 and len(constructor_uses) == 1 and loads[0] is constructor_uses[0]

    def is_specced_before_use(self, node: ast.Call) -> bool:
        name = self.bound_name.get(node)
        if name is None:
            return False
        first_contract_use = min((*self.unsafe_use_lines.get(name, []), *self.escape_lines.get(name, [])), default=None)
        return any(
            line > node.lineno and (first_contract_use is None or line < first_contract_use)
            for line in self.spec_addition_lines.get(name, [])
        )

    def is_exempt(self, node: ast.Call) -> bool:
        return any(
            (
                node in self.import_fallbacks,
                node in self.sys_module_stubs,
                self.is_call_recorder(node),
                self.is_method_stub(node),
                self.is_inert_constructor_placeholder(node),
                self.is_specced_before_use(node),
            )
        )


class _ImportedConstructors(NamedTuple):
    direct: set[str]
    shadowed: set[str]

    @classmethod
    def from_tree(cls, tree: ast.Module) -> Self:
        direct: set[str] = set()
        for node in nodes(tree, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*" and _looks_like_class_name(alias.name):
                    direct.add(alias.asname or alias.name)
        return cls(direct, _shadowed_mock_bindings(tree, direct))

    def resolves(self, func: ast.expr) -> bool:
        return isinstance(func, ast.Name) and func.id in self.direct and func.id not in self.shadowed


def _looks_like_class_name(name: str) -> bool:
    return bool(name) and name[0].isupper()


def _has_unshadowed_sys_import(tree: ast.Module) -> bool:
    imported = any(
        alias.name == "sys" and alias.asname is None for node in nodes(tree, ast.Import) for alias in node.names
    )
    return imported and "sys" not in _shadowed_mock_bindings(tree, {"sys"})


def _is_sys_modules_subscript(target: ast.expr | None) -> bool:
    return (
        isinstance(target, ast.Subscript)
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "modules"
        and isinstance(target.value.value, ast.Name)
        and target.value.value.id == "sys"
    )


def _escaped_names(argument: ast.expr) -> set[str]:
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


def _mock_add_spec_has_contract(node: ast.Call) -> bool:
    if any(
        not isinstance(argument, ast.Starred) and not (isinstance(argument, ast.Constant) and argument.value is None)
        for argument in node.args
    ):
        return True
    return any(
        keyword.arg == "spec" and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
        for keyword in node.keywords
    )


def _dotted_path(expr: ast.expr) -> str | None:
    parts: list[str] = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name):
        return None
    parts.append(expr.id)
    return ".".join(reversed(parts))


def _module_shadowed_bindings(tree: ast.Module, imported: set[str]) -> set[str]:
    rebound: set[str] = set()

    class _Visitor(ast.NodeVisitor):
        @override
        def visit_Import(self, node: ast.Import) -> None:
            pass

        @override
        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            pass

        @override
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            rebound.add(node.name)

        @override
        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            rebound.add(node.name)

        @override
        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            rebound.add(node.name)

        @override
        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                rebound.add(node.id)

    visitor = _Visitor()
    for statement in tree.body:
        visitor.visit(statement)
    return rebound & imported


def _shadowed_mock_bindings(tree: ast.Module, imported: set[str]) -> set[str]:
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
    found: dict[ast.Call, str] = {}
    imports = ImportIndex.from_tree(tree)

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.fixtures: list[frozenset[str]] = []

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            if not _is_pytest_collected_or_fixture(node, imports):
                self.fixtures.append(self.fixtures[-1] if self.fixtures else frozenset())
                self.generic_visit(node)
                self.fixtures.pop()
                return
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


def _is_pytest_collected_or_fixture(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: ImportIndex,
) -> bool:
    if node.name.startswith("test_"):
        return True
    pytest_sources = frozenset({"pytest"})
    return any(
        imports.resolves(
            decorator.func if isinstance(decorator, ast.Call) else decorator,
            sources=pytest_sources,
            symbol="fixture",
        )
        for decorator in node.decorator_list
    )


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
) -> list[_UnspeccedCall]:
    hits: list[_UnspeccedCall] = []
    for node in nodes(tree, ast.Call):
        symbol = names.resolve(node.func) or pytest_mocker.get(node)
        if symbol is None:
            continue
        label = _render_callee(node.func, symbol)
        if _has_contract_argument(node, names, symbol) or _has_positional_replacement(node, label, names):
            continue
        if facts.is_exempt(node):
            continue
        hits.append(_UnspeccedCall(node, label))
    return hits


def _has_contract_argument(node: ast.Call, names: _MockNames, symbol: str) -> bool:
    # `**kwargs` forwarding could smuggle a spec in; treat it as specced rather
    # than guess, since the call site no longer states its own contract.
    for keyword in node.keywords:
        if keyword.arg is None:
            return True
        if symbol in _UNSPECCED_FACTORIES:
            if keyword.arg in _CONSTRUCTOR_CONTRACT_KEYWORDS and not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value is None
            ):
                return True
            continue
        if keyword.arg == "create":
            if not isinstance(keyword.value, ast.Constant) or keyword.value.value is True:
                return True
            continue
        if keyword.arg == "new":
            # DEFAULT requests the patcher's normal generated mock; every other
            # value, including None, is a concrete replacement.
            if not names.is_default(keyword.value):
                return True
            continue
        if keyword.arg == "autospec":
            if not (isinstance(keyword.value, ast.Constant) and keyword.value.value in {None, False}):
                return True
            continue
        if keyword.arg == "new_callable":
            # Choosing another unrestricted Mock subclass changes callability or
            # awaitability, not the collaborator contract. Unknown factories may
            # create a concrete non-mock replacement, so decline to guess.
            if isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                continue
            if names.resolve(keyword.value) in _UNSPECCED_FACTORIES:
                continue
            return True
        if keyword.arg in _PATCH_CONTRACT_KEYWORDS and not (
            isinstance(keyword.value, ast.Constant) and keyword.value.value is None
        ):
            return True
    return False


def _has_positional_replacement(node: ast.Call, label: str, names: _MockNames) -> bool:
    # `spec` / `new` are positional parameters of these signatures, and that is
    # how they are nearly always spelled — `patch("mod.fn", replacement)` is
    # `new=replacement`, `Mock(Process)` is `spec=Process`.
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        # `*args` forwarding: the arity is unknown, so decline to guess.
        return True
    arity = _REPLACEMENT_ARITY[label]
    if len(node.args) < arity:
        return False
    replacement = node.args[arity - 1]
    return not (label.startswith("patch") and names.is_default(replacement))


def _render_callee(func: ast.expr, symbol: str) -> str:
    if isinstance(func, ast.Attribute) and func.attr == "object":
        return f"{symbol}.object"
    return symbol
