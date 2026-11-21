from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import call_arguments, conditional_branches, header_comment_lines, literal_string, tokens
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
from sarj_iac_lint.rules._literal_policy import local_collections, resolve_local_tokens
from sarj_iac_lint.terraform import TerraformSession, is_terraform, terraform_blocks


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

    from sarj_iac_lint._hcl import Attribute, Block


_FIXTURE_DIRS = frozenset({"fixture", "fixtures", "testdata", "generated"})
_GENERATED = re.compile(r"generated.{0,80}(?:do not edit|don't edit)", re.IGNORECASE)
_COLLECTION_CONVERSIONS = frozenset({"toset", "tomap", "tolist"})


@final
class ConditionalResourcePresence(Rule):
    id = "conditional-resource-presence"
    code = "SARJ221"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Prefer stable Terraform resource presence or an explicit review justification.",
        rationale=(
            "Conditional zero/empty instance selections duplicate provisioning paths and introduce indexed resource "
            "references. Temporary migration switches can outlive the migration and obscure the intended topology."
        ),
        remediation=(
            "Prefer a direct migration and stable resource declarations. If optional provisioning is necessary, "
            "justify its lifetime and ownership in the PR or input description. Preserve state addresses and "
            "restore/cutover ordering when simplifying an existing deployment."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "This is a review advisory, not proof that optional infrastructure is wrong. No resource deletion or state-address rewrite is automatic.",
            "Inspect count and for_each on resource, module and ephemeral blocks, including direct same-file local aliases and collection conversions. Plain multiplicity, ordinary value selections, data lookups and member-specific comprehension filters are not targeted.",
            "The shared analysis session resolves same-module cross-file local aliases. Object traversals and arbitrary function results remain opaque; cycles and ambiguous declarations are not guessed.",
            "The specific deployment-identity policy takes precedence; this warning takes precedence over a generic nested-selection warning at the same attribute when both rules are selected.",
            "Covers authored .tf and .tf.json; generated headers, fixtures and other HCL dialects are excluded. Review justification does not require adding a Terraform comment.",
            "Safe fixes cover native HCL single-line count expressions whose conditions are Boolean literals and whose branches are homogeneous bounded scalar literals. The selected result must be a nonnegative integer. The count attribute, labels, indices and every other parsed attribute remain unchanged. Symbolic/default/date decisions, for_each, JSON, comments, unknown functions and mixed branch types are refused.",
        ),
        examples=(
            RuleExample(
                example_id="literal-count",
                scenario="literal-count",
                title="Fold a literal gate while retaining indexed instances",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.iac("main.tf", 'resource "example_service" "this" {\n  count = true ? 1 : 0\n}\n'),),
                fixed_files=(ExampleFile.iac("main.tf", 'resource "example_service" "this" {\n  count = 1\n}\n'),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="stable-count-addresses",
                scenario="literal-count",
                title="The count attribute preserves instance addresses",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.iac("main.tf", 'resource "example_service" "this" {\n  count = 1\n}\n'),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="temporary-provisioning-switch",
                title="A migration switch retains two provisioning paths",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf", 'resource "example_service" "this" {\n  count = var.use_new ? 1 : 0\n}\n'
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="stable-provisioning",
                title="The desired resource is declared directly",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.iac("main.tf", 'resource "example_service" "this" {}\n'),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    def __init__(self, *, session: TerraformSession | None = None) -> None:
        self.session = session

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_terraform(path) or "?" not in source or any(part.lower() in _FIXTURE_DIRS for part in path.parts):
            return []
        if _GENERATED.search(" ".join(header_comment_lines(source, leading_only=True))):
            return []
        try:
            top = terraform_blocks(path, source)
            values = local_collections(self.session.blocks(path) if self.session is not None else top)
            return [
                Diagnostic(
                    path,
                    attribute.line,
                    attribute.col,
                    self.code,
                    _gate_message(block.type, block.labels, attribute.name, tokens(attribute.value), values),
                    severity=DefaultLevel.WARNING,
                )
                for block, attribute in _presence_attributes(top)
                if _gates_presence(tokens(attribute.value), values, collection=attribute.name == "for_each")
            ]
        except ValueError:
            return []


def _gate_message(
    kind: str, labels: tuple[str, ...], attribute: str, parts: tuple[str, ...], values: Mapping[str, str]
) -> str:
    resolved = resolve_local_tokens(parts, values)
    identity = ".".join((kind, *labels, attribute))
    if resolved is not None and resolved[:2] in {("true", "?"), ("false", "?")}:
        return (
            f"{identity} has a Boolean-literal gate, independent of deployment inputs. Simplify the expression only after preserving branch types, count indices or for_each keys, references and outputs. "
            "Keep the count/for_each attribute; deleting it changes instance addresses and requires a reviewed state migration."
        )
    return (
        f"Conditional resource presence at {identity}: review the input's Retire by/Remove when or Permanent description and every supported configuration. "
        "A name, default, repeated tfvars value or expired date does not establish cutover or rollback readiness. "
        "Preserve count indices/for_each keys, references, outputs and deployment differences; any address change requires reviewed migration evidence."
    )


def _normalize(
    parts: tuple[str, ...], values: Mapping[str, str], *, collection: bool
) -> tuple[tuple[str, ...], bool] | None:
    seen: set[tuple[tuple[str, ...], bool]] = set()
    while True:
        resolved = resolve_local_tokens(parts, values)
        if resolved is None:
            return None
        parts = resolved
        state = parts, collection
        if state in seen:
            return None
        seen.add(state)
        args = call_arguments(parts)
        if args is None or len(args) != 1:
            return state
        if (collection and parts[0] in _COLLECTION_CONVERSIONS) or (not collection and parts[0] == "tonumber"):
            parts = args[0]
        elif not collection and parts[0] == "length":
            parts, collection = args[0], True
        else:
            return state


def _gates_presence(parts: tuple[str, ...], values: Mapping[str, str], *, collection: bool) -> bool:
    pending = [(parts, collection)]
    seen: set[tuple[tuple[str, ...], bool]] = set()
    while pending:
        parts, collection = pending.pop()
        normalized = _normalize(parts, values, collection=collection)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        parts, collection = normalized
        branches = conditional_branches(parts)
        if not branches:
            continue
        left, right = branches
        if _empty(left, values, collection=collection) != _empty(right, values, collection=collection):
            return True
        pending.extend((branch, collection) for branch in branches)
    return False


def _empty(parts: tuple[str, ...], values: Mapping[str, str], *, collection: bool) -> bool:
    normalized = _normalize(parts, values, collection=collection)
    if normalized is None:
        return False
    parts, collection = normalized
    if collection:
        return parts in {("{", "}"), ("[", "]")}
    literal = literal_string(" ".join(parts))
    try:
        return Decimal(literal if literal is not None else "".join(parts)) == 0
    except InvalidOperation:
        return False


def _presence_attributes(blocks: tuple[Block, ...]) -> Iterator[tuple[Block, Attribute]]:
    for block in blocks:
        if block.type in {"resource", "module", "ephemeral"}:
            for attribute in block.attributes:
                if attribute.name in {"count", "for_each"}:
                    yield block, attribute
