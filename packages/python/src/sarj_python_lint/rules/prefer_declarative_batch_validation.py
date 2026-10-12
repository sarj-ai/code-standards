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
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._logging import LOG_METHODS
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._resource_provenance import ResourceProvenance
from sarj_python_lint.rules.prefer_class_row import PreferClassRow


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_BASE_MODELS = frozenset({"pydantic.BaseModel", "pydantic.main.BaseModel"})
_VALIDATION_ERRORS = frozenset({"pydantic.ValidationError", "pydantic_core.ValidationError"})
_SEQUENCES = frozenset({"typing.List", "typing.Tuple", "typing.Sequence", "collections.abc.Sequence"})
_ROW_FACTORIES = frozenset({"psycopg.rows.dict_row", "psycopg.rows.class_row"})
_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


@dataclass(frozen=True)
class _Batch:
    factory: ast.expr | None = None


@dataclass(frozen=True)
class _Builder:
    name: str
    initializer: ast.Assign | ast.AnnAssign
    owner: ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class _ValidatedAppend:
    value: ast.expr
    local: str | None = None


@final
class PreferDeclarativeBatchValidation(Rule):
    id = "prefer-declarative-batch-validation"
    code = "SARJ494"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Validate a homogeneous Pydantic batch with a declared collection contract.",
        rationale=(
            "Per-record validation comprehensions and catch/log/drop builders spread a collection contract "
            "across repeated model calls and mutable error-handling scaffolding. A named collection schema "
            "makes the batch's error policy explicit."
        ),
        remediation=(
            "Use class_row(Model) for unchanged Psycopg model rows, or a named RootModel[list[Model]] for "
            "collection validation. Declare whether invalid records reject the batch or are intentionally omitted "
            "(for example with OnErrorOmit). Preserve required logging and rejection reports."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only locally proven, undecorated Pydantic BaseModel classes, local inheritance and unique aliases are recognized; imported application models and dynamic ancestry remain unreported.",
            "Inputs must be a literal collection, an unambiguous list/tuple/Sequence declaration, or materialized rows from a locally bound Psycopg dict_row/class_row cursor. Unknown and streaming iterables are excluded.",
            "Comprehensions must have one synchronous generator and no filter. Loops require an adjacent fresh list and one validation-only try block with a proven ValidationError handler that only logs and drops a record.",
            "Changing models or context, preprocessing, rejection reports, secondary effects, observable loop locals, and validation options other than literal from_attributes=True are excluded.",
            "Simple append loops remain owned by Ruff PERF401; its resulting model-validation comprehension is checked here. Proven SARJ013 cursor conversions take precedence over this warning.",
            "There is no autofix: collection validation can change error aggregation, record omission, logging, evaluation after the first invalid record, and failure timing. Tests, generated files and vendor sources are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="homogeneous-validation-comprehension",
                title="Declare collection validation once",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/batches.py",
                        "from pydantic import BaseModel\nclass Item(BaseModel):\n    value: int\n"
                        "def load(rows: list[object]):\n    return [Item.model_validate(row) for row in rows]\n",
                    ),
                ),
                focus_path=PurePosixPath("app/batches.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-batch-validation",
                title="A named collection schema owns the batch",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/batches.py",
                        "from pydantic import BaseModel, RootModel\nclass Item(BaseModel):\n    value: int\n"
                        "class Items(RootModel[list[Item]]):\n    pass\n"
                        "def load(rows: list[object]):\n    return Items.model_validate(rows).root\n",
                    ),
                ),
                focus_path=PurePosixPath("app/batches.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.generated
            or is_test_path(context.path)
            or not {"vendor", "vendored", "third_party"}.isdisjoint(context.path.parts)
            or "model_validate" not in context.symbol_source
            or context.tree is None
        ):
            return []
        candidates = [node for node in context.nodes(ast.ListComp, ast.For) if _may_validate_batch(node)]
        if not candidates:
            return []
        facts = _Facts(context)
        if facts.provenance.wildcard or facts.provenance.dynamic_namespace:
            return []
        findings: list[Diagnostic] = []
        for node in candidates:
            matched = _comprehension(node, facts) if isinstance(node, ast.ListComp) else _drop_loop(node, facts)
            if matched is None:
                continue
            model, batch = matched
            if (
                batch.factory is not None
                and (batch.factory.lineno, batch.factory.col_offset + 1) in facts.database_owners
            ):
                continue
            if is_suppressed(context.source_lines, node.lineno, self.code):
                continue
            findings.append(
                Diagnostic(
                    path=context.path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"per-record validation of `{model}` builds a homogeneous batch; use class_row({model}) "
                        "for unchanged database rows, or a named RootModel collection with an explicit reject-or-omit "
                        "policy; preserve required error reporting and logging"
                    ),
                )
            )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


class _Facts:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = ResourceProvenance(context, require_static_namespace=True)
        self.imports = {
            statement: ImportIndex.from_tree(ast.Module(body=[statement], type_ignores=[]))
            for statement in context.nodes(ast.Import, ast.ImportFrom)
        }
        self._binding_cache: dict[tuple[str, ast.AST | None], tuple[ast.AST, ...]] = {}
        self._read_cache: dict[ast.AST, tuple[ast.Name, ...]] = {}
        self._import_cache: dict[ast.alias, bool] = {}
        self._type_cache: dict[ast.AST, bool] = {}

    @cached_property
    def database_owners(self) -> set[tuple[int, int]]:
        return {(finding.line, finding.col) for finding in PreferClassRow().check_context(self.context)}

    def bindings(self, name: str, at: ast.AST) -> tuple[ast.AST, ...]:
        scope = self.provenance.scope(at)
        key = (name, scope)
        if key not in self._binding_cache:
            self._binding_cache[key] = self._lexical_bindings(name, scope)
        return self._binding_cache[key]

    def _lexical_bindings(self, name: str, scope: ast.AST | None) -> tuple[ast.AST, ...]:
        initial = scope
        while scope is not None:
            if (scope is initial or not isinstance(scope, ast.ClassDef)) and (
                nodes := self.provenance.bindings.get(scope, {}).get(name)
            ):
                return tuple(nodes)
            scope = self.provenance.scope(scope)
        return ()

    def _reads_for(self, name: str, binding: ast.AST) -> tuple[ast.Name, ...]:
        if binding not in self._read_cache:
            self._read_cache[binding] = tuple(
                read for read in self.provenance.reads.get(name, ()) if self.bindings(name, read) == (binding,)
            )
        return self._read_cache[binding]

    def qualified(self, expression: ast.expr) -> str | None:
        root = _root(expression)
        if root is None or root.id in self.provenance.mutated | self.provenance.external_bindings:
            return None
        bindings = self.bindings(root.id, expression)
        if len(bindings) != 1 or not isinstance(bindings[0], ast.alias):
            return None
        owner = self.context.parents.get(bindings[0])
        index = self.imports.get(owner) if isinstance(owner, (ast.Import, ast.ImportFrom)) else None
        if index is None or not self._import_untouched(root.id, bindings[0], index):
            return None
        return _import_name(expression, index)

    def _import_untouched(self, name: str, binding: ast.alias, index: ImportIndex) -> bool:
        if binding not in self._import_cache:
            self._import_cache[binding] = all(
                self._safe_import_read(read, index) for read in self._reads_for(name, binding)
            )
        return self._import_cache[binding]

    def _safe_import_read(self, read: ast.Name, index: ImportIndex) -> bool:
        reference: ast.expr = read
        parent = self.context.parents.get(reference)
        while isinstance(parent, ast.Attribute) and parent.value is reference:
            reference, parent = parent, self.context.parents.get(parent)
        match parent:
            case ast.Call(func=func) if func is reference:
                return not (isinstance(reference, ast.Attribute) and reference.attr in {"__setattr__", "__delattr__"})
            case ast.ClassDef(bases=bases):
                return reference in bases
            case ast.Subscript():
                return True
            case (
                ast.arg(annotation=slot)
                | ast.AnnAssign(annotation=slot)
                | ast.FunctionDef(returns=slot)
                | ast.AsyncFunctionDef(returns=slot)
                | ast.ExceptHandler(type=slot)
            ):
                return slot is reference
            case ast.keyword(arg="row_factory"):
                return self._row_factory_reference(reference, parent, index)
            case _:
                return False

    def _row_factory_reference(self, reference: ast.expr, keyword: ast.keyword, index: ImportIndex) -> bool:
        call = self.context.parents.get(keyword)
        return (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "cursor"
            and _import_name(reference, index) in _ROW_FACTORIES
        )

    def builtin(self, name: str, at: ast.AST) -> bool:
        return not self.bindings(name, at) and self.provenance.builtin_namespace_untouched

    def model(self, expression: ast.expr, seen: frozenset[ast.AST] = frozenset()) -> bool:
        if not isinstance(expression, ast.Name) or expression.id in self.provenance.external_bindings:
            return False
        bindings = self.bindings(expression.id, expression)
        if len(bindings) != 1 or bindings[0] in seen or not self._safe_type_binding(bindings[0], seen):
            return False
        binding = bindings[0]
        if isinstance(binding, ast.Name):
            value = self.provenance.assignment_value(binding, expression)
            return value is not None and self.model(value, seen | {binding})
        if not isinstance(binding, ast.ClassDef) or not isinstance(
            self.context.parents.get(binding), (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            return False
        if binding.decorator_list or binding.keywords or len(binding.bases) != 1:
            return False
        if any(_binds_validation(member) for member in binding.body):
            return False
        base = binding.bases[0]
        return self.qualified(base) in _BASE_MODELS or self.model(base, seen | {binding})

    def _safe_type_binding(self, binding: ast.AST, seen: frozenset[ast.AST]) -> bool:
        name = (
            binding.name if isinstance(binding, ast.ClassDef) else binding.id if isinstance(binding, ast.Name) else None
        )
        if name is None or name in self.provenance.mutated | self.provenance.external_bindings:
            return False
        if self.bindings(name, binding) != (binding,):
            return False
        if binding not in self._type_cache:
            self._type_cache[binding] = all(
                self._safe_type_read(read, seen | {binding}) for read in self._reads_for(name, binding)
            )
        return self._type_cache[binding]

    def _safe_type_read(self, read: ast.Name, seen: frozenset[ast.AST]) -> bool:
        parent = self.context.parents.get(read)
        match parent:
            case ast.Attribute(value=value, attr="model_validate"):
                return value is read
            case ast.ClassDef(bases=bases):
                return read in bases
            case ast.Call():
                return parent.func is read or self._class_row_consumer(parent, read)
            case ast.Subscript() | ast.arg():
                return _in_annotation(read, self)
            case ast.Assign() | ast.AnnAssign():
                return _in_annotation(read, self) or self._type_alias(parent, read, seen)
            case _:
                return False

    def _class_row_consumer(self, call: ast.Call, read: ast.Name) -> bool:
        return call.args == [read] and not call.keywords and self.qualified(call.func) == "psycopg.rows.class_row"

    def _type_alias(self, assignment: ast.Assign | ast.AnnAssign, read: ast.Name, seen: frozenset[ast.AST]) -> bool:
        if assignment.value is not read:
            return False
        targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            return False
        return targets[0] in seen or self._safe_type_binding(targets[0], seen)

    def batch(self, expression: ast.expr, seen: frozenset[ast.AST] = frozenset()) -> _Batch | None:
        if isinstance(expression, (ast.List, ast.Tuple)):
            return _Batch()
        if isinstance(expression, ast.Name):
            return self._named_batch(expression, seen)
        value = expression.value if isinstance(expression, ast.Await) else expression
        if (
            not isinstance(value, ast.Call)
            or not isinstance(value.func, ast.Attribute)
            or value.func.attr not in {"fetchall", "fetchmany"}
            or not isinstance(value.func.value, ast.Name)
        ):
            return None
        return self._materialized_batch(value, value.func.value)

    def _named_batch(self, expression: ast.Name, seen: frozenset[ast.AST]) -> _Batch | None:
        bindings = self.bindings(expression.id, expression)
        if len(bindings) != 1 or bindings[0] in seen or expression.id in self.provenance.external_bindings:
            return None
        binding = bindings[0]
        if isinstance(binding, ast.Name):
            value = self._batch_assignment(binding, expression)
            if value is not None:
                return self.batch(value, seen | {binding})
        parent = self.context.parents.get(binding)
        annotation = (
            binding.annotation
            if isinstance(binding, ast.arg)
            else (parent.annotation if isinstance(parent, ast.AnnAssign) else None)
        )
        return _Batch() if annotation is not None and self._sequence_annotation(annotation) else None

    def _batch_assignment(self, binding: ast.Name, at: ast.Name) -> ast.expr | None:
        value = self.provenance.assignment_value(binding, at)
        if value is not None:
            return value
        assignment = self.context.parents.get(binding)
        if not isinstance(assignment, (ast.Assign, ast.AnnAssign)) or assignment.lineno >= at.lineno:
            return None
        container = self.context.parents.get(assignment)
        return assignment.value if isinstance(container, (ast.With, ast.AsyncWith)) else None

    def _materialized_batch(self, fetch: ast.Call, receiver: ast.Name) -> _Batch | None:
        if receiver.id in self.provenance.mutated | self.provenance.external_bindings:
            return None
        cursor = self._cursor_definition(receiver, fetch)
        if (
            not isinstance(cursor, ast.Call)
            or not isinstance(cursor.func, ast.Attribute)
            or cursor.func.attr != "cursor"
        ):
            return None
        factory = next((keyword.value for keyword in cursor.keywords if keyword.arg == "row_factory"), None)
        reference = factory.func if isinstance(factory, ast.Call) else factory
        return _Batch(factory) if reference is not None and self.qualified(reference) in _ROW_FACTORIES else None

    def _cursor_definition(self, receiver: ast.Name, at: ast.Call) -> ast.expr | None:
        bindings = self.bindings(receiver.id, at)
        if len(bindings) != 1:
            return None
        binding = bindings[0]
        parent = self.context.parents.get(binding)
        if isinstance(parent, ast.withitem):
            owner = self.context.parents.get(parent)
            return parent.context_expr if self.provenance.contains(owner, at) else None
        return self.provenance.assignment_value(binding, at) if isinstance(binding, ast.Name) else None

    def _sequence_annotation(self, annotation: ast.expr) -> bool:
        if not isinstance(annotation, ast.Subscript):
            return False
        value = annotation.value
        return (
            isinstance(value, ast.Name) and value.id in {"list", "tuple"} and self.builtin(value.id, value)
        ) or self.qualified(value) in _SEQUENCES

    def logging(self, statement: ast.stmt, error: str | None) -> bool:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            return False
        call = statement.value
        if not isinstance(call.func, ast.Attribute) or call.func.attr not in LOG_METHODS:
            return False
        target = self.qualified(call.func)
        if target not in {f"loguru.logger.{call.func.attr}", f"logging.{call.func.attr}"}:
            return False
        for value in (*call.args, *(keyword.value for keyword in call.keywords)):
            for node in ast.walk(value):
                if isinstance(node, (ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr, ast.Lambda)):
                    return False
                if isinstance(node, ast.Call) and not (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "str"
                    and self.builtin("str", node)
                    and len(node.args) == 1
                    and not node.keywords
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == error
                ):
                    return False
        return not any(keyword.arg is None for keyword in call.keywords)


def _root(expression: ast.expr) -> ast.Name | None:
    while isinstance(expression, ast.Attribute):
        expression = expression.value
    return expression if isinstance(expression, ast.Name) else None


def _import_name(expression: ast.expr, index: ImportIndex) -> str | None:
    root = _root(expression)
    target = index.bindings.get(root.id) if root is not None else None
    if target is None:
        return None
    parts: list[str] = []
    while isinstance(expression, ast.Attribute):
        parts.append(expression.attr)
        expression = expression.value
    return ".".join((target.module, *((target.symbol,) if target.symbol else ()), *reversed(parts)))


def _binds_validation(statement: ast.stmt) -> bool:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return statement.name == "model_validate"
    for node in ast.walk(statement):
        match node:
            case (
                ast.FunctionDef(name="model_validate")
                | ast.AsyncFunctionDef(name="model_validate")
                | ast.ClassDef(name="model_validate")
                | ast.Name(id="model_validate", ctx=(ast.Store() | ast.Del()))
                | ast.ExceptHandler(name="model_validate")
                | ast.MatchAs(name="model_validate")
            ):
                return True
            case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
                if any((alias.asname or alias.name.partition(".")[0]) == "model_validate" for alias in aliases):
                    return True
            case _:
                pass
    return False


def _in_annotation(node: ast.AST, facts: _Facts) -> bool:
    context = facts.context
    child = node
    parent = context.parents.get(child)
    while parent is not None and not isinstance(parent, _SCOPES):
        if isinstance(parent, (ast.arg, ast.AnnAssign)):
            return parent.annotation is child
        if isinstance(parent, ast.Call):
            return False
        child, parent = parent, context.parents.get(parent)
    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return parent.returns is child
    return (
        isinstance(parent, ast.ClassDef)
        and child in parent.bases
        and isinstance(child, ast.Subscript)
        and facts.qualified(child.value) in {"pydantic.RootModel", "pydantic.root_model.RootModel"}
    )


def _validation(value: ast.expr, item: str, facts: _Facts) -> str | None:
    if (
        not isinstance(value, ast.Call)
        or not isinstance(value.func, ast.Attribute)
        or value.func.attr != "model_validate"
    ):
        return None
    if (
        len(value.args) != 1
        or not isinstance(value.args[0], ast.Name)
        or value.args[0].id != item
        or not facts.model(value.func.value)
    ):
        return None
    if value.keywords and not (
        len(value.keywords) == 1
        and value.keywords[0].arg == "from_attributes"
        and isinstance(value.keywords[0].value, ast.Constant)
        and value.keywords[0].value.value is True
    ):
        return None
    return ast.unparse(value.func.value)


def _comprehension(node: ast.ListComp, facts: _Facts) -> tuple[str, _Batch] | None:
    if len(node.generators) != 1:
        return None
    generator = node.generators[0]
    if generator.is_async or generator.ifs or not isinstance(generator.target, ast.Name):
        return None
    batch = facts.batch(generator.iter)
    if batch is None:
        return None
    model = _validation(node.elt, generator.target.id, facts)
    return (model, batch) if model is not None else None


def _may_validate_batch(node: ast.ListComp | ast.For) -> bool:
    if isinstance(node, ast.ListComp):
        return _is_validation_call(node.elt)
    if not node.body or not isinstance(node.body[0], ast.Try):
        return False
    match node.body[0].body:
        case [ast.Assign(value=value), *_] | [
            ast.Expr(value=ast.Call(func=ast.Attribute(attr="append"), args=[value])),
            *_,
        ]:
            return _is_validation_call(value)
        case _:
            return False


def _is_validation_call(value: ast.expr) -> bool:
    return isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "model_validate"


def _drop_loop(loop: ast.For, facts: _Facts) -> tuple[str, _Batch] | None:
    if loop.orelse or not isinstance(loop.target, ast.Name):
        return None
    builder = _fresh_builder(loop, facts)
    if builder is None:
        return None
    attempt = _logged_attempt(loop, facts)
    if attempt is None:
        return None
    appended = _validated_append(loop, attempt, builder.name)
    if appended is None:
        return None
    locals_ = {loop.target.id, *(() if appended.local is None else (appended.local,))}
    if _locals_observed(loop, locals_, facts):
        return None
    if _collection_observed(loop, builder.initializer, builder.owner, builder.name, facts):
        return None
    batch = facts.batch(loop.iter)
    if batch is None:
        return None
    model = _validation(appended.value, loop.target.id, facts)
    return (model, batch) if model is not None else None


def _fresh_builder(loop: ast.For, facts: _Facts) -> _Builder | None:
    parent = facts.context.parents.get(loop)
    if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.With, ast.AsyncWith)):
        return None
    owner: ast.AST | None = parent
    while owner is not None and not isinstance(owner, _SCOPES):
        owner = facts.context.parents.get(owner)
    if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    position = parent.body.index(loop)
    if position == 0:
        return None
    initializer = parent.body[position - 1]
    match initializer:
        case (
            ast.Assign(targets=[ast.Name(id=name)], value=ast.List(elts=[]))
            | ast.AnnAssign(target=ast.Name(id=name), value=ast.List(elts=[]), simple=1)
        ):
            return _Builder(name, initializer, owner)
        case _:
            return None


def _logged_attempt(loop: ast.For, facts: _Facts) -> ast.Try | None:
    if not loop.body or not isinstance(loop.body[0], ast.Try):
        return None
    attempt = loop.body[0]
    if attempt.finalbody or len(attempt.handlers) != 1:
        return None
    handler = attempt.handlers[0]
    if handler.type is None or facts.qualified(handler.type) not in _VALIDATION_ERRORS:
        return None
    logging = handler.body[:-1] if isinstance(handler.body[-1], ast.Continue) else handler.body
    if not logging or not all(facts.logging(statement, handler.name) for statement in logging):
        return None
    return attempt


def _validated_append(loop: ast.For, attempt: ast.Try, name: str) -> _ValidatedAppend | None:
    if len(attempt.body) == 1 and not attempt.orelse and len(loop.body) == 1:
        value = _append(attempt.body[0], name)
        if value is not None:
            return _ValidatedAppend(value)
    match attempt.body[0]:
        case ast.Assign(targets=[ast.Name(id=local)], value=value):
            pass
        case _:
            return None
    tail = [*attempt.body[1:], *attempt.orelse, *loop.body[1:]]
    if len(tail) != 1:
        return None
    appended = _append(tail[0], name)
    if not isinstance(appended, ast.Name) or appended.id != local:
        return None
    if len(loop.body) > 1 and not isinstance(attempt.handlers[0].body[-1], ast.Continue):
        return None
    return _ValidatedAppend(value, local)


def _append(statement: ast.stmt, name: str) -> ast.expr | None:
    match statement:
        case ast.Expr(
            value=ast.Call(func=ast.Attribute(value=ast.Name(id=receiver), attr="append"), args=[value], keywords=[])
        ) if receiver == name:
            return value
        case _:
            return None


def _locals_observed(loop: ast.For, names: set[str], facts: _Facts) -> bool:
    inside = frozenset(ast.walk(loop))
    return any(
        read not in inside and facts.bindings(name, read) == facts.bindings(name, loop)
        for name in names
        for read in facts.provenance.reads.get(name, ())
    )


def _collection_observed(loop: ast.For, initializer: ast.stmt, owner: ast.AST, name: str, facts: _Facts) -> bool:
    bindings = facts.bindings(name, loop)
    if len(bindings) != 1 or facts.context.parents.get(bindings[0]) is not initializer:
        return True
    inside = frozenset(ast.walk(loop))
    return any(
        read not in inside
        and facts.bindings(name, read) == bindings
        and not (isinstance(facts.context.parents.get(read), ast.Return) and facts.provenance.scope(read) is owner)
        for read in facts.provenance.reads.get(name, ())
    )
