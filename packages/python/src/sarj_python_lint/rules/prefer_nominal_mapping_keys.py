from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    DiagnosticSubject,
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


_MAPPING_TYPES = frozenset(
    {
        "builtins.dict",
        "typing.Dict",
        "typing.Mapping",
        "typing.MutableMapping",
        "collections.abc.Mapping",
        "collections.abc.MutableMapping",
    }
)
_PRIMITIVES = frozenset({"str", "int", "float", "bool", "bytes"})
_MAPPING_ARITY = 2
_MAX_METADATA_DEPTH = 8
_METADATA = frozenset({"typing.ClassVar", "typing_extensions.ClassVar", "typing.Final", "typing_extensions.Final"})


@final
class PreferNominalMappingKeys(Rule):
    id = "prefer-nominal-mapping-keys"
    code = "SARJ568"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Declare record shapes or nominal keys at primitive-keyed mapping boundaries.",
        rationale="A primitive mapping erases both fixed record keys and the domain identity of dynamic keys.",
        remediation="Use a TypedDict or validated model for a fixed record; for a dynamic domain mapping use a nominal NewType identifier or enum key. Preserve intentionally open transport and algorithm contracts with a reasoned local exception.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Reviews public function parameters and returns, public class fields and public module type aliases whose mappings use primitive keys and primitive or primitive-container values. Private class implementation maps are excluded. This is domain-modeling advice, not proof that every dictionary is a closed record.",
            "Private algorithm helpers, local variables, ClassVar/Final metadata, Any/object/JsonValue-valued mappings, nominal or enum keys, tests and generated files are excluded. Existing schema-free mapping rules own Any/object payloads.",
            "Standard import aliases, Optional/Annotated wrappers, nested containers and quoted annotations are recognized. A local mapping alias is reported at its declaration rather than again at every use. Imported aliases and opaque value types are not expanded.",
            "No automatic TypedDict, NewType or enum construction is safe without knowing allowed keys, persistence and serialization contracts.",
        ),
        examples=(
            RuleExample(
                example_id="undeclared-domain",
                title="The contract is implicit",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/service.py", "class Report:\n    timings: dict[str, float]\n"),),
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
                        "from typing import TypedDict\nclass Timings(TypedDict):\n    total: float\nclass Report:\n    timings: Timings\n",
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
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        facts = AnnotationOrigins(context)
        findings: list[Diagnostic] = []
        for anchor, annotation in _boundaries(context):
            if context.suppressions.is_suppressed(anchor.lineno, self.code):
                continue
            parsed = context.annotation_semantics.parse(annotation)
            if parsed is None or _metadata(parsed, annotation, facts):
                continue
            if not any(_primitive_mapping(node, annotation, facts) for node in ast.walk(parsed)):
                continue
            findings.append(
                Diagnostic(
                    context.path,
                    anchor.lineno,
                    anchor.col_offset + 1,
                    self.code,
                    "This primitive-keyed mapping hides a record shape or key domain; use a TypedDict for fixed fields "
                    "or nominal identifier/enum keys for a dynamic domain mapping.",
                    severity=Severity.WARNING,
                    subject=DiagnosticSubject.RETURN if _return_annotation(anchor, context) else None,
                )
            )
        return findings


def _boundaries(context: PythonFileContext) -> Iterator[tuple[ast.arg | ast.expr | ast.stmt, ast.expr]]:
    yield from _declaration_boundaries(context)
    yield from _callable_boundaries(context)


def _declaration_boundaries(context: PythonFileContext) -> Iterator[tuple[ast.stmt, ast.expr]]:
    for node in context.nodes(ast.AnnAssign):
        parent = context.parents.get(node)
        if isinstance(parent, ast.ClassDef) and not parent.name.startswith("_"):
            yield node, node.annotation
        elif (
            parent is context.tree
            and isinstance(node.target, ast.Name)
            and not node.target.id.startswith("_")
            and node.value is not None
            and context.module_imports.resolved_qualified_name(node.annotation)
            in {
                "typing.TypeAlias",
                "typing_extensions.TypeAlias",
            }
        ):
            yield node, node.value
    for node in context.nodes(ast.TypeAlias):
        if context.parents.get(node) is context.tree and not node.name.id.startswith("_"):
            yield node, node.value


def _callable_boundaries(context: PythonFileContext) -> Iterator[tuple[ast.arg | ast.expr, ast.expr]]:
    for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
        parent = context.parents.get(node)
        if isinstance(parent, ast.ClassDef) and parent.name.startswith("_"):
            continue
        if node.name.startswith("_") or not isinstance(context.parents.get(node), ast.Module | ast.ClassDef):
            continue
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if argument.annotation is not None:
                yield argument, argument.annotation
        if node.returns is not None:
            yield node.returns, node.returns


def _metadata(node: ast.expr, at: ast.expr, facts: AnnotationOrigins) -> bool:
    for _ in range(_MAX_METADATA_DEPTH):
        resolved = facts.resolve_annotation(node, at=at)
        if resolved is None or not isinstance(resolved.expression, ast.Subscript):
            return False
        node, at = resolved.expression, resolved.at
        qualified = facts.qualified(node.value, at)
        if qualified in _METADATA:
            return True
        if qualified not in {"typing.Annotated", "typing_extensions.Annotated"}:
            return False
        node = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) and node.slice.elts else node.slice
    return False


def _return_annotation(node: ast.AST, context: PythonFileContext) -> bool:
    parent = context.parents.get(node)
    return isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and parent.returns is node


def _primitive_mapping(node: ast.AST, at: ast.expr, facts: AnnotationOrigins) -> bool:
    if (
        not isinstance(node, ast.Subscript)
        or not isinstance(node.slice, ast.Tuple)
        or len(node.slice.elts) != _MAPPING_ARITY
    ):
        return False
    if not (facts.builtin(node.value, "dict", at) or facts.qualified(node.value, at) in _MAPPING_TYPES):
        return False
    key, value = node.slice.elts
    return _primitive(key, at, facts) and any(
        isinstance(member, ast.expr) and _primitive(member, at, facts) for member in ast.walk(value)
    )


def _primitive(node: ast.expr, at: ast.expr, facts: AnnotationOrigins) -> bool:
    resolved = facts.resolve_annotation(node, at=at)
    return (
        resolved is not None
        and isinstance(resolved.expression, ast.Name)
        and resolved.expression.id in _PRIMITIVES
        and facts.builtin(resolved.expression, resolved.expression.id, resolved.at)
    )
