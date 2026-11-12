from __future__ import annotations

import ast
from pathlib import PurePosixPath
import sys
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_MIN_OPERATIONS = 2
_MIN_STATE_FIELDS = 2
_VALUE_MODULES = sys.stdlib_module_names | {"typing_extensions"}


@final
class PreferExplicitClassContract(Rule):
    id = "prefer-explicit-class-contract"
    code = "SARJ569"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Declare a contract for a stateful behavior class.",
        rationale="A class coordinating mutable state and multiple operations exposes a concrete implementation without declaring its substitution or inheritance contract.",
        remediation="Declare a focused shared ABC or Protocol for the execution behavior and type consumers against it. If the class is intentionally concrete with no substitution boundary, declare it final instead of inventing an unused abstraction.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Reviews direct public module classes with no base other than builtin object, at least two public operations, at least two constructor-owned state fields, fresh lifecycle/state initialization and a retained import-proven non-stdlib collaborator read by an operation. Configuration-only classes and constructor-only argument holders do not establish an execution boundary. Names alone do not trigger this advice.",
            "Existing bases, decorators, dataclasses and records, stateless utilities, nested classes, test doubles and generated code are excluded. A final class is an explicit concrete contract; this policy does not mandate inheritance for all Python classes.",
            "No base class or final decorator is added automatically because real consumers, subclassing and framework registration must be reviewed.",
        ),
        examples=(
            RuleExample(
                example_id="undeclared-domain",
                title="The contract is implicit",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from httpx import AsyncClient\nclass Execution:\n    def __init__(self, client: AsyncClient, state):\n        self.client = client\n        self.state = state\n        self.cancelled = False\n    def run(self):\n        return self.client.send(self.state)\n    def cancel(self):\n        self.state = None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-domain",
                title="The contract is explicit",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from httpx import AsyncClient\nfrom typing import Protocol\nclass ExecutionPort(Protocol):\n    def run(self): ...\n    def cancel(self): ...\nclass Execution(ExecutionPort):\n    def __init__(self, client: AsyncClient, state):\n        self.client = client\n        self.state = state\n        self.cancelled = False\n    def run(self):\n        return self.client.send(self.state)\n    def cancel(self):\n        self.state = None\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path) or context.path.stem.startswith("_"):
            return []
        findings: list[Diagnostic] = []
        for node in context.tree.body:
            if not isinstance(node, ast.ClassDef) or not _execution_boundary(node, context):
                continue
            if context.suppressions.is_suppressed(node.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    node.lineno,
                    node.col_offset + 1,
                    self.code,
                    "This stateful behavior class has no declared contract; share a focused ABC or Protocol "
                    "with its consumers, or mark an intentionally concrete class final.",
                    severity=Severity.WARNING,
                )
            )
        return findings


def _execution_boundary(node: ast.ClassDef, context: PythonFileContext) -> bool:
    if not _uncontracted(node, context):
        return False
    methods = [member for member in node.body if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)]
    if sum(not method.name.startswith("_") for method in methods) < _MIN_OPERATIONS:
        return False
    constructors = [method for method in methods if method.name == "__init__"]
    if len(constructors) != 1:
        return False
    constructor = constructors[0]
    return (
        len(_state_fields(constructor)) >= _MIN_STATE_FIELDS
        and _initializes_state(constructor)
        and _retained_collaborator(constructor, methods, context)
    )


def _uncontracted(node: ast.ClassDef, context: PythonFileContext) -> bool:
    return (
        not node.name.startswith("_")
        and not node.decorator_list
        and not node.keywords
        and all(AnnotationOrigins(context).builtin(base, "object", base) for base in node.bases)
    )


def _own_nodes(method: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(method.body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        yield node
        pending.extend(ast.iter_child_nodes(node))


def _state_fields(method: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    parameters = [*method.args.posonlyargs, *method.args.args]
    if not parameters:
        return set()
    instance = parameters[0].arg
    return {
        node.attr
        for node in _own_nodes(method)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Store)
        and isinstance(node.value, ast.Name)
        and node.value.id == instance
    }


def _retained_collaborator(
    constructor: ast.FunctionDef | ast.AsyncFunctionDef,
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef],
    context: PythonFileContext,
) -> bool:
    arguments = [*constructor.args.posonlyargs, *constructor.args.args]
    if not arguments:
        return False
    instance = arguments[0].arg
    facts = AnnotationOrigins(context)
    imported = {
        argument.arg
        for argument in arguments[1:] + list(constructor.args.kwonlyargs)
        if argument.annotation is not None and _external_annotation(argument.annotation, facts, context)
    }
    retained = _stored_arguments(constructor, imported, instance)
    return bool(retained) and any(
        _reads_retained(method, retained, instance) for method in methods if not method.name.startswith("_")
    )


def _external_annotation(annotation: ast.expr, facts: AnnotationOrigins, context: PythonFileContext) -> bool:
    for member in context.annotation_semantics.transparent_members(annotation):
        qualified = facts.qualified(member, annotation)
        if qualified is not None and qualified.partition(".")[0] not in _VALUE_MODULES:
            return True
    return False


def _stored_arguments(
    constructor: ast.FunctionDef | ast.AsyncFunctionDef, imported: set[str], instance: str
) -> set[str]:
    retained: set[str] = set()
    for node in _own_nodes(constructor):
        match node:
            case ast.Assign(value=ast.Name(id=name), targets=targets) if name in imported:
                retained.update(
                    target.attr
                    for target in targets
                    if isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == instance
                )
            case ast.AnnAssign(
                value=ast.Name(id=name), target=ast.Attribute(value=ast.Name(id=owner), attr=attribute)
            ) if name in imported and owner == instance:
                retained.add(attribute)
            case _:
                pass
    return retained


def _reads_retained(method: ast.FunctionDef | ast.AsyncFunctionDef, retained: set[str], instance: str) -> bool:
    return any(
        isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Load)
        and node.attr in retained
        and isinstance(node.value, ast.Name)
        and node.value.id == instance
        for node in _own_nodes(method)
    )


def _initializes_state(constructor: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    arguments = [*constructor.args.posonlyargs, *constructor.args.args, *constructor.args.kwonlyargs]
    parameters = {argument.arg for argument in arguments}
    instance = arguments[0].arg if arguments else ""
    return any(
        not isinstance(value, ast.Name) or value.id not in parameters
        for value in _assigned_state(constructor, instance)
    )


def _assigned_state(constructor: ast.FunctionDef | ast.AsyncFunctionDef, instance: str) -> Iterator[ast.expr]:
    for node in _own_nodes(constructor):
        match node:
            case ast.Assign(value=value, targets=targets):
                if any(
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == instance
                    for target in targets
                ):
                    yield value
            case ast.AnnAssign(value=value, target=ast.Attribute(value=ast.Name(id=owner))) if (
                value is not None and owner == instance
            ):
                yield value
            case _:
                pass
