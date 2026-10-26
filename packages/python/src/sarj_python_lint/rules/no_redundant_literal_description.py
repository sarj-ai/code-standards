from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._inert_model_annotation import inert_direct_model_body
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


_PYDANTIC_BASE_MODEL_SOURCES = frozenset({"pydantic", "pydantic.main", "pydantic.v1", "pydantic.v1.main"})
_PYDANTIC_FIELD_SOURCES = frozenset({"pydantic", "pydantic.fields", "pydantic.v1", "pydantic.v1.fields"})
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_ENUM_SOURCES = frozenset({"enum"})
_DOMAIN_CLAUSE = re.compile(
    r"\b(?:this\s+)?(?:(?:must|should)(?:\s+only)?\s+be(?:\s+(?:either|one\s+of)"
    r"(?:\s+the\s+following\s+values?)?)?|(?:allowed|valid)\s+values?\s*:?)\s*:?[ ]*"
    r"(?P<body>.+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_QUOTED_VALUE = re.compile(r"(?P<quote>['\"`])(?P<value>.+?)(?P=quote)")
_IDENTIFIER_VALUE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


@final
class NoRedundantLiteralDescription(Rule):
    id = "no-restated-closed-domain-description"
    code = "SARJ423"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Do not restate a string Literal or local string Enum domain in its Pydantic description.",
        rationale=(
            "Pydantic already publishes literal and enum domains in JSON Schema; duplicate must-be prose can "
            "contradict the generated contract after a value changes."
        ),
        remediation=(
            "Remove only the repeated value list. Preserve guidance about when to use each value, UX labels, "
            "examples, deprecation, or rationale not encoded by the field type."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        aliases=("no-redundant-literal-description",),
        limitations=(
            "Safe fixes remove only the description keyword of a comment-free, error-level inert Field call whose entire literal description repeats the complete declared domain. Schema-ownership warnings remain review-only.",
            "Only direct fields on classes with a direct BaseModel base are inspected.",
            "Domains are resolved only from direct string Literals and static Literal aliases or string-valued Enums in the same module.",
            "Descriptions are reported only when a narrow clause repeats the complete domain without mapping or rationale.",
            "ERROR requires an inert direct model with no json_schema_extra options; custom construction, schema metadata, local aliases and Enum annotations retain WARNING with schema-ownership review guidance.",
            "Test and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="closed-domain-restated",
                title="Closed domain repeated in prose",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Literal\nfrom pydantic import BaseModel, Field\n\n"
                        "class Request(BaseModel):\n"
                        "    mode: Literal['realtime', 'batch'] = Field(\n"
                        "        description=\"Must be 'realtime' or 'batch'.\"\n"
                        "    )\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="closed-domain-behavior-described",
                title="Description adds behavior not present in the schema",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Literal\nfrom pydantic import BaseModel, Field\n\n"
                        "class Request(BaseModel):\n"
                        "    mode: Literal['realtime', 'batch'] = Field(\n"
                        "        description='Use batch mode for work expected to exceed the request timeout.'\n"
                        "    )\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="safe-autofix-subset",
                title="A proven subset has a convergent automatic fix",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        (
                            "from typing import Literal\n"
                            "from pydantic import BaseModel, Field\n"
                            "class Request(BaseModel):\n"
                            "    mode: Literal['one', 'two'] = Field(description=\"Must be 'one' or 'two'.\")\n"
                        ),
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        (
                            "from typing import Literal\n"
                            "from pydantic import BaseModel, Field\n"
                            "class Request(BaseModel):\n"
                            "    mode: Literal['one', 'two'] = Field()\n"
                        ),
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
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
        imports = _module_import_index(tree)
        local_domains = _local_closed_domains(tree, imports)
        diagnostics: list[Diagnostic] = []

        def collect_field_descriptions(
            statement: ast.AnnAssign, field_name: str, domain: frozenset[str], *, severity: Severity
        ) -> None:
            for field_call in _field_calls(statement, imports):
                description = next(
                    (keyword.value for keyword in field_call.keywords if keyword.arg == "description"), None
                )
                if not (
                    isinstance(description, ast.Constant)
                    and isinstance(description.value, str)
                    and _repeats_domain(description.value, domain)
                ):
                    continue
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=description.lineno,
                        col=description.col_offset + 1,
                        code=self.code,
                        message=(
                            f"`{field_name}` repeats its declared Literal or Enum domain; "
                            "remove the repeated list only after preserving required schema metadata and behavioral guidance."
                        ),
                        severity=severity,
                    )
                )

        for model in context.nodes(ast.ClassDef):
            if not _is_direct_model(model, imports) or _has_custom_schema_hook(model):
                continue
            severity = _description_level(model, context)
            for statement in model.body:
                if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
                    continue
                domain = _closed_domain(statement.annotation, imports, local_domains)
                if domain is None or _has_schema_override(statement.annotation, imports):
                    continue
                collect_field_descriptions(
                    statement,
                    statement.target.id,
                    domain,
                    severity=severity,
                )
        return diagnostics


def _description_level(model: ast.ClassDef, context: PythonFileContext) -> Severity:
    return Severity.ERROR if _inert_description_model(model, context) else Severity.WARNING


def _inert_description_model(model: ast.ClassDef, context: PythonFileContext) -> bool:
    if context.dynamic_namespace or not inert_direct_model_body(model, context.imports):
        return False
    provenance = context.static_resource_provenance
    for node in walk_ast(model):
        if isinstance(node, ast.keyword) and node.arg == "json_schema_extra":
            return False
        if not _annotation_provider_proven(node, context, provenance):
            return False
        if isinstance(node, ast.Call) and not provenance.imported(
            node.func, context.imports.resolved_qualified_name(node.func) or "pydantic.Field"
        ):
            return False
    return any(
        provenance.imported(base, context.imports.resolved_qualified_name(base) or "pydantic.BaseModel")
        for base in model.bases
    )


def _annotation_provider_proven(node: ast.AST, context: PythonFileContext, provenance: ResourceProvenance) -> bool:
    if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Constant):
        return False
    if isinstance(node, ast.Subscript) and context.imports.resolved_qualified_name(node.value) in {
        "typing.Annotated",
        "typing_extensions.Annotated",
    }:
        argument = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) and node.slice.elts else node.slice
        return not isinstance(argument, ast.Constant)
    if isinstance(node, ast.Name | ast.Attribute) and (qualified := context.imports.resolved_qualified_name(node)) in {
        "typing.Literal",
        "typing.Annotated",
        "typing_extensions.Literal",
        "typing_extensions.Annotated",
    }:
        return provenance.imported(node, qualified)
    return True


def _is_direct_model(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return any(imports.resolves(base, sources=_PYDANTIC_BASE_MODEL_SOURCES, symbol="BaseModel") for base in node.bases)


def _local_closed_domains(tree: ast.Module, imports: ImportIndex) -> dict[str, frozenset[str]]:
    domains: dict[str, frozenset[str]] = {}
    for statement in tree.body:
        name = _bound_name(statement)
        if name is None:
            continue
        if isinstance(statement, ast.ClassDef):
            domain = _enum_domain(statement, imports)
        else:
            value = statement.value if isinstance(statement, (ast.Assign, ast.AnnAssign)) else None
            domain = _closed_domain(value, imports, domains) if isinstance(value, ast.expr) else None
        if domain is None:
            domains.pop(name, None)
        else:
            domains[name] = domain
    return domains


def _bound_name(statement: ast.stmt) -> str | None:
    match statement:
        case ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
            return statement.name
        case ast.AnnAssign(target=ast.Name(id=name)) | ast.Assign(targets=[ast.Name(id=name)]):
            return name
        case _:
            return None


def _module_import_index(tree: ast.Module) -> ImportIndex:
    body: list[ast.stmt] = []
    for statement in tree.body:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            body.append(statement)
            continue
        name = _bound_name(statement)
        if name is not None:
            body.append(ast.Assign(targets=[ast.Name(id=name, ctx=ast.Store())], value=ast.Constant(None)))
    return ImportIndex.from_tree(ast.Module(body=body, type_ignores=[]))


def _enum_domain(node: ast.ClassDef, imports: ImportIndex) -> frozenset[str] | None:
    if not any(
        imports.resolves(base, sources=_ENUM_SOURCES, symbol=symbol)
        for base in node.bases
        for symbol in ("Enum", "StrEnum")
    ):
        return None
    values: set[str] = set()
    for statement in node.body:
        value = statement.value if isinstance(statement, (ast.Assign, ast.AnnAssign)) else None
        if value is None:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return None
        values.add(value.value)
    return frozenset(values) if values else None


def _closed_domain(
    node: ast.expr | None, imports: ImportIndex, local_domains: dict[str, frozenset[str]]
) -> frozenset[str] | None:
    if isinstance(node, ast.Name):
        return local_domains.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _closed_union_domain(node, imports, local_domains)
    if not isinstance(node, ast.Subscript):
        return None
    if imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Literal"):
        return _literal_domain(node)
    if imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Annotated"):
        members = node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
        return _closed_domain(members[0], imports, local_domains) if members else None
    return None


def _closed_union_domain(
    node: ast.expr, imports: ImportIndex, local_domains: dict[str, frozenset[str]]
) -> frozenset[str] | None:
    values: set[str] = set()
    pending = [node]
    while pending:
        member = pending.pop()
        if isinstance(member, ast.BinOp) and isinstance(member.op, ast.BitOr):
            pending.extend((member.right, member.left))
            continue
        domain = _closed_domain(member, imports, local_domains)
        if domain is None:
            return None
        values.update(domain)
    return frozenset(values)


def _repeats_domain(description: str, domain: frozenset[str]) -> bool:
    match = _DOMAIN_CLAUSE.search(description)
    if match is None:
        return False
    body = match.group("body")
    quoted = tuple(item.group("value") for item in _QUOTED_VALUE.finditer(body))
    values = frozenset(quoted) if quoted else frozenset(_IDENTIFIER_VALUE.findall(body))
    if values != domain:
        return False
    residue = _QUOTED_VALUE.sub("", body) if quoted else _IDENTIFIER_VALUE.sub("", body)
    residue = re.sub(r"\b(?:and|or)\b|[\s,\[\](){}]", "", residue, flags=re.IGNORECASE)
    return not residue


def _has_custom_schema_hook(model: ast.ClassDef) -> bool:
    return any(
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == "__get_pydantic_json_schema__"
        for statement in model.body
    )


def _has_schema_override(annotation: ast.expr, imports: ImportIndex) -> bool:
    return any(
        isinstance(node, ast.Call)
        and imports.resolves(
            node.func,
            sources=frozenset({"pydantic", "pydantic.json_schema"}),
            symbol="WithJsonSchema",
        )
        for node in walk_ast(annotation)
    )


def _field_calls(statement: ast.AnnAssign, imports: ImportIndex) -> tuple[ast.Call, ...]:
    candidates: list[ast.expr] = []
    if statement.value is not None:
        candidates.append(statement.value)
    annotation = statement.annotation
    if isinstance(annotation, ast.Subscript) and imports.resolves(
        annotation.value, sources=_TYPING_SOURCES, symbol="Annotated"
    ):
        members = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else (annotation.slice,)
        candidates.extend(members[1:])
    return tuple(
        candidate
        for candidate in candidates
        if isinstance(candidate, ast.Call)
        and imports.resolves(candidate.func, sources=_PYDANTIC_FIELD_SOURCES, symbol="Field")
    )


def _literal_domain(node: ast.Subscript) -> frozenset[str] | None:
    members = node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
    values: set[str] = set()
    for member in members:
        if not isinstance(member, ast.Constant) or not isinstance(member.value, str):
            return None
        values.add(member.value)
    return frozenset(values)
