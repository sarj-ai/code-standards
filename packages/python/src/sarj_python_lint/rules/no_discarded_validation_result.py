from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import cached_property
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, final, override

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
)
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
_MAX_REEXPORTS = 8
_MAX_ALIASES = 8
_TEST_CASES = frozenset(
    {
        "unittest.TestCase",
        "unittest.case.TestCase",
        "unittest.IsolatedAsyncioTestCase",
        "unittest.async_case.IsolatedAsyncioTestCase",
    }
)
_EXCEPTION_ASSERTIONS = frozenset({"assertRaises", "assertRaisesRegex"})


@dataclass(frozen=True, slots=True)
class _AssertionWrites:
    bindings: frozenset[tuple[ast.AST, str]]
    instances: frozenset[tuple[ast.ClassDef, str]]


@dataclass(frozen=True, slots=True)
class _ResolvedValidation:
    owner: "PythonFileContext"
    function: _Function
    namespaces: tuple[ResourceProvenance, ...]


@final
class NoDiscardedValidationResult(Rule):
    id = "no-discarded-validation-result"
    code = "SARJ519"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Consume a value-producing validator's result instead of relying on its exceptions.",
        rationale="Discarding a conversion's returned value makes validation an implicit exception side effect. The caller can continue with unvalidated or unnormalized inputs even after constructing a checked replacement.",
        remediation="Use the checked result in the following operation, or expose a separate validation command returning None. Preserve exception behavior; do not delete the call or add a dummy assignment.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Reports standalone calls to source-resolved, undecorated Python functions with a non-None return annotation, value returns, and an explicit raise.",
            "Local and imported functions, import aliases, bounded re-exports, and directly awaited async functions are supported; unknown receivers, decorated callables, and dynamic namespaces are excluded.",
            "Compiler scopes select runtime bindings; observed global/nonlocal reassignment and ambiguous scopes are excluded. Import identity is established without executing provider modules.",
            "Observed first-party namespace writes and opaque module escapes invalidate affected providers across aliases, self imports and re-exports; package namespace hazards conservatively cover descendants.",
            "Source-proven unittest.mock.patch APIs invalidate static contracts in the caller and provider/re-export modules, including string-target patches. Ordinary locally named patch functions do not disable checks.",
            "Stable local callable aliases with prior direct assignments are followed through bounded chains. Conditional assignments and unresolved callable escapes are excluded.",
            "Direct execution in class bodies is excluded because sequential lookup and metaclass-prepared namespaces can supply different callees. Method bodies remain checked.",
            "Functions with explicit mutation, standalone command calls, generators, nested definitions, or context-manager/try/loop orchestration are excluded. This is not a general purity proof.",
            "Import-resolved pytest.raises and source-proven unittest exception assertion blocks observe the exception contract and are excluded. Generated and vendored sources are excluded; maintained tests are checked.",
            "Optional, Any, Never, and NoReturn return contracts are excluded. No automatic assignment, deletion, or validation rewrite is offered.",
        ),
        examples=(
            RuleExample(
                example_id="discarded-checked-value",
                title="A checked replacement is constructed and discarded",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/counts.py",
                        "def checked_count(raw: str) -> int:\n    if not raw:\n        raise ValueError('empty count')\n    return int(raw)\ndef save(raw: str) -> None:\n    checked_count(raw)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/counts.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="consume-checked-value",
                title="Pass the validated replacement to the next operation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/counts.py",
                        "def checked_count(raw: str) -> int:\n    if not raw:\n        raise ValueError('empty count')\n    return int(raw)\ndef save(raw: str) -> int:\n    return checked_count(raw)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/counts.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None:
            return []
        calls = [
            (node, node.value.value if isinstance(node.value, ast.Await) else node.value)
            for node in context.nodes(ast.Expr)
            if isinstance(node.value, ast.Call)
            or (isinstance(node.value, ast.Await) and isinstance(node.value.value, ast.Call))
        ]
        if not calls:
            return []
        analysis = _ValidationResults(context)
        return [
            Diagnostic(
                path=context.path,
                line=statement.lineno,
                col=statement.col_offset + 1,
                code=self.code,
                message="This value-producing validator's result is discarded; consume the checked value or use a validation command returning None.",
                severity=Severity.WARNING,
            )
            for statement, call in calls
            if isinstance(call, ast.Call)
            and not is_suppressed(context.source_lines, statement.lineno, self.code)
            and analysis.discarded(statement, call)
        ]


@final
class _ValidationResults:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = ResourceProvenance(context, require_static_namespace=True)
        self.owners: dict[Path, tuple[PythonFileContext, ResourceProvenance]] = {}
        self.contracts: dict[_Function, bool] = {}

    def discarded(self, statement: ast.Expr, call: ast.Call) -> bool:
        if self.provenance.dynamic_namespace or self.provenance.wildcard or self._expected_exception(statement):
            return False
        resolved = self._resolve(call.func)
        if resolved is None:
            return False
        owner, function = resolved.owner, resolved.function
        if isinstance(function, ast.AsyncFunctionDef) != isinstance(statement.value, ast.Await):
            return False
        if function not in self.contracts:
            self.contracts[function] = not owner.generated and _value_validator(function)
        return self.contracts[function] and not any(
            _namespace_uncertain(provenance, owner.path) or _namespace_uncertain(provenance, provenance.context.path)
            for provenance in resolved.namespaces
        )

    def _resolve(self, expression: ast.expr) -> _ResolvedValidation | None:
        if isinstance(self.provenance.scope(expression), ast.ClassDef):
            return None
        followed = self._follow_aliases(expression)
        if followed is None:
            return None
        expression = followed
        if isinstance(expression, ast.Name):
            binding = self.provenance.runtime_binding(expression.id, expression)
            if isinstance(binding, ast.FunctionDef | ast.AsyncFunctionDef):
                owner = self.context.parents.get(binding)
                return (
                    _ResolvedValidation(self.context, binding, (self.provenance,))
                    if isinstance(owner, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef)
                    else None
                )
        attributes: list[str] = []
        root = expression
        while isinstance(root, ast.Attribute):
            attributes.append(root.attr)
            root = root.value
        if not isinstance(root, ast.Name):
            return None
        binding = self.provenance.runtime_binding(root.id, expression)
        if not isinstance(binding, ast.alias):
            return None
        qualified = self.provenance.runtime_import_name(expression)
        if qualified is None:
            parent = self.context.parents.get(binding)
            if not (
                isinstance(parent, ast.ImportFrom)
                and parent.level > 0
                and parent.module is None
                and self.provenance.scope(binding) is self.context.tree
                and root.id not in self.provenance.mutated
            ):
                return None
        location = self._import_location(self.context, binding, tuple(reversed(attributes)))
        return self._imported_function(location) if location is not None else None

    def _follow_aliases(self, expression: ast.expr) -> ast.expr | None:
        seen: set[ast.AST] = set()
        for _ in range(_MAX_ALIASES):
            if not isinstance(expression, ast.Name):
                return expression
            binding = self.provenance.runtime_binding(expression.id, expression)
            if not isinstance(binding, ast.Name):
                return expression
            if binding in seen:
                return None
            seen.add(binding)
            value = self.provenance.assignment_value(binding, expression)
            if not isinstance(value, ast.Name | ast.Attribute):
                return None
            expression = value
        return None

    def _import_location(
        self, owner: PythonFileContext, binding: ast.alias, attributes: tuple[str, ...] = ()
    ) -> tuple[Path, str] | None:
        parent = owner.parents.get(binding)
        match parent:
            case ast.ImportFrom(module=module, level=level):
                parts = (*((module,) if module else ()), *((binding.name, *attributes[:-1]) if attributes else ()))
                module = ".".join(parts)
                name = attributes[-1] if attributes else binding.name
            case ast.Import() if attributes:
                prefix = binding.name if binding.asname else binding.name.partition(".")[0]
                module, name, level = ".".join((prefix, *attributes[:-1])), attributes[-1], 0
            case _:
                return None
        path = owner.session.local_source.resolve_module(owner.path, module, level, facts=owner.session.first_party)
        return (path, name) if path is not None else None

    def _imported_function(self, location: tuple[Path, str]) -> _ResolvedValidation | None:
        from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- avoid the registry and analysis-session import cycle.

        seen: set[tuple[Path, str]] = set()
        namespaces = [self.provenance]
        for _ in range(_MAX_REEXPORTS):
            if location in seen:
                return None
            seen.add(location)
            path, name = location
            module = self.context.session.local_source.read_module(path)
            if module is None:
                return None
            if path not in self.owners:
                owner = PythonFileContext(path, module.source, self.context.session)
                self.owners[path] = owner, ResourceProvenance(owner, require_static_namespace=True)
            owner, provenance = self.owners[path]
            if provenance.dynamic_namespace or provenance.wildcard or name in provenance.mutated:
                return None
            namespaces.append(provenance)
            bindings = provenance.bindings.get(owner.tree, {}).get(name, ())
            if len(bindings) != 1:
                return None
            [binding] = bindings
            if provenance.runtime_binding(name, binding) is not binding:
                return None
            if isinstance(binding, ast.FunctionDef | ast.AsyncFunctionDef):
                return _ResolvedValidation(owner, binding, tuple(namespaces))
            if not isinstance(binding, ast.alias):
                return None
            next_location = self._import_location(owner, binding)
            if next_location is None:
                return None
            location = next_location
        return None

    def _expected_exception(self, node: ast.AST) -> bool:
        parent = self.context.parents.get(node)
        while parent is not None and not isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
            if isinstance(parent, ast.With) and any(
                isinstance(item.context_expr, ast.Call)
                and (
                    self.provenance.runtime_import_name(item.context_expr.func) == "pytest.raises"
                    or self._unittest_assertion(item.context_expr)
                )
                for item in parent.items
            ):
                return True
            parent = self.context.parents.get(parent)
        return False

    def _unittest_assertion(self, call: ast.Call) -> bool:
        if not isinstance(call.func, ast.Attribute) or call.func.attr not in _EXCEPTION_ASSERTIONS:
            return False
        receiver = call.func.value
        seen: set[ast.AST] = set()
        for _ in range(_MAX_ALIASES):
            if isinstance(receiver, ast.Call):
                return self.provenance.runtime_import_name(receiver.func) in _TEST_CASES
            if not isinstance(receiver, ast.Name):
                return False
            binding = self.provenance.runtime_binding(receiver.id, receiver)
            if binding is None or binding in seen or self._assertion_modified(binding, call.func.attr):
                return False
            if isinstance(binding, ast.arg):
                return self._unittest_method(binding, call.func.attr)
            if not isinstance(binding, ast.Name):
                return False
            seen.add(binding)
            value = self.provenance.assignment_value(binding, receiver)
            if value is None:
                return False
            receiver = value
        return False

    def _unittest_method(self, binding: ast.arg, assertion: str) -> bool:
        arguments = self.context.parents.get(binding)
        function = self.context.parents.get(arguments) if arguments is not None else None
        owner = self._receiver_class(binding)
        if not (
            isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef)
            and not function.decorator_list
            and owner is not None
            and not owner.decorator_list
            and not owner.keywords
            and len(owner.bases) == 1
            and self.provenance.runtime_import_name(owner.bases[0]) in _TEST_CASES
        ):
            return False
        members = self.provenance.bindings.get(owner, {})
        if any(name in members for name in (assertion, "__getattribute__", "__getattr__")):
            return False
        return (owner, assertion) not in self._assertion_writes.instances and not self._assertion_modified(
            owner, assertion
        )

    def _receiver_class(self, binding: ast.AST) -> ast.ClassDef | None:
        arguments = self.context.parents.get(binding) if isinstance(binding, ast.arg) else None
        function = self.context.parents.get(arguments) if arguments is not None else None
        owner = self.context.parents.get(function) if function is not None else None
        if (
            isinstance(arguments, ast.arguments)
            and (*arguments.posonlyargs, *arguments.args)[:1] == (binding,)
            and isinstance(owner, ast.ClassDef)
        ):
            return owner
        return None

    def _assertion_modified(self, binding: ast.AST, assertion: str) -> bool:
        return (binding, assertion) in self._assertion_writes.bindings

    @cached_property
    def _assertion_writes(self) -> _AssertionWrites:
        writes: set[tuple[ast.AST, str]] = set()
        instances: set[tuple[ast.ClassDef, str]] = set()
        for node in self.context.nodes(ast.Attribute):
            if not (
                node.attr in _EXCEPTION_ASSERTIONS | {"__class__", "__getattribute__", "__getattr__"}
                and isinstance(node.ctx, ast.Store | ast.Del)
                and isinstance(node.value, ast.Name)
            ):
                continue
            binding = self.provenance.runtime_binding(node.value.id, node.value)
            if binding is None:
                continue
            names = {node.attr} if node.attr in _EXCEPTION_ASSERTIONS else _EXCEPTION_ASSERTIONS
            writes.update((binding, name) for name in names)
            owner = self._receiver_class(binding)
            if owner is not None:
                instances.update((owner, name) for name in names)
        return _AssertionWrites(frozenset(writes), frozenset(instances))


def _namespace_uncertain(provenance: ResourceProvenance, path: Path) -> bool:
    if provenance.mock_namespace_patching:
        return True
    sources = provenance.imported_namespace_hazards
    if not sources:
        return False
    target = path.resolve()
    return any(
        target == source or (source.name == "__init__.py" and target.is_relative_to(source.parent))
        for source in sources
    )


def _value_validator(function: _Function) -> bool:
    if function.decorator_list or not _value_annotation(function.returns):
        return False
    statements = list(function.body)
    raised = returned = False
    while statements:
        statement = statements.pop()
        match statement:
            case ast.Raise(exc=exception) if exception is not None:
                raised = True
            case ast.Return(value=value):
                if not _returned_value(value):
                    return False
                returned = True
            case ast.If(test=test, body=body, orelse=otherwise):
                if _expression_effect(test):
                    return False
                statements.extend((*body, *otherwise))
            case _:
                if not _passive_statement(statement):
                    return False
    return raised and returned


def _value_annotation(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return False
    excluded = {"Any", "Never", "NoReturn", "Optional"}
    return not any(
        (isinstance(node, ast.Constant) and node.value is None)
        or (isinstance(node, ast.Name) and node.id in excluded)
        or (isinstance(node, ast.Attribute) and node.attr in excluded)
        for node in ast.walk(annotation)
    )


def _expression_effect(value: ast.expr, *, allow_calls: bool = False) -> bool:
    effects = (
        (ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr)
        if allow_calls
        else (ast.Call, ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr)
    )
    return any(isinstance(node, effects) for node in ast.walk(value))


def _returned_value(value: ast.expr | None) -> bool:
    return (
        value is not None
        and not (isinstance(value, ast.Constant) and value.value is None)
        and not _expression_effect(value, allow_calls=True)
    )


def _passive_statement(statement: ast.stmt) -> bool:
    match statement:
        case ast.Assign(targets=targets, value=value):
            return all(isinstance(target, ast.Name) for target in targets) and not _expression_effect(value)
        case ast.AnnAssign(target=ast.Name(), value=value):
            return value is None or isinstance(value, ast.Constant)
        case ast.Expr(value=ast.Constant(value=str())):
            return True
        case _:
            return False
