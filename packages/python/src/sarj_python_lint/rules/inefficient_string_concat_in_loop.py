"""SARJ002: detect O(n²) single-accumulator string growth inside loops.

Growing a string with `s += <str>` or `s = s + <str>` inside a loop is O(n²)
in CPython because strings are immutable — each step allocates a new string and
copies the previous one. Append to a list and `"".join(parts)` at the end for
O(n).

The rule fires only on genuine single-string accumulation. It deliberately does
NOT treat a `str()/repr()/format()` coercion, a `.join()` / `.format()` /
`.strftime()` call, or an `os.path.join(...)`-style call as accumulation — those
are either the prescribed remedy or a bounded per-iteration transform, not the
O(n²) defect. Per-slot writes (`parts[i] = ...`) and idempotent rebinding
(`x = f(x)`) are likewise excluded.

A target that is freshly (re)bound earlier in the same loop body — `desc = ...`
then `desc += suffix`, or a tuple unpack `obj, path = q.popleft()` then
`path += ...` — is loop-local: it starts empty each iteration, so the growth is
bounded, not cross-iteration accumulation. Only a target initialised BEFORE the
loop is a true O(n²) accumulator, so a preceding non-accumulating rebind of the
target inside the loop suppresses the diagnostic.

A target whose intermediate values are CONSUMED per iteration is a probe, not
an accumulator — `"".join` at the end cannot replace it. Two consumption
shapes are exempt (both minimized from pydantic's unique-name generation):

* the enclosing `while` test reads the target
  (`while name in taken: name += "_"`), or
* the loop body reads the target outside its own accumulation statement
  (`globals.setdefault(reference_name, model)` then `reference_name += "_"`).

A pure accumulator is only ever written inside the loop, so it keeps firing.

References:
- https://docs.python.org/3/library/stdtypes.html#str.join
- https://wiki.python.org/moin/PythonSpeed/PerformanceTips

* **generated files** (`_paths.is_generated_source`). Their layout is the
  generator's, and re-running the generator discards any edit, so a finding
  there can never be acted on in place. Measured on the 69 `DO NOT EDIT`
  files git-tracked across bulbul and noura-be — Speakeasy's
  `python/sdk/src/sarj_platform_sdk/` accounts for all of them.

"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, TypeGuard, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class InefficientStringConcatInLoop(Rule):
    """O(n²) string concatenation in a loop."""

    id: str = "inefficient-string-concat-in-loop"
    code: str = "SARJ002"
    description: str = "`s += '...'` / `s = s + '...'` in a loop is O(n²); append to a list and join."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated_source(source):
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
        """Report whether the concat target's intermediate values are consumed.

        A target read by an enclosing while test, or read inside a loop body
        outside its own accumulation, is a probe (unique-name generation):
        every intermediate value matters, so `join` cannot replace the growth.

        Returns:
            True when the target is consumed per iteration rather than only grown.

        """
        target_src = ast.unparse(self._accumulation_target(node))
        if any(target_src in names for names in self._while_probe_names):
            return True
        # Only the INNERMOST loop's reads consume the growth per iteration; a
        # read in an outer loop body sees only the finished inner accumulation.
        return bool(self._loop_reads) and target_src in self._loop_reads[-1]

    def _is_loop_local_target(self, node: ast.AugAssign | ast.Assign) -> bool:
        """Report whether the concat target is freshly rebound earlier this iteration.

        A target rebound (not self-accumulated) before the concat inside the same
        innermost loop body starts empty each pass, so its growth is bounded.

        Returns:
            True when the target is loop-local rather than a cross-iteration accumulator.

        """
        target = self._accumulation_target(node)
        rebinds = self._loop_reassigns[-1].get(ast.unparse(target), ())
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
        """Report whether `s = s + <str>` rebinds the target to itself-plus-more.

        Returns:
            True when the assignment is a BinOp(Add) accumulation onto the target.

        """
        if not isinstance(value, ast.BinOp) or not isinstance(value.op, ast.Add):
            return False
        other = _other_add_operand(target, value)
        if other is None:
            return False
        return self._is_string_growth(target, other)

    def _is_string_growth(self, target: ast.expr, rhs: ast.expr) -> bool:
        """Report whether appending `rhs` to `target` is single-string accumulation.

        Returns:
            True when the append grows a string-typed target.

        """
        if isinstance(target, ast.Subscript):
            return False
        if _looks_like_string(rhs):
            return True
        if isinstance(rhs, ast.Name) and isinstance(target, ast.Name):
            return target.id in self._string_vars[-1]
        return False


def _test_names(test: ast.expr) -> set[str]:
    """Collect the source text of every Name/Attribute read in a while test.

    Returns:
        The unparsed reads appearing in the test expression.

    """
    return {ast.unparse(n) for n in ast.walk(test) if isinstance(n, (ast.Name, ast.Attribute))}


def _loop_read_names(loop: ast.For | ast.AsyncFor | ast.While) -> frozenset[str]:
    """Collect names READ in the loop body outside their own accumulation.

    An `s += x` stores (no Load of `s`); an `s = s + x` self-read is excluded.
    Any other Load — a call argument, a subscript key, a comparison — consumes
    the intermediate value, which marks the target as a probe. Nested
    function/lambda bodies are excluded (they run in their own scope).

    Returns:
        The unparsed Name/Attribute reads in the loop's own body.

    """
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
        stack.extend(ast.iter_child_nodes(node))
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
            reads.add(ast.unparse(node))
    return frozenset(reads)


def _loop_local_reassignments(loop: ast.For | ast.AsyncFor | ast.While) -> dict[str, list[int]]:
    """Map each target rebound inside this loop's own body to the lines that rebind it.

    Only rebinds that are NOT self-accumulation (`s = s + x`) count — those are the
    defect itself, not a fresh reset. Nested loops / functions / classes are their
    own scope and are excluded.

    Returns:
        Target source string → line numbers where it is freshly (re)bound.

    """
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
                    reassigns.setdefault(ast.unparse(bound), []).append(bound.lineno)
    elif (
        isinstance(node, ast.AnnAssign)
        and node.value is not None
        and not _is_accumulation_assign(node.target, node.value)
    ):
        reassigns.setdefault(ast.unparse(node.target), []).append(node.target.lineno)
    for child in ast.iter_child_nodes(node):
        _collect_reassignments(child, reassigns)


def _iter_binding_targets(target: ast.expr) -> Iterator[ast.Name | ast.Attribute]:
    """Yield the Name / Attribute leaves a binding target rebinds.

    Subscript leaves (`acc[i] = ...`) are per-slot writes, not a rebind of the
    accumulator itself, so they are skipped.

    Yields:
        Each Name / Attribute node the target binds.

    """
    if isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _iter_binding_targets(elt)
    elif isinstance(target, ast.Starred):
        yield from _iter_binding_targets(target.value)
    elif isinstance(target, (ast.Name, ast.Attribute)):
        yield target


def _is_accumulation_assign(target: ast.expr, value: ast.expr) -> bool:
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
        return _other_add_operand(target, value) is not None
    return False


def _other_add_operand(target: ast.expr, binop: ast.BinOp) -> ast.expr | None:
    """Return the non-target operand of `target + x` / `x + target`.

    Returns:
        The other operand, or None if neither side matches the target.

    """
    target_src = ast.unparse(target)
    if ast.unparse(binop.left) == target_src:
        return binop.right
    if ast.unparse(binop.right) == target_src:
        return binop.left
    return None


def _string_typed_locals(func: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> frozenset[str]:
    """Collect names assigned a string-literal-ish value in this function's own body.

    Used as the string-typed signal for bare-`Name` accumulation (`buf += line`):
    a numeric accumulator (`total = 0`) is absent, so `total += x` stays clean.

    Returns:
        The frozenset of locally string-typed names.

    """
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
    for child in ast.iter_child_nodes(node):
        _collect_string_targets(child, names)


def _looks_like_string(node: ast.AST) -> bool:
    """Report whether this expression is obviously a string at runtime.

    Deliberately conservative: a bare call (`str(x)`, `",".join(...)`,
    `os.path.join(...)`) is NOT treated as a string — those shapes also appear in
    benign one-shot reassignment and are not the accumulation defect.

    Returns:
        True when the expression is heuristically string-typed.

    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.JoinedStr):  # f-string
        return True
    if isinstance(node, ast.NamedExpr):  # walrus `(y := <str>)`
        return _looks_like_string(node.value)
    if isinstance(node, ast.IfExp):  # ternary — string only if both branches are
        return _looks_like_string(node.body) and _looks_like_string(node.orelse)
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            return _looks_like_string(node.left) or _looks_like_string(node.right)
        if isinstance(node.op, ast.Mod):  # `"row %s" % x` — left operand decides
            return _looks_like_string(node.left)
    return False
