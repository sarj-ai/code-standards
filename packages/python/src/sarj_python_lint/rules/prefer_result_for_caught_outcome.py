from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field, replace
from functools import cached_property
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, final, override

from sarj_python_lint._analysis_session import AnalysisSession
from sarj_python_lint._file_context import PythonFileContext
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
)
from sarj_python_lint.rules._ast_index import has_own_yield
from sarj_python_lint.rules._ast_names import dotted_parts
from sarj_python_lint.rules._namespace_access import dynamic_namespace_access
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._project_index import import_binding_symbol
from sarj_python_lint.rules.no_custom_control_flow_exception import covered_custom_raises


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_python_lint.rules._project_index import ProjectIndexSet, SourceUnit


type _Function = ast.FunctionDef | ast.AsyncFunctionDef

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_TYPING = frozenset({"typing", "typing_extensions"})
_MAX_BASE_DEPTH = 16
_BAD = """class MissingField(RuntimeError):
    pass

def evaluate(fields: set[str], field: str) -> None:
    if field not in fields:
        raise MissingField(field)

def keep(records: list[set[str]], field: str) -> list[set[str]]:
    kept = []
    for record in records:
        try:
            evaluate(record, field)
        except MissingField:
            continue
        kept.append(record)
    return kept
"""
_GOOD = """from dataclasses import dataclass

@dataclass(frozen=True)
class Met:
    pass

@dataclass(frozen=True)
class NotMet:
    field: str

type Evaluation = Met | NotMet

def evaluate(fields: set[str], field: str) -> Evaluation:
    if field not in fields:
        return NotMet(field)
    return Met()

def keep(records: list[set[str]], field: str) -> list[set[str]]:
    return [record for record in records if isinstance(evaluate(record, field), Met)]
"""


def _builtin_bases() -> dict[str, frozenset[str]]:
    pending = [BaseException]
    bases: dict[str, frozenset[str]] = {}
    while pending:
        error = pending.pop()
        if error.__module__ == "builtins":
            bases[f"builtins.{error.__name__}"] = frozenset(
                f"builtins.{base.__name__}" for base in error.__mro__ if base is not object
            )
            pending.extend(error.__subclasses__())
    return bases | dict.fromkeys(("builtins.IOError", "builtins.EnvironmentError"), bases["builtins.OSError"])


_BUILTIN_BASES: Final = _builtin_bases()


@final
class PreferResultForCaughtOutcome(ProjectRule):
    id = "prefer-result-for-caught-outcome"
    code = "SARJ604"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Return a typed outcome when every caller handles the same first-party exception.",
        rationale="When each direct caller catches an exception and continues or returns, the return type hides an expected outcome.",
        remediation="Return a tagged outcome with the data the handlers use, and match its variants at the callers.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Checks stable, undecorated module functions and methods on plain classes. "
                "Indirect calls, callable escapes, re-exports, and ambiguous bindings abstain."
            ),
            (
                "Requires an exact named handler in the nearest try body at every call site. "
                "Superclass-only handlers, handlers that raise, generators, special methods, "
                "Never and NoReturn functions, and raises already covered by SARJ542 are excluded."
            ),
        ),
        examples=(
            RuleExample(
                example_id="caught-filter-outcome",
                title="A filter signals a routine rejection by raising",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("filters/__init__.py", _BAD),),
                focus_path=PurePosixPath("filters/__init__.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-filter-outcome",
                title="The filter returns an explicit evaluation outcome",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("filters/__init__.py", _GOOD),),
                focus_path=PurePosixPath("filters/__init__.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary
    _findings: dict[Path, list[Diagnostic]] | None = None

    @override
    def prepare(self, indexes: ProjectIndexSet) -> None:
        super().prepare(indexes)
        self._findings = None

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        project = context.session.project
        if project is None or "raise" not in context.symbol_source:
            return []
        unit = project.unit(context.path)
        if unit is None or unit.source != context.source:
            return []
        if self._findings is None:
            self._findings = _ProjectOutcomes(project).findings()
        return [replace(item, path=context.path) for item in self._findings.get(unit.path, ())]


@dataclass(frozen=True, slots=True)
class _Raised:
    node: ast.Raise
    error: str
    ancestors: frozenset[str]


@dataclass(slots=True)
class _Candidate:
    source: _Source
    function: _Function
    raises: list[_Raised] = field(default_factory=list)
    callers: set[str] = field(default_factory=set)


@final
class _Source:
    def __init__(self, unit: SourceUnit, session: AnalysisSession) -> None:
        self.unit = unit
        self.module = unit.module or ""
        self.context = PythonFileContext(unit.path, unit.source, session)

    @cached_property
    def aliases(self) -> dict[str, dict[ast.alias, str]]:
        aliases: dict[str, dict[ast.alias, str]] = defaultdict(dict)
        for binding in self.context.nodes(ast.alias):
            statement = self.context.parents.get(binding)
            if isinstance(statement, ast.Import | ast.ImportFrom):
                symbol = import_binding_symbol(self.unit, statement, binding)
                if symbol is not None:
                    name = binding.asname or binding.name.partition(".")[0]
                    aliases[name][binding] = ".".join(part for part in (symbol.module, symbol.name) if part)
        return aliases

    @cached_property
    def opaque(self) -> bool:
        context = self.context
        if context.has_wildcard_import or not context.dynamic_namespace:
            return context.has_wildcard_import
        return dynamic_namespace_access(
            (
                node
                for node in context.nodes(ast.AST)
                if not (
                    isinstance(node, ast.Attribute)
                    and node.attr == "__dict__"
                    and isinstance(context.parents.get(node), ast.FormattedValue)
                )
            ),
            context.imports,
            context.parents,
        )

    @cached_property
    def covered_raises(self) -> set[ast.Raise]:
        return covered_custom_raises(self.context)

    def declaration(self, owner: ast.AST | None, name: str) -> ast.AST | None:
        bindings = self.context.binding_inventory.bindings.get(owner, {}).get(name, ())
        if len(bindings) != 1 or name in self.context.binding_inventory.external_bindings:
            return None
        return bindings[0]

    def reference(self, node: ast.expr) -> str | None:
        parts = dotted_parts(node)
        if parts is None:
            return None
        name, *attrs = parts
        match self.context.static_resource_provenance.runtime_binding(name, node):
            case ast.alias() as binding:
                origin = self.aliases.get(name, {}).get(binding)
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() as declaration if (
                self.module and self.context.parents.get(declaration) is self.unit.tree
            ):
                origin = f"{self.module}.{name}"
            case ast.arg() as parameter if attrs:
                origin = self._receiver_class(parameter)
            case None if f"builtins.{name}" in _BUILTIN_BASES and self.context.imports.builtin_is_unshadowed(name):
                origin = f"builtins.{name}"
            case _:
                return None
        return ".".join((origin, *attrs)) if origin is not None else None

    def _receiver_class(self, parameter: ast.arg) -> str | None:
        function = self.context.static_resource_provenance.scope(parameter)
        if not isinstance(function, _FUNCTIONS) or function.decorator_list:
            return None
        owner = self.context.parents.get(function)
        parameters = function.args.posonlyargs or function.args.args
        if not parameters or parameters[0] is not parameter:
            return None
        if (
            self.module
            and isinstance(owner, ast.ClassDef)
            and self.context.parents.get(owner) is self.unit.tree
            and self.declaration(self.unit.tree, owner.name) is owner
        ):
            return f"{self.module}.{owner.name}"
        return None

    def ambiguous_bindings(self, node: ast.Name | ast.Attribute) -> Iterator[str]:
        parts = dotted_parts(node)
        if parts is not None:
            root, *attrs = parts
            if self.context.static_resource_provenance.runtime_binding(root, node) is None:
                for origin in self.aliases.get(root, {}).values():
                    yield ".".join((origin, *attrs))
                if self.module:
                    yield ".".join((self.module, *parts))


@final
class _ProjectOutcomes:
    def __init__(self, project: ProjectIndexSet) -> None:
        session = AnalysisSession()
        session.project = project
        self.project = project
        self.sources = [
            _Source(unit, session)
            for unit in project.source_units
            if unit.tree is not None
            and not is_test_path(unit.path)
            and not is_test_support_path(unit.path)
            and {"vendor", "vendored", "third_party"}.isdisjoint(unit.path.parts)
        ]
        self.modules = {
            source.module: source
            for source in self.sources
            if source.module and project.source_unit(source.module) is source.unit
        }

        self.candidates = self._candidates()
        self.methods: dict[str, set[str]] = defaultdict(set)
        self.namespaces: dict[str, set[str]] = defaultdict(set)
        for qualified, candidate in self.candidates.items():
            namespace, _, name = qualified.rpartition(".")
            if namespace != candidate.source.module:
                self.methods[name].add(qualified)
            while namespace:
                self.namespaces[namespace].add(qualified)
                namespace = namespace.rpartition(".")[0]

    def findings(self) -> dict[Path, list[Diagnostic]]:
        names = {name.rsplit(".", 1)[-1] for name in self.candidates | self.namespaces}
        for source in self.sources:
            self._scan(source, names)
        findings: dict[Path, list[Diagnostic]] = defaultdict(list)
        for candidate in self.candidates.values():
            if not candidate.callers or not candidate.raises:
                continue
            context = candidate.source.context
            callers = ", ".join(sorted(candidate.callers))
            for raised in candidate.raises:
                if raised.node in candidate.source.covered_raises or context.suppressions.is_suppressed(
                    raised.node.lineno, PreferResultForCaughtOutcome.code
                ):
                    continue
                findings[context.path].append(
                    Diagnostic(
                        context.path,
                        raised.node.lineno,
                        raised.node.col_offset + 1,
                        PreferResultForCaughtOutcome.code,
                        f"Every caller ({callers}) handles {raised.error.rsplit('.', 1)[-1]} as an outcome. Return a typed result.",
                        Severity.WARNING,
                    )
                )
        return findings

    def _candidates(self) -> dict[str, _Candidate]:
        candidates: dict[str, _Candidate] = {}
        for source in self.modules.values():
            context = source.context
            if "raise" not in context.symbol_source or source.opaque or context.generated:
                continue
            for node in context.nodes(ast.Raise):
                self._collect_raise(candidates, source, node)
        return candidates

    def _collect_raise(self, candidates: dict[str, _Candidate], source: _Source, node: ast.Raise) -> None:
        context = source.context
        owner = context.static_resource_provenance.scope(node)
        if not isinstance(owner, _FUNCTIONS) or (name := self._candidate_name(source, owner)) is None:
            return
        target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        error = source.reference(target) if target is not None else None
        if error is None or error.startswith("builtins.") or (ancestors := self._ancestors(error)) is None:
            return
        if not _local_boundary(node, owner, context):
            candidates.setdefault(name, _Candidate(source, owner)).raises.append(_Raised(node, error, ancestors))

    def _candidate_name(self, source: _Source, function: _Function) -> str | None:
        context = source.context
        owner = context.parents.get(function)
        if (
            function.decorator_list
            or function.name.startswith("__")
            or source.declaration(owner, function.name) is not function
        ):
            return None
        if has_own_yield(function) or _returns_never(function, context):
            return None
        if owner is source.unit.tree:
            return f"{source.module}.{function.name}"
        if (
            isinstance(owner, ast.ClassDef)
            and not (owner.bases or owner.keywords or owner.decorator_list)
            and context.parents.get(owner) is source.unit.tree
            and source.declaration(source.unit.tree, owner.name) is owner
            and not self.project.direct_subclasses(source.unit, owner.name)
        ):
            return f"{source.module}.{owner.name}.{function.name}"
        return None

    def _ancestors(self, name: str, seen: frozenset[str] = frozenset()) -> frozenset[str] | None:
        if name in _BUILTIN_BASES:
            return _BUILTIN_BASES[name]
        if name in seen or len(seen) >= _MAX_BASE_DEPTH:
            return None
        module, _, identifier = name.rpartition(".")
        source = self.modules.get(module)
        if source is None or source.opaque:
            return None
        declaration = source.declaration(source.unit.tree, identifier)
        if (
            not isinstance(declaration, ast.ClassDef)
            or source.context.parents.get(declaration) is not source.unit.tree
            or declaration.keywords
            or any(
                not source.context.module_imports.resolves(decorator, sources=_TYPING, symbol="final")
                for decorator in declaration.decorator_list
            )
            or not declaration.bases
        ):
            return None
        ancestors = {name}
        for base in declaration.bases:
            origin = source.reference(base)
            if origin is None or (bases := self._ancestors(origin, seen | {name})) is None:
                return None
            ancestors.update(bases)
        return frozenset(ancestors)

    def _scan(self, source: _Source, names: set[str]) -> None:
        context = source.context
        for origin in source.aliases.get("*", {}).values():
            self._discard_namespace(origin)
        if source.unit.path.name == "__init__.py":
            self._discard_exports(source)
        visible_names = names | {
            alias
            for alias, origins in source.aliases.items()
            if any(origin in self.candidates or origin in self.namespaces for origin in origins.values())
        }
        for reference in context.nodes(ast.Name, ast.Attribute):
            name = reference.id if isinstance(reference, ast.Name) else reference.attr
            if name in visible_names:
                self._use(source, reference)

    def _use(self, source: _Source, reference: ast.Name | ast.Attribute) -> None:
        origin = source.reference(reference)
        if isinstance(reference, ast.Attribute) and isinstance(reference.value, ast.Call):
            owner = source.reference(reference.value.func)
            if owner is not None and owner in self.namespaces:
                origin = f"{owner}.{reference.attr}"
        if origin is None:
            self._discard_ambiguous(source, reference)
        elif origin in self.candidates:
            self._apply_call(origin, source, reference)
        elif origin in self.namespaces:
            parent = source.context.parents.get(reference)
            if not (
                (isinstance(parent, ast.Attribute) and parent.value is reference)
                or (isinstance(parent, ast.Call) and parent.func is reference)
            ):
                self._discard_namespace(origin)

    def _discard_namespace(self, origin: str) -> None:
        for candidate in self.namespaces.get(origin, ()):
            self.candidates.pop(candidate, None)

    def _discard_ambiguous(self, source: _Source, reference: ast.Name | ast.Attribute) -> None:
        for possibility in source.ambiguous_bindings(reference):
            self.candidates.pop(possibility, None)
        if isinstance(reference, ast.Attribute):
            for candidate in self.methods.get(reference.attr, ()):
                self.candidates.pop(candidate, None)

    def _discard_exports(self, source: _Source) -> None:
        pending = [origin for bindings in source.aliases.values() for origin in bindings.values()]
        seen: set[str] = set()
        while pending:
            origin = pending.pop()
            if origin in seen:
                continue
            seen.add(origin)
            self.candidates.pop(origin, None)
            module, _, name = origin.rpartition(".")
            if (provider := self.modules.get(module)) is not None:
                pending.extend(provider.aliases.get(name, {}).values())

    def _apply_call(self, origin: str, source: _Source, reference: ast.expr) -> None:
        candidate = self.candidates[origin]
        context = source.context
        call = context.parents.get(reference)
        if source.opaque or not isinstance(call, ast.Call) or call.func is not reference:
            self.candidates.pop(origin)
            return
        if isinstance(candidate.function, ast.AsyncFunctionDef) and not isinstance(
            context.parents.get(call), ast.Await
        ):
            self.candidates.pop(origin)
            return
        if (attempt := _enclosing_try(call, context)) is None:
            self.candidates.pop(origin)
            return
        candidate.raises[:] = [raised for raised in candidate.raises if self._handles(source, attempt, raised)]
        owners = [owner.name for owner in _parents(call, context) if isinstance(owner, (*_FUNCTIONS, ast.ClassDef))]
        candidate.callers.add(".".join((source.module or context.path.stem, *reversed(owners))))

    def _handles(self, source: _Source, attempt: ast.Try, raised: _Raised) -> bool:
        for handler in attempt.handlers:
            if handler.type is None:
                return False
            types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
            origins = [source.reference(item) for item in types]
            if raised.error in origins and all(origin is not None for origin in origins):
                return not any(isinstance(node, ast.Raise) for node in ast.walk(handler))
            if any(
                origin is None or (bases := self._ancestors(origin)) is None or bases <= raised.ancestors
                for origin in origins
            ):
                return False
        return False


def _parents(node: ast.AST, context: PythonFileContext) -> Iterator[ast.AST]:
    parent = context.parents.get(node)
    while parent is not None:
        yield parent
        parent = context.parents.get(parent)


def _enclosing_try(call: ast.Call, context: PythonFileContext) -> ast.Try | None:
    child: ast.AST = call
    for parent in _parents(call, context):
        match parent:
            case ast.Try(body=body) if child in body:
                return parent
            case (
                ast.Try()
                | ast.TryStar()
                | ast.FunctionDef()
                | ast.AsyncFunctionDef()
                | ast.ClassDef()
                | ast.Lambda()
                | ast.GeneratorExp()
                | ast.TypeAlias()
            ):
                break
            case _:
                child = parent
    return None


def _local_boundary(node: ast.Raise, function: _Function, context: PythonFileContext) -> bool:
    child: ast.AST = node
    for parent in _parents(node, context):
        if parent is function:
            break
        if isinstance(parent, ast.With | ast.AsyncWith) or (
            isinstance(parent, ast.Try | ast.TryStar)
            and (parent.finalbody or (parent.handlers and child in parent.body))
        ):
            return True
        child = parent
    return False


def _returns_never(function: _Function, context: PythonFileContext) -> bool:
    returns = context.annotation_semantics.resolve_alias(function.returns)
    return returns is not None and any(
        context.module_imports.resolves(returns, sources=_TYPING, symbol=name) for name in ("Never", "NoReturn")
    )
