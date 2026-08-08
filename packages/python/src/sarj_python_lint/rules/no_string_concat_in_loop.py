"""SARJ002 — O(n²) single-accumulator string growth inside loops.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_string_concat_in_loop.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, TypeGuard, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, walk
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _src(node: ast.expr) -> str:
    """`ast.unparse` for the shapes this rule compares, without `ast.unparse`'s cost."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, (ast.Name, ast.Attribute)):
        return f"{_src(node.value)}.{node.attr}"
    return ast.unparse(node)


@final
class NoStringConcatInLoop(Rule):
    id: str = "no-string-concat-in-loop"
    code: str = "SARJ002"
    documentation = RuleDocumentation(
        summary="Do not grow one string with repeated concatenation inside a loop.",
        rationale="Repeated string growth copies the accumulated value on each iteration and can take quadratic time.",
        remediation="Append each fragment to a list and join the fragments once after the loop.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        aliases=("inefficient-string-concat-in-loop",),
        limitations=(
            "The rule requires syntax that establishes string-like growth and excludes generated files.",
            "Subscript targets, per-iteration reinitialization, and intermediate values consumed by the loop are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="string-growth-in-loop",
                title="String accumulator grown on every iteration",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/render.py",
                        'def render(items):\n    result = ""\n    for item in items:\n        result += f"{item}\\n"\n    return result\n',
                    ),
                ),
                focus_path=PurePosixPath("app/render.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="join-string-fragments",
                title="Fragments joined after the loop",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/render.py",
                        'def render(items):\n    lines = []\n    for item in items:\n        lines.append(str(item))\n    return "\\n".join(lines)\n',
                    ),
                ),
                focus_path=PurePosixPath("app/render.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
        if "+" not in source or ("for " not in source and "while " not in source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        visitor = _ConcatVisitor()
        visitor.visit(tree)
        return [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message="String concat in a loop is O(n²). Append to a list and `''.join(...)`.",
            )
            for node in visitor.hits
        ]


class _ConcatVisitor(ast.NodeVisitor):
    """Single O(n) pass flagging each in-loop string accumulation exactly once."""

    def __init__(self) -> None:
        self._loop_depth: int = 0
        self._string_vars: list[frozenset[str]] = [frozenset()]
        self._loop_reassigns: list[dict[str, list[int]]] = []
        self._loop_reads: list[frozenset[str]] = []
        self._while_probe_names: list[frozenset[str]] = []
        self.hits: list[ast.AugAssign | ast.Assign] = []

    @override
    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            saved_depth = self._loop_depth
            saved_probes = self._while_probe_names
            saved_reads = self._loop_reads
            self._loop_depth = 0
            self._while_probe_names = []
            self._loop_reads = []
            self._string_vars.append(_string_typed_locals(node))
            super().generic_visit(node)
            self._string_vars.pop()
            self._loop_depth = saved_depth
            self._while_probe_names = saved_probes
            self._loop_reads = saved_reads
            return
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            self._loop_depth += 1
            self._loop_reassigns.append(_loop_local_reassignments(node))
            self._loop_reads.append(_loop_read_names(node))
            if isinstance(node, ast.While):
                self._while_probe_names.append(frozenset(_test_names(node.test)))
            super().generic_visit(node)
            if isinstance(node, ast.While):
                self._while_probe_names.pop()
            self._loop_reads.pop()
            self._loop_reassigns.pop()
            self._loop_depth -= 1
            return
        if (
            self._loop_depth
            and self._is_in_loop_concat(node)
            and not self._is_loop_local_target(node)
            and not self._is_probe_target(node)
        ):
            self.hits.append(node)
        super().generic_visit(node)

    def _is_probe_target(self, node: ast.AugAssign | ast.Assign) -> bool:
        """Report whether the concat target's intermediate values are consumed."""
        target_src = _src(self._accumulation_target(node))
        if any(target_src in names for names in self._while_probe_names):
            return True
        # Only the INNERMOST loop's reads consume the growth per iteration; a
        # read in an outer loop body sees only the finished inner accumulation.
        return bool(self._loop_reads) and target_src in self._loop_reads[-1]

    def _is_loop_local_target(self, node: ast.AugAssign | ast.Assign) -> bool:
        """Report whether the concat target is freshly rebound earlier this iteration."""
        target = self._accumulation_target(node)
        rebinds = self._loop_reassigns[-1].get(_src(target), ())
        return any(line < node.lineno for line in rebinds)

    def _accumulation_target(self, node: ast.AugAssign | ast.Assign) -> ast.expr:
        if isinstance(node, ast.AugAssign):
            return node.target
        for target in node.targets:
            if self._is_self_add_growth(target, node.value):
                return target
        return node.targets[0]

    def _is_in_loop_concat(self, node: ast.AST) -> TypeGuard[ast.AugAssign | ast.Assign]:
        if isinstance(node, ast.AugAssign):
            return isinstance(node.op, ast.Add) and self._is_string_growth(node.target, node.value)
        if isinstance(node, ast.Assign):
            return any(self._is_self_add_growth(target, node.value) for target in node.targets)
        return False

    def _is_self_add_growth(self, target: ast.expr, value: ast.expr) -> bool:
        """Report whether `s = s + <str>` rebinds the target to itself-plus-more."""
        if not isinstance(value, ast.BinOp) or not isinstance(value.op, ast.Add):
            return False
        other = _other_add_operand(target, value)
        if other is None:
            return False
        return self._is_string_growth(target, other)

    def _is_string_growth(self, target: ast.expr, rhs: ast.expr) -> bool:
        """Report whether appending `rhs` to `target` is single-string accumulation."""
        if isinstance(target, ast.Subscript):
            return False
        if _looks_like_string(rhs):
            return True
        if isinstance(rhs, ast.Name) and isinstance(target, ast.Name):
            return target.id in self._string_vars[-1]
        return False


def _test_names(test: ast.expr) -> set[str]:
    """Collect the source text of every Name/Attribute read in a while test."""
    return {_src(n) for n in walk(test) if isinstance(n, (ast.Name, ast.Attribute))}


def _loop_read_names(loop: ast.For | ast.AsyncFor | ast.While) -> frozenset[str]:
    """Collect names READ in the loop body outside their own accumulation."""
    reads: set[str] = set()
    stack: list[ast.AST] = list(loop.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if _is_accumulation_assign(target, node.value) and isinstance(node.value, ast.BinOp):
                # Skip the self-read operand; still record reads in the other one.
                other = _other_add_operand(target, node.value)
                if other is not None:
                    stack.append(other)
                continue
        stack.extend(children(node))
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
            reads.add(_src(node))
    return frozenset(reads)


def _loop_local_reassignments(loop: ast.For | ast.AsyncFor | ast.While) -> dict[str, list[int]]:
    """Map each target rebound inside this loop's own body to the lines that rebind it."""
    reassigns: dict[str, list[int]] = {}
    for stmt in loop.body:
        _collect_reassignments(stmt, reassigns)
    return reassigns


def _collect_reassignments(node: ast.AST, reassigns: dict[str, list[int]]) -> None:
    if isinstance(
        node,
        (ast.For, ast.AsyncFor, ast.While, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
    ):
        return
    if isinstance(node, ast.Assign):
        for target in node.targets:
            for bound in _iter_binding_targets(target):
                if not _is_accumulation_assign(bound, node.value):
                    reassigns.setdefault(_src(bound), []).append(bound.lineno)
    elif (
        isinstance(node, ast.AnnAssign)
        and node.value is not None
        and not _is_accumulation_assign(node.target, node.value)
    ):
        reassigns.setdefault(_src(node.target), []).append(node.target.lineno)
    for child in children(node):
        _collect_reassignments(child, reassigns)


def _iter_binding_targets(target: ast.expr) -> Iterator[ast.Name | ast.Attribute]:
    """Yield the Name / Attribute leaves a binding target rebinds."""
    match target:
        case ast.Tuple() | ast.List():
            for elt in target.elts:
                yield from _iter_binding_targets(elt)
        case ast.Starred(value=value):
            yield from _iter_binding_targets(value)
        case ast.Name() | ast.Attribute():
            yield target
        case _:
            pass


def _is_accumulation_assign(target: ast.expr, value: ast.expr) -> bool:
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
        return _other_add_operand(target, value) is not None
    return False


def _other_add_operand(target: ast.expr, binop: ast.BinOp) -> ast.expr | None:
    """Return the non-target operand of `target + x` / `x + target`."""
    target_src = _src(target)
    if _src(binop.left) == target_src:
        return binop.right
    if _src(binop.right) == target_src:
        return binop.left
    return None


def _string_typed_locals(func: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> frozenset[str]:
    """Collect names assigned a string-literal-ish value in this function's own body."""
    if isinstance(func, ast.Lambda):
        return frozenset()
    names: set[str] = set()
    for stmt in func.body:
        _collect_string_targets(stmt, names)
    return frozenset(names)


def _collect_string_targets(node: ast.AST, names: set[str]) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
        return
    if isinstance(node, ast.Assign) and _looks_like_string(node.value):
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    if (
        isinstance(node, ast.AnnAssign)
        and node.value is not None
        and isinstance(node.target, ast.Name)
        and _looks_like_string(node.value)
    ):
        names.add(node.target.id)
    for child in children(node):
        _collect_string_targets(child, names)


def _looks_like_string(node: ast.AST) -> bool:
    """Report whether this expression is obviously a string at runtime."""
    match node:
        case ast.Constant(value=str()):
            return True
        case ast.JoinedStr():  # f-string
            return True
        case ast.NamedExpr(value=value):  # walrus `(y := <str>)`
            return _looks_like_string(value)
        case ast.IfExp(body=body, orelse=orelse):  # ternary — string only if both branches are
            return _looks_like_string(body) and _looks_like_string(orelse)
        case ast.BinOp(left=left, op=ast.Add(), right=right):
            return _looks_like_string(left) or _looks_like_string(right)
        case ast.BinOp(left=left, op=ast.Mod()):  # `"row %s" % x` — left operand decides
            return _looks_like_string(left)
        case _:
            return False
