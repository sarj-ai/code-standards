from __future__ import annotations

import ast
from dataclasses import dataclass
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
from sarj_python_lint.rules._sequence_iteration import only_index_reads, sequence_root, stable_iteration_nodes


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


@dataclass(frozen=True, slots=True)
class _ChunkSlice:
    width: ast.expr
    indices: frozenset[ast.Name]


@final
class PreferItertoolsBatched(Rule):
    id = "prefer-itertools-batched"
    code = "SARJ605"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Iterate fixed-size chunks with itertools.batched instead of restating the batch size in a slice.",
        rationale=(
            "A range step and a slice width express the same batch size twice and can drift independently. "
            "itertools.batched states the width once and includes a final partial batch."
        ),
        remediation=(
            "Import batched from itertools and iterate batched(sequence, size, strict=False). "
            "Review consumers because each batch is a tuple. Omit strict=False when supporting Python 3.12."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only synchronous range(0, len(sequence), step) loops, optionally wrapped in enumerate, and single-generator comprehensions without filters are checked. The sequence must be a name or dotted attribute chain.",
            "Every offset read must belong to a matching slice bound. Rebindings, index-capturing nested scopes, shadowed builtins, stub files, generated sources and declared targets below Python 3.12 are excluded. While loops are not reported.",
            "Operand types are not inferred. batched yields tuples, so callers must review slice-type-dependent operations; there is no automatic fix. Python 3.12 advice omits the strict keyword introduced in Python 3.13.",
        ),
        examples=(
            RuleExample(
                example_id="repeated-batch-size",
                title="The range and slice repeat the batch size",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "batches.py",
                        "def run(files, size):\n    for offset in range(0, len(files), size):\n        consume(files[offset : offset + size])\n",
                    ),
                ),
                focus_path=PurePosixPath("batches.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="one-batch-size",
                title="batched owns the batch size",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "batches.py",
                        "from itertools import batched\ndef run(files, size):\n    for batch in batched(files, size, strict=False):\n        consume(batch)\n",
                    ),
                ),
                focus_path=PurePosixPath("batches.py"),
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
        findings: list[Diagnostic] = []
        target = context.session.python_target
        for loop in context.nodes(ast.For, ast.ListComp, ast.SetComp, ast.GeneratorExp):
            if _shadowed_builtins(context, loop):
                continue
            parts = _parts(loop)
            if parts is None:
                continue
            loop_target, iterator, body = parts
            candidate = _range(iterator, loop_target)
            if candidate is None:
                continue
            sequence, step, index = candidate
            width = _slice_width(sequence, index, body)
            if width is None or context.suppressions.is_suppressed(loop.lineno, self.code):
                continue
            if target.has_declared_support_before(context.path, (3, 12)):
                continue
            strict = "" if target.has_declared_support_before(context.path, (3, 13)) else ", strict=False"
            subject = ast.unparse(sequence)
            drift = (
                f" and the slice width `{ast.unparse(width)}` differs from the step `{ast.unparse(step)}`"
                if ast.dump(width) != ast.dump(step)
                else ""
            )
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=loop.lineno,
                    col=loop.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=f"Manual chunking of `{subject}` states the batch size twice{drift}; iterate `itertools.batched({subject}, {ast.unparse(step)}{strict})`.",
                )
            )
        return sorted(findings, key=lambda item: (item.line, item.col))


def _shadowed_builtins(context: PythonFileContext, loop: ast.AST) -> bool:
    scope = context.binding_inventory.scope(loop)
    return any(
        name in names
        for owner, names in context.binding_inventory.bindings.items()
        if not isinstance(owner, ast.ClassDef) or owner is scope
        for name in ("range", "len", "enumerate")
    )


def _parts(node: ast.AST) -> tuple[ast.expr, ast.expr, tuple[ast.AST, ...]] | None:
    match node:
        case ast.For(target=target, iter=iterator, body=body, orelse=orelse):
            return target, iterator, (*body, *orelse)
        case (
            ast.ListComp(elt=element, generators=[generator])
            | ast.SetComp(elt=element, generators=[generator])
            | ast.GeneratorExp(elt=element, generators=[generator])
        ) if not generator.is_async and not generator.ifs:
            return generator.target, generator.iter, (element,)
        case _:
            return None


def _range(iterator: ast.expr, target: ast.expr) -> tuple[ast.expr, ast.expr, str] | None:
    match iterator, target:
        case ast.Call(func=ast.Name(id="enumerate"), args=[inner, *_]), ast.Tuple(elts=[_, ast.Name() as offset]):
            return _range(inner, offset)
        case ast.Call(
            func=ast.Name(id="range"),
            args=[ast.Constant(value=0), ast.Call(func=ast.Name(id="len"), args=[sequence], keywords=[]), step],
            keywords=[],
        ), ast.Name(id=index):
            if sequence_root(sequence) is not None and not (
                (isinstance(step, ast.Constant) and isinstance(step.value, int) and step.value <= 0)
                or (isinstance(step, ast.UnaryOp) and isinstance(step.op, ast.USub))
            ):
                return sequence, step, index
        case _:
            pass
    return None


def _slice_width(sequence: ast.expr, index: str, body: tuple[ast.AST, ...]) -> ast.expr | None:
    nodes = stable_iteration_nodes(body, sequence, index)
    if nodes is None:
        return None
    slices = [chunk for node in nodes if (chunk := _chunk_slice(node, sequence, index)) is not None]
    allowed = frozenset(offset for chunk in slices for offset in chunk.indices)
    if not slices or not only_index_reads(nodes, index, allowed):
        return None
    return slices[0].width


def _chunk_slice(node: ast.AST, sequence: ast.expr, index: str) -> _ChunkSlice | None:
    match node:
        case ast.Subscript(
            value=value,
            slice=ast.Slice(lower=ast.Name(id=name) as lower, upper=ast.BinOp(op=ast.Add()) as upper, step=None),
            ctx=ast.Load(),
        ) if name == index and ast.dump(value) == ast.dump(sequence):
            match upper.left, upper.right:
                case ast.Name(id=bound_name) as bound, width if bound_name == index:
                    return _ChunkSlice(width, frozenset((lower, bound)))
                case width, ast.Name(id=bound_name) as bound if bound_name == index:
                    return _ChunkSlice(width, frozenset((lower, bound)))
                case _:
                    pass
        case _:
            pass
    return None
