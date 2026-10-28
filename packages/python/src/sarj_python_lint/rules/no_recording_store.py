from __future__ import annotations

import ast
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
    from sarj_python_lint.rules._project_index import SourceUnit


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
            "Checks test sources for a subclass of a source-visible persistence contract declaring get and upsert. The concrete override must record to an instance list initialized in its constructor, return a synthetic result, and perform no await or self-method delegation.",
            "Unknown free-function calls retain possible persistence effects and abstain. Source-proven Pydantic constructors, plain dataclass constructors, native NewType wrappers and unshadowed builtin value conversions are recognized as value construction for this advice; their validation hooks are not claimed to be runtime-pure.",
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
        contracts = DeclaredContracts(context)
        findings: list[Diagnostic] = []
        for owner in context.nodes(ast.ClassDef):
            if is_suppressed(context.source_lines, owner.lineno, self.code):
                continue
            contract_methods = _contract_methods(owner, contracts)
            if not {"get", "upsert"} <= contract_methods:
                continue
            lists = _instance_lists(owner)
            if lists and any(
                _records(method, lists, context, contracts)
                for method in owner.body
                if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef) and method.name in contract_methods
            ):
                findings.append(
                    Diagnostic(
                        context.path,
                        owner.lineno,
                        owner.col_offset + 1,
                        self.code,
                        "This store override records a call instead of exercising persistence; inject the PostgreSQL implementation and assert stored state in an isolated database fixture.",
                        severity=Severity.WARNING,
                    )
                )
        return findings


def _contract_methods(owner: ast.ClassDef, contracts: DeclaredContracts) -> set[str]:
    result: set[str] = set()
    for base in owner.bases:
        resolved = contracts.class_type(base)
        if resolved is not None:
            result.update(
                node.name
                for node in resolved.declaration.body
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            )
    return result


def _instance_lists(owner: ast.ClassDef) -> frozenset[str]:
    result: set[str] = set()
    for method in owner.body:
        if not isinstance(method, ast.FunctionDef) or method.name != "__init__":
            continue
        for node in direct_nodes(method):
            match node:
                case ast.Assign(targets=[ast.Attribute(value=ast.Name(id="self"), attr=name)], value=ast.List()):
                    result.add(name)
                case ast.AnnAssign(target=ast.Attribute(value=ast.Name(id="self"), attr=name), value=ast.List()):
                    result.add(name)
                case _:
                    pass
    return frozenset(result)


def _records(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    lists: frozenset[str],
    context: PythonFileContext,
    contracts: DeclaredContracts,
) -> bool:
    recorded = False
    returned = False
    for node in direct_nodes(method):
        if isinstance(node, ast.Await):
            return False
        if isinstance(node, ast.Return) and node.value is not None:
            returned = True
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        match target:
            case ast.Attribute(value=ast.Attribute(value=ast.Name(id="self"), attr=name), attr="append"):
                recorded |= name in lists
            case ast.Attribute():
                native = context.static_resource_provenance.runtime_import_name(target)
                if native not in {
                    "datetime.datetime.now",
                    "datetime.datetime.utcnow",
                    "uuid.uuid4",
                    "uuid.uuid7",
                } and not _value_constructor(node, context, contracts):
                    return False
            case _:
                if not _value_constructor(node, context, contracts):
                    return False
    return recorded and returned


def _value_constructor(call: ast.Call, context: PythonFileContext, contracts: DeclaredContracts) -> bool:
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
        return context.imports.builtin_is_unshadowed(target.id)
    model = contracts.class_type(target, at=call)
    if model is not None and contracts.inherits(model, MODEL_BASES):
        return True
    unit = contracts.unit
    symbol = contracts.project.resolve(unit, target) if unit is not None else None
    provider = contracts.project.source_unit(symbol.module) if symbol is not None else None
    if provider is None or provider.tree is None or symbol is None:
        return False
    declarations = [member for member in provider.tree.body if _declares(member, symbol.name)]
    if len(declarations) != 1 or _provider_mutated(provider, symbol.name, declarations[0]):
        return False
    imports = ImportIndex.from_tree(provider.tree)
    declaration = declarations[0]
    if isinstance(declaration, ast.ClassDef):
        return _plain_dataclass(declaration, imports)
    value = declaration.value if isinstance(declaration, ast.Assign | ast.AnnAssign) else None
    return _native_newtype(value, symbol.name, imports, provider)


def _declares(node: ast.stmt, name: str) -> bool:
    match node:
        case ast.ClassDef(name=declared):
            return declared == name
        case ast.Assign(targets=[ast.Name(id=declared)]) | ast.AnnAssign(target=ast.Name(id=declared)):
            return declared == name
        case _:
            return False


def _provider_mutated(unit: SourceUnit, name: str, declaration: ast.stmt | None) -> bool:
    if unit.tree is None:
        return True
    bindings: frozenset[ast.expr]
    match declaration:
        case ast.Assign(targets=targets):
            bindings = frozenset(targets)
        case ast.AnnAssign(target=target):
            bindings = frozenset({target})
        case _:
            bindings = frozenset()
    return any(_writes_provider_symbol(node, name, bindings) for node in ast.walk(unit.tree))


def _writes_provider_symbol(node: ast.AST, name: str, bindings: frozenset[ast.expr]) -> bool:
    match node:
        case ast.Name(id=written, ctx=ast.Store() | ast.Del()):
            return written == name and node not in bindings
        case ast.Attribute(value=root, ctx=ast.Store() | ast.Del()):
            while isinstance(root, ast.Attribute):
                root = root.value
            return isinstance(root, ast.Name) and root.id == name
        case _:
            return False


def _native_newtype(value: ast.expr | None, name: str, imports: ImportIndex, provider: SourceUnit) -> bool:
    if not isinstance(value, ast.Call):
        return False
    root = value.func
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or _provider_mutated(provider, root.id, None):
        return False
    return (
        len(value.args) == _NEWTYPE_ARGUMENTS
        and not value.keywords
        and imports.resolves(value.func, sources=frozenset({"typing", "typing_extensions"}), symbol="NewType")
        and isinstance(value.args[0], ast.Constant)
        and value.args[0].value == name
    )


def _plain_dataclass(owner: ast.ClassDef, imports: ImportIndex) -> bool:
    if owner.bases or owner.keywords or len(owner.decorator_list) != 1:
        return False
    if any(isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) for member in owner.body):
        return False
    if any(isinstance(node, ast.Call) for member in owner.body for node in ast.walk(member)):
        return False
    decorator = owner.decorator_list[0]
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return imports.resolves(target, sources=frozenset({"dataclasses"}), symbol="dataclass")
