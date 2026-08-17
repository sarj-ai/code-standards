"""SARJ071 — Advise when a concrete service may benefit from a consumer-owned port.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_require_port_for_service.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path, PurePosixPath
import re
from typing import ClassVar, override

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
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


# Name tails that mark a class as a service in this codebase's own vocabulary.
_SERVICE_NAME_RE = re.compile(r"(?:Service|Store|DAO|Dao|Gateway|Provider)$")


@dataclass(frozen=True, slots=True)
class _StoredParameters:
    fields_by_parameter: dict[str, frozenset[str]]
    fallback_stored: frozenset[str]


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

# Injected types that are configuration, measurements, or ambient runtime, not a
# substitutable collaborator: nobody swaps `ServerSettings` or `ViewportSize` in a test.
_WEAK_COLLABORATOR_RE = re.compile(r"(?:Settings|Config|Configuration|Options|Logger|Log|Clock|Context|Size)$")

# Runtime driver handles are implementation details of an adapter, not a port
# that consumers substitute through.
_DRIVER_HANDLE_ANNOTATIONS = frozenset(
    {
        "AsyncClient",
        "AsyncConnection",
        "AsyncConnectionPool",
        "AsyncEngine",
        "AsyncRedis",
        "AsyncSession",
        "Client",
        "Connection",
        "ConnectionPool",
        "Engine",
        "Pool",
        "Redis",
        "Session",
    }
)

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
_INTERFACE_DECORATORS = frozenset({"abstractmethod", "abstractproperty"})

# Class decorators that bind the class to a declared interface.
_IMPLEMENTS_DECORATORS = frozenset({"implementer", "implementer_only", "provider", "runtime_checkable", "register"})

# Parameter types that only appear on an HTTP route handler.
_HTTP_PARAM_TYPES = frozenset({"Request", "Response", "BackgroundTasks", "WebSocket", "UploadFile"})

# Callables used as FastAPI/Starlette parameter markers, either inside an `Annotated[...]`
_HTTP_PARAM_MARKERS = frozenset({"Header", "Query", "Depends", "Body", "Path", "Form", "File", "Cookie", "Security"})

# Directory segments that hold programs rather than importable library code.
_TOP_LEVEL_SCRIPT_DIR_NAMES = frozenset({"scripts", "bin", "tools"})
_MIGRATION_DIR_NAMES = frozenset({"migrations", "alembic"})

# One public method is a function in a trenchcoat; an ABC over it is ceremony.
_MIN_PUBLIC_METHODS = 2

# A store/repository-backed application service is ordinary layering, not
# evidence that consumers also need a second abstraction over the service.
_PERSISTENCE_DEPENDENCY_RE = re.compile(r"(?:Store|Repository|Repo)$")

# A collaborator must drive more than one operation before a service-level
# substitution boundary is worth suggesting.
_MIN_COLLABORATOR_METHODS = 2

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


class RequirePortForService(Rule):
    id: str = "require-port-for-service"
    code: str = "SARJ071"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Consider a consumer-owned port for a service with a behaviorally used collaborator.",
        rationale="A small port can decouple consumers when they genuinely need to substitute a concrete service boundary.",
        remediation="Define a focused `Protocol` or ABC and type substituting consumers against it, or suppress the advisory when no substitution boundary exists.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This advisory uses service-family names, constructor annotations, collaborator calls, and public-method counts as heuristics.",
            "Tests, generated code, scripts, known framework shapes, persistence-only dependencies, and classes with declared bases are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="concrete-service-boundary",
                title="Concrete service directly exposes an injected collaborator",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/services/thing_service.py",
                        "class ThingService:\n"
                        "    def __init__(self, client: ThingClient) -> None:\n"
                        "        self.client = client\n\n"
                        "    def read(self, key: str) -> str:\n"
                        "        return self.client.get(key)\n\n"
                        "    def write(self, key: str, value: str) -> None:\n"
                        "        self.client.put(key, value)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/services/thing_service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-service-port",
                title="Service implements a declared port",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/services/thing_service.py",
                        "class ThingService(ThingServicePort):\n"
                        "    def __init__(self, client: ThingClient) -> None:\n"
                        "        self.client = client\n\n"
                        "    def read(self, key: str) -> str:\n"
                        "        return self.client.get(key)\n\n"
                        "    def write(self, key: str, value: str) -> None:\n"
                        "        self.client.put(key, value)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/services/thing_service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

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
        local_class_names = {node.name for node in classes}
        local_port_names = {
            node.name
            for node in classes
            if _BASE_NAME_RE.match(node.name)
            or _declares_interface(node)
            or any(_dotted_tail(base) in {"ABC", "Protocol"} for base in node.bases)
            or any(keyword.arg == "metaclass" and _dotted_tail(keyword.value) == "ABCMeta" for keyword in node.keywords)
        }
        for _round in range(len(classes)):
            grown = {
                node.name
                for node in classes
                if node.name not in local_port_names
                and any(_dotted_tail(base) in local_port_names for base in node.bases)
            }
            if not grown:
                break
            local_port_names |= grown

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"`{node.name}` injects `{collaborator}` and exposes {_public_method_count(node)} public "
                    "methods without a declared port. If consumers genuinely need substitution, define a "
                    "small consumer-owned `Protocol`/ABC and type those consumers against it. Do not add a "
                    "port solely for a composition root or a single concrete consumer."
                ),
            )
            for node in classes
            if (
                collaborator := _unsubstitutable_service(
                    node,
                    data_names,
                    bound_names,
                    local_class_names,
                    local_port_names,
                )
            )
            is not None
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_library_source(path: Path) -> bool:
    """Report whether `path` holds importable production code."""
    if is_test_path(path) or is_test_support_path(path):
        return False
    parts = _repository_relative_parts(path)
    if parts and parts[0] in _TOP_LEVEL_SCRIPT_DIR_NAMES:
        return False
    if any(part in _MIGRATION_DIR_NAMES for part in parts):
        return False
    return not any(left == "management" and right == "commands" for left, right in pairwise(parts))


def _repository_relative_parts(path: Path) -> tuple[str, ...]:
    """Use checkout-relative parts when an absolute corpus path is available."""
    if not path.is_absolute():
        return path.parts
    for parent in path.parents:
        if (parent / ".git").exists():
            return path.relative_to(parent).parts
    return path.parts


def _has_main_guard(tree: ast.Module) -> bool:
    """Report whether the module is its own entry point."""
    for stmt in tree.body:
        if not isinstance(stmt, ast.If):
            continue
        match stmt.test:
            case ast.Compare(
                left=ast.Name(id="__name__"),
                ops=[ast.Eq()],
                comparators=[ast.Constant(value="__main__")],
            ):
                return True
            case _:
                continue
    return False


def _unsubstitutable_service(
    node: ast.ClassDef,
    data_names: frozenset[str] | set[str],
    bound_names: frozenset[str] | set[str],
    local_class_names: frozenset[str] | set[str],
    local_port_names: frozenset[str] | set[str],
) -> str | None:
    """Decide whether `node` is a service class with no port above it."""
    if node.name.startswith("_") or not _SERVICE_NAME_RE.search(node.name):
        return None
    if _BASE_NAME_RE.match(node.name) or _names_a_port_in_scope(node.name, bound_names):
        return None
    if _has_base(node, local_class_names, local_port_names) or _is_data_type(node) or _declares_interface(node):
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


def _has_base(
    node: ast.ClassDef,
    local_class_names: frozenset[str] | set[str],
    local_port_names: frozenset[str] | set[str],
) -> bool:
    """Report whether the class inherits a real port or an unknown external/framework base."""
    if any(keyword.arg == "metaclass" and _dotted_tail(keyword.value) == "ABCMeta" for keyword in node.keywords):
        return True
    for base in node.bases:
        name = _dotted_tail(base)
        if name in {None, "object"}:
            continue
        if name == "Generic":
            continue
        if name in local_class_names:
            if name in local_port_names:
                return True
            continue
        return True
    return False


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
    """Find a required collaborator that drives a meaningful public surface."""
    init = next((method for method in _methods(node) if method.name == "__init__"), None)
    if init is None:
        return None
    stored_parameters = _self_stored_parameters(init)
    candidates: list[tuple[str, frozenset[str]]] = []
    for param, default in _params_with_defaults(init):
        if param.arg == "self":
            continue
        annotation = _annotation_tail(param.annotation)
        if (
            annotation is None
            or annotation in _PRIMITIVE_ANNOTATIONS
            or annotation in _DRIVER_HANDLE_ANNOTATIONS
            or annotation in data_names
        ):
            continue
        if _WEAK_COLLABORATOR_RE.search(annotation):
            continue
        fields = stored_parameters.fields_by_parameter.get(param.arg)
        if fields is None or default is not None or _annotation_allows_none(param.annotation):
            continue
        if param.arg in stored_parameters.fallback_stored:
            continue
        if _PERSISTENCE_DEPENDENCY_RE.search(annotation):
            return None
        candidates.append((annotation, fields))
    for annotation, fields in candidates:
        if _behavioral_public_method_count(node, fields) >= _MIN_COLLABORATOR_METHODS:
            return annotation
    return None


def _self_stored_parameters(
    init: ast.FunctionDef | ast.AsyncFunctionDef,
) -> _StoredParameters:
    """Map constructor parameters to fields, recording fallback storage."""
    fields_by_parameter: dict[str, set[str]] = {}
    fallback_stored: set[str] = set()
    stack: list[ast.AST] = list(init.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            stack.extend(ast.iter_child_nodes(node))
            continue
        if value is None:
            continue
        fields = {
            target.attr
            for target in targets
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self"
        }
        if not fields:
            continue
        for parameter in _stored_parameter_names(value):
            fields_by_parameter.setdefault(parameter, set()).update(fields)
        fallback_stored.update(_fallback_parameter_names(value))
    return _StoredParameters(
        {parameter: frozenset(fields) for parameter, fields in fields_by_parameter.items()},
        frozenset(fallback_stored),
    )


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


def _fallback_parameter_names(value: ast.expr) -> set[str]:
    """Collect parameters retained through an implementation fallback."""
    if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
        return _stored_parameter_names(value)
    if isinstance(value, ast.Call) and _dotted_tail(value.func) == "cast":
        cast_values = value.args[1:]
        if cast_values:
            return _fallback_parameter_names(cast_values[-1])
    return set()


def _annotation_allows_none(annotation: ast.expr | None) -> bool:
    """Report whether an annotation explicitly permits absence."""
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant):
        if annotation.value is None:
            return True
        if isinstance(annotation.value, str):
            try:
                return _annotation_allows_none(ast.parse(annotation.value, mode="eval").body)
            except SyntaxError, ValueError:
                return False
        return False
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _annotation_allows_none(annotation.left) or _annotation_allows_none(annotation.right)
    if isinstance(annotation, ast.Subscript):
        outer = _dotted_tail(annotation.value)
        if outer == "Optional":
            return True
        if outer == "Annotated":
            inner = annotation.slice.elts[0] if isinstance(annotation.slice, ast.Tuple) else annotation.slice
            return _annotation_allows_none(inner)
        if outer == "Union":
            members = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
            return any(_annotation_allows_none(member) for member in members)
    return False


def _behavioral_public_method_count(node: ast.ClassDef, fields: frozenset[str]) -> int:
    """Count public methods that invoke a retained collaborator field."""
    return sum(
        _method_invokes_field(method, fields)
        for method in _methods(node)
        if method.name != "__init__"
        and not method.name.startswith("_")
        and not any(_dotted_tail(dec) in _NON_METHOD_DECORATORS for dec in method.decorator_list)
    )


def _method_invokes_field(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    fields: frozenset[str],
) -> bool:
    """Report a direct `self.field(...)` or `self.field.method(...)` call."""
    stack: list[ast.AST] = list(method.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(current, ast.Call) and _called_self_field(current.func) in fields:
            return True
        stack.extend(ast.iter_child_nodes(current))
    return False


def _called_self_field(func: ast.expr) -> str | None:
    """Resolve the retained field in one-level collaborator calls."""
    if not isinstance(func, ast.Attribute):
        return None
    receiver = func.value
    if isinstance(receiver, ast.Name) and receiver.id == "self":
        return func.attr
    if isinstance(receiver, ast.Attribute) and isinstance(receiver.value, ast.Name) and receiver.value.id == "self":
        return receiver.attr
    return None


def _annotation_tail(annotation: ast.expr | None) -> str | None:
    """Reduce an annotation to the identifier that names its type."""
    match annotation:
        case None:
            return None
        case ast.Constant(value=str() as value):
            try:
                parsed = ast.parse(value, mode="eval")
            except SyntaxError, ValueError:
                return None
            return _annotation_tail(parsed.body)
        case ast.Constant():
            return None
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            for side in (left, right):
                tail = _annotation_tail(side)
                if tail is not None and tail != "None":
                    return tail
            return None
        case ast.Subscript(value=value, slice=inner):
            outer = _dotted_tail(value)
            if outer not in _TRANSPARENT_GENERICS:
                return outer
            if isinstance(inner, ast.Tuple):
                inner = inner.elts[0] if inner.elts else inner
            return _annotation_tail(inner)
        case _:
            return _dotted_tail(annotation)


def _dotted_tail(node: ast.expr) -> str | None:
    """Reduce an expression to its final identifier."""
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=attr):
            return attr
        case ast.Subscript(value=value):
            return _dotted_tail(value)
        case ast.Call(func=func):
            return _dotted_tail(func)
        case ast.Constant(value=None):
            return "None"
        case _:
            return None
