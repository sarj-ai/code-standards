"""SARJ023 — Stepdown rule — a single-caller private helper belongs below its caller.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_stepdown.py
"""

from __future__ import annotations

import ast
from collections import Counter
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
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path


_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

type _Def = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef

_SELF_NAMES = frozenset({"self", "cls"})

# These decorators preserve an ordinary callable definition and do not register
# it through user code at definition time. Unknown decorators are movement barriers.
_ORDER_TRANSPARENT_DECORATORS = frozenset({"classmethod", "staticmethod", "final", "override"})

#: A repeated singledispatch implementation name cannot identify one movable target.
_DISCARD_NAME = "_"


def _child_nodes(node: ast.AST) -> Iterator[ast.AST]:
    yield from children(node)


def _walk(node: ast.AST) -> Iterator[ast.AST]:
    stack: list[ast.AST] = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(_child_nodes(n))


@final
class Stepdown(Rule):
    id: str = "stepdown"
    code: str = "SARJ023"
    documentation = RuleDocumentation(
        summary="A private helper used by one caller should be defined below that caller.",
        rationale="Caller-first ordering keeps the module's public flow visible before its implementation details.",
        remediation="Move the private helper below its sole caller without changing either body.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Generated files, tests, `__main__.py`, mutual recursion, and helpers with multiple callers are excluded.",
            "Decorated definitions and dynamic references that cannot prove a sole caller are not reported.",
        ),
        examples=(
            RuleExample(
                example_id="helper-before-sole-caller",
                title="Private helper appears before its sole caller",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def _parse(payload: dict) -> dict:\n    return payload\n\ndef handle(payload: dict) -> dict:\n    return _parse(payload)\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="helper-after-sole-caller",
                title="Private helper appears after its sole caller",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def handle(payload: dict) -> dict:\n    return _parse(payload)\n\ndef _parse(payload: dict) -> dict:\n    return payload\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.name == "__main__.py" or is_generated(path, source):
            return []
        if is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags = _check_module_scope(path, tree, self.code)
        classes = [node for node in _walk(tree) if isinstance(node, ast.ClassDef)]
        family_external = _family_external_refs(classes)
        for cls in classes:
            diags.extend(_check_class_scope(path, cls, self.code, family_external.get(id(cls), frozenset())))
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _last_by_name[DefT: _Def](defs: Sequence[DefT]) -> dict[str, DefT]:
    """Index defs by name, keeping the runtime implementation of an overload group."""
    last: dict[str, DefT] = {}
    for d in defs:
        last[d.name] = d
    return last


def _check_module_scope(path: Path, tree: ast.Module, code: str) -> list[Diagnostic]:
    defs = [n for n in tree.body if isinstance(n, _SCOPE_NODES)]
    counts = Counter(d.name for d in defs)
    unique_defs = {name: d for d in defs if counts[name := d.name] == 1}
    all_defs = _last_by_name(defs)

    pinned = _module_pinned_names(tree, frozenset(all_defs))
    shadowed = _module_assigned_names(tree)

    graph: dict[str, set[str]] = {}
    ref_lines: dict[tuple[str, str], int] = {}
    for d in defs:
        name = d.name
        callees = graph.setdefault(name, set())
        nodes = (
            _resolved_function_loads(d, frozenset(all_defs))
            if isinstance(d, _DEF_NODES)
            else _runtime_nodes(_deferred_body(d))
        )
        local: set[str] = set() if isinstance(d, _DEF_NODES) else _locally_bound_names(d)
        for n in nodes:
            if (
                isinstance(n, ast.Name)
                and isinstance(n.ctx, ast.Load)
                and n.id in all_defs
                and n.id != name
                and n.id not in local
            ):
                callees.add(n.id)
                _record_ref_line(ref_lines, name, n.id, n.lineno)

    diags: list[Diagnostic] = []
    for name, d in unique_defs.items():
        if not isinstance(d, _DEF_NODES) or not _is_private_helper_name(name):
            continue
        if name in pinned or name in shadowed or _has_order_sensitive_decorator(d):
            continue
        diags.extend(
            _flag_if_above_single_caller(path, code, name, node=d, graph=graph, defs=all_defs, ref_lines=ref_lines)
        )
    return diags


def _check_class_scope(path: Path, cls: ast.ClassDef, code: str, external_callers: frozenset[str]) -> list[Diagnostic]:
    methods = [n for n in cls.body if isinstance(n, _DEF_NODES)]
    counts = Counter(m.name for m in methods)
    unique = {name: m for m in methods if counts[name := m.name] == 1}
    all_methods = _last_by_name(methods)

    pinned = _class_pinned_names(cls)
    shadowed = _class_attr_names(cls)
    for m in methods:
        shadowed |= _self_attribute_stores(m)

    graph: dict[str, set[str]] = {}
    ref_lines: dict[tuple[str, str], int] = {}
    for m in methods:
        name = m.name
        callees = graph.setdefault(name, set())
        for n in _runtime_nodes(m.body):
            if not isinstance(n, ast.Attribute) or not isinstance(n.ctx, ast.Load) or n.attr not in all_methods:
                continue
            if _is_same_class_ref(n.value, cls.name):
                if n.attr != name:
                    callees.add(n.attr)
                    _record_ref_line(ref_lines, name, n.attr, n.lineno)
            else:
                # `peer._helper()` may target another instance of this class.
                # Without type information, claiming `self._helper()` is the
                # sole caller would be noisier than conservatively pinning it.
                pinned.add(n.attr)

    diags: list[Diagnostic] = []
    for name, m in unique.items():
        if not _is_private_helper_name(name):
            continue
        if name in pinned or name in shadowed or name in external_callers or _has_order_sensitive_decorator(m):
            continue
        diags.extend(
            _flag_if_above_single_caller(path, code, name, node=m, graph=graph, defs=all_methods, ref_lines=ref_lines)
        )
    return diags


def _flag_if_above_single_caller(
    path: Path,
    code: str,
    name: str,
    *,
    node: ast.stmt,
    graph: dict[str, set[str]],
    defs: Mapping[str, ast.stmt],
    ref_lines: dict[tuple[str, str], int],
) -> list[Diagnostic]:
    callers = [c for c, callees in graph.items() if name in callees]
    if len(callers) != 1:
        return []
    (caller,) = callers
    if caller == _DISCARD_NAME:
        return []
    if isinstance(defs[caller], ast.ClassDef):
        return []
    caller_node = defs[caller]
    if isinstance(caller_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _has_order_sensitive_decorator(caller_node):
        return []
    if _reaches(graph, name, caller):
        return []
    if node.lineno >= defs[caller].lineno:
        return []
    ref_line = ref_lines.get((caller, name), defs[caller].lineno)
    return [
        Diagnostic(
            path=path,
            line=node.lineno,
            col=node.col_offset + 1,
            code=code,
            message=(
                f"private helper `{name}` is defined above its only caller "
                f"`{caller}` (referenced at line {ref_line}) — "
                "move it below the code that calls it (stepdown rule)."
            ),
        )
    ]


def _record_ref_line(ref_lines: dict[tuple[str, str], int], caller: str, callee: str, lineno: int) -> None:
    key = (caller, callee)
    existing = ref_lines.get(key)
    if existing is None or lineno < existing:
        ref_lines[key] = lineno


def _family_external_refs(classes: list[ast.ClassDef]) -> dict[int, frozenset[str]]:
    """Map each class to method names its inheritance relatives reference via self/cls/super."""
    name_to_ids: dict[str, list[int]] = {}
    for c in classes:
        name_to_ids.setdefault(c.name, []).append(id(c))

    parents: dict[int, set[int]] = {id(c): set() for c in classes}
    children: dict[int, set[int]] = {id(c): set() for c in classes}
    for c in classes:
        for base in c.bases:
            bname = _base_name(base)
            if bname is None:
                continue
            for pid in name_to_ids.get(bname, ()):
                if pid != id(c):
                    parents[id(c)].add(pid)
                    children[pid].add(id(c))

    self_refs: dict[int, set[str]] = {id(c): _class_self_method_refs(c) for c in classes}

    external: dict[int, frozenset[str]] = {}
    for c in classes:
        cid = id(c)
        family = _reachable(cid, parents) | _reachable(cid, children)
        ext: set[str] = set()
        for other in family:
            ext |= self_refs[other]
        external[cid] = frozenset(ext)
    return external


def _reachable(start: int, adjacency: dict[int, set[int]]) -> set[int]:
    seen: set[int] = set()
    stack = list(adjacency[start])
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency[node])
    return seen


def _base_name(base: ast.expr) -> str | None:
    match base:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=attr):
            return attr
        case ast.Subscript(value=value):
            return _base_name(value)
        case _:
            return None


def _class_self_method_refs(cls: ast.ClassDef) -> set[str]:
    """Collect method names this class references via `self` / `cls` / `super()` / its own name."""
    out: set[str] = set()
    for m in cls.body:
        if not isinstance(m, _DEF_NODES):
            continue
        for n in _runtime_nodes(m.body):
            if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load) and _is_self_like(n.value, cls.name):
                out.add(n.attr)
    return out


def _is_same_class_ref(value: ast.expr, class_name: str) -> bool:
    return isinstance(value, ast.Name) and (value.id in _SELF_NAMES or value.id == class_name)


def _is_self_like(value: ast.expr, class_name: str) -> bool:
    match value:
        case ast.Name(id=vid):
            return vid in _SELF_NAMES or vid == class_name
        case ast.Call(func=ast.Name(id="super")):
            return True
        case _:
            return False


def _is_private_helper_name(name: str) -> bool:
    if not name.startswith("_"):
        return False
    return not (name.startswith("__") and name.endswith("__"))


def _has_order_sensitive_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        match target:
            case ast.Name(id=name) | ast.Attribute(attr=name) if name in _ORDER_TRANSPARENT_DECORATORS:
                continue
            case _:
                return True
    return False


def _deferred_body(node: ast.stmt) -> list[ast.stmt]:
    """Collect statements that execute only when the def is invoked, not at import."""
    if isinstance(node, _DEF_NODES):
        return node.body
    if isinstance(node, ast.ClassDef):
        return [
            stmt
            for child in node.body
            if isinstance(child, (*_DEF_NODES, ast.ClassDef))
            for stmt in _deferred_body(child)
        ]
    return []


def _runtime_nodes(stmts: list[ast.stmt]) -> Iterator[ast.expr]:
    """Yield expression nodes reachable at call time within `stmts`."""
    stack: list[ast.AST] = list(stmts)
    while stack:
        node = stack.pop()
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                stack.extend(node.body)
                stack.extend(node.decorator_list)
                stack.extend(node.args.defaults)
                stack.extend(d for d in node.args.kw_defaults if d is not None)
            case ast.ClassDef(decorator_list=decorators, bases=bases, keywords=keywords):
                # A nested class owns a separate receiver namespace. Its method
                # bodies are not calls made by the enclosing function/method.
                stack.extend(decorators)
                stack.extend(bases)
                stack.extend(keyword.value for keyword in keywords)
            case ast.AnnAssign(value=value):
                if value is not None:
                    stack.append(value)
            case ast.If(test=test, orelse=orelse) if _is_type_checking_test(test):
                stack.extend(orelse)
            case ast.expr():
                yield node
                stack.extend(_child_nodes(node))
            case _:
                stack.extend(_child_nodes(node))


def _module_pinned_names(tree: ast.Module, definition_names: frozenset[str]) -> set[str]:
    pinned = _global_declaration_names(tree)
    for stmt in tree.body:
        if isinstance(stmt, _DEF_NODES):
            pinned |= _immediate_def_refs(stmt)
        elif isinstance(stmt, ast.ClassDef):
            pinned |= _class_pinned_names(stmt) | _immediate_class_header_refs(stmt)
        else:
            pinned |= _name_loads(stmt)
            for node in _walk(stmt):
                if isinstance(node, ast.Lambda):
                    pinned.update(load.id for load in _resolved_lambda_loads(node, definition_names))
    return pinned


def _global_declaration_names(tree: ast.Module) -> set[str]:
    """Pin names explicitly routed to mutable module state from any nested scope."""
    return {name for node in _walk(tree) if isinstance(node, ast.Global) for name in node.names}


def _class_pinned_names(cls: ast.ClassDef) -> set[str]:
    """Collect bare names referenced at class-creation time inside the class body."""
    pinned: set[str] = set()
    for stmt in cls.body:
        if isinstance(stmt, _DEF_NODES):
            pinned |= _immediate_def_refs(stmt)
        elif isinstance(stmt, ast.ClassDef):
            pinned |= _class_pinned_names(stmt) | _immediate_class_header_refs(stmt)
        else:
            pinned |= _name_loads(stmt)
    for node in _walk(cls):
        match node:
            case ast.Call(
                func=ast.Name(id="getattr" | "setattr" | "hasattr" | "delattr"),
                args=[_, ast.Constant(value=str() as name), *_],
            ):
                pinned.add(name)
            case _:
                pass
    return pinned


def _immediate_def_refs(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect names evaluated at `def` time: decorators, defaults, annotations."""
    parts: list[ast.expr] = list(node.decorator_list)
    parts.extend(node.args.defaults)
    parts.extend(d for d in node.args.kw_defaults if d is not None)
    args = node.args
    parts.extend(
        ann
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
        if a is not None and (ann := a.annotation) is not None
    )
    if node.returns is not None:
        parts.append(node.returns)
    out: set[str] = set()
    for p in parts:
        out |= _name_loads(p)
    return out


def _immediate_class_header_refs(cls: ast.ClassDef) -> set[str]:
    out: set[str] = set()
    for p in (*cls.decorator_list, *cls.bases, *(k.value for k in cls.keywords)):
        out |= _name_loads(p)
    return out


def _name_loads(node: ast.AST) -> set[str]:
    """Collect load-context bare names evaluated where `node` sits at import/def time."""
    out: set[str] = set()
    stack: list[ast.AST] = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Lambda):
            stack.extend(n.args.defaults)
            stack.extend(d for d in n.args.kw_defaults if d is not None)
            continue
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            out.add(n.id)
        stack.extend(_child_nodes(n))
    return out


def _module_assigned_names(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, _SCOPE_NODES):
            continue
        for n in _walk(stmt):
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                out.add(n.id)
            elif isinstance(n, ast.alias):
                out.add((n.asname or n.name).split(".")[0])
    return out


def _class_attr_names(cls: ast.ClassDef) -> set[str]:
    out: set[str] = set()
    for stmt in cls.body:
        if isinstance(stmt, _SCOPE_NODES):
            continue
        for n in _walk(stmt):
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                out.add(n.id)
    return out


def _self_attribute_stores(node: ast.stmt) -> set[str]:
    return {
        n.attr
        for n in _walk(node)
        if isinstance(n, ast.Attribute)
        and isinstance(n.ctx, (ast.Store, ast.Del))
        and isinstance(n.value, ast.Name)
        and n.value.id in _SELF_NAMES
    }


def _locally_bound_names(node: ast.stmt) -> set[str]:
    comp_targets = {
        id(t)
        for n in _walk(node)
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for gen in n.generators
        for t in _walk(gen.target)
        if isinstance(t, ast.Name)
    }
    bound: set[str] = set()
    for n in _walk(node):
        match n:
            case ast.Name(ctx=ast.Store() | ast.Del()) if id(n) not in comp_targets:
                bound.add(n.id)
            case ast.arg():
                bound.add(n.arg)
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() if n is not node:
                bound.add(n.name)
            case ast.alias(name=name, asname=asname):
                bound.add((asname or name).split(".")[0])
            case ast.MatchAs(name=str() as nm) | ast.MatchStar(name=str() as nm) | ast.MatchMapping(rest=str() as nm):
                bound.add(nm)
            case _:
                pass
    return bound


def _resolved_function_loads(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    candidates: frozenset[str],
) -> Iterator[ast.Name]:
    """Yield loads that resolve past the function's lexical scopes to a module definition."""
    blocked = _direct_scope_bindings(node) & candidates
    yield from _resolved_loads(node.body, candidates, blocked)


def _resolved_lambda_loads(node: ast.Lambda, candidates: frozenset[str]) -> Iterator[ast.Name]:
    blocked = _lambda_bindings(node) & candidates
    yield from _resolved_loads((node.body,), candidates, blocked)


def _resolved_loads(
    nodes: Sequence[ast.AST],
    candidates: frozenset[str],
    blocked: set[str],
) -> Iterator[ast.Name]:
    for node in nodes:
        match node:
            case ast.Name(id=name, ctx=ast.Load()) if name in candidates and name not in blocked:
                yield node
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                immediate = (*node.decorator_list, *node.args.defaults, *(d for d in node.args.kw_defaults if d))
                yield from _resolved_loads(immediate, candidates, blocked)
                child_blocked = (blocked | (_direct_scope_bindings(node) & candidates)) - _global_names(node)
                yield from _resolved_loads(node.body, candidates, child_blocked)
            case ast.Lambda():
                immediate = (*node.args.defaults, *(d for d in node.args.kw_defaults if d))
                yield from _resolved_loads(immediate, candidates, blocked)
                child_blocked = blocked | (_lambda_bindings(node) & candidates)
                yield from _resolved_loads((node.body,), candidates, child_blocked)
            case ast.ListComp() | ast.SetComp() | ast.GeneratorExp() | ast.DictComp():
                yield from _resolved_comprehension_loads(node, candidates, blocked)
            case ast.If(test=test, orelse=orelse) if _is_type_checking_test(test):
                yield from _resolved_loads(orelse, candidates, blocked)
            case ast.AnnAssign(value=value):
                if value is not None:
                    yield from _resolved_loads((value,), candidates, blocked)
            case ast.ClassDef():
                # Class namespaces and method closures have different lookup rules.
                # Abstain instead of flattening them into the enclosing function.
                yield from _resolved_loads(
                    (*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)),
                    candidates,
                    blocked,
                )
            case _:
                yield from _resolved_loads(tuple(_child_nodes(node)), candidates, blocked)


def _resolved_comprehension_loads(
    node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp,
    candidates: frozenset[str],
    blocked: set[str],
) -> Iterator[ast.Name]:
    comp_blocked = set(blocked)
    for generator in node.generators:
        yield from _resolved_loads((generator.iter,), candidates, comp_blocked)
        comp_blocked.update(_target_names(generator.target) & candidates)
        yield from _resolved_loads(generator.ifs, candidates, comp_blocked)
    values = (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)
    yield from _resolved_loads(values, candidates, comp_blocked)


def _direct_scope_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    bound = _argument_names(node.args)
    stack: list[ast.AST] = list(node.body)
    while stack:
        current = stack.pop()
        match current:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                bound.add(current.name)
            case ast.Lambda() | ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                continue
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                bound.add(name)
            case ast.alias(name=name, asname=asname):
                bound.add((asname or name).split(".")[0])
            case (
                ast.MatchAs(name=str() as name)
                | ast.MatchStar(name=str() as name)
                | ast.MatchMapping(rest=str() as name)
            ):
                bound.add(name)
            case ast.ExceptHandler(name=str() as name):
                bound.add(name)
                stack.extend(_child_nodes(current))
            case _:
                stack.extend(_child_nodes(current))
    return bound - _global_names(node)


def _lambda_bindings(node: ast.Lambda) -> set[str]:
    return _argument_names(node.args)


def _argument_names(args: ast.arguments) -> set[str]:
    return {
        arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg) if arg is not None
    }


def _global_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    stack: list[ast.AST] = list(node.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(current, ast.Global):
            names.update(current.names)
        stack.extend(_child_nodes(current))
    return names


def _target_names(node: ast.AST) -> set[str]:
    return {child.id for child in _walk(node) if isinstance(child, ast.Name)}


def _is_type_checking_test(test: ast.expr) -> bool:
    match test:
        case ast.Name(id="TYPE_CHECKING") | ast.Attribute(attr="TYPE_CHECKING"):
            return True
        case _:
            return False


def _reaches(graph: dict[str, set[str]], start: str, target: str) -> bool:
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        for nxt in graph.get(node, ()):
            if nxt == target:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False
