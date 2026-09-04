from __future__ import annotations

import ast
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
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._comments import is_protected, stem
from sarj_python_lint.rules._docstrings import (
    VALUE_MARKER_RE,
    identifier_stems,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_GRAMMATICAL_FILLER = frozenset({"a", "an", "class", "the"})
_GETATTR_MIN_ARGS = 2
_DOCSTRING_TOKEN_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?|\d+")


class RedundantClassDocstring(Rule):
    id: str = "redundant-class-docstring"
    code: str = "SARJ085"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Undecorated base-free class docstring only repeats the class name.",
        rationale="A name-only restatement adds maintenance cost without documenting the class contract.",
        remediation=(
            "Remove the restatement after confirming `__doc__` is not an external contract. Keep schema descriptions, "
            "runtime-consumed prose, hidden invariants, lifetimes, and exclusions."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        aliases=("class-docstring-restates-name",),
        limitations=(
            "Decorated or inherited classes, recognized in-file runtime docstring reads, generated files, and docstring-only class bodies are excluded.",
            "The rule compares conservative word stems from the class name; any non-grammatical novel term keeps the docstring.",
        ),
        examples=(
            RuleExample(
                example_id="class-name-restatement",
                title="Docstring only repeats the class name",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/policy.py", 'class RetryPolicy:\n    """The retry policy."""\n\n    attempts: int = 3\n'
                    ),
                ),
                focus_path=PurePosixPath("app/policy.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="class-invariant",
                title="Docstring adds a concrete constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/policy.py",
                        'class RetryPolicy:\n    """Retry policy required because the upstream caps concurrency."""\n\n    attempts: int = 3\n',
                    ),
                ),
                focus_path=PurePosixPath("app/policy.py"),
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
        for node in nodes(tree, ast.ClassDef):
            if node.name not in consumed_docstrings and self._is_ceremony(node):
                expr = node.body[0]
                if is_suppressed(source_lines, expr.lineno, self.code):
                    continue
                diags.append(
                    Diagnostic(
                        path=path,
                        line=expr.lineno,
                        col=expr.col_offset + 1,
                        code=self.code,
                        message=self.description,
                        severity=Severity.WARNING,
                    )
                )
        return sorted(diags, key=lambda d: d.line)

    @staticmethod
    def _is_ceremony(node: ast.ClassDef) -> bool:
        docstring = ast.get_docstring(node, clean=True)
        if not docstring or VALUE_MARKER_RE.search(docstring) or is_protected(docstring):
            return False
        if len(node.body) == 1:
            return False  # the docstring IS the body; deleting it leaves a syntax error
        if node.bases or node.keywords or node.decorator_list:
            return False
        known = identifier_stems(node.name)
        content = [
            word
            for match in _DOCSTRING_TOKEN_RE.finditer(docstring)
            if (word := match.group(0).lower()) not in _GRAMMATICAL_FILLER
        ]
        return bool(content) and all(stem(word) in known for word in content)


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
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "vars"
        and value.args
    ):
        return _terminal_name(value.args[0])
    return None
