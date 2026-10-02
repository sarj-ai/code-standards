from __future__ import annotations

import ast
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, TypeGuard, final, override

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


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_BUILTINS = frozenset({"builtins"})
_ATTRIBUTE_HOOKS = frozenset({"__slots__", "__getattr__", "__getattribute__", "__setattr__", "__delattr__"})


@final
class DiscourageBackingFieldProperties(Rule):
    id = "discourage-backing-field-properties"
    code = "SARJ478"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Prefer typed public attributes over properties that only forward constructor inputs.",
        rationale="A private storage name and a forwarding accessor duplicate ordinary state access and dependency wiring.",
        remediation=(
            "Use a typed public attribute when callers may rebind it; retain and narrowly suppress an intentional "
            "read-only binding. Preserve required interface and descriptor behavior."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only synchronous public getters returning a private field assigned directly from a constructor parameter are checked.",
            "Inherited classes other than plain object, class decorators, metaclasses, slots, and attribute hooks are excluded.",
            "Setters, deleters, extra decorators, and class-defined backing descriptors are excluded.",
            "Read-only intent cannot be inferred from syntax; this is a style warning, not a proof of redundant behavior.",
            "Generated source, wildcard imports, and shadowed property bindings are excluded. No autofix is provided.",
        ),
        examples=(
            RuleExample(
                example_id="forwarding-getter",
                title="Accessor duplicates ordinary dependency storage",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "class Service:\n    def __init__(self, store: Store) -> None:\n        self._store = store\n"
                        "    @property\n    def store(self) -> Store:\n        return self._store\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="public-attribute",
                title="Dependency has one typed public name",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "class Service:\n    def __init__(self, store: Store) -> None:\n        self.store: Store = store\n",
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
        if context.generated or context.tree is None or _ambiguous_builtins(context):
            return []
        findings: list[Diagnostic] = []
        for owner in context.nodes(ast.ClassDef):
            attributes = _class_attributes(owner)
            if not _ordinary_class(context, owner) or not _ATTRIBUTE_HOOKS.isdisjoint(attributes):
                continue
            fields = _constructor_fields(owner)
            for method in owner.body:
                if not isinstance(method, ast.FunctionDef) or (field := _backing_field(context, method)) not in fields:
                    continue
                if field is None or field in attributes or attributes[method.name] != 1:
                    continue
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=method.lineno,
                        col=method.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=(
                            f"Property `{method.name}` only forwards `{field}`; prefer a typed public attribute if rebinding "
                            "is allowed, or retain the read-only binding with a reasoned suppression."
                        ),
                    )
                )
        return findings


def _builtin(context: PythonFileContext, expression: ast.expr, name: str) -> bool:
    return (
        isinstance(expression, ast.Name) and expression.id == name and context.imports.builtin_is_unshadowed(name)
    ) or context.imports.resolves(expression, sources=_BUILTINS, symbol=name)


def _ambiguous_builtins(context: PythonFileContext) -> bool:
    names = {"property", "object"} | {
        name
        for name, target in context.module_imports.bindings.items()
        if target.module == "builtins" and target.symbol in {None, "property", "object"}
    }
    return any(
        (isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names))
        or (
            isinstance(node, ast.Import | ast.ImportFrom)
            and not isinstance(context.parents.get(node), ast.Module)
            and any((alias.asname or alias.name.partition(".")[0]) in names for alias in node.names)
        )
        or (
            isinstance(node, ast.Attribute)
            and node.attr in {"property", "object"}
            and isinstance(node.ctx, ast.Store | ast.Del)
        )
        for node in context.nodes(ast.Import, ast.ImportFrom, ast.Attribute)
    )


def _ordinary_class(context: PythonFileContext, owner: ast.ClassDef) -> bool:
    if owner.decorator_list or owner.keywords or any(not _builtin(context, base, "object") for base in owner.bases):
        return False
    return not any(
        isinstance(statement, ast.If | ast.Try | ast.TryStar | ast.For | ast.While | ast.With | ast.Match)
        for statement in owner.body
    )


def _class_attributes(owner: ast.ClassDef) -> Counter[str]:
    attributes: Counter[str] = Counter()
    for member in owner.body:
        match member:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                attributes[name] += 1
            case ast.Assign(targets=targets):
                for target in targets:
                    if isinstance(target, ast.Name):
                        attributes[target.id] += 1
            case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr()):
                attributes[name] += 1
            case _:
                pass
    return attributes


def _constructor_fields(owner: ast.ClassDef) -> set[str]:
    constructor = _constructor(owner)
    if constructor is None:
        return set()
    positional = constructor.args.posonlyargs + constructor.args.args
    if not positional:
        return set()
    receiver = positional[0].arg
    parameters = {parameter.arg for parameter in (*positional[1:], *constructor.args.kwonlyargs)}
    fields: set[str] = set()
    for statement in constructor.body:
        if not isinstance(statement, ast.Assign | ast.AnnAssign) or not isinstance(statement.value, ast.Name):
            continue
        if statement.value.id not in parameters:
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        for target in targets:
            if _receiver_attribute(target, receiver):
                fields.add(target.attr)
    return fields


def _constructor(owner: ast.ClassDef) -> ast.FunctionDef | None:
    constructors = [
        method for method in owner.body if isinstance(method, ast.FunctionDef) and method.name == "__init__"
    ]
    if len(constructors) != 1 or constructors[0].decorator_list:
        return None
    return constructors[0]


def _receiver_attribute(expression: ast.expr, receiver: str) -> TypeGuard[ast.Attribute]:
    return (
        isinstance(expression, ast.Attribute)
        and isinstance(expression.value, ast.Name)
        and expression.value.id == receiver
    )


def _backing_field(context: PythonFileContext, method: ast.FunctionDef) -> str | None:
    if (
        method.name.startswith("_")
        or len(method.decorator_list) != 1
        or not _builtin(context, method.decorator_list[0], "property")
    ):
        return None
    positional = method.args.posonlyargs + method.args.args
    if (
        len(positional) != 1
        or method.args.kwonlyargs
        or method.args.vararg
        or method.args.kwarg
        or method.args.defaults
    ):
        return None
    body = _body(method)
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return None
    value = body[0].value
    if not _receiver_attribute(value, positional[0].arg):
        return None
    return value.attr if value.attr.startswith("_") and not value.attr.endswith("__") else None


def _body(method: ast.FunctionDef) -> list[ast.stmt]:
    return method.body[1:] if ast.get_docstring(method) is not None else method.body
