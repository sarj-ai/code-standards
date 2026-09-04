from __future__ import annotations

import ast
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path, PurePosixPath
import re
from typing import ClassVar, NamedTuple, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


# Name tails that mark a class as a service in this codebase's own vocabulary.
_SERVICE_NAME_RE = re.compile(r"(?:Service|Store|DAO|Dao|Gateway|Provider)$")
_SERVICE_CLASS_RE = re.compile(r"\bclass\s+\w+(?:Service|Store|DAO|Dao|Gateway|Provider)\b")


class _ParameterDefault(NamedTuple):
    parameter: ast.arg
    default: ast.expr | None


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
        "Literal",
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
_UNSUPPORTED_COMPOUND_STATEMENTS = (
    ast.For,
    ast.AsyncFor,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.TryStar,
    ast.Match,
)
_FRAMEWORK_METHOD_DECORATORS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "websocket", "command", "group"}
)
_CAST_SOURCES = frozenset({"typing", "typing_extensions"})


class RequirePortForService(Rule):
    id: str = "require-port-for-service"
    code: str = "SARJ071"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Consider a consumer-owned port when visible service structure suggests a substitution boundary.",
        rationale="A small port can decouple consumers when they genuinely need to substitute a concrete service boundary.",
        remediation=(
            "When a real consumer needs substitution, define a focused consumer-owned `Protocol` and type that "
            "consumer against it; otherwise suppress the advisory instead of adding an unused abstraction."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This advisory uses service-family names, constructor annotations, collaborator calls, and public-method counts as heuristics.",
            "Only direct module classes are checked; tests, generated code, scripts, framework callbacks, Store/Repository persistence dependencies, and external or interface-like bases are excluded.",
            "The file-local rule cannot prove cross-module consumers or substitution needs, so it remains a warning; a port owned in another module may require an exact suppression on the implementation.",
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
                        "        self.client.put(key, value)\n\n"
                        "def sync(service: ThingService) -> None:\n"
                        "    service.write('inbox', service.read('outbox'))\n",
                    ),
                ),
                focus_path=PurePosixPath("app/services/thing_service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-service-port",
                title="A visible structural port already describes the service boundary",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/services/thing_service.py",
                        "from typing import Protocol\n\n"
                        "class ThingServicePort(Protocol):\n"
                        "    def read(self, key: str) -> str: ...\n"
                        "    def write(self, key: str, value: str) -> None: ...\n\n"
                        "class ThingService:\n"
                        "    def __init__(self, client: ThingClient) -> None:\n"
                        "        self.client = client\n\n"
                        "    def read(self, key: str) -> str:\n"
                        "        return self.client.get(key)\n\n"
                        "    def write(self, key: str, value: str) -> None:\n"
                        "        self.client.put(key, value)\n\n"
                        "def sync(service: ThingServicePort) -> None:\n"
                        "    service.write('inbox', service.read('outbox'))\n",
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
        if (
            not _is_library_source(path)
            or is_generated(path, source)
            or "__init__" not in source
            or _SERVICE_CLASS_RE.search(source) is None
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        if _has_main_guard(tree):
            return []

        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        bound_names: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                bound_names.add(node.name)
            elif isinstance(node, ast.ImportFrom | ast.Import):
                bound_names.update(alias.asname or alias.name.rpartition(".")[2] for alias in node.names)
        imports = ImportIndex.from_tree(tree)
        source_lines = source.splitlines()
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
                severity=Severity.WARNING,
                message=(
                    f"`{node.name}` injects `{collaborator}` and exposes {_public_method_count(node)} public "
                    "methods with no recognizable in-file or inherited port. If a real consumer needs "
                    "substitution, define a small consumer-owned `Protocol` and type that consumer against it; "
                    "otherwise suppress this advisory instead of adding an unused abstraction."
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
                    imports=imports,
                )
            )
            is not None
            and not _class_is_suppressed(node, source_lines, self.code)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _is_library_source(path: Path) -> bool:
    if is_test_path(path) or is_test_support_path(path):
        return False
    parts = _repository_relative_parts(path)
    if parts and parts[0] in _TOP_LEVEL_SCRIPT_DIR_NAMES:
        return False
    if any(part in _MIGRATION_DIR_NAMES for part in parts):
        return False
    return not any(left == "management" and right == "commands" for left, right in pairwise(parts))


def _repository_relative_parts(path: Path) -> tuple[str, ...]:
    if not path.is_absolute():
        return path.parts
    for parent in path.parents:
        if (parent / ".git").exists():
            return path.relative_to(parent).parts
    return path.parts


def _has_main_guard(tree: ast.Module) -> bool:
    for stmt in tree.body:
        if not isinstance(stmt, ast.If):
            continue
        match stmt.test:
            case (
                ast.Compare(
                    left=ast.Name(id="__name__"),
                    ops=[ast.Eq()],
                    comparators=[ast.Constant(value="__main__")],
                )
                | ast.Compare(
                    left=ast.Constant(value="__main__"),
                    ops=[ast.Eq()],
                    comparators=[ast.Name(id="__name__")],
                )
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
    *,
    imports: ImportIndex,
) -> str | None:
    if node.name.startswith("_") or not _SERVICE_NAME_RE.search(node.name):
        return None
    if (
        _BASE_NAME_RE.match(node.name)
        or _names_a_port_in_scope(node.name, bound_names)
        or f"{node.name}Port" in local_port_names
    ):
        return None
    if _has_base(node, local_class_names, local_port_names) or _is_data_type(node) or _declares_interface(node):
        return None
    if (
        _public_method_count(node) < _MIN_PUBLIC_METHODS
        or _handles_http_requests(node)
        or _has_framework_callback_method(node)
    ):
        return None
    return _injected_collaborator(node, data_names, imports)


def _has_framework_callback_method(node: ast.ClassDef) -> bool:
    return any(
        isinstance(target := decorator.func if isinstance(decorator, ast.Call) else decorator, ast.Attribute)
        and target.attr in _FRAMEWORK_METHOD_DECORATORS
        for method in _methods(node)
        if not method.name.startswith("_")
        for decorator in method.decorator_list
    )


def _handles_http_requests(node: ast.ClassDef) -> bool:
    return any(
        _is_http_parameter(param, default)
        for method in _methods(node)
        if not method.name.startswith("_")
        for param, default in _params_with_defaults(method)
    )


def _params_with_defaults(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[_ParameterDefault]:
    args = method.args
    positional = [*args.posonlyargs, *args.args]
    padding: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    return [
        *map(_ParameterDefault, positional, [*padding, *args.defaults], strict=True),
        *map(_ParameterDefault, args.kwonlyargs, args.kw_defaults, strict=True),
    ]


def _is_http_parameter(param: ast.arg, default: ast.expr | None) -> bool:
    if param.annotation is not None:
        for inner in ast.walk(param.annotation):
            if isinstance(inner, ast.Name | ast.Attribute) and _dotted_tail(inner) in _HTTP_PARAM_TYPES:
                return True
            if isinstance(inner, ast.Call) and _dotted_tail(inner.func) in _HTTP_PARAM_MARKERS:
                return True
    return isinstance(default, ast.Call) and _dotted_tail(default.func) in _HTTP_PARAM_MARKERS


def _names_a_port_in_scope(name: str, bound_names: frozenset[str] | set[str]) -> bool:
    return any(
        name[index].isupper()
        and (suffix := name[index:]) in bound_names
        and _SERVICE_NAME_RE.fullmatch(suffix) is None
        and bool(_SERVICE_NAME_RE.search(suffix))
        for index in range(1, len(name))
    )


def _has_base(
    node: ast.ClassDef,
    local_class_names: frozenset[str] | set[str],
    local_port_names: frozenset[str] | set[str],
) -> bool:
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
    if any(_dotted_tail(dec) in _DATA_DECORATORS for dec in node.decorator_list):
        return True
    return any(_dotted_tail(base) in _DATA_BASES for base in node.bases)


def _declares_interface(node: ast.ClassDef) -> bool:
    if any(_dotted_tail(dec) in _IMPLEMENTS_DECORATORS for dec in node.decorator_list):
        return True
    return any(_dotted_tail(dec) in _INTERFACE_DECORATORS for method in _methods(node) for dec in method.decorator_list)


def _methods(node: ast.ClassDef) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [stmt for stmt in node.body if isinstance(stmt, _FUNC_NODES)]


def _public_method_count(node: ast.ClassDef) -> int:
    return sum(
        1
        for method in _methods(node)
        if not method.name.startswith("_")
        and not any(_dotted_tail(dec) in _NON_METHOD_DECORATORS for dec in method.decorator_list)
    )


def _injected_collaborator(
    node: ast.ClassDef,
    data_names: frozenset[str] | set[str],
    imports: ImportIndex,
) -> str | None:
    init = next((method for method in _methods(node) if method.name == "__init__"), None)
    if init is None:
        return None
    stored_parameters = _self_stored_parameters(init, imports)
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
    imports: ImportIndex,
) -> _StoredParameters:
    fields_by_parameter: dict[str, set[str]] = {}
    fallback_stored: set[str] = set()
    overwritten_fields: set[str] = set()
    field_write_counts: dict[str, int] = {}
    stack: list[ast.stmt] = list(reversed(init.body))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Return | ast.Raise):
            break
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant):
            branch = node.body if bool(node.test.value) else node.orelse
            stack.extend(reversed(branch))
            continue
        if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and not bool(node.test.value):
            stack.extend(reversed(node.orelse))
            continue
        if isinstance(node, (ast.If, ast.While, *_UNSUPPORTED_COMPOUND_STATEMENTS)):
            return _StoredParameters({}, frozenset())
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
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
        for field in fields:
            field_write_counts[field] = field_write_counts.get(field, 0) + 1
        parameters = _stored_parameter_names(value, imports)
        if not parameters:
            overwritten_fields.update(fields)
        for parameter in parameters:
            fields_by_parameter.setdefault(parameter, set()).update(fields)
        fallback_stored.update(_fallback_parameter_names(value, imports))
    return _StoredParameters(
        {
            parameter: frozenset(field for field in fields - overwritten_fields if field_write_counts[field] == 1)
            for parameter, fields in fields_by_parameter.items()
            if any(field not in overwritten_fields and field_write_counts[field] == 1 for field in fields)
        },
        frozenset(fallback_stored),
    )


def _stored_parameter_names(value: ast.expr, imports: ImportIndex) -> set[str]:
    if isinstance(value, ast.Name):
        return {value.id}
    if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
        return {name for item in value.values for name in _stored_parameter_names(item, imports)}
    if isinstance(value, ast.Call) and imports.resolves(value.func, sources=_CAST_SOURCES, symbol="cast"):
        cast_values = value.args[1:]
        if cast_values:
            return _stored_parameter_names(cast_values[-1], imports)
    return set()


def _fallback_parameter_names(value: ast.expr, imports: ImportIndex) -> set[str]:
    if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
        return _stored_parameter_names(value, imports)
    if isinstance(value, ast.Call) and imports.resolves(value.func, sources=_CAST_SOURCES, symbol="cast"):
        cast_values = value.args[1:]
        if cast_values:
            return _fallback_parameter_names(cast_values[-1], imports)
    return set()


def _annotation_allows_none(annotation: ast.expr | None) -> bool:
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
    if _has_unsupported_control_flow(method.body):
        return False
    found, _falls_through = _statements_invoke_field(method.body, fields)
    return found


def _has_unsupported_control_flow(statements: list[ast.stmt]) -> bool:
    stack = list(statements)
    while stack:
        statement = stack.pop()
        if isinstance(statement, (ast.While, *_UNSUPPORTED_COMPOUND_STATEMENTS)):
            return True
        if isinstance(statement, ast.If):
            stack.extend(statement.body)
            stack.extend(statement.orelse)
    return False


def _statements_invoke_field(statements: list[ast.stmt], fields: frozenset[str]) -> tuple[bool, bool]:
    for statement in statements:
        if isinstance(statement, ast.If):
            if _node_invokes_field(statement.test, fields):
                return True, True
            if isinstance(statement.test, ast.Constant):
                branch = statement.body if bool(statement.test.value) else statement.orelse
                found, falls_through = _statements_invoke_field(branch, fields)
            else:
                body_found, body_falls = _statements_invoke_field(statement.body, fields)
                else_found, else_falls = _statements_invoke_field(statement.orelse, fields)
                found, falls_through = body_found or else_found, body_falls or else_falls
            if found or not falls_through:
                return found, falls_through
            continue
        if (
            isinstance(statement, ast.While)
            and isinstance(statement.test, ast.Constant)
            and not bool(statement.test.value)
        ):
            found, falls_through = _statements_invoke_field(statement.orelse, fields)
            if found or not falls_through:
                return found, falls_through
            continue
        if isinstance(statement, (ast.While, *_UNSUPPORTED_COMPOUND_STATEMENTS)):
            continue
        if _node_invokes_field(statement, fields):
            return True, True
        if isinstance(statement, ast.Return | ast.Raise):
            return False, False
    return False, True


def _node_invokes_field(node: ast.AST, fields: frozenset[str]) -> bool:
    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Lambda,
            ast.ListComp,
            ast.SetComp,
            ast.DictComp,
            ast.GeneratorExp,
        ),
    ):
        return False
    if isinstance(node, ast.Call) and _called_self_field(node.func) in fields:
        return True
    if isinstance(node, ast.Compare) and len(node.ops) > 1:
        return False
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            if _node_invokes_field(value, fields):
                return True
            truth = _static_truth(value)
            if isinstance(node.op, ast.And) and truth is False:
                break
            if isinstance(node.op, ast.Or) and truth is True:
                break
        return False
    if isinstance(node, ast.IfExp) and (truth := _static_truth(node.test)) is not None:
        branch = node.body if truth else node.orelse
        return _node_invokes_field(branch, fields)
    return any(
        _node_invokes_field(child, fields)
        for child in ast.iter_child_nodes(node)
        if not isinstance(child, ast.stmt | ast.ExceptHandler)
    )


def _static_truth(node: ast.AST) -> bool | None:
    match node:
        case ast.Constant(value=value):
            return bool(value)
        case ast.Tuple(elts=items) | ast.List(elts=items) | ast.Set(elts=items):
            return bool(items)
        case ast.Dict(keys=keys):
            return bool(keys)
        case ast.UnaryOp(op=ast.Not(), operand=operand):
            truth = _static_truth(operand)
            return None if truth is None else not truth
        case ast.BoolOp(op=operator, values=values):
            truths = [_static_truth(value) for value in values]
            if isinstance(operator, ast.And):
                if False in truths:
                    return False
                return True if all(truth is True for truth in truths) else None
            if True in truths:
                return True
            return False if all(truth is False for truth in truths) else None
        case _:
            return None


def _called_self_field(func: ast.expr) -> str | None:
    current = func
    while isinstance(current, ast.Attribute):
        if isinstance(current.value, ast.Name) and current.value.id == "self":
            return current.attr
        current = current.value
    return None


def _class_is_suppressed(node: ast.ClassDef, source_lines: list[str], code: str) -> bool:
    start = min((decorator.lineno for decorator in node.decorator_list), default=node.lineno)
    return any(is_suppressed(source_lines, line, code) for line in range(start, node.lineno + 1))


def _annotation_tail(annotation: ast.expr | None) -> str | None:
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
