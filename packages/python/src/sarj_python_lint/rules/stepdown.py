"""SARJ023: stepdown rule — a single-caller private helper belongs below its caller.

A file should read top-to-bottom like a newspaper: public API first, then the
private helpers it uses. This rule encodes only the fully unambiguous core of
that convention.

The rule is deliberately restricted to helpers with EXACTLY ONE same-scope
caller. For a single-caller helper there is one canonical stepdown position —
immediately below its sole caller — so a violation ("helper sits above its only
caller") has a single, non-arbitrary fix and the reorder is a clear readability
win. Helpers with two or more callers are OUT OF SCOPE: a shared helper has no
canonical "below which caller?" answer (stepping below one caller reads wrong
relative to the others), and the verdict would flip whenever a caller moves.
That multi-caller arbitrariness is exactly the disputed-churn class this
redesign removes.

Fires on:
1. **Module-level helper above its one caller** — a private top-level function
   (`_name`) referenced at call time by EXACTLY ONE top-level function/class,
   and defined above that caller.
2. **Class-level private method above its one caller** — a private, non-dunder
   method referenced via `self._name` / `cls._name` by EXACTLY ONE sibling
   method, and defined above it.

Never fires on:
- Public defs and private top-level classes (declarations, not helpers).
- Unused helpers (no same-scope caller).
- Helpers with two or more same-scope callers (no canonical stepdown target).
- Helpers whose sole caller is a CLASS. A class is a scope, not a call site:
  the real caller is a method inside it, and no module-level position sits
  "directly below" that method — the helper would land after the class's
  closing line, which for a large class is hundreds of lines past the
  reference (`fastapi/routing.py:214`, `_wrap_gen_lifespan_context`, whose
  only "caller" is `APIRouter` spanning lines 2219-6405). Collapsing a whole
  class into one caller also hides genuine multi-caller ambiguity —
  `pydantic/_internal/_generate_schema.py:286` is referenced from three
  different `GenerateSchema` methods yet counted once, exactly the arbitrary
  "below which caller?" case this rule excludes elsewhere. Classes still
  COUNT as callers, so a helper shared by a class and a function stays
  suppressed as multi-caller (31 corpus hits removed, e.g.
  `httpx/_models.py:67`, `rich/console.py:505`, `requests/adapters.py:85`).
- Mutual / indirect / two-node recursion — cycles have no valid stepdown order.
- Names that are position-pinned by an import-time / class-creation-time
  reference: module-level statements, decorator lists, default arguments,
  annotations, class-body attribute values. Moving those breaks runtime.
- Names referenced inside `if TYPE_CHECKING:` blocks (pinned, not call sites).
- Names defined more than once in the scope (`@overload`, `@x.setter`,
  conditional defs), reassigned at module/class scope, or locally rebound
  inside the calling function itself — the reference there resolves to the
  local, so that function is not counted as a caller. A local binding in some
  OTHER (non-calling) function does not suppress the helper.
- Methods decorated `@property` / `@cached_property` (read as attributes) and
  `@abstractmethod` (interface contracts conventionally sit together).
- Methods reached through inheritance: a private method is not flagged when an
  in-module ancestor or descendant class references it via
  `self` / `cls` / `super()`. Same-class caller counting alone would report a
  false "only caller"; the actual caller may live in a sub/superclass (SQLAlchemy
  `_code_str`). Siblings are excluded — an identically-named sibling method is a
  different method. Callers in classes outside the module remain invisible to
  syntactic analysis.
* **generated files** (`_paths.is_generated_source`). Their layout is the
  generator's, and re-running the generator discards any edit, so a finding
  there can never be acted on in place. Measured on the 69 `DO NOT EDIT`
  files git-tracked across bulbul and noura-be — Speakeasy's
  `python/sdk/src/sarj_platform_sdk/` accounts for all of them.
"""

from __future__ import annotations

import ast
from collections import Counter
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path


_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

#: Decorator names that exempt a method from being flagged: property-like
#: methods read as attributes, and abstract methods are interface declarations.
_EXEMPT_METHOD_DECORATORS = frozenset({"property", "cached_property", "abstractmethod", "setter", "getter", "deleter"})

_SELF_NAMES = frozenset({"self", "cls"})


def _child_nodes(node: ast.AST) -> Iterator[ast.AST]:
    yield from ast.iter_child_nodes(node)


def _walk(node: ast.AST) -> Iterator[ast.AST]:
    stack: list[ast.AST] = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(_child_nodes(n))


class Stepdown(Rule):
    """Single-caller private helper defined above its only caller — move it below."""

    id: str = "stepdown"
    code: str = "SARJ023"
    description: str = "Private helper defined above its only caller — move it below the code that calls it."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated_source(source):
            return []
        if _is_test_path(path):
            return []
        if "def _" not in source and "async def _" not in source:
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


def _check_module_scope(path: Path, tree: ast.Module, code: str) -> list[Diagnostic]:
    defs = [n for n in tree.body if isinstance(n, _SCOPE_NODES)]
    counts = Counter(d.name for d in defs)
    unique_defs = {name: d for d in defs if counts[name := d.name] == 1}

    pinned = _module_pinned_names(tree)
    shadowed = _module_assigned_names(tree)

    graph: dict[str, set[str]] = {}
    ref_lines: dict[tuple[str, str], int] = {}
    for name, d in unique_defs.items():
        local = _locally_bound_names(d)
        callees: set[str] = set()
        for n in _runtime_nodes(_deferred_body(d)):
            if (
                isinstance(n, ast.Name)
                and isinstance(n.ctx, ast.Load)
                and n.id in unique_defs
                and n.id != name
                and n.id not in local
            ):
                callees.add(n.id)
                _record_ref_line(ref_lines, name, n.id, n.lineno)
        graph[name] = callees

    diags: list[Diagnostic] = []
    for name, d in unique_defs.items():
        if not isinstance(d, _DEF_NODES) or not _is_private_helper_name(name):
            continue
        if name in pinned or name in shadowed:
            continue
        diags.extend(
            _flag_if_above_single_caller(path, code, name, node=d, graph=graph, defs=unique_defs, ref_lines=ref_lines)
        )
    return diags


def _check_class_scope(path: Path, cls: ast.ClassDef, code: str, external_callers: frozenset[str]) -> list[Diagnostic]:
    methods = [n for n in cls.body if isinstance(n, _DEF_NODES)]
    counts = Counter(m.name for m in methods)
    unique = {name: m for m in methods if counts[name := m.name] == 1}

    pinned = _class_pinned_names(cls)
    shadowed = _class_attr_names(cls)
    for m in methods:
        shadowed |= _self_attribute_stores(m)

    graph: dict[str, set[str]] = {}
    ref_lines: dict[tuple[str, str], int] = {}
    for name, m in unique.items():
        callees: set[str] = set()
        for n in _runtime_nodes(m.body):
            if (
                isinstance(n, ast.Attribute)
                and isinstance(n.ctx, ast.Load)
                and _is_same_class_ref(n.value, cls.name)
                and n.attr in unique
                and n.attr != name
            ):
                callees.add(n.attr)
                _record_ref_line(ref_lines, name, n.attr, n.lineno)
        graph[name] = callees

    diags: list[Diagnostic] = []
    for name, m in unique.items():
        if not _is_private_helper_name(name):
            continue
        if name in pinned or name in shadowed or name in external_callers or _has_exempt_decorator(m):
            continue
        diags.extend(
            _flag_if_above_single_caller(path, code, name, node=m, graph=graph, defs=unique, ref_lines=ref_lines)
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
    if isinstance(defs[caller], ast.ClassDef):
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
                "move it directly below the code that calls it (stepdown rule)."
            ),
        )
    ]


def _record_ref_line(ref_lines: dict[tuple[str, str], int], caller: str, callee: str, lineno: int) -> None:
    key = (caller, callee)
    existing = ref_lines.get(key)
    if existing is None or lineno < existing:
        ref_lines[key] = lineno


def _family_external_refs(classes: list[ast.ClassDef]) -> dict[int, frozenset[str]]:
    """Map each class to method names its inheritance relatives reference via self/cls/super.

    A private method can be called through inheritance — a subclass's
    `self._m()` / `super()._m()`, or a base method's `self._m()` that dispatches
    to a descendant's override. Counting only same-class call sites therefore
    undercounts callers and produces false "only caller" claims (SQLAlchemy
    `_code_str`). For each class this walks its in-module ancestors and
    descendants (by base-name matching) and returns the self/cls/super method
    references those relatives make. A method named here has a caller reachable
    through dispatch from outside its own class body and must not be flagged as
    single-caller. Siblings share an ancestor but not dispatch, so they are
    excluded — a sibling's identically-named private method is a different
    method, and lumping them would wrongly suppress genuine single-caller
    helpers.

    Returns:
        Mapping of `id(ClassDef)` to the inheritance-reachable method references.

    """
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
    """Collect method names this class references via `self` / `cls` / `super()` / its own name.

    Returns:
        The set of self-like method references made in the class's method bodies.

    """
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


def _has_exempt_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        match target:
            case ast.Name(id=name) if name in _EXEMPT_METHOD_DECORATORS:
                return True
            case ast.Attribute(attr=attr) if attr in _EXEMPT_METHOD_DECORATORS:
                return True
            case _:
                pass
    return False


def _deferred_body(node: ast.stmt) -> list[ast.stmt]:
    """Collect statements that execute only when the def is invoked, not at import.

    For a function that is its body; for a class it is the bodies of its
    (recursively nested) methods — class-body statements run at class-creation
    time and are handled as pinning references instead.

    Returns:
        The deferred-execution statements for `node`.

    """
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
    """Yield expression nodes reachable at call time within `stmts`.

    Skips decorator lists / defaults / annotations of the given defs' nested
    defs only where they run at definition time relative to the enclosing
    scope; inside an already-deferred body, nested decorators and defaults DO
    run at call time and are included. Annotations and `if TYPE_CHECKING:`
    bodies are never included.

    Yields:
        Each call-time-reachable expression node.

    """
    stack: list[ast.AST] = list(stmts)
    while stack:
        node = stack.pop()
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                stack.extend(node.body)
                stack.extend(node.decorator_list)
                stack.extend(node.args.defaults)
                stack.extend(d for d in node.args.kw_defaults if d is not None)
            case ast.ClassDef():
                stack.extend(node.body)
                stack.extend(node.decorator_list)
                stack.extend(node.bases)
                stack.extend(k.value for k in node.keywords)
            case ast.AnnAssign():
                if node.value is not None:
                    stack.append(node.value)
            case ast.If() if _is_type_checking_test(node.test):
                stack.extend(node.orelse)
            case ast.expr():
                yield node
                stack.extend(_child_nodes(node))
            case _:
                stack.extend(_child_nodes(node))


def _module_pinned_names(tree: ast.Module) -> set[str]:
    pinned: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, _DEF_NODES):
            pinned |= _immediate_def_refs(stmt)
        elif isinstance(stmt, ast.ClassDef):
            pinned |= _class_pinned_names(stmt) | _immediate_class_header_refs(stmt)
        else:
            pinned |= _name_loads(stmt)
    return pinned


def _class_pinned_names(cls: ast.ClassDef) -> set[str]:
    """Collect bare names referenced at class-creation time inside the class body.

    Returns:
        The set of class-creation-time pinned names.

    """
    pinned: set[str] = set()
    for stmt in cls.body:
        if isinstance(stmt, _DEF_NODES):
            pinned |= _immediate_def_refs(stmt)
        elif isinstance(stmt, ast.ClassDef):
            pinned |= _class_pinned_names(stmt) | _immediate_class_header_refs(stmt)
        else:
            pinned |= _name_loads(stmt)
    return pinned


def _immediate_def_refs(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect names evaluated at `def` time: decorators, defaults, annotations.

    Returns:
        The set of def-time evaluated names.

    """
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
    """Collect load-context bare names evaluated where `node` sits at import/def time.

    A lambda body is deferred — it runs only when the lambda is later invoked,
    not at the point the lambda literal is created — so names inside it are not
    import-time pins. Lambda argument defaults DO evaluate at creation time and
    are kept.

    Returns:
        The set of import/def-time load names.

    """
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
            case ast.alias():
                bound.add((n.asname or n.name).split(".")[0])
            case ast.MatchAs(name=str() as nm) | ast.MatchStar(name=str() as nm):
                bound.add(nm)
            case ast.MatchMapping(rest=str() as nm):
                bound.add(nm)
            case _:
                pass
    return bound


def _is_type_checking_test(test: ast.expr) -> bool:
    match test:
        case ast.Name(id="TYPE_CHECKING"):
            return True
        case ast.Attribute(attr="TYPE_CHECKING"):
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


def _is_test_path(path: Path) -> bool:
    if path.name == "conftest.py":
        return True
    if path.name.startswith("test_"):
        return True
    return "tests" in path.parts
