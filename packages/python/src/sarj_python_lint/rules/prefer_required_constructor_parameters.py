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
from sarj_python_lint.rules._ast_position import AstPosition, ast_position
from sarj_python_lint.rules._imports import TYPING_SOURCES
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@final
class PreferRequiredConstructorParameters(Rule):
    id = "prefer-required-constructor-parameters"
    code = "SARJ468"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Prefer required constructor parameters so callers choose dependencies and configuration explicitly.",
        rationale=(
            "Defaulted constructor parameters hide choices at the composition boundary. Replacing None with an empty "
            "string, a constant, or a factory still permits an implicit choice. A required nullable parameter makes "
            "a meaningful absent value explicit without inventing a sentinel."
        ),
        remediation=(
            "Require the parameter and update callers to pass their choice explicitly; preserve meaningful None values. "
            "Suppress intentional framework or public-library defaults with a compatibility reason."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        aliases=("discourage-nullable-constructor-parameters",),
        limitations=(
            "This architectural preference is advisory: a default is not necessarily a correctness defect.",
            "Only directly defined __init__ signatures are checked, including class-suite branches and static/class methods; assigned or generated constructors and dataclass fields are not inferred.",
            "Tests, generated files, stubs, and proven overload declarations are excluded. Ambiguous imports, namespace mutation, or escaped overload handles retain the advisory conservatively.",
            "Dynamic decorator replacement and cross-function mutation timing are not inferred.",
            "Removing defaults can break callers, so the rule does not autofix signatures.",
        ),
        examples=(
            RuleExample(
                example_id="defaulted-choice",
                title="Constructor silently selects an empty configuration",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        'class Service:\n    def __init__(self, agent_name: str = "") -> None:\n'
                        "        self.agent_name = agent_name\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-absent-choice",
                title="Caller explicitly chooses an absent configuration",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "class Service:\n    def __init__(self, agent_name: str | None) -> None:\n        self.agent_name = agent_name\n",
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
        if context.generated or context.tree is None or is_test_path(context.path) or context.path.suffix == ".pyi":
            return []
        findings: list[Diagnostic] = []
        provenance: ResourceProvenance | None = None
        for method in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            if method.name != "__init__" or not isinstance(_scope(context, method), ast.ClassDef):
                continue
            if method.decorator_list:
                if provenance is None:
                    provenance = _overload_provenance(context)
                if _is_overload(context, provenance, method):
                    continue
            findings.extend(
                Diagnostic(
                    path=context.path,
                    line=parameter.lineno,
                    col=parameter.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"Constructor parameter `{parameter.arg}` has a default; "
                        "prefer requiring callers to pass their choice explicitly."
                    ),
                )
                for parameter in _defaulted_parameters(method.args)
            )
        return findings


def _defaulted_parameters(arguments: ast.arguments) -> list[ast.arg]:
    positional = arguments.posonlyargs + arguments.args
    return positional[len(positional) - len(arguments.defaults) :] + [
        parameter
        for parameter, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
        if default is not None
    ]


def _scope(context: PythonFileContext, node: ast.AST) -> ast.AST | None:
    parent = context.parents.get(node)
    while parent is not None and not isinstance(
        parent, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    ):
        parent = context.parents.get(parent)
    return parent


def _overload_provenance(context: PythonFileContext) -> ResourceProvenance:
    provenance = ResourceProvenance(context)
    comprehensions = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
    for expression in context.nodes(ast.NamedExpr):
        target = expression.target
        original = provenance.scope(target)
        if not isinstance(original, comprehensions):
            continue
        # Assignment expressions in comprehensions bind in the containing
        # scope, unlike iteration targets, which stay comprehension-local.
        containing = original
        while isinstance(containing, comprehensions):
            containing = provenance.scope(containing)
        provenance.bindings[original][target.id].remove(target)
        provenance.bindings[containing][target.id].append(target)
    return provenance


def _binding(provenance: ResourceProvenance, name: str, at: ast.AST) -> ast.AST | None:
    scope = provenance.scope(at)
    deferred = False
    while scope is not None:
        bindings = provenance.bindings.get(scope, {}).get(name, [])
        directives = [binding for binding in bindings if isinstance(binding, ast.Global | ast.Nonlocal)]
        if directives and not isinstance(scope, ast.Module):
            return _declared_binding(provenance, name, at, scope, bindings)
        bindings = _value_bindings(bindings)
        bindings = _visible_bindings(bindings, scope, at, deferred=deferred)
        if bindings:
            return bindings[0] if len(bindings) == 1 and not _directed_write(provenance, scope, name, at) else None
        deferred |= isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda)
        scope = _enclosing_scope(provenance, scope)
    return None


def _enclosing_scope(provenance: ResourceProvenance, scope: ast.AST) -> ast.AST | None:
    # A class body can see its own namespace, but enclosing classes do not
    # become lexical closures for nested classes or functions.
    outer = provenance.scope(scope)
    while isinstance(outer, ast.ClassDef):
        outer = provenance.scope(outer)
    return outer


def _declared_binding(
    provenance: ResourceProvenance,
    name: str,
    at: ast.AST,
    scope: ast.AST,
    bindings: list[ast.AST],
) -> ast.AST | None:
    # A declaration redirects lookup; it does not replace the value. Writes
    # through that declaration retain the conservative warning in every scope.
    bindings = _evaluated_bindings(provenance.context, bindings, at)
    if any(not isinstance(binding, ast.Global | ast.Nonlocal) for binding in bindings):
        return None
    destination = (
        provenance.context.tree
        if any(isinstance(binding, ast.Global) for binding in bindings)
        else _nonlocal_scope(provenance, scope, name)
    )
    if destination is None or _directed_write(provenance, destination, name, at):
        return None
    bindings = _value_bindings(provenance.bindings.get(destination, {}).get(name, []))
    bindings = _visible_bindings(bindings, destination, at, deferred=_deferred(provenance.context, at))
    return bindings[0] if len(bindings) == 1 else None


def _nonlocal_scope(provenance: ResourceProvenance, scope: ast.AST, name: str) -> ast.AST | None:
    outer = _enclosing_scope(provenance, scope)
    while outer is not None:
        if isinstance(outer, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            bindings = provenance.bindings.get(outer, {}).get(name, [])
            if bindings and not any(isinstance(binding, ast.Global | ast.Nonlocal) for binding in bindings):
                return outer
        outer = _enclosing_scope(provenance, outer)
    return None


def _directed_write(provenance: ResourceProvenance, destination: ast.AST, name: str, at: ast.AST) -> bool:
    for scope, names in provenance.bindings.items():
        if scope is None or isinstance(scope, ast.Module):
            continue
        bindings = names.get(name, [])
        directives = [binding for binding in bindings if isinstance(binding, ast.Global | ast.Nonlocal)]
        writes = _value_bindings(bindings)
        if not directives or not writes or not _evaluated_bindings(provenance.context, writes, at):
            continue
        target = (
            provenance.context.tree
            if any(isinstance(directive, ast.Global) for directive in directives)
            else _nonlocal_scope(provenance, scope, name)
        )
        if target is destination:
            return True
    return False


def _evaluated_bindings(context: PythonFileContext, bindings: list[ast.AST], at: ast.AST) -> list[ast.AST]:
    if _deferred(context, at):
        return bindings
    return [binding for binding in bindings if _position(binding) <= _position(at)]


def _value_bindings(bindings: list[ast.AST]) -> list[ast.AST]:
    return [binding for binding in bindings if not isinstance(binding, ast.Global | ast.Nonlocal)]


def _visible_bindings(bindings: list[ast.AST], scope: ast.AST, at: ast.AST, *, deferred: bool) -> list[ast.AST]:
    if deferred:
        return bindings
    earlier = [binding for binding in bindings if getattr(binding, "lineno", 0) <= getattr(at, "lineno", 0)]
    # A future function local cannot fall back to an outer name, whereas a
    # class or module lookup can still use a prior enclosing import.
    if earlier or not isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        return earlier
    return bindings


def _imported(context: PythonFileContext, binding: ast.AST | None) -> str | None:
    if not isinstance(binding, ast.alias):
        return None
    statement = context.parents.get(binding)
    if isinstance(statement, ast.Import):
        return binding.name if binding.asname else binding.name.partition(".")[0]
    if isinstance(statement, ast.ImportFrom) and statement.level == 0 and statement.module is not None:
        return f"{statement.module}.{binding.name}"
    return None


def _is_overload(
    context: PythonFileContext,
    provenance: ResourceProvenance,
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    for decorator in method.decorator_list:
        root = decorator.value if isinstance(decorator, ast.Attribute) and decorator.attr == "overload" else decorator
        if not isinstance(root, ast.Name):
            continue
        binding = _binding(provenance, root.id, method)
        if not isinstance(binding, ast.alias):
            continue
        target = _imported(context, binding)
        qualified = f"{target}.overload" if isinstance(decorator, ast.Attribute) else target
        if qualified not in {f"{source}.overload" for source in TYPING_SOURCES}:
            continue
        if not _overload_changed(
            context,
            provenance,
            method,
            qualified,
            module_before=_module_capture(context, method if isinstance(decorator, ast.Attribute) else binding),
        ):
            return True
    return False


def _overload_changed(
    context: PythonFileContext,
    provenance: ResourceProvenance,
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    qualified: str,
    *,
    module_before: AstPosition | None,
) -> bool:
    module = qualified.rpartition(".")[0]
    deferred = _deferred(context, method)
    signature_reads = _default_reads(method.args)
    for read in context.nodes(ast.Name):
        if not isinstance(read.ctx, ast.Load):
            continue
        if not deferred and read not in signature_reads and _position(read) > _position(method):
            continue
        imported = _imported(context, _binding(provenance, read.id, method if read in signature_reads else read))
        if imported not in {qualified, module}:
            continue
        parent = context.parents.get(read)
        if (
            imported == module
            and module_before is not None
            and _position(read) > module_before
            and _namespace_rebinding(parent)
        ):
            continue
        if _unsafe_overload_read(context, read, namespace=imported == module):
            return True
    return False


def _default_reads(arguments: ast.arguments) -> set[ast.Name]:
    defaults = [*arguments.defaults, *(default for default in arguments.kw_defaults if default is not None)]
    return {node for default in defaults for node in ast.walk(default) if isinstance(node, ast.Name)}


def _namespace_rebinding(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "overload" and isinstance(node.ctx, ast.Store | ast.Del)


def _position(node: ast.AST) -> AstPosition:
    return ast_position(node, missing=-1)


def _module_capture(context: PythonFileContext, node: ast.AST) -> AstPosition | None:
    return None if _deferred(context, node) else _position(node)


def _deferred(context: PythonFileContext, node: ast.AST) -> bool:
    scope = _scope(context, node)
    while isinstance(scope, ast.ClassDef):
        scope = _scope(context, scope)
    return isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda)


def _unsafe_overload_read(context: PythonFileContext, read: ast.Name, *, namespace: bool) -> bool:
    expression: ast.expr = read
    parent = context.parents.get(expression)
    if isinstance(parent, ast.arguments):
        return False
    if namespace and isinstance(parent, ast.Attribute) and parent.attr != "overload":
        return parent.attr in {"__dict__", "__setattr__", "__delattr__", "__getattribute__", "__getattr__"}
    while isinstance(parent, ast.Attribute):
        if isinstance(parent.ctx, ast.Store | ast.Del):
            return True
        expression = parent
        parent = context.parents.get(expression)
    if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and expression in parent.decorator_list:
        return False
    direct_overload = expression is read or (
        namespace and isinstance(expression, ast.Attribute) and expression.value is read
    )
    return not (direct_overload and isinstance(parent, ast.Call) and parent.func is expression)
