from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sarj_python_lint.rule_base import Diagnostic, Severity, is_suppressed
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
from sarj_python_lint.rules._closed_helpers import call_matches
from sarj_python_lint.rules._declared_contracts import DeclaredClass, DeclaredContracts, ordinary_pytest_test
from sarj_python_lint.rules._fixture_contracts import (
    CONSTRUCTION_HOOKS,
    MAX_DEPTH,
    abstract_ancestors,
    abstract_contract,
    class_identity_stable,
    compatible_operation,
    contract_accepts,
    has_class_hook,
    method_definition,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._project_index import SourceUnit
from sarj_python_lint.rules._pytest import collected_tests
from sarj_python_lint.rules._test_composition import call_arguments


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules.pytest_fixture_returns_bare_tuple import FixtureDeclaration


type Function = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class _CallSignature:
    function: Function
    unit: SourceUnit
    bound: bool


class FixtureContractParameters:
    def __init__(
        self, context: PythonFileContext, contracts: DeclaredContracts, fixtures: tuple[FixtureDeclaration, ...]
    ) -> None:
        self.context = context
        self.contracts = contracts
        self._imports: dict[ast.Module, ImportIndex] = {}
        self._semantics: dict[ast.Module, AnnotationSemantics] = {}
        self._operations: dict[tuple[ast.ClassDef, ast.ClassDef, str], bool] = {}
        self._ancestors: dict[ast.ClassDef, tuple[DeclaredClass, ...]] = {}
        fixture_functions = {fixture.node: fixture for fixture in fixtures}
        tests = collected_tests(context.tree.body) if context.tree is not None else ()
        functions = tuple(fixture_functions) + tuple(
            function for function in tests if function not in fixture_functions
        )
        self._potential_consumers = tuple(context.nodes(ast.FunctionDef, ast.AsyncFunctionDef))
        self.parameters = tuple(
            (function, tuple(self._injected_parameters(function, fixture=function in fixture_functions)))
            for function in functions
            if self._supported_owner(function, fixture_functions.get(function))
        )

    def findings(self, code: str) -> list[Diagnostic]:
        findings: list[Diagnostic] = []
        for function, parameters in self.parameters:
            for parameter in parameters:
                if (
                    parameter.annotation is None
                    or is_suppressed(self.context.source_lines, function.lineno, code)
                    or is_suppressed(self.context.source_lines, parameter.lineno, code)
                ):
                    continue
                implementation = self._instance(parameter.annotation, self.contracts.unit)
                if implementation is None or abstract_contract(implementation, self.contracts):
                    continue
                candidates = self._candidates(implementation)
                if len(candidates) != 1 or not self.supports_parameter(
                    function, parameter, implementation, candidates[0]
                ):
                    continue
                annotation = parameter.annotation
                findings.append(
                    Diagnostic(
                        self.context.path,
                        annotation.lineno,
                        annotation.col_offset + 1,
                        code,
                        f"Injected `{parameter.arg}` exposes `{implementation.declaration.name}`; use its existing `{candidates[0].declaration.name}` contract for the consumed operations, or retain a reviewed implementation-specific contract.",
                        severity=Severity.ERROR,
                    )
                )
        return findings

    def implementation_consumer(self, name: str, implementation: DeclaredClass, contract: DeclaredClass) -> bool:
        for function in self._potential_consumers:
            parameters = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
            for parameter in parameters:
                if parameter.arg != name:
                    continue
                reads = self.context.static_resource_provenance.binding_reads(name, parameter)
                if reads and not self.supports_parameter(function, parameter, implementation, contract):
                    return True
        return False

    def supported_fixture(self, fixture: FixtureDeclaration) -> bool:
        if not self._supported_owner(fixture.node, fixture):
            return False
        if not isinstance(fixture.decorator, ast.Call):
            return True
        for keyword in fixture.decorator.keywords:
            if keyword.arg is None:
                return False
            if keyword.arg == "name" and not (
                isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)
            ):
                return False
        return True

    def supports_parameter(
        self, function: Function, parameter: ast.arg, implementation: DeclaredClass, contract: DeclaredClass
    ) -> bool:
        return self._binding_supported(parameter.arg, parameter, function, implementation, contract, seen=frozenset())

    def _binding_supported(
        self,
        name: str,
        binding: ast.AST,
        function: Function,
        implementation: DeclaredClass,
        contract: DeclaredClass,
        *,
        seen: frozenset[ast.AST],
    ) -> bool:
        if binding in seen or len(seen) >= MAX_DEPTH or _hidden_consumer(function, name):
            return False
        provenance = self.context.static_resource_provenance
        reads = provenance.binding_reads(name, binding)
        return bool(reads) and all(
            provenance.scope(read) is function
            and self._read_supported(read, function, implementation, contract, seen | {binding})
            for read in reads
        )

    def _read_supported(
        self,
        read: ast.Name,
        function: Function,
        implementation: DeclaredClass,
        contract: DeclaredClass,
        seen: frozenset[ast.AST],
    ) -> bool:
        parent = self.context.parents.get(read)
        match parent:
            case ast.Attribute(value=value) if value is read:
                return self._operation_read_supported(parent, implementation, contract)
            case ast.Assign(value=value, targets=[ast.Name() as target]) if (
                value is read and self.context.parents.get(parent) is function
            ):
                return self._binding_supported(target.id, target, function, implementation, contract, seen=seen)
            case ast.Compare():
                return _none_comparison(parent, read)
            case _:
                pass
        call = (
            parent if isinstance(parent, ast.Call) else self.context.parents.get(parent) if parent is not None else None
        )
        return isinstance(call, ast.Call) and self._forwarded_to_contract(read, call, contract)

    def _operation_read_supported(
        self, member: ast.Attribute, implementation: DeclaredClass, contract: DeclaredClass
    ) -> bool:
        call = self.context.parents.get(member)
        if not isinstance(member.ctx, ast.Load) or not isinstance(call, ast.Call) or call.func is not member:
            return False
        key = (implementation.declaration, contract.declaration, member.attr)
        if key not in self._operations:
            self._operations[key] = compatible_operation(implementation, contract, member.attr, self.contracts)
        return self._operations[key]

    def _forwarded_to_contract(self, value: ast.Name, call: ast.Call, contract: DeclaredClass) -> bool:
        signature = self._call_signature(call)
        if signature is None:
            return False
        function = signature.function
        arguments = function.args
        if arguments.vararg is not None or arguments.kwarg is not None or function.type_params:
            return False
        positional = (*arguments.posonlyargs, *arguments.args)
        if signature.bound and not positional:
            return False
        checked_call = (
            ast.Call(func=call.func, args=[ast.Constant(value=None), *call.args], keywords=call.keywords)
            if signature.bound
            else call
        )
        if not call_matches(function, checked_call):
            return False
        supplied = call_arguments(call, tuple(parameter.arg for parameter in positional[int(signature.bound) :]))
        if supplied is None:
            return False
        formals = {parameter.arg: parameter for parameter in (*positional, *arguments.kwonlyargs)}
        names = [name for name, expression in supplied.items() if expression is value]
        return bool(names) and all(
            (formal := formals.get(name)) is not None
            and formal.annotation is not None
            and self._accepts_contract(formal.annotation, signature, contract)
            for name in names
        )

    def _call_signature(self, call: ast.Call) -> _CallSignature | None:
        model = self.contracts.class_type(call.func)
        if model is not None:
            return self._constructor_signature(model)
        unit = self.contracts.unit
        if unit is None or not self._stable_reference(call.func, unit):
            return None
        root = self._root_name(call.func)
        binding = self.context.static_resource_provenance.binding(root, call.func) if root is not None else None
        if not isinstance(binding, ast.alias | ast.FunctionDef | ast.AsyncFunctionDef):
            return None
        symbol = self.contracts.project.resolve(unit, call.func)
        owner = self.contracts.project.source_unit(symbol.module) if symbol is not None else None
        if symbol is None or owner is None or owner.tree is None:
            return None
        definitions = [
            node
            for node in owner.tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == symbol.name
        ]
        if (
            len(definitions) != 1
            or definitions[0].decorator_list
            or sum(symbol.name in self.contracts.bound_names(statement) for statement in owner.tree.body) != 1
            or (isinstance(binding, ast.FunctionDef | ast.AsyncFunctionDef) and definitions[0] is not binding)
        ):
            return None
        return _CallSignature(definitions[0], owner, bound=False)

    def _constructor_signature(self, model: DeclaredClass) -> _CallSignature | None:
        if has_class_hook(model, self.contracts, CONSTRUCTION_HOOKS):
            return None
        definition = method_definition(model, "__init__", self.contracts)
        if definition is None or definition.declaration.decorator_list:
            return None
        return _CallSignature(definition.declaration, definition.owner.unit, bound=True)

    def _accepts_contract(self, annotation: ast.expr, signature: _CallSignature, contract: DeclaredClass) -> bool:
        model = self._instance(annotation, signature.unit)
        if model is None or self._class_annotation_shadowed(annotation, signature):
            return False
        return class_identity_stable(model, self.contracts) and contract_accepts(contract, model, self.contracts)

    def _instance(self, annotation: ast.expr, unit: SourceUnit | None) -> DeclaredClass | None:
        if unit is None or unit.tree is None:
            return None
        semantics = self._unit_semantics(unit)
        parsed = semantics.resolve_alias(annotation)
        if not isinstance(parsed, ast.Name | ast.Attribute) or not self._stable_reference(parsed, unit):
            return None
        model = self.contracts.annotation(annotation, unit)
        if (
            model is None
            or model.declaration.type_params
            or any(isinstance(base, ast.Subscript) for base in model.declaration.bases)
        ):
            return None
        return model

    def _unit_semantics(self, unit: SourceUnit) -> AnnotationSemantics:
        if unit.tree is None:
            return self.context.annotation_semantics
        if unit.tree not in self._imports:
            self._imports[unit.tree] = ImportIndex.from_tree(unit.tree, module_scope_only=True)
            self._semantics[unit.tree] = AnnotationSemantics.from_imports(unit.tree, self._imports[unit.tree])
        return self._semantics[unit.tree]

    def _stable_reference(self, expression: ast.expr, unit: SourceUnit) -> bool:
        root = expression
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name) or unit.tree is None:
            return False
        self._unit_semantics(unit)
        imports = self._imports[unit.tree]
        if root.id in unit.imports:
            if root.id in imports.shadowed_names:
                return False
            return not any(
                isinstance(node, ast.Attribute)
                and not isinstance(node.ctx, ast.Load)
                and self._root_name(node) == root.id
                for node in ast.walk(unit.tree)
            )
        return True

    @staticmethod
    def _root_name(node: ast.expr) -> str | None:
        while isinstance(node, ast.Attribute | ast.Subscript):
            node = node.value
        return node.id if isinstance(node, ast.Name) else None

    def _class_annotation_shadowed(self, annotation: ast.expr, signature: _CallSignature) -> bool:
        unit = signature.unit
        if unit.tree is None:
            return True
        semantics = self._unit_semantics(unit)
        parsed = semantics.parse(annotation)
        resolved = semantics.resolve_alias(annotation)
        roots = {self._root_name(node) for node in (parsed, resolved) if node is not None}
        for node in unit.tree.body:
            if isinstance(node, ast.ClassDef) and signature.function in node.body:
                return any(roots & self.contracts.bound_names(statement) for statement in node.body)
        return False

    def _candidates(self, implementation: DeclaredClass) -> tuple[DeclaredClass, ...]:
        if implementation.declaration not in self._ancestors:
            self._ancestors[implementation.declaration] = abstract_ancestors(implementation, self.contracts)
        return self._ancestors[implementation.declaration]

    def _supported_owner(self, function: Function, fixture: FixtureDeclaration | None) -> bool:
        if function.type_params or self.context.tree is None or self.context.dynamic_namespace:
            return False
        owner = self.context.parents.get(function)
        if not isinstance(owner, ast.Module | ast.ClassDef) or _disabled_member(owner.body, function.name):
            return False
        if self.context.static_resource_provenance.bindings.get(owner, {}).get(function.name) != (function,):
            return False
        current = owner
        while isinstance(current, ast.ClassDef):
            parent = self.context.parents.get(current)
            if (
                not _plain_test_class(current)
                or current.name in self.context.static_resource_provenance.mutated
                or _collection_disabled(current.body)
                or (isinstance(parent, ast.Module | ast.ClassDef) and _disabled_member(parent.body, current.name))
            ):
                return False
            current = parent
        if _collection_disabled(self.context.tree.body):
            return False
        if fixture is None:
            return (
                ordinary_pytest_test(function, self.context)
                and not self._has_generation_hook(function)
                and not self._owned_mark(function)
            )
        return all(
            decorator is fixture.decorator
            or (
                (
                    qualified := self.context.imports.resolved_qualified_name(
                        decorator.func if isinstance(decorator, ast.Call) else decorator
                    )
                )
                is not None
                and qualified.startswith("pytest.mark.")
            )
            for decorator in function.decorator_list
        )

    def _injected_parameters(self, function: Function, *, fixture: bool) -> Iterator[ast.arg]:
        excluded: set[str] | None = set() if fixture else self._parametrized(function)
        if excluded is None:
            return
        arguments = function.args
        positional = (*arguments.posonlyargs, *arguments.args)
        defaulted = {argument.arg for argument in positional[len(positional) - len(arguments.defaults) :]}
        owner = self.context.parents.get(function)
        receiver = positional[0] if isinstance(owner, ast.ClassDef) and positional else None
        for argument in arguments.args:
            if argument is not receiver and argument.arg not in defaulted | excluded:
                yield argument
        for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True):
            if default is None and argument.arg not in excluded:
                yield argument

    def _parametrized(self, function: Function) -> set[str] | None:
        names: set[str] = set()
        for mark in self._marks(function):
            parsed = self._mark_parameters(mark)
            if parsed is None:
                return None
            names.update(parsed)
        return names

    def _marks(self, function: Function) -> list[ast.expr]:
        marks: list[ast.expr] = list(function.decorator_list)
        for statements in self._scope_statements(function):
            for statement in statements:
                value = _named_assignment_value(statement, "pytestmark")
                if value is not None:
                    marks.extend(value.elts if isinstance(value, ast.List | ast.Tuple) else [value])
        return marks

    def _scope_statements(self, function: Function) -> Iterator[list[ast.stmt]]:
        owner = self.context.parents.get(function)
        while isinstance(owner, ast.ClassDef):
            yield owner.body
            owner = self.context.parents.get(owner)
        if self.context.tree is not None:
            yield self.context.tree.body

    def _has_generation_hook(self, function: Function) -> bool:
        owner = self.context.parents.get(function)
        bindings = self.context.static_resource_provenance.bindings
        while isinstance(owner, ast.Module | ast.ClassDef):
            if "pytest_generate_tests" in bindings.get(owner, {}):
                return True
            owner = self.context.parents.get(owner)
        return False

    def _owned_mark(self, function: Function) -> bool:
        return any(
            node.attr == "pytestmark" and isinstance(node.value, ast.Name) and node.value.id == function.name
            for node in self.context.nodes(ast.Attribute)
        )

    def _mark_parameters(self, mark: ast.expr) -> set[str] | None:
        target = mark.func if isinstance(mark, ast.Call) else mark
        qualified = self.context.imports.resolved_qualified_name(target)
        if qualified is None or not qualified.startswith("pytest.mark."):
            return None
        if qualified != "pytest.mark.parametrize":
            return set()
        if not isinstance(mark, ast.Call) or any(keyword.arg is None for keyword in mark.keywords):
            return None
        expression = (
            mark.args[0]
            if mark.args
            else next((keyword.value for keyword in mark.keywords if keyword.arg == "argnames"), None)
        )
        names = _case_names(expression)
        if names is None:
            return None
        return _direct_case_names(mark, names)


def _hidden_consumer(function: Function, name: str) -> bool:
    for node in ast.walk(function):
        if isinstance(node, ast.Nonlocal) and name in node.names:
            return True
        if isinstance(node, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) and any(
            isinstance(read, ast.Name) and read.id == name and isinstance(read.ctx, ast.Load)
            for read in ast.walk(node.generators[0].iter)
        ):
            return True
    return False


def _direct_case_names(mark: ast.Call, names: set[str]) -> set[str] | None:
    indirect = next((keyword.value for keyword in mark.keywords if keyword.arg == "indirect"), None)
    if indirect is None or (isinstance(indirect, ast.Constant) and indirect.value is False):
        return names
    if isinstance(indirect, ast.Constant) and indirect.value is True:
        return set()
    indirect_names = _case_names(indirect) if isinstance(indirect, ast.List | ast.Tuple) else None
    return names - indirect_names if indirect_names is not None and indirect_names <= names else None


def _case_names(node: ast.expr | None) -> set[str] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {name.strip() for name in node.value.split(",")}
    if not isinstance(node, ast.List | ast.Tuple) or not all(
        isinstance(element, ast.Constant) and isinstance(element.value, str) for element in node.elts
    ):
        return None
    return {
        element.value for element in node.elts if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }


def _none_comparison(comparison: ast.Compare, read: ast.Name) -> bool:
    if len(comparison.ops) != 1 or len(comparison.comparators) != 1:
        return False
    other = comparison.comparators[0] if comparison.left is read else comparison.left
    return isinstance(comparison.ops[0], ast.Is | ast.IsNot) and isinstance(other, ast.Constant) and other.value is None


def _plain_test_class(owner: ast.ClassDef) -> bool:
    return (
        owner.name.startswith("Test")
        and not owner.bases
        and not owner.decorator_list
        and not owner.keywords
        and not any(
            isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and member.name in {"__init__", "__new__"}
            for member in owner.body
        )
    )


def _disabled_member(statements: list[ast.stmt], name: str) -> bool:
    return any(_member_disabled(statement, name) for statement in statements)


def _member_disabled(statement: ast.stmt, name: str) -> bool:
    match statement:
        case ast.Assign(targets=targets, value=value):
            return any(_test_flag(target, name) for target in targets) and not _known_true(value)
        case ast.AnnAssign(target=target, value=value) if value is not None:
            return _test_flag(target, name) and not _known_true(value)
        case _:
            return False


def _test_flag(target: ast.expr, name: str) -> bool:
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "__test__"
        and isinstance(target.value, ast.Name)
        and target.value.id == name
    )


def _known_true(value: ast.expr) -> bool:
    return isinstance(value, ast.Constant) and value.value is True


def _collection_disabled(statements: list[ast.stmt]) -> bool:
    return any(
        (value := _named_assignment_value(statement, "__test__")) is not None and not _known_true(value)
        for statement in statements
    )


def _named_assignment_value(statement: ast.stmt, name: str) -> ast.expr | None:
    match statement:
        case ast.Assign(targets=targets, value=value) if any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            return value
        case ast.AnnAssign(target=ast.Name(id=bound), value=value) if bound == name:
            return value
        case _:
            return None
