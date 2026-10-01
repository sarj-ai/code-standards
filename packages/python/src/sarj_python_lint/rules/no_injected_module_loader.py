from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

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
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules.no_hidden_constructor_fallback import LocalBindingCollector, scope_bindings


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


_LOADER_TARGETS = frozenset({"importlib.import_module", "importlib.__import__", "builtins.__import__"})


@final
class NoInjectedModuleLoader(Rule):
    id = "no-injected-module-loader"
    code = "SARJ471"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Keep Python module loaders out of application parameter defaults.",
        rationale="Exposing Python's import machinery as an injectable dependency expands the callable contract and hides the concrete imported API behind a generic loader.",
        remediation="Use a normal or lazy import inside the implementation; pass the concrete configuration, object, or domain factory when callers need a real dependency boundary.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Flags defaults resolving to importlib.import_module, importlib.__import__, or builtins.__import__, including stable module-level import and single-assignment aliases and unshadowed __import__.",
            "Tests, test support, and generated code are excluded. Required loader parameters, application loaders, wrapper lambdas, alias chains, comprehensions, and imports local to enclosing scopes are not inferred.",
            "Conservatively skips shadowed or rebound names, wildcard-import files, and files that reassign loader attributes. No autofix: removing an argument changes the callable contract and moving imports can change initialization timing.",
        ),
        examples=(
            RuleExample(
                example_id="injected-loader",
                title="Import machinery becomes a configurable parameter",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "import importlib\ndef run(*, loader=importlib.import_module):\n    return loader('plugin').create()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="lazy-import",
                title="Implementation owns its lazy import",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py", "def run():\n    from plugin import create\n    return create()\n"
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
        if (
            context.tree is None
            or context.generated
            or is_test_path(context.path)
            or is_test_support_path(context.path)
            or _ambiguous_loader_bindings(context)
        ):
            return []
        aliases = _stable_loader_aliases(context)
        findings: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda):
            for argument, default in _defaults(function.args):
                direct = _is_loader(default, context)
                aliased = isinstance(default, ast.Name) and aliases.get(default.id, function.lineno) < function.lineno
                if not (direct or aliased) or _shadowed(default, function, context):
                    continue
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=argument.lineno,
                        col=argument.col_offset + 1,
                        code=self.code,
                        message=f"Parameter `{argument.arg}` exposes Python's module loader; import directly or pass a concrete domain dependency.",
                        severity=Severity.WARNING,
                    )
                )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _ambiguous_loader_bindings(context: PythonFileContext) -> bool:
    if any(alias.name == "*" for node in context.nodes(ast.ImportFrom) for alias in node.names):
        return True
    return any(
        isinstance(node.ctx, (ast.Store, ast.Del))
        and context.module_imports.resolved_qualified_name(node) in _LOADER_TARGETS
        for node in context.nodes(ast.Attribute)
    )


def _defaults(arguments: ast.arguments) -> Iterator[tuple[ast.arg, ast.expr]]:
    positional = (*arguments.posonlyargs, *arguments.args)
    defaulted = positional[-len(arguments.defaults) :] if arguments.defaults else ()
    yield from zip(defaulted, arguments.defaults, strict=True)
    yield from (
        (argument, default)
        for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
        if default is not None
    )


def _is_loader(default: ast.expr, context: PythonFileContext) -> bool:
    if context.module_imports.resolved_qualified_name(default) in _LOADER_TARGETS:
        return True
    return (
        isinstance(default, ast.Name)
        and default.id == "__import__"
        and context.module_imports.builtin_is_unshadowed("__import__")
    )


def _shadowed(default: ast.expr, function: ast.AST, context: PythonFileContext) -> bool:
    root = default
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name):
        return True
    parent = context.parents.get(function)
    while parent is not None:
        if isinstance(parent, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return True
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if root.id in scope_bindings(parent):
                return True
        elif isinstance(parent, ast.ClassDef):
            collector = LocalBindingCollector()
            for statement in parent.body:
                collector.visit(statement)
            if root.id in collector.names:
                return True
        parent = context.parents.get(parent)
    return False


def _stable_loader_aliases(context: PythonFileContext) -> dict[str, int]:
    if context.tree is None:
        return {}
    aliases: dict[str, int] = {}
    for statement in context.tree.body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
            ):
                if (
                    _is_loader(value, context)
                    and _loader_import_precedes(value, statement.lineno, context)
                    and _binding_count(name, context) == 1
                ):
                    aliases[name] = statement.lineno
            case _:
                pass
    return aliases


def _loader_import_precedes(value: ast.expr, line: int, context: PythonFileContext) -> bool:
    root = value
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or context.tree is None:
        return False
    if root.id == "__import__" and context.module_imports.builtin_is_unshadowed(root.id):
        return True
    return any(
        statement.lineno < line
        and any((alias.asname or alias.name.split(".")[0]) == root.id for alias in statement.names)
        for statement in context.tree.body
        if isinstance(statement, (ast.Import, ast.ImportFrom))
    )


def _binding_count(name: str, context: PythonFileContext) -> int:
    return (
        sum(node.id == name and isinstance(node.ctx, (ast.Store, ast.Del)) for node in context.nodes(ast.Name))
        + sum(node.arg == name for node in context.nodes(ast.arg))
        + sum((node.asname or node.name.split(".")[0]) == name for node in context.nodes(ast.alias))
        + sum(
            node.name == name
            for node in context.nodes(
                ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler, ast.MatchAs, ast.MatchStar
            )
        )
        + sum(node.rest == name for node in context.nodes(ast.MatchMapping))
    )
