from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext


_PUBLIC_EMITTERS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "log"})
_MODULE_EMITTERS = frozenset("logging." + name for name in _PUBLIC_EMITTERS)
_LOGGER_FACTORIES = frozenset({"logging.getLogger", "logging.Logger"})
_BUILTIN_SINKS = frozenset({"logging.StreamHandler", "logging.FileHandler"})
_ROUTING_ATTRIBUTES = frozenset({"handlers", "filters", "level", "disabled", "propagate", "name"})
_ROUTING_METHODS = frozenset(
    {
        "setLevel",
        "addHandler",
        "removeHandler",
        "addFilter",
        "removeFilter",
        "isEnabledFor",
        "getEffectiveLevel",
        "hasHandlers",
    }
)
_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_MAX_SOURCE_CHARACTERS = 500_000
_MIN_ATTRIBUTE_MUTATION_ARGS = 2


@dataclass(frozen=True, slots=True)
class ApplicationLoggingUse:
    line: int
    column: int
    operation: str
    kind: Literal["event", "sink"]


@dataclass(frozen=True, slots=True)
class _ModuleImportState:
    import_lines: dict[str, int]
    star_import_line: int
    module_names: frozenset[str]
    root_names: frozenset[str]


@dataclass(frozen=True, slots=True)
class _LoggerBinding:
    scope: ast.AST
    name: str
    assignment: ast.Assign | ast.AnnAssign


def application_logging_uses(path: Path, source: str, *, root: Path) -> tuple[ApplicationLoggingUse, ...]:
    from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- load native AST helpers only when library policy selects Python source.
    from sarj_python_lint.rules._paths import is_test_path  # ruff: ignore[import-outside-top-level] -- preserve the engine-owned test scope without cross-package private imports.

    if not path.is_absolute() or not root.is_absolute() or ".." in path.parts or ".." in root.parts:
        msg = "logging policy requires canonical absolute source and root paths"
        raise ValueError(msg)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        msg = "logging policy source escapes repository root"
        raise ValueError(msg) from exc
    if relative.suffix not in {".py", ".pyi"} or len(source) > _MAX_SOURCE_CHARACTERS:
        msg = "logging policy requires a bounded selected Python source"
        raise ValueError(msg)
    if relative.suffix == ".pyi":
        return ()
    context = PythonFileContext(path, source)
    if is_test_path(relative) or context.generated:
        return ()
    if context.tree is None:
        msg = f"selected Python source could not be parsed: {path}"
        raise ValueError(msg)
    return _LoggingProvenance(context).uses()


class _LoggingProvenance:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        tree = context.tree
        if tree is None:
            msg = "logging provenance requires a parsed Python syntax tree"
            raise ValueError(msg)
        self.tree = tree
        self.parents = context.parents
        self.imports = context.imports
        self.nodes = context.nodes(ast.AST)
        self.import_state = self._module_import_state()
        self.escaped_names = self._escaped_module_names()
        self.mutated_operations: set[str] = set()
        self._collect_mutations()
        self.binding_counts: dict[tuple[ast.AST, str], int] = {}
        self.binding_loads: dict[_LoggerBinding, list[ast.Name]] = {}
        self.bindings = self._logger_bindings()

    def uses(self) -> tuple[ApplicationLoggingUse, ...]:
        findings = [use for call in self.context.nodes(ast.Call) if (use := self._call_use(call)) is not None]
        return tuple(sorted(set(findings), key=lambda item: (item.line, item.column, item.operation)))

    def _call_use(self, call: ast.Call) -> ApplicationLoggingUse | None:
        qualified = self._qualified(call.func)
        if qualified in _BUILTIN_SINKS:
            return self._use(call, qualified, "sink")
        if qualified == "logging.basicConfig" and self._uses_default_handlers(call):
            return self._use(call, qualified, "sink")
        if qualified in _MODULE_EMITTERS:
            return self._use(call, qualified, "event")
        if not isinstance(call.func, ast.Attribute) or call.func.attr not in _PUBLIC_EMITTERS:
            return None
        operation = "logging.Logger." + call.func.attr
        if operation in self.mutated_operations or not self._logger_receiver(call.func.value):
            return None
        return self._use(call, operation, "event")

    @staticmethod
    def _uses_default_handlers(call: ast.Call) -> bool:
        handlers = next((keyword.value for keyword in call.keywords if keyword.arg == "handlers"), None)
        default_handlers = handlers is None or (isinstance(handlers, ast.Constant) and handlers.value is None)
        return default_handlers and not any(keyword.arg is None for keyword in call.keywords)

    def _use(self, call: ast.Call, operation: str, kind: Literal["event", "sink"]) -> ApplicationLoggingUse:
        line = self.context.source_lines[call.lineno - 1]
        column = len(line.encode("utf-8")[: call.col_offset].decode("utf-8")) + 1
        return ApplicationLoggingUse(call.lineno, column, operation, kind)

    def _scope(self, node: ast.AST) -> ast.AST:
        current = self.parents.get(node)
        while current is not None and not isinstance(current, _SCOPES):
            current = self.parents.get(current)
        return self.tree if current is None else current

    def _module_import_state(self) -> _ModuleImportState:
        lines: dict[str, int] = {}
        star_line = 0
        for statement in self.tree.body:
            match statement:
                case ast.Import():
                    for alias in statement.names:
                        lines[alias.asname or alias.name.partition(".")[0]] = statement.lineno
                case ast.ImportFrom():
                    for alias in statement.names:
                        if alias.name == "*":
                            star_line = max(star_line, statement.lineno)
                        else:
                            lines[alias.asname or alias.name] = statement.lineno
                case _:
                    pass
        return _ModuleImportState(lines, star_line, self._logging_module_aliases(), self._logging_root_aliases())

    def _logging_module_aliases(self) -> frozenset[str]:
        return frozenset(
            alias.asname or alias.name.partition(".")[0]
            for statement in self.tree.body
            if isinstance(statement, ast.Import)
            for alias in statement.names
            if alias.name == "logging" or alias.name.startswith("logging.")
        )

    def _logging_root_aliases(self) -> frozenset[str]:
        return frozenset(
            alias.asname or alias.name
            for statement in self.tree.body
            if isinstance(statement, ast.ImportFrom) and statement.level == 0 and statement.module == "logging"
            for alias in statement.names
            if alias.name == "root"
        )

    def _escaped_module_names(self) -> frozenset[str]:
        module_names = self.import_state.module_names
        root_names = self.import_state.root_names
        imported_names = module_names | root_names
        escaped: set[str] = set()
        for node in self.context.nodes(ast.Name):
            if node.id not in imported_names or not isinstance(node.ctx, ast.Load):
                continue
            parent = self.parents.get(node)
            if not isinstance(parent, ast.Attribute):
                escaped.add(node.id)
                continue
            if (node.id in module_names and parent.attr == "__dict__") or (
                node.id in root_names and self._root_reference_escapes(parent)
            ):
                escaped.add(node.id)
        return frozenset(escaped)

    def _root_reference_escapes(self, parent: ast.Attribute) -> bool:
        if parent.attr not in _PUBLIC_EMITTERS | _ROUTING_METHODS:
            return parent.attr not in _ROUTING_ATTRIBUTES
        call = self.parents.get(parent)
        return isinstance(parent.ctx, ast.Load) and (not isinstance(call, ast.Call) or call.func is not parent)

    def _qualified(self, expression: ast.expr) -> str | None:
        root = expression
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name) or root.id in self.escaped_names:
            return None
        if self.import_state.import_lines.get(root.id, 0) <= self.import_state.star_import_line:
            return None
        name = self.imports.resolved_qualified_name(expression)
        if name is None:
            return None
        parts = name.split(".")
        if any(".".join(parts[:end]) in self.mutated_operations for end in range(1, len(parts) + 1)):
            return None
        return name

    def _collect_mutations(self) -> None:
        for node in self.context.nodes(ast.Attribute):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self._record_attribute_mutation(node)
        for call in self.context.nodes(ast.Call):
            attribute = self._mutation_call_attribute(call)
            if attribute is not None:
                self._record_attribute_mutation(attribute)

    def _record_attribute_mutation(self, attribute: ast.Attribute) -> None:
        qualified = self._qualified(attribute)
        if self._factory_receiver(attribute.value):
            qualified = "logging.Logger." + attribute.attr
        if qualified is not None:
            self.mutated_operations.add(qualified)

    def _mutation_call_attribute(self, call: ast.Call) -> ast.Attribute | None:
        if not isinstance(call.func, ast.Name) or call.func.id not in {"setattr", "delattr"}:
            return None
        if not self.imports.builtin_is_unshadowed(call.func.id) or len(call.args) < _MIN_ATTRIBUTE_MUTATION_ARGS:
            return None
        name = call.args[1]
        if not isinstance(name, ast.Constant) or not isinstance(name.value, str):
            return None
        return ast.Attribute(value=call.args[0], attr=name.value, ctx=ast.Load())

    def _factory_receiver(self, expression: ast.expr) -> bool:
        return (
            isinstance(expression, ast.Call) and self._qualified(expression.func) in _LOGGER_FACTORIES
        ) or self._qualified(expression) == "logging.root"

    def _logger_bindings(self) -> dict[tuple[ast.AST, str], _LoggerBinding]:
        assignments = self._index_bindings()
        candidates: dict[tuple[ast.AST, str], _LoggerBinding] = {}
        for binding in assignments:
            if self._is_logger_binding(binding):
                candidates[binding.scope, binding.name] = binding
        self.bindings = candidates
        self.binding_loads = {}
        for node in self.context.nodes(ast.Name):
            if isinstance(node.ctx, ast.Load) and (binding := self._binding(node)) is not None:
                self.binding_loads.setdefault(binding, []).append(node)
        return {key: binding for key, binding in candidates.items() if self._nonescaping(binding)}

    def _index_bindings(self) -> list[_LoggerBinding]:
        counts: dict[tuple[ast.AST, str], int] = {}
        assignments: list[_LoggerBinding] = []
        for node in self.nodes:
            name = self._bound_name(node)
            if name is not None:
                key = (self._scope(node), name)
                counts[key] = counts.get(key, 0) + 1
            match node:
                case ast.Global() | ast.Nonlocal():
                    for name in node.names:
                        counts[self._scope(node), name] = 2
                case ast.Import() | ast.ImportFrom():
                    for alias in node.names:
                        local = alias.asname or alias.name.partition(".")[0]
                        key = (self._scope(node), local)
                        counts[key] = counts.get(key, 0) + 1
                case _:
                    pass
            assignment = self._logger_assignment(node)
            if assignment is not None:
                assignments.append(assignment)
        self.binding_counts = counts
        return assignments

    @staticmethod
    def _bound_name(node: ast.AST) -> str | None:
        match node:
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                return name
            case ast.arg(arg=name):
                return name
            case (
                ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
                | ast.ExceptHandler(name=name)
                | ast.MatchAs(name=name)
                | ast.MatchStar(name=name)
            ):
                return name
            case ast.MatchMapping(rest=name):
                return name
            case _:
                pass
        return None

    def _logger_assignment(self, node: ast.AST) -> _LoggerBinding | None:
        match node:
            case ast.Assign(targets=[ast.Name(id=name)]):
                return _LoggerBinding(self._scope(node), name, node)
            case ast.AnnAssign(target=ast.Name(id=name), value=value) if value is not None:
                return _LoggerBinding(self._scope(node), name, node)
            case _:
                pass
        return None

    def _is_logger_binding(self, binding: _LoggerBinding) -> bool:
        assignment = binding.assignment
        if binding.scope is self.tree and assignment.lineno <= self.import_state.star_import_line:
            return False
        if self.binding_counts.get((binding.scope, binding.name)) != 1:
            return False
        if self.parents.get(assignment) is not binding.scope:
            return False
        return isinstance(assignment.value, ast.Call) and self._qualified(assignment.value.func) in _LOGGER_FACTORIES

    def _binding(self, node: ast.Name) -> _LoggerBinding | None:
        scope = self._scope(node)
        origin = scope
        while scope is not None:
            if not (isinstance(scope, ast.ClassDef) and scope is not origin):
                key = (scope, node.id)
                if key in self.binding_counts:
                    return self.bindings.get(key)
            parent = self._scope(scope)
            scope = None if parent is scope else parent
        return None

    def _nonescaping(self, binding: _LoggerBinding) -> bool:
        for node in self.binding_loads.get(binding, ()):
            parent = self.parents.get(node)
            if not isinstance(parent, ast.Attribute):
                return False
            if parent.attr in _PUBLIC_EMITTERS:
                call = self.parents.get(parent)
                if not isinstance(parent.ctx, ast.Load) or not isinstance(call, ast.Call) or call.func is not parent:
                    return False
            elif parent.attr in _ROUTING_METHODS:
                call = self.parents.get(parent)
                if not isinstance(call, ast.Call) or call.func is not parent:
                    return False
            elif parent.attr not in _ROUTING_ATTRIBUTES:
                return False
        return True

    def _logger_receiver(self, expression: ast.expr) -> bool:
        if self._factory_receiver(expression):
            return True
        if isinstance(expression, ast.Name):
            binding = self._binding(expression)
            return binding is not None and binding.assignment.lineno < expression.lineno
        return False
