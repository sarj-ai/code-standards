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
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_TUPLE_NAMES = frozenset({"tuple", "Tuple"})
_SINGLE_RETURN_WRAPPERS = frozenset({"Annotated", "Awaitable", "Optional"})
_UNION_NAMES = frozenset({"Union"})
_COROUTINE_NAMES = frozenset({"Coroutine"})
_COLLECTION_RETURN_WRAPPERS = frozenset(
    {"Collection", "Iterable", "List", "Mapping", "Sequence", "dict", "frozenset", "list", "set"}
)

_MIN_ELEMENTS = 2
_DOCUMENTATION_DIR_NAMES = frozenset({"docs", "docs_src"})
_SORT_KEY_CALLS = frozenset({"max", "min", "sorted"})
_FIXTURE_DECORATORS = frozenset({"fixture", "yield_fixture"})
_POSITIONAL_RETURN_PROTOCOLS = frozenset({"__reduce__", "__reduce_ex__"})

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
    "function return contract contains a fixed positional tuple[...] — callers must unpack by "
    "position; prefer a typing.NamedTuple or frozen dataclass (or a frozen pydantic model at validation boundaries)."
)


@final
class PreferNamedtupleOverTupleReturn(Rule):
    id: str = "prefer-namedtuple-over-tuple-return"
    code: str = "SARJ026"
    documentation = RuleDocumentation(
        summary="Functions should return named records instead of fixed positional tuples, including tuples nested in collections.",
        rationale="A positional tuple hides field meaning and lets callers silently swap or misread values.",
        remediation="Return a `NamedTuple`, frozen dataclass, or frozen validation model with named fields.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Generated files, documentation examples, declared overrides, pytest fixtures, pickle protocols, and syntax-proven sort/key callbacks are excluded.",
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
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        facts = _module_facts(tree)
        diags: list[Diagnostic] = []
        reported: set[str] = set()
        for node, owner, qualified_name in _iter_boundary_functions(tree):
            if node.name in _POSITIONAL_RETURN_PROTOCOLS:
                continue
            if _is_declared_override(node, owner, facts, path):
                continue
            if (
                _is_fixture(node, facts)
                or _is_sort_key_callback(node, tree)
                or _is_opaque_composite_key(node, owner, tree, facts)
                or _is_nested_adapter_of_override(node, owner, facts, path)
            ):
                continue
            if not (
                (node.returns is not None and _is_bare_positional_tuple(node.returns, facts.type_aliases))
                or (node.returns is None and _returns_tuple_literal(node))
            ):
                continue
            if qualified_name in reported:
                continue
            reported.add(qualified_name)
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
    return any(part.lower() in _DOCUMENTATION_DIR_NAMES for part in path.parts)


@dataclass(frozen=True, slots=True)
class _ModuleFacts:
    local_classes: frozenset[str]
    #: For each method name, how many distinct classes in this module declare it.
    classes_declaring: dict[str, int]
    class_methods: dict[str, frozenset[str]]
    type_aliases: dict[str, ast.expr]
    fixture_decorators: frozenset[str]
    parents: dict[ast.AST, ast.AST]


def _module_facts(tree: ast.Module) -> _ModuleFacts:
    local_classes: set[str] = set()
    classes_declaring: dict[str, int] = {}
    class_methods: dict[str, frozenset[str]] = {}
    type_aliases: dict[str, ast.expr] = {}
    fixture_decorators: set[str] = set(_FIXTURE_DECORATORS)
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and statement.module in {"pytest", "pytest_asyncio"}:
            fixture_decorators.update(
                alias.asname or alias.name for alias in statement.names if alias.name == "fixture"
            )
        elif isinstance(statement, ast.TypeAlias):
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
        methods = {m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
        class_methods[node.name] = frozenset(methods)
        for name in methods:
            classes_declaring[name] = classes_declaring.get(name, 0) + 1
    return _ModuleFacts(
        local_classes=frozenset(local_classes),
        classes_declaring=classes_declaring,
        class_methods=class_methods,
        type_aliases=type_aliases,
        fixture_decorators=frozenset(fixture_decorators),
        parents={child: parent for parent in walk(tree) for child in children(parent)},
    )


def _iter_boundary_functions(
    tree: ast.Module,
) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, ast.ClassDef | None, str]]:
    stack: list[tuple[ast.AST, ast.ClassDef | None, tuple[str, ...]]] = [(tree, None, ())]
    while stack:
        node, owner, prefix = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified = (*prefix, node.name)
            yield node, owner, ".".join(qualified)
            stack.extend((child, owner, qualified) for child in children(node))
            continue
        if isinstance(node, ast.ClassDef):
            qualified = (*prefix, node.name)
            stack.extend((child, node, qualified) for child in children(node))
            continue
        stack.extend((child, owner, prefix) for child in children(node))


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef, facts: _ModuleFacts) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = _name_of(target)
        if name in facts.fixture_decorators:
            return True
    return False


def _is_sort_key_callback(node: ast.FunctionDef | ast.AsyncFunctionDef, tree: ast.Module) -> bool:
    for call in nodes(tree, ast.Call):
        function = _name_of(call.func)
        if function not in _SORT_KEY_CALLS and not (isinstance(call.func, ast.Attribute) and call.func.attr == "sort"):
            continue
        if any(
            keyword.arg == "key" and isinstance(keyword.value, ast.Name) and keyword.value.id == node.name
            for keyword in call.keywords
        ):
            return True
    return False


def _is_declared_override(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    facts: _ModuleFacts,
    path: Path,
) -> bool:
    if any(_name_of(dec) == "override" for dec in node.decorator_list):
        return True
    if _calls_super_method(node):
        return True
    if owner is None:
        return False
    base_names = [name for base in owner.bases if (name := _name_of(base)) is not None]
    if any(node.name in facts.class_methods.get(name, frozenset()) for name in base_names):
        return True
    if owner.name in base_names:
        return True  # `class UDPSocket(abc.UDPSocket)` — a concrete impl of its own ABC
    foreign = any(name not in facts.local_classes and name not in _STRUCTURAL_BASES for name in base_names)
    if foreign and not node.name.startswith("_") and (is_test_path(path) or is_test_support_path(path)):
        return True
    return foreign and facts.classes_declaring.get(node.name, 0) >= _SIBLING_DECLARATIONS


def _is_nested_adapter_of_override(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    facts: _ModuleFacts,
    path: Path,
) -> bool:
    parent = facts.parents.get(node)
    while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
        parent = facts.parents.get(parent)
    if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    if not _is_declared_override(parent, owner, facts, path):
        return False
    references = [
        candidate
        for candidate in walk(parent)
        if isinstance(candidate, ast.Name) and isinstance(candidate.ctx, ast.Load) and candidate.id == node.name
    ]
    if not references:
        return False
    for reference in references:
        current: ast.AST | None = reference
        while current is not None and current is not parent and not isinstance(current, ast.Return):
            current = facts.parents.get(current)
        if not isinstance(current, ast.Return):
            return False
    return True


_OPAQUE_KEY_METHODS = frozenset({"add", "discard", "get", "pop", "remove", "setdefault"})


def _is_opaque_composite_key(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
    tree: ast.Module,
    facts: _ModuleFacts,
) -> bool:
    if _is_frozen_dataclass_key_property(node, owner):
        return True
    if owner is not None or not node.name.startswith("_"):
        return False
    calls = [call for call in nodes(tree, ast.Call) if isinstance(call.func, ast.Name) and call.func.id == node.name]
    return bool(calls) and all(_value_is_used_opaquely(call, tree, facts.parents) for call in calls)


def _is_frozen_dataclass_key_property(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    owner: ast.ClassDef | None,
) -> bool:
    if owner is None or node.name != "key" or not any(_name_of(dec) == "property" for dec in node.decorator_list):
        return False
    frozen = any(
        _name_of(dec.func) == "dataclass"
        and any(
            keyword.arg == "frozen" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
            for keyword in dec.keywords
        )
        for dec in owner.decorator_list
        if isinstance(dec, ast.Call)
    )
    if not frozen:
        return False
    returns = [child for child in walk(node) if isinstance(child, ast.Return)]
    return bool(returns) and all(
        isinstance(ret.value, ast.Tuple)
        and len(ret.value.elts) >= _MIN_ELEMENTS
        and all(
            isinstance(element, ast.Attribute) and isinstance(element.value, ast.Name) and element.value.id == "self"
            for element in ret.value.elts
        )
        for ret in returns
    )


def _value_is_used_opaquely(value: ast.expr, tree: ast.Module, parents: dict[ast.AST, ast.AST]) -> bool:
    parent = parents.get(value)
    match parent:
        case ast.Compare():
            return True
        case ast.Subscript(slice=slice_node) if slice_node is value:
            return True
        case ast.Call(func=ast.Attribute(attr=method), args=args) if method in _OPAQUE_KEY_METHODS and value in args:
            return True
        case ast.Assign():
            if len(parent.targets) != 1:
                return False
            target = parent.targets[0]
        case ast.AnnAssign():
            target = parent.target
        case _:
            return False

    if not isinstance(target, ast.Name):
        return False
    scope: ast.AST = parent
    while not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
        next_scope = parents.get(scope)
        if next_scope is None:
            return False
        scope = next_scope
    loads = [
        candidate
        for candidate in walk(scope)
        if isinstance(candidate, ast.Name) and isinstance(candidate.ctx, ast.Load) and candidate.id == target.id
    ]
    return bool(loads) and all(_value_is_used_opaquely(load, tree, parents) for load in loads)


def _calls_super_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
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
    minimum_elements: int = _MIN_ELEMENTS,
) -> bool:
    match annotation:
        case ast.Constant(value=str() as value):
            try:
                parsed = ast.parse(value, mode="eval").body
            except SyntaxError:
                return False
            return _is_bare_positional_tuple(parsed, aliases, resolving, minimum_elements)
        case ast.Name(id=name) if aliases is not None and name not in resolving:
            target = aliases.get(name)
            return target is not None and _is_bare_positional_tuple(
                target, aliases, resolving | {name}, minimum_elements
            )
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return _is_bare_positional_tuple(left, aliases, resolving, minimum_elements) or _is_bare_positional_tuple(
                right, aliases, resolving, minimum_elements
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
        return _is_bare_positional_tuple(inner, aliases, resolving, minimum_elements)
    if wrapper in _UNION_NAMES:
        members = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return any(_is_bare_positional_tuple(member, aliases, resolving, minimum_elements) for member in members)
    if wrapper in _COROUTINE_NAMES:
        members = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return bool(members) and _is_bare_positional_tuple(members[-1], aliases, resolving, minimum_elements)
    if wrapper in _COLLECTION_RETURN_WRAPPERS:
        members = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        return any(_is_bare_positional_tuple(member, aliases, resolving, _MIN_ELEMENTS) for member in members)
    if wrapper not in _TUPLE_NAMES:
        return False
    if not isinstance(annotation.slice, ast.Tuple):
        return False
    elements = annotation.slice.elts
    if len(elements) < minimum_elements:
        return False
    return not any(_is_ellipsis(el) for el in elements)


def _is_ellipsis(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is Ellipsis


def _name_of(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None
