from __future__ import annotations

import ast
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
    is_suppressed,
)
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex


@final
class RequirePydanticForStructuredPayload(Rule):
    id = "require-pydantic-for-structured-payload"
    code = "SARJ450"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Structured nested FastAPI payloads must be parsed into a named Pydantic model before field access.",
        rationale=(
            "A validated outer request does not validate the shape of an open nested mapping; fixed-key reads bypass the "
            "route's declared contract."
        ),
        remediation=(
            "Validate the nested value with `PayloadModel.model_validate(...)` or `TypeAdapter(PayloadModel).validate_python(...)`, "
            "then use typed attributes."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=("Tests, generated sources, dynamic-key access, and non-FastAPI functions are excluded.",),
        examples=(
            RuleExample(
                example_id="raw-nested-route-payload",
                title="A route reads a fixed key from a nested request mapping",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/routes.py",
                        "from fastapi import APIRouter\nrouter = APIRouter()\n@router.post('/actions')\ndef action(body: RequestModel):\n    payload = body.payload\n    return payload.get('nameOnCard')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/routes.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="parsed-nested-route-payload",
                title="A route validates a nested request model",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/routes.py",
                        "from fastapi import APIRouter\nrouter = APIRouter()\n@router.post('/actions')\ndef action(body: RequestModel):\n    payload = CardPayload.model_validate(body.payload)\n    return payload.name_on_card\n",
                    ),
                ),
                focus_path=PurePosixPath("app/routes.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if is_test_path(path) or context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        index = context.fastapi
        imports = context.module_imports
        structured_fields = _structured_record_fields(tree, imports)
        lines = context.source_lines
        findings: list[Diagnostic] = []
        for function in (
            node for node in context.nodes(ast.AST) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            if not index.routes(function):
                continue
            parameters = {
                argument.arg: _annotation_name(argument.annotation)
                for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
            }
            raw_names = _nested_payload_bindings(function, parameters, structured_fields)
            for access in _fixed_key_accesses(function, raw_names):
                if is_suppressed(lines, access.lineno, self.code):
                    continue
                findings.append(
                    Diagnostic(
                        path,
                        access.lineno,
                        access.col_offset + 1,
                        self.code,
                        "parse the nested request payload into a named Pydantic model before fixed-key access",
                    )
                )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _nested_payload_bindings(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parameters: dict[str, str | None],
    structured_fields: frozenset[tuple[str, str]],
) -> set[str]:
    result: set[str] = set()
    for node in walk_ast(function):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if (
            not isinstance(value, ast.Attribute)
            or not isinstance(value.value, ast.Name)
            or value.value.id not in parameters
        ):
            continue
        owner = parameters[value.value.id]
        if owner is not None and (owner, value.attr) in structured_fields:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        result.update(target.id for target in targets if isinstance(target, ast.Name))
    return result


def _structured_record_fields(tree: ast.Module, imports: ImportIndex) -> frozenset[tuple[str, str]]:
    classes = [statement for statement in tree.body if isinstance(statement, ast.ClassDef)]
    named_records = _direct_named_records(classes, imports)
    for _round in range(len(classes)):
        inherited = _inherited_named_records(classes, named_records)
        if inherited <= named_records:
            break
        named_records.update(inherited)
    fields: set[tuple[str, str]] = set()
    for node in classes:
        if node.name in named_records:
            fields.update(_named_record_fields(node, named_records))
    return frozenset(fields)


def _direct_named_records(classes: list[ast.ClassDef], imports: ImportIndex) -> set[str]:
    return {node.name for node in classes if any(_is_named_record_base(base, imports) for base in node.bases)}


def _is_named_record_base(base: ast.expr, imports: ImportIndex) -> bool:
    return imports.resolves(base, sources=frozenset({"pydantic"}), symbol="BaseModel") or imports.resolves(
        base, sources=frozenset({"typing", "typing_extensions"}), symbol="TypedDict"
    )


def _inherited_named_records(classes: list[ast.ClassDef], named_records: set[str]) -> set[str]:
    return {
        node.name
        for node in classes
        if any(isinstance(base, ast.Name) and base.id in named_records for base in node.bases)
    }


def _named_record_fields(node: ast.ClassDef, named_records: set[str]) -> set[tuple[str, str]]:
    return {
        (node.name, statement.target.id)
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and _annotation_name(statement.annotation) in named_records
    }


def _annotation_name(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return None
    return node.id if isinstance(node, ast.Name) else None


def _fixed_key_accesses(function: ast.FunctionDef | ast.AsyncFunctionDef, raw_names: set[str]) -> list[ast.expr]:
    return [
        node
        for node in walk_ast(function)
        if isinstance(node, ast.expr)
        and (_is_fixed_subscript(node, raw_names) or _is_fixed_mapping_call(node, raw_names))
    ]


def _is_fixed_subscript(node: ast.AST, raw_names: set[str]) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id in raw_names
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    )


def _is_fixed_mapping_call(node: ast.AST, raw_names: set[str]) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    owner = node.func.value
    key = node.args[0] if node.args else None
    return (
        node.func.attr in {"get", "pop", "setdefault"}
        and isinstance(owner, ast.Name)
        and owner.id in raw_names
        and isinstance(key, ast.Constant)
        and isinstance(key.value, str)
    )
