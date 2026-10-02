from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

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
from sarj_python_lint.rules._ast_index import walk
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_CALLABLE_ARITY = 2

_CALLABLES = frozenset({"typing.Callable", "collections.abc.Callable", "typing_extensions.Callable"})


@final
class RequirePreciseFactorySignature(ProjectRule):
    id = "require-precise-factory-signature"
    code = "SARJ473"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Keep fixed keyword factory calls behind a precise callable signature.",
        rationale="Callable[..., T] erases argument checking, so misspelled keywords and incompatible injected factories pass strict typing and can fail at runtime.",
        remediation="Use an exact callable Protocol for substitutable factories. Use type[T] when this dependency genuinely requires a class, accounting for subclass constructor compatibility.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only undecorated module-level functions with proven standard Callable[..., OwnedClass] parameters directly called with at least one named keyword are considered. Imported classes require scanned first-party declarations.",
            "Tests, test support, generated code, unresolved/string/generic annotations, positional-only calls, unpacking, forwarding, nested captures, rebinding and ambiguous imports are excluded. Import capture checks are conservative across the file, so an unrelated local pattern, exception or walrus binding can prevent a warning.",
            "A fixed call demonstrates signature erasure, not a current runtime defect. Genuine dynamic APIs can use a reasoned suppression. No autofix: the correct contract depends on whether classes or function factories are intended.",
        ),
        examples=(
            RuleExample(
                example_id="erased-factory",
                title="Keyword arguments escape checking",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from collections.abc import Callable\nclass Result: pass\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="exact-factory",
                title="Factory declares its keyword contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from typing import Protocol\nclass Result: pass\nclass Factory(Protocol):\n    def __call__(self, *, size: int) -> Result: ...\ndef build(factory: Factory):\n    return factory(size=4)\n",
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
        tree = context.tree
        if tree is None or context.generated or is_test_path(context.path) or is_test_support_path(context.path):
            return []
        if any(alias.name == "*" for node in context.nodes(ast.ImportFrom) for alias in node.names):
            return []
        findings: list[Diagnostic] = []
        for function in tree.body:
            if (
                not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                or function.decorator_list
                or function.type_params
            ):
                continue
            for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs):
                result = _factory_result(argument.annotation, context)
                if (
                    result is None
                    or not _fixed_calls(function, argument.arg, context)
                    or not _owned_result(result, function, context)
                ):
                    continue
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=argument.lineno,
                        col=argument.col_offset + 1,
                        code=self.code,
                        message=f"`{argument.arg}` is called with fixed keywords but Callable[..., T] erases its argument contract; use a precise callable signature.",
                        severity=Severity.WARNING,
                    )
                )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _factory_result(annotation: ast.expr | None, context: PythonFileContext) -> ast.Name | ast.Attribute | None:
    if (
        not isinstance(annotation, ast.Subscript)
        or context.module_imports.resolved_qualified_name(annotation.value) not in _CALLABLES
    ):
        return None
    if not isinstance(annotation.slice, ast.Tuple) or len(annotation.slice.elts) != _CALLABLE_ARITY:
        return None
    parameters, result = annotation.slice.elts
    if (
        not isinstance(parameters, ast.Constant)
        or parameters.value is not Ellipsis
        or not isinstance(result, (ast.Name, ast.Attribute))
    ):
        return None
    root = _root(annotation.value)
    if (root is not None and _captured_import_root(root, context)) or any(
        isinstance(node.ctx, (ast.Store, ast.Del)) and _root(node) == root for node in context.nodes(ast.Attribute)
    ):
        return None
    return result


def _fixed_calls(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str, context: PythonFileContext) -> bool:
    contents = [node for statement in function.body for node in walk(statement)]
    references = [node for node in contents if isinstance(node, ast.Name) and node.id == name]
    return (
        bool(references)
        and not any(_binds_name(node, name) for node in contents)
        and all(_direct_keyword_call(reference, function, context) for reference in references)
    )


def _direct_keyword_call(
    reference: ast.Name, function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext
) -> bool:
    call = context.parents.get(reference)
    if not isinstance(call, ast.Call) or call.func is not reference or not call.keywords:
        return False
    if any(keyword.arg is None for keyword in call.keywords) or any(isinstance(arg, ast.Starred) for arg in call.args):
        return False
    parent = context.parents.get(call)
    while parent is not None and parent is not function:
        if isinstance(
            parent,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.Lambda,
                ast.ClassDef,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        ):
            return False
        parent = context.parents.get(parent)
    return parent is function


def _owned_result(
    result: ast.Name | ast.Attribute, function: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext
) -> bool:
    tree = context.tree
    if tree is None:
        return False
    root = _root(result)
    if any(isinstance(node.ctx, (ast.Store, ast.Del)) and _root(node) == root for node in context.nodes(ast.Attribute)):
        return False
    local = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and isinstance(result, ast.Name) and node.name == result.id
        ),
        None,
    )
    if local is not None:
        return local.lineno < function.lineno and _stable_class(tree, local.name)
    if root not in context.module_imports.bindings or (root is not None and _captured_import_root(root, context)):
        return False
    project = context.session.project
    if project is None or (unit := project.unit_or_source(context.path, context.source, tree)) is None:
        return False
    summary = project.class_for(unit, result)
    if (
        summary is None
        or (declaration := project.source_unit(summary.symbol.module)) is None
        or declaration.tree is None
    ):
        return False
    return not (
        is_generated(declaration.path, declaration.source)
        or is_test_path(declaration.path)
        or is_test_support_path(declaration.path)
    ) and _stable_class(declaration.tree, summary.symbol.name)


def _stable_class(tree: ast.Module, name: str) -> bool:
    declarations = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    if len(declarations) != 1 or declarations[0].decorator_list:
        return False
    return not any(_binds_name(node, name) for node in walk(tree) if node is not declarations[0])


def _captured_import_root(name: str, context: PythonFileContext) -> bool:
    return any(
        _binds_name(node, name)
        for node in context.nodes(ast.MatchAs, ast.MatchStar, ast.MatchMapping, ast.ExceptHandler)
    ) or any(node.target.id == name for node in context.nodes(ast.NamedExpr))


def _binds_name(node: ast.AST, name: str) -> bool:
    match node:
        case (
            ast.Name(id=bound, ctx=(ast.Store() | ast.Del()))
            | ast.arg(arg=bound)
            | ast.FunctionDef(name=bound)
            | ast.AsyncFunctionDef(name=bound)
            | ast.ClassDef(name=bound)
            | ast.ExceptHandler(name=str() as bound)
            | ast.MatchAs(name=str() as bound)
            | ast.MatchStar(name=str() as bound)
            | ast.MatchMapping(rest=str() as bound)
        ):
            return bound == name
        case ast.alias(name=imported, asname=alias):
            return (alias or imported.split(".")[0]) == name
        case _:
            return False


def _root(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None
