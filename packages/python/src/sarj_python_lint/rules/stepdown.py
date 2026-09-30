from __future__ import annotations

import ast
from collections import Counter
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
)
from sarj_python_lint.rules._ast_index import children
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext


_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

type _Def = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef

# These decorators preserve an ordinary callable definition and do not register
# it through user code at definition time. Unknown decorators are movement barriers.
_ORDER_TRANSPARENT_DECORATORS = frozenset({"classmethod", "staticmethod"})

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


@dataclass(frozen=True, slots=True)
class _TreeIndex:
    nodes: list[ast.AST]
    parents: dict[int, ast.AST]


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
            "Only lexically resolved builtin classmethod/staticmethod decorators are transparent; other decorators and executable statements are movement barriers.",
            "Only direct calls and nonescaping local callable aliases establish callers; escaped values and ambiguous receivers are excluded.",
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
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if path.name == "__main__.py" or context.generated:
            return []
        if is_test_path(path):
            return []
        tree = context.tree
        if tree is None:
            return []
        index = _tree_index(tree)
        nodes, parents = index.nodes, index.parents
        transparent = _transparent_builtin_decorators(tree, nodes)
        diags = _check_module_scope(path, tree, self.code, transparent, parents)
        for node in nodes:
            if isinstance(node, _DEF_NODES):
                diags.extend(
                    _check_module_scope(
                        path, ast.Module(body=node.body, type_ignores=[]), self.code, transparent, parents
                    )
                )
        classes = [node for node in nodes if isinstance(node, ast.ClassDef)]
        family_external = _family_external_refs(classes)
        mutable_names = {name for node in nodes if isinstance(node, (ast.Global, ast.Nonlocal)) for name in node.names}
        for cls in classes:
            diags.extend(
                _check_class_scope(
                    path,
                    cls,
                    self.code,
                    family_external.get(id(cls), frozenset()),
                    transparent,
                    parents=parents,
                    stable_class_name=cls.name not in mutable_names and _stable_class_binding(cls, parents),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _tree_index(tree: ast.Module) -> _TreeIndex:
    nodes: list[ast.AST] = []
    parents: dict[int, ast.AST] = {}
    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        nodes.append(node)
        for child in _child_nodes(node):
            parents[id(child)] = node
            stack.append(child)
    return _TreeIndex(nodes=nodes, parents=parents)


def _last_by_name[DefT: _Def](defs: Sequence[DefT]) -> dict[str, DefT]:
    return {definition.name: definition for definition in defs}


def _check_module_scope(
    path: Path, tree: ast.Module, code: str, transparent: Mapping[int, str], parents: Mapping[int, ast.AST]
) -> list[Diagnostic]:
    defs = [n for n in tree.body if isinstance(n, _SCOPE_NODES)]
    if not any(isinstance(node, _DEF_NODES) and _is_private_helper_name(node.name) for node in defs):
        return []
    counts = Counter(d.name for d in defs)
    unique_defs = {name: d for d in defs if counts[name := d.name] == 1}
    all_defs = _last_by_name(defs)

    pinned = _module_pinned_names(tree, frozenset(all_defs))
    shadowed = _module_assigned_names(tree)

    graph: dict[str, set[str]] = {}
    ref_lines: dict[tuple[str, str], int] = {}
    _module_call_graph(defs, all_defs, graph, ref_lines, parents, pinned=pinned)

    diags: list[Diagnostic] = []
    for name, d in unique_defs.items():
        if not isinstance(d, _DEF_NODES) or not _is_private_helper_name(name):
            continue
        if name in pinned or name in shadowed or _has_order_sensitive_decorator(d, transparent):
            continue
        diags.extend(
            _flag_if_above_single_caller(
                path,
                code,
                name,
                node=d,
                graph=graph,
                defs=all_defs,
                ref_lines=ref_lines,
                transparent=transparent,
                statements=tree.body,
            )
        )
    return diags


def _check_class_scope(
    path: Path,
    cls: ast.ClassDef,
    code: str,
    external_callers: frozenset[str],
    transparent: Mapping[int, str],
    *,
    parents: Mapping[int, ast.AST],
    stable_class_name: bool,
) -> list[Diagnostic]:
    methods = [n for n in cls.body if isinstance(n, _DEF_NODES)]
    if not any(_is_private_helper_name(method.name) for method in methods):
        return []
    counts = Counter(m.name for m in methods)
    unique = {name: m for m in methods if counts[name := m.name] == 1}
    all_methods = _last_by_name(methods)

    pinned = _class_pinned_names(cls)
    shadowed = _class_attr_names(cls)
    for m in methods:
        shadowed |= _self_attribute_stores(m)

    graph: dict[str, set[str]] = {}
    ref_lines: dict[tuple[str, str], int] = {}
    _class_call_graph(
        cls,
        methods,
        all_methods,
        graph,
        ref_lines,
        parents=parents,
        pinned=pinned,
        transparent=transparent,
        stable_class_name=stable_class_name,
    )

    diags: list[Diagnostic] = []
    for name, m in unique.items():
        if not _is_private_helper_name(name):
            continue
        if (
            name in pinned
            or name in shadowed
            or name in external_callers
            or _has_order_sensitive_decorator(m, transparent)
        ):
            continue
        diags.extend(
            _flag_if_above_single_caller(
                path,
                code,
                name,
                node=m,
                graph=graph,
                defs=all_methods,
                ref_lines=ref_lines,
                transparent=transparent,
                statements=cls.body,
            )
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
    transparent: Mapping[int, str],
    statements: Sequence[ast.stmt],
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
    if isinstance(caller_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _has_order_sensitive_decorator(
        caller_node, transparent
    ):
        return []
    if _reaches(graph, name, caller):
        return []
    if node.lineno >= defs[caller].lineno:
        return []
    if not _safe_movement(node, caller_node, statements, transparent):
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
    out: set[str] = set()
    for m in cls.body:
        if not isinstance(m, _DEF_NODES):
            continue
        for n in _walk(m):
            if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
                out.add(n.attr)
    return out


def _is_private_helper_name(name: str) -> bool:
    if not name.startswith("_"):
        return False
    return not (name.startswith("__") and name.endswith("__"))


def _transparent_builtin_decorators(tree: ast.Module, nodes: Sequence[ast.AST]) -> dict[int, str]:
    resolved: dict[int, str] = {}
    mutated = {
        node.attr for node in nodes if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del))
    }

    def visit(scope: ast.Module | _Def, enclosing: dict[str, str]) -> None:
        for child, visible in _scope_decorator_environments(scope, enclosing):
            if isinstance(child, _DEF_NODES):
                for decorator in child.decorator_list:
                    target = _builtin_decorator_target(decorator, visible)
                    if target in _ORDER_TRANSPARENT_DECORATORS and target not in mutated:
                        resolved[id(decorator)] = target
            # A method's body closes over the enclosing function/module,
            # never over its containing class's namespace.
            visit(child, enclosing if isinstance(scope, ast.ClassDef) else visible)

    visit(tree, {name: name for name in _ORDER_TRANSPARENT_DECORATORS})
    return resolved


def _scope_decorator_environments(
    scope: ast.Module | _Def, enclosing: Mapping[str, str]
) -> Iterator[tuple[_Def, dict[str, str]]]:
    if not any(child for statement in scope.body for child in _scope_declarations(statement)):
        return
    bindings = _scope_binding_counts(scope)
    visible = {name: target for name, target in enclosing.items() if name not in bindings}
    for statement in scope.body:
        if isinstance(statement, ast.ImportFrom) and any(alias.name == "*" for alias in statement.names):
            visible.clear()
        visible.update((name, target) for name, target in _builtin_imports(statement) if bindings[name] == 1)
        for child in _scope_declarations(statement):
            yield child, visible


def _scope_declarations(statement: ast.stmt) -> Iterator[_Def]:
    if isinstance(statement, _SCOPE_NODES):
        yield statement
        return
    for child in _child_nodes(statement):
        if isinstance(child, ast.stmt):
            yield from _scope_declarations(child)
        elif isinstance(child, (ast.ExceptHandler, ast.match_case)):
            for nested in child.body:
                yield from _scope_declarations(nested)


def _builtin_imports(statement: ast.stmt) -> Iterator[tuple[str, str]]:
    if isinstance(statement, ast.Import):
        for alias in statement.names:
            if alias.name == "builtins":
                yield alias.asname or alias.name, "builtins"
    elif isinstance(statement, ast.ImportFrom) and statement.module == "builtins" and statement.level == 0:
        for alias in statement.names:
            if alias.name in _ORDER_TRANSPARENT_DECORATORS:
                yield alias.asname or alias.name, alias.name


def _builtin_decorator_target(node: ast.expr, visible: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return visible.get(node.id)
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and visible.get(node.value.id) == "builtins"
    ):
        return node.attr
    return None


def _has_order_sensitive_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef, transparent: Mapping[int, str]
) -> bool:
    return any(id(decorator) not in transparent for decorator in node.decorator_list)


def _safe_movement(
    helper: ast.stmt,
    caller: ast.stmt,
    statements: Sequence[ast.stmt],
    transparent: Mapping[int, str],
) -> bool:
    if not isinstance(helper, _DEF_NODES):
        return False
    dependencies = _immediate_def_refs(helper)
    crossed = [statement for statement in statements if helper.lineno < statement.lineno <= caller.lineno]
    for statement in (helper, *crossed):
        if isinstance(statement, ast.Pass) or (
            isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
        ):
            continue
        if not isinstance(statement, _DEF_NODES) or _has_order_sensitive_decorator(statement, transparent):
            return False
        if statement is not helper and statement.name in dependencies:
            return False
        if _definition_executes_code(statement):
            return False
    return True


def _definition_executes_code(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    # Calls during definition can execute arbitrary code, including the caller
    # before the moved helper has been initialized.
    return any(
        isinstance(child, (ast.Call, ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr))
        for part in _definition_expressions(node)
        for child in _walk(part)
    )


def _definition_expressions(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.expr]:
    yield from node.args.defaults
    yield from (value for value in node.args.kw_defaults if value is not None)
    for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg):
        if argument is not None and argument.annotation is not None:
            yield argument.annotation
    if node.returns is not None:
        yield node.returns


def _scope_binding_counts(scope: ast.Module | _Def) -> Counter[str]:
    counts: Counter[str] = Counter()
    if isinstance(scope, _DEF_NODES):
        counts.update(_argument_names(scope.args))
    stack: list[ast.AST] = list(scope.body)
    while stack:
        node = stack.pop()
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                counts[node.name] += 1
                stack.extend(_scope_header_expressions(node))
            case ast.Lambda():
                stack.extend(node.args.defaults)
                stack.extend(value for value in node.args.kw_defaults if value is not None)
            case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                stack.extend(_comprehension_expressions(node))
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                counts[name] += 1
            case ast.alias(name=name, asname=asname):
                counts[asname or name.split(".")[0]] += 1
            case ast.ExceptHandler(name=str() as name):
                counts[name] += 1
                stack.extend(node.body)
            case (
                ast.MatchAs(name=str() as name)
                | ast.MatchStar(name=str() as name)
                | ast.MatchMapping(rest=str() as name)
            ):
                counts[name] += 1
                stack.extend(_child_nodes(node))
            case _:
                stack.extend(_child_nodes(node))
    return counts


def _scope_header_expressions(node: _Def) -> Iterator[ast.expr]:
    yield from node.decorator_list
    if isinstance(node, _DEF_NODES):
        yield from _definition_expressions(node)
    else:
        yield from node.bases
        yield from (keyword.value for keyword in node.keywords)


def _stable_class_binding(cls: ast.ClassDef, parents: Mapping[int, ast.AST]) -> bool:
    current: ast.AST = cls
    while id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, (ast.Module, *_SCOPE_NODES)):
            return _scope_binding_counts(current)[cls.name] == 1
    return False


def _comprehension_expressions(
    node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
) -> Iterator[ast.expr]:
    for generator in node.generators:
        yield generator.iter
        yield from generator.ifs
    if isinstance(node, ast.DictComp):
        yield node.key
        yield node.value
    else:
        yield node.elt


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
    return {name for node in _walk(tree) if isinstance(node, (ast.Global, ast.Nonlocal)) for name in node.names}


def _class_pinned_names(cls: ast.ClassDef) -> set[str]:
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
            case ast.Call(func=ast.Name(id="getattr" | "setattr" | "hasattr" | "delattr")):
                pinned.update(statement.name for statement in cls.body if isinstance(statement, _DEF_NODES))
            case _:
                pass
    return pinned


def _immediate_def_refs(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
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
    return {n.attr for n in _walk(node) if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del))}


def _resolved_lambda_loads(node: ast.Lambda, candidates: frozenset[str]) -> Iterator[ast.Name]:
    blocked = _lambda_bindings(node) & candidates
    yield from _resolved_loads((node.body,), candidates, blocked)


def _resolved_loads(
    nodes: Sequence[ast.AST],
    candidates: frozenset[str],
    blocked: set[str],
) -> Iterator[ast.Name]:
    for node in nodes:
        yield from _resolved_node_loads(node, candidates, blocked)


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
                stack.extend(_scope_header_expressions(current))
            case ast.Lambda():
                stack.extend(current.args.defaults)
                stack.extend(value for value in current.args.kw_defaults if value is not None)
            case ast.ListComp() | ast.SetComp() | ast.DictComp() | ast.GeneratorExp():
                stack.extend(_comprehension_expressions(current))
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
    bound = _argument_names(node.args)
    stack: list[ast.AST] = [node.body]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.Lambda):
            stack.extend(current.args.defaults)
            stack.extend(default for default in current.args.kw_defaults if default is not None)
            continue
        if isinstance(current, ast.NamedExpr):
            bound.update(_target_names(current.target))
        stack.extend(_child_nodes(current))
    return bound


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


def _module_call_graph(
    defs: list[_Def],
    all_defs: dict[str, _Def],
    graph: dict[str, set[str]],
    ref_lines: dict[tuple[str, str], int],
    parents: Mapping[int, ast.AST],
    *,
    pinned: set[str],
) -> None:
    for definition in defs:
        name = definition.name
        callees = graph.setdefault(name, set())
        nodes = (
            _resolved_function_loads(definition, frozenset(all_defs))
            if isinstance(definition, _DEF_NODES)
            else _runtime_nodes(_deferred_body(definition))
        )
        local: set[str] = set() if isinstance(definition, _DEF_NODES) else _locally_bound_names(definition)
        for node in nodes:
            if not isinstance(node, ast.Name) or node.id not in all_defs or node.id in local:
                continue
            line = _call_reference_line(node, definition, parents)
            if line is None:
                pinned.add(node.id)
            elif node.id != name:
                callees.add(node.id)
                _record_ref_line(ref_lines, name, node.id, line)
        pinned.update(_nested_class_name_loads(definition) & all_defs.keys())


def _runtime_nodes(stmts: list[ast.stmt]) -> Iterator[ast.expr]:
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


def _nested_class_name_loads(definition: _Def) -> set[str]:
    # Nested class closures are real references but have a distinct caller
    # namespace. Do not erase them and claim another function is sole caller.
    return {
        name
        for child in _walk(definition)
        if isinstance(child, ast.ClassDef) and child is not definition
        for name in _name_loads(child)
    }


def _call_reference_line(node: ast.expr, owner: _Def, parents: Mapping[int, ast.AST]) -> int | None:
    parent = parents.get(id(node))
    if isinstance(parent, ast.Call) and parent.func is node:
        return node.lineno if _call_scope_is_local(node, owner, parents) else None
    if not isinstance(owner, _DEF_NODES):
        return None
    alias = _assignment_alias(parent, node)
    if alias is None or parent not in owner.body or _scope_binding_counts(owner)[alias] != 1:
        return None
    if alias in _global_names(owner) or any(
        isinstance(child, ast.Nonlocal) and alias in child.names for child in _walk(owner)
    ):
        return None
    return _local_alias_call_line(owner, alias, node.lineno, parents)


def _call_scope_is_local(node: ast.expr, owner: _Def, parents: Mapping[int, ast.AST]) -> bool:
    current: ast.AST = node
    while id(current) in parents:
        parent = parents[id(current)]
        if parent is owner:
            return True
        if isinstance(parent, ast.ClassDef):
            return False
        if isinstance(parent, _DEF_NODES) and current in parent.body:
            enclosing = parents.get(id(parent))
            if not isinstance(enclosing, _DEF_NODES) or _scope_binding_counts(enclosing)[parent.name] != 1:
                return False
            if _local_alias_call_line(enclosing, parent.name, parent.lineno, parents) is None:
                return False
        if isinstance(parent, ast.Lambda) and current is parent.body:
            return _call_reference_line(parent, owner, parents) is not None
        current = parent
    return False


def _local_alias_call_line(
    owner: ast.FunctionDef | ast.AsyncFunctionDef, alias: str, assigned_line: int, parents: Mapping[int, ast.AST]
) -> int | None:
    uses = [
        child
        for child in _walk(owner)
        if isinstance(child, ast.Name) and child.id == alias and isinstance(child.ctx, ast.Load)
    ]
    if not uses:
        return None
    for use in uses:
        call = parents.get(id(use))
        if not isinstance(call, ast.Call) or call.func is not use or use.lineno <= assigned_line:
            return None
        # A nested closure can escape through its own return value. Only calls
        # made directly by this lexical function establish a nonescaping alias.
        current: ast.AST = use
        while id(current) in parents:
            current = parents[id(current)]
            if current is owner:
                break
            if isinstance(current, (*_SCOPE_NODES, ast.Lambda)):
                return None
    return min(use.lineno for use in uses)


def _assignment_alias(parent: ast.AST | None, value: ast.expr) -> str | None:
    match parent:
        case ast.Assign(targets=[ast.Name(id=name)], value=assigned) if assigned is value:
            return name
        case ast.AnnAssign(target=ast.Name(id=name), value=assigned) if assigned is value:
            return name
        case _:
            return None


def _resolved_function_loads(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    candidates: frozenset[str],
) -> Iterator[ast.Name]:
    blocked = _direct_scope_bindings(node) & candidates
    yield from _resolved_loads(node.body, candidates, blocked)


def _locally_bound_names(node: ast.stmt) -> set[str]:
    comp_targets = _comprehension_target_ids(node)
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


def _deferred_body(node: ast.stmt) -> list[ast.stmt]:
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


def _class_call_graph(
    cls: ast.ClassDef,
    methods: Sequence[ast.FunctionDef | ast.AsyncFunctionDef],
    all_methods: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef],
    graph: dict[str, set[str]],
    ref_lines: dict[tuple[str, str], int],
    *,
    parents: Mapping[int, ast.AST],
    pinned: set[str],
    transparent: Mapping[int, str],
    stable_class_name: bool,
) -> None:
    for method in methods:
        callees = graph.setdefault(method.name, set())
        receivers = _method_receivers(method, cls.name, transparent, stable_class_name=stable_class_name)
        known = {id(node): receivers[node.id] for node in _resolved_loads(method.body, frozenset(receivers), set())}
        for node in _walk(method):
            if (
                not isinstance(node, ast.Attribute)
                or not isinstance(node.ctx, ast.Load)
                or node.attr not in all_methods
            ):
                continue
            receiver_kind = known.get(id(node.value))
            target = all_methods[node.attr]
            target_is_instance = not any(
                transparent.get(id(decorator)) in _ORDER_TRANSPARENT_DECORATORS for decorator in target.decorator_list
            )
            line = _call_reference_line(node, method, parents)
            if receiver_kind is None or (receiver_kind == "class" and target_is_instance) or line is None:
                pinned.add(node.attr)
            elif node.attr != method.name:
                callees.add(node.attr)
                _record_ref_line(ref_lines, method.name, node.attr, line)


def _method_receivers(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    class_name: str,
    transparent: Mapping[int, str],
    *,
    stable_class_name: bool,
) -> dict[str, str]:
    counts = _scope_binding_counts(method)
    mutable_closures = {
        name for node in _walk(method) if isinstance(node, (ast.Global, ast.Nonlocal)) for name in node.names
    }
    receivers = {} if class_name in counts or not stable_class_name else {class_name: "class"}
    kinds = {transparent.get(id(decorator)) for decorator in method.decorator_list}
    positional = (*method.args.posonlyargs, *method.args.args)
    if "staticmethod" not in kinds and positional:
        receiver = positional[0].arg
        if counts[receiver] == 1 and receiver not in mutable_closures:
            receivers[receiver] = "class" if "classmethod" in kinds else "instance"
    return _receiver_aliases(method, receivers, counts, mutable_closures)


def _receiver_aliases(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    receivers: dict[str, str],
    counts: Counter[str],
    mutable_closures: set[str],
) -> dict[str, str]:
    for statement in method.body:
        value = statement.value if isinstance(statement, (ast.Assign, ast.AnnAssign)) else None
        if isinstance(value, ast.Name) and value.id in receivers:
            alias = _assignment_alias(statement, value)
            if alias is not None and counts[alias] == 1 and alias not in mutable_closures:
                receivers[alias] = receivers[value.id]
    return receivers


def _comprehension_target_ids(node: ast.stmt) -> set[int]:
    return {
        id(t)
        for n in _walk(node)
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for gen in n.generators
        for t in _walk(gen.target)
        if isinstance(t, ast.Name)
    }


def _resolved_node_loads(node: ast.AST, candidates: frozenset[str], blocked: set[str]) -> Iterator[ast.Name]:
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
