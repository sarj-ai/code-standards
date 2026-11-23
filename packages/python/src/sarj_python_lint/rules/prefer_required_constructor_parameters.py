from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
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
from sarj_python_lint.rules._ast_position import AstPosition, ast_position
from sarj_python_lint.rules._imports import ABC_SOURCES, TYPING_SOURCES
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._project_index import SymbolRef


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_CONTRACT_BASES = frozenset(
    {
        *(SymbolRef(source, "Protocol") for source in TYPING_SOURCES),
        *(SymbolRef(source, "ABC") for source in ABC_SOURCES),
    }
)
_BUILTIN_NAMES = frozenset(dir(builtins))
_VALUE_MODULES = frozenset({"builtins", "collections.abc", "datetime", "decimal", "pathlib", "typing", "uuid"})
_NESTED_SCOPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


@dataclass(frozen=True, slots=True)
class _Fallback:
    name: str
    value: ast.expr


@dataclass(frozen=True, slots=True)
class _Guard:
    fallback: _Fallback
    target: ast.Name


@final
class PreferRequiredConstructorParameters(ProjectRule):
    id = "prefer-required-constructor-parameters"
    code = "SARJ468"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Prefer required constructor parameters so callers choose dependencies and configuration explicitly.",
        rationale=(
            "Defaulted constructor parameters hide choices at the composition boundary. Replacing None with an empty "
            "string, a constant, or a factory still permits an implicit choice. A required nullable parameter makes "
            "a meaningful absent value explicit without inventing a sentinel. None is not meaningful when the "
            "constructor immediately replaces it with a constructed fallback, or when it stands for a disabled "
            "service that every consumer must re-check instead of receiving a disabled implementation."
        ),
        remediation=(
            "Require the parameter and update callers to pass their choice explicitly; preserve meaningful None values. "
            "Pass the fallback from the composition root, and model a disabled service as an implementation of its "
            "interface. Suppress intentional framework or public-library defaults with a compatibility reason."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        aliases=("discourage-nullable-constructor-parameters",),
        limitations=(
            "This architectural preference is advisory: a default is not necessarily a correctness defect.",
            "Only directly defined __init__ signatures are checked, including class-suite branches and static/class methods; assigned or generated constructors and dataclass fields are not inferred.",
            "Tests, generated files, stubs, and proven overload declarations are excluded. Ambiguous imports, namespace mutation, or escaped overload handles retain the advisory conservatively.",
            "Dynamic decorator replacement and cross-function mutation timing are not inferred.",
            "Required `T | None` parameters warn only when __init__ replaces None with a call-built fallback, or with a class or function reference retained on self and called, or when T is a project-indexed first-party ABC or Protocol declaring a method. Builtin, typing, collections.abc, datetime, decimal, pathlib and uuid value types, rebound parameters, nested-scope fallbacks, Optional/Union spellings and fallbacks outside __init__ are not inferred.",
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
            RuleExample(
                example_id="nullable-constructed-fallback",
                title="Constructor accepts None only to build its own dependency",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "class Service:\n    def __init__(self, timing: Timing | None) -> None:\n"
                        "        self.timing = timing or Timing()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
                scenario="nullable-fallback",
            ),
            RuleExample(
                example_id="nullable-derived-value",
                title="None selects a value derived from the runtime",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "import os\n\nclass Service:\n    def __init__(self, workers: int | None) -> None:\n"
                        "        self.workers = workers or os.cpu_count()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
                scenario="nullable-fallback",
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
                    provenance = context.resource_provenance
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
            findings.extend(_nullable_findings(context, method, self.code))
        return findings


def _nullable_findings(
    context: PythonFileContext, method: ast.FunctionDef | ast.AsyncFunctionDef, code: str
) -> Iterator[Diagnostic]:
    members = {
        parameter.arg: (parameter, member)
        for parameter in _required_parameters(method.args)
        if (member := _nullable_member(parameter.annotation)) is not None
    }
    if not members:
        return
    constructed = _constructed_fallbacks(context, method, set(members))
    for name, (parameter, member) in members.items():
        if name in constructed and not _value_type(context, member):
            message = (
                f"Constructor parameter `{name}` accepts None only to construct a fallback; "
                "require callers to pass the dependency explicitly."
            )
        elif (interface := _interface(context, member)) is not None:
            message = (
                f"Constructor dependency `{name}` is nullable; require a `{interface}` and represent "
                "absence with a disabled implementation of that interface."
            )
        else:
            continue
        yield Diagnostic(
            path=context.path,
            line=parameter.lineno,
            col=parameter.col_offset + 1,
            code=code,
            severity=Severity.WARNING,
            message=message,
        )


def _required_parameters(arguments: ast.arguments) -> list[ast.arg]:
    positional = arguments.posonlyargs + arguments.args
    return positional[: len(positional) - len(arguments.defaults)] + [
        parameter
        for parameter, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
        if default is None
    ]


def _nullable_member(annotation: ast.expr | None) -> ast.expr | None:
    match annotation:
        case ast.Constant(value=str() as text):
            try:
                return _nullable_member(ast.parse(text, mode="eval").body)
            except SyntaxError:
                return None
        case (
            ast.BinOp(left=ast.Constant(value=None), op=ast.BitOr(), right=member)
            | ast.BinOp(left=member, op=ast.BitOr(), right=ast.Constant(value=None))
        ):
            return member
        case _:
            return None


def _reference(member: ast.expr) -> ast.expr:
    match member:
        case ast.Subscript(value=value):
            return value
        case _:
            return member


def _value_type(context: PythonFileContext, member: ast.expr) -> bool:
    match _reference(member):
        case ast.Name(id=name) if name in _BUILTIN_NAMES and context.imports.builtin_is_unshadowed(name):
            return name != "type"
        case reference:
            module, _, name = (context.imports.resolved_qualified_name(reference) or "").rpartition(".")
            return module in _VALUE_MODULES and name != "Callable"


def _interface(context: PythonFileContext, member: ast.expr) -> str | None:
    project = context.session.project
    unit = project.unit(context.path) if project is not None else None
    if project is None or unit is None:
        return None
    summary = project.class_for(unit, _reference(member))
    if summary is None or _CONTRACT_BASES.isdisjoint(summary.bases):
        return None
    source = project.source_unit(summary.symbol.module)
    declaration = next(
        (
            item
            for item in (source.tree.body if source is not None and source.tree is not None else ())
            if isinstance(item, ast.ClassDef) and item.name == summary.symbol.name
        ),
        None,
    )
    if declaration is None or not any(
        isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) for item in declaration.body
    ):
        return None
    return summary.symbol.name


def _constructed_fallbacks(
    context: PythonFileContext, method: ast.FunctionDef | ast.AsyncFunctionDef, names: set[str]
) -> set[str]:
    nodes = [node for statement in method.body for node in _local_nodes(statement)]
    called = _called_self_attributes(context, method)
    guards = [guard for node in nodes if (guard := _guard(node, names)) is not None]
    targets = {guard.target for guard in guards}
    found = {guard.fallback.name for guard in guards if _constructs(guard.fallback.value)}
    found.update(name for node in nodes if (name := _constructed_name(node, names, called)) is not None)
    rebound = {
        node.id
        for node in nodes
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del) and node not in targets
    }
    return found - rebound


def _guard(node: ast.AST, names: set[str]) -> _Guard | None:
    match node:
        case ast.If(
            test=ast.Compare(left=ast.Name(id=name), ops=[ast.Is()], comparators=[ast.Constant(value=None)]),
            body=[ast.Assign(targets=[ast.Name(id=target) as stored], value=value)],
            orelse=[],
        ) if name == target and name in names:
            return _Guard(_Fallback(name, value), stored)
        case _:
            return None


def _constructed_name(node: ast.AST, names: set[str], called: set[str]) -> str | None:
    match node:
        case (
            ast.Assign(targets=[ast.Attribute(value=ast.Name(id="self"), attr=attr)], value=value)
            | ast.AnnAssign(target=ast.Attribute(value=ast.Name(id="self"), attr=attr), value=ast.expr() as value)
        ) if (fallback := _fallback(value, names)) is not None and attr in called:
            return fallback.name
        case _ if (fallback := _fallback(node, names)) is not None and _constructs(fallback.value):
            return fallback.name
        case _:
            return None


def _local_nodes(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, _NESTED_SCOPES):
            yield from _local_nodes(child)


def _fallback(node: ast.AST, names: set[str]) -> _Fallback | None:
    match node:
        case ast.BoolOp(op=ast.Or(), values=[ast.Name(id=name), fallback]) if name in names:
            return _Fallback(name, fallback)
        case ast.IfExp(
            test=ast.Compare(left=ast.Name(id=name), ops=[ast.Is()], comparators=[ast.Constant(value=None)]),
            body=fallback,
            orelse=ast.Name(id=value),
        ) if name in names and value == name:
            return _Fallback(name, fallback)
        case ast.IfExp(
            test=ast.Compare(left=ast.Name(id=name), ops=[ast.IsNot()], comparators=[ast.Constant(value=None)]),
            body=ast.Name(id=value),
            orelse=fallback,
        ) if name in names and value == name:
            return _Fallback(name, fallback)
        case _:
            return None


def _constructs(node: ast.expr) -> bool:
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
    return isinstance(node, ast.Call)


def _called_self_attributes(context: PythonFileContext, method: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    owner = _scope(context, method)
    if not isinstance(owner, ast.ClassDef):
        return set()
    return {
        node.func.attr
        for node in ast.walk(owner)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    }


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


def _binding(provenance: ResourceProvenance, name: str, at: ast.AST) -> ast.AST | None:
    scope = provenance.scope(at)
    deferred = False
    while scope is not None:
        bindings = provenance.bindings.get(scope, {}).get(name, ())
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
    outer = provenance.scope(scope)
    while isinstance(outer, ast.ClassDef):
        outer = provenance.scope(outer)
    return outer


def _declared_binding(
    provenance: ResourceProvenance,
    name: str,
    at: ast.AST,
    scope: ast.AST,
    bindings: Sequence[ast.AST],
) -> ast.AST | None:
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
    bindings = _value_bindings(provenance.bindings.get(destination, {}).get(name, ()))
    bindings = _visible_bindings(bindings, destination, at, deferred=_deferred(provenance.context, at))
    return bindings[0] if len(bindings) == 1 else None


def _nonlocal_scope(provenance: ResourceProvenance, scope: ast.AST, name: str) -> ast.AST | None:
    outer = _enclosing_scope(provenance, scope)
    while outer is not None:
        if isinstance(outer, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            bindings = provenance.bindings.get(outer, {}).get(name, ())
            if bindings and not any(isinstance(binding, ast.Global | ast.Nonlocal) for binding in bindings):
                return outer
        outer = _enclosing_scope(provenance, outer)
    return None


def _directed_write(provenance: ResourceProvenance, destination: ast.AST, name: str, at: ast.AST) -> bool:
    for scope, names in provenance.bindings.items():
        if scope is None or isinstance(scope, ast.Module):
            continue
        bindings = names.get(name, ())
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


def _evaluated_bindings(context: PythonFileContext, bindings: Sequence[ast.AST], at: ast.AST) -> Sequence[ast.AST]:
    if _deferred(context, at):
        return bindings
    return [binding for binding in bindings if _position(binding) <= _position(at)]


def _value_bindings(bindings: Sequence[ast.AST]) -> list[ast.AST]:
    return [binding for binding in bindings if not isinstance(binding, ast.Global | ast.Nonlocal)]


def _visible_bindings(bindings: Sequence[ast.AST], scope: ast.AST, at: ast.AST, *, deferred: bool) -> Sequence[ast.AST]:
    if deferred:
        return bindings
    earlier = [
        binding
        for binding in bindings
        if getattr(  # sarj-noqa: SARJ557 -- Order heterogeneous AST bindings whose marker nodes can omit source locations.
            binding, "lineno", 0
        )
        <= getattr(  # sarj-noqa: SARJ557 -- Order heterogeneous AST bindings whose marker nodes can omit source locations.
            at, "lineno", 0
        )
    ]
    if earlier or not isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        return earlier
    return bindings


def _imported(context: PythonFileContext, binding: ast.AST | None) -> str | None:
    if not isinstance(binding, ast.alias):
        return None
    statement = context.parents.get(binding)
    match statement:
        case ast.Import():
            return binding.name if binding.asname else binding.name.partition(".")[0]
        case ast.ImportFrom() if statement.level == 0 and statement.module is not None:
            return f"{statement.module}.{binding.name}"
        case _:
            pass
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
