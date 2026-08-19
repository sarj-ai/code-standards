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
    parse_or_none,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_PYDANTIC_BASE_MODEL_SOURCES = frozenset({"pydantic", "pydantic.main"})
_PYDANTIC_FIELD_SOURCES = frozenset({"pydantic", "pydantic.fields"})
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_ENUM_SOURCES = frozenset({"enum"})
_DOMAIN_ONLY = re.compile(r"^\s*(?:must|should)\s+be(?:\s+one\s+of)?\s+(?P<body>.+?)\s*[.!]?\s*$", re.IGNORECASE)
_QUOTED_VALUE = re.compile(r"(['\"])(?P<value>.+?)\1")


@final
class NoRedundantLiteralDescription(Rule):
    id = "no-redundant-literal-description"
    code = "SARJ422"
    documentation = RuleDocumentation(
        summary="Do not restate a Literal or Enum field's closed domain in its Pydantic description.",
        rationale=(
            "Pydantic already publishes literal and enum domains in JSON Schema; duplicate must-be prose can "
            "contradict the generated contract after a value changes."
        ),
        remediation="Remove the domain-only description or replace it with rationale not encoded by the field type.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only direct fields on direct BaseModel subclasses are inspected.",
            "Enum fields are inspected only when their direct string-valued enum class is declared in the same module.",
            "Descriptions are reported only when they begin with a narrow 'must be' or 'should be' restatement.",
            "Test and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="literal-domain-restated",
                title="Literal domain repeated in prose",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Literal\nfrom pydantic import BaseModel, Field\n\n"
                        "class Request(BaseModel):\n"
                        "    kind: Literal['call'] = Field(description=\"Must be 'call'\")\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="literal-rationale-described",
                title="Description adds rationale",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/models.py",
                        "from typing import Literal\nfrom pydantic import BaseModel, Field\n\n"
                        "class Request(BaseModel):\n"
                        "    kind: Literal['call'] = Field(description='Routes through the realtime provider.')\n",
                    ),
                ),
                focus_path=PurePosixPath("app/models.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree)
        enum_domains = _local_enum_domains(tree, imports)
        diagnostics: list[Diagnostic] = []
        for model in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            if not _is_direct_model(model, imports):
                continue
            for statement in model.body:
                if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
                    continue
                domain = _closed_domain(statement.annotation, imports, enum_domains)
                if domain is None:
                    continue
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
                                f"`{statement.target.id}` repeats its closed type domain in `description`; "
                                "remove the restatement or document rationale not present in the schema."
                            ),
                        )
                    )
        return diagnostics


def _is_direct_model(node: ast.ClassDef, imports: ImportIndex) -> bool:
    return len(node.bases) == 1 and imports.resolves(
        node.bases[0], sources=_PYDANTIC_BASE_MODEL_SOURCES, symbol="BaseModel"
    )


def _local_enum_domains(tree: ast.Module, imports: ImportIndex) -> dict[str, frozenset[str]]:
    domains: dict[str, frozenset[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not any(
            imports.resolves(base, sources=_ENUM_SOURCES, symbol=symbol)
            for base in node.bases
            for symbol in ("Enum", "IntEnum", "StrEnum")
        ):
            continue
        values: set[str] = set()
        complete = True
        for statement in node.body:
            value = statement.value if isinstance(statement, (ast.Assign, ast.AnnAssign)) else None
            if value is None:
                continue
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                complete = False
                break
            values.add(value.value)
        if complete and values:
            domains[node.name] = frozenset(values)
    return domains


def _closed_domain(
    node: ast.expr, imports: ImportIndex, enum_domains: dict[str, frozenset[str]]
) -> frozenset[str] | None:
    if isinstance(node, ast.Name):
        return enum_domains.get(node.id)
    if not isinstance(node, ast.Subscript):
        return None
    if imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Literal"):
        members = node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
        values: set[str] = set()
        for member in members:
            if not isinstance(member, ast.Constant) or not isinstance(member.value, str):
                return None
            values.add(member.value)
        return frozenset(values)
    if imports.resolves(node.value, sources=_TYPING_SOURCES, symbol="Annotated"):
        members = node.slice.elts if isinstance(node.slice, ast.Tuple) else (node.slice,)
        return _closed_domain(members[0], imports, enum_domains) if members else None
    return None


def _repeats_domain(description: str, domain: frozenset[str]) -> bool:
    match = _DOMAIN_ONLY.fullmatch(description)
    if match is None:
        return False
    body = match.group("body")
    values = frozenset(item.group("value") for item in _QUOTED_VALUE.finditer(body))
    if values != domain:
        return False
    residue = _QUOTED_VALUE.sub("", body)
    residue = re.sub(r"\b(?:and|or)\b|[\s,\[\](){}]", "", residue, flags=re.IGNORECASE)
    return not residue


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
