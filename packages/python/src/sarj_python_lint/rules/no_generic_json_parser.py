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
    is_suppressed,
)


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
            "Reports import-proven TypeAdapter construction and RootModel bases containing JsonValue, Json, Any or object, including module-local explicit type aliases. Tests remain in scope; generated files are excluded.",
            "Typed dictionaries of domain values, model fields storing arbitrary JSON, opaque imported aliases and custom parser classes are excluded. Recursive arbitrary unions without a canonical open type are not inferred.",
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
        if context.generated or context.tree is None:
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
            if not is_suppressed(context.source_lines, node.lineno, self.code)
        ]


def _open_parser_nodes(
    context: PythonFileContext, imports: ImportIndex, aliases: dict[str, ast.expr]
) -> list[ast.expr]:
    candidates: list[ast.expr] = []
    for call in context.nodes(ast.Call):
        if not imports.resolves(call.func, sources=_PYDANTIC, symbol="TypeAdapter"):
            continue
        schema = call.args[0] if call.args else next((kw.value for kw in call.keywords if kw.arg == "type"), None)
        if schema is not None and _open_schema(schema, imports, aliases):
            candidates.append(call)
    for owner in context.nodes(ast.ClassDef):
        candidates.extend(_open_root_bases(owner, imports, aliases))
    return sorted(candidates, key=lambda node: (node.lineno, node.col_offset))


def _open_root_bases(owner: ast.ClassDef, imports: ImportIndex, aliases: dict[str, ast.expr]) -> list[ast.Subscript]:
    return [
        base
        for base in owner.bases
        if isinstance(base, ast.Subscript)
        and imports.resolves(base.value, sources=_PYDANTIC, symbol="RootModel")
        and _open_schema(base.slice, imports, aliases)
    ]


def _open_schema(
    node: ast.expr, imports: ImportIndex, aliases: dict[str, ast.expr], seen: frozenset[str] = frozenset()
) -> bool:
    for item in ast.walk(node):
        if not isinstance(item, ast.expr):
            continue
        if any(imports.resolves(item, sources=_PYDANTIC, symbol=name) for name in ("JsonValue", "Json")):
            return True
        if imports.resolves(item, sources=_TYPING, symbol="Any"):
            return True
        if isinstance(item, ast.Name):
            if item.id == "object" and imports.builtin_is_unshadowed("object"):
                return True
            if (
                item.id in aliases
                and item.id not in seen
                and _open_schema(aliases[item.id], imports, aliases, seen | {item.id})
            ):
                return True
    return False
