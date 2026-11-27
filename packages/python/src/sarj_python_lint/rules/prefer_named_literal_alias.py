from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NamedTuple, final, override

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
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
from sarj_python_lint.rules._first_party import distribution_root
from sarj_python_lint.rules._imports import TYPING_SOURCES
from sarj_python_lint.rules._literal_domains import literal_aliases, string_literal_members


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex
    from sarj_python_lint.rules._literal_domains import LiteralAlias, LiteralDomainIndex


_INLINE_MESSAGE = "Name this Literal domain with a `type` alias and reuse it instead of inlining it."
_MIN_MEMBERS_FOR_DIFFERENT_NAMES = 3


class _InlineLiteral(NamedTuple):
    location: ast.expr
    members: frozenset[str] | None


class _AnnotationPart(NamedTuple):
    expression: ast.expr
    quoted: ast.Constant | None = None


def _annotations(tree: ast.Module) -> Iterator[ast.expr]:
    for node in ast.walk(tree):
        match node:
            case ast.AnnAssign(annotation=annotation):
                yield annotation
            case ast.arg(annotation=ast.expr() as annotation):
                yield annotation
            case ast.FunctionDef(returns=ast.expr() as returns) | ast.AsyncFunctionDef(returns=ast.expr() as returns):
                yield returns
            case _:
                pass


def _annotation_literals(annotation: ast.expr, imports: ImportIndex) -> Iterator[_InlineLiteral]:
    pending = [_AnnotationPart(annotation)]
    while pending:
        node, quoted = pending.pop()
        match node:
            case ast.Constant(value=str()) if quoted is None:
                if (parsed := AnnotationSemantics.parse(node)) is not None:
                    pending.append(_AnnotationPart(parsed, node))
            case ast.Subscript(value=wrapper) if imports.resolves(wrapper, sources=TYPING_SOURCES, symbol="Literal"):
                if isinstance(node.slice, ast.Tuple) and len(node.slice.elts) > 1:
                    yield _InlineLiteral(quoted or node, string_literal_members(node))
            case _:
                pending.extend(
                    _AnnotationPart(child, quoted) for child in reversed(_annotation_children(node, imports))
                )


def _annotation_children(node: ast.expr, imports: ImportIndex) -> list[ast.expr]:
    match node:
        case ast.Subscript(value=wrapper, slice=ast.Tuple(elts=items)) if imports.resolves(
            wrapper, sources=TYPING_SOURCES, symbol="Annotated"
        ):
            return items[:1]
        case _:
            return [child for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr)]


def _project_domains(context: PythonFileContext) -> LiteralDomainIndex | None:
    session = context.session
    owner = distribution_root(context.path, facts=session.first_party)
    return session.nominal_project.literal_domains(owner, project=session.project) if owner is not None else None


def _inline_message(members: frozenset[str] | None, domains: LiteralDomainIndex | None) -> str:
    if members is None or domains is None:
        return _INLINE_MESSAGE
    aliases = domains.aliases.get(members, [])
    if len(aliases) == 1:
        alias = aliases[0]
        return f"Reuse the existing Literal alias `{alias.name}` from `{alias.module}` instead of inlining this domain."
    if not aliases and len(enums := domains.enums.get(members, [])) == 1:
        enum = enums[0]
        return f"This inline Literal mirrors `{enum.name}` from `{enum.module}`. Share one declaration of the domain."
    return _INLINE_MESSAGE


def _alias_message(alias: LiteralAlias, path: Path, domains: LiteralDomainIndex) -> str | None:
    peers = [
        peer
        for peer in domains.aliases.get(alias.members, [])
        if (peer.path != path or peer.name != alias.name)
        and (len(alias.members) >= _MIN_MEMBERS_FOR_DIFFERENT_NAMES or peer.name == alias.name)
    ]
    if len(peers) == 1 and peers[0].path < path:
        peer = peers[0]
        return f"This Literal alias repeats `{peer.name}` from `{peer.module}`. Reuse one shared alias."
    if not peers and len(enums := domains.enums.get(alias.members, [])) == 1:
        enum = enums[0]
        return f"This Literal alias mirrors `{enum.name}` from `{enum.module}`. Share one declaration of the domain."
    return None


@final
class PreferNamedLiteralAlias(Rule):
    id = "prefer-named-literal-alias"
    code = "SARJ586"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Name multi-member Literal annotations with a reusable type alias.",
        rationale=(
            "An inline multi-member Literal is an anonymous domain. Each copy drifts independently, "
            "and readers cannot tell which annotations share one closed set of values. The same drift "
            "can happen when separate aliases or an Enum describe the same domain."
        ),
        remediation=(
            "Reuse the existing declaration when it expresses the same domain. Otherwise declare "
            '`type Reason = Literal["a", "b"]` once and annotate with `Reason` everywhere the domain is used.'
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Parameter, return and variable annotations are checked; casts and other runtime expressions are not.",
            "A single-member Literal, such as a Pydantic discriminator tag, is accepted inline.",
            "Project matches require explicit string members in the same distribution and omit generated sources.",
            "Aliases in different modules must share a name or at least three members. Ambiguous matches are omitted.",
        ),
        examples=(
            RuleExample(
                example_id="inline-literal-domain",
                title="A parameter repeats an anonymous Literal domain",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/errors.py",
                        "from typing import Literal\n\n\n"
                        "class FallbackError(RuntimeError):\n"
                        '    def __init__(self, reason: Literal["unavailable", "failed"]) -> None:\n'
                        "        super().__init__(reason)\n"
                        '        self.reason: Literal["unavailable", "failed"] = reason\n',
                    ),
                ),
                focus_path=PurePosixPath("app/errors.py"),
                expected_count=2,
                public=True,
            ),
            RuleExample(
                example_id="named-literal-domain",
                title="Annotations share one named Literal alias",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/errors.py",
                        "from typing import Literal\n\n"
                        'type FallbackReason = Literal["unavailable", "failed"]\n\n\n'
                        "class FallbackError(RuntimeError):\n"
                        "    def __init__(self, reason: FallbackReason) -> None:\n"
                        "        super().__init__(reason)\n"
                        "        self.reason: FallbackReason = reason\n",
                    ),
                ),
                focus_path=PurePosixPath("app/errors.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="duplicate-literal-domain",
                title="Separate modules declare the same Literal domain",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile(PurePosixPath("pyproject.toml"), '[project]\nname = "example"\n'),
                    ExampleFile.python(
                        "app/cards.py",
                        'from typing import Literal\ntype CardKind = Literal["charge", "debit", "prepaid"]\n',
                    ),
                    ExampleFile.python(
                        "app/config.py",
                        'from typing import Literal\ntype CardKindName = Literal["prepaid", "charge", "debit"]\n',
                    ),
                ),
                focus_path=PurePosixPath("app/config.py"),
                expected_count=1,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if "Literal" not in context.source or context.generated or context.tree is None:
            return []
        imports = context.module_imports
        aliases = literal_aliases(context.tree, imports)
        inline = [
            literal
            for annotation in _annotations(context.tree)
            for literal in _annotation_literals(annotation, imports)
        ]
        domains = _project_domains(context) if aliases or any(item.members is not None for item in inline) else None
        diagnostics = [
            self._diagnostic(context, item.location, _inline_message(item.members, domains)) for item in inline
        ]
        if domains is not None and aliases:
            module_path = context.path.resolve().with_suffix(".py")
            diagnostics.extend(
                self._diagnostic(context, alias.node, message)
                for alias in aliases
                if (message := _alias_message(alias, module_path, domains)) is not None
            )
        return [item for item in diagnostics if not context.suppressions.is_suppressed(item.line, self.code)]

    def _diagnostic(self, context: PythonFileContext, node: ast.expr, message: str) -> Diagnostic:
        return Diagnostic(
            path=context.path,
            line=node.lineno,
            col=node.col_offset + 1,
            code=self.code,
            message=message,
            severity=Severity.WARNING,
        )
