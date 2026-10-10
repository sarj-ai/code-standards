from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import (
    document,
    header_comment_lines,
    strip_outer_parentheses,
    tokens,
)
from sarj_iac_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)


if TYPE_CHECKING:
    from pathlib import Path


_GENERATED_RE = re.compile(r"generated.{0,80}(?:do not edit|don't edit)", re.IGNORECASE)
_FIXTURE_DIRS = frozenset({"fixture", "fixtures", "testdata", "generated"})
_MIN_TYPE_CONSTRUCTOR_TOKENS = 4
_MIN_CALL_TOKENS = 4
_BINARY_PART_COUNT = 2
_MIN_CONTAINS_TOKENS = 7
_MIN_BOOLEAN_LIST_TOKENS = 5


class _TypeKind(StrEnum):
    BOOL = "bool"
    LIST = "list"
    MAP = "map"
    NUMBER = "number"
    OBJECT = "object"
    SET = "set"
    STRING = "string"
    TUPLE = "tuple"


_CONVERSION_FOR_TYPE = MappingProxyType(
    {
        _TypeKind.BOOL: "tobool",
        _TypeKind.LIST: "tolist",
        _TypeKind.MAP: "tomap",
        _TypeKind.NUMBER: "tonumber",
        _TypeKind.SET: "toset",
        _TypeKind.STRING: "tostring",
    }
)
_LENGTH_TYPES = frozenset(
    {
        _TypeKind.STRING,
        _TypeKind.LIST,
        _TypeKind.SET,
        _TypeKind.MAP,
        _TypeKind.OBJECT,
        _TypeKind.TUPLE,
    }
)
_KEY_TYPES = frozenset({_TypeKind.MAP, _TypeKind.OBJECT})


@final
class NoRedundantVariableValidation(Rule):
    id = "no-redundant-variable-validation"
    code = "SARJ209"
    documentation = RuleDocumentation(
        summary="Flag Terraform variable validation conditions already guaranteed by the variable's type constraint.",
        rationale=(
            "Terraform applies a declared type constraint before custom validation. Rechecking that the same value "
            "can be read, converted to its declared type, or exhausts a non-nullable boolean domain adds a second "
            "contract that cannot reject a valid input and obscures the validations that enforce real domain rules."
        ),
        remediation=(
            "Delete the redundant validation block. Keep validation for narrower domain requirements such as ranges, "
            "formats, enums, nullability, and relationships between fields."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only exact, syntax-parsed tautologies over the validation block's own variable are reported.",
            (
                "Provider constraints, compound expressions containing a real domain predicate, dynamic types, "
                "heterogeneous tuples, and validations of another variable are intentionally not inferred."
            ),
            "Generated files, fixtures, testdata, and non-.tf inputs are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="declared-string-conversion",
                title="String conversion repeats the declared string type",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "region" {\n'
                        "  type = string\n"
                        "  validation {\n"
                        "    condition     = can(tostring(var.region))\n"
                        '    error_message = "Region must be a string."\n'
                        "  }\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("variables.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="string-domain-format",
                title="String validation enforces a narrower domain format",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "region" {\n'
                        "  type = string\n"
                        "  validation {\n"
                        '    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+$", var.region))\n'
                        '    error_message = "Region must use the provider region format."\n'
                        "  }\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("variables.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="non-nullable-boolean-domain",
                title="Boolean enumeration repeats a non-nullable boolean type",
                outcome=ExampleOutcome.MATCH,
                scenario="nullability",
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "enabled" {\n'
                        "  type     = bool\n"
                        "  nullable = false\n"
                        "  validation {\n"
                        "    condition     = contains([true, false], var.enabled)\n"
                        '    error_message = "Enabled must be true or false."\n'
                        "  }\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("variables.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="nullable-boolean-null-guard",
                title="Boolean enumeration rejects an otherwise permitted null",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="nullability",
                files=(
                    ExampleFile.iac(
                        "variables.tf",
                        'variable "enabled" {\n'
                        "  type = bool\n"
                        "  validation {\n"
                        "    condition     = contains([true, false], var.enabled)\n"
                        '    error_message = "Enabled must not be null."\n'
                        "  }\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("variables.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf" or _fixture_path(path) or _generated_header(source):
            return []
        try:
            root = document(source)
        except ValueError:
            return []
        findings: list[Diagnostic] = []
        for variable in root.blocks:
            if variable.type != "variable" or len(variable.labels) != 1:
                continue
            type_attribute = variable.attribute("type")
            if type_attribute is None or (type_kind := _type_kind(tokens(type_attribute.value))) is None:
                continue
            name = variable.labels[0]
            nullable = variable.attribute("nullable")
            forbids_null = nullable is not None and strip_outer_parentheses(tokens(nullable.value)) == ("false",)
            for validation in variable.blocks:
                if validation.type != "validation" or (condition := validation.attribute("condition")) is None:
                    continue
                if _restates_type(tokens(condition.value), name, type_kind, forbids_null=forbids_null):
                    findings.append(
                        Diagnostic(
                            path,
                            condition.line,
                            condition.col,
                            self.code,
                            (
                                f"Validation of `var.{name}` is already guaranteed by its declared `{type_kind}` type; "
                                "delete this validation block."
                            ),
                        )
                    )
        return findings


def _type_kind(value: tuple[str, ...]) -> _TypeKind | None:
    normalized = strip_outer_parentheses(value)
    if len(normalized) == 1:
        try:
            kind = _TypeKind(normalized[0])
        except ValueError:
            return None
        return kind if kind in {_TypeKind.BOOL, _TypeKind.NUMBER, _TypeKind.STRING} else None
    if (
        len(normalized) >= _MIN_TYPE_CONSTRUCTOR_TOKENS
        and normalized[1] == "("
        and normalized[-1] == ")"
        and _matching_closer(normalized, 1) == len(normalized) - 1
    ):
        try:
            kind = _TypeKind(normalized[0])
        except ValueError:
            return None
        if kind in {_TypeKind.LIST, _TypeKind.MAP, _TypeKind.OBJECT, _TypeKind.SET, _TypeKind.TUPLE}:
            return kind
    return None


def _restates_type(
    condition: tuple[str, ...],
    variable_name: str,
    type_kind: _TypeKind,
    *,
    forbids_null: bool,
) -> bool:
    normalized = strip_outer_parentheses(condition)
    variable = f"var.{variable_name}"
    if (can_argument := _unary_call(normalized, "can")) is not None:
        can_argument = strip_outer_parentheses(can_argument)
        if can_argument == (variable,):
            return True
        conversion = _CONVERSION_FOR_TYPE.get(type_kind)
        if conversion is not None and _unary_call(can_argument, conversion) == (variable,):
            return True
        if forbids_null and type_kind in _LENGTH_TYPES and _unary_call(can_argument, "length") == (variable,):
            return True
        if forbids_null and type_kind in _KEY_TYPES and _unary_call(can_argument, "keys") == (variable,):
            return True
    return (
        forbids_null
        and type_kind is _TypeKind.BOOL
        and (
            _is_exhaustive_boolean_equality(normalized, variable)
            or _is_exhaustive_boolean_contains(normalized, variable)
        )
    )


def _unary_call(value: tuple[str, ...], function: str) -> tuple[str, ...] | None:
    normalized = strip_outer_parentheses(value)
    if len(normalized) < _MIN_CALL_TOKENS or normalized[:2] != (function, "(") or normalized[-1] != ")":
        return None
    if _matching_closer(normalized, 1) != len(normalized) - 1:
        return None
    argument = normalized[2:-1]
    return strip_outer_parentheses(argument) if _top_level_split(argument, ",") is None else None


def _is_exhaustive_boolean_equality(value: tuple[str, ...], variable: str) -> bool:
    parts = _top_level_split(value, "||")
    if parts is None:
        return False
    literals: set[str] = set()
    for part in parts:
        equality = _top_level_split(strip_outer_parentheses(part), "==")
        if equality is None or len(equality) != _BINARY_PART_COUNT:
            return False
        left, right = (strip_outer_parentheses(item) for item in equality)
        if left == (variable,) and right in {("true",), ("false",)}:
            literals.add(right[0])
        elif right == (variable,) and left in {("true",), ("false",)}:
            literals.add(left[0])
        else:
            return False
    return literals == {"true", "false"}


def _is_exhaustive_boolean_contains(value: tuple[str, ...], variable: str) -> bool:
    normalized = strip_outer_parentheses(value)
    if len(normalized) < _MIN_CONTAINS_TOKENS or normalized[:2] != ("contains", "(") or normalized[-1] != ")":
        return False
    if _matching_closer(normalized, 1) != len(normalized) - 1:
        return False
    arguments = _top_level_split(normalized[2:-1], ",")
    if (
        arguments is None
        or len(arguments) != _BINARY_PART_COUNT
        or strip_outer_parentheses(arguments[1]) != (variable,)
    ):
        return False
    collection = strip_outer_parentheses(arguments[0])
    if len(collection) < _MIN_BOOLEAN_LIST_TOKENS or collection[0] != "[" or collection[-1] != "]":
        return False
    items = _top_level_split(collection[1:-1], ",")
    return items is not None and {strip_outer_parentheses(item) for item in items} == {("true",), ("false",)}


def _top_level_split(value: tuple[str, ...], delimiter: str) -> tuple[tuple[str, ...], ...] | None:
    depth = 0
    starts = [0]
    for index, token in enumerate(value):
        if token in {"(", "[", "{"}:
            depth += 1
        elif token in {
            ")",
            "]",
            "}",
        }:
            depth -= 1
            if depth < 0:
                return None
        elif token == delimiter and depth == 0:
            starts.append(index + 1)
    if depth != 0 or len(starts) == 1:
        return None
    ends = [start - 1 for start in starts[1:]] + [len(value)]
    parts = tuple(value[start:end] for start, end in zip(starts, ends, strict=True))
    return parts if all(parts) else None


def _matching_closer(value: tuple[str, ...], opener_index: int) -> int | None:
    open_token = value[opener_index]
    closer = {"(": ")", "[": "]", "{": "}"}.get(open_token)
    if closer is None:
        return None
    depth = 0
    for index in range(opener_index, len(value)):
        if value[index] == open_token:
            depth += 1
        elif value[index] == closer:
            depth -= 1
            if depth == 0:
                return index
    return None


def _fixture_path(path: Path) -> bool:
    return any(part.lower() in _FIXTURE_DIRS for part in path.parts)


def _generated_header(source: str) -> bool:
    comments = (line.lstrip().removeprefix("*").strip() for line in header_comment_lines(source, leading_only=True))
    return _GENERATED_RE.search(" ".join(comments)) is not None
