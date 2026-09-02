from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_iac_lint._hcl import document, tokens
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
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from sarj_iac_lint._hcl import Attribute, Block

# Names that directly identify an environment. More ambiguous deployment terms
# require corroboration from an environment-shaped literal.
ENVIRONMENT_SEGMENTS = frozenset({"environment", "env"})

# Segments that are also ordinary product words. These count only when every other
# segment is a neutral qualifier, so `var.project` and `var.gcp_project_id` match
# while `var.langfuse_ui_project_id` (a third-party resource id) does not.
QUALIFIED_SEGMENTS = frozenset({"project", "slug", "branch", "account", "tenant", "stage", "workspace", "deployment"})

_NEUTRAL_QUALIFIERS = frozenset(
    {
        "gcp",
        "google",
        "aws",
        "azure",
        "cloud",
        "tf",
        "terraform",
        "id",
        "ids",
        "name",
        "number",
        "short",
        "target",
        "main",
        "primary",
        "host",
    }
)

# Weak identity names need corroboration from the compared literal. These are
# exact segments rather than substrings: `product` and `developmental` are not
# deployment labels, while `platform-prod` and `preview_us` are.
_ENVIRONMENT_LITERAL_SEGMENTS = frozenset(
    {"dev", "development", "preview", "prod", "production", "qa", "sandbox", "stage", "staging", "test", "testing"}
)
_LITERAL_SEGMENT_RE = re.compile(r"[^a-z0-9]+")

_WORKSPACE = "terraform.workspace"
_IDENTITY_PREFIXES = ("var.", "local.")

_CONTAINS = "contains"
_COMPARISONS = frozenset({"==", "!="})
_NORMALIZERS = frozenset({"lower", "trimspace", "upper"})
_CONTAINS_ARGS = 2

_OPEN = frozenset({"(", "[", "{"})
_CLOSE = frozenset({")", "]", "}"})

# Words that read like identifiers but head expressions: `if (x)` groups, `foo(x)` calls.
_EXPRESSION_KEYWORDS = frozenset({"if", "for", "in"})

# Checked first to avoid duplicate diagnostics: SARJ206 categorically owns these files.
_TEST_SUFFIXES = (".tftest.hcl", ".tftest.json")

_LIST_TOKENS = 3
# A parenthesized group is at least its two parens around one token.
_GROUP_TOKENS = 3
# A string literal is at least its two quotes.
_MIN_QUOTED_LENGTH = 2
_GENERATED_RE = re.compile(r"generated.{0,80}(?:do not edit|don't edit)", re.IGNORECASE)


class _Use(NamedTuple):
    identity: str
    shape: str


class _AssertionBlockKind(StrEnum):
    ASSERT = "assert"
    CHECK = "check"
    LIFECYCLE = "lifecycle"
    POSTCONDITION = "postcondition"
    PRECONDITION = "precondition"
    VALIDATION = "validation"
    VARIABLE = "variable"


@final
class NoEnvironmentConditional(Rule):
    id = "no-environment-conditional"
    code = "SARJ204"
    documentation = RuleDocumentation(
        summary=(
            "Warn when Terraform chooses behavior from deployment-identity comparisons; prefer explicit typed "
            "capabilities or values."
        ),
        rationale=(
            "Hard-coded environment branches scatter deployment policy through expressions and obscure the actual "
            "capability or value that callers intend to vary."
        ),
        remediation=(
            "Pass the selected typed value or one named capability from the root configuration. Retain an explicit "
            "validation, precondition, or check when environment identity is itself the safety invariant."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "A comparison inside validation, precondition, postcondition, check, or assert asserts which "
                "inputs are legal and is exempt. Terraform test files are rejected separately by SARJ206."
            ),
            "Comparison against the empty string is an unset-input test, not an environment branch, and is ignored.",
            (
                'An interpolated value such as "cache-${var.environment}" names a resource and is not a branch. '
                'A branch written inside a template — "${var.environment == \\"prod\\" ? ... }", a %{ if } '
                "directive, or a heredoc body — goes unscanned: strings tokenize opaquely and heredoc bodies "
                "are masked."
            ),
            (
                "Pure case/whitespace normalization with lower, upper, or trimspace is unwrapped; arbitrary function "
                "results remain opaque."
            ),
            (
                "Ambiguous identity names (`project`, `account`, `tenant`, `branch`, and `slug`) require an "
                "environment-labelled comparison literal such as `platform-prod`; comparisons to ordinary "
                "business values and map indexing by those names are intentionally ignored."
            ),
            "Only .tf and terragrunt.hcl are read; Packer, Nomad, and other HCL dialects are outside this rule.",
            "Environment-keyed map indexing and lookup are data selection rather than branching and are allowed.",
            (
                "A diagnostic is reported at the attribute's line. In a multi-line value the comparison itself "
                "may sit further down, so `# sarj-noqa: SARJ204` belongs on the attribute line."
            ),
        ),
        examples=(
            RuleExample(
                example_id="environment-gated-resource",
                title="Resource gated on the environment name",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "sandbox.tf",
                        'resource "google_storage_bucket" "cache" {\n'
                        '  count = var.environment == "sandbox" ? 1 : 0\n'
                        '  name  = "cache"\n'
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("sandbox.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-capability-input",
                title="Resource gated on a named capability input",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "sandbox.tf",
                        'resource "google_storage_bucket" "cache" {\n'
                        "  count = var.enable_object_cache ? 1 : 0\n"
                        '  name  = "cache"\n'
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("sandbox.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="hard-coded-environment-choice",
                title="Code branches on a hard-coded environment label",
                outcome=ExampleOutcome.MATCH,
                scenario="data-selection",
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'locals {\n  redis_tier = var.environment == "prod" ? "STANDARD_HA" : "BASIC"\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="environment-keyed-input-map",
                title="Externally supplied map selects a value without hard-coded branches",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="data-selection",
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        "locals {\n  redis_tier = var.redis_tiers_by_environment[var.environment]\n}\n",
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="module-input-derived-from-environment",
                title="Module input computed from the environment name",
                outcome=ExampleOutcome.MATCH,
                scenario="module-input",
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'module "iam" {\n'
                        '  source                             = "./iam"\n'
                        '  team_platform_owner_privilege      = var.environment == "dev"\n'
                        '  developer_secret_access_v2_enabled = var.environment == "dev"\n'
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=2,
                public=True,
            ),
            RuleExample(
                example_id="module-input-passed-from-tfvars",
                title="Module input passed through from tfvars",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="module-input",
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'module "iam" {\n'
                        '  source                             = "./iam"\n'
                        "  team_platform_owner_privilege      = var.team_platform_owner_privilege\n"
                        "  developer_secret_access_v2_enabled = var.developer_secret_access_v2_enabled\n"
                        "}\n",
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="project-id-with-environment-evidence",
                title="Cloud project identity names a deployment environment",
                outcome=ExampleOutcome.MATCH,
                scenario="ambiguous-identity",
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'locals {\n  tier = var.gcp_project_id == "platform-prod" ? "HA" : "BASIC"\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="business-project-value",
                title="Business project identity has no deployment evidence",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="ambiguous-identity",
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        'locals {\n  queue = var.project == "analytics" ? "events" : "default"\n}\n',
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        name = str(path)
        fixture_input = any(part.lower() in {"fixture", "fixtures", "testdata"} for part in path.parts)
        if (
            name.endswith(_TEST_SUFFIXES)
            or (path.suffix != ".tf" and path.name != "terragrunt.hcl")
            or fixture_input
            or _generated_header(source)
        ):
            return []
        diags = [
            Diagnostic(
                path=path,
                line=attr.line,
                col=attr.col,
                code=self.code,
                message=_message(owner, attr, use),
            )
            for owner, attr in _attributes((document(source),))
            if (use := _environment_use(attr.value)) is not None
        ]
        return sorted(diags, key=lambda d: (d.line, d.col))


def _attributes(
    bs: tuple[Block, ...],
    parents: tuple[Block, ...] = (),
) -> Iterator[tuple[Block, Attribute]]:
    for block in bs:
        if _is_assertion_block(block, parents):
            continue
        for attr in block.attributes:
            yield block, attr
        yield from _attributes(block.blocks, (*parents, block))


def _is_assertion_block(block: Block, parents: tuple[Block, ...]) -> bool:
    try:
        kind = _AssertionBlockKind(block.type)
        parent = _AssertionBlockKind(parents[-1].type) if parents else None
    except ValueError:
        return False
    return (
        (kind is _AssertionBlockKind.VALIDATION and parent is _AssertionBlockKind.VARIABLE)
        or (
            kind in {_AssertionBlockKind.PRECONDITION, _AssertionBlockKind.POSTCONDITION}
            and parent is _AssertionBlockKind.LIFECYCLE
        )
        or (kind is _AssertionBlockKind.ASSERT and parent is _AssertionBlockKind.CHECK)
    )


def _environment_use(value: str) -> _Use | None:
    toks = tokens(value)
    for index, tok in enumerate(toks):
        if tok in _COMPARISONS:
            use = _comparison(toks, index)
        elif tok == _CONTAINS and index + 1 < len(toks) and toks[index + 1] == "(":
            use = _call(toks, index)
        else:
            continue
        if use is not None:
            return use
    return None


def uses_environment_conditional(value: str) -> bool:
    return _environment_use(value) is not None


def _comparison(toks: tuple[str, ...], index: int) -> _Use | None:
    if index == 0 or index + 1 >= len(toks):
        return None
    left, right = _left_operand(toks, index), _right_operand(toks, index)
    if left is None or right is None:
        return None
    shape = f"{left} {toks[index]} {right}"
    if _is_environment_identity(left, literal=right) and _is_literal_string(right):
        return _Use(left, shape)
    if _is_environment_identity(right, literal=left) and _is_literal_string(left):
        return _Use(right, shape)
    return None


def _left_operand(toks: tuple[str, ...], index: int) -> str | None:
    if toks[index - 1] != ")":
        return toks[index - 1]
    open_index = _matching_open(toks, index - 1)
    if open_index is None:
        return None
    if open_index > 0 and _is_reference(toks[open_index - 1]):
        return _normalized_identity(toks[open_index - 1], toks[open_index + 1 : index - 1])
    return _single_token(toks[open_index + 1 : index - 1])


def _right_operand(toks: tuple[str, ...], index: int) -> str | None:
    if index + 2 < len(toks) and toks[index + 1] in _NORMALIZERS and toks[index + 2] == "(":
        close_index = _matching_close(toks, index + 2)
        if close_index is None:
            return None
        return _normalized_identity(toks[index + 1], toks[index + 3 : close_index])
    if toks[index + 1] != "(":
        return toks[index + 1]
    close_index = _matching_close(toks, index + 1)
    if close_index is None:
        return None
    return _single_token(toks[index + 2 : close_index])


def _call(toks: tuple[str, ...], index: int) -> _Use | None:
    args = _call_arguments(toks, index + 1)
    if len(args) != _CONTAINS_ARGS:
        return None
    needle = _single_identity(args[1])
    haystack = _single_token(args[0])
    if needle is None or (haystack is not None and haystack.startswith("var.")):
        return None
    listing = "[...]" if _is_literal_list(args[0]) else "..."
    return _Use(needle, f"contains({listing}, {needle})")


def _call_arguments(toks: tuple[str, ...], open_index: int) -> list[list[str]]:
    args: list[list[str]] = []
    current: list[str] = []
    depth = 0
    for tok in toks[open_index + 1 :]:
        if tok in _CLOSE and depth == 0:
            break
        if tok == "," and depth == 0:
            args.append(current)
            current = []
            continue
        if tok in _OPEN:
            depth += 1
        elif tok in _CLOSE:
            depth -= 1
        current.append(tok)
    if current:
        args.append(current)
    return args


def _single_identity(arg: Sequence[str]) -> str | None:
    peeled = _peel(arg)
    tok = _single_token(peeled)
    if tok is not None:
        return tok if _is_environment_identity(tok) else None
    if (
        len(peeled) >= _GROUP_TOKENS + 1
        and peeled[0] in _NORMALIZERS
        and peeled[1] == "("
        and _matching_close(peeled, 1) == len(peeled) - 1
    ):
        return _normalized_identity(peeled[0], peeled[2:-1])
    return None


def _single_token(group: Sequence[str]) -> str | None:
    peeled = _peel(group)
    return peeled[0] if len(peeled) == 1 else None


def _peel(group: Sequence[str]) -> Sequence[str]:
    while len(group) >= _GROUP_TOKENS and group[0] == "(" and _matching_close(group, 0) == len(group) - 1:
        group = group[1:-1]
    return group


def _matching_close(toks: Sequence[str], open_index: int) -> int | None:
    depth = 0
    for index in range(open_index, len(toks)):
        if toks[index] in _OPEN:
            depth += 1
        elif toks[index] in _CLOSE:
            depth -= 1
            if depth == 0:
                return index
    return None


def _matching_open(toks: Sequence[str], close_index: int) -> int | None:
    depth = 0
    for index in range(close_index, -1, -1):
        if toks[index] in _CLOSE:
            depth += 1
        elif toks[index] in _OPEN:
            depth -= 1
            if depth == 0:
                return index
    return None


def _is_reference(tok: str) -> bool:
    return tok not in _EXPRESSION_KEYWORDS and (tok[:1].isalpha() or tok[:1] == "_")


def _is_literal_list(arg: list[str]) -> bool:
    if len(arg) < _LIST_TOKENS or arg[0] != "[" or arg[-1] != "]":
        return False
    items = [tok for tok in arg[1:-1] if tok != ","]
    return bool(items) and all(_is_literal_string(tok) for tok in items)


def _is_environment_identity(tok: str, *, literal: str | None = None) -> bool:
    lowered = tok.lower()
    if lowered == _WORKSPACE:
        return True
    if not lowered.startswith(_IDENTITY_PREFIXES):
        return False
    return any(_is_environment_name(component, literal=literal) for component in lowered.split(".")[1:])


def _is_environment_name(name: str, *, literal: str | None) -> bool:
    segments = [segment for segment in re.split(r"[_-]", name.lower()) if segment]
    if not segments:
        return False
    if ENVIRONMENT_SEGMENTS & set(segments):
        return True
    if not QUALIFIED_SEGMENTS & set(segments):
        return False
    qualified = all(segment in QUALIFIED_SEGMENTS or segment in _NEUTRAL_QUALIFIERS for segment in segments)
    return qualified and literal is not None and _literal_names_environment(literal)


def _literal_names_environment(literal: str) -> bool:
    if not _is_literal_string(literal):
        return False
    segments = frozenset(_LITERAL_SEGMENT_RE.split(literal[1:-1].lower()))
    return bool(segments & _ENVIRONMENT_LITERAL_SEGMENTS)


def _is_literal_string(tok: str) -> bool:
    if len(tok) < _MIN_QUOTED_LENGTH or not tok.startswith('"') or not tok.endswith('"'):
        return False
    if "${" in tok:
        return False
    return bool(tok[1:-1].strip())


def _message(owner: Block, attr: Attribute, use: _Use) -> str:
    # The synthetic root block has no type: its attributes sit at the file's top
    # level, which is where Terragrunt keeps `inputs`.
    labelled = " ".join([owner.type, *(f'"{label}"' for label in owner.labels)])
    where = labelled if owner.type else "the file root"
    return (
        f"`{attr.name}` in {where} selects behavior from deployment identity ({use.shape}); pass the selected typed "
        "value or one named capability from the root configuration."
    )


def _normalized_identity(function: str, argument: Sequence[str]) -> str | None:
    if function not in _NORMALIZERS:
        return None
    return _single_identity(argument)


def _generated_header(source: str) -> bool:
    header = "\n".join(line for line in source.splitlines()[:20] if line.lstrip().startswith(("#", "//", "/*", "*")))
    return _GENERATED_RE.search(header) is not None
