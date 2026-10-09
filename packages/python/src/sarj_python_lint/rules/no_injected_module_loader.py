from __future__ import annotations

import ast
from itertools import chain
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
    from collections.abc import Iterator, Mapping

    from sarj_python_lint._file_context import PythonFileContext


_LOADER_TARGETS = frozenset({"importlib.import_module", "importlib.__import__", "builtins.__import__"})
_LEXICAL_SCOPES = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


@final
class NoInjectedModuleLoader(Rule):
    id = "no-injected-module-loader"
    code = "SARJ471"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Avoid a generic module-loader parameter used only to import one fixed module.",
        rationale="When every direct use imports the same literal module, a generic importer can be unnecessary customization rather than a domain dependency. Dynamic plugin/import APIs legitimately need import hooks.",
        remediation="Consider owning the fixed import inside the implementation when import-hook substitution is unnecessary. Preserve intentional import hooks and plugin APIs; do not add wrapper factories or Protocols just to silence this advisory.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Flags defaults resolving to importlib.import_module, importlib.__import__, or builtins.__import__, including stable module-level import and single-assignment aliases and unshadowed __import__.",
            "Every body reference to the parameter must be a direct call with one identical literal module name. Dynamic names, multiple module names, forwarding, returned/captured hooks, rebinding, unpacking and unused defaults are excluded.",
            "Tests, test support, and generated code are excluded. Required loader parameters, application loaders, wrapper lambdas, alias chains, comprehensions, and imports local to enclosing scopes are not inferred.",
            "Conservatively skips shadowed or rebound names, wildcard-import files, reassigned loader attributes, conflicting conditional or relative imports, and exception or pattern captures of importer roots, symbols or assignment aliases. Identical repeated importer imports remain valid. A relevant-name capture in an unrelated local scope can cause a false negative because capture checks are file-wide.",
            "Assignment aliases require one module binding and precede use by line and column. Defaults use their enclosing evaluation scope: earlier statements in the nearest executing class body can shadow loaders; methods and nested classes do not close over class attributes. Enclosing function body bindings remain conservative exclusions, but a function's parameters do not shadow its own defaults. Relevant global declarations and walrus writes exclude sensitive importer names. Compound class statements can cause conservative omissions. Dynamic namespace mutation is not inferred. No autofix: changing arguments or import placement can alter API and initialization behavior.",
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
        ):
            return []
        aliases = _stable_loader_aliases(context)
        if _ambiguous_loader_bindings(context, aliases):
            return []
        findings: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda):
            for argument, default in _defaults(function.args):
                direct = _is_loader(default, context)
                aliased = (
                    isinstance(default, ast.Name)
                    and default.id in aliases
                    and (aliases[default.id].lineno, aliases[default.id].col_offset)
                    < (function.lineno, function.col_offset)
                )
                module_name = _fixed_module_name(context, function, argument.arg)
                if not (direct or aliased) or _shadowed(default, function, context) or module_name is None:
                    continue
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=argument.lineno,
                        col=argument.col_offset + 1,
                        code=self.code,
                        message=(
                            f"Parameter `{argument.arg}` exposes a generic module loader but only imports "
                            f"`{module_name}`; consider an internal import unless this import hook is intentional."
                        ),
                        severity=Severity.WARNING,
                    )
                )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _fixed_module_name(
    context: PythonFileContext, function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, name: str
) -> str | None:
    body = [function.body] if isinstance(function, ast.Lambda) else function.body
    module_names: set[str] = set()
    for reference in chain.from_iterable(ast.walk(statement) for statement in body):
        if not isinstance(reference, ast.Name) or reference.id != name:
            continue
        call = context.parents.get(reference)
        if not isinstance(reference.ctx, ast.Load) or not isinstance(call, ast.Call) or call.func is not reference:
            return None
        if (
            call.keywords
            or len(call.args) != 1
            or not isinstance(call.args[0], ast.Constant)
            or not isinstance(call.args[0].value, str)
        ):
            return None
        parent = context.parents.get(call)
        while parent is not None and parent is not function:
            if isinstance(parent, _LEXICAL_SCOPES):
                return None
            parent = context.parents.get(parent)
        module_names.add(call.args[0].value)
    return next(iter(module_names)) if len(module_names) == 1 else None


def _ambiguous_loader_bindings(context: PythonFileContext, aliases: Mapping[str, ast.stmt]) -> bool:
    if any(alias.name == "*" for node in context.nodes(ast.ImportFrom) for alias in node.names):
        return True
    sensitive_names = {"__import__", *aliases} | {
        name
        for name, target in context.module_imports.bindings.items()
        if (target.module in {"importlib", "builtins"} and target.symbol is None)
        or f"{target.module}.{target.symbol}" in _LOADER_TARGETS
    }
    if _conflicting_loader_imports(context, sensitive_names):
        return True
    if any(sensitive_names.intersection(node.names) for node in context.nodes(ast.Global)):
        return True
    for node in context.nodes(ast.ExceptHandler, ast.MatchAs, ast.MatchStar, ast.MatchMapping, ast.NamedExpr):
        match node:
            case (
                ast.ExceptHandler(name=name)
                | ast.MatchAs(name=name)
                | ast.MatchStar(name=name)
                | ast.MatchMapping(rest=name)
                | ast.NamedExpr(target=ast.Name(id=name))
            ):
                if name in sensitive_names:
                    return True
    return any(
        isinstance(node.ctx, (ast.Store, ast.Del))
        and context.module_imports.resolved_qualified_name(node) in _LOADER_TARGETS
        for node in context.nodes(ast.Attribute)
    )


def _conflicting_loader_imports(context: PythonFileContext, sensitive_names: set[str]) -> bool:
    for statement in context.nodes(ast.Import, ast.ImportFrom):
        if not _is_module_binding(statement, context):
            continue
        for alias in statement.names:
            name = alias.asname or alias.name.partition(".")[0]
            if name in sensitive_names and _loader_import_conflicts(statement, alias, name, context):
                return True
    return False


def _loader_import_conflicts(
    statement: ast.Import | ast.ImportFrom,
    alias: ast.alias,
    name: str,
    context: PythonFileContext,
) -> bool:
    if isinstance(statement, ast.ImportFrom):
        if statement.level or statement.module is None:
            return True
        imported = (statement.module, alias.name)
    else:
        imported = (alias.name if alias.asname else alias.name.partition(".")[0], None)
    binding = context.module_imports.bindings.get(name)
    if binding is not None:
        return imported != (binding.module, binding.symbol)
    return name == "__import__" and ".".join(part for part in imported if part is not None) not in _LOADER_TARGETS


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
    child = function
    parent = context.parents.get(child)
    class_scope_visible = True
    while parent is not None:
        match parent:
            case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                return True
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.Lambda():
                if _in_scope_body(parent, child):
                    if root.id in scope_bindings(parent):
                        return True
                    class_scope_visible = False
            case ast.ClassDef():
                if _in_scope_body(parent, child):
                    if class_scope_visible and _class_prefix_shadows(parent, child, root.id):
                        return True
                    class_scope_visible = False
            case _:
                pass
        child = parent
        parent = context.parents.get(parent)
    return False


def _in_scope_body(scope: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda, child: ast.AST) -> bool:
    # Defaults and class headers execute outside the scope being defined.
    return scope.body is child if isinstance(scope, ast.Lambda) else child in scope.body


def _class_prefix_shadows(owner: ast.ClassDef, containing: ast.AST, name: str) -> bool:
    collector = LocalBindingCollector()
    for statement in owner.body:
        if statement is containing:
            match statement:
                case ast.Assign(value=value) | ast.AnnAssign(value=ast.expr() as value):
                    collector.visit(value)
                case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                    pass
                case _:
                    collector.visit(statement)
            break
        collector.visit(statement)
    return name in collector.names


def _stable_loader_aliases(context: PythonFileContext) -> dict[str, ast.stmt]:
    if context.tree is None:
        return {}
    aliases: dict[str, ast.stmt] = {}
    for statement in context.tree.body:
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=value)
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value)
            ):
                if (
                    _is_loader(value, context)
                    and _loader_import_precedes(value, statement, context)
                    and _binding_count(name, context) == 1
                ):
                    aliases[name] = statement
            case _:
                pass
    return aliases


def _loader_import_precedes(value: ast.expr, assignment: ast.stmt, context: PythonFileContext) -> bool:
    root = value
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or context.tree is None:
        return False
    if root.id == "__import__" and context.module_imports.builtin_is_unshadowed(root.id):
        return True
    return any(
        (statement.lineno, statement.col_offset) < (assignment.lineno, assignment.col_offset)
        and any((alias.asname or alias.name.split(".")[0]) == root.id for alias in statement.names)
        for statement in context.tree.body
        if isinstance(statement, (ast.Import, ast.ImportFrom))
    )


def _binding_count(name: str, context: PythonFileContext) -> int:
    return (
        sum(
            _binds_name(node, name) and _is_module_binding(node, context)
            for node in context.nodes(
                ast.Name,
                ast.alias,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.ExceptHandler,
                ast.MatchAs,
                ast.MatchStar,
                ast.MatchMapping,
            )
        )
        + sum(name in node.names for node in context.nodes(ast.Global))
        + sum(node.target.id == name for node in context.nodes(ast.NamedExpr))
    )


def _binds_name(node: ast.AST, name: str) -> bool:
    match node:
        case (
            ast.Name(id=bound, ctx=(ast.Store() | ast.Del()))
            | ast.FunctionDef(name=bound)
            | ast.AsyncFunctionDef(name=bound)
            | ast.ClassDef(name=bound)
            | ast.ExceptHandler(name=bound)
            | ast.MatchAs(name=bound)
            | ast.MatchStar(name=bound)
            | ast.MatchMapping(rest=bound)
        ):
            return bound == name
        case ast.alias(name=imported, asname=alias):
            return (alias or imported.partition(".")[0]) == name
        case _:
            return False


def _is_module_binding(node: ast.AST, context: PythonFileContext) -> bool:
    while node in context.parents:
        node = context.parents[node]
        if isinstance(node, _LEXICAL_SCOPES):
            return isinstance(node, ast.Module)
    return False
