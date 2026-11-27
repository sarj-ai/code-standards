from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
from sarj_python_lint.rules._sequence_iteration import only_index_reads, stable_iteration_nodes


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MUTATORS = frozenset({"append", "extend", "insert", "pop", "remove", "clear", "sort", "reverse"})


@final
class PreferDirectIteration(Rule):
    id = "prefer-direct-iteration"
    code = "SARJ606"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Iterate a sequence directly when range(len()) only indexes it.",
        rationale="An index that only reads the corresponding sequence item obscures a direct iteration over values.",
        remediation="Replace range(len(sequence)) and sequence[index] reads with a direct loop over sequence items.",
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only synchronous for loops over range(len(sequence)) with a name target and a name or dotted attribute operand are checked. Operand types are not inferred; review custom indexing semantics before rewriting.",
            "Every index read in the body and else must be the exact sequence[index] read. Mutation, rebinding, index-capturing nested scopes, shadowed range/len, generated sources and stub files are excluded. There is no automatic fix.",
        ),
        examples=(
            RuleExample(
                example_id="index-only-reads",
                title="The index only reads sequence items",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "iteration.py",
                        "def run(files):\n    for index in range(len(files)):\n        consume(files[index])\n",
                    ),
                ),
                focus_path=PurePosixPath("iteration.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="direct-values",
                title="Iterate values directly",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "iteration.py", "def run(files):\n    for item in files:\n        consume(item)\n"
                    ),
                ),
                focus_path=PurePosixPath("iteration.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.path.suffix == ".pyi" or context.generated or "range" not in context.source or context.tree is None:
            return []
        if any(name in names for names in context.binding_inventory.bindings.values() for name in ("range", "len")):
            return []
        diagnostics: list[Diagnostic] = []
        for loop in context.nodes(ast.For):
            match loop:
                case ast.For(
                    target=ast.Name(id=index),
                    iter=ast.Call(
                        func=ast.Name(id="range"),
                        args=[ast.Call(func=ast.Name(id="len"), args=[sequence], keywords=[])],
                        keywords=[],
                    ),
                ):
                    pass
                case _:
                    continue
            if not _only_reads(loop, sequence, index) or context.suppressions.is_suppressed(loop.lineno, self.code):
                continue
            subject = ast.unparse(sequence)
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=loop.lineno,
                    col=loop.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=f"`for {index} in range(len({subject}))` uses the index only to read `{subject}[{index}]`; iterate `for item in {subject}` directly.",
                )
            )
        return diagnostics


def _only_reads(loop: ast.For, sequence: ast.expr, index: str) -> bool:
    nodes = stable_iteration_nodes((*loop.body, *loop.orelse), sequence, index)
    if nodes is None:
        return False
    allowed: set[ast.Name] = set()
    for node in nodes:
        match node:
            case ast.Subscript(value=value, slice=ast.Name(id=name) as offset, ctx=ast.Load()) if (
                name == index and ast.dump(value) == ast.dump(sequence)
            ):
                allowed.add(offset)
            case ast.Subscript(value=value, ctx=ast.Store() | ast.Del()) if ast.dump(value) == ast.dump(sequence):
                return False
            case ast.Call(func=ast.Attribute(value=value, attr=method)) if method in _MUTATORS and ast.dump(
                value
            ) == ast.dump(sequence):
                return False
            case _:
                pass
    return bool(allowed) and only_index_reads(nodes, index, allowed)
