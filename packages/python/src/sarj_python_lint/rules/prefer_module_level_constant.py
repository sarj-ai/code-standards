"""SARJ039: literal-only constant collection built inside a function — hoist it.

Python port of the TypeScript rule `prefer-module-level-constant`. A lookup
table, allow-list, membership `frozenset` or validation regex written at the top
of a function is rebuilt on every single call. Three costs, in increasing order
of severity:

1. Allocation — every call re-walks the display and re-allocates the list /
   dict / set / tuple, and `re.compile` re-parses the pattern (the module-level
   `re` cache is bounded and evicted wholesale, so it is not a substitute).
2. Discoverability — a domain constant buried in a function body is invisible
   to the next reader and cannot be imported, tested, or reused, so it gets
   duplicated in the next function that needs it. That is the defect class: the
   duplicated copies drift apart.
3. Review churn — this was the single most frequent recurring review comment in
   the mined PR corpus, in Python and TypeScript alike.

Fires on a local binding (`x = ...` / `x: T = ...`) inside a `def` / `async def`
whose value is one of:

* a list / dict / set / tuple display, or `frozenset([...])`, with at least
  `_MIN_ELEMENTS` top-level entries and where EVERY leaf (dict values and keys
  included) is an `ast.Constant` — or a signed numeric constant, or a nested
  display of the same, up to `_MAX_LITERAL_DEPTH`; or
* `re.compile("<literal>")`, optionally with constant flags
  (`re.I`, `re.I | re.M`, a plain int).

"Every leaf is a constant" is the load-bearing gate, not a stylistic
preference. A `Name`, `Attribute`, `Call`, comprehension or f-string leaf means
the value can capture a parameter or observe call-time state, so hoisting it
would be a `NameError` or a behaviour change. Gating on constants kills that
entire false-positive class — including the common
`allowed = [user_id, "admin"]` shape — outright.

Escape / mutation analysis is deliberately STRICT, and stricter than the
TypeScript original. A module-level Python constant is import-time-shared
mutable state living for the life of the process: a wrong hoist is a
cross-request data-corruption bug, not a style regression. So the rule bails
unless EVERY reference to the binding inside the enclosing function is a
provably non-mutating, non-escaping read.

Deliberately NOT flagged:

* **Rebound names.** The name must be bound exactly ONCE in the function. Any
  second binding bails: re-assignment, `x += [...]`, a walrus rebind, `del x`,
  a `global` / `nonlocal` declaration, a `for` target, `with ... as x`,
  `except ... as x`, a comprehension or `match` capture target, an `import as`,
  a same-named nested `def` / `class`, or a parameter of the same name.
* **Mutated collections.** Any method call on the binding that is not on the
  explicit safe list (`get`, `keys`, `values`, `items`, `copy`, `index`,
  `count`) is treated as mutating — default-DENY, so `.append` / `.extend` /
  `.insert` / `.remove` / `.pop` / `.clear` / `.sort` / `.reverse` / `.update` /
  `.add` / `.discard` / `.setdefault` / `.popitem` / `.__setitem__` are covered
  along with anything a future stdlib grows. A subscript STORE (`x[k] = v`),
  `del x[k]`, or an attribute store (`x.attr = v`) likewise bails. A compiled
  regex gets its own safe-method list (`match`, `search`, `fullmatch`,
  `findall`, `finditer`, `split`, `sub`, `subn`) since `re.Pattern` is immutable.
* **Escaping values the caller may mutate.** `return x`, `yield x`, passing `x`
  bare as a positional or keyword argument to a call that is not a known
  non-retaining consumer, `self.x = x`, `d[k] = x`, embedding it in a
  `[x]` / `{...}` display, aliasing it (`y = x`), a `*x` / `**x` spread, or
  capturing it in a nested `def` / `lambda` / `class` body. Once the value
  leaves the function this rule cannot see what happens to it.
* **Safe consumers still fire** — `len(x)`, `sorted(x)`, `set`/`frozenset`/
  `list`/`tuple`/`dict`, `any`, `all`, `min`, `max`, `sum`, `enumerate`,
  `reversed`, `iter`, `json.dumps`, the non-mutating methods above, `x` as a
  `for`/comprehension iterable, `k in x`, a subscript LOAD (`x[0]`), a
  comparison, and f-string interpolation. Note `sorted(x)` and `list(x)` COPY,
  so they are reads, while `x.sort()` mutates in place and bails.
* **Tiny displays** (`< _MIN_ELEMENTS` entries) read better next to their use.
* **Test files and generated files** (`_paths.is_test_path` /
  `_paths.is_generated_source`): fixture tables belong next to the assertion
  that explains them, and generated code mirrors its generator.

One real difference from the TypeScript original: that rule must never hoist a
`/g` or `/y` regex, because a JavaScript RegExp object carries `lastIndex`
across calls to `.test()` / `.exec()`, so a shared instance resumes mid-string
on the next call. A Python compiled pattern carries no per-object scan state —
position is an argument to `.match()` / `.search()`, and `re.finditer` returns a
fresh iterator — so there is no equivalent carve-out here and every constant
`re.compile` is reported.

There is no autofix: hoisting has to pick an insertion point and may collide
with an existing module-scope name, and a wrong automated hoist is worse than
the warning.

A deliberate per-call rebuild (a fresh mutable default the rule cannot see
through, say) is suppressed with `# sarj-noqa: SARJ039 — <reason>`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated_source, is_test_path


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

#: Collection methods known not to mutate the receiver. Everything else is
#: assumed to mutate — default-deny, so an unrecognised method suppresses the
#: report rather than risking a hoist that shares mutable state across calls.
_SAFE_METHODS = frozenset({"copy", "count", "get", "index", "items", "keys", "values"})

#: The `re.Pattern` API. A compiled pattern is immutable and, unlike a JavaScript
#: RegExp, carries no scan state, so these are all pure reads — but the list is
#: still explicit, so an unrecognised method on a pattern bails like any other.
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

#: Nodes that open a scope of their own. A reference to the binding inside one
#: is a capture, which outlives the call and therefore bails.
_INNER_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class PreferModuleLevelConstant(Rule):
    """Literal-only collection or compiled regex rebuilt per call — hoist to module scope."""

    id: str = "prefer-module-level-constant"
    code: str = "SARJ039"
    description: str = (
        "a literal-only collection or compiled regex built inside a function is "
        "rebuilt on every call — hoist it to module scope."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated_source(source):
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
    """A classified initializer: what kind of value it is and how many entries it has."""

    kind: str
    size: int


@dataclass(frozen=True, slots=True)
class _Scope:
    """One function body flattened: every descendant node, its parent, its nesting."""

    nodes: list[ast.AST]
    parents: dict[int, ast.AST]
    nested: set[int]


def _iter_functions(tree: ast.Module) -> Iterator[_Function]:
    """Walk the module for every `def` / `async def`, nested ones included.

    Yields:
        Each function node in the module.

    """
    for node in ast.walk(tree):
        if isinstance(node, _FUNCTION_NODES):
            yield node


def _hoistable_bindings(func: _Function) -> Iterator[tuple[ast.stmt, str, _Candidate]]:
    """Find the bindings in this function's own scope that are safe to hoist.

    Yields:
        The assignment statement, the bound name, and its classified value.

    """
    scope = _scope_of(func)
    for node in scope.nodes:
        if id(node) in scope.nested or not isinstance(node, ast.stmt):
            continue
        binding = _candidate_binding(node)
        if binding is None:
            continue
        target, value = binding
        candidate = _classify(value)
        if candidate is None or not _is_large_enough(candidate):
            continue
        if _is_safely_hoistable(scope, func, target, _safe_methods_for(candidate)):
            yield node, target.id, candidate


def _scope_of(func: _Function) -> _Scope:
    """Flatten the function body into nodes, parent links, and nesting flags.

    A node is "nested" when it lives inside an inner `def` / `lambda` / `class`,
    i.e. in a scope that can outlive or re-enter the enclosing call.

    Returns:
        The flattened view of the function body.

    """
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
        stack.extend((child, node, child_nested) for child in ast.iter_child_nodes(node))
    return _Scope(nodes=nodes, parents=parents, nested=nested)


def _candidate_binding(node: ast.stmt) -> tuple[ast.Name, ast.expr] | None:
    """Match a single-target `x = <value>` / `x: T = <value>` statement.

    Returns:
        The bound name and its initializer, or None for any other statement.

    """
    match node:
        case ast.Assign(targets=[ast.Name() as target], value=value):
            return target, value
        case ast.AnnAssign(target=ast.Name() as target, value=ast.expr() as value):
            return target, value
        case _:
            return None


def _classify(value: ast.expr) -> _Candidate | None:
    """Classify the initializer as a constant-only display, a `frozenset`, or a regex.

    Returns:
        The candidate kind and top-level size, or None when it does not qualify.

    """
    match value:
        case ast.List(elts=elts):
            return _display_candidate("list", value, len(elts))
        case ast.Set(elts=elts):
            return _display_candidate("set", value, len(elts))
        case ast.Tuple(elts=elts):
            return _display_candidate("tuple", value, len(elts))
        case ast.Dict(keys=keys):
            return _display_candidate("dict", value, len(keys))
        case ast.Call():
            return _call_candidate(value)
        case _:
            return None


def _is_large_enough(candidate: _Candidate) -> bool:
    """Apply the `_MIN_ELEMENTS` floor, which a compiled regex is exempt from.

    Returns:
        True when the candidate is worth hoisting on size grounds.

    """
    return candidate.kind == _REGEX_KIND or candidate.size >= _MIN_ELEMENTS


def _display_candidate(kind: str, node: ast.expr, size: int) -> _Candidate | None:
    """Accept a display only when every one of its leaves is a constant.

    Returns:
        The candidate, or None when any leaf is non-constant.

    """
    return _Candidate(kind=kind, size=size) if _is_constant_only(node, 0) else None


def _call_candidate(call: ast.Call) -> _Candidate | None:
    """Classify `frozenset([...])` and `re.compile("...")` call initializers.

    Returns:
        The candidate, or None for any other call.

    """
    if call.keywords:
        return None
    callee = _dotted_name(call.func)
    if callee == _FROZENSET:
        return _frozenset_candidate(call)
    if callee == _RE_COMPILE and _is_constant_pattern(call):
        return _Candidate(kind=_REGEX_KIND, size=1)
    return None


def _frozenset_candidate(call: ast.Call) -> _Candidate | None:
    """Accept `frozenset(<constant-only display>)`.

    Returns:
        The candidate, or None when the sole argument is not a constant display.

    """
    match call.args:
        case [ast.List(elts=elts) | ast.Set(elts=elts) | ast.Tuple(elts=elts) as inner] if _is_constant_only(inner, 0):
            return _Candidate(kind=_FROZENSET_KIND, size=len(elts))
        case _:
            return None


def _is_constant_pattern(call: ast.Call) -> bool:
    """Report whether a `re.compile(...)` call takes a literal pattern and constant flags.

    Returns:
        True when the compiled pattern is fully determined at import time.

    """
    if not call.args or len(call.args) > _COMPILE_MAX_ARGS:
        return False
    match call.args[0]:
        case ast.Constant(value=str() | bytes()):
            pass
        case _:
            return False
    return len(call.args) < _COMPILE_MAX_ARGS or _is_constant_flags(call.args[1])


def _is_constant_flags(node: ast.expr) -> bool:
    """Report whether a `re.compile` flags argument is an import-time constant.

    Accepts an int literal, an `re.<FLAG>` attribute, and `|` combinations of
    those — the only flag shapes real code uses.

    Returns:
        True when the flags expression is constant.

    """
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
    """Report whether the expression is built entirely out of constants.

    No name, no attribute, no call, no comprehension, no f-string, no spread. A
    constant-only value cannot capture a parameter, cannot observe call-time
    state, and cannot have side effects, which is exactly what makes the hoist
    provably safe.

    Returns:
        True when every leaf of the expression is a literal constant.

    """
    if depth > _MAX_LITERAL_DEPTH:
        return False
    match node:
        case ast.Constant():
            return True
        case ast.UnaryOp(op=ast.USub() | ast.UAdd(), operand=ast.Constant(value=int() | float() | complex())):
            return True
        case ast.List(elts=elts) | ast.Set(elts=elts) | ast.Tuple(elts=elts):
            return all(_is_constant_only(element, depth + 1) for element in elts)
        case ast.Dict(keys=keys, values=values):
            entries = [*keys, *values]
            return all(entry is not None and _is_constant_only(entry, depth + 1) for entry in entries)
        case _:
            return False


def _safe_methods_for(candidate: _Candidate) -> frozenset[str]:
    """Pick the non-mutating method list that applies to this kind of value.

    Returns:
        The methods callable on the binding without mutating it.

    """
    return _SAFE_REGEX_METHODS if candidate.kind == _REGEX_KIND else _SAFE_METHODS


def _is_safely_hoistable(
    scope: _Scope,
    func: _Function,
    target: ast.Name,
    safe_methods: frozenset[str],
) -> bool:
    """Report whether every reference to the binding is a non-mutating, non-escaping read.

    Default-deny: the binding must be bound exactly once and every other
    reference must be recognised as safe, so an unfamiliar usage suppresses the
    report rather than risking a hoist that shares mutable state across calls.

    Returns:
        True when the binding can be moved to module scope without changing behaviour.

    """
    name = target.id
    if name in _parameter_names(func):
        return False
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
        elif not _is_safe_read(node, scope.parents, safe_methods):
            return False
    return True


def _parameter_names(func: _Function) -> frozenset[str]:
    """Collect every parameter name of the function, variadics included.

    Returns:
        The parameter names, which the binding may not shadow.

    """
    args = func.args
    params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    params.extend(arg for arg in (args.vararg, args.kwarg) if arg is not None)
    return frozenset(param.arg for param in params)


def _mentions_name(node: ast.AST, name: str) -> bool:
    """Report whether this node inside an inner scope refers to the binding.

    Returns:
        True when an inner `def` / `lambda` / `class` captures or shadows the name.

    """
    match node:
        case ast.Name(id=ident):
            return ident == name
        case ast.arg(arg=ident):
            return ident == name
        case ast.Global(names=names) | ast.Nonlocal(names=names):
            return name in names
        case _:
            return False


def _rebinds_name(node: ast.AST, name: str) -> bool:
    """Report whether this node binds the name through something other than a `Name` store.

    Covers the binding forms that carry the name as a plain string:
    `except ... as x`, `global` / `nonlocal`, a nested `def` / `class`, an
    `import as`, and `match` captures.

    Returns:
        True when the node is a second binding of the name.

    """
    match node:
        case ast.Global(names=names) | ast.Nonlocal(names=names):
            return name in names
        case ast.ExceptHandler(name=bound):
            return bound == name
        case ast.FunctionDef(name=bound) | ast.AsyncFunctionDef(name=bound) | ast.ClassDef(name=bound):
            return bound == name
        case ast.alias(asname=None, name=module):
            return module.split(".")[0] == name
        case ast.alias(asname=str() as bound):
            return bound == name
        case ast.MatchAs(name=bound) | ast.MatchStar(name=bound):
            return bound == name
        case ast.MatchMapping(rest=rest):
            return rest == name
        case _:
            return False


def _is_safe_read(node: ast.Name, parents: dict[int, ast.AST], safe_methods: frozenset[str]) -> bool:
    """Report whether this single reference to the binding neither mutates nor escapes it.

    Returns:
        True when the reference is a recognised non-mutating, non-escaping read.

    """
    parent = parents.get(id(node))
    match parent:
        case ast.Attribute():
            return _is_safe_method_call(parent, parents, safe_methods)
        case ast.Subscript(value=value, ctx=ctx):
            # `x[k]` reads; `x[k] = v` / `del x[k]` mutate. `d[x]` uses the
            # binding as a key, which is a plain read whatever `d` does.
            return isinstance(ctx, ast.Load) if value is node else True
        case ast.Call(args=args, func=callee):
            return any(arg is node for arg in args) and _is_safe_callee(callee)
        case ast.keyword(arg=str(), value=value) if value is node:
            grandparent = parents.get(id(parent))
            return isinstance(grandparent, ast.Call) and _is_safe_callee(grandparent.func)
        case ast.Compare():
            return True
        case ast.For(iter=iterable) | ast.AsyncFor(iter=iterable) | ast.comprehension(iter=iterable):
            return iterable is node
        case ast.FormattedValue():
            return True
        case _:
            return False


def _is_safe_method_call(
    attribute: ast.Attribute,
    parents: dict[int, ast.AST],
    safe_methods: frozenset[str],
) -> bool:
    """Report whether `x.<attr>` is an immediate call to a known non-mutating method.

    A bare `x.attr` read that is not called hands the bound method out, and an
    attribute store mutates, so both are unsafe.

    Returns:
        True when the attribute is a called method on the safe list.

    """
    if not isinstance(attribute.ctx, ast.Load) or attribute.attr not in safe_methods:
        return False
    parent = parents.get(id(attribute))
    return isinstance(parent, ast.Call) and parent.func is attribute


def _is_safe_callee(func: ast.expr) -> bool:
    """Report whether a call that receives the binding is known not to retain or mutate it.

    Returns:
        True when the callee is on the safe list.

    """
    return _dotted_name(func) in _SAFE_CALLEES


def _dotted_name(node: ast.expr) -> str | None:
    """Render a `Name` / `Attribute` chain as a dotted string.

    Returns:
        The dotted name, or None when the expression is not a plain chain.

    """
    match node:
        case ast.Name(id=ident):
            return ident
        case ast.Attribute(value=value, attr=attr):
            base = _dotted_name(value)
            return None if base is None else f"{base}.{attr}"
        case _:
            return None


def _message(name: str, candidate: _Candidate) -> str:
    """Render the diagnostic text for one hoistable binding.

    Returns:
        The message naming the binding and the hoist.

    """
    if candidate.kind == _REGEX_KIND:
        return (
            f"`{name}` is a constant regex recompiled on every call — hoist it to module scope so it is compiled once."
        )
    return (
        f"`{name}` is a constant-only {candidate.kind} rebuilt on every call — hoist it "
        "to module scope so it is built once and can be imported, reused, and tested."
    )
