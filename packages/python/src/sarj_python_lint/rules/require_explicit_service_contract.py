from __future__ import annotations

import ast
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._imports import ABC_SOURCES, TYPING_SOURCES, ImportIndex
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._service_http_callbacks import http_callback_dispatch
from sarj_python_lint.rules.require_port_for_service import (
    annotation_tail,
    called_self_field,
    class_methods,
    is_data_type,
    self_stored_parameters,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit


_EXECUTOR_CALLBACK_INDEX = 1


@dataclass(frozen=True, slots=True)
class _RetainedCollaborators:
    fields: frozenset[str]
    typed_fields: frozenset[str]


@final
class RequireExplicitServiceContract(ProjectRule):
    id = "require-explicit-service-contract"
    code = "SARJ465"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Require an explicit contract for services that invoke collaborators or perform HTTP operations.",
        rationale=(
            "A one-operation service can orchestrate other services without declaring "
            "the contract that callers consume and implementations and fakes satisfy."
        ),
        remediation=(
            "Declare a focused ABC or Protocol covering the service operations and make that contract explicit "
            "on the implementation; reuse an existing contract instead of adding a nominal duplicate."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Module-level service, store, and provider roles qualify when a public operation invokes a directly retained constructor collaborator. Classes that dispatch retained callbacks through asyncio or issue requests through locally constructed httpx clients also qualify without a role name or directory.",
            "Resolvable inherited ABC and Protocol operations, including private and generic contracts, satisfy this policy; unresolved ancestry is not treated as a missing contract.",
            "Generated code, tests, data values, abstract declarations, descriptors, static/class helpers, and unknown rewriting decorators are excluded.",
            "The bounded analysis follows directly retained constructor parameters and private instance helpers; dynamic field aliases and structurally implemented Protocols declared only by external consumers are not inferred.",
            "An unannotated bare callback factory does not by itself establish a service collaborator. Called collaborator methods and proven native callback dispatch remain in scope.",
            "Executor dispatch requires a directly acquired or uniquely assigned asyncio event loop, or asyncio.to_thread, and an explicit callback argument. Wrapper dispatchers and ambiguous starred arguments are not inferred.",
            "HTTP client construction and request calls require stable native imports and an unescaped local client binding. An awaited typed callback invoked with a locally constructed first-party wrapper also qualifies when its active constructor or entered lifecycle reaches a source-proven native HTTP client factory. This establishes a resource dispatch boundary; the callback's network behavior is not inferred.",
            "First-party wrapper source may be generated, but must belong to the owning distribution or a declared workspace dependency. Unknown third-party wrappers, conditional or decorated lifecycle/helper dispatch, mere construction or cleanup without callback dispatch, mutated or escaped clients, and non-HTTP values abstain.",
            "Method signatures are checked by the type checker. This explicit-contract policy has no automatic rewrite; preserve required framework boundaries with a reasoned exact-code exception.",
        ),
        examples=(
            RuleExample(
                example_id="single-operation-service-without-contract",
                title="One service operation still needs its contract",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "class OrchestratorService:\n"
                        "    def __init__(self, worker: Worker) -> None:\n"
                        "        self.worker = worker\n"
                        "    def run(self) -> None:\n"
                        "        self.worker.run()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="retained-executor-callback-without-contract",
                scenario="executor-dispatch",
                title="Dispatching injected work establishes a service boundary",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/batching.py",
                        "import asyncio\n"
                        "from collections.abc import Callable\n"
                        "class Batcher:\n"
                        "    def __init__(self, operation: Callable[[], None]) -> None:\n"
                        "        self.operation = operation\n"
                        "    async def run(self) -> None:\n"
                        "        await asyncio.get_running_loop().run_in_executor(None, self.operation)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/batching.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="retained-executor-callback-with-contract",
                scenario="executor-dispatch",
                title="The dispatcher declares its public operation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/batching.py",
                        "import asyncio\n"
                        "from collections.abc import Callable\n"
                        "from typing import Protocol\n"
                        "class Operations(Protocol):\n"
                        "    async def run(self) -> None: ...\n"
                        "class Batcher(Operations):\n"
                        "    def __init__(self, operation: Callable[[], None]) -> None:\n"
                        "        self.operation = operation\n"
                        "    async def run(self) -> None:\n"
                        "        await asyncio.get_running_loop().run_in_executor(None, self.operation)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/batching.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="explicit-single-operation-contract",
                title="The service declares its operation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from abc import ABC, abstractmethod\n"
                        "class Runner(ABC):\n"
                        "    @abstractmethod\n"
                        "    def run(self) -> None: ...\n"
                        "class OrchestratorService(Runner):\n"
                        "    def __init__(self, worker: Worker) -> None:\n"
                        "        self.worker = worker\n"
                        "    def run(self) -> None:\n"
                        "        self.worker.run()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="explicit-protocol-contract",
                title="A focused Protocol already supplies the service contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from typing import Protocol\n"
                        "class _Runner(Protocol):\n"
                        "    def run(self) -> None: ...\n"
                        "class OrchestratorService(_Runner):\n"
                        "    def __init__(self, worker: Worker) -> None:\n"
                        "        self.worker = worker\n"
                        "    def run(self) -> None:\n"
                        "        self.worker.run()\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        tree = context.tree
        if tree is None or context.generated or is_test_path(context.path):
            return []
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        diagnostics: list[Diagnostic] = []
        for node in classes.values():
            if (
                node.name.startswith("_")
                or is_data_type(node)
                or not _is_service_role(node, context)
                or not _known_decorators(node.decorator_list, context.imports)
                or _declares_abstract_operations(node, context.imports)
            ):
                continue
            operations = _collaborator_operations(node, context)
            if not operations:
                continue
            if _contract_status(node, operations, classes, context) is not False:
                continue
            start = min((decorator.lineno for decorator in node.decorator_list), default=node.lineno)
            if any(is_suppressed(context.source_lines, line, self.code) for line in range(start, node.lineno + 1)):
                continue
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.ERROR,
                    message=(
                        # Existing baselines fingerprint the diagnostic message.
                        f"`{node.name}` invokes a retained collaborator from "
                        f"{', '.join(sorted(operations))} without a declared ABC or Protocol covering its service operations."
                    ),
                )
            )
        return diagnostics


BOUNDARY_SUFFIXES = (
    "Service",
    "ServiceImpl",
    "Store",
    "Repository",
    "Provider",
    "Executor",
    "Enqueuer",
    "Runner",
    "Platform",
    "Manager",
    "ManagerImpl",
    "Control",
    "Refresher",
    "Reader",
    "Settlement",
    "Retry",
    "Stop",
    "Catalog",
    "DAO",
)
_NON_SERVICE_SUFFIXES = ("Router", "Middleware", "Builder", "Factory")
BOUNDARY_DIRECTORIES = frozenset({"services", "stores", "providers", "repositories"})
_NON_SERVICE_DIRECTORIES = frozenset({"routers", "middleware", "scripts"})
_BUILTIN_VALUES = frozenset(
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
        "list",
        "dict",
        "set",
        "frozenset",
        "tuple",
        "type",
    }
)
_VALUE_SOURCES = frozenset(
    {
        "typing",
        "typing_extensions",
        "collections.abc",
        "pathlib",
        "uuid",
        "datetime",
        "decimal",
        "fractions",
        "re",
        "logging",
    }
)
_IMPORTED_VALUES = frozenset(
    {
        "Any",
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
        "Logger",
    }
)


def _is_service_role(node: ast.ClassDef, context: PythonFileContext) -> bool:
    parts = frozenset(context.path.parts)
    if parts & _NON_SERVICE_DIRECTORIES or node.name.endswith(_NON_SERVICE_SUFFIXES):
        return False
    for keyword in node.keywords:
        if keyword.arg is None:
            return False
        if keyword.arg != "metaclass":
            continue
        if context.imports.resolves(keyword.value, sources=ABC_SOURCES, symbol="ABCMeta"):
            continue
        if (
            isinstance(keyword.value, ast.Name)
            and keyword.value.id == "type"
            and context.imports.builtin_is_unshadowed("type")
        ):
            continue
        return False
    return (
        bool(parts & BOUNDARY_DIRECTORIES)
        or node.name.endswith(BOUNDARY_SUFFIXES)
        or (
            any(marker in context.source for marker in ("run_in_executor", "to_thread", "httpx", "Callable"))
            and bool(_collaborator_operations(node, context, boundary_only=True))
        )
    )


def _collaborator_operations(
    node: ast.ClassDef, context: PythonFileContext, *, boundary_only: bool = False
) -> frozenset[str]:
    constructor = next((method for method in class_methods(node) if method.name == "__init__"), None)
    if constructor is not None and not _known_decorators(constructor.decorator_list, context.imports):
        return frozenset()
    retained = (
        _collaborator_fields(constructor, context)
        if constructor is not None
        else _RetainedCollaborators(frozenset(), frozenset())
    )
    return operations_for_fields(
        node,
        retained.fields,
        context.imports,
        typed_fields=retained.typed_fields,
        boundary_only=boundary_only,
        context=context,
    )


def _collaborator_fields(
    constructor: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext
) -> _RetainedCollaborators:
    stored = self_stored_parameters(constructor, context.imports)
    value_names: set[str] = (
        {item.name for item in context.tree.body if isinstance(item, ast.ClassDef) and is_data_type(item)}
        if context.tree is not None
        else set()
    )
    fields: set[str] = set()
    typed_fields: set[str] = set()
    for parameter in (*constructor.args.posonlyargs, *constructor.args.args, *constructor.args.kwonlyargs):
        if _is_value_parameter(parameter.annotation, context.imports, value_names):
            continue
        fields.update(stored.fields_by_parameter.get(parameter.arg, ()))
        if parameter.annotation is not None:
            typed_fields.update(stored.fields_by_parameter.get(parameter.arg, ()))
    return _RetainedCollaborators(frozenset(fields), frozenset(typed_fields))


def _is_value_parameter(annotation: ast.expr | None, imports: ImportIndex, value_names: set[str]) -> bool:
    name = annotation_tail(annotation)
    if name in value_names:
        return True
    if name is not None and name in _BUILTIN_VALUES and imports.builtin_is_unshadowed(name):
        return True
    reference = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    return reference is not None and imports.resolved_symbol(reference, sources=_VALUE_SOURCES) in _IMPORTED_VALUES


def operations_for_fields(
    node: ast.ClassDef,
    fields: frozenset[str],
    imports: ImportIndex,
    *,
    typed_fields: frozenset[str] | None = None,
    boundary_only: bool = False,
    context: PythonFileContext | None = None,
) -> frozenset[str]:
    if not fields and (context is None or not any(marker in context.source for marker in ("httpx", "Callable"))):
        return frozenset()
    methods = [method for method in class_methods(node) if _instance_operation(method, imports)]
    callers: dict[str, set[str]] = defaultdict(set)
    reaches_collaborator: set[str] = set()
    for method in methods:
        visitor = _CollaboratorCalls(
            fields,
            imports,
            typed_fields=fields if typed_fields is None else typed_fields,
            boundary_only=boundary_only,
            context=context,
        )
        visitor.visit_statements(method.body)
        if visitor.invalidated:
            continue
        if visitor.found:
            reaches_collaborator.add(method.name)
        for callee in visitor.calledclass_methods:
            callers[callee].add(method.name)
    return _reachable_public_operations(methods, callers, reaches_collaborator)


def _reachable_public_operations(
    methods: list[ast.FunctionDef | ast.AsyncFunctionDef],
    callers: dict[str, set[str]],
    reaches_collaborator: set[str],
) -> frozenset[str]:
    pending = deque(reaches_collaborator)
    while pending:
        for caller in callers[pending.popleft()] - reaches_collaborator:
            reaches_collaborator.add(caller)
            pending.append(caller)
    return frozenset(
        method.name for method in methods if not method.name.startswith("_") and method.name in reaches_collaborator
    )


@final
class _CollaboratorCalls(ast.NodeVisitor):
    def __init__(
        self,
        fields: frozenset[str],
        imports: ImportIndex,
        *,
        typed_fields: frozenset[str],
        boundary_only: bool,
        context: PythonFileContext | None,
    ) -> None:
        self.fields = fields
        self.typed_fields = typed_fields
        self.imports = imports
        self.boundary_only = boundary_only
        self.context = context
        self.found = False
        self.invalidated = False
        self.calledclass_methods: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "self" and isinstance(node.ctx, ast.Store | ast.Del):
            self.invalidated = True

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.ctx, ast.Store | ast.Del)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and node.attr in self.fields
        ):
            self.invalidated = True
        self.generic_visit(node)

    def visit_statements(self, statements: list[ast.stmt]) -> bool:
        for statement in statements:
            if isinstance(statement, ast.If):
                self.visit(statement.test)
                if isinstance(statement.test, ast.Constant):
                    branch = statement.body if statement.test.value else statement.orelse
                    falls_through = self.visit_statements(branch)
                else:
                    body_falls_through = self.visit_statements(statement.body)
                    else_falls_through = self.visit_statements(statement.orelse)
                    falls_through = body_falls_through or else_falls_through
                if not falls_through:
                    return False
                continue
            self.visit(statement)
            if isinstance(statement, ast.Return | ast.Raise | ast.Break | ast.Continue):
                return False
        return True

    def visit_Call(self, node: ast.Call) -> None:
        callback = _executor_callback(node, self.imports, self.context)
        if (
            (not self.boundary_only and self._calls_retained(node.func))
            or (callback is not None and called_self_field(callback) in self.fields)
            or _http_boundary_call(node, self.context)
        ):
            self.found = True
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        ):
            self.calledclass_methods.add(node.func.attr)
        self.generic_visit(node)

    def _calls_retained(self, function: ast.expr) -> bool:
        field = called_self_field(function)
        if field not in self.fields:
            return False
        if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
            return field in self.typed_fields
        return True

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_If(self, node: ast.If) -> None:
        self.visit_statements([node])

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        if not isinstance(node.test, ast.Constant) or node.test.value:
            self.visit_statements(node.body)
        self.visit_statements(node.orelse)

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.visit(item.optional_vars)
        self.visit_statements(node.body)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        for value in node.values:
            self.visit(value)
            if not isinstance(value, ast.Constant):
                continue
            if isinstance(node.op, ast.And) and not value.value:
                break
            if isinstance(node.op, ast.Or) and value.value:
                break

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.visit(node.test)
        if isinstance(node.test, ast.Constant):
            self.visit(node.body if node.test.value else node.orelse)
            return
        self.visit(node.body)
        self.visit(node.orelse)

    def visit_Try(self, node: ast.Try) -> None:
        body_falls_through = self.visit_statements(node.body)
        for handler in node.handlers:
            self.visit_statements(handler.body)
        if body_falls_through:
            self.visit_statements(node.orelse)
        self.visit_statements(node.finalbody)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        # Creation evaluates the first iterable, while the generator body is deferred.
        self.visit(node.generators[0].iter)


def _executor_callback(node: ast.Call, imports: ImportIndex, context: PythonFileContext | None) -> ast.expr | None:
    if imports.resolved_qualified_name(node.func) == "asyncio.to_thread":
        return node.args[0] if node.args and not isinstance(node.args[0], ast.Starred) else None
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "run_in_executor":
        return None
    if not _is_asyncio_loop(node.func.value, imports, context):
        return None
    return _run_in_executor_callback(node)


def _is_asyncio_loop(receiver: ast.expr, imports: ImportIndex, context: PythonFileContext | None) -> bool:
    loop: ast.expr | None = receiver
    if isinstance(loop, ast.Name) and context is not None:
        provenance = context.static_resource_provenance
        loop = provenance.constructor(loop, receiver) if provenance.unescaped(loop, receiver) else None
    return (
        isinstance(loop, ast.Call)
        and not loop.args
        and not loop.keywords
        and imports.resolved_qualified_name(loop.func) in {"asyncio.get_running_loop", "asyncio.get_event_loop"}
    )


def _run_in_executor_callback(node: ast.Call) -> ast.expr | None:
    if any(isinstance(argument, ast.Starred) for argument in node.args[: _EXECUTOR_CALLBACK_INDEX + 1]) or any(
        keyword.arg is None for keyword in node.keywords
    ):
        return None
    if len(node.args) > _EXECUTOR_CALLBACK_INDEX:
        return node.args[_EXECUTOR_CALLBACK_INDEX] if all(keyword.arg != "func" for keyword in node.keywords) else None
    if not node.args and all(keyword.arg != "executor" for keyword in node.keywords):
        return None
    return next((keyword.value for keyword in node.keywords if keyword.arg == "func"), None)


_HTTP_OPERATIONS = frozenset({"request", "get", "post", "put", "patch", "delete", "head", "options", "send", "stream"})


def _http_boundary_call(node: ast.Call, context: PythonFileContext | None) -> bool:
    if http_callback_dispatch(node, context):
        return True
    if (
        context is None
        or "httpx" not in context.source
        or not isinstance(node.func, ast.Attribute)
        or node.func.attr not in _HTTP_OPERATIONS
        or not isinstance(node.func.value, ast.Name)
    ):
        return False
    receiver = node.func.value
    provenance = context.static_resource_provenance
    constructor = provenance.constructor(receiver, node)
    return (
        constructor is not None
        and provenance.runtime_import_name(constructor.func) in {"httpx.Client", "httpx.AsyncClient"}
        and provenance.unescaped(receiver, node, allow_context=True)
    )


def _known_decorators(decorators: list[ast.expr], imports: ImportIndex) -> bool:
    return all(
        imports.resolved_symbol(decorator, sources=TYPING_SOURCES) in {"final", "override", "runtime_checkable"}
        or imports.resolves(decorator, sources=ABC_SOURCES, symbol="abstractmethod")
        for decorator in decorators
    )


def _instance_operation(method: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> bool:
    positional = [*method.args.posonlyargs, *method.args.args]
    return bool(positional) and positional[0].arg == "self" and _known_decorators(method.decorator_list, imports)


def _declares_abstract_operations(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return any(
        imports.resolves(decorator, sources=ABC_SOURCES, symbol="abstractmethod")
        for method in class_methods(node)
        for decorator in method.decorator_list
    )


def _declares_contract(node: ast.ClassDef, imports: ImportIndex) -> bool:
    bases = [base.value if isinstance(base, ast.Subscript) else base for base in node.bases]
    return any(
        imports.resolves(base, sources=ABC_SOURCES, symbol="ABC")
        or imports.resolves(base, sources=TYPING_SOURCES, symbol="Protocol")
        for base in bases
    ) or any(
        keyword.arg == "metaclass" and imports.resolves(keyword.value, sources=ABC_SOURCES, symbol="ABCMeta")
        for keyword in node.keywords
    )


def _neutral_base(base: ast.expr, imports: ImportIndex) -> bool:
    if isinstance(base, ast.Name) and base.id == "object" and imports.builtin_is_unshadowed("object"):
        return True
    return imports.resolves(base, sources=ABC_SOURCES, symbol="ABC") or imports.resolved_symbol(
        base, sources=TYPING_SOURCES
    ) in {"Generic", "Protocol"}


def _contract_status(
    node: ast.ClassDef,
    operations: frozenset[str],
    classes: dict[str, ast.ClassDef],
    context: PythonFileContext,
) -> bool | None:
    surfaces: set[str] = set()
    unknown = False
    project = context.session.project
    unit = project.unit(context.path) if project is not None else None
    for expression in node.bases:
        base = expression.value if isinstance(expression, ast.Subscript) else expression
        if _neutral_base(base, context.imports):
            continue
        resolved = _resolve_base(base, classes, context.imports, project, unit)
        if resolved is None:
            unknown = True
            continue
        declaration, source_unit, source_imports = resolved
        contract = _contract_surface(declaration, source_unit, source_imports, project, set(), classes=classes)
        surfaces.update(contract.operations)
        unknown |= contract.unresolved
    return True if operations <= surfaces else None if unknown else False


def _resolve_base(
    base: ast.expr,
    classes: dict[str, ast.ClassDef],
    imports: ImportIndex,
    project: ProjectIndexSet | None,
    unit: SourceUnit | None,
) -> tuple[ast.ClassDef, SourceUnit | None, ImportIndex] | None:
    base = base.value if isinstance(base, ast.Subscript) else base
    if isinstance(base, ast.Name) and base.id in classes:
        return classes[base.id], unit, imports
    if project is None or unit is None:
        return None
    summary = project.class_for(unit, base)
    if summary is None:
        return None
    stable = imports.resolved_qualified_name(base)
    if stable != f"{summary.symbol.module}.{summary.symbol.name}":
        return None
    source_unit = project.source_unit(summary.symbol.module)
    if source_unit is None or source_unit.tree is None:
        return None
    declaration = next(
        (item for item in source_unit.tree.body if isinstance(item, ast.ClassDef) and item.name == summary.symbol.name),
        None,
    )
    if declaration is None:
        return None
    return declaration, source_unit, ImportIndex.from_tree(source_unit.tree, module_scope_only=True)


@dataclass(frozen=True)
class _ContractSurface:
    operations: frozenset[str]
    unresolved: bool


def _contract_surface(
    declaration: ast.ClassDef,
    unit: SourceUnit | None,
    imports: ImportIndex,
    project: ProjectIndexSet | None,
    seen: set[ast.ClassDef],
    *,
    classes: dict[str, ast.ClassDef],
) -> _ContractSurface:
    if declaration in seen or not _known_decorators(declaration.decorator_list, imports):
        return _ContractSurface(operations=frozenset(), unresolved=True)
    seen.add(declaration)
    bases = [base.value if isinstance(base, ast.Subscript) else base for base in declaration.bases]
    surface: set[str] = _public_operations(declaration, imports) if _declares_contract(declaration, imports) else set()
    unknown = False
    local_classes = (
        {item.name: item for item in unit.tree.body if isinstance(item, ast.ClassDef)}
        if unit is not None and unit.tree is not None
        else classes
    )
    for base in bases:
        if _neutral_base(base, imports):
            continue
        resolved = _resolve_base(base, local_classes, imports, project, unit)
        if resolved is None:
            unknown = True
            continue
        ancestor, ancestor_unit, ancestor_imports = resolved
        ancestor_surface = _contract_surface(
            ancestor, ancestor_unit, ancestor_imports, project, seen.copy(), classes=local_classes
        )
        surface.update(ancestor_surface.operations)
        unknown |= ancestor_surface.unresolved
    if surface and _declares_abstract_operations(declaration, imports):
        surface.update(_public_operations(declaration, imports))
    return _ContractSurface(operations=frozenset(surface), unresolved=unknown)


def _public_operations(declaration: ast.ClassDef, imports: ImportIndex) -> set[str]:
    return {
        method.name
        for method in class_methods(declaration)
        if not method.name.startswith("_") and _instance_operation(method, imports)
    }
