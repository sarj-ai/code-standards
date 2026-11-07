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
)
from sarj_python_lint.rules._ast_index import has_own_yield
from sarj_python_lint.rules._declared_contracts import DeclaredContracts
from sarj_python_lint.rules._imports import TYPING_SOURCES, ImportIndex
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules.require_explicit_service_contract import operations_for_fields
from sarj_python_lint.rules.require_port_for_service import class_methods, is_data_type, self_stored_parameters


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_WORKER = "class Worker:\n    def __init__(self, store):\n        self.store = store\n    def run(self):\n        return self.store.load()\n"
_BAD = (
    _WORKER
    + "class Consumer:\n    def __init__(self, store):\n        self.store = store\n    def run(self):\n        return Worker(self.store).run()\n"
)
_GOOD = (
    _WORKER
    + "class Consumer:\n    def __init__(self, worker):\n        self.worker = worker\n    def run(self):\n        return self.worker.run()\n\ndef compose(store):\n    return Consumer(Worker(store))\n"
)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


@final
class PreferInjectedService(ProjectRule):
    id = "prefer-injected-service"
    code = "SARJ564"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Inject a service instead of constructing it from dependencies already available to the consumer.",
        rationale="Hardwired collaborator construction hides its lifetime and prevents callers from substituting the service directly.",
        remediation="Construct the collaborator at the application's composition boundary with the appropriate lifetime and inject it into the consumer. Do not introduce a global singleton or share request-specific state.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Warning-stage Python policy, based on resolved first-party class behavior rather than service names. A collaborator must directly retain constructor arguments and invoke them through a public operation.",
            "Covers construction retained by the consumer's constructor or immediately followed by a service operation. All arguments must be constructor parameters or directly retained consumer dependencies. Runtime arguments, returned factories, composition containers, tests and generated files are excluded.",
            "Inherited implementations, decorated methods, class-level state or descriptors, resource lifecycles, generators, instance-field reassignment, expanded arguments, reexports, unknown constructors and ambiguous bindings abstain. Local construction followed by later local-variable use is not inferred.",
            "Source inspection cannot establish every ownership or lifetime requirement. Review warning findings before changing composition; no automatic rewrite is offered.",
        ),
        examples=(
            RuleExample(
                example_id="constructs-service-during-operation",
                title="The consumer hardwires a collaborator using an existing dependency",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/service.py", _BAD),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="injects-composed-service",
                title="The composition boundary supplies the collaborator",
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
        if (
            context.tree is None
            or context.generated
            or is_test_path(context.path)
            or is_test_support_path(context.path)
        ):
            return []
        if context.has_wildcard_import or context.dynamic_namespace:
            return []
        contracts: DeclaredContracts | None = None
        diagnostics: list[Diagnostic] = []
        for call in context.nodes(ast.Call):
            method = _enclosing_method(call, context)
            owner = context.parents.get(method) if method is not None else None
            if method is None or not isinstance(owner, ast.ClassDef):
                continue
            if not _stable_arguments(call, method, owner, context):
                continue
            if contracts is None:
                contracts = DeclaredContracts(context)
            collaborator = contracts.class_type(call.func, at=call)
            if collaborator is None:
                continue
            operations = _service_operations(collaborator.declaration)
            if not operations or not _used_as_service(call, owner, operations, context):
                continue
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=call.lineno,
                    col=call.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=f"Inject {collaborator.declaration.name} instead of constructing it from the consumer's dependencies; compose it with the appropriate lifetime at the application boundary.",
                )
            )
        return diagnostics


def _enclosing_method(call: ast.Call, context: PythonFileContext) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    node: ast.AST = call
    while (parent := context.parents.get(node)) is not None:
        if not isinstance(parent, _SCOPES):
            node = parent
            continue
        if not isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
            return None
        owner = context.parents.get(parent)
        if not isinstance(owner, ast.ClassDef) or is_data_type(owner):
            return None
        if any(item.name in {"__enter__", "__aenter__", "__exit__", "__aexit__"} for item in class_methods(owner)):
            return None
        positional = [*parent.args.posonlyargs, *parent.args.args]
        if (
            all(
                context.imports.resolves(item, sources=TYPING_SOURCES, symbol="override")
                for item in parent.decorator_list
            )
            and not has_own_yield(parent)
            and positional
            and positional[0].arg == "self"
        ):
            return parent
        return None
    return None


def _self_field(expression: ast.AST) -> str | None:
    if (
        isinstance(expression, ast.Attribute)
        and isinstance(expression.value, ast.Name)
        and expression.value.id == "self"
    ):
        return expression.attr
    return None


def _stable_arguments(
    call: ast.Call, method: ast.FunctionDef | ast.AsyncFunctionDef, owner: ast.ClassDef, context: PythonFileContext
) -> bool:
    values = [*call.args, *(keyword.value for keyword in call.keywords)]
    if not values or any(keyword.arg is None for keyword in call.keywords):
        return False
    constructor = next((item for item in class_methods(owner) if item.name == "__init__"), None)
    if constructor is None:
        return False
    arguments = [*constructor.args.posonlyargs, *constructor.args.args, *constructor.args.kwonlyargs]
    parameters = set(arguments[1:])
    stored = self_stored_parameters(constructor, context.imports)
    fields = frozenset(field for names in stored.fields_by_parameter.values() for field in names)
    changed: set[str] = set()
    for item in class_methods(owner):
        if item is constructor:
            continue
        changed.update(_written_fields(item))
    provenance = context.static_resource_provenance
    receiver = (method.args.posonlyargs + method.args.args)[0]
    return all(
        (isinstance(value, ast.Name) and method is constructor and provenance.binding(value.id, value) in parameters)
        or (
            isinstance(value, ast.Attribute)
            and _self_field(value) in fields - changed
            and provenance.binding("self", value) is receiver
        )
        for value in values
    )


def _written_fields(method: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    return frozenset(
        field
        for node in ast.walk(method)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del)
        if (field := _self_field(node)) is not None
    )


def _service_operations(node: ast.ClassDef) -> frozenset[str]:
    if node.bases or node.keywords or is_data_type(node):
        return frozenset()
    if any(isinstance(item, ast.Assign | ast.AnnAssign | ast.AugAssign) for item in node.body):
        return frozenset()
    methods = class_methods(node)
    if any(method.decorator_list or (method.name.startswith("__") and method.name != "__init__") for method in methods):
        return frozenset()
    constructor = next((method for method in methods if method.name == "__init__"), None)
    if constructor is None or constructor.decorator_list or constructor.args.vararg or constructor.args.kwarg:
        return frozenset()
    if any(has_own_yield(method) or _written_fields(method) for method in methods if method is not constructor):
        return frozenset()
    fields = _constructor_fields(constructor)
    return operations_for_fields(node, fields, ImportIndex.from_tree(ast.Module(body=[node], type_ignores=[])))


def _constructor_fields(constructor: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    parameters = {
        item.arg for item in (*constructor.args.posonlyargs, *constructor.args.args, *constructor.args.kwonlyargs)
    } - {"self"}
    fields: set[str] = set()
    for statement in constructor.body:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        if not isinstance(statement, ast.Assign | ast.AnnAssign) or not isinstance(statement.value, ast.Name):
            return frozenset()
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if statement.value.id not in parameters:
            return frozenset()
        for target in targets:
            field = _self_field(target)
            if field is None:
                return frozenset()
            fields.add(field)
    return frozenset(fields)


def _used_as_service(
    call: ast.Call, owner: ast.ClassDef, operations: frozenset[str], context: PythonFileContext
) -> bool:
    parent = context.parents.get(call)
    if isinstance(parent, ast.Attribute) and parent.value is call and parent.attr in operations:
        operation = context.parents.get(parent)
        return isinstance(operation, ast.Call) and operation.func is parent
    if isinstance(parent, ast.Assign | ast.AnnAssign) and parent.value is call:
        method = _enclosing_method(call, context)
        if method is None or method.name != "__init__":
            return False
        targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
        fields = frozenset(field for target in targets if (field := _self_field(target)) is not None)
        return bool(operations_for_fields(owner, fields, context.imports))
    return False
