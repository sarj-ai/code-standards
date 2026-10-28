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
    ProjectRule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._declared_contracts import DeclaredContracts
from sarj_python_lint.rules._imports import TYPING_SOURCES
from sarj_python_lint.rules._resource_provenance import import_name_for_binding


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import SourceUnit


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
type _Discard = ast.Expr | ast.Assign | ast.AnnAssign
_MAX_DEPTH = 16
_MIN_VARIANTS = 2
_BASE = """from typing import Literal
from pydantic import BaseModel
class Accepted(BaseModel):
    kind: Literal['accepted']
    value: str
class Rejected(BaseModel):
    kind: Literal['rejected']
    reason: str
type Outcome = Accepted | Rejected
def check(value: str) -> Outcome:
    return Accepted(kind='accepted', value=value)
"""


@dataclass(frozen=True)
class _FunctionSource:
    context: "PythonFileContext"
    function: _Function


@dataclass(frozen=True)
class _Reference:
    context: "PythonFileContext"
    expression: ast.expr
    anchor: ast.AST | None = None


@final
class NoDiscardedTaggedOutcome(ProjectRule):
    id = "no-discarded-tagged-outcome"
    code = "SARJ548"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Handle a returned tagged outcome instead of discarding it.",
        rationale=(
            "A tagged return union makes possible outcomes visible in the type contract. Discarding the value "
            "bypasses the caller's opportunity to handle its alternatives, including a declared failure."
        ),
        remediation=(
            "Use or forward the returned outcome. Handle its variants with match and a typed exhaustive "
            "fallback such as assert_never; preserve payloads and side effects. Do not delete the operation "
            "or hide the result behind a dummy assignment."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Review warning for standalone synchronous calls and directly awaited async calls to stable source-visible module functions. The return must resolve to at least two direct Pydantic, dataclass or required TypedDict variants sharing a string Literal discriminator with disjoint values. No name such as Result or Error establishes proof.",
            "Module-local and prepared-project absolute imports, quoted bare aliases and PEP 604 returns, unquoted typing.Union and Annotated, and bounded non-generic type aliases are supported. Quoted typing-wrapper combinations, unknown receivers, decorated or generic functions, re-exports, optional/scalar branches, generic records, inheritance, dynamic namespaces, rebound identities and unsupported annotations abstain.",
            "Named assignments, returned, passed or conditionally consumed results are preserved. A direct assignment to the single underscore target is an explicit discard and is reviewed. An unawaited async call belongs to coroutine checks. Direct class-body execution, generated sources and opaque providers are excluded. This rule identifies discarding; it does not prove that an assignment handles every variant or infer expected failure from a record name.",
            "String Literal tags must be direct instance fields on every variant and retain their original class-scope binding. Quoted field tags remain outside the proof; quoted module return annotations retain their source declaration anchor. Dynamic fields, optional TypedDict fields, non-string tags, computed Literal values and multi-field discriminator hierarchies are not inferred. No automatic rewrite changes call behavior or error handling.",
        ),
        examples=(
            RuleExample(
                example_id="discarded-outcome",
                title="A tagged outcome is discarded",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/outcomes.py", _BASE + "check('value')\n"),),
                focus_path=PurePosixPath("app/outcomes.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="forwarded-outcome",
                title="The caller forwards the outcome",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python("app/outcomes.py", _BASE + "def run() -> Outcome:\n    return check('value')\n"),
                ),
                focus_path=PurePosixPath("app/outcomes.py"),
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
        analysis = _OutcomeCalls(context)
        return [
            Diagnostic(
                context.path,
                statement.lineno,
                statement.col_offset + 1,
                self.code,
                "This call returns a tagged outcome that is discarded; use or forward it and handle its variants explicitly.",
                severity=Severity.WARNING,
            )
            for statement in context.nodes(ast.Expr, ast.Assign, ast.AnnAssign)
            if _direct_discard(statement)
            and not is_suppressed(context.source_lines, statement.lineno, self.code)
            and analysis.discarded(statement)
        ]


def _direct_discard(statement: _Discard) -> bool:
    match statement:
        case ast.Expr() | ast.Assign(targets=[ast.Name(id="_")]) | ast.AnnAssign(target=ast.Name(id="_")):
            return True
        case _:
            return False


@final
class _OutcomeCalls:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.contracts = DeclaredContracts(context)
        self.providers: dict[Path, PythonFileContext] = {context.path: context}
        self.outcomes: dict[_Function, bool] = {}

    def discarded(self, statement: _Discard) -> bool:
        value = statement.value
        awaited = isinstance(value, ast.Await)
        call = value.value if isinstance(value, ast.Await) else value
        if not isinstance(call, ast.Call) or isinstance(
            self.context.static_resource_provenance.scope(call), ast.ClassDef
        ):
            return False
        source = self._function_source(call.func)
        if source is None or isinstance(source.function, ast.AsyncFunctionDef) != awaited:
            return False
        function = source.function
        if function not in self.outcomes:
            members = (
                self._members(_Reference(source.context, function.returns, function), frozenset())
                if function.returns is not None
                else None
            )
            self.outcomes[function] = members is not None and self._tagged(members)
        return self.outcomes[function]

    def _function_source(self, expression: ast.expr) -> _FunctionSource | None:
        provenance = self.context.static_resource_provenance
        if provenance.dynamic_namespace or provenance.wildcard:
            return None
        local = self._local_function(expression)
        if local is not None:
            return local
        if provenance.runtime_import_name(expression) is None:
            return None
        return self._imported_function(expression)

    def _local_function(self, expression: ast.expr) -> _FunctionSource | None:
        if not isinstance(expression, ast.Name):
            return None
        binding = self.context.static_resource_provenance.runtime_binding(expression.id, expression)
        if not isinstance(binding, ast.FunctionDef | ast.AsyncFunctionDef):
            return None
        if self.context.parents.get(binding) is not self.context.tree or not self._stable(self.context, binding.name):
            return None
        if binding.decorator_list or binding.type_params:
            return None
        return _FunctionSource(self.context, binding)

    def _imported_function(self, expression: ast.expr) -> _FunctionSource | None:
        unit = self.contracts.unit
        symbol = self.contracts.project.resolve(unit, expression) if unit is not None else None
        provider = self.contracts.project.source_unit(symbol.module) if symbol is not None else None
        owner = self._provider(provider)
        if owner is None or owner.tree is None or symbol is None or not self._stable(owner, symbol.name):
            return None
        functions = [
            node
            for node in owner.tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == symbol.name
        ]
        if len(functions) != 1 or functions[0].decorator_list or functions[0].type_params:
            return None
        return _FunctionSource(owner, functions[0])

    def _provider(self, unit: SourceUnit | None) -> PythonFileContext | None:
        if unit is None or unit.tree is None:
            return None
        if unit.path not in self.providers:
            from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- facts only for a source-resolved provider.

            self.providers[unit.path] = PythonFileContext(unit.path, unit.source, self.context.session)
        owner = self.providers[unit.path]
        return None if owner.generated else owner

    @staticmethod
    def _stable(owner: PythonFileContext, name: str) -> bool:
        provenance = owner.static_resource_provenance
        if provenance.dynamic_namespace or provenance.wildcard:
            return False
        return (
            name not in provenance.mutated
            and name not in provenance.external_bindings
            and len(provenance.bindings.get(owner.tree, {}).get(name, ())) == 1
        )

    def _members(
        self, reference: _Reference, seen: frozenset[tuple[Path, str]], depth: int = 0
    ) -> list[_Reference] | None:
        owner = reference.context
        semantics = owner.annotation_semantics
        node = semantics.parse(reference.expression)
        if node is None or depth >= _MAX_DEPTH:
            return None
        anchor = reference.anchor or reference.expression
        if isinstance(node, ast.Name) and node.id in semantics.aliases:
            key = (owner.path, node.id)
            if key in seen or not _alias_identity(owner, node.id, semantics.aliases[node.id], anchor):
                return None
            return self._members(_Reference(owner, semantics.aliases[node.id]), seen | {key}, depth + 1)
        if isinstance(node, ast.Name | ast.Attribute) and _reference_binding(owner, node, anchor) is None:
            return None
        children = _union_children(node, owner)
        if children is not None:
            return self._expanded_members(_Reference(owner, node, anchor), children, seen, depth)
        imported = self._imported_alias(_Reference(owner, node, anchor))
        if imported is not None:
            key = (imported.context.path, ast.unparse(imported.expression))
            return None if key in seen else self._members(imported, seen | {key}, depth + 1)
        return [_Reference(owner, node, anchor)]

    def _expanded_members(
        self,
        reference: _Reference,
        children: list[ast.expr],
        seen: frozenset[tuple[Path, str]],
        depth: int,
    ) -> list[_Reference] | None:
        result: list[_Reference] = []
        for child in children:
            member = _Reference(reference.context, child, reference.anchor)
            expanded = self._members(member, seen, depth + 1)
            if expanded is None:
                return None
            result.extend(expanded)
            if len(result) > _MAX_DEPTH:
                return None
        return result

    def _imported_alias(self, reference: _Reference) -> _Reference | None:
        owner, node = reference.context, reference.expression
        if not isinstance(_reference_binding(owner, node, reference.anchor or node), ast.alias):
            return None
        unit = self.contracts.project.unit(owner.path)
        symbol = self.contracts.project.resolve(unit, node) if unit is not None else None
        if symbol is None or symbol.module == (unit.module if unit is not None else None):
            return None
        provider = self._provider(self.contracts.project.source_unit(symbol.module))
        if provider is None or not self._stable(provider, symbol.name):
            return None
        alias = provider.annotation_semantics.aliases.get(symbol.name)
        return _Reference(provider, alias) if alias is not None else None

    def _tagged(self, members: list[_Reference]) -> bool:
        if len(members) < _MIN_VARIANTS or len(members) > _MAX_DEPTH:
            return False
        variants = [self._record(member) for member in members]
        if any(variant is None for variant in variants):
            return False
        records = [variant for variant in variants if variant is not None]
        common = set(records[0]).intersection(*(record for record in records[1:]))
        return any(_disjoint([record[field] for record in records]) for field in common)

    def _record(self, reference: _Reference) -> dict[str, frozenset[str]] | None:
        owner = reference.context
        if _reference_binding(owner, reference.expression, reference.anchor or reference.expression) is None:
            return None
        unit = self.contracts.project.unit(owner.path)
        if unit is None:
            return None
        summary = self.contracts.project.class_for(unit, reference.expression)
        provider = (
            self._provider(self.contracts.project.source_unit(summary.symbol.module)) if summary is not None else None
        )
        if (
            provider is None
            or provider.tree is None
            or summary is None
            or not self._stable(provider, summary.symbol.name)
        ):
            return None
        declaration = next(
            (
                node
                for node in provider.tree.body
                if isinstance(node, ast.ClassDef) and node.name == summary.symbol.name
            ),
            None,
        )
        if declaration is None or not _record_shape(declaration, provider):
            return None
        return _record_tags(declaration, provider)


def _union_children(node: ast.expr, context: PythonFileContext) -> list[ast.expr] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [node.left, node.right]
    if not isinstance(node, ast.Subscript):
        return None
    qualified = _typing_reference(context, node.value, node)
    symbol = qualified.rpartition(".")[2] if qualified is not None else None
    if symbol == "Union":
        return node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if symbol == "Annotated" and isinstance(node.slice, ast.Tuple) and node.slice.elts:
        return [node.slice.elts[0]]
    return None


def _record_shape(node: ast.ClassDef, context: PythonFileContext) -> bool:
    if node.type_params or any(
        keyword.arg != "total" or not isinstance(keyword.value, ast.Constant) or keyword.value.value is not True
        for keyword in node.keywords
    ):
        return False
    decorators = [item.func if isinstance(item, ast.Call) else item for item in node.decorator_list]
    dataclass = len(decorators) == 1 and _dataclass_decorator(node.decorator_list[0], context)
    model = len(node.bases) == 1 and context.static_resource_provenance.runtime_import_name(node.bases[0]) in {
        "pydantic.BaseModel",
        "pydantic.main.BaseModel",
        "typing.TypedDict",
        "typing_extensions.TypedDict",
    }
    if not ((dataclass and not node.bases and not node.keywords) or (model and not decorators)):
        return False
    return all(_record_member(member) for member in node.body)


def _dataclass_decorator(node: ast.expr, context: PythonFileContext) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    if context.static_resource_provenance.runtime_import_name(target) != "dataclasses.dataclass":
        return False
    if not isinstance(node, ast.Call):
        return True
    return not node.args and all(
        keyword.arg is not None and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, bool)
        for keyword in node.keywords
    )


def _record_member(node: ast.stmt) -> bool:
    match node:
        case ast.AnnAssign(target=ast.Name()) | ast.Pass() | ast.Expr(value=ast.Constant(value=str())):
            return True
        case _:
            return False


def _record_tags(declaration: ast.ClassDef, context: PythonFileContext) -> dict[str, frozenset[str]] | None:
    fields = [
        node for node in declaration.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    ]
    names = [node.target.id for node in fields if isinstance(node.target, ast.Name)]
    if len(names) != len(set(names)):
        return None
    return {
        node.target.id: values
        for node in fields
        if isinstance(node.target, ast.Name) and (values := _literal_strings(node.annotation, context)) is not None
    }


def _literal_strings(annotation: ast.expr, context: PythonFileContext) -> frozenset[str] | None:
    reference = _literal_reference(_Reference(context, annotation))
    if reference is None:
        return None
    node = reference.expression
    if not isinstance(node, ast.Subscript) or _typing_reference(context, node.value, reference.anchor or node) not in {
        "typing.Literal",
        "typing_extensions.Literal",
    }:
        return None
    values = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if not values or any(not isinstance(value, ast.Constant) or not isinstance(value.value, str) for value in values):
        return None
    return frozenset(
        value.value for value in values if isinstance(value, ast.Constant) and isinstance(value.value, str)
    )


def _literal_reference(reference: _Reference) -> _Reference | None:
    owner = reference.context
    seen: set[str] = set()
    while isinstance(reference.expression, ast.Name):
        name = reference.expression.id
        value = owner.annotation_semantics.aliases.get(name)
        if value is None or name in seen or len(seen) >= _MAX_DEPTH:
            return None
        if not _alias_identity(owner, name, value, reference.anchor or reference.expression):
            return None
        seen.add(name)
        reference = _Reference(owner, value)
    # Keep the original AST lookup scope. Quoted field tags do not provide an
    # original class-scope expression and remain outside this narrow proof.
    return reference if not isinstance(reference.expression, ast.Constant) else None


def _alias_identity(context: PythonFileContext, name: str, value: ast.expr, anchor: ast.AST) -> bool:
    binding = _reference_binding(context, ast.Name(id=name), anchor)
    declaration = context.parents.get(binding) if binding is not None else None
    return isinstance(declaration, ast.TypeAlias | ast.AnnAssign) and declaration.value is value


def _typing_reference(context: PythonFileContext, expression: ast.expr, anchor: ast.AST) -> str | None:
    binding = _reference_binding(context, expression, anchor)
    if not isinstance(binding, ast.alias):
        return None
    qualified = import_name_for_binding(expression, binding, context.parents.get(binding))
    if qualified is None or qualified.rpartition(".")[0] not in TYPING_SOURCES:
        return None
    if expression not in context.parents:
        return None
    return qualified if context.static_resource_provenance.imported(expression, qualified) else None


def _reference_binding(context: PythonFileContext, expression: ast.expr, anchor: ast.AST) -> ast.AST | None:
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or anchor not in context.parents:
        return None
    provenance = context.static_resource_provenance
    if provenance.dynamic_namespace or provenance.wildcard or root.id in provenance.mutated:
        return None
    if root.id in provenance.external_bindings:
        return None
    binding = provenance.binding(root.id, anchor)
    return binding if isinstance(binding, ast.alias | ast.ClassDef | ast.Name) else None


def _disjoint(domains: list[frozenset[str]]) -> bool:
    seen: set[str] = set()
    for domain in domains:
        if not seen.isdisjoint(domain):
            return False
        seen.update(domain)
    return True
