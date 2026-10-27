from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, final

from sarj_python_lint.rules._declared_contracts import MODEL_BASES, SETTINGS_BASES, DeclaredContracts
from sarj_python_lint.rules._native_object_contracts import NativeObjectContracts, builtin_object, source_position
from sarj_python_lint.rules._test_composition import call_arguments, direct_nodes
from sarj_python_lint.rules.require_pydantic_for_mapping_shape import MappingShapeFacts


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
REFINEMENT_TYPES = frozenset(
    {"typing.TypeGuard", "typing.TypeIs", "typing_extensions.TypeGuard", "typing_extensions.TypeIs"}
)
_TYPE_TARGETS = frozenset(
    {"str", "bytes", "int", "float", "bool", "complex", "dict", "list", "set", "frozenset", "tuple"}
)
_CONTAINERS = frozenset({"dict", "list", "set", "frozenset", "tuple"})
_MAPPINGS = frozenset({"collections.abc.Mapping", "typing.Mapping", "typing_extensions.Mapping"})
_PARSERS = frozenset(
    {
        "ast.literal_eval",
        "json.load",
        "json.loads",
        "pickle.load",
        "pickle.loads",
        "tomllib.load",
        "tomllib.loads",
        "yaml.load",
        "yaml.safe_load",
        "yaml.full_load",
    }
)
_OPAQUE_INPUTS = frozenset(
    {
        "copy.copy",
        "copy.deepcopy",
        "json.dump",
        "json.dumps",
        "pickle.dump",
        "pickle.dumps",
        "typing.get_args",
        "typing.get_origin",
        "typing_extensions.get_args",
        "typing_extensions.get_origin",
    }
)
_UNIVERSAL_BUILTINS = frozenset({"bool", "format", "hash", "id", "repr", "str", "type"})
_DECODERS = frozenset({"json.JSONDecoder", "json.decoder.JSONDecoder"})
_PAIR_ARITY = 2
_MAX_DEPTH = 12
_MAX_GUARDS = 64
_ORIGIN_PASSES = 3
_VALIDATION_BASES = MODEL_BASES | SETTINGS_BASES | {"pydantic.RootModel", "pydantic.root_model.RootModel"}


class _Origin(Enum):
    CHECKED_INPUT = auto()
    UNKNOWN_VALUE = auto()
    CARRIER = auto()
    CHECKED_VALUE = auto()


@dataclass(frozen=True)
class _NativeResult:
    handled: bool
    origin: _Origin | None


@dataclass(frozen=True)
class _BooleanPaths:
    all_required: bool
    branches: tuple[ast.expr, ...]


@dataclass(frozen=True)
class _Refinement:
    target: ast.expr
    facts: MappingShapeFacts
    annotation: ast.expr


@dataclass
class _ProofBudget:
    depth: int = 0

    def acquire(self) -> bool:
        if self.depth >= _MAX_DEPTH:
            return False
        self.depth += 1
        return True

    def release(self) -> None:
        self.depth -= 1


@final
class OpaqueContractFacts:
    def __init__(
        self,
        context: PythonFileContext,
        facts: MappingShapeFacts,
        *,
        modules: dict[Path, OpaqueContractFacts] | None = None,
        budget: _ProofBudget | None = None,
    ) -> None:
        self.context = context
        self.facts = facts
        self.native = NativeObjectContracts(context, facts)
        self.guards: dict[str, _Refinement | None] = {}
        self.checked: dict[_Function, frozenset[ast.arg]] = {}
        self.raw_checked: dict[_Function, frozenset[ast.arg]] = {}
        self.modules = {} if modules is None else modules
        self.modules[context.path.resolve()] = self
        self.budget = _ProofBudget() if budget is None else budget
        self.parameter_reads: dict[ast.arg, tuple[ast.Name, ...]] = {}
        self.reads_indexed = False
        self.results: dict[_Function, _Origin | None] = {}
        self.independent_results: dict[_Function, _Origin | None] = {}
        self.reachability: dict[tuple[ast.AST, _Function], bool] = {}
        self.asserted_parameters: dict[ast.Assert, frozenset[ast.arg]] = {}

    def owns(self, function: _Function, annotation: ast.expr) -> bool:
        if self.native.property_result(function, annotation):
            return True
        parameters = self.checked_parameters(function)
        if any(parameter.annotation is annotation for parameter in parameters):
            return True
        if annotation is not function.returns:
            return False
        return self.result(function) is not None

    def result(self, function: _Function, *, independent: bool = False) -> _Origin | None:
        cache = self.independent_results if independent else self.results
        if function in cache:
            return cache[function]
        cache[function] = None
        if not self.budget.acquire():
            return None
        try:
            result = self._find_result(function, independent=independent)
        finally:
            self.budget.release()
        cache[function] = result
        return result

    def _find_result(self, function: _Function, *, independent: bool) -> _Origin | None:
        parameters: frozenset[ast.arg] = frozenset() if independent else self.checked_parameters(function)
        origins = _RawOrigins(self, function, parameters)
        returned = [
            node.value
            for node in direct_nodes(function)
            if isinstance(node, ast.Return) and self.reachable(node, function)
        ]
        if not returned:
            return None
        values = [origins.value(value) if value is not None else None for value in returned]
        opaque_result = function.returns is not None and self._bare_object(function.returns)
        proven = any(values) and all(
            (origin is not None and (origin is _Origin.UNKNOWN_VALUE or not opaque_result))
            or _fallback(value, self.context)
            for value, origin in zip(returned, values, strict=True)
        )
        return (_Origin.UNKNOWN_VALUE if opaque_result else _Origin.CARRIER) if proven else None

    def _bare_object(self, annotation: ast.expr) -> bool:
        node = self.context.annotation_semantics.parse(annotation)
        return node is not None and builtin_object(node, self.facts, annotation)

    def checked_parameters(self, function: _Function) -> frozenset[ast.arg]:
        if function in self.checked:
            return self.checked[function]
        self.checked[function] = frozenset()
        if not self.budget.acquire():
            return frozenset()
        try:
            result = self._find_checked(function)
        finally:
            self.budget.release()
        self.checked[function] = result
        return result

    def _find_checked(self, function: _Function) -> frozenset[ast.arg]:
        found = set(self.native.namespace(function).parameters())
        terminal_rejection = _rejects(function.body)
        for node in direct_nodes(function):
            if not self.reachable(node, function):
                continue
            if isinstance(node, ast.Return):
                found.update(self._returned_parameters(node))
                continue
            if isinstance(node, ast.Call):
                found.update(self._universal_inputs(node))
                found.update(self._model_inputs(node))
            if self.context.parents.get(node) is function:
                found.update(self._statement_parameters(node, terminal_rejection=terminal_rejection))
        found.update(self._identity_parameters(function))
        found.update(self._key_parameters(function))
        return frozenset(found)

    def _key_parameters(self, function: _Function) -> set[ast.arg]:
        found: set[ast.arg] = set()
        for parameter in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs):
            if not self._raw_mapping(parameter):
                continue
            reads = self._reads(parameter)
            if (
                reads
                and all(self._key_read(read) for read in reads)
                and any(self._key_operation(read) for read in reads)
            ):
                found.add(parameter)
        return found

    def _key_read(self, read: ast.Name) -> bool:
        parent = self.context.parents.get(read)
        if isinstance(parent, ast.Assign | ast.AnnAssign) and parent.value is read:
            return True
        if isinstance(parent, ast.Compare):
            return all(isinstance(operator, ast.Is | ast.IsNot) for operator in parent.ops) or (
                read in parent.comparators and all(isinstance(operator, ast.In | ast.NotIn) for operator in parent.ops)
            )
        return self._key_operation(read)

    def _key_operation(self, read: ast.Name) -> bool:
        parent = self.context.parents.get(read)
        if isinstance(parent, ast.For | ast.comprehension) and parent.iter is read:
            return True
        if isinstance(parent, ast.Attribute) and parent.value is read and parent.attr == "keys":
            return True
        return (
            isinstance(parent, ast.Call)
            and parent.args == [read]
            and not parent.keywords
            and any(self.facts.builtin(parent.func, name, parent) for name in ("set", "frozenset"))
        )

    def _identity_parameters(self, function: _Function) -> set[ast.arg]:
        found: set[ast.arg] = set()
        for parameter in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs):
            reads = self._reads(parameter)
            if (
                reads
                and all(self._identity_read(read) for read in reads)
                and any(
                    isinstance(parent := self.context.parents.get(read), ast.Compare)
                    and all(isinstance(operator, ast.Is | ast.IsNot) for operator in parent.ops)
                    for read in reads
                )
            ):
                found.add(parameter)
        return found

    def _identity_read(self, read: ast.Name) -> bool:
        parent = self.context.parents.get(read)
        if isinstance(parent, ast.Compare):
            return all(isinstance(operator, ast.Is | ast.IsNot) for operator in parent.ops)
        return self._universal_read(read)

    def _statement_parameters(self, node: ast.AST, *, terminal_rejection: bool) -> set[ast.arg]:
        parameters = (
            set(self._assertion_parameters(node)) if isinstance(node, ast.Assert) else self._rejection_parameters(node)
        )
        if terminal_rejection and isinstance(node, ast.If) and _terminates(node.body):
            parameters.update(self._predicate(node.test))
        return {parameter for parameter in parameters if self._safe_before(parameter, node)}

    def _assertion_parameters(self, node: ast.Assert) -> frozenset[ast.arg]:
        if node not in self.asserted_parameters:
            self.asserted_parameters[node] = frozenset(self._path_parameters(node.test))
        return self.asserted_parameters[node]

    def _path_parameters(self, expression: ast.expr, *, positive: bool = True, depth: int = 0) -> set[ast.arg]:
        if depth >= _MAX_DEPTH or _literal_truth(expression) is not None:
            return set()
        if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
            return self._path_parameters(expression.operand, positive=not positive, depth=depth + 1)
        if isinstance(expression, ast.BoolOp):
            paths = _boolean_paths(expression, positive=positive)
            facts = [self._path_parameters(branch, positive=positive, depth=depth + 1) for branch in paths.branches]
            if not facts:
                return set()
            result = set(facts[0])
            for branch in facts[1:]:
                if paths.all_required:
                    result.update(branch)
                else:
                    result.intersection_update(branch)
            return result
        return self._predicate(expression) if positive else set()

    def reachable(self, node: ast.AST, function: _Function) -> bool:
        key = node, function
        if key not in self.reachability:
            self.reachability[key] = self._reachable_path(node, function)
        return self.reachability[key]

    def _reachable_path(self, node: ast.AST, function: _Function) -> bool:
        while (parent := self.context.parents.get(node)) is not None:
            if isinstance(node, ast.stmt) and any(
                _stops_suite(sibling) for sibling in _previous_statements(node, parent)
            ):
                return False
            if not _reachable_branch(node, parent):
                return False
            if parent is function:
                return True
            node = parent
        return False

    def _returned_parameters(self, node: ast.Return) -> set[ast.arg]:
        if node.value is None:
            return set()
        candidate = node.value.test if isinstance(node.value, ast.IfExp) else node.value
        found = {parameter for parameter in self._predicate(candidate) if self._safe_before(parameter, node)}
        if isinstance(node.value, ast.Call):
            found.update(self._universal_inputs(node.value))
        return found

    def _rejection_parameters(self, node: ast.AST) -> set[ast.arg]:
        match node:
            case ast.If():
                return self._if_parameters(node)
            case ast.Match():
                return self._match_parameters(node)
            case _:
                return set()

    def _if_parameters(self, node: ast.If) -> set[ast.arg]:
        if _rejects(node.body):
            candidate = node.test
            if isinstance(candidate, ast.BoolOp) and isinstance(candidate.op, ast.Or):
                candidate = candidate.values[0]
            if (parameter := self._type_comparison(candidate, rejected=True)) is not None:
                return {parameter}
            if isinstance(candidate, ast.UnaryOp) and isinstance(candidate.op, ast.Not):
                return self._predicate(candidate.operand)
        return self._predicate(node.test) if _rejects(node.orelse) else set()

    def _match_parameters(self, node: ast.Match) -> set[ast.arg]:
        if not node.cases:
            return set()
        last = node.cases[-1]
        if not (
            isinstance(last.pattern, ast.MatchAs)
            and last.pattern.name is None
            and last.guard is None
            and _rejects(last.body)
        ):
            return set()
        parameter = self.parameter(node.subject)
        if parameter is not None and any(_class_pattern(case.pattern) for case in node.cases[:-1]):
            return {parameter}
        return set()

    def _predicate(self, expression: ast.expr) -> set[ast.arg]:
        if isinstance(expression, ast.BoolOp):
            return self._predicate(expression.values[0])
        if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
            expression = expression.operand
        if (parameter := self._type_comparison(expression, rejected=False)) is not None:
            return {parameter}
        if not isinstance(expression, ast.Call) or not expression.args:
            return set()
        if self._isinstance(expression) or self._guard(expression.func):
            parameter = self.parameter(expression.args[0])
            return {parameter} if parameter is not None else set()
        return set()

    def _type_comparison(self, node: ast.expr, *, rejected: bool) -> ast.arg | None:
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
            return None
        operator = node.ops[0]
        if not isinstance(operator, (ast.IsNot, ast.NotEq) if rejected else (ast.Is, ast.Eq)):
            return None
        for call, kind in ((node.left, node.comparators[0]), (node.comparators[0], node.left)):
            if not isinstance(call, ast.Call) or len(call.args) != 1 or call.keywords:
                continue
            if not (
                self.facts.builtin(call.func, "type", call) or self.facts.qualified(call.func, call) == "builtins.type"
            ):
                continue
            qualified = self.facts.qualified(kind, node)
            if any(self.facts.builtin(kind, name, node) or qualified == f"builtins.{name}" for name in _TYPE_TARGETS):
                return self.parameter(call.args[0])
        return None

    def _isinstance(self, call: ast.Call) -> bool:
        return (
            len(call.args) == _PAIR_ARITY
            and not call.keywords
            and not any(isinstance(value, ast.Starred) for value in call.args)
            and (
                self.facts.builtin(call.func, "isinstance", call)
                or self.facts.qualified(call.func, call) == "builtins.isinstance"
            )
        )

    def _universal_inputs(self, call: ast.Call) -> set[ast.arg]:
        if not any(
            self.parameter(value) is not None for value in (*call.args, *(item.value for item in call.keywords))
        ):
            return set()
        assertion = self._enclosing_assertion(call)
        asserted = (
            self._assertion_parameters(assertion)
            if assertion is not None and (self._isinstance(call) or self._guard(call.func))
            else None
        )
        return {
            parameter
            for value in self._accepted_arguments(call)
            if (parameter := self.parameter(value)) is not None
            and (asserted is None or parameter in asserted)
            and all(self._universal_read(read) for read in self._reads(parameter))
        }

    def _enclosing_assertion(self, node: ast.AST) -> ast.Assert | None:
        while (parent := self.context.parents.get(node)) is not None:
            if isinstance(parent, ast.Assert):
                return parent
            if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                return None
            node = parent
        return None

    def _accepted_arguments(self, call: ast.Call) -> tuple[ast.expr, ...]:
        if native := self.native.arguments(call):
            return native
        qualified = self.facts.qualified(call.func, call)
        universal = qualified in _OPAQUE_INPUTS or (
            len(call.args) == 1
            and not call.keywords
            and not isinstance(call.args[0], ast.Starred)
            and any(self.facts.builtin(call.func, name, call) for name in _UNIVERSAL_BUILTINS)
        )
        if universal or self._isinstance(call) or self._guard(call.func):
            return tuple(call.args[:1])
        source = self._source(call.func)
        if source is None:
            return ()
        owner, function = source
        positional = (*function.args.posonlyargs, *function.args.args)
        arguments = call_arguments(call, tuple(parameter.arg for parameter in positional))
        if arguments is None:
            return ()
        eligible = tuple(
            parameter
            for parameter in (*positional, *function.args.kwonlyargs)
            if parameter.arg in arguments
            and (parameter.annotation is None or _raw_output(parameter.annotation, owner.facts, parameter.annotation))
        )
        if not eligible:
            return ()
        checked = owner.checked_parameters(function)
        return tuple(arguments[parameter.arg] for parameter in eligible if parameter in checked)

    def _model_inputs(self, call: ast.Call) -> set[ast.arg]:
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "model_validate":
            return set()
        arguments = call_arguments(call, ("obj",))
        parameter = self.parameter(arguments["obj"]) if arguments is not None and "obj" in arguments else None
        if parameter is None or not self._safe_before(parameter, call):
            return set()
        contracts = DeclaredContracts(self.context)
        model = contracts.class_type(call.func.value)
        return {parameter} if model is not None and contracts.inherits(model, _VALIDATION_BASES) else set()

    def _reads(self, parameter: ast.arg) -> tuple[ast.Name, ...]:
        if not self.reads_indexed:
            index: dict[ast.arg, list[ast.Name]] = {}
            for reads in self.facts.provenance.reads.values():
                for read in reads:
                    if (owner := self.parameter(read)) is not None:
                        index.setdefault(owner, []).append(read)
            self.parameter_reads = {owner: tuple(reads) for owner, reads in index.items()}
            self.reads_indexed = True
        reads = self.parameter_reads.get(parameter, ())
        scope = self.facts.provenance.scope(parameter)
        if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
            return tuple(read for read in reads if self.reachable(read, scope))
        return reads

    def _safe_before(self, parameter: ast.arg, node: ast.AST) -> bool:
        position = source_position(node)
        return all(self._universal_read(read) for read in self._reads(parameter) if source_position(read) < position)

    def _universal_read(self, read: ast.Name) -> bool:
        if self.narrowed(read) is _Origin.CHECKED_VALUE:
            return True
        parent = self.context.parents.get(read)
        if isinstance(parent, ast.keyword):
            parent = self.context.parents.get(parent)
        if isinstance(parent, ast.Assign | ast.AnnAssign) and parent.value is read:
            return True
        if isinstance(parent, ast.Subscript) and parent.value is read:
            return self._raw_annotation(self.parameter(read))
        if isinstance(parent, ast.Attribute) and parent.value is read and parent.attr == "get":
            return self._raw_annotation(self.parameter(read))
        if isinstance(parent, ast.Attribute) and parent.value is read and parent.attr == "keys":
            return self._raw_mapping(self.parameter(read))
        if isinstance(parent, ast.Compare):
            return self._comparison_read(read, parent)
        if (
            isinstance(parent, ast.Call)
            and parent.args[:1] == [read]
            and self._raw_mapping(self.parameter(read))
            and any(self.facts.builtin(parent.func, name, parent) for name in ("set", "frozenset"))
        ):
            return True
        return isinstance(parent, ast.Call) and any(value is read for value in self._accepted_arguments(parent))

    def _comparison_read(self, read: ast.Name, parent: ast.Compare) -> bool:
        if all(isinstance(operator, ast.Is | ast.IsNot | ast.Eq | ast.NotEq) for operator in parent.ops):
            return True
        return (
            read in parent.comparators
            and all(isinstance(operator, ast.In | ast.NotIn) for operator in parent.ops)
            and self._raw_annotation(self.parameter(read))
        )

    def parameter(self, node: ast.expr, *, depth: int = 0) -> ast.arg | None:
        if depth >= _MAX_DEPTH:
            return None
        if isinstance(node, ast.Name):
            binding = self.facts.provenance.runtime_binding(node.id, node)
            if isinstance(binding, ast.arg):
                return binding
            if isinstance(binding, ast.Name):
                value = self.assigned(binding, node)
                return self.parameter(value, depth=depth + 1) if value is not None else None
        receiver = _projection_receiver(node)
        parameter = self.parameter(receiver, depth=depth + 1) if receiver is not None else None
        return parameter if self._raw_annotation(parameter) else None

    def assigned(self, binding: ast.Name, at: ast.AST) -> ast.expr | None:
        value = self.facts.provenance.assignment_value(binding, at)
        if value is not None:
            return value
        statement = self.context.parents.get(binding)
        if (isinstance(statement, ast.Assign) and len(statement.targets) == 1) or isinstance(statement, ast.AnnAssign):
            value = statement.value
        else:
            return None
        return value if value is not None and _statement_dominates(statement, at, self.context) else None

    def _raw_annotation(self, parameter: ast.arg | None) -> bool:
        return (
            parameter is not None
            and parameter.annotation is not None
            and _unchecked_input(_Refinement(parameter.annotation, self.facts, parameter.annotation))
        )

    def _guard(self, expression: ast.expr) -> bool:
        return self._refinement(expression) is not None

    def _raw_mapping(self, parameter: ast.arg | None) -> bool:
        if not self._raw_annotation(parameter) or parameter is None or parameter.annotation is None:
            return False
        return _unchecked_input(_Refinement(parameter.annotation, self.facts, parameter.annotation), mapping=True)

    def _refinement(self, expression: ast.expr) -> _Refinement | None:
        if isinstance(expression, ast.Name):
            binding = self.facts.provenance.runtime_binding(expression.id, expression)
            if isinstance(binding, ast.FunctionDef) and self._stable_function(binding):
                annotation = self.context.annotation_semantics.parse(binding.returns)
                if (
                    isinstance(annotation, ast.Subscript)
                    and binding.returns is not None
                    and self.facts.qualified(annotation.value, binding.returns) in REFINEMENT_TYPES
                ):
                    return _Refinement(annotation.slice, self.facts, binding.returns)
                return None
        qualified = self.facts.qualified(expression, expression)
        if qualified is None or len(self.guards) >= _MAX_GUARDS:
            return None
        if qualified not in self.guards:
            self.guards[qualified] = self._imported_guard(qualified)
        return self.guards[qualified]

    def _imported_guard(self, qualified: str) -> _Refinement | None:
        source = self._imported_source(qualified)
        if source is None:
            return None
        owner, function = source
        if function.returns is None:
            return None
        facts = owner.facts
        annotation = owner.context.annotation_semantics.parse(function.returns)
        if (
            isinstance(annotation, ast.Subscript)
            and facts.qualified(annotation.value, function.returns) in REFINEMENT_TYPES
        ):
            return _Refinement(annotation.slice, facts, function.returns)
        return None

    def _source(self, expression: ast.expr) -> tuple[OpaqueContractFacts, ast.FunctionDef] | None:
        if isinstance(expression, ast.Name):
            binding = self.facts.provenance.runtime_binding(expression.id, expression)
            if isinstance(binding, ast.FunctionDef) and self._stable_function(binding):
                return self, binding
        qualified = self.facts.qualified(expression, expression)
        return self._imported_source(qualified) if qualified is not None else None

    def _imported_source(self, qualified: str) -> tuple[OpaqueContractFacts, ast.FunctionDef] | None:
        module, _, name = qualified.rpartition(".")
        path = self.context.session.local_source.resolve_module(
            self.context.path, module, 0, facts=self.context.session.first_party
        )
        if path is not None and (owner := self.modules.get(path.resolve())) is not None:
            return owner.export(name)
        if len(self.modules) >= _MAX_GUARDS:
            return None
        loaded = self.context.session.local_source.read_module(path) if path is not None else None
        if loaded is None:
            return None
        from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- source loading runs after AnalysisSession initialization.

        context = PythonFileContext(loaded.path, loaded.source, self.context.session)
        owner = OpaqueContractFacts(context, MappingShapeFacts(context), modules=self.modules, budget=self.budget)
        return owner.export(name)

    def export(self, name: str) -> tuple[OpaqueContractFacts, ast.FunctionDef] | None:
        bindings = self.facts.provenance.bindings.get(self.context.tree, {}).get(name, ())
        if len(bindings) != 1 or not isinstance(bindings[0], ast.FunctionDef):
            return None
        function = bindings[0]
        return (self, function) if self._stable_function(function) else None

    def _stable_function(self, function: ast.FunctionDef) -> bool:
        provenance = self.facts.provenance
        return (
            not function.decorator_list
            and not provenance.wildcard
            and not provenance.dynamic_namespace
            and function.name not in provenance.mutated
            and function.name not in provenance.external_bindings
        )

    def call_origin(self, call: ast.Call, origins: _RawOrigins) -> _Origin | None:
        source = self._source(call.func)
        if source is None:
            return None
        owner, function = source
        annotation = function.returns
        if annotation is None or not _raw_output(annotation, owner.facts, annotation):
            return None
        positional = (*function.args.posonlyargs, *function.args.args)
        arguments = call_arguments(call, tuple(parameter.arg for parameter in positional))
        raw = owner.raw_parameters(function, owner.checked_parameters(function))
        dependent = (
            arguments is not None
            and bool(raw)
            and all(
                parameter.arg in arguments
                and origins.value(arguments[parameter.arg])
                in {_Origin.CHECKED_INPUT, _Origin.UNKNOWN_VALUE, _Origin.CARRIER}
                for parameter in raw
            )
        )
        return owner.result(function, independent=not dependent)

    def narrowed(self, value: ast.expr) -> _Origin | None:
        return next(
            (
                origin
                for test, positive in self._conditions(value)
                if (origin := self._narrowing(test, value, positive=positive)) is not None
            ),
            None,
        )

    def _conditions(self, value: ast.expr) -> list[tuple[ast.expr, bool]]:
        conditions: list[tuple[ast.expr, bool]] = []
        current: ast.AST = value
        while (parent := self.context.parents.get(current)) is not None:
            if (condition := _control_condition(current, parent)) is not None:
                conditions.append(condition)
            if isinstance(current, ast.stmt):
                conditions.extend(_preceding_conditions(current, parent))
            if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
                break
            current = parent
        return conditions

    def refined_key(self, value: ast.Name) -> _Origin | None:
        for test, positive in self._conditions(value):
            if (origin := self._key_narrowing(test, value, positive=positive)) is not None:
                return origin
        return None

    def _key_narrowing(self, test: ast.expr, value: ast.Name, *, positive: bool, depth: int = 0) -> _Origin | None:
        if depth >= _MAX_DEPTH or _literal_truth(test) is not None:
            return None
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return self._key_narrowing(test.operand, value, positive=not positive, depth=depth + 1)
        if isinstance(test, ast.BoolOp):
            paths = _boolean_paths(test, positive=positive)
            return _joined_narrowing(
                [self._key_narrowing(member, value, positive=positive, depth=depth + 1) for member in paths.branches],
                required=paths.all_required,
                unchecked=_Origin.UNKNOWN_VALUE,
            )
        if positive and isinstance(test, ast.Call) and test.args and self._same_binding(test.args[0], value):
            refinement = self._refinement(test.func)
            return _key_contract(refinement) if refinement is not None else None
        return None

    def _narrowing(self, test: ast.expr, value: ast.expr, *, positive: bool, depth: int = 0) -> _Origin | None:
        if depth >= _MAX_DEPTH or _literal_truth(test) is not None:
            return None
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return self._narrowing(test.operand, value, positive=not positive, depth=depth + 1)
        if isinstance(test, ast.BoolOp):
            paths = _boolean_paths(test, positive=positive)
            return _joined_narrowing(
                [self._narrowing(member, value, positive=positive, depth=depth + 1) for member in paths.branches],
                required=paths.all_required,
                unchecked=_Origin.CHECKED_INPUT,
            )
        if (
            not positive
            or not isinstance(test, ast.Call)
            or not test.args
            or not self._same_binding(test.args[0], value)
        ):
            return None
        if self._isinstance(test):
            return (
                _Origin.CHECKED_INPUT if _runtime_container(test.args[1], self.facts, test) else _Origin.CHECKED_VALUE
            )
        refinement = self._refinement(test.func)
        if refinement is not None:
            return _Origin.CHECKED_INPUT if _unchecked_target(refinement) else _Origin.CHECKED_VALUE
        return None

    def _same_binding(self, subject: ast.expr, value: ast.expr) -> bool:
        if isinstance(subject, ast.Name) and isinstance(value, ast.Name):
            provenance = self.facts.provenance
            binding = provenance.runtime_binding(subject.id, subject)
            return binding is not None and binding is provenance.runtime_binding(value.id, value)
        return (
            isinstance(subject, ast.Attribute)
            and isinstance(value, ast.Attribute)
            and subject.attr == value.attr
            and self._same_binding(subject.value, value.value)
        )

    def raw_parameters(self, function: _Function, checked: frozenset[ast.arg]) -> frozenset[ast.arg]:
        if function in self.raw_checked:
            return self.raw_checked[function]
        self.raw_checked[function] = frozenset()
        if not self.budget.acquire():
            return frozenset()
        try:
            result = self._find_raw_parameters(function, checked)
        finally:
            self.budget.release()
        self.raw_checked[function] = result
        return result

    def _find_raw_parameters(self, function: _Function, checked: frozenset[ast.arg]) -> frozenset[ast.arg]:
        raw: set[ast.arg] = set()
        raw.update(parameter for parameter in checked if self._raw_annotation(parameter))
        for node in direct_nodes(function):
            if not isinstance(node, ast.Call) or not self.reachable(node, function):
                continue
            parameter = self.parameter(node.args[0]) if node.args else None
            if parameter is not None and parameter in checked and self._raw_guard(node):
                raw.add(parameter)
            raw.update(self._delegated_raw(node, checked))
        return frozenset(raw)

    def _raw_guard(self, call: ast.Call) -> bool:
        if self._isinstance(call):
            return _runtime_container(call.args[1], self.facts, call)
        refinement = self._refinement(call.func)
        return refinement is not None and _unchecked_target(refinement)

    def _delegated_raw(self, call: ast.Call, checked: frozenset[ast.arg]) -> set[ast.arg]:
        if not any(self.parameter(value) in checked for value in (*call.args, *(item.value for item in call.keywords))):
            return set()
        source = self._source(call.func)
        if source is None:
            return set()
        owner, target = source
        positional = (*target.args.posonlyargs, *target.args.args)
        arguments = call_arguments(call, tuple(argument.arg for argument in positional))
        if arguments is None:
            return set()
        found: set[ast.arg] = set()
        for formal in owner.raw_parameters(target, owner.checked_parameters(target)):
            actual = arguments.get(formal.arg)
            delegated = self.parameter(actual) if actual is not None else None
            if delegated is not None and delegated in checked:
                found.add(delegated)
        return found

    def parser(self, call: ast.Call) -> bool:
        if self.facts.qualified(call.func, call) in _PARSERS:
            return True
        if not isinstance(call.func, ast.Attribute) or call.func.attr not in {"decode", "raw_decode"}:
            return False
        receiver = call.func.value
        if not isinstance(receiver, ast.Name):
            return False
        binding = self.facts.provenance.runtime_binding(receiver.id, receiver)
        if isinstance(binding, ast.arg) and binding.annotation is not None:
            return self.facts.qualified(binding.annotation, binding.annotation) in _DECODERS
        if isinstance(binding, ast.Name):
            value = self.facts.provenance.assignment_value(binding, receiver)
            return isinstance(value, ast.Call) and self.facts.qualified(value.func, value) in _DECODERS
        return False


@final
class _RawOrigins:
    def __init__(self, facts: OpaqueContractFacts, function: _Function, parameters: frozenset[ast.arg]) -> None:
        self.facts = facts
        self.function = function
        self.origins: dict[ast.AST, _Origin] = dict.fromkeys(
            facts.raw_parameters(function, parameters) if parameters else (), _Origin.CHECKED_INPUT
        )
        self.iteration_slots: dict[ast.AST, tuple[_Origin, ...]] = {}
        self.nodes = tuple(node for node in direct_nodes(function) if facts.reachable(node, function))
        for _ in range(_ORIGIN_PASSES):
            for node in self.nodes:
                self._propagate(node)

    def _propagate(self, node: ast.AST) -> None:
        match node:
            case (
                ast.Assign(targets=[ast.Name() as target], value=value)
                | ast.AnnAssign(target=ast.Name() as target, value=value)
            ) if value is not None:
                if (origin := self.value(value)) is not None:
                    self.origins[target] = origin
            case ast.For(target=target, iter=iterator) | ast.comprehension(target=target, iter=iterator):
                if (origins := self._iterator(iterator)) is not None:
                    self._iteration_targets(target, origins)
            case ast.Assign(targets=[ast.Subscript(value=ast.Name() as receiver)], value=value):
                if self.value(value) is not None and (binding := self._raw_receiver(receiver)) is not None:
                    self.origins[binding] = _Origin.CARRIER
            case _:
                pass

    def _binding(self, node: ast.Name) -> ast.AST | None:
        provenance = self.facts.facts.provenance
        binding = provenance.runtime_binding(node.id, node)
        if binding is None and isinstance(
            provenance.scope(node), ast.DictComp | ast.ListComp | ast.SetComp | ast.GeneratorExp
        ):
            return provenance.binding(node.id, node)
        return binding

    def _raw_receiver(self, receiver: ast.Name) -> ast.AST | None:
        binding = self._binding(receiver)
        if binding is None:
            return None
        if binding in self.origins:
            return binding
        if not isinstance(binding, ast.Name):
            return None
        value = self.facts.assigned(binding, receiver)
        if isinstance(value, ast.Dict | ast.List):
            return binding
        if isinstance(value, ast.Call) and any(
            self.facts.facts.builtin(value.func, kind, value) for kind in ("dict", "list")
        ):
            return binding
        return None

    def _iterator(self, node: ast.expr) -> tuple[_Origin, ...] | None:
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"items", "keys", "values"}
            and self.value(node.func.value) in {_Origin.CHECKED_INPUT, _Origin.UNKNOWN_VALUE, _Origin.CARRIER}
        ):
            key = self._mapping_key(node.func.value)
            if node.func.attr == "items":
                return (key or _Origin.UNKNOWN_VALUE, _Origin.UNKNOWN_VALUE)
            return (key or _Origin.UNKNOWN_VALUE,) if node.func.attr == "keys" else (_Origin.UNKNOWN_VALUE,)
        if self.value(node) not in {_Origin.CHECKED_INPUT, _Origin.UNKNOWN_VALUE, _Origin.CARRIER}:
            return None
        return (self._mapping_key(node) or _Origin.UNKNOWN_VALUE,)

    def _mapping_key(self, node: ast.expr, *, depth: int = 0) -> _Origin | None:
        if depth >= _MAX_DEPTH or not isinstance(node, ast.Name):
            return None
        if (origin := self.facts.refined_key(node)) is not None:
            return origin
        binding = self._binding(node)
        if isinstance(binding, ast.Name):
            value = self.facts.assigned(binding, node)
            return self._mapping_key(value, depth=depth + 1) if value is not None else None
        if not isinstance(binding, ast.arg) or binding.annotation is None:
            return None
        return _key_contract(_Refinement(binding.annotation, self.facts.facts, binding.annotation))

    def _iteration_targets(self, target: ast.expr, origins: tuple[_Origin, ...]) -> None:
        if isinstance(target, ast.Name):
            self.origins[target] = origins[0] if len(origins) == 1 else _Origin.CARRIER
            if len(origins) != 1:
                self.iteration_slots[target] = origins
            return
        if isinstance(target, ast.Tuple | ast.List) and len(target.elts) == len(origins):
            for member, origin in zip(target.elts, origins, strict=True):
                self._iteration_targets(member, (origin,))
            return
        if origins == (_Origin.UNKNOWN_VALUE,):
            for member in ast.walk(target):
                if isinstance(member, ast.Name):
                    self.origins[member] = _Origin.UNKNOWN_VALUE

    def value(self, node: ast.expr, *, depth: int = 0) -> _Origin | None:
        if depth >= _MAX_DEPTH:
            return None
        native = self._native_value(node)
        if native.handled:
            return native.origin
        match node:
            case ast.Name():
                binding = self._binding(node)
                origin = self.origins.get(binding) if binding is not None else None
                return (self.facts.narrowed(node) or origin) if origin is not None else None
            case ast.Subscript(value=ast.Name() as receiver) if (
                binding := self._binding(receiver)
            ) is not None and binding in self.iteration_slots:
                return self._iteration_slot(node, self.iteration_slots[binding])
            case ast.Subscript(value=receiver):
                return self._child(receiver, depth)
            case ast.Call() if self.facts.parser(node):
                return _Origin.UNKNOWN_VALUE
            case ast.Call(func=ast.Attribute(value=receiver, attr="get")):
                return self._child(receiver, depth)
            case ast.Call():
                return self.facts.call_origin(node, self)
            case ast.IfExp():
                return self._conditional_value(node, depth)
            case ast.DictComp(value=value) | ast.ListComp(elt=value) | ast.SetComp(elt=value):
                return _Origin.CARRIER if self.value(value, depth=depth + 1) is not None else None
            case _:
                return None

    def _native_value(self, node: ast.expr) -> _NativeResult:
        if self.facts.native.output(node, self.function):
            return _NativeResult(handled=True, origin=self.facts.narrowed(node) or _Origin.UNKNOWN_VALUE)
        namespace = self.facts.native.namespace(self.function)
        if isinstance(node, ast.Name) and namespace.container(node):
            return _NativeResult(handled=True, origin=_Origin.CARRIER)
        receiver = _projection_receiver(node)
        return _NativeResult(handled=receiver is not None and namespace.known(receiver), origin=None)

    def _conditional_value(self, node: ast.IfExp, depth: int) -> _Origin | None:
        first = self.value(node.body, depth=depth + 1)
        second = self.value(node.orelse, depth=depth + 1)
        if first is second:
            return first
        if first is not None and _fallback(node.orelse, self.facts.context):
            return first
        return second if second is not None and _fallback(node.body, self.facts.context) else None

    def _child(self, receiver: ast.expr, depth: int) -> _Origin | None:
        origin = self.value(receiver, depth=depth + 1)
        return _Origin.UNKNOWN_VALUE if origin is not None and origin is not _Origin.CHECKED_VALUE else None

    def _iteration_slot(self, node: ast.Subscript, slots: tuple[_Origin, ...]) -> _Origin | None:
        index = node.slice.value if isinstance(node.slice, ast.Constant) else None
        if isinstance(index, int) and -len(slots) <= index < len(slots):
            return slots[index]
        return _Origin.UNKNOWN_VALUE if all(origin is _Origin.UNKNOWN_VALUE for origin in slots) else None


def _projection_receiver(node: ast.expr) -> ast.expr | None:
    match node:
        case ast.Subscript(value=receiver):
            return receiver
        case ast.Call(func=ast.Attribute(value=receiver, attr="get"), args=[_, *_]):
            return receiver
        case _:
            return None


def _control_condition(node: ast.AST, parent: ast.AST) -> tuple[ast.expr, bool] | None:
    if isinstance(parent, ast.IfExp):
        accepted, rejected = node is parent.body, node is parent.orelse
    elif isinstance(parent, ast.If):
        accepted, rejected = node in parent.body, node in parent.orelse
    else:
        return None
    return (parent.test, accepted) if accepted or rejected else None


def _literal_truth(node: ast.expr, *, depth: int = 0) -> bool | None:
    if depth >= _MAX_DEPTH:
        return None
    if isinstance(node, ast.Constant):
        if node.value is None:
            return False
        if isinstance(node.value, str | bytes | bool | int | float | complex):
            return bool(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        truth = _literal_truth(node.operand, depth=depth + 1)
        return not truth if truth is not None else None
    if isinstance(node, ast.BoolOp):
        truths = [_literal_truth(member, depth=depth + 1) for member in node.values]
        decisive = isinstance(node.op, ast.Or)
        if decisive in truths:
            return decisive
        return not decisive if all(truth is not None for truth in truths) else None
    return None


def _boolean_paths(node: ast.BoolOp, *, positive: bool) -> _BooleanPaths:
    required = isinstance(node.op, ast.And) is positive
    branches = tuple(member for member in node.values if required or _literal_truth(member) is not (not positive))
    return _BooleanPaths(all_required=required, branches=branches)


def _joined_narrowing(origins: list[_Origin | None], *, required: bool, unchecked: _Origin) -> _Origin | None:
    if not origins:
        return None
    if required:
        if _Origin.CHECKED_VALUE in origins:
            return _Origin.CHECKED_VALUE
        return unchecked if unchecked in origins else None
    if None in origins:
        return None
    return unchecked if unchecked in origins else _Origin.CHECKED_VALUE


def _stops_suite(node: ast.stmt) -> bool:
    return isinstance(node, ast.Return | ast.Raise | ast.Break | ast.Continue) or (
        isinstance(node, ast.Assert) and _literal_truth(node.test) is False
    )


def _reachable_branch(node: ast.AST, parent: ast.AST) -> bool:
    if isinstance(parent, ast.If | ast.IfExp):
        condition = _control_condition(node, parent)
        if condition is not None:
            test, positive = condition
            truth = _literal_truth(test)
            return truth is None or truth is positive
    if isinstance(parent, ast.While) and node in parent.body and _literal_truth(parent.test) is False:
        return False
    if isinstance(parent, ast.BoolOp) and isinstance(node, ast.expr) and node in parent.values:
        preceding = parent.values[: parent.values.index(node)]
        decisive = isinstance(parent.op, ast.Or)
        return all(_literal_truth(member) is not decisive for member in preceding)
    return True


def _key_contract(refinement: _Refinement) -> _Origin | None:
    facts, at = refinement.facts, refinement.annotation
    node = facts.context.annotation_semantics.parse(refinement.target)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        members = [_Refinement(member, facts, at) for member in (node.left, node.right)]
        origins = [
            _key_contract(member)
            or (
                _Origin.UNKNOWN_VALUE
                if _unchecked_input(member) or _unknown_slot(member.target, facts, at)
                else _Origin.CHECKED_VALUE
            )
            for member in members
        ]
        return _Origin.UNKNOWN_VALUE if _Origin.UNKNOWN_VALUE in origins else _Origin.CHECKED_VALUE
    if not isinstance(node, ast.Subscript) or _container_kind(node.value, facts, at) != "mapping":
        return None
    slots = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if len(slots) != _PAIR_ARITY:
        return None
    return _Origin.UNKNOWN_VALUE if _unknown_slot(slots[0], facts, at) else _Origin.CHECKED_VALUE


def _previous_statements(node: ast.stmt, parent: ast.AST) -> tuple[ast.stmt, ...]:
    for statements in _statement_suites(parent):
        if node in statements:
            return tuple(statements[: statements.index(node)])
    return ()


def _preceding_conditions(node: ast.stmt, parent: ast.AST) -> Iterator[tuple[ast.expr, bool]]:
    for sibling in reversed(_previous_statements(node, parent)):
        if isinstance(sibling, ast.Assert):
            yield sibling.test, True
        elif isinstance(sibling, ast.If) and _rejects(sibling.body):
            yield sibling.test, False


def _statement_suites(parent: ast.AST) -> Iterator[list[ast.stmt]]:
    match parent:
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            yield parent.body
            yield parent.orelse
        case ast.Try() | ast.TryStar():
            yield parent.body
            yield parent.orelse
            yield parent.finalbody
        case (
            ast.Module()
            | ast.Interactive()
            | ast.FunctionDef()
            | ast.AsyncFunctionDef()
            | ast.ClassDef()
            | ast.With()
            | ast.AsyncWith()
            | ast.ExceptHandler()
            | ast.match_case()
        ):
            yield parent.body
        case _:
            return


def _statement_dominates(statement: ast.stmt, at: ast.AST, context: PythonFileContext) -> bool:
    owner = context.parents.get(statement)
    if owner is None or statement.lineno >= source_position(at)[0]:
        return False
    current = at
    while (parent := context.parents.get(current)) is not None:
        if parent is owner:
            return isinstance(current, ast.stmt) and statement in _previous_statements(current, owner)
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            return False
        current = parent
    return False


def _terminates(body: list[ast.stmt]) -> bool:
    return bool(body) and isinstance(body[-1], ast.Return | ast.Raise)


def _raw_output(node: ast.expr, facts: MappingShapeFacts, at: ast.expr) -> bool:
    parsed = facts.context.annotation_semantics.parse(node)
    if isinstance(parsed, ast.BinOp) and isinstance(parsed.op, ast.BitOr):
        return _raw_output(parsed.left, facts, at) or _raw_output(parsed.right, facts, at)
    return parsed is not None and (
        _unknown_slot(parsed, facts, at) or _unchecked_target(_Refinement(parsed, facts, at))
    )


def _container_kind(node: ast.expr, facts: MappingShapeFacts, at: ast.AST) -> str | None:
    qualified = facts.qualified(node, at)
    if qualified in _MAPPINGS:
        return "mapping"
    for kind in _CONTAINERS:
        if facts.builtin(node, kind, at) or qualified == f"builtins.{kind}":
            return "mapping" if kind == "dict" else kind
    return None


def _runtime_container(node: ast.expr, facts: MappingShapeFacts, at: ast.AST) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _runtime_container(node.left, facts, at) and _runtime_container(node.right, facts, at)
    if isinstance(node, ast.Tuple):
        return bool(node.elts) and all(_runtime_container(member, facts, at) for member in node.elts)
    return _container_kind(node, facts, at) is not None


def _unchecked_input(refinement: _Refinement, *, mapping: bool = False, depth: int = 0) -> bool:
    if depth >= _MAX_DEPTH:
        return False
    facts, at = refinement.facts, refinement.annotation
    node = facts.context.annotation_semantics.parse(refinement.target)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        members = [_Refinement(member, facts, at) for member in (node.left, node.right)]
        accepted = [_unchecked_input(member, mapping=mapping, depth=depth + 1) for member in members]
        if not mapping:
            return any(accepted)
        unsafe = any(
            not allowed and (_unchecked_input(member, depth=depth + 1) or _unknown_slot(member.target, facts, at))
            for member, allowed in zip(members, accepted, strict=True)
        )
        return any(accepted) and not unsafe
    if mapping and (not isinstance(node, ast.Subscript) or _container_kind(node.value, facts, at) != "mapping"):
        return False
    return node is not None and _unchecked_target(_Refinement(node, facts, at), depth=depth)


def _unchecked_target(refinement: _Refinement, *, depth: int = 0) -> bool:
    if depth >= _MAX_DEPTH:
        return False
    facts, at = refinement.facts, refinement.annotation
    node = facts.context.annotation_semantics.parse(refinement.target)
    if node is None:
        return False
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return all(
            _unchecked_target(_Refinement(member, facts, at), depth=depth + 1) for member in (node.left, node.right)
        )
    if not isinstance(node, ast.Subscript):
        return _container_kind(node, facts, at) is not None
    kind = _container_kind(node.value, facts, at)
    slots = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
    if kind == "mapping":
        return len(slots) == _PAIR_ARITY and _unknown_slot(slots[1], facts, at)
    if kind == "tuple":
        if len(slots) == _PAIR_ARITY and isinstance(slots[-1], ast.Constant) and slots[-1].value is Ellipsis:
            slots.pop()
        return bool(slots) and all(_unknown_slot(slot, facts, at) for slot in slots)
    return kind is not None and len(slots) == 1 and _unknown_slot(slots[0], facts, at)


def _unknown_slot(node: ast.expr, facts: MappingShapeFacts, at: ast.AST) -> bool:
    parsed = facts.context.annotation_semantics.parse(node)
    if parsed is None:
        return False
    if isinstance(parsed, ast.BinOp) and isinstance(parsed.op, ast.BitOr):
        return _unknown_slot(parsed.left, facts, at) or _unknown_slot(parsed.right, facts, at)
    return builtin_object(parsed, facts, at)


def _rejects(body: list[ast.stmt]) -> bool:
    if not body:
        return False
    match body[-1]:
        case (
            ast.Raise()
            | ast.Return(value=None | ast.Constant(value=None | False))
            | ast.Return(value=ast.Dict(keys=[]) | ast.List(elts=[]) | ast.Tuple(elts=[]) | ast.Set(elts=[]))
        ):
            return True
        case _:
            return False


def _class_pattern(pattern: ast.pattern) -> bool:
    return isinstance(pattern, ast.MatchClass) or (
        isinstance(pattern, ast.MatchOr) and any(_class_pattern(member) for member in pattern.patterns)
    )


def _fallback(node: ast.expr | None, context: PythonFileContext) -> bool:
    if node is None or isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Dict | ast.List | ast.Set | ast.Tuple):
        return not (node.keys if isinstance(node, ast.Dict) else node.elts)
    if isinstance(node, ast.Name):
        provenance = context.static_resource_provenance
        binding = provenance.runtime_binding(node.id, node)
        if isinstance(binding, ast.Name):
            value = provenance.assignment_value(binding, node)
            return (
                isinstance(value, ast.Call)
                and not value.args
                and not value.keywords
                and context.imports.builtin_is_unshadowed("object")
                and isinstance(value.func, ast.Name)
                and value.func.id == "object"
            )
    return False
