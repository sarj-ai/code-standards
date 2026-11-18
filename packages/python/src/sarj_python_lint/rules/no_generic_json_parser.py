from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
)
from sarj_python_lint.rules._annotation_origins import AnnotationOrigins


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


_PYDANTIC = frozenset({"pydantic", "pydantic.root_model", "pydantic.type_adapter", "pydantic.types"})
_TYPING = frozenset({"typing", "typing_extensions"})


@final
class NoGenericJsonParser(Rule):
    id = "no-generic-json-parser"
    code = "SARJ552"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Parse consumed JSON fields with a bespoke declarative model instead of an open JSON parser.",
        rationale="An open JSON domain validates syntax and value kinds without declaring required fields or their relationships; consumers must then reconstruct the contract manually.",
        remediation="Declare only the fields the consumer needs in a named Pydantic model and use model_validate_json or model_validate. Allow unrelated fields when the wire contract permits them. Document an exact-code exception for genuinely schema-agnostic infrastructure.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Reports import-proven TypeAdapter construction and RootModel bases containing JsonValue, Json, Any or object, including module-local explicit type aliases. Inline RootModel validation is checked only for the optional open record described below; ordinary inline JSON plumbing remains unchanged. Tests remain in scope; generated files are excluded.",
            "A direct stable total=False TypedDict whose nonempty field set is entirely JsonValue, Any or object also leaves every value open. Required, mixed/domain-valued, inherited, decorated and configured records remain allowed, as do ordinary annotations and arbitrary-JSON model fields. Imported aliases and recursive arbitrary unions without a canonical open type are not inferred.",
            "Generic schema infrastructure may need a reasoned local suppression. No model or complete request schema is synthesized automatically.",
        ),
        examples=(
            RuleExample(
                example_id="generic-response-parser",
                title="An open JSON mapping does not declare the response fields",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_api.py",
                        "from pydantic import JsonValue, RootModel\nclass Response(RootModel[dict[str, JsonValue]]):\n    pass\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_api.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="partial-declarative-response",
                title="Declare just the field this consumer needs",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_api.py",
                        "from pydantic import BaseModel\nclass Response(BaseModel):\n    version: int\n",
                    ),
                ),
                focus_path=PurePosixPath("tests/test_api.py"),
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
            or context.tree is None
            or not any(name in context.symbol_source for name in ("TypeAdapter", "RootModel"))
        ):
            return []
        imports = context.imports
        aliases = {
            statement.name.id: statement.value
            for statement in context.tree.body
            if isinstance(statement, ast.TypeAlias)
        }
        candidates = _open_parser_nodes(context, imports, aliases)
        return [
            Diagnostic(
                context.path,
                node.lineno,
                node.col_offset + 1,
                self.code,
                "Replace this open JSON parser with a named model declaring the consumed fields.",
                severity=Severity.WARNING,
            )
            for node in candidates
            if not context.suppressions.is_suppressed(node.lineno, self.code)
        ]


def _open_parser_nodes(
    context: PythonFileContext, imports: ImportIndex, aliases: dict[str, ast.expr]
) -> list[ast.expr]:
    tree = context.tree
    if tree is None:
        return []
    candidates: list[ast.expr] = []
    records = {
        statement.name: statement
        for statement in tree.body
        if isinstance(statement, ast.ClassDef) and _optional_record_declaration(statement, imports)
    }
    for call in context.nodes(ast.Call):
        schema = _parser_schema(call, context, imports, records)
        if schema is not None and _open_schema(schema, imports, aliases, context=context, records=records):
            candidates.append(call)
    for owner in context.nodes(ast.ClassDef):
        candidates.extend(_open_root_bases(owner, imports, aliases, context=context, records=records))
    return sorted(candidates, key=lambda node: (node.lineno, node.col_offset))


def _parser_schema(
    call: ast.Call, context: PythonFileContext, imports: ImportIndex, records: dict[str, ast.ClassDef]
) -> ast.expr | None:
    if not imports.resolves(call.func, sources=_PYDANTIC, symbol="TypeAdapter"):
        schema = _inline_root_schema(call, context)
        return (
            schema
            if (
                isinstance(schema, ast.Name)
                and schema.id in records
                and _open_optional_record(records[schema.id], schema, context)
            )
            else None
        )
    if call.args:
        return call.args[0]
    return next((keyword.value for keyword in call.keywords if keyword.arg == "type"), None)


def _open_root_bases(
    owner: ast.ClassDef,
    imports: ImportIndex,
    aliases: dict[str, ast.expr],
    *,
    context: PythonFileContext,
    records: dict[str, ast.ClassDef],
) -> list[ast.Subscript]:
    return [
        base
        for base in owner.bases
        if isinstance(base, ast.Subscript)
        and imports.resolves(base.value, sources=_PYDANTIC, symbol="RootModel")
        and _open_schema(base.slice, imports, aliases, context=context, records=records)
    ]


def _open_schema(
    node: ast.expr,
    imports: ImportIndex,
    aliases: dict[str, ast.expr],
    seen: frozenset[str] = frozenset(),
    *,
    context: PythonFileContext,
    records: dict[str, ast.ClassDef],
) -> bool:
    facts = AnnotationOrigins(context)
    for item in ast.walk(node):
        if not isinstance(item, ast.expr):
            continue
        if facts.qualified(item, item) in {
            "pydantic.JsonValue",
            "pydantic.types.JsonValue",
            "pydantic.Json",
            "pydantic.types.Json",
        }:
            return True
        if facts.qualified(item, item) in {"typing.Any", "typing_extensions.Any"}:
            return True
        if isinstance(item, ast.Name):
            record = records.get(item.id)
            if record is not None and _open_optional_record(record, item, context):
                return True
            if facts.builtin(item, "object", item):
                return True
            if (
                item.id in aliases
                and item.id not in seen
                and not facts.shadowed(item.id, item)
                and facts.alias_value(item, item) is aliases[item.id]
                and _open_schema(aliases[item.id], imports, aliases, seen | {item.id}, context=context, records=records)
            ):
                return True
    return False


def _inline_root_schema(call: ast.Call, context: PythonFileContext) -> ast.expr | None:
    target = call.func
    if isinstance(target, ast.Attribute) and target.attr in {"model_validate", "model_validate_json"}:
        target = target.value
    if not isinstance(target, ast.Subscript):
        return None
    qualified = AnnotationOrigins(context).qualified(target.value, call)
    return target.slice if qualified in {"pydantic.RootModel", "pydantic.root_model.RootModel"} else None


def _optional_record_declaration(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return (
        not node.decorator_list
        and not node.type_params
        and len(node.bases) == 1
        and imports.resolves(node.bases[0], sources=_TYPING, symbol="TypedDict")
        and len(node.keywords) == 1
        and node.keywords[0].arg == "total"
        and isinstance(node.keywords[0].value, ast.Constant)
        and node.keywords[0].value.value is False
    )


def _open_optional_record(node: ast.ClassDef, use: ast.Name, context: PythonFileContext) -> bool:
    facts = AnnotationOrigins(context)
    provenance = facts.provenance
    if (
        facts.shadowed(use.id, use)
        or provenance.wildcard
        or provenance.dynamic_namespace
        or use.id in provenance.mutated | provenance.external_bindings
        or provenance.binding(use.id, use) is not node
    ):
        return False
    fields: list[ast.expr] = []
    for statement in node.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value is None:
            fields.append(statement.annotation)
        elif not (
            isinstance(statement, ast.Pass)
            or (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            )
        ):
            return False
    return bool(fields) and all(_arbitrary_value(field, facts) for field in fields)


def _arbitrary_value(node: ast.expr, facts: AnnotationOrigins) -> bool:
    resolved = facts.resolve_annotation(node)
    if resolved is None:
        return False
    value, at = resolved.expression, resolved.at
    return facts.builtin(value, "object", at) or facts.qualified(value, at) in {
        "pydantic.JsonValue",
        "pydantic.types.JsonValue",
        "typing.Any",
        "typing_extensions.Any",
    }
