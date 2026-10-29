from __future__ import annotations

import ast
from collections import Counter
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
    is_suppressed,
)
from sarj_python_lint.rules._declared_contracts import MODEL_BASES, DeclaredContracts
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._test_composition import direct_nodes


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._declared_contracts import DeclaredClass
    from sarj_python_lint.rules._project_index import SourceUnit, SymbolRef


_BAD = """class Store:
    def get(self, key): ...
    def upsert(self, item): ...
class Recording(Store):
    def __init__(self):
        self.writes = []
    def upsert(self, item):
        self.writes.append(item)
        return item
"""
_NEWTYPE_ARGUMENTS = 2


@final
class NoRecordingStore(ProjectRule):
    id = "no-recording-store"
    code = "SARJ544"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Use the PostgreSQL store in tests instead of a recording-only store implementation.",
        rationale="An in-memory store double proves that a method was called but bypasses SQL, constraints, transactions and concurrency behavior. It can accept operations the real store rejects.",
        remediation="Inject the real PostgreSQL store with an isolated database fixture and assert persisted state. Keep operational observability around real persistence rather than replacing persistence with an appended call list.",
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks test sources for a subclass of a source-visible persistence contract declaring get and upsert. The concrete override must record to a stable instance list initialized directly in its constructor and return a synthetic result in straight-line instance code, without unknown calls, writes, await or self-method delegation.",
            "Unknown free-function calls retain possible persistence effects and abstain. Source-proven Pydantic models without custom methods or field calls, plain dataclass constructors, native NewType wrappers and unshadowed builtin value conversions are recognized as value construction for this advice; native validation is not claimed to be runtime-pure. Mutated or escaped constructor providers and shadowed constructor calls abstain.",
            "Class names do not trigger the rule. Imported bases need the prepared project source graph. Unknown bases, SQL-backed stores, delegated spies, unrelated call recorders, dynamic collections and unsupported inheritance remain outside scope. One warning is emitted per recording implementation, with no automatic rewrite.",
        ),
        examples=(
            RuleExample(
                example_id="recording-persistence",
                title="Recording replaces persistence",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/fakes/store.py", _BAD),),
                focus_path=PurePosixPath("tests/fakes/store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="delegating-spy",
                title="A spy retains actual persistence",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fakes/store.py", _BAD.replace("return item", "return super().upsert(item)")
                    ),
                ),
                focus_path=PurePosixPath("tests/fakes/store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None or not is_test_path(context.path):
            return []
        constructors = _ConstructorFacts(context)
        return [
            Diagnostic(
                context.path,
                owner.lineno,
                owner.col_offset + 1,
                self.code,
                "This store override records a call instead of exercising persistence; inject the PostgreSQL implementation and assert stored state in an isolated database fixture.",
                severity=Severity.WARNING,
            )
            for owner in context.nodes(ast.ClassDef)
            if not is_suppressed(context.source_lines, owner.lineno, self.code)
            and _recording_owner(owner, constructors)
        ]


def _recording_owner(owner: ast.ClassDef, constructors: _ConstructorFacts) -> bool:
    if len(owner.bases) != 1 or owner.keywords or owner.decorator_list:
        return False
    contract_methods = constructors.contract_methods(owner.bases[0])
    if not {"get", "upsert"} <= contract_methods:
        return False
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
    names = Counter(method.name for method in methods)
    lists = _instance_lists(methods)
    return bool(lists) and any(
        _records(method, lists, constructors)
        for method in methods
        if method.name in contract_methods and names[method.name] == 1
    )


def _instance_lists(methods: list[ast.FunctionDef | ast.AsyncFunctionDef]) -> frozenset[str]:
    initializers = [node for node in methods if isinstance(node, ast.FunctionDef) and node.name == "__init__"]
    if len(initializers) != 1 or not _instance_method(initializers[0]):
        return frozenset()
    initializer = initializers[0]
    if any(_unsafe_initializer_node(node) for node in direct_nodes(initializer)):
        return frozenset()
    written = (_self_written_field(node) for method in methods for node in direct_nodes(method))
    writes = Counter(name for name in written if name is not None)
    initialized = {_initialized_list(node) for node in initializer.body}
    return frozenset(name for name in initialized if name is not None and writes[name] == 1)


def _initialized_list(node: ast.stmt) -> str | None:
    match node:
        case ast.Assign(targets=[ast.Attribute(value=ast.Name(id="self"), attr=name)], value=ast.List()):
            return name
        case ast.AnnAssign(target=ast.Attribute(value=ast.Name(id="self"), attr=name), value=ast.List()):
            return name
        case _:
            return None


def _self_written_field(node: ast.AST) -> str | None:
    match node:
        case ast.Attribute(value=ast.Name(id="self"), attr=name, ctx=ast.Store() | ast.Del()):
            return name
        case _:
            return None


def _self_rebound(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "self" and isinstance(node.ctx, ast.Store | ast.Del)


def _unsafe_initializer_node(node: ast.AST) -> bool:
    return isinstance(node, ast.Call | ast.Return | ast.Raise | ast.Yield | ast.YieldFrom) or _self_rebound(node)


def _instance_method(method: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    positional = (*method.args.posonlyargs, *method.args.args)
    return bool(positional) and positional[0].arg == "self" and not method.decorator_list


def _records(
    method: ast.FunctionDef | ast.AsyncFunctionDef, lists: frozenset[str], constructors: _ConstructorFacts
) -> bool:
    if not _instance_method(method) or any(isinstance(statement, ast.Return) for statement in method.body[:-1]):
        return False
    nodes = tuple(direct_nodes(method))
    if any(_unsupported_recording_node(node) for node in nodes):
        return False
    calls = [node for node in nodes if isinstance(node, ast.Call)]
    if not all(_allowed_call(call, lists, constructors) for call in calls):
        return False
    returned = any(isinstance(node, ast.Return) and node.value is not None for node in nodes)
    recorded = any(_recorded_field(call) in lists for call in calls)
    return recorded and returned


def _unsupported_recording_node(node: ast.AST) -> bool:
    if isinstance(
        node,
        ast.Await
        | ast.Yield
        | ast.YieldFrom
        | ast.Raise
        | ast.If
        | ast.IfExp
        | ast.BoolOp
        | ast.For
        | ast.AsyncFor
        | ast.While
        | ast.Try
        | ast.TryStar
        | ast.With
        | ast.AsyncWith
        | ast.Match
        | ast.FunctionDef
        | ast.AsyncFunctionDef
        | ast.ClassDef
        | ast.Lambda
        | ast.comprehension,
    ):
        return True
    if isinstance(node, ast.Attribute | ast.Subscript) and isinstance(node.ctx, ast.Store | ast.Del):
        return True
    return _self_rebound(node)


def _recorded_field(call: ast.Call) -> str | None:
    match call.func:
        case ast.Attribute(value=ast.Attribute(value=ast.Name(id="self"), attr=name), attr="append"):
            return name
        case _:
            return None


def _allowed_call(call: ast.Call, lists: frozenset[str], constructors: _ConstructorFacts) -> bool:
    field = _recorded_field(call)
    if field is not None:
        return field in lists
    if isinstance(call.func, ast.Attribute):
        native = constructors.context.static_resource_provenance.runtime_import_name(call.func)
        if native in {"datetime.datetime.now", "datetime.datetime.utcnow", "uuid.uuid4", "uuid.uuid7"}:
            return True
    return constructors.value_constructor(call)


def _root_name(target: ast.expr) -> ast.Name | None:
    while isinstance(target, ast.Attribute):
        target = target.value
    return target if isinstance(target, ast.Name) else None


def _constructor_binding(call: ast.Call, context: PythonFileContext) -> ast.alias | ast.ClassDef | ast.Name | None:
    root = _root_name(call.func)
    if root is None:
        return None
    binding = context.static_resource_provenance.binding(root.id, call)
    if isinstance(binding, ast.ClassDef):
        return binding
    if not isinstance(binding, ast.alias | ast.Name):
        return None
    statement = context.parents.get(binding)
    if isinstance(binding, ast.Name) and statement is context.tree:
        return binding
    if statement is not None and context.parents.get(statement) is context.tree:
        return binding
    return None


@final
class _ConstructorFacts:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.contracts = DeclaredContracts(context)
        self._providers: dict[ast.Module, _ProviderFacts] = {}
        self._values: dict[tuple[SymbolRef, ast.AST], bool] = {}
        self._contracts: dict[tuple[ast.AST | None, str], set[str]] = {}

    def provider(self, unit: SourceUnit) -> _ProviderFacts | None:
        if unit.tree is None:
            return None
        if unit.tree not in self._providers:
            self._providers[unit.tree] = _ProviderFacts(unit.tree)
        return self._providers[unit.tree]

    def contract_methods(self, base: ast.expr) -> set[str]:
        root = _root_name(base)
        if root is None:
            return set()
        binding = self.context.static_resource_provenance.binding(root.id, base)
        key = (binding, ast.dump(base))
        if key not in self._contracts:
            resolved = self.contracts.class_type(base)
            self._contracts[key] = _declared_methods(resolved)
        return self._contracts[key]

    def value_constructor(self, call: ast.Call) -> bool:
        target = call.func
        if isinstance(target, ast.Name) and target.id in {
            "str",
            "int",
            "float",
            "bool",
            "bytes",
            "list",
            "tuple",
            "dict",
            "set",
            "frozenset",
        }:
            return self.context.imports.builtin_is_unshadowed(target.id)
        binding = _constructor_binding(call, self.context)
        if binding is None or self.contracts.unit is None:
            return False
        symbol = self.contracts.project.resolve(self.contracts.unit, target)
        if symbol is None:
            return False
        key = (symbol, binding)
        if key not in self._values:
            self._values[key] = self._prove_value(call, symbol)
        return self._values[key]

    def _prove_value(self, call: ast.Call, symbol: SymbolRef) -> bool:
        model = self.contracts.class_type(call.func, at=call)
        if model is not None and self.contracts.inherits(model, MODEL_BASES):
            return self._plain_model(model)
        unit = self.contracts.project.source_unit(symbol.module)
        provider = self.provider(unit) if unit is not None else None
        if provider is None:
            return False
        declaration = provider.declaration(symbol.name)
        if declaration is None or not provider.stable(symbol.name, declaration):
            return False
        if isinstance(declaration, ast.ClassDef):
            return _plain_dataclass(declaration, provider)
        value = declaration.value if isinstance(declaration, ast.Assign | ast.AnnAssign) else None
        return _native_newtype(value, symbol.name, provider)

    def _plain_model(self, model: DeclaredClass) -> bool:
        pending = [model]
        seen: set[ast.ClassDef] = set()
        while pending:
            current = pending.pop()
            if current.declaration in seen:
                continue
            seen.add(current.declaration)
            parents = self._model_parents(current)
            if parents is None:
                return False
            pending.extend(parents)
        return True

    def _model_parents(self, model: DeclaredClass) -> list[DeclaredClass] | None:
        provider = self.provider(model.unit)
        owner = model.declaration
        if provider is None or not provider.stable(owner.name, owner) or _custom_value_body(owner):
            return None
        parents: list[DeclaredClass] = []
        for base in owner.bases:
            if provider.module_imports.resolves(
                base, sources=frozenset({"pydantic", "pydantic.main"}), symbol="BaseModel"
            ):
                if not _stable_native_root(base, provider):
                    return None
                continue
            inherited = self.contracts.class_type(base, model.unit)
            if inherited is None:
                return None
            parents.append(inherited)
        return parents


def _declared_methods(model: DeclaredClass | None) -> set[str]:
    if model is None:
        return set()
    return {node.name for node in model.declaration.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)}


@final
class _ProviderFacts:
    def __init__(self, tree: ast.Module) -> None:
        nodes = tuple(ast.walk(tree))
        parents = {child: parent for parent in nodes for child in ast.iter_child_nodes(parent)}
        self.imports = ImportIndex.from_tree(tree)
        self.module_imports = ImportIndex.from_tree(tree, module_scope_only=True)
        self._declarations = _provider_declarations(tree)
        self._writes = _provider_writes(nodes)
        self._escaped = _provider_escapes(nodes, parents)

    def declaration(self, name: str) -> ast.stmt | None:
        declarations = self._declarations.get(name, [])
        return declarations[0] if len(declarations) == 1 else None

    def mutated(self, name: str, declaration: ast.stmt | None = None) -> bool:
        return bool(self._writes.get(name, set()) - _declaration_bindings(declaration))

    def stable(self, name: str, declaration: ast.stmt) -> bool:
        return not self.mutated(name, declaration) and name not in self._escaped


def _declaration_bindings(declaration: ast.stmt | None) -> set[ast.expr]:
    match declaration:
        case ast.Assign(targets=targets):
            return set(targets)
        case ast.AnnAssign(target=target):
            return {target}
        case _:
            return set()


def _provider_declarations(tree: ast.Module) -> dict[str, list[ast.stmt]]:
    result: dict[str, list[ast.stmt]] = {}
    for statement in tree.body:
        name = _declared_name(statement)
        if name is not None:
            result.setdefault(name, []).append(statement)
    return result


def _declared_name(node: ast.stmt) -> str | None:
    match node:
        case ast.ClassDef(name=name):
            return name
        case ast.Assign(targets=[ast.Name(id=name)]) | ast.AnnAssign(target=ast.Name(id=name)):
            return name
        case _:
            return None


def _provider_writes(nodes: tuple[ast.AST, ...]) -> dict[str, set[ast.expr]]:
    result: dict[str, set[ast.expr]] = {}
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            result.setdefault(node.id, set()).add(node)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del):
            root = _root_name(node)
            if root is not None:
                result.setdefault(root.id, set()).add(node)
    return result


def _provider_escapes(nodes: tuple[ast.AST, ...], parents: dict[ast.AST, ast.AST]) -> set[str]:
    escaped: set[str] = set()
    value_nodes: set[ast.AST] = set()
    for node in nodes:
        parent = parents.get(node)
        if parent in value_nodes or _escape_value_child(node, parent):
            value_nodes.add(node)
        if isinstance(node, ast.Name) and node in value_nodes and not _call_target(node, parents):
            escaped.add(node.id)
        root = _called_attribute_root(node)
        if root is not None:
            escaped.add(root)
    return escaped


def _escape_value_child(node: ast.AST, parent: ast.AST | None) -> bool:
    if isinstance(parent, ast.Call):
        return parent.func is not node
    return isinstance(parent, ast.Assign | ast.AnnAssign) and parent.value is node


def _called_attribute_root(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    root = _root_name(node.func)
    return root.id if root is not None else None


def _call_target(node: ast.Name, parents: dict[ast.AST, ast.AST]) -> bool:
    parent = parents.get(node)
    return isinstance(parent, ast.Call) and parent.func is node


def _stable_native_root(target: ast.expr, provider: _ProviderFacts) -> bool:
    root = _root_name(target)
    return root is not None and not provider.mutated(root.id)


def _native_newtype(value: ast.expr | None, name: str, provider: _ProviderFacts) -> bool:
    if not isinstance(value, ast.Call) or not _stable_native_root(value.func, provider):
        return False
    return (
        len(value.args) == _NEWTYPE_ARGUMENTS
        and not value.keywords
        and provider.imports.resolves(value.func, sources=frozenset({"typing", "typing_extensions"}), symbol="NewType")
        and isinstance(value.args[0], ast.Constant)
        and value.args[0].value == name
    )


def _custom_value_body(owner: ast.ClassDef) -> bool:
    if any(isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) for member in owner.body):
        return True
    return any(isinstance(node, ast.Call) for member in owner.body for node in ast.walk(member))


def _plain_dataclass(owner: ast.ClassDef, provider: _ProviderFacts) -> bool:
    if owner.bases or owner.keywords or len(owner.decorator_list) != 1 or _custom_value_body(owner):
        return False
    decorator = owner.decorator_list[0]
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return _stable_native_root(target, provider) and provider.imports.resolves(
        target, sources=frozenset({"dataclasses"}), symbol="dataclass"
    )
