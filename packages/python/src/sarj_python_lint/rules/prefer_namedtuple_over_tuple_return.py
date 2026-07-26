"""SARJ026: flag public functions returning a bare positional `tuple[A, B, ...]`.

A multi-field value returned across a boundary — from a public function (name not
starting `_`) — must be a `NamedTuple` (or a frozen pydantic model when it needs
validation), never a positional `tuple[A, B]` the caller has to unpack by position.
A bare `tuple[bytes, dict, str | None]` return forces every caller to remember which
slot is which; a typo swaps two fields silently. A named result gives each field a
name and lets pyright catch a wrong-order access.

    # flagged
    def download_to_memory(...) -> tuple[bytes, dict[str, str], str | None]:
        ...

    # preferred
    class Download(NamedTuple):
        body: bytes
        headers: dict[str, str]
        content_type: str | None

    def download_to_memory(...) -> Download:
        ...

The three tuple uses CLAUDE.md permits are deliberately NOT flagged:
- `tuple[X, ...]` — an immutable homogeneous sequence (Ellipsis form),
- `tuple[X, X]` — structurally homogeneous (every element identical, e.g.
  `tuple[int, int]`), a pair of the same thing rather than distinct fields,
- `tuple[Literal["both"], A, B]` — a discriminated-union tag (first element a
  `Literal[...]`).

Also NOT flagged: private (`_`-prefixed) functions, single-element `tuple[X]`,
a bare unsubscripted `tuple`, and any non-tuple / unannotated return.

Famous-repo sweep hardening also exempts:
- test files (`_paths.is_test_path`) — test helpers returning ad-hoc pairs
  (`make_pipe() -> tuple[Send, Receive]`) are local scaffolding, not a public
  boundary;
- interface stubs whose body only raises `NotImplementedError` (plus a
  docstring), `@overload` stubs, and `@abstractmethod` declarations with no
  implementation — the tuple shape mirrors an external protocol (trio's
  `SocketType.accept` mirrors stdlib `socket.accept`;
  `anyio/src/anyio/abc/_sockets.py:230` `receive_fds` mirrors
  `socket.recvmsg`) and cannot change unilaterally. A bare `...` body on an
  *undecorated* function is NOT exempt — it is also the shorthand for an
  ordinary unwritten function;
- **nested functions.** A closure has no callers outside its enclosing
  function, so it never crosses the boundary this rule protects, and the pair
  it returns is usually mandated by the consumer: 2 of the 3 sweep hits are
  `sorted(key=...)` functions that MUST return a tuple
  (`rich/rich/_inspect.py:128`, `rich/rich/scope.py:45`), the third a local
  stack popper (`rich/rich/markup.py:146`);
- **declared overrides.** A method implementing an inherited contract does not
  own its signature. Recognised, in order of directness: an `@override`
  decorator; a `super().<same name>(...)` call in the body
  (`fastapi/fastapi/routing.py:825`, `:1244`); a base whose trailing name
  repeats the class's own name, the "concrete implementation of my ABC" idiom
  (`anyio/src/anyio/_backends/_trio.py:514` `class UNIXSocketStream(SocketStream,
  abc.UNIXSocketStream)`, `:617`, `_asyncio.py:1502`, `:1693`); and an imported
  (non-structural) base combined with a sibling class in the same module
  declaring the same method name — one shared shape across sibling classes is a
  contract, not a local design choice (`fastapi/fastapi/routing.py` declares
  `matches(scope) -> tuple[Match, Scope]`, starlette's `BaseRoute` protocol, on
  6 classes).

An override of a third-party base that carries none of those marks is still
flagged; adding `@override` (which the type checker wants anyway) both
documents the inheritance and silences the rule.

Suppress a deliberate positional return with `# sarj-noqa: SARJ026 — <reason>`.

References:
- https://docs.python.org/3/library/typing.html#typing.NamedTuple

"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from types import EllipsisType
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_TUPLE_NAMES = frozenset({"tuple", "Tuple"})
_LITERAL_NAMES = frozenset({"Literal"})

_MIN_ELEMENTS = 2

#: How many classes in one module must declare a same-named method before the
#: shape counts as a shared contract rather than one class's own design.
_SIBLING_DECLARATIONS = 2

#: Bases that shape a class rather than hand it an interface to implement. A
#: method on a `BaseModel` / `Protocol` / `Generic` subclass is still the
#: module's own design, so these do not mark a method as an inherited override.
_STRUCTURAL_BASES = frozenset(
    {
        "ABC",
        "BaseModel",
        "Enum",
        "Exception",
        "Generic",
        "IntEnum",
        "NamedTuple",
        "Protocol",
        "StrEnum",
        "TypedDict",
        "dict",
        "float",
        "int",
        "list",
        "object",
        "str",
        "tuple",
    }
)

_MSG = (
    "public function returns a bare positional tuple[...] — callers must unpack by "
    "position; prefer a NamedTuple (or a frozen pydantic model for boundary values)."
)


class PreferNamedtupleOverTupleReturn(Rule):
    """Public function returning a bare positional `tuple[A, B, ...]` — prefer a NamedTuple."""

    id: str = "prefer-namedtuple-over-tuple-return"
    code: str = "SARJ026"
    description: str = (
        "public function returning a bare positional tuple[A, B, ...] — prefer a "
        "NamedTuple or frozen pydantic model so callers don't unpack by position."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        facts = _module_facts(tree)
        diags: list[Diagnostic] = []
        for node, owner in _iter_boundary_functions(tree):
            if node.name.startswith("_"):
                continue
            if node.returns is None:
                continue
            if _is_interface_stub(node) or _is_overload(node) or _is_abstract_declaration(node):
                continue
            if _is_declared_override(node, owner, facts):
                continue
            if not _is_bare_positional_tuple(node.returns):
                continue
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=_MSG,
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


@dataclass(frozen=True, slots=True)
class _ModuleFacts:
    """What the module knows about itself: its own classes, its imports, its method names."""

    local_classes: frozenset[str]
    #: For each method name, how many distinct classes in this module declare it.
    classes_declaring: dict[str, int]


def _module_facts(tree: ast.Module) -> _ModuleFacts:
    """Collect the module-wide facts the override heuristics need.

    Returns:
        The names of classes defined here and the per-method-name class counts.

    """
    local_classes: set[str] = set()
    classes_declaring: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        local_classes.add(node.name)
        for name in {m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}:
            classes_declaring[name] = classes_declaring.get(name, 0) + 1
    return _ModuleFacts(local_classes=frozenset(local_classes), classes_declaring=classes_declaring)


def _iter_boundary_functions(
    tree: ast.Module,
) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, ast.ClassDef | None]]:
    """Walk every module-level or class-level function, paired with its owning class.

    Functions nested inside another function are skipped outright: a closure has
    no callers outside the frame that defines it, so its return shape never
    crosses the boundary this rule guards.

    Yields:
        Each boundary function and the class that declares it, if any.

    """
    stack: list[tuple[ast.AST, ast.ClassDef | None]] = [(tree, None)]
    while stack:
        node, owner = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, owner
            continue  # do not descend: everything below is nested in a function
        child_owner = node if isinstance(node, ast.ClassDef) else owner
        stack.extend((child, child_owner) for child in ast.iter_child_nodes(node))


def _is_declared_override(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    facts: _ModuleFacts,
) -> bool:
    """Report whether the method implements a contract inherited from a base class.

    An override does not own its signature: the tuple shape is pinned by the
    base, so changing it here is not an option this module has.

    Returns:
        True when the method is a recognised override.

    """
    if any(_name_of(dec) == "override" for dec in node.decorator_list):
        return True
    if _calls_super_method(node):
        return True
    if owner is None:
        return False
    base_names = [name for base in owner.bases if (name := _name_of(base)) is not None]
    if owner.name in base_names:
        return True  # `class UDPSocket(abc.UDPSocket)` — a concrete impl of its own ABC
    foreign = any(name not in facts.local_classes and name not in _STRUCTURAL_BASES for name in base_names)
    return foreign and facts.classes_declaring.get(node.name, 0) >= _SIBLING_DECLARATIONS


def _calls_super_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the body calls `super().<this method's name>(...)`.

    Returns:
        True when the body delegates to the base implementation.

    """
    for child in ast.walk(node):
        match child:
            case ast.Call(func=ast.Attribute(attr=attr, value=ast.Call(func=ast.Name(id="super")))) if (
                attr == node.name
            ):
                return True
            case _:
                continue
    return False


def _is_abstract_declaration(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the node is an `@abstractmethod` with no implementation.

    Like the `NotImplementedError` stub, such a declaration states a contract
    whose shape usually mirrors something external (anyio's `receive_fds`
    mirrors `socket.recvmsg`), and the concrete side is elsewhere.

    Returns:
        True for an abstract declaration whose body is only a docstring / `...` / `pass`.

    """
    if not any(_name_of(dec) == "abstractmethod" for dec in node.decorator_list):
        return False
    return all(_is_empty_statement(stmt) for stmt in node.body)


def _is_empty_statement(stmt: ast.stmt) -> bool:
    match stmt:
        case ast.Pass():
            return True
        case ast.Expr(value=ast.Constant(value=str() | EllipsisType())):
            return True
        case _:
            return False


def _is_interface_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the body only raises `NotImplementedError` (+ docstring).

    Such a function declares an interface pinned elsewhere; its tuple shape is
    not this module's to change. A bare `...` body is NOT a stub here — it is
    also the shorthand for an ordinary unwritten function.

    Returns:
        True when the body is a NotImplementedError stub.

    """
    has_raise = False
    for stmt in node.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            continue  # docstring
        if _raises_not_implemented(stmt):
            has_raise = True
            continue
        return False
    return has_raise


def _raises_not_implemented(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Raise):
        return False
    exc = stmt.exc
    target = exc.func if isinstance(exc, ast.Call) else exc
    return isinstance(target, ast.Name) and target.id == "NotImplementedError"


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        match dec:
            case ast.Name(id="overload") | ast.Attribute(attr="overload"):
                return True
            case _:
                continue
    return False


def _is_bare_positional_tuple(annotation: ast.expr) -> bool:
    """Report whether `annotation` is `tuple[A, B, ...]` with >=2 heterogeneous elements.

    Exempts the three permitted forms: `tuple[X, ...]` (Ellipsis), structurally
    homogeneous `tuple[X, X]`, and the `tuple[Literal[...], ...]` discriminated tag.

    Returns:
        True when the annotation is a bare positional heterogeneous tuple.

    """
    if not isinstance(annotation, ast.Subscript):
        return False
    if _name_of(annotation.value) not in _TUPLE_NAMES:
        return False
    if not isinstance(annotation.slice, ast.Tuple):
        return False
    elements = annotation.slice.elts
    if len(elements) < _MIN_ELEMENTS:
        return False
    if any(_is_ellipsis(el) for el in elements):
        return False
    if _all_equal(elements):
        return False
    return not _is_literal(elements[0])


def _all_equal(elements: list[ast.expr]) -> bool:
    """Report whether every element is structurally identical (a homogeneous pair/tuple).

    Returns:
        True when all elements are structurally equal.

    """
    first = elements[0]
    return all(_ast_equal(el, first) for el in elements[1:])


def _is_ellipsis(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is Ellipsis


def _is_literal(node: ast.expr) -> bool:
    """Report whether `node` is a `Literal[...]` subscript (discriminated-union tag).

    Returns:
        True when the node is a `Literal[...]` subscript.

    """
    return isinstance(node, ast.Subscript) and _name_of(node.value) in _LITERAL_NAMES


def _name_of(node: ast.expr) -> str | None:
    """Return the trailing name of a reference: `tuple` / `typing.Tuple` -> the trailing id.

    Returns:
        The trailing identifier, or None when `node` is neither a Name nor Attribute.

    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _ast_equal(a: ast.expr, b: ast.expr) -> bool:
    """Compare `a` and `b` structurally, ignoring source positions.

    Returns:
        True when the two trees are structurally equal.

    """
    return ast.dump(a) == ast.dump(b)
