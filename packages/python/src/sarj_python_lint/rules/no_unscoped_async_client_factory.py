from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from enum import IntEnum
from functools import cached_property
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._ast_index import has_own_yield
from sarj_python_lint.rules._binding_inventory import scope_binding_names
from sarj_python_lint.rules._httpx_clients import (
    ASYNC_CLIENTS,
    MAX_ALIAS_DEPTH,
    SYNC_CLIENTS,
    allocates,
    imports_untouched,
    runtime_expression,
    stable_binding,
)
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit, SymbolRef


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext


_UNPACKAGED_MODULE = "__self_source__"
_CLEANUP_HOOKS = frozenset(
    {
        "aclose",
        "close",
        "__aenter__",
        "__aexit__",
        "__enter__",
        "__exit__",
        "__del__",
        "__getattr__",
        "__getattribute__",
    }
)
_TRANSPARENT_FUNCTION_DECORATORS = frozenset(
    {"typing.override", "typing_extensions.override", "typing.final", "typing_extensions.final"}
)
_TRANSPARENT_CLASS_DECORATORS = frozenset({"dataclasses.dataclass", "typing.final", "typing_extensions.final"})
_INERT_BASES = frozenset(
    {
        "abc.ABC",
        "typing.Generic",
        "typing.NamedTuple",
        "typing.Protocol",
        "typing_extensions.Protocol",
        "pydantic.BaseModel",
        "pydantic.main.BaseModel",
    }
)
_MESSAGE = (
    "httpx client built here leaves this function only inside the returned object, and nothing closes it; "
    "open it in the caller's `with` or `async with` scope and inject it, or give the returned object a `close` or `aclose` that closes it"
)
_BAD = "import httpx\nclass Dao:\n    def __init__(self, client):\n        self.client = client\nclass Service:\n    def __init__(self, dao):\n        self.dao = dao\ndef build_service(token):\n    client = httpx.AsyncClient(headers={'Authorization': token})\n    return Service(dao=Dao(client))\n"
_GOOD = _BAD.replace(
    "        self.dao = dao\n",
    "        self.dao = dao\n    async def aclose(self):\n        await self.dao.client.aclose()\n",
)


@final
class NoUnscopedAsyncClientFactory(ProjectRule):
    id = "no-unscoped-async-client-factory"
    code = "SARJ577"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Inject an HTTPX client instead of hiding a never-closed one inside a returned object.",
        rationale="A factory that wraps a fresh client in its returned object and never closes it leaks one connection pool per call, and callers cannot see the client to close it.",
        remediation="Open the client in the caller's with or async with scope and inject it, or give the returned object a close or aclose method that closes the client. Keep tenant credentials, cookies and event loops in separate clients; do not replace them with a global client.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "An import-proven httpx AsyncClient or Client built in a non-generator function, staticmethod or classmethod, directly or through a one-hop factory, reaches a return only as a constructor argument, nested to 32 links. Each wrapper must resolve through the project index to a class, or a re-export of one, whose own body and resolved bases define no aclose, close, enter/exit or attribute-forwarding hook, decorated only with dataclass or final; wrappers that define one own the client. abc.ABC, Generic, NamedTuple, Protocol and pydantic.BaseModel bases are inert.",
            "The rule stays silent when the client or any wrapper is used in with/async with, reaches aclose/close/__aexit__ through any attribute chain (including push_async_callback(client.aclose)), is returned bare, is read by a closure, or flows into a call that is not a resolved wrapper class, including AsyncExitStack.enter_async_context, functools.partial and lifespans. Other decorators such as functools.cache, contextmanager and pytest fixtures, unresolved wrapper classes and rebinding other than to None also abstain.",
            "Callers that close a client through a returned field are not inferred: the project index has no function call graph, factories are importable from unindexed code, and tests call them without closing. Such factories report until the returned object owns closure through aclose or the client moves to the caller. A wrapper constructor that hands the client to another owner, and runtime patching of wrapper classes, are not inferred.",
            "The rule skips test and test-support paths, where helpers hand throwaway clients, usually over httpx.MockTransport, to the object under test.",
            "SARJ549 owns clients built in __init__, so this rule skips __init__. Ruff ASYNC212 owns blocking HTTPX use in async functions, and SIM115 covers only file openers.",
        ),
        examples=(
            RuleExample(
                example_id="wrapped-factory-leak",
                title="Do not hide a fresh client inside a returned service",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/service.py", _BAD),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="wrapper-owns-closure",
                title="Give the returned object ownership of client closure",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/service.py", _GOOD),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "httpx" not in context.symbol_source or "Client" not in context.symbol_source:
            return []
        if context.generated or context.tree is None or context.has_wildcard_import or context.dynamic_namespace:
            return []
        if is_test_path(context.path) or is_test_support_path(context.path):
            return []
        clients = frozenset[str]().union(
            *(kind for kind in (ASYNC_CLIENTS, SYNC_CLIENTS) if imports_untouched(context, kind))
        )
        if not clients:
            return []
        factories: dict[ast.FunctionDef | ast.Lambda, bool] = {}
        wrappers = _InertWrappers(context)
        candidates: dict[ast.FunctionDef | ast.AsyncFunctionDef, bool] = {}
        findings: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            function = context.binding_inventory.scope(call)
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not allocates(context, call, clients=clients, follow_factory=True, factories=factories):
                continue
            if function not in candidates:
                candidates[function] = _factory_candidate(context, function)
            if (
                candidates[function]
                and runtime_expression(context, call)
                and _ClientFlow(context, function, wrappers).escapes_only_wrapped(call)
                and not context.suppressions.is_suppressed(call.lineno, self.code)
            ):
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=call.lineno,
                        col=call.col_offset + 1,
                        code=self.code,
                        severity=Severity.ERROR,
                        message=_MESSAGE,
                    )
                )
        return findings


def _factory_candidate(context: PythonFileContext, function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return (
        function.name != "__init__"
        and not has_own_yield(function)
        and all(_transparent_decorator(context, decorator) for decorator in function.decorator_list)
    )


def _transparent_decorator(context: PythonFileContext, decorator: ast.expr) -> bool:
    if isinstance(decorator, ast.Name) and decorator.id in {"staticmethod", "classmethod"}:
        return context.imports.builtin_is_unshadowed(decorator.id)
    return context.imports.resolved_qualified_name(decorator) in _TRANSPARENT_FUNCTION_DECORATORS


class _Escape(IntEnum):
    LOCAL = 0
    RETURNED_WRAPPED = 1
    UNKNOWN = 2


@final
class _ClientFlow:
    def __init__(
        self,
        context: PythonFileContext,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        wrappers: _InertWrappers,
    ) -> None:
        self._context = context
        self._inventory = context.binding_inventory
        self._function = function
        self._wrappers = wrappers

    def escapes_only_wrapped(self, allocation: ast.Call) -> bool:
        return self._value(allocation, wrapped=False, remaining=MAX_ALIAS_DEPTH) is _Escape.RETURNED_WRAPPED

    def _value(self, value: ast.expr, *, wrapped: bool, remaining: int) -> _Escape:
        if remaining == 0:
            return _Escape.UNKNOWN
        parent = self._context.parents.get(value)
        match parent:
            case ast.Return():
                return _Escape.RETURNED_WRAPPED if wrapped else _Escape.UNKNOWN
            case ast.Assign(targets=[ast.Name() as target]) | ast.AnnAssign(target=ast.Name() as target) if (
                parent.value is value
            ):
                return self._name(target, wrapped=wrapped, remaining=remaining - 1)
            case ast.keyword(arg=str()):
                return self._wrapper(self._context.parents.get(parent), remaining=remaining - 1)
            case ast.Call() if value in parent.args:
                return self._wrapper(parent, remaining=remaining - 1)
            case _:
                return _Escape.UNKNOWN

    def _wrapper(self, call: ast.AST | None, *, remaining: int) -> _Escape:
        if not isinstance(call, ast.Call) or not self._wrappers.inert(call.func):
            return _Escape.UNKNOWN
        return self._value(call, wrapped=True, remaining=remaining)

    def _name(self, target: ast.Name, *, wrapped: bool, remaining: int) -> _Escape:
        name = target.id
        bindings = self._inventory.bindings.get(self._function, {}).get(name, ())
        if name in self._inventory.external_bindings or any(
            binding is not target and not _none_assignment(self._context, binding) for binding in bindings
        ):
            return _Escape.UNKNOWN
        escape = _Escape.LOCAL
        for read in self._inventory.reads.get(name, ()):
            if not self._context.resource_provenance.contains(self._function, read):
                continue
            outcome = (
                self._read(read, wrapped=wrapped, remaining=remaining)
                if self._inventory.scope(read) is self._function
                else self._nested_read(read)
            )
            if outcome is _Escape.UNKNOWN:
                return outcome
            escape = max(escape, outcome)
        return escape

    def _read(self, read: ast.Name, *, wrapped: bool, remaining: int) -> _Escape:
        parent = self._context.parents.get(read)
        match parent:
            case ast.Attribute():
                return _Escape.UNKNOWN if _reaches_cleanup(self._context, parent) else _Escape.LOCAL
            case ast.Compare():
                return _Escape.LOCAL
            case ast.If(test=test) | ast.While(test=test) | ast.IfExp(test=test) if test is read:
                return _Escape.LOCAL
            case _:
                return self._value(read, wrapped=wrapped, remaining=remaining)

    def _nested_read(self, read: ast.Name) -> _Escape:
        scope = self._inventory.scope(read)
        while scope is not None and scope is not self._function:
            if read.id in self._inventory.bindings.get(scope, {}):
                return _Escape.LOCAL
            scope = self._inventory.scope(scope)
        return _Escape.UNKNOWN


def _none_assignment(context: PythonFileContext, binding: ast.AST) -> bool:
    match context.parents.get(binding):
        case (
            ast.Assign(targets=[target], value=ast.Constant(value=None))
            | ast.AnnAssign(target=target, value=ast.Constant(value=None))
        ):
            return target is binding
        case _:
            return False


def _reaches_cleanup(context: PythonFileContext, attribute: ast.Attribute) -> bool:
    node: ast.AST | None = attribute
    while isinstance(node, ast.Attribute):
        if node.attr in _CLEANUP_HOOKS:
            return True
        node = context.parents.get(node)
    return False


@final
@dataclass(frozen=True, slots=True)
class _ClassDeclaration:
    unit: SourceUnit
    node: ast.ClassDef


@final
class _InertWrappers:
    def __init__(self, context: PythonFileContext) -> None:
        self._context = context
        self._verdicts: dict[SymbolRef, bool] = {}
        self._module_bindings: dict[Path, dict[str, list[ast.stmt]]] = {}

    @cached_property
    def _project(self) -> ProjectIndexSet:
        return self._context.session.project or ProjectIndexSet.single(self._context.path, self._context.source)

    @cached_property
    def _unit(self) -> SourceUnit | None:
        context = self._context
        if context.tree is None:
            return None
        unit = self._project.unit_or_source(context.path, context.source, context.tree)
        if unit is not None and unit.module is not None:
            return unit
        imports: Mapping[str, SymbolRef] = {} if unit is None else unit.imports
        return SourceUnit(context.path, _UNPACKAGED_MODULE, context.source, context.tree, imports)

    def inert(self, constructor: ast.expr) -> bool:
        root = constructor.value if isinstance(constructor, ast.Attribute) else constructor
        if self._unit is None or not isinstance(root, ast.Name) or root.id in self._context.binding_inventory.mutated:
            return False
        match stable_binding(self._context, root.id, constructor):
            case ast.ClassDef() as declaration if root is constructor:
                stable = self._context.parents.get(declaration) is self._context.tree
            case ast.alias() as alias:
                stable = isinstance(self._context.binding_inventory.scope(alias), ast.Module)
            case _:
                stable = False
        symbol = ProjectIndexSet.resolve(self._unit, constructor) if stable else None
        return symbol is not None and self._inert_symbol(symbol, remaining=MAX_ALIAS_DEPTH)

    def _inert_symbol(self, symbol: SymbolRef, *, remaining: int) -> bool:
        if symbol not in self._verdicts:
            self._verdicts[symbol] = False
            located = self._locate(symbol, remaining=remaining)
            self._verdicts[symbol] = located is not None and self._inert_declaration(
                located.unit, located.node, remaining=remaining - 1
            )
        return self._verdicts[symbol]

    def _locate(self, symbol: SymbolRef, *, remaining: int) -> _ClassDeclaration | None:
        for _ in range(remaining):
            unit = (
                self._unit
                if self._unit is not None and symbol.module == self._unit.module
                else self._project.source_unit(symbol.module)
            )
            if unit is None or unit.tree is None:
                return None
            match self._bindings(unit).get(symbol.name, []):
                case [ast.ClassDef(name=name) as declaration] if name == symbol.name:
                    return _ClassDeclaration(unit, declaration)
                case [ast.ImportFrom()] if (exported := unit.imports.get(symbol.name)) is not None and exported.name:
                    symbol = exported
                case _:
                    return None
        return None

    def _bindings(self, unit: SourceUnit) -> dict[str, list[ast.stmt]]:
        if unit.path not in self._module_bindings:
            bindings: dict[str, list[ast.stmt]] = defaultdict(list)
            for statement in unit.tree.body if unit.tree is not None else ():
                for name in _statement_bindings(statement):
                    bindings[name].append(statement)
            self._module_bindings[unit.path] = bindings
        return self._module_bindings[unit.path]

    def _inert_declaration(self, unit: SourceUnit, declaration: ast.ClassDef, *, remaining: int) -> bool:
        if remaining == 0 or declaration.keywords:
            return False
        if any(
            _qualified(ProjectIndexSet.resolve(unit, decorator.func if isinstance(decorator, ast.Call) else decorator))
            not in _TRANSPARENT_CLASS_DECORATORS
            for decorator in declaration.decorator_list
        ):
            return False
        if any(not _CLEANUP_HOOKS.isdisjoint(_statement_bindings(statement)) for statement in declaration.body):
            return False
        return all(self._inert_base(unit, base, remaining=remaining) for base in declaration.bases)

    def _inert_base(self, unit: SourceUnit, base: ast.expr, *, remaining: int) -> bool:
        if isinstance(base, ast.Subscript):
            base = base.value
        if isinstance(base, ast.Name) and base.id == "object" and "object" not in self._bindings(unit):
            return True
        symbol = ProjectIndexSet.resolve(unit, base)
        if symbol is None:
            return False
        return _qualified(symbol) in _INERT_BASES or self._inert_symbol(symbol, remaining=remaining)


def _statement_bindings(statement: ast.stmt) -> frozenset[str]:
    if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        header = (child for child in ast.iter_child_nodes(statement) if child not in statement.body)
        if not any(isinstance(node, ast.NamedExpr) for part in header for node in ast.walk(part)):
            return frozenset({statement.name})
    return scope_binding_names(statement)


def _qualified(symbol: SymbolRef | None) -> str | None:
    return None if symbol is None else f"{symbol.module}.{symbol.name}"
