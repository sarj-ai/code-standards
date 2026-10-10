from __future__ import annotations

import ast
import builtins
from pathlib import PurePosixPath
from typing import (
    TYPE_CHECKING,
    ClassVar,
    cast,  # ruff: ignore[banned-api] -- vars exposes Any; the object view permits isinstance narrowing.
    final,
    override,
)

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
    is_suppressed,
)
from sarj_python_lint.rules._closed_helpers import dynamic_namespace, stable_class
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules._resource_provenance import ResourceProvenance
from sarj_python_lint.rules._suppression_comments import scan_comments


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import SourceUnit, SymbolRef
    from sarj_python_lint.rules._suppression_comments import Comment


_BUILTIN_NAMESPACE = cast("Mapping[str, object]", vars(builtins))
_BUILTIN_EXCEPTIONS = frozenset(
    name for name, value in _BUILTIN_NAMESPACE.items() if isinstance(value, type) and issubclass(value, Exception)
)
_BAD = "try:\n    action()\nexcept ValueError as error:\n    raise RuntimeError('invalid') from error\nexcept TypeError as error:\n    raise RuntimeError('invalid') from error\n"
_GOOD = "try:\n    action()\nexcept (ValueError, TypeError) as error:\n    raise RuntimeError('invalid') from error\n"


@final
class DuplicateAdjacentExceptionHandler(ProjectRule):
    id = "duplicate-adjacent-exception-handler"
    code = "SARJ488"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Adjacent exception handlers repeat the same executable translation.",
        rationale="Repeating one translation for adjacent statically known exception classes creates extra branches to maintain without different behavior.",
        remediation="Consider one tuple handler for the adjacent exception types. Preserve distinct messages, cleanup, ordering, and intentional independently maintained translations.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only ordinary try statements with adjacent handlers, identical exception bindings, executable ASTs and comments are compared; exception groups and bare re-raise/pass handlers are excluded.",
            "Handler types must be simple names or tuples of unshadowed builtin or statically resolved first-party Exception subclasses, with unconditional stable declarations/imports.",
            "Dynamic namespace access, unknown external exception classes, generated/vendor sources, different comments, and intervening handlers are excluded. No autofix preserves intentional translation seams.",
        ),
        examples=tuple(
            RuleExample(
                example_id=name,
                title=title,
                outcome=outcome,
                files=(ExampleFile.python("app/service.py", source),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=count,
                public=True,
            )
            for name, title, outcome, source, count in (
                ("repeated-translation", "Adjacent handlers translate identically", ExampleOutcome.MATCH, _BAD, 1),
                ("one-tuple-handler", "One handler owns the shared translation", ExampleOutcome.NO_MATCH, _GOOD, 0),
            )
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        tree = context.tree
        if context.generated or tree is None or "except" not in context.symbol_source or dynamic_namespace(context):
            return []
        project = context.session.project or ProjectIndexSet.single(context.path, context.source)
        unit = project.unit_or_source(context.path, context.source, tree)
        provenance = ResourceProvenance(context)
        comments = scan_comments(context.source)
        findings: list[Diagnostic] = []
        for statement in context.nodes(ast.Try):
            previous: ast.ExceptHandler | None = None
            reported = False
            for handler in statement.handlers:
                safe = _safe_types(handler.type, context, provenance, project, unit, seen=set())
                if previous is not None and safe and _same_translation(previous, handler, comments):
                    if not reported and not is_suppressed(context.source_lines, handler.lineno, self.code):
                        findings.append(
                            Diagnostic(
                                path=context.path,
                                line=handler.lineno,
                                col=handler.col_offset + 1,
                                code=self.code,
                                severity=Severity.WARNING,
                                message="Adjacent exception handlers have identical translations; consider one tuple handler, preserving intentional separate error contracts.",
                            )
                        )
                    reported = True
                else:
                    reported = False
                previous = handler if safe else None
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _same_translation(first: ast.ExceptHandler, second: ast.ExceptHandler, comments: list[Comment]) -> bool:
    if first.name != second.name or not first.body or first.type is None or second.type is None:
        return False
    if not {node.id for node in ast.walk(first.type) if isinstance(node, ast.Name)}.isdisjoint(
        node.id for node in ast.walk(second.type) if isinstance(node, ast.Name)
    ):
        return False
    if len(first.body) == 1 and (
        isinstance(first.body[0], ast.Pass) or (isinstance(first.body[0], ast.Raise) and first.body[0].exc is None)
    ):
        return False
    if ast.dump(ast.Module(body=first.body, type_ignores=[])) != ast.dump(
        ast.Module(body=second.body, type_ignores=[])
    ):
        return False
    if any((first.end_lineno or first.lineno) < comment.line < second.lineno for comment in comments):
        return False
    return _comments(first, comments) == _comments(second, comments)


def _comments(handler: ast.ExceptHandler, comments: list[Comment]) -> list[str]:
    return [
        comment.body for comment in comments if handler.lineno <= comment.line <= (handler.end_lineno or handler.lineno)
    ]


def _safe_types(
    expression: ast.expr | None,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    project: ProjectIndexSet,
    unit: SourceUnit | None,
    *,
    seen: set[SymbolRef],
) -> bool:
    if isinstance(expression, ast.Tuple):
        return bool(expression.elts) and all(
            _safe_types(element, context, provenance, project, unit, seen=seen) for element in expression.elts
        )
    if not isinstance(expression, ast.Name):
        return False
    if (
        expression.id in _BUILTIN_EXCEPTIONS
        and context.imports.builtin_is_unshadowed(expression.id)
        and provenance.binding(expression.id, expression) is None
    ):
        return True
    return _first_party_exception(expression, context, provenance, project, unit, seen=seen)


def _first_party_exception(
    expression: ast.Name,
    context: PythonFileContext,
    provenance: ResourceProvenance,
    project: ProjectIndexSet,
    unit: SourceUnit | None,
    *,
    seen: set[SymbolRef],
) -> bool:
    from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- defer until the rule registry finishes loading.

    binding = provenance.binding(expression.id, expression)
    if not isinstance(binding, ast.ClassDef | ast.alias) or unit is None:
        return False
    if isinstance(binding, ast.alias):
        statement = context.parents.get(binding)
        if statement is None or context.parents.get(statement) is not context.tree:
            return False
    summary = project.class_for(unit, expression)
    if (
        summary is None
        or summary.symbol in seen
        or (owner := project.source_unit(summary.symbol.module)) is None
        or owner.tree is None
        or is_generated(owner.path, owner.source)
    ):
        return False
    definition_context = (
        context if owner.path == context.path else PythonFileContext(owner.path, owner.source, context.session)
    )
    definition_provenance = provenance if definition_context is context else ResourceProvenance(definition_context)
    declaration = next(
        (node for node in definition_context.nodes(ast.ClassDef) if node.name == summary.symbol.name), None
    )
    return (
        declaration is not None
        and stable_class(definition_context, declaration, definition_provenance)
        and len(declaration.bases) == 1
        and _safe_types(
            declaration.bases[0],
            definition_context,
            definition_provenance,
            project,
            owner,
            seen=seen | {summary.symbol},
        )
    )
