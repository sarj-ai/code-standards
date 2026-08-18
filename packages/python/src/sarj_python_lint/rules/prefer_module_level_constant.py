from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, nodes
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


type _Function = ast.FunctionDef | ast.AsyncFunctionDef

#: A display smaller than this reads better next to its use than as a
#: module-level constant, so this is the floor at which hoisting pays for itself.
_MIN_ELEMENTS = 3

#: How deep a nested display may go before we stop trying to prove it constant.
_MAX_LITERAL_DEPTH = 4

#: `re.compile(pattern[, flags])` — anything longer is not the shape we model.
_COMPILE_MAX_ARGS = 2

_REGEX_KIND = "regex"
_FROZENSET_KIND = "frozenset"

_RE_COMPILE = "re.compile"
_FROZENSET = "frozenset"
_RE_FLAG_PREFIX = "re."

#: Callables that read their argument and return a fresh value without retaining
#: or mutating the original, so passing the binding to one is still a read.
_SAFE_CALLEES = frozenset(
    {
        "all",
        "any",
        "dict",
        "enumerate",
        "frozenset",
        "iter",
        "json.dumps",
        "len",
        "list",
        "max",
        "min",
        "reversed",
        "set",
        "sorted",
        "sum",
        "tuple",
    }
)

#: Collection methods known not to mutate the receiver.
_SAFE_METHODS = frozenset({"copy", "count", "get", "index", "items", "keys", "values"})

#: The `re.Pattern` API.
_SAFE_REGEX_METHODS = frozenset(
    {
        "findall",
        "finditer",
        "fullmatch",
        "match",
        "search",
        "split",
        "sub",
        "subn",
    }
)

_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

#: Nodes that open a scope of their own.
_INNER_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class PreferModuleLevelConstant(Rule):
    id: str = "prefer-module-level-constant"
    code: str = "SARJ039"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Literal-only collections and compiled regular expressions built inside a function should be module-level constants.",
        rationale="Rebuilding immutable data or a constant regex on every call wastes work and obscures its static nature.",
        remediation="Define the value once at module scope and reference that constant from the function.",
        category=RuleCategory.PERFORMANCE,
        limitations=(
            "Test and generated files are excluded.",
            "Only proven literal-only collections of at least three elements and constant `re.compile` calls are reported.",
        ),
        examples=(
            RuleExample(
                example_id="list-built-per-call",
                title="Static list rebuilt in a function",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py", 'def handle(value):\n    allowed = ["a", "b", "c"]\n    return value in allowed\n'
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="module-level-list",
                title="Static list defined once",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py", 'ALLOWED = ["a", "b", "c"]\n\ndef handle(value):\n    return value in ALLOWED\n'
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
        if is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        for func in _iter_functions(tree):
            for stmt, name, candidate in _hoistable_bindings(func):
                diags.append(
                    Diagnostic(
                        path=path,
                        line=stmt.lineno,
                        col=stmt.col_offset + 1,
                        code=self.code,
                        message=_message(name, candidate),
                    )
                )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


@dataclass(frozen=True, slots=True)
class _Candidate:
    kind: str
    size: int


@dataclass(frozen=True, slots=True)
class _Scope:
    nodes: list[ast.AST]
    parents: dict[int, ast.AST]
    nested: set[int]


@dataclass(frozen=True, slots=True)
class _BindingCandidate:
    target: ast.Name
    value: ast.expr


def _iter_functions(tree: ast.Module) -> Iterator[_Function]:
    yield from nodes(tree, *_FUNCTION_NODES)


def _hoistable_bindings(func: _Function) -> Iterator[tuple[ast.stmt, str, _Candidate]]:
    scope = _scope_of(func)
    if _reads_frame_locals(scope):
        return
    for node in scope.nodes:
        if id(node) in scope.nested or not isinstance(node, ast.stmt):
            continue
        binding = _candidate_binding(node)
        if binding is None:
            continue
        candidate = _classify(binding.value)
        if candidate is None or not _is_large_enough(candidate):
            continue
        if _is_safely_hoistable(scope, func, binding.target, _safe_methods_for(candidate)):
            yield node, binding.target.id, candidate


def _scope_of(func: _Function) -> _Scope:
    nodes: list[ast.AST] = []
    parents: dict[int, ast.AST] = {}
    nested: set[int] = set()
    stack: list[tuple[ast.AST, ast.AST, bool]] = [(child, func, False) for child in func.body]
    while stack:
        node, parent, is_nested = stack.pop()
        nodes.append(node)
        parents[id(node)] = parent
        if is_nested:
            nested.add(id(node))
        child_nested = is_nested or isinstance(node, _INNER_SCOPE_NODES)
        stack.extend((child, node, child_nested) for child in children(node))
    return _Scope(nodes=nodes, parents=parents, nested=nested)


def _reads_frame_locals(scope: _Scope) -> bool:
    for node in scope.nodes:
        match node:
            case ast.Call(func=ast.Name(id="locals" | "vars"), args=[], keywords=[]):
                return True
            case _:
                continue
    return False


def _candidate_binding(node: ast.stmt) -> _BindingCandidate | None:
    match node:
        case (
            ast.Assign(targets=[ast.Name() as target], value=value)
            | ast.AnnAssign(target=ast.Name() as target, value=ast.expr() as value)
        ):
            return _BindingCandidate(target, value)
        case _:
            return None


def _classify(value: ast.expr) -> _Candidate | None:
    match value:
        case ast.List(elts=elts):
            return _display_candidate("list", value, len(elts))
        case ast.Set(elts=elts):
            return _display_candidate("set", value, len(elts))
        case ast.Tuple() if _is_immutable_literal(value):
            return None
        case ast.Tuple(elts=elts):
            return _display_candidate("tuple", value, len(elts))
        case ast.Dict(keys=keys):
            return _display_candidate("dict", value, len(keys))
        case ast.Call():
            return _call_candidate(value)
        case _:
            return None


def _is_large_enough(candidate: _Candidate) -> bool:
    return candidate.kind == _REGEX_KIND or candidate.size >= _MIN_ELEMENTS


def _display_candidate(kind: str, node: ast.expr, size: int) -> _Candidate | None:
    return _Candidate(kind=kind, size=size) if _is_constant_only(node, 0) else None


def _call_candidate(call: ast.Call) -> _Candidate | None:
    if call.keywords:
        return None
    callee = _dotted_name(call.func)
    if callee == _FROZENSET:
        return _frozenset_candidate(call)
    if callee == _RE_COMPILE and _is_constant_pattern(call):
        return _Candidate(kind=_REGEX_KIND, size=1)
    return None


def _frozenset_candidate(call: ast.Call) -> _Candidate | None:
    match call.args:
        case [ast.List(elts=elts) | ast.Set(elts=elts) | ast.Tuple(elts=elts) as inner] if _is_constant_only(inner, 0):
            return _Candidate(kind=_FROZENSET_KIND, size=len(elts))
        case _:
            return None


def _is_constant_pattern(call: ast.Call) -> bool:
    if not call.args or len(call.args) > _COMPILE_MAX_ARGS:
        return False
    match call.args[0]:
        case ast.Constant(value=str() | bytes()):
            pass
        case _:
            return False
    return len(call.args) < _COMPILE_MAX_ARGS or _is_constant_flags(call.args[1])


def _is_constant_flags(node: ast.expr) -> bool:
    match node:
        case ast.Constant(value=int()):
            return True
        case ast.Attribute():
            dotted = _dotted_name(node)
            return dotted is not None and dotted.startswith(_RE_FLAG_PREFIX)
        case ast.BinOp(op=ast.BitOr(), left=left, right=right):
            return _is_constant_flags(left) and _is_constant_flags(right)
        case _:
            return False


def _is_constant_only(node: ast.expr, depth: int) -> bool:
    if depth > _MAX_LITERAL_DEPTH:
        return False
    match node:
        case (
            ast.Constant()
            | ast.UnaryOp(op=ast.USub() | ast.UAdd(), operand=ast.Constant(value=int() | float() | complex()))
        ):
            return True
        case ast.List() | ast.Set() | ast.Tuple():
            return all(_is_constant_only(element, depth + 1) for element in node.elts)
        case ast.Dict(keys=keys, values=values):
            entries = [*keys, *values]
            return all(entry is not None and _is_constant_only(entry, depth + 1) for entry in entries)
        case _:
            return False


def _is_immutable_literal(node: ast.expr) -> bool:
    match node:
        case (
            ast.Constant()
            | ast.UnaryOp(op=ast.USub() | ast.UAdd(), operand=ast.Constant(value=int() | float() | complex()))
        ):
            return True
        case ast.Tuple(elts=elts):
            return all(_is_immutable_literal(element) for element in elts)
        case _:
            return False


def _safe_methods_for(candidate: _Candidate) -> frozenset[str]:
    return _SAFE_REGEX_METHODS if candidate.kind == _REGEX_KIND else _SAFE_METHODS


def _is_safely_hoistable(
    scope: _Scope,
    func: _Function,
    target: ast.Name,
    safe_methods: frozenset[str],
) -> bool:
    name = target.id
    if name in _parameter_names(func):
        return False
    reads = 0
    for node in scope.nodes:
        if id(node) in scope.nested:
            if _mentions_name(node, name):
                return False
            continue
        if _rebinds_name(node, name):
            return False
        if not (isinstance(node, ast.Name) and node.id == name):
            continue
        if not isinstance(node.ctx, ast.Load):
            if node is not target:
                return False
        elif _is_safe_read(node, scope.parents, safe_methods):
            reads += 1
        else:
            return False
    # A binding the function never reads is either dead or read reflectively
    # (`locals()`, a debugger, a frame-inspecting logger); either way there is no
    # use site the hoist would serve, and moving it changes what `locals()` holds.
    return reads > 0


def _parameter_names(func: _Function) -> frozenset[str]:
    args = func.args
    params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    params.extend(arg for arg in (args.vararg, args.kwarg) if arg is not None)
    return frozenset(param.arg for param in params)


def _mentions_name(node: ast.AST, name: str) -> bool:
    match node:
        case ast.Name(id=ident) | ast.arg(arg=ident):
            return ident == name
        case ast.Global() | ast.Nonlocal():
            return name in node.names
        case _:
            return False


def _rebinds_name(node: ast.AST, name: str) -> bool:
    match node:
        case ast.Global() | ast.Nonlocal():
            return name in node.names
        case ast.ExceptHandler() | ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            return node.name == name
        case ast.alias(asname=None, name=module):
            return module.split(".")[0] == name
        case ast.alias(asname=str()) | ast.MatchAs(name=str()) | ast.MatchStar(name=str()):
            return node.name == name
        case ast.MatchMapping(rest=rest):
            return rest == name
        case _:
            return False


def _is_safe_read(node: ast.Name, parents: dict[int, ast.AST], safe_methods: frozenset[str]) -> bool:
    parent = parents.get(id(node))
    match parent:
        case ast.Attribute():
            return _is_safe_method_call(parent, parents, safe_methods)
        case ast.Subscript(value=value, ctx=ctx):
            # `x[k]` reads; `x[k] = v` / `del x[k]` mutate.
            # A binding used as `frame[x]` is not representation-neutral:
            # pandas and other selector APIs distinguish a list from a tuple.
            return value is node and isinstance(ctx, ast.Load)
        case ast.Call(args=args, func=callee):
            return any(arg is node for arg in args) and _is_safe_callee(callee)
        case ast.keyword(arg=str(), value=value) if value is node:
            grandparent = parents.get(id(parent))
            # `dict(label=x)` retains `x` as a nested value; unlike
            # `dict(x)`, it does not copy the candidate collection itself.
            return (
                isinstance(grandparent, ast.Call)
                and _is_safe_callee(grandparent.func)
                and _dotted_name(grandparent.func) != "dict"
            )
        case ast.Compare():
            return True
        case ast.For() | ast.AsyncFor() | ast.comprehension():
            return parent.iter is node
        case ast.FormattedValue():
            return True
        case _:
            return False


def _is_safe_method_call(
    attribute: ast.Attribute,
    parents: dict[int, ast.AST],
    safe_methods: frozenset[str],
) -> bool:
    if not isinstance(attribute.ctx, ast.Load) or attribute.attr not in safe_methods:
        return False
    parent = parents.get(id(attribute))
    return isinstance(parent, ast.Call) and parent.func is attribute


def _is_safe_callee(func: ast.expr) -> bool:
    return _dotted_name(func) in _SAFE_CALLEES


def _dotted_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=ident):
            return ident
        case ast.Attribute(value=value, attr=attr):
            base = _dotted_name(value)
            return None if base is None else f"{base}.{attr}"
        case _:
            return None


def _message(name: str, candidate: _Candidate) -> str:
    if candidate.kind == _REGEX_KIND:
        return f"`{name}` repeats a regex-cache lookup on every call — hoist it to module scope."
    return (
        f"`{name}` is a constant-only {candidate.kind} rebuilt on every call — hoist it "
        "to module scope in immutable form (tuple, frozenset, or an immutable mapping) "
        "so it is built once without exposing mutable shared state."
    )
