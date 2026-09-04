from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
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
from sarj_python_lint.rules._ast_index import children, nodes
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


type _Function = ast.FunctionDef | ast.AsyncFunctionDef

#: Small displays rarely justify expanding a module's public lifetime and
#: naming surface. A display in a loop has a lower threshold because the
#: allocation repeats within one call as well as across calls.
_MIN_ELEMENTS = 8
_MIN_LOOP_ELEMENTS = 3

#: `re.compile(pattern[, flags])` — anything longer is not the shape we model.
_COMPILE_MAX_ARGS = 2

_REGEX_KIND = "regex"
_FROZENSET_KIND = "frozenset"

_RE_SOURCES = frozenset({"re"})

#: Callables that read their argument and return a fresh value without retaining
#: or mutating the original, so passing the binding to one is still a read.
_SAFE_BUILTIN_CALLEES = frozenset(
    {
        "all",
        "any",
        "dict",
        "len",
        "list",
        "max",
        "min",
        "set",
        "sorted",
        "sum",
    }
)
_SET_SAFE_BUILTIN_CALLEES = frozenset({"all", "any", "len", "max", "min", "set", "sorted", "sum"})
_RE_DEBUG_FLAG = int(re.DEBUG)

_SAFE_COLLECTION_METHODS = MappingProxyType(
    {
        "dict": frozenset({"get", "items", "keys", "values"}),
        "list": frozenset({"count", "index"}),
        "set": frozenset(),
        _FROZENSET_KIND: frozenset(),
    }
)

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
        summary="Hoist repeatedly read static values when an immutable module representation preserves behavior.",
        rationale=(
            "Rebuilding a substantial static collection repeats allocation, while calling `re.compile` with a "
            "constant pattern repeats a regex-cache lookup. In reusable code, an immutable module value makes "
            "the static lifetime explicit without exposing shared mutable state."
        ),
        remediation=(
            "Define the value once at module scope as a tuple, frozenset, immutable mapping, or compiled pattern, "
            "then reference it from the function. Preserve ordering and concrete-type behavior used by callers."
        ),
        category=RuleCategory.PERFORMANCE,
        limitations=(
            "Test, test-support, and generated files are excluded.",
            "Collections require at least eight deeply immutable elements, or three when allocated inside a loop; only representation-insensitive reads are accepted.",
            "Regex findings require a proven stdlib `re.compile` binding and exclude `re.DEBUG`; the rule cannot prove that a function is hot, so findings remain advisory.",
        ),
        examples=(
            RuleExample(
                example_id="static-membership-built-per-call",
                title="Substantial static membership table rebuilt per call",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        'def handle(value):\n    allowed = ["a", "b", "c", "d", "e", "f", "g", "h"]\n    return value in allowed\n',
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="immutable-module-membership",
                title="Immutable membership table defined once",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        'ALLOWED = ("a", "b", "c", "d", "e", "f", "g", "h")\n\ndef handle(value):\n    return value in ALLOWED\n',
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
        if _is_excluded_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        unsafe_bindings = _unsafe_bindings(tree)
        re_attribute_mutated = _has_re_attribute_mutation(tree)
        if "*" in unsafe_bindings:
            return []
        diags: list[Diagnostic] = []
        for func in _iter_functions(tree):
            for stmt, name, candidate in _hoistable_bindings(
                func,
                imports,
                unsafe_bindings,
                re_attribute_mutated=re_attribute_mutated,
            ):
                diags.append(
                    Diagnostic(
                        path=path,
                        line=stmt.lineno,
                        col=stmt.col_offset + 1,
                        code=self.code,
                        message=_message(name, candidate),
                        severity=Severity.WARNING,
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


def _hoistable_bindings(
    func: _Function,
    imports: ImportIndex,
    unsafe_bindings: frozenset[str],
    *,
    re_attribute_mutated: bool,
) -> Iterator[tuple[ast.stmt, str, _Candidate]]:
    scope = _scope_of(func)
    if _reads_frame_locals(scope):
        return
    for node in scope.nodes:
        if id(node) in scope.nested or not isinstance(node, ast.stmt):
            continue
        binding = _candidate_binding(node)
        if binding is None:
            continue
        candidate = _classify(
            binding.value,
            imports,
            unsafe_bindings,
            re_attribute_mutated=re_attribute_mutated,
        )
        if candidate is None or not _is_large_enough(candidate, node, scope.parents):
            continue
        if _is_safely_hoistable(
            scope,
            func,
            binding.target,
            candidate,
            imports=imports,
            unsafe_bindings=unsafe_bindings,
        ):
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


def _classify(
    value: ast.expr,
    imports: ImportIndex,
    unsafe_bindings: frozenset[str],
    *,
    re_attribute_mutated: bool,
) -> _Candidate | None:
    match value:
        case ast.List(elts=elts):
            return _display_candidate("list", value, len(elts))
        case ast.Set(elts=elts):
            return _display_candidate("set", value, len(elts))
        case ast.Tuple():
            return None
        case ast.Dict(keys=keys):
            return _display_candidate("dict", value, len(keys))
        case ast.Call():
            return _call_candidate(
                value,
                imports,
                unsafe_bindings,
                re_attribute_mutated=re_attribute_mutated,
            )
        case _:
            return None


def _is_large_enough(candidate: _Candidate, node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    if candidate.kind == _REGEX_KIND:
        return True
    minimum = _MIN_LOOP_ELEMENTS if _has_loop_ancestor(node, parents) else _MIN_ELEMENTS
    return candidate.size >= minimum


def _has_loop_ancestor(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    current: ast.AST | None = node
    while (current := parents.get(id(current))) is not None:
        if isinstance(current, (ast.For, ast.AsyncFor, ast.While, ast.comprehension)):
            return True
    return False


def _display_candidate(kind: str, node: ast.expr, size: int) -> _Candidate | None:
    match node:
        case ast.List(elts=elts) | ast.Set(elts=elts):
            entries: list[ast.expr | None] = [*elts]
        case ast.Dict(keys=keys, values=values):
            entries = [*keys, *values]
        case _:
            return None
    return (
        _Candidate(kind=kind, size=size)
        if all(entry is not None and _is_immutable_literal(entry) for entry in entries)
        else None
    )


def _call_candidate(
    call: ast.Call,
    imports: ImportIndex,
    unsafe_bindings: frozenset[str],
    *,
    re_attribute_mutated: bool,
) -> _Candidate | None:
    if call.keywords:
        return None
    if (
        isinstance(call.func, ast.Name)
        and call.func.id == "frozenset"
        and "frozenset" not in unsafe_bindings
        and imports.builtin_is_unshadowed("frozenset")
    ):
        return _frozenset_candidate(call)
    if (
        not re_attribute_mutated
        and _root_name(call.func) not in unsafe_bindings
        and imports.resolves(call.func, sources=_RE_SOURCES, symbol="compile")
        and _is_constant_pattern(call, imports)
    ):
        return _Candidate(kind=_REGEX_KIND, size=1)
    return None


def _frozenset_candidate(call: ast.Call) -> _Candidate | None:
    match call.args:
        case [ast.List(elts=elts) | ast.Set(elts=elts) | ast.Tuple(elts=elts)] if all(
            _is_immutable_literal(element) for element in elts
        ):
            return _Candidate(kind=_FROZENSET_KIND, size=len(elts))
        case _:
            return None


def _is_constant_pattern(call: ast.Call, imports: ImportIndex) -> bool:
    if not call.args or len(call.args) > _COMPILE_MAX_ARGS:
        return False
    match call.args[0]:
        case ast.Constant(value=str() | bytes()):
            pass
        case _:
            return False
    return len(call.args) < _COMPILE_MAX_ARGS or _is_constant_flags(call.args[1], imports)


def _is_constant_flags(node: ast.expr, imports: ImportIndex) -> bool:
    match node:
        case ast.Constant(value=int() as value):
            return value & _RE_DEBUG_FLAG == 0
        case ast.Name() | ast.Attribute():
            symbol = imports.resolved_symbol(node, sources=_RE_SOURCES)
            return symbol is not None and symbol != "DEBUG"
        case ast.BinOp(op=ast.BitOr(), left=left, right=right):
            return _is_constant_flags(left, imports) and _is_constant_flags(right, imports)
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


def _is_safely_hoistable(
    scope: _Scope,
    func: _Function,
    target: ast.Name,
    candidate: _Candidate,
    *,
    imports: ImportIndex,
    unsafe_bindings: frozenset[str],
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
        elif _is_safe_read(node, scope.parents, candidate, imports, unsafe_bindings):
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


def _is_safe_read(
    node: ast.Name,
    parents: dict[int, ast.AST],
    candidate: _Candidate,
    imports: ImportIndex,
    unsafe_bindings: frozenset[str],
) -> bool:
    parent = parents.get(id(node))
    match parent:
        case ast.Attribute():
            return _is_safe_method_call(parent, parents, _safe_methods_for(candidate))
        case ast.Subscript(value=value, slice=index, ctx=ctx):
            # `x[k]` reads; `x[k] = v` / `del x[k]` mutate.
            # A binding used as `frame[x]` is not representation-neutral:
            # pandas and other selector APIs distinguish a list from a tuple.
            return (
                candidate.kind in {"dict", "list"}
                and value is node
                and isinstance(ctx, ast.Load)
                and not isinstance(index, ast.Slice)
            )
        case ast.Call(args=args, func=callee):
            return any(arg is node for arg in args) and _is_safe_callee(
                callee,
                candidate,
                imports,
                unsafe_bindings,
            )
        case ast.Compare(left=left, ops=ops, comparators=comparators):
            return (
                len(ops) == 1
                and isinstance(ops[0], (ast.In, ast.NotIn))
                and left is not node
                and len(comparators) == 1
                and comparators[0] is node
            )
        case ast.For() | ast.AsyncFor() | ast.comprehension():
            return candidate.kind != "set" and parent.iter is node
        case _:
            return False


def _safe_methods_for(candidate: _Candidate) -> frozenset[str]:
    if candidate.kind == _REGEX_KIND:
        return _SAFE_REGEX_METHODS
    return _SAFE_COLLECTION_METHODS[candidate.kind]


def _is_safe_method_call(
    attribute: ast.Attribute,
    parents: dict[int, ast.AST],
    safe_methods: frozenset[str],
) -> bool:
    if not isinstance(attribute.ctx, ast.Load) or attribute.attr not in safe_methods:
        return False
    parent = parents.get(id(attribute))
    return isinstance(parent, ast.Call) and parent.func is attribute


def _is_safe_callee(
    func: ast.expr,
    candidate: _Candidate,
    imports: ImportIndex,
    unsafe_bindings: frozenset[str],
) -> bool:
    safe_callees = _SET_SAFE_BUILTIN_CALLEES if candidate.kind == "set" else _SAFE_BUILTIN_CALLEES
    return (
        isinstance(func, ast.Name)
        and func.id in safe_callees
        and func.id not in unsafe_bindings
        and imports.builtin_is_unshadowed(func.id)
    )


def _unsafe_bindings(tree: ast.Module) -> frozenset[str]:
    module_imports = {id(statement) for statement in tree.body if isinstance(statement, (ast.Import, ast.ImportFrom))}
    names = {
        alias.asname or alias.name.partition(".")[0]
        for statement in ast.walk(tree)
        if isinstance(statement, (ast.Import, ast.ImportFrom)) and id(statement) not in module_imports
        for alias in statement.names
    }
    if any(
        isinstance(statement, ast.ImportFrom) and any(alias.name == "*" for alias in statement.names)
        for statement in ast.walk(tree)
    ):
        names.add("*")
    names.update(
        candidate.name
        for candidate in ast.walk(tree)
        if isinstance(candidate, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and candidate.name is not None
    )
    names.update(
        candidate.rest
        for candidate in ast.walk(tree)
        if isinstance(candidate, ast.MatchMapping) and candidate.rest is not None
    )
    return frozenset(names)


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _has_re_attribute_mutation(tree: ast.Module) -> bool:
    module_names = {
        alias.asname or "re"
        for statement in tree.body
        if isinstance(statement, ast.Import)
        for alias in statement.names
        if alias.name == "re"
    }
    return any(
        isinstance(node, ast.Attribute)
        and isinstance(node.ctx, (ast.Store, ast.Del))
        and _root_name(node) in module_names
        for node in ast.walk(tree)
    )


def _is_excluded_test_path(path: Path) -> bool:
    return (
        is_test_path(path)
        or is_test_support_path(path)
        or any(part.lower() in {"test", "tests"} for part in path.parts)
    )


def _message(name: str, candidate: _Candidate) -> str:
    if candidate.kind == _REGEX_KIND:
        return f"`{name}` repeats a regex-cache lookup on every call — hoist it to module scope."
    return (
        f"`{name}` is a constant-only {candidate.kind} rebuilt on every call — hoist it "
        "to module scope in immutable form (tuple, frozenset, or an immutable mapping) "
        "so it is built once without exposing mutable shared state."
    )
