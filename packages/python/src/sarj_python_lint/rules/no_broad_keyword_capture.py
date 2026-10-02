from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final

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
    is_suppressed,
)
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics, scope_bound_names
from sarj_python_lint.rules._ast_index import walk


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MIN_OVERLOAD_DECLARATIONS = 2
_OVERLOAD_DECORATORS = frozenset({"typing.overload", "typing_extensions.overload"})
_KNOWN_DECORATORS = _OVERLOAD_DECORATORS | {
    "builtins.classmethod",
    "builtins.staticmethod",
    "abc.abstractmethod",
    "typing.final",
    "typing.override",
    "typing_extensions.final",
    "typing_extensions.override",
}


@final
class NoBroadKeywordCapture(Rule):
    id = "no-broad-keyword-capture"
    code = "SARJ477"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Prefer precise keyword interfaces over missing, Any- or object-valued captures.",
        rationale=(
            "Replacing a fixed typed interface with broad **kwargs can erase required keyword names and per-key "
            "value types, making test doubles accept calls the real implementation rejects. object remains a safe "
            "typed top type, and deliberately open data interfaces can be valid; this warning requests interface "
            "review rather than proving every broad capture is defective."
        ),
        remediation=(
            "Keep explicit typed parameters at fixed interfaces. Preserve required keyword names with named unused "
            "local bindings. Use ParamSpec for forwarding, Unpack[TypedDict] for named schemas, or a precise "
            "homogeneous value type. Document genuinely open interfaces with an exact-code reasoned suppression."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This is an advisory interface policy, not proof of incorrect behavior or a universal ban on the object type.",
            "Reports missing, Any- or object-valued keyword captures whether discarded, read or forwarded.",
            "Precise or unresolved decorated signature-declaration families and functions with unresolved decorator effects are excluded; known classmethod/staticmethod/abstractmethod/final/override declarations remain eligible.",
            "Homogeneous keyword types constrain values but allow arbitrary names; ParamSpec preserves only its target's existing contract.",
            "Generated/vendor source and stubs are excluded. Unresolved imports, wildcard imports and shadowed annotation provenance are conservative.",
            "Cross-file aliases, external stubs, generated signatures and runtime reflection are not resolved; transparent annotation metadata and ambiguous decorated declaration families can cause conservative false negatives.",
            "No autofix can infer the intended contract. Dynamic payload/formatting APIs can intentionally need an exact-code exception.",
        ),
        examples=(
            RuleExample(
                example_id="discarded-session-keywords",
                title="An ignored catch-all weakens a fake's contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fakes/session.py",
                        "class Session:\n    async def start(self, **_kwargs: object) -> None:\n        self.start_count += 1\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/fakes/session.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-unused-keywords",
                title="Preserve named typed keywords with a named unused binding",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fakes/session.py",
                        "class Session:\n    async def start(self, *, room: Room, agent: Agent) -> None:\n        _unused_inputs = room, agent\n        self.start_count += 1\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/fakes/session.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="broad-forwarding-arguments",
                title="Forwarding broad arguments still loses the callable contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/adapter.py",
                        "def wrapper(*args: object, **kwargs: object):\n    return target(*args, **kwargs)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/adapter.py"),
                expected_count=1,
                public=True,
                scenario="forwarding",
            ),
            RuleExample(
                example_id="typed-forwarding-arguments",
                title="ParamSpec preserves the forwarded callable contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/adapter.py",
                        "from collections.abc import Callable\ndef wrapper[**P, R](target: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:\n    return target(*args, **kwargs)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/adapter.py"),
                expected_count=0,
                public=True,
                scenario="forwarding",
            ),
            RuleExample(
                example_id="open-template-fields",
                title="A deliberately open formatting interface still requests policy review",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/templates.py",
                        "def render(template: str, **values: object) -> str:\n    return template.format(**values)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/templates.py"),
                expected_count=1,
                public=True,
                scenario="dynamic-boundary",
            ),
            RuleExample(
                example_id="documented-open-template-fields",
                title="Document why template fields require an open object-valued interface",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/templates.py",
                        "def render(template: str, **values: object) -> str:  # sarj-noqa: SARJ477 — template supplies dynamic field names and object formatting\n    return template.format(**values)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/templates.py"),
                expected_count=0,
                public=True,
                scenario="dynamic-boundary",
            ),
        ),
    )
    description = documentation.summary

    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "*" not in context.source or context.generated or context.path.suffix == ".pyi":
            return []
        tree = context.tree
        if tree is None:
            return []
        semantics = AnnotationSemantics.from_tree(tree)
        overloads: set[ast.FunctionDef | ast.AsyncFunctionDef] | None = None
        findings: list[Diagnostic] = []
        for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            argument = function.args.kwarg
            if argument is None:
                continue
            if not _is_broad(argument.annotation, semantics):
                continue
            if _uncertain_annotation(argument.annotation, function, context, semantics):
                continue
            if _unknown_decorator(function, context, semantics):
                continue
            if overloads is None:
                overloads = _overload_implementations(context, semantics)
            if function in overloads:
                continue
            if is_suppressed(context.source_lines, argument.lineno, self.code) or is_suppressed(
                context.source_lines, function.lineno, self.code
            ):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=argument.lineno,
                    col=argument.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"keyword capture `{argument.arg}` has no declared names or narrow value type; "
                        "prefer an explicit typed interface or document a deliberately open contract."
                    ),
                )
            )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _is_broad(annotation: ast.expr | None, semantics: AnnotationSemantics) -> bool:
    if annotation is None:
        return True
    return any(
        (isinstance(member, ast.Name) and member.id == "object" and semantics.imports.builtin_is_unshadowed("object"))
        or semantics.imports.resolved_qualified_name(member)
        in {"typing.Any", "typing_extensions.Any", "builtins.object"}
        for member in semantics.transparent_members(annotation)
    )


def _shadowed_annotation(
    annotation: ast.expr | None,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    semantics: AnnotationSemantics,
) -> bool:
    names = _uses_names(annotation, semantics)
    if names & _type_parameter_names(function):
        return True
    parent = context.parents.get(function)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and names & _scope_bindings(
            parent
        ):
            return True
        parent = context.parents.get(parent)
    return False


def _scope_bindings(owner: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> set[str]:
    bound = scope_bound_names(owner.body) | _type_parameter_names(owner)
    if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = owner.args
        bound.update(arg.arg for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs])
        bound.update(arg.arg for arg in (args.vararg, args.kwarg) if arg is not None)
    return bound


def _has_wildcard_import(context: PythonFileContext) -> bool:
    return any(alias.name == "*" for node in context.nodes(ast.ImportFrom) for alias in node.names)


def _uncertain_annotation(
    annotation: ast.expr | None,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    semantics: AnnotationSemantics,
) -> bool:
    if annotation is None:
        return False
    if _has_wildcard_import(context):
        return True
    if context.tree is not None:
        unknown = scope_bound_names(context.tree.body) - set(semantics.imports.bindings) - set(semantics.aliases)
        if _uses_names(annotation, semantics) & unknown:
            return True
    return _shadowed_annotation(annotation, function, context, semantics)


def _type_parameter_names(owner: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> set[str]:
    return {
        parameter.name
        for parameter in owner.type_params
        if isinstance(parameter, (ast.TypeVar, ast.TypeVarTuple, ast.ParamSpec))
    }


def _uses_names(expression: ast.expr | None, semantics: AnnotationSemantics) -> set[str]:
    parsed = semantics.parse(expression)
    return {node.id for node in walk(parsed) if isinstance(node, ast.Name)} if parsed is not None else set()


def _known_decorator(
    decorator: ast.expr,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    semantics: AnnotationSemantics,
) -> str | None:
    if _has_wildcard_import(context):
        return None
    if _shadowed_annotation(decorator, function, context, semantics):
        return None
    if isinstance(decorator, ast.Name) and decorator.id in {"classmethod", "staticmethod"}:
        if context.tree is not None and decorator.id in scope_bound_names(context.tree.body):
            return None
        if semantics.imports.builtin_is_unshadowed(decorator.id):
            return "builtins." + decorator.id
    return semantics.imports.resolved_qualified_name(decorator)


def _unknown_decorator(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    semantics: AnnotationSemantics,
) -> bool:
    return any(
        _known_decorator(decorator, function, context, semantics) not in _KNOWN_DECORATORS
        for decorator in function.decorator_list
    )


def _overload_implementations(
    context: PythonFileContext,
    semantics: AnnotationSemantics,
) -> set[ast.FunctionDef | ast.AsyncFunctionDef]:
    families: dict[tuple[ast.AST | None, str], list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    implementations: set[ast.FunctionDef | ast.AsyncFunctionDef] = set()
    events = context.nodes(ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Name, ast.Import, ast.ImportFrom)
    for node in sorted(events, key=lambda item: (item.lineno, item.col_offset)):
        scope = _lexical_scope(node, context)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            key = scope, node.name
            if _signature_declaration(node, context, semantics):
                families.setdefault(key, []).append(node)
            else:
                family = families.pop(key, [])
                if _precise_family(family, semantics):
                    implementations.add(node)
        else:
            for name in _rebound_names(node):
                families.pop((scope, name), None)
    return implementations


def _lexical_scope(node: ast.AST, context: PythonFileContext) -> ast.AST | None:
    parent = context.parents.get(node)
    while parent is not None and not isinstance(
        parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    ):
        parent = context.parents.get(parent)
    return parent


def _precise_family(family: list[ast.FunctionDef | ast.AsyncFunctionDef], semantics: AnnotationSemantics) -> bool:
    return len(family) >= _MIN_OVERLOAD_DECLARATIONS and all(
        f.args.kwarg is None or not _is_broad(f.args.kwarg.annotation, semantics) for f in family
    )


def _rebound_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return {node.id}
    if isinstance(node, ast.ClassDef):
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return scope_bound_names([node])
    return set()


def _signature_declaration(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    context: PythonFileContext,
    semantics: AnnotationSemantics,
) -> bool:
    decorators = {_known_decorator(decorator, function, context, semantics) for decorator in function.decorator_list}
    return bool(decorators & _OVERLOAD_DECORATORS) or not decorators <= _KNOWN_DECORATORS
