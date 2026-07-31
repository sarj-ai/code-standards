"""SARJ083 — Forbid implicit dictionary accesses using string literals.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_no_implicit_attribute_access.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ083.md
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes, walk


if TYPE_CHECKING:
    from pathlib import Path

_EXCLUDED_BASES = {
    "environ",
    "headers",
    "cookies",
    "session",
    "redis",
    "cache",
    "state",
    "config",
    "kwargs",
    "env",
    "os",
    "sys",
}


# Typing constructs subscripted with string literals. `Literal["x"]` is a type,
# not a lookup, so the rule's advice ("parse declaratively with Pydantic") is
# nonsensical there -- the annotation already IS the declarative schema.
_TYPE_SUBSCRIPTS = frozenset(
    {
        "Literal",
        "Annotated",
        "TypedDict",
        "NamedTuple",
        "Field",
        "Doc",
        "Required",
        "NotRequired",
        "ReadOnly",
    }
)

# Generic wrappers that do not change what the annotated value IS. `Optional[X]`,
# `Final[X]` and `Annotated[X, ...]` all still describe an `X`, so the search for
# a TypedDict has to pass through them; `list[X]` does not, and is not here.
_TYPE_WRAPPERS = frozenset(
    {
        "Optional",
        "Union",
        "Annotated",
        "Final",
        "ClassVar",
        "Required",
        "NotRequired",
        "ReadOnly",
    }
)

# In-place collection methods. A subscript that is one of these calls' receiver
# is building the collection it indexes, not reading a field out of a payload.
_MUTATION_METHODS = frozenset({"append", "add", "extend", "update", "insert", "discard", "setdefault"})

# Namespaces the language itself defines. Their keys are CPython's, not a
# schema anybody could have declared.
_REFLECTION_BASES = frozenset({"f_globals", "f_locals", "__annotations__"})
_REFLECTION_CALLS = frozenset({"globals", "locals", "get_type_hints"})

# `ConfigParser.get(section, option, *, fallback=...)`. `dict.get` has no
# `fallback` parameter, so the keyword alone identifies the call exactly.
_CONFIGPARSER_POSITIONALS = 2


def _looks_like_route_or_url(value: str) -> bool:
    """Report whether a `.get()` argument is a route path or URL rather than a key."""
    return value.startswith("/") or "://" in value


def _get_base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _root_name(node: ast.expr) -> str | None:
    """Walk an attribute/subscript spine down to the identifier it starts at.

    Returns:
        The leftmost `Name`'s identifier, or None when the spine has no root name.

    """
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _is_dunder(key: str) -> bool:
    return key.startswith("__") and key.endswith("__") and len(key) > len("____")


@dataclass(frozen=True, slots=True)
class _FileFacts:
    """The whole-file context a single subscript cannot answer for itself."""

    annotation_nodes: frozenset[int]
    mutation_receivers: frozenset[int]
    schema_bound_names: frozenset[str]
    constant_tables: frozenset[str]


class NoImplicitAttributeAccess(Rule):
    id: str = "no-implicit-attribute-access"
    code: str = "SARJ083"
    has_evidence: bool = True
    description: str = "Implicit dictionary access with string literals — parse declaratively with Pydantic."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if _is_test_path(path) or _is_excluded_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        candidates: list[tuple[ast.Call | ast.Subscript, str]] = []
        for node in nodes(tree, ast.Call, ast.Subscript):
            key = _get_key(node) if isinstance(node, ast.Call) else _subscript_key(node)
            if key is not None:
                candidates.append((node, key))
        if not candidates:
            # The whole-file index below is only ever needed to *reject*, so a
            # file with nothing to reject must not pay for it.
            return []

        facts = _file_facts(tree)
        diags: list[Diagnostic] = []
        for node, key in candidates:
            if _is_exempt(node, key, facts):
                continue
            lookup = f".get('{key}')" if isinstance(node, ast.Call) else f"['{key}']"
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=f"Imperative `{lookup}` lookup — use a declarative Pydantic model instead.",
                )
            )

        return diags


def _get_key(node: ast.Call) -> str | None:
    """Read the string key of a `<base>.get("literal")` lookup worth reporting."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "get" or not node.args:
        return None
    first = node.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return None
    # `.get()` is also the HTTP verb and the route-registration decorator, and
    # both take a string first argument, so the method name alone cannot tell
    # them from a mapping lookup. The ARGUMENT can: a URL or a route path is not
    # a dictionary key. Measured on two first-party repos, this shape was 168 of the
    # rule's 1,756 findings (9.6%) -- `@router.get("/available-events")` and
    # `await self.http_client.get(url)` were reported as implicit schema access.
    if _looks_like_route_or_url(first.value):
        return None
    if _is_configparser_get(node):
        return None
    return None if _get_base_name(func.value) in _EXCLUDED_BASES else first.value


def _is_configparser_get(node: ast.Call) -> bool:
    """Report whether a `.get(...)` call is `ConfigParser.get(section, option)`.

    `conf.get("api", "ssl_cert", fallback="")` reads an INI file by section and
    option; the two string arguments are not a key and a default. `dict.get`
    accepts no `fallback` keyword at all, so its presence alongside two
    positional strings identifies the configparser signature exactly and the
    guard costs no recall.

    Returns:
        True when the call carries `fallback=` and two positional string arguments.

    """
    if not any(kw.arg == "fallback" for kw in node.keywords):
        return False
    if len(node.args) < _CONFIGPARSER_POSITIONALS:
        return False
    return all(
        isinstance(arg, ast.Constant) and isinstance(arg.value, str) for arg in node.args[:_CONFIGPARSER_POSITIONALS]
    )


def _subscript_key(node: ast.Subscript) -> str | None:
    """Read the string key of a `<base>["literal"]` lookup worth reporting."""
    # Writing to a mapping is the opposite of the defect. This rule is about
    # PLUCKING fields out of a payload whose schema is already known -- building
    # a dict up key by key (`field_dict["x"] = x`, `params["status"] = ...`) is
    # ordinary construction, and a Pydantic model does not replace it. Measured
    # on two first-party repos this was 503 of 1,756 findings (28.6%), the single
    # largest source, and every sampled instance was an assignment target. A
    # `d["k"] += 1` target is a `Store` too, so augmented assignment lands here.
    if isinstance(node.ctx, (ast.Store, ast.Del)):
        return None
    # `Literal["a"]`, `Annotated[T, "..."]` and friends are type expressions that
    # merely LOOK like subscripts. They are not dictionary access at all, and no
    # Pydantic model can replace them -- `Literal["user"]` IS the schema. 470 of
    # 1,756 findings (26.8%), second only to assignment targets. The positional
    # annotation guard in `_is_exempt` covers the rest of the same family, where
    # the wrapper is an ordinary generic (`Optional["Router"]`).
    base_name = _get_base_name(node.value)
    if base_name in _TYPE_SUBSCRIPTS:
        return None
    index = node.slice
    if not isinstance(index, ast.Constant) or not isinstance(index.value, str):
        return None
    return None if base_name in _EXCLUDED_BASES else index.value


def _is_exempt(node: ast.Call | ast.Subscript, key: str, facts: _FileFacts) -> bool:
    """Report whether whole-file context clears a lookup the local test flagged.

    Returns:
        True when the lookup is one of the five measured non-defect shapes.

    """
    if _is_dunder(key):
        return True
    if id(node) in facts.annotation_nodes:
        return True
    if isinstance(node, ast.Subscript) and id(node) in facts.mutation_receivers:
        return True
    receiver = _receiver(node)
    if receiver is None:
        return False
    if _get_base_name(receiver) in _REFLECTION_BASES:
        return True
    if isinstance(receiver, ast.Call) and _get_base_name(receiver.func) in _REFLECTION_CALLS:
        return True
    root = _root_name(receiver)
    return root is not None and (root in facts.schema_bound_names or root in facts.constant_tables)


def _receiver(node: ast.Call | ast.Subscript) -> ast.expr | None:
    """Read the expression a lookup is performed ON.

    Returns:
        `x` for `x["k"]` and for `x.get("k")`, or None when the shape is neither.

    """
    match node:
        case ast.Subscript(value=value):
            return value
        case ast.Call(func=ast.Attribute(value=value)):
            return value
        case _:
            return None


def _file_facts(tree: ast.Module) -> _FileFacts:
    """Derive the whole-file context the per-node guards consult.

    Returns:
        The four indexes, each built from the memoized per-file node index.

    """
    typed_dicts = _typed_dict_class_names(tree)
    return _FileFacts(
        annotation_nodes=_annotation_nodes(tree),
        mutation_receivers=_mutation_receivers(tree),
        schema_bound_names=_schema_bound_names(tree, typed_dicts) if typed_dicts else frozenset(),
        constant_tables=_constant_tables(tree),
    )


def _annotation_nodes(tree: ast.Module) -> frozenset[int]:
    """Collect the identity of every node sitting inside an annotation.

    Returns:
        `id()` of each node in a parameter, return or variable annotation subtree.

    """
    roots: list[ast.expr] = []
    for node in nodes(tree, ast.arg, ast.AnnAssign, ast.FunctionDef, ast.AsyncFunctionDef):
        match node:
            case ast.arg(annotation=ast.expr() as annotation):
                roots.append(annotation)
            case ast.AnnAssign(annotation=annotation):
                roots.append(annotation)
            case ast.FunctionDef(returns=ast.expr() as returns) | ast.AsyncFunctionDef(returns=ast.expr() as returns):
                roots.append(returns)
            case _:
                pass
    return frozenset(id(inner) for root in roots for inner in walk(root))


def _mutation_receivers(tree: ast.Module) -> frozenset[int]:
    """Collect subscripts that are the receiver of an in-place collection method.

    Returns:
        `id()` of each `<sub>["k"]` that `.append`/`.update`/… is called on.

    """
    receivers: set[int] = set()
    for call in nodes(tree, ast.Call):
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr in _MUTATION_METHODS:
            receivers.add(id(func.value))
    return frozenset(receivers)


def _typed_dict_class_names(tree: ast.Module) -> frozenset[str]:
    """Collect the names of TypedDict types declared in this file.

    Both spellings are read — `class X(TypedDict)` and the functional
    `X = TypedDict("X", {...})` — and subclassing is followed to a fixed point,
    so a `class Y(X)` under a TypedDict `X` counts too.

    Returns:
        The TypedDict type names declared in this module.

    """
    declared: set[str] = set()
    derived: list[tuple[str, set[str]]] = []
    for cls in nodes(tree, ast.ClassDef):
        bases = {name for base in cls.bases if (name := _get_base_name(base)) is not None}
        if "TypedDict" in bases:
            declared.add(cls.name)
        elif bases:
            derived.append((cls.name, bases))
    for assign in nodes(tree, ast.Assign):
        value = assign.value
        if isinstance(value, ast.Call) and _get_base_name(value.func) == "TypedDict":
            declared.update(target.id for target in assign.targets if isinstance(target, ast.Name))
    grew = True
    while grew:
        grew = False
        for name, bases in derived:
            if name not in declared and bases & declared:
                declared.add(name)
                grew = True
    return frozenset(declared)


def _annotation_heads(annotation: ast.expr) -> frozenset[str]:
    """Collect the type names an annotated value could be an instance of.

    `Optional[X]`, `Final[X]` and `X | None` all still describe an `X`, so the
    wrappers are unwrapped; `list[X]` is NOT, because a list of `X` is a list.
    A string forward reference is parsed and followed.

    Returns:
        The candidate type names, or an empty set for an unreadable annotation.

    """
    match annotation:
        case ast.Name(id=name):
            return frozenset({name})
        case ast.Attribute(attr=name):
            return frozenset({name})
        case ast.Constant(value=str() as text):
            inner = _parse_type_text(text)
            return _annotation_heads(inner) if inner is not None else frozenset()
        case ast.BinOp(op=ast.BitOr(), left=left, right=right):
            return _annotation_heads(left) | _annotation_heads(right)
        case ast.Subscript(value=value, slice=index) if _get_base_name(value) in _TYPE_WRAPPERS:
            elements = index.elts if isinstance(index, ast.Tuple) else [index]
            # Annotated rather than a bare `frozenset()`, whose element type is
            # unknown and makes the whole return type partially unknown.
            empty: frozenset[str] = frozenset()
            return empty.union(*(_annotation_heads(element) for element in elements))
        case ast.Subscript(value=value):
            head = _get_base_name(value)
            return frozenset({head}) if head is not None else frozenset()
        case _:
            return frozenset()


def _parse_type_text(text: str) -> ast.expr | None:
    """Parse a string forward reference into the expression it names.

    Returns:
        The parsed expression, or None when the text is not one.

    """
    try:
        return ast.parse(text, mode="eval").body
    except SyntaxError, ValueError:
        return None


def _schema_bound_names(tree: ast.Module, typed_dicts: frozenset[str]) -> frozenset[str]:
    """Collect names whose declared type is one of this file's TypedDicts.

    Returns:
        The parameter and annotated-variable names bound to a TypedDict type.

    """
    bound: set[str] = set()
    for node in nodes(tree, ast.arg, ast.AnnAssign):
        match node:
            case ast.arg(arg=name, annotation=ast.expr() as annotation):
                pass
            case ast.AnnAssign(target=ast.Name(id=name), annotation=annotation):
                pass
            case _:
                continue
        if _annotation_heads(annotation) & typed_dicts:
            bound.add(name)
    return frozenset(bound)


def _constant_tables(tree: ast.Module) -> frozenset[str]:
    """Collect SCREAMING_CASE names bound to a dict/list literal at a declaration scope.

    Module body and class body only: a constant table is declared, not computed,
    and a local `TABLE = {...}` inside a function body is not what the shape
    describes.

    Returns:
        The constant lookup-table names declared in this file.

    """
    tables: set[str] = set()
    bodies: list[list[ast.stmt]] = [tree.body]
    bodies += [cls.body for cls in nodes(tree, ast.ClassDef)]
    for body in bodies:
        for stmt in body:
            match stmt:
                case ast.Assign(targets=targets, value=ast.Dict() | ast.List()):
                    tables.update(t.id for t in targets if isinstance(t, ast.Name) and t.id.isupper())
                case ast.AnnAssign(target=ast.Name(id=name), value=ast.Dict() | ast.List()) if name.isupper():
                    tables.add(name)
                case _:
                    pass
    return frozenset(tables)


def _is_test_path(path: Path) -> bool:
    return path.name.startswith("test_") or "tests" in path.parts


def _is_excluded_path(path: Path) -> bool:
    excluded = {".uv-cache", ".venv", "venv", "node_modules", "site-packages"}
    return bool(excluded.intersection(path.parts))
