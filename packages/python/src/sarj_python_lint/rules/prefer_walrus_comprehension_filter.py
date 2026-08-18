from __future__ import annotations

import ast
from pathlib import PurePosixPath
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
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, nodes, walk


if TYPE_CHECKING:
    from pathlib import Path


def _check_comprehension_node(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    source_lines: list[str],
    code: str,
    path: Path,
    parents: dict[ast.AST, ast.AST],
) -> list[Diagnostic]:
    if len(node.generators) != 1 or not _has_callable_scope(node, parents):
        return []

    gen = node.generators[0]
    if not gen.ifs:
        return []

    elt_nodes = (
        [node.elt] if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp) else [node.key, node.value]
    )
    calls_in_elts = [
        candidate
        for elt in elt_nodes
        if not any(isinstance(n, ast.Lambda) for n in walk(elt))
        for candidate in walk(elt)
        if isinstance(candidate, ast.Call)
    ]
    diags: list[Diagnostic] = []

    for if_clause in gen.ifs:
        if any(isinstance(n, ast.NamedExpr) for n in walk(if_clause)):
            continue
        calls_in_if = [n for n in walk(if_clause) if isinstance(n, ast.Call)]
        repeated = any(
            not (isinstance(call.func, ast.Name) and call.func.id in {"isinstance", "issubclass", "hasattr", "getattr"})
            and any(ast.compare(call, candidate) for candidate in calls_in_elts)
            for call in calls_in_if
        )
        if not repeated:
            continue
        line = getattr(if_clause, "lineno", 1)
        col = getattr(if_clause, "col_offset", 0) + 1
        if not is_suppressed(source_lines, line, code):
            diags.append(
                Diagnostic(
                    path=path,
                    line=line,
                    col=col,
                    code=code,
                    message=(
                        "Repeated function call in comprehension filter and element — "
                        "bind it once in the filter with a fresh, meaningful name."
                    ),
                )
            )

    return diags


def _has_callable_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    child = node
    while (parent := parents.get(child)) is not None:
        match parent:
            case ast.TypeAlias() | ast.TypeVar() | ast.ParamSpec() | ast.TypeVarTuple():
                return False
            case ast.arg() | ast.AnnAssign() if child is parent.annotation:
                return False
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                if child is parent.returns:
                    return False
                if child in parent.body:
                    return True
            case ast.Lambda():
                if child is parent.body:
                    return True
            case ast.ClassDef():
                if child in parent.body:
                    return False
            case ast.Module():
                return False
            case _:
                pass
        child = parent
    return False


class PreferWalrusComprehensionFilter(Rule):
    id: str = "prefer-walrus-comprehension-filter"
    code: str = "SARJ076"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Evaluate a repeated comprehension call once with a named expression.",
        rationale="Calling the same function in both the filter and result duplicates work and can repeat side effects.",
        remediation="Bind the result to a fresh meaningful name in the filter and use that name in the comprehension result.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only single-generator comprehensions inside callable bodies are analyzed.",
            "Attribute reads, type-narrowing builtins, differing calls, and filters already using a named expression are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-comprehension-call",
                title="Comprehension evaluates one call twice",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/values.py",
                        "def collect(values):\n    return [compute(value) for value in values if compute(value)]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/values.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bound-comprehension-result",
                title="Comprehension evaluates the call once",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/values.py",
                        "def collect(values):\n    return [result for value in values if (result := compute(value))]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/values.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        comprehensions = nodes(tree, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        if not comprehensions:
            return []
        source_lines = source.splitlines()
        diags: list[Diagnostic] = []
        parents = {child: parent for parent in nodes(tree, ast.AST) for child in children(parent)}

        for node in comprehensions:
            diags.extend(_check_comprehension_node(node, source_lines, self.code, path, parents))

        return sorted(diags, key=lambda d: (d.line, d.col))
