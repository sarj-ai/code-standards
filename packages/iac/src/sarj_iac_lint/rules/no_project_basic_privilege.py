from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import literal_string, strip_outer_parentheses, tokens
from sarj_iac_lint.rule_base import (
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)
from sarj_iac_lint.rules._literal_policy import balanced_blocks


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sarj_iac_lint._hcl import Block

_BASIC_PRIVILEGES = frozenset({"roles/owner", "roles/editor"})
_LABEL_COUNT = 2
_BINDINGS_DEPTH = 2
_JOIN_ARGUMENT_COUNT = 2
_MAX_LOCAL_ALIAS_DEPTH = 16
_MAX_STATIC_EXPRESSION_DEPTH = 32
_GRANTS = frozenset({"google_project_iam_member", "google_project_iam_binding"})


@final
class NoProjectBasicPrivilege(Rule):
    id = "no-project-basic-privilege"
    code = "SARJ212"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Disallow proven project IAM Owner and Editor grants.",
        rationale="Project Owner and Editor grants confer broad mutable access across project services.",
        remediation="Grant the specific predefined or custom roles required by the principal.",
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only project IAM member, binding and policy resources in .tf files are checked.",
            "Literal roles, literal for_each role sets, same-file unique local tuples/sets, jsonencode bindings and same-file google_iam_policy data are recognized.",
            "Scalar role values also follow same-file unique static local aliases and bounded literal join expressions; grouping and HCL string escapes preserve the value. Cycles, duplicate declarations, templates and unknown inputs remain opaque.",
            "Local collections must be literal strings consumed as a set; duplicate declarations, local aliases, dynamic values, maps and comprehensions are excluded.",
            "Unknown expressions, inherited organization/folder access and other roles are not guessed.",
        ),
        examples=tuple(
            RuleExample(
                example_id=example_id,
                title=title,
                outcome=outcome,
                files=(ExampleFile.iac("main.tf", source),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=count,
                public=True,
            )
            for example_id, title, outcome, source, count in (
                (
                    "project-editor",
                    "Project Editor grants broad mutable access",
                    ExampleOutcome.MATCH,
                    (
                        'locals { grants = ["roles/editor", "roles/logging.logWriter"] }\n'
                        'resource "google_project_iam_member" "app" {\n'
                        "  for_each = toset(local.grants)\n  role = each.value\n}\n"
                    ),
                    1,
                ),
                (
                    "specific-role",
                    "A specific role stays scoped",
                    ExampleOutcome.NO_MATCH,
                    'resource "google_project_iam_member" "app" { role = "roles/logging.logWriter" }\n',
                    0,
                ),
            )
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix.lower() != ".tf":
            return []
        try:
            top = balanced_blocks(source)
        except ValueError:
            return []
        collections = _local_collections(top)
        policies = {
            f"data.google_iam_policy.{block.labels[1]}.policy_data": _data_policy_roles(block, collections)
            for block in top
            if block.type == "data" and len(block.labels) == _LABEL_COUNT and block.labels[0] == "google_iam_policy"
        }
        findings: list[Diagnostic] = []
        for block in top:
            if block.type != "resource" or not block.labels:
                continue
            roles: frozenset[str] = frozenset()
            if block.labels[0] in _GRANTS:
                roles = _grant_roles(block, collections)
            elif block.labels[0] == "google_project_iam_policy" and (attr := block.attribute("policy_data")):
                roles = policies.get(attr.value.strip(), _jsonencode_roles(attr.value))
            forbidden = sorted(roles & _BASIC_PRIVILEGES)
            if forbidden:
                findings.append(
                    Diagnostic(
                        path,
                        block.line,
                        block.col,
                        self.code,
                        f"Project IAM grants {', '.join(forbidden)}; use specific predefined or custom roles",
                    )
                )
        return findings


def _local_collections(top: tuple[Block, ...]) -> dict[str, str]:
    attributes = [attr for block in top if block.type == "locals" and not block.labels for attr in block.attributes]
    counts = Counter(attr.name for attr in attributes)
    return {attr.name: attr.value for attr in attributes if counts[attr.name] == 1}


def _grant_roles(block: Block, collections: Mapping[str, str] | None = None) -> frozenset[str]:
    attr = block.attribute("role")
    if attr is None:
        return frozenset()
    value = attr.value.strip()
    literal = None if value.endswith(",") else _static_string(tokens(value), collections or {})
    if literal is not None:
        return frozenset({literal})
    if attr.value.strip() not in {"each.value", "each.key"} or (each := block.attribute("for_each")) is None:
        return frozenset()
    parts = _role_set_items(each.value, collections)
    values = [literal_string(part) for part in parts if part != ","]
    return frozenset(value for value in values if value is not None) if all(values) else frozenset()


def _static_string(
    parts: tuple[str, ...], local_values: Mapping[str, str], seen: frozenset[str] = frozenset(), depth: int = 0
) -> str | None:
    if depth >= _MAX_STATIC_EXPRESSION_DEPTH:
        return None
    parts = strip_outer_parentheses(parts)
    if len(parts) == 1:
        literal = literal_string(parts[0])
        if literal is not None:
            return literal
        alias = parts[0].removeprefix("local.") if parts[0].startswith("local.") else ""
        if alias in local_values and alias not in seen and len(seen) < _MAX_LOCAL_ALIAS_DEPTH:
            return _static_string(tokens(local_values[alias]), local_values, seen | {alias}, depth + 1)
        return None
    return _static_join(parts, local_values, seen, depth)


def _static_join(
    parts: tuple[str, ...], local_values: Mapping[str, str], seen: frozenset[str], depth: int
) -> str | None:
    if parts[:2] != ("join", "(") or parts[-1:] != (")",):
        return None
    arguments = _comma_parts(parts[2:-1])
    if len(arguments) != _JOIN_ARGUMENT_COUNT:
        return None
    separator = _static_string(arguments[0], local_values, seen, depth + 1)
    collection = arguments[1]
    if separator is None or collection[:1] != ("[",) or collection[-1:] != ("]",):
        return None
    elements = [_static_string(element, local_values, seen, depth + 1) for element in _comma_parts(collection[1:-1])]
    return (
        separator.join(element for element in elements if element is not None)
        if all(element is not None for element in elements)
        else None
    )


def _comma_parts(parts: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    values: list[tuple[str, ...]] = []
    start, depth = 0, 0
    for index, part in enumerate(parts):
        if part in {"(", "[", "{"}:
            depth += 1
        elif part in {")", "]", "}"}:
            depth -= 1
        elif part == "," and depth == 0:
            values.append(parts[start:index])
            start = index + 1
    if start < len(parts):
        values.append(parts[start:])
    return tuple(values)


def _role_set_items(expression: str, collections: Mapping[str, str] | None) -> tuple[str, ...]:
    parts = tokens(expression)
    as_set = parts[:2] == ("toset", "(") and parts[-1:] == (")",)
    if as_set:
        parts = parts[2:-1]
    if len(parts) == 1 and parts[0].startswith("local."):
        expression = collections.get(parts[0][len("local.") :], "") if collections is not None else ""
        parts = tokens(expression)
        local_set = parts[:2] == ("toset", "(") and parts[-1:] == (")",)
        if not as_set and not local_set:
            return ()
        if local_set:
            parts = parts[2:-1]
    if parts[:1] != ("[",) or parts[-1:] != ("]",):
        return ()
    return parts[1:-1]


def _data_policy_roles(block: Block, collections: Mapping[str, str]) -> frozenset[str]:
    return frozenset(
        role for binding in block.blocks if binding.type == "binding" for role in _grant_roles(binding, collections)
    )


def _jsonencode_roles(value: str) -> frozenset[str]:
    parts = tokens(value)
    if parts[:3] != ("jsonencode", "(", "{") or parts[-2:] != ("}", ")"):
        return frozenset()
    # Match only literal role attributes of direct objects in the bindings list.
    # Strings in members, metadata, nested conditions or unknown expressions never prove a grant.
    roles: set[str] = set()
    stack: list[str] = []
    bindings_depth: int | None = None
    for index, part in enumerate(parts[2:-1], start=2):
        if part in {"{", "[", "("}:
            stack.append(part)
        elif part in {"}", "]", ")"}:
            if not stack:
                return frozenset()
            stack.pop()
            if bindings_depth is not None and len(stack) < bindings_depth:
                bindings_depth = None
        if (
            part in {"bindings", '"bindings"'}
            and len(stack) == 1
            and parts[index + 1 : index + 2] in {("=",), (":",)}
            and parts[index + 2 : index + 3] == ("[",)
        ):
            bindings_depth = _BINDINGS_DEPTH
        role = _binding_literal_role(parts, index, stack, bindings_depth)
        if role is not None:
            roles.add(role)
    return frozenset(roles)


def _binding_literal_role(
    parts: tuple[str, ...], index: int, stack: list[str], bindings_depth: int | None
) -> str | None:
    if (
        parts[index] not in {"role", '"role"'}
        or bindings_depth != _BINDINGS_DEPTH
        or stack != ["{", "[", "{"]
        or parts[index + 1 : index + 2] not in {("=",), (":",)}
    ):
        return None
    return literal_string(parts[index + 2]) if _literal_ends(parts, index + 3) else None


def _literal_ends(parts: tuple[str, ...], index: int) -> bool:
    return parts[index : index + 1] in {(",",), ("}",)} or parts[index + 1 : index + 2] in {("=",), (":",)}
