"""SARJ026 — Public functions returning a bare positional `tuple[A, B, ...]`.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_namedtuple_over_tuple_return.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from types import EllipsisType
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, nodes, walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_TUPLE_NAMES = frozenset({"tuple", "Tuple"})
_LITERAL_NAMES = frozenset({"Literal"})

_MIN_ELEMENTS = 2

#: How many classes in one module must declare a same-named method before the
#: shape counts as a shared contract rather than one class's own design.
_SIBLING_DECLARATIONS = 2

#: Bases that shape a class rather than hand it an interface to implement.
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
    id: str = "prefer-namedtuple-over-tuple-return"
    code: str = "SARJ026"
    description: str = (
        "public function returning a bare positional tuple[A, B, ...] — prefer a "
        "NamedTuple or frozen pydantic model so callers don't unpack by position."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source):
            return []
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
    """Collect the module-wide facts the override heuristics need."""
    local_classes: set[str] = set()
    classes_declaring: dict[str, int] = {}
    for node in nodes(tree, ast.ClassDef):
        local_classes.add(node.name)
        for name in {m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}:
            classes_declaring[name] = classes_declaring.get(name, 0) + 1
    return _ModuleFacts(local_classes=frozenset(local_classes), classes_declaring=classes_declaring)


def _iter_boundary_functions(
    tree: ast.Module,
) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, ast.ClassDef | None]]:
    """Walk every module-level or class-level function, paired with its owning class."""
    stack: list[tuple[ast.AST, ast.ClassDef | None]] = [(tree, None)]
    while stack:
        node, owner = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, owner
            continue  # do not descend: everything below is nested in a function
        child_owner = node if isinstance(node, ast.ClassDef) else owner
        stack.extend((child, child_owner) for child in children(node))


def _is_declared_override(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    facts: _ModuleFacts,
) -> bool:
    """Report whether the method implements a contract inherited from a base class."""
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
    """Report whether the body calls `super().<this method's name>(...)`."""
    for child in walk(node):
        match child:
            case ast.Call(func=ast.Attribute(attr=attr, value=ast.Call(func=ast.Name(id="super")))) if (
                attr == node.name
            ):
                return True
            case _:
                continue
    return False


def _is_abstract_declaration(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the node is an `@abstractmethod` with no implementation."""
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
    """Report whether the body only raises `NotImplementedError` (+ docstring)."""
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
    """Report whether `annotation` is `tuple[A, B, ...]` with >=2 heterogeneous elements."""
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
    """Report whether every element is structurally identical (a homogeneous pair/tuple)."""
    first = elements[0]
    return all(_ast_equal(el, first) for el in elements[1:])


def _is_ellipsis(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is Ellipsis


def _is_literal(node: ast.expr) -> bool:
    """Report whether `node` is a `Literal[...]` subscript (discriminated-union tag)."""
    return isinstance(node, ast.Subscript) and _name_of(node.value) in _LITERAL_NAMES


def _name_of(node: ast.expr) -> str | None:
    """Return the trailing name of a reference: `tuple` / `typing.Tuple` -> the trailing id."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _ast_equal(a: ast.expr, b: ast.expr) -> bool:
    """Compare `a` and `b` structurally, ignoring source positions."""
    return ast.dump(a) == ast.dump(b)
