"""SARJ026 — Public functions returning a bare positional `tuple[A, B, ...]`.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_namedtuple_over_tuple_return.py
"""

from __future__ import annotations

import ast
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
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, nodes, walk
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_TUPLE_NAMES = frozenset({"tuple", "Tuple"})
_SINGLE_RETURN_WRAPPERS = frozenset({"Annotated", "Awaitable", "Optional"})
_UNION_NAMES = frozenset({"Union"})
_COROUTINE_NAMES = frozenset({"Coroutine"})

_MIN_ELEMENTS = 2
_DOCUMENTATION_DIR_NAMES = frozenset({"docs", "docs_src"})

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
    "position; prefer a typing.NamedTuple or frozen dataclass (or a frozen pydantic model at validation boundaries)."
)


@final
class PreferNamedtupleOverTupleReturn(Rule):
    id: str = "prefer-namedtuple-over-tuple-return"
    code: str = "SARJ026"
    documentation = RuleDocumentation(
        summary="Public functions should return named records instead of fixed positional tuples.",
        rationale="A positional tuple hides field meaning and lets callers silently swap or misread values.",
        remediation="Return a `NamedTuple`, frozen dataclass, or frozen validation model with named fields.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Generated files, tests, documentation examples, private functions, nested functions, and declared overrides are excluded.",
            "Only fixed multi-item tuple annotations or inferred tuple-literal returns are reported.",
        ),
        examples=(
            RuleExample(
                example_id="positional-public-return",
                title="Public function returns a positional pair",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/profile.py",
                        "def load_profile() -> tuple[str, int]:\n    return 'Ada', 42\n",
                    ),
                ),
                focus_path=PurePosixPath("app/profile.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-public-return",
                title="Public function returns a named record",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/profile.py",
                        "from typing import NamedTuple\n\nclass Profile(NamedTuple):\n    name: str\n    age: int\n\ndef load_profile() -> Profile:\n    return Profile('Ada', 42)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/profile.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_generated(path, source) or _is_documentation_path(path):
            return []
        if is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        facts = _module_facts(tree)
        diags: list[Diagnostic] = []
        reported: set[tuple[str | None, str]] = set()
        for node, owner in _iter_boundary_functions(tree):
            if node.name.startswith("_") or (owner is not None and owner.name.startswith("_")):
                continue
            if _is_declared_override(node, owner, facts):
                continue
            if not (
                (node.returns is not None and _is_bare_positional_tuple(node.returns, facts.type_aliases))
                or (node.returns is None and _returns_tuple_literal(node))
            ):
                continue
            family = (owner.name if owner is not None else None, node.name)
            if family in reported:
                continue
            reported.add(family)
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


def _is_documentation_path(path: Path) -> bool:
    """Report whether `path` is executable source embedded in documentation."""
    return any(part.lower() in _DOCUMENTATION_DIR_NAMES for part in path.parts)


@dataclass(frozen=True, slots=True)
class _ModuleFacts:
    """What the module knows about itself: its own classes, its imports, its method names."""

    local_classes: frozenset[str]
    #: For each method name, how many distinct classes in this module declare it.
    classes_declaring: dict[str, int]
    type_aliases: dict[str, ast.expr]


def _module_facts(tree: ast.Module) -> _ModuleFacts:
    """Collect the module-wide facts the override heuristics need."""
    local_classes: set[str] = set()
    classes_declaring: dict[str, int] = {}
    type_aliases: dict[str, ast.expr] = {}
    for statement in tree.body:
        if isinstance(statement, ast.TypeAlias):
            type_aliases[statement.name.id] = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and _name_of(statement.annotation) == "TypeAlias"
            and statement.value is not None
        ):
            type_aliases[statement.target.id] = statement.value
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Subscript)
        ):
            type_aliases[statement.targets[0].id] = statement.value
    for node in nodes(tree, ast.ClassDef):
        local_classes.add(node.name)
        for name in {m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}:
            classes_declaring[name] = classes_declaring.get(name, 0) + 1
    return _ModuleFacts(
        local_classes=frozenset(local_classes),
        classes_declaring=classes_declaring,
        type_aliases=type_aliases,
    )


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


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        match dec:
            case ast.Name(id="overload") | ast.Attribute(attr="overload"):
                return True
            case _:
                continue
    return False


def _returns_tuple_literal(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Detect an inferred fixed tuple without descending into nested scopes."""
    pending: list[ast.AST] = [*node.body]
    while pending:
        current = pending.pop()
        match current:
            case ast.Return(value=ast.Tuple(elts=elements)) if len(elements) >= _MIN_ELEMENTS:
                return True
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() | ast.Lambda():
                continue
            case _:
                pending.extend(children(current))
    return False


def _is_bare_positional_tuple(
    annotation: ast.expr,
    aliases: dict[str, ast.expr] | None = None,
    resolving: frozenset[str] = frozenset(),
) -> bool:
    """Report whether an annotation contains a fixed positional tuple with at least two elements."""
    match annotation:
        case ast.Constant(value=str() as value):
            try:
                parsed = ast.parse(value, mode="eval").body
            except SyntaxError:
                return False
            return _is_bare_positional_tuple(parsed, aliases, resolving)
        case ast.Name(id=name) if aliases is not None and name not in resolving:
            target = aliases.get(name)
            return target is not None and _is_bare_positional_tuple(target, aliases, resolving | {name})
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return _is_bare_positional_tuple(left, aliases, resolving) or _is_bare_positional_tuple(
                right, aliases, resolving
            )
        case ast.Subscript():
            pass
        case _:
            return False
    wrapper = _name_of(annotation.value)
    if wrapper in _SINGLE_RETURN_WRAPPERS:
        inner = (
            annotation.slice.elts[0]
            if wrapper == "Annotated" and isinstance(annotation.slice, ast.Tuple)
            else annotation.slice
        )
        return _is_bare_positional_tuple(inner, aliases, resolving)
    if wrapper in _UNION_NAMES:
        members = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return any(_is_bare_positional_tuple(member, aliases, resolving) for member in members)
    if wrapper in _COROUTINE_NAMES:
        members = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return bool(members) and _is_bare_positional_tuple(members[-1], aliases, resolving)
    if wrapper not in _TUPLE_NAMES:
        return False
    if not isinstance(annotation.slice, ast.Tuple):
        return False
    elements = annotation.slice.elts
    if len(elements) < _MIN_ELEMENTS:
        return False
    return not any(_is_ellipsis(el) for el in elements)


def _is_ellipsis(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is Ellipsis


def _name_of(node: ast.expr) -> str | None:
    """Return the trailing name of a reference: `tuple` / `typing.Tuple` -> the trailing id."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
