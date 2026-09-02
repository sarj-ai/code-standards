from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, override

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
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import is_protected, stem
from sarj_python_lint.rules._docstrings import (
    PROMPT_DECORATOR_MARKERS,
    VALUE_MARKER_RE,
    annotation_tokens,
    arg_entries,
    arg_section,
    decorator_markers,
    identifier_stems,
    restates,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_ARGUMENT_CONSTRAINT_RE = re.compile(r"\b(available|current|existing|optional|required|supported)\b", re.IGNORECASE)

_RUNTIME_DOC_DECORATORS = (
    (frozenset({"agents"}), "function_tool"),
    (frozenset({"click"}), "command"),
    (frozenset({"typer"}), "command"),
)

_OVERLOAD_MODULES = frozenset({"typing", "typing_extensions"})


@dataclass(frozen=True, slots=True)
class _ParameterFacts:
    known_stems: frozenset[str]
    annotation_stems: frozenset[str]


class DocstringArgsRestateSignature(Rule):
    id: str = "docstring-args-restate-signature"
    code: str = "SARJ086"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Remove a wholly redundant Google-style Args section when every entry only repeats the function signature.",
        rationale=(
            "Repeated names and types drift and crowd out constraints, units, ownership, and side effects. Complete "
            "parameter tables may remain when a public documentation contract requires them."
        ),
        remediation=(
            "Remove only the redundant Args section; remove the whole docstring only when no section adds behavior. "
            "Keep constraints, accepted formats, units, non-obvious defaults, relationships, and public API semantics "
            "in the docstring."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The rule reads Google-style argument sections and requires every documented entry to be a restatement before reporting.",
            "Generated files, runtime-consumed prompt, CLI, and route docstrings, protected facts, and empty machine-generated stubs are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="argument-restates-signature",
                title="Argument description repeats its name",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/widgets.py",
                        'def count_widgets(tenant_id: str) -> int:\n    """Count active widgets.\n\n    Args:\n        tenant_id: Tenant ID\n    """\n    return 0\n',
                    ),
                ),
                focus_path=PurePosixPath("app/widgets.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="argument-documents-unit",
                title="Unit and sentinel semantics add a contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/widgets.py",
                        'def set_timeout(timeout_ms: int) -> None:\n    """Configure request handling.\n\n    Args:\n        timeout_ms: Request deadline in milliseconds; zero disables retries.\n    """\n',
                    ),
                ),
                focus_path=PurePosixPath("app/widgets.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        self._walk(tree, None, path, ImportIndex.from_tree(tree), diags)
        return sorted(diags, key=lambda d: d.line)

    def _walk(
        self,
        node: ast.AST,
        class_name: str | None,
        path: Path,
        imports: ImportIndex,
        diags: list[Diagnostic],
    ) -> None:
        for child in children(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function(child, class_name, path, imports, diags)
                self._walk(child, class_name, path, imports, diags)
            elif isinstance(child, ast.ClassDef):
                self._walk(child, child.name, path, imports, diags)
            else:
                self._walk(child, class_name, path, imports, diags)

    def _check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None,
        path: Path,
        imports: ImportIndex,
        diags: list[Diagnostic],
    ) -> None:
        docstring = ast.get_docstring(node, clean=True)
        if not docstring:
            return
        block = arg_section(docstring)
        if block is None or VALUE_MARKER_RE.search(block) or is_protected(block):
            return
        if _is_runtime_consumed_or_overload(node, imports):
            return
        entries = arg_entries(block)
        if not entries:
            return
        parameters = _parameter_stems(node, class_name)
        for name, annotation, description in entries:
            if not description:
                return  # a machine-emitted `name (type):` stub — see the module docstring
            normalized_name = name.lstrip("*")
            parameter = parameters.get(normalized_name)
            if parameter is None or _ARGUMENT_CONSTRAINT_RE.search(description):
                return
            known = parameter.known_stems
            signature_annotation = parameter.annotation_stems
            documented_annotation = identifier_stems(annotation)
            if documented_annotation and documented_annotation != signature_annotation:
                return
            if not restates(description, known):
                return
        expr = node.body[0]
        diags.append(
            Diagnostic(
                path=path,
                line=expr.lineno,
                col=expr.col_offset + 1,
                code=self.code,
                message=(
                    f"`{node.name}` has an Args section whose entries only repeat matching parameter names or types; "
                    "remove that section or document a constraint not evident from the signature."
                ),
                severity=Severity.WARNING,
            )
        )


def _parameter_stems(
    node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None
) -> dict[str, _ParameterFacts]:
    callable_stems = identifier_stems(node.name)
    if class_name is not None:
        callable_stems |= identifier_stems(class_name)
    parameters: dict[str, _ParameterFacts] = {}
    args = node.args
    for argument in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
        if argument is None or argument.arg in {"self", "cls"}:
            continue
        annotation_stems = {stem(token) for token in annotation_tokens(argument.annotation)}
        known = callable_stems | identifier_stems(argument.arg) | annotation_stems
        parameters[argument.arg] = _ParameterFacts(frozenset(known), frozenset(annotation_stems))
    return parameters


def _is_runtime_consumed_or_overload(node: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> bool:
    if decorator_markers(node) & PROMPT_DECORATOR_MARKERS:
        return True
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if imports.resolves(target, sources=_OVERLOAD_MODULES, symbol="overload"):
            return True
        if any(imports.resolves(target, sources=sources, symbol=symbol) for sources, symbol in _RUNTIME_DOC_DECORATORS):
            return True
    return False
