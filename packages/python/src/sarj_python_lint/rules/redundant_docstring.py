from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from typing import ClassVar, override

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
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._comments import is_protected, split_identifier, stem
from sarj_python_lint.rules._docstrings import (
    VALUE_MARKER_RE,
    signature_stems,
)
from sarj_python_lint.rules._paths import is_generated


_DOCSTRING_TOKEN_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?|\d+")
_GRAMMATICAL_FILLER = frozenset({"a", "an", "function", "method", "the"})
_GETATTR_MIN_ARGS = 2
_MULTI_PARAMETER_MIN = 2


@dataclass(slots=True)
class _ScanContext:
    path: Path
    source_lines: list[str]
    consumed_docstrings: set[str]
    diagnostics: list[Diagnostic]


class RedundantDocstring(Rule):
    id: str = "redundant-docstring"
    code: str = "SARJ050"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Function or plain-method docstring only repeats its declaration.",
        rationale="Restating a clear name and signature creates maintenance work without helping callers.",
        remediation=(
            "Remove the restatement after confirming `__doc__` is not an external contract. Clarify author-controlled "
            "names or types, and keep prose that documents constraints, side effects, or failure modes."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        aliases=("function-docstring-restates-declaration",),
        limitations=(
            "Decorated functions, methods on decorated or inherited classes, recognized in-file runtime docstring reads, generated files, and docstring-only bodies are excluded.",
            "Every non-grammatical Unicode word or number must already occur in the function name, parameters, or annotations; multi-parameter prose must include a distinguishing word from every parameter.",
        ),
        examples=(
            RuleExample(
                example_id="signature-restatement",
                title="Function docstring only repeats its declaration",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        'def update_message(message_id: str):\n    """Update the message."""\n    return None\n',
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="behavioral-docstring",
                title="Function docstring adds an atomicity guarantee",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        'def update_message(message_id: str):\n    """Replace any existing draft atomically."""\n    return None\n',
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
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
        source_lines = source.splitlines()
        consumed_docstrings = _consumed_docstring_names(tree)
        diags: list[Diagnostic] = []
        context = _ScanContext(path, source_lines, consumed_docstrings, diags)
        self._walk(tree, context)
        return sorted(diags, key=lambda d: d.line)

    def _walk(
        self,
        node: ast.AST,
        context: _ScanContext,
    ) -> None:
        for child in children(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function(child, context)
                self._walk(child, context)
            elif isinstance(child, ast.ClassDef):
                if not child.bases and not child.keywords and not child.decorator_list:
                    self._walk(child, context)
            else:
                self._walk(child, context)

    def _check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        context: _ScanContext,
    ) -> None:
        docstring = ast.get_docstring(node, clean=True)
        if not docstring or VALUE_MARKER_RE.search(docstring) or is_protected(docstring):
            return
        if len(node.body) == 1:
            return  # the docstring IS the body; deleting it leaves a syntax error
        if node.decorator_list or node.name in context.consumed_docstrings:
            return
        known_stems = signature_stems(node, None)
        if node.name.startswith("set_"):
            known_stems.add(stem("update"))
        content = [
            word
            for match in _DOCSTRING_TOKEN_RE.finditer(docstring)
            if (word := match.group(0).lower()) not in _GRAMMATICAL_FILLER
        ]
        content_stems = {stem(word) for word in content}
        parameter_stems = _parameter_stem_groups(node)
        if (
            not content
            or not content_stems <= known_stems
            or not _parameters_are_distinguished(parameter_stems, content_stems)
        ):
            return
        expr = node.body[0]
        if is_suppressed(context.source_lines, expr.lineno, self.code):
            return
        context.diagnostics.append(
            Diagnostic(
                path=context.path,
                line=expr.lineno,
                col=expr.col_offset + 1,
                code=self.code,
                message=self.description,
                severity=Severity.WARNING,
            )
        )


def _parameter_stem_groups(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[set[str]]:
    args = node.args
    parameters = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
    return [
        {stem(part) for part in split_identifier(parameter.arg)}
        for parameter in parameters
        if parameter is not None and parameter.arg not in {"self", "cls"}
    ]


def _parameters_are_distinguished(groups: list[set[str]], content: set[str]) -> bool:
    if len(groups) < _MULTI_PARAMETER_MIN:
        return True
    for index, group in enumerate(groups):
        shared = {
            other_stem for other_index, other in enumerate(groups) if other_index != index for other_stem in other
        }
        distinguishing = group - shared
        if not distinguishing or distinguishing.isdisjoint(content):
            return False
    return True


def _consumed_docstring_names(tree: ast.Module) -> set[str]:
    consumed: set[str] = set()
    aliases: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "__doc__":
            if name := _terminal_name(node.value):
                consumed.add(name)
        elif isinstance(node, ast.Call) and _is_docstring_reader(node):
            if name := _terminal_name(node.args[0]):
                consumed.add(name)
        elif isinstance(node, ast.Subscript):
            if name := _subscripted_docstring_owner(node):
                consumed.add(name)
        elif isinstance(node, ast.Assign) and isinstance(node.value, (ast.Name, ast.Attribute)):
            original = _terminal_name(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name) and original is not None:
                    aliases.setdefault(target.id, set()).add(original)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, (ast.Name, ast.Attribute))
        ):
            original = _terminal_name(node.value)
            if original is not None:
                aliases.setdefault(node.target.id, set()).add(original)
    changed = True
    while changed:
        changed = False
        for alias, originals in aliases.items():
            if alias not in consumed:
                continue
            before = len(consumed)
            consumed.update(originals)
            changed |= len(consumed) != before
    return consumed


def _terminal_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_docstring_reader(node: ast.Call) -> bool:
    if not node.args:
        return False
    function = node.func
    if isinstance(function, ast.Name) and function.id == "help":
        return True
    if isinstance(function, ast.Attribute) and function.attr in {"getdoc", "render_doc"}:
        return True
    return (
        isinstance(function, ast.Name)
        and function.id == "getattr"
        and len(node.args) >= _GETATTR_MIN_ARGS
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "__doc__"
    )


def _subscripted_docstring_owner(node: ast.Subscript) -> str | None:
    if not isinstance(node.slice, ast.Constant) or node.slice.value != "__doc__":
        return None
    value = node.value
    if isinstance(value, ast.Attribute) and value.attr == "__dict__":
        return _terminal_name(value.value)
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "vars" and value.args:
        return _terminal_name(value.args[0])
    return None
