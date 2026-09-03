from __future__ import annotations

import ast
from operator import itemgetter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple, TypeGuard, final, override

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


_RANGE_MAX_ARGS = 3


class _StringStateEvent(NamedTuple):
    line: int
    target: str
    is_string: bool


def _src(node: ast.expr) -> str:
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
        summary="Avoid repeatedly growing a proven string accumulator across a loop backedge.",
        rationale="Repeated immutable-string growth can copy the accumulated value on each iteration and become quadratic.",
        remediation="Collect fragments and join once, or use `io.StringIO` when incremental writes are required.",
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
                        'def render(items):\n    result = ""\n    for item in items:\n        result += str(item)\n    return result\n',
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
                        'def render(items):\n    return "".join(str(item) for item in items)\n',
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
                message=(
                    "Repeated immutable-string growth in a loop can become quadratic — collect fragments and join "
                    "once, or use `io.StringIO`."
                ),
            )
            for node in visitor.hits
        ]


class _ConcatVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self._loop_depth: int = 0
        self._loop_reassigns: list[dict[str, list[int]]] = []
        self._loop_reads: list[frozenset[str]] = []
        self._loop_reported: list[set[str]] = []
        self._while_probe_names: list[frozenset[str]] = []
        self._class_string_attrs: list[frozenset[str]] = [frozenset()]
        self._functions: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda] = []
        self.hits: list[ast.AugAssign | ast.Assign] = []

    @override
    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.ClassDef):
            self._class_string_attrs.append(_class_string_attributes(node))
            super().generic_visit(node)
            self._class_string_attrs.pop()
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            saved_depth = self._loop_depth
            saved_probes = self._while_probe_names
            saved_reads = self._loop_reads
            self._loop_depth = 0
            self._while_probe_names = []
            self._loop_reads = []
            self._functions.append(node)
            super().generic_visit(node)
            self._functions.pop()
            self._loop_depth = saved_depth
            self._while_probe_names = saved_probes
            self._loop_reads = saved_reads
            return
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            self._visit_loop(node)
            return
        if (
            self._loop_depth
            and self._is_in_loop_concat(node)
            and not self._is_loop_local_target(node)
            and not self._is_probe_target(node)
        ):
            target = _src(self._accumulation_target(node))
            if target not in self._loop_reported[-1]:
                self._loop_reported[-1].add(target)
                self.hits.append(node)
        super().generic_visit(node)

    def _visit_loop(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        for expression in _loop_header_expressions(node):
            self.visit(expression)
        bounded = _loop_runs_at_most_once(node)
        if not bounded:
            self._loop_depth += 1
            self._loop_reassigns.append(_loop_local_reassignments(node))
            self._loop_reads.append(_loop_read_names(node))
            self._loop_reported.append(set())
            if isinstance(node, ast.While):
                self._while_probe_names.append(frozenset(_test_names(node.test)))
        for statement in node.body:
            self.visit(statement)
        if not bounded:
            if isinstance(node, ast.While):
                self._while_probe_names.pop()
            self._loop_reads.pop()
            self._loop_reassigns.pop()
            self._loop_reported.pop()
            self._loop_depth -= 1
        for statement in node.orelse:
            self.visit(statement)

    def _is_probe_target(self, node: ast.AugAssign | ast.Assign) -> bool:
        target_src = _src(self._accumulation_target(node))
        if any(target_src in names for names in self._while_probe_names):
            return True
        # Only the INNERMOST loop's reads consume the growth per iteration; a
        # read in an outer loop body sees only the finished inner accumulation.
        return bool(self._loop_reads) and target_src in self._loop_reads[-1]

    def _is_loop_local_target(self, node: ast.AugAssign | ast.Assign) -> bool:
        target = self._accumulation_target(node)
        rebinds = self._loop_reassigns[-1].get(_src(target), ())
        return bool(rebinds)

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
        if isinstance(value, ast.JoinedStr):
            return any(
                isinstance(part, ast.FormattedValue) and _src(part.value) == _src(target) for part in value.values
            ) and self._is_string_growth(target, value)
        if not isinstance(value, ast.BinOp) or not isinstance(value.op, ast.Add):
            return False
        if not _add_tree_contains_target(target, value):
            return False
        return self._is_string_growth(target, value)

    def _is_string_growth(self, target: ast.expr, _rhs: ast.expr) -> bool:
        if isinstance(target, ast.Subscript):
            return False
        if _is_definitely_non_string(_rhs):
            return False
        target_name = _src(target)
        if target_name in self._class_string_attrs[-1]:
            return True
        return bool(self._functions) and _target_is_string_before(self._functions[-1], target_name, target.lineno)


def _is_definitely_non_string(value: ast.expr) -> bool:
    if isinstance(value, ast.Constant):
        return not isinstance(value.value, str)
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in {"bool", "float", "int", "len"}
    )


def _loop_header_expressions(node: ast.For | ast.AsyncFor | ast.While) -> tuple[ast.expr, ...]:
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return (node.target, node.iter)
    return (node.test,)


def _loop_runs_at_most_once(node: ast.For | ast.AsyncFor | ast.While) -> bool:
    if isinstance(node, (ast.For, ast.AsyncFor)):
        if isinstance(node.iter, (ast.List, ast.Tuple, ast.Set)):
            return len(node.iter.elts) <= 1
        if isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range":
            return _range_cardinality_at_most_one(node.iter)
    return (
        bool(node.body)
        and isinstance(node.body[-1], ast.Break)
        and not any(isinstance(inner, ast.Continue) for statement in node.body[:-1] for inner in walk(statement))
    )


def _range_cardinality_at_most_one(call: ast.Call) -> bool:
    if call.keywords or not 1 <= len(call.args) <= _RANGE_MAX_ARGS:
        return False
    values = [
        argument.value
        for argument in call.args
        if isinstance(argument, ast.Constant) and isinstance(argument.value, int)
    ]
    if len(values) != len(call.args):
        return False
    return len(range(*values)) <= 1


def _target_is_string_before(
    func: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    target_name: str,
    line: int,
) -> bool:
    if isinstance(func, ast.Lambda):
        return False
    state = _parameter_string_state(func, target_name)
    for event_line, event_name, event_state in sorted(_assignment_states(func), key=itemgetter(0)):
        if event_line >= line:
            break
        if event_name == target_name:
            state = event_state
    return state


def _parameter_string_state(func: ast.FunctionDef | ast.AsyncFunctionDef, target_name: str) -> bool:
    arguments = (*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs)
    return any(argument.arg == target_name and _annotation_is_str(argument.annotation) for argument in arguments)


def _assignment_states(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[_StringStateEvent]:
    events: list[_StringStateEvent] = []
    for statement in func.body:
        _collect_assignment_states(statement, events)
    return events


def _collect_assignment_states(node: ast.AST, events: list[_StringStateEvent]) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
        return
    match node:
        case ast.Assign(targets=targets, value=value):
            for target in targets:
                events.extend(
                    _StringStateEvent(bound.lineno, _src(bound), _looks_like_string(value))
                    for bound in _iter_binding_targets(target)
                    if not _is_accumulation_assign(bound, value)
                )
        case ast.AnnAssign(target=target, annotation=annotation, value=value):
            if isinstance(target, (ast.Name, ast.Attribute)) and value is not None:
                events.append(_StringStateEvent(target.lineno, _src(target), _annotation_is_str(annotation)))
        case ast.NamedExpr(target=target, value=value):
            events.append(_StringStateEvent(target.lineno, _src(target), _looks_like_string(value)))
        case _:
            pass
    for child in children(node):
        _collect_assignment_states(child, events)


def _class_string_attributes(node: ast.ClassDef) -> frozenset[str]:
    states: dict[str, list[bool]] = {}
    for statement in node.body:
        _collect_class_attr_states(statement, states)
    return frozenset(name for name, evidence in states.items() if evidence and all(evidence))


def _collect_class_attr_states(node: ast.AST, states: dict[str, list[bool]]) -> None:
    if isinstance(node, ast.ClassDef):
        return
    match node:
        case ast.Assign(targets=targets, value=value):
            for target in targets:
                if isinstance(target, ast.Attribute) and _src(target).startswith("self."):
                    states.setdefault(_src(target), []).append(_looks_like_string(value))
        case ast.AnnAssign(target=ast.Attribute() as target, annotation=annotation):
            if _src(target).startswith("self."):
                states.setdefault(_src(target), []).append(_annotation_is_str(annotation))
        case _:
            pass
    for child in children(node):
        _collect_class_attr_states(child, states)


def _test_names(test: ast.expr) -> set[str]:
    return {_src(n) for n in walk(test) if isinstance(n, (ast.Name, ast.Attribute))}


def _loop_read_names(loop: ast.For | ast.AsyncFor | ast.While) -> frozenset[str]:
    reads: set[str] = set()
    stack: list[ast.AST] = list(loop.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(node.value, ast.JoinedStr) and any(
                isinstance(part, ast.FormattedValue) and _src(part.value) == _src(target) for part in node.value.values
            ):
                stack.extend(
                    part.value
                    for part in node.value.values
                    if isinstance(part, ast.FormattedValue) and _src(part.value) != _src(target)
                )
                continue
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
    reassigns: dict[str, list[int]] = {}
    for stmt in loop.body:
        match stmt:
            case ast.Assign(targets=targets, value=value):
                for target in targets:
                    for bound in _iter_binding_targets(target):
                        if not _is_accumulation_assign(bound, value):
                            reassigns.setdefault(_src(bound), []).append(bound.lineno)
            case ast.AnnAssign(target=target, value=value) if value is not None:
                if not _is_accumulation_assign(target, value):
                    reassigns.setdefault(_src(target), []).append(target.lineno)
            case _:
                pass
    return reassigns


def _iter_binding_targets(target: ast.expr) -> Iterator[ast.Name | ast.Attribute]:
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
    if isinstance(value, ast.JoinedStr):
        return any(isinstance(part, ast.FormattedValue) and _src(part.value) == _src(target) for part in value.values)
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
        return _add_tree_contains_target(target, value)
    return False


def _add_tree_contains_target(target: ast.expr, value: ast.expr) -> bool:
    target_src = _src(target)
    return any(_src(node) == target_src for node in walk(value) if isinstance(node, (ast.Name, ast.Attribute)))


def _other_add_operand(target: ast.expr, binop: ast.BinOp) -> ast.expr | None:
    target_src = _src(target)
    if _src(binop.left) == target_src:
        return binop.right
    if _src(binop.right) == target_src:
        return binop.left
    return None


def _annotation_is_str(annotation: ast.expr | None) -> bool:
    if isinstance(annotation, ast.Name):
        return annotation.id == "str"
    if isinstance(annotation, ast.Attribute):
        return isinstance(annotation.value, ast.Name) and annotation.value.id == "builtins" and annotation.attr == "str"
    if not isinstance(annotation, ast.Subscript):
        return False
    wrapper = annotation.value
    name = wrapper.id if isinstance(wrapper, ast.Name) else wrapper.attr if isinstance(wrapper, ast.Attribute) else ""
    if name not in {"Annotated", "Final"}:
        return False
    first = annotation.slice.elts[0] if isinstance(annotation.slice, ast.Tuple) else annotation.slice
    return _annotation_is_str(first)


def _looks_like_string(node: ast.AST) -> bool:
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
