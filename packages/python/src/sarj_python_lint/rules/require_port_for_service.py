"""SARJ071 — A concrete service with injected collaborators and no ABC above it is not substitutable

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_require_port_for_service.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


# Name tails that mark a class as a service in this codebase's own vocabulary.
_SERVICE_NAME_RE = re.compile(r"(?:Service|Store|DAO|Dao|Gateway|Provider)$")

# Classes named as the base of a family are the port being asked for, not a missing one.
_BASE_NAME_RE = re.compile(r"^(?:Base|Abstract)[A-Z_]")

# Annotations that name a value rather than a collaborator.
_PRIMITIVE_ANNOTATIONS = frozenset(
    {
        "str",
        "int",
        "bool",
        "float",
        "complex",
        "bytes",
        "bytearray",
        "object",
        "None",
        "Any",
        "list",
        "dict",
        "set",
        "frozenset",
        "tuple",
        "type",
        # The capitalised `typing` aliases are the same builtins.
        "List",
        "Dict",
        "Set",
        "FrozenSet",
        "Tuple",
        "Type",
        "Text",
        "Sequence",
        "Mapping",
        "MutableMapping",
        "Iterable",
        "Iterator",
        "Collection",
        "Callable",
        "Path",
        "PurePath",
        "UUID",
        "datetime",
        "date",
        "time",
        "timedelta",
        "Decimal",
        "Fraction",
        "Pattern",
        "TextIO",
        "BinaryIO",
    }
)

# Injected types that are configuration or ambient runtime, not a substitutable
# collaborator: nobody swaps a `ServerSettings` or a LiveKit `JobContext` in a test.
_WEAK_COLLABORATOR_RE = re.compile(r"(?:Settings|Config|Configuration|Options|Logger|Log|Clock|Context)$")

# Annotation wrappers that are transparent — the collaborator is inside them.
_TRANSPARENT_GENERICS = frozenset({"Optional", "Union", "Annotated", "Awaitable", "Coroutine", "Final", "ClassVar"})

# Bases that make a same-module class a data type, so a parameter annotated with it is
# a value being passed, not a port being injected.
_DATA_BASES = frozenset(
    {
        "BaseModel",
        "RootModel",
        "TypedDict",
        "NamedTuple",
        "Enum",
        "StrEnum",
        "IntEnum",
        "IntFlag",
        "Flag",
        "Struct",
        "Exception",
        "BaseException",
    }
)

# Decorators that turn a class into a record.
_DATA_DECORATORS = frozenset({"dataclass", "dataclasses", "define", "frozen", "mutable", "attrs", "attr", "s"})

# Method decorators that mean the callable is not an instance method a consumer calls
# through the port: descriptors, factories and namespaced helpers.
_NON_METHOD_DECORATORS = frozenset({"property", "cached_property", "staticmethod", "classmethod"})

# Method decorators that declare the class is already an interface without an ABC base.
_INTERFACE_DECORATORS = frozenset({"abstractmethod", "abstractproperty", "overload"})

# Class decorators that bind the class to a declared interface.
_IMPLEMENTS_DECORATORS = frozenset({"implementer", "implementer_only", "provider", "runtime_checkable", "register"})

# Parameter types that only appear on an HTTP route handler.
_HTTP_PARAM_TYPES = frozenset({"Request", "Response", "BackgroundTasks", "WebSocket", "UploadFile"})

# Callables used as FastAPI/Starlette parameter markers, either inside an `Annotated[...]`
_HTTP_PARAM_MARKERS = frozenset({"Header", "Query", "Depends", "Body", "Path", "Form", "File", "Cookie", "Security"})

# Directory segments that hold programs rather than importable library code.
_SCRIPT_DIR_NAMES = frozenset({"scripts", "bin", "tools", "migrations", "alembic", "management", "commands"})

# Directory segments and file stems that hold shared test doubles but are not `tests/`.
_TEST_HELPER_DIRS = frozenset({"testing", "fakes", "mocks", "doubles", "test_fakes", "test_doubles", "test_utils"})
_TEST_HELPER_STEM_RE = re.compile(r"(?:^|_)(?:fakes?|mocks?|stubs?|doubles?|testing)(?:$|_)")

# One public method is a function in a trenchcoat; an ABC over it is ceremony.
_MIN_PUBLIC_METHODS = 2

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class RequirePortForService(Rule):
    id: str = "require-port-for-service"
    code: str = "SARJ071"
    description: str = (
        # `*Client` is NOT in the name gate — it was measured and excluded (7 OSS
        "Concrete `*Service`/`*Store`/`*DAO`/`*Gateway`/`*Provider` with injected collaborators "
        "and no ABC — consumers must depend on the concrete class, so their tests can only mock it."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag service classes that have no abstract base to be substituted through."""
        if not _is_library_source(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        if _has_main_guard(tree):
            return []

        classes: list[ast.ClassDef] = []
        bound_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node)
                bound_names.add(node.name)
            elif isinstance(node, ast.ImportFrom | ast.Import):
                bound_names.update(alias.asname or alias.name.rpartition(".")[2] for alias in node.names)
        data_names = {node.name for node in classes if _is_data_type(node)}

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"`{node.name}` injects `{collaborator}` and exposes {_public_method_count(node)} public "
                    "methods, but has no abstract base, so every consumer has to name the concrete class and "
                    "the only way to test one is to patch or mock it. Extract the public methods onto an "
                    f"`abc.ABC` (or a `Protocol`) and have `{node.name}` implement it, so consumers depend on "
                    "the port and tests can pass a purpose-built implementation instead of a mock — except "
                    "for a `*Store`/`*DAO` persistence port, where tests should drive the real backend "
                    "implementation against the test database rather than an in-memory double."
                ),
            )
            for node in classes
            if (collaborator := _unsubstitutable_service(node, data_names, bound_names)) is not None
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_library_source(path: Path) -> bool:
    """Report whether `path` holds importable production code."""
    if is_test_path(path):
        return False
    parts = set(path.parts)
    if parts & _TEST_HELPER_DIRS or parts & _SCRIPT_DIR_NAMES:
        return False
    return not _TEST_HELPER_STEM_RE.search(path.stem)


def _has_main_guard(tree: ast.Module) -> bool:
    """Report whether the module is its own entry point."""
    return any(
        isinstance(stmt, ast.If)
        and any(isinstance(name, ast.Name) and name.id == "__name__" for name in ast.walk(stmt.test))
        for stmt in tree.body
    )


def _unsubstitutable_service(
    node: ast.ClassDef, data_names: frozenset[str] | set[str], bound_names: frozenset[str] | set[str]
) -> str | None:
    """Decide whether `node` is a service class with no port above it."""
    if node.name.startswith("_") or not _SERVICE_NAME_RE.search(node.name):
        return None
    if _BASE_NAME_RE.match(node.name) or _names_a_port_in_scope(node.name, bound_names):
        return None
    if _has_base(node) or _is_data_type(node) or _declares_interface(node):
        return None
    if _public_method_count(node) < _MIN_PUBLIC_METHODS or _handles_http_requests(node):
        return None
    return _injected_collaborator(node, data_names)


def _handles_http_requests(node: ast.ClassDef) -> bool:
    """Report whether the class's public methods are HTTP route handlers."""
    return any(
        _is_http_parameter(param, default)
        for method in _methods(node)
        if not method.name.startswith("_")
        for param, default in _params_with_defaults(method)
    )


def _params_with_defaults(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[ast.arg, ast.expr | None]]:
    """Pair every parameter of `method` with its default expression."""
    args = method.args
    positional = [*args.posonlyargs, *args.args]
    padding: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    return [
        *zip(positional, [*padding, *args.defaults], strict=True),
        *zip(args.kwonlyargs, args.kw_defaults, strict=True),
    ]


def _is_http_parameter(param: ast.arg, default: ast.expr | None) -> bool:
    """Report whether one parameter belongs to a web framework rather than a domain call."""
    if param.annotation is not None:
        for inner in ast.walk(param.annotation):
            if isinstance(inner, ast.Name | ast.Attribute) and _dotted_tail(inner) in _HTTP_PARAM_TYPES:
                return True
            if isinstance(inner, ast.Call) and _dotted_tail(inner.func) in _HTTP_PARAM_MARKERS:
                return True
    return isinstance(default, ast.Call) and _dotted_tail(default.func) in _HTTP_PARAM_MARKERS


def _names_a_port_in_scope(name: str, bound_names: frozenset[str] | set[str]) -> bool:
    """Report whether the class name is a qualified form of a port already in scope."""
    return any(
        name[index].isupper() and (suffix := name[index:]) in bound_names and bool(_SERVICE_NAME_RE.search(suffix))
        for index in range(1, len(name))
    )


def _has_base(node: ast.ClassDef) -> bool:
    """Report whether the class inherits anything at all."""
    if node.keywords:
        return True
    return any(_dotted_tail(base) != "object" for base in node.bases)


def _is_data_type(node: ast.ClassDef) -> bool:
    """Report whether the class is a record rather than a service."""
    if any(_dotted_tail(dec) in _DATA_DECORATORS for dec in node.decorator_list):
        return True
    return any(_dotted_tail(base) in _DATA_BASES for base in node.bases)


def _declares_interface(node: ast.ClassDef) -> bool:
    """Report whether the class already declares an interface."""
    if any(_dotted_tail(dec) in _IMPLEMENTS_DECORATORS for dec in node.decorator_list):
        return True
    return any(_dotted_tail(dec) in _INTERFACE_DECORATORS for method in _methods(node) for dec in method.decorator_list)


def _methods(node: ast.ClassDef) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [stmt for stmt in node.body if isinstance(stmt, _FUNC_NODES)]


def _public_method_count(node: ast.ClassDef) -> int:
    """Count the instance methods a consumer would call through a port."""
    return sum(
        1
        for method in _methods(node)
        if not method.name.startswith("_")
        and not any(_dotted_tail(dec) in _NON_METHOD_DECORATORS for dec in method.decorator_list)
    )


def _injected_collaborator(node: ast.ClassDef, data_names: frozenset[str] | set[str]) -> str | None:
    """Find a constructor parameter that is a real collaborator stored on `self`."""
    init = next((method for method in _methods(node) if method.name == "__init__"), None)
    if init is None:
        return None
    stored = _self_stored_parameters(init)
    args = init.args
    for param in [*args.posonlyargs, *args.args[1:], *args.kwonlyargs]:
        annotation = _annotation_tail(param.annotation)
        if annotation is None or annotation in _PRIMITIVE_ANNOTATIONS or annotation in data_names:
            continue
        if _WEAK_COLLABORATOR_RE.search(annotation):
            continue
        if param.arg in stored:
            return annotation
    return None


def _self_stored_parameters(init: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect constructor parameters assigned directly to `self`."""
    names: set[str] = set()
    for node in ast.walk(init):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is not None and any(
            isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self"
            for target in targets
        ):
            names.update(_stored_parameter_names(value))
    return names


def _stored_parameter_names(value: ast.expr) -> set[str]:
    """Resolve transparent fallback and typing wrappers around stored parameters."""
    if isinstance(value, ast.Name):
        return {value.id}
    if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
        return {name for item in value.values for name in _stored_parameter_names(item)}
    if isinstance(value, ast.Call) and _dotted_tail(value.func) == "cast":
        cast_values = value.args[1:]
        if cast_values:
            return _stored_parameter_names(cast_values[-1])
    return set()


def _annotation_tail(annotation: ast.expr | None) -> str | None:
    """Reduce an annotation to the identifier that names its type."""
    if annotation is None:
        return None
    if isinstance(annotation, ast.Constant):
        if not isinstance(annotation.value, str):
            return None
        try:
            parsed = ast.parse(annotation.value, mode="eval")
        except SyntaxError, ValueError:
            return None
        return _annotation_tail(parsed.body)
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        for side in (annotation.left, annotation.right):
            tail = _annotation_tail(side)
            if tail is not None and tail != "None":
                return tail
        return None
    if isinstance(annotation, ast.Subscript):
        outer = _dotted_tail(annotation.value)
        if outer not in _TRANSPARENT_GENERICS:
            return outer
        inner = annotation.slice
        if isinstance(inner, ast.Tuple):
            inner = inner.elts[0] if inner.elts else inner
        return _annotation_tail(inner)
    return _dotted_tail(annotation)


def _dotted_tail(node: ast.expr) -> str | None:
    """Reduce an expression to its final identifier."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _dotted_tail(node.value)
    if isinstance(node, ast.Call):
        return _dotted_tail(node.func)
    if isinstance(node, ast.Constant) and node.value is None:
        return "None"
    return None
