"""SARJ204: Terraform must take named inputs instead of branching on the environment name."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_iac_lint._hcl import blocks, tokens
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
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_iac_lint._hcl import Attribute, Block

# Segments that only ever name a deploy, so a match anywhere in the name is enough.
ENVIRONMENT_SEGMENTS = frozenset({"environment", "env", "stage", "workspace", "deployment"})

# Segments that are also ordinary product words. These count only when every other
# segment is a neutral qualifier, so `var.project` and `var.gcp_project_id` match
# while `var.langfuse_ui_project_id` (a third-party resource id) does not.
QUALIFIED_SEGMENTS = frozenset({"project", "slug", "branch", "account", "tenant"})

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

# Whole subtrees that assert which inputs are legal. Comparing the environment to a
# literal is the assertion there, and there is no named input that could replace it.
_ASSERTION_BLOCKS = frozenset({"validation", "precondition", "postcondition", "check", "assert"})

_WORKSPACE = "terraform.workspace"
_IDENTITY_PREFIXES = ("var.", "local.")

_CONTAINS = "contains"
_LOOKUP = "lookup"
_COMPARISONS = frozenset({"==", "!="})
_MIN_CALL_ARGS = 2

_OPEN = frozenset({"(", "[", "{"})
_CLOSE = frozenset({")", "]", "}"})

_HCL_SUFFIXES = (".tf", ".hcl")
# Checked first: `.tftest.hcl` also ends in `.hcl`, and asserting on the environment
# is the entire purpose of a Terraform test file.
_TEST_SUFFIXES = (".tftest.hcl", ".tftest.json")

_LIST_TOKENS = 3
# A string literal is at least its two quotes.
_MIN_QUOTED_LENGTH = 2


class _Use(NamedTuple):
    """One environment-name branch found in an attribute value."""

    identity: str
    shape: str


@final
class NoEnvironmentConditional(Rule):
    """Terraform branching on the environment name rather than on a named input."""

    id = "no-environment-conditional"
    code = "SARJ204"
    documentation = RuleDocumentation(
        summary=(
            "Terraform must not branch on the environment or project name; declare a variable and pass the value "
            "in from tfvars."
        ),
        rationale=(
            "Terraform that reads which environment it is in keeps the decision in code rather than in "
            "configuration, so a caller cannot see what varies, and every new environment is an edit to every "
            "expression that names the old ones — including at a module call site, where the value belongs in "
            "that environment's tfvars instead."
        ),
        remediation=(
            "Declare the behaviour as its own variable and set its value per environment in tfvars, so the "
            "environment selects configuration rather than the code selecting behaviour."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "A comparison inside validation, precondition, postcondition, check, or assert asserts which "
                "inputs are legal and is exempt, as is a .tftest.hcl file."
            ),
            "Comparison against the empty string is an unset-input test, not an environment branch, and is ignored.",
            'An interpolated value such as "cache-${var.environment}" names a resource and is not a branch.',
            "Only .tf and .hcl are read: blocks() drops file-level attributes, so .tfvars is out of scope.",
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
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag every environment-name branch outside an assertion block."""
        name = str(path)
        if name.endswith(_TEST_SUFFIXES) or not name.endswith(_HCL_SUFFIXES):
            return []
        diags = [
            Diagnostic(
                path=path,
                line=attr.line,
                col=attr.col,
                code=self.code,
                message=_message(owner, attr, use),
            )
            for owner, attr in _attributes(blocks(source))
            if (use := _environment_use(attr.value)) is not None
        ]
        return sorted(diags, key=lambda d: (d.line, d.col))


def _attributes(bs: tuple[Block, ...]) -> Iterator[tuple[Block, Attribute]]:
    """Walk every attribute at every depth, pruning whole assertion subtrees."""
    for block in bs:
        if block.type in _ASSERTION_BLOCKS:
            continue
        for attr in block.attributes:
            yield block, attr
        yield from _attributes(block.blocks)


def _environment_use(value: str) -> _Use | None:
    """Find the first environment-name branch in `value`, or None when there is none."""
    toks = tokens(value)
    for index, tok in enumerate(toks):
        if tok in _COMPARISONS:
            use = _comparison(toks, index)
        elif tok in {_CONTAINS, _LOOKUP} and index + 1 < len(toks) and toks[index + 1] == "(":
            use = _call(toks, index)
        else:
            continue
        if use is not None:
            return use
    return None


def _comparison(toks: tuple[str, ...], index: int) -> _Use | None:
    """Read `<identity> == "literal"` in either operand order."""
    if index == 0 or index + 1 >= len(toks):
        return None
    left, right = toks[index - 1], toks[index + 1]
    shape = f"{left} {toks[index]} {right}"
    if _is_environment_identity(left) and _is_literal_string(right):
        return _Use(left, shape)
    if _is_environment_identity(right) and _is_literal_string(left):
        return _Use(right, shape)
    return None


def _call(toks: tuple[str, ...], index: int) -> _Use | None:
    """Read `contains([literals], identity)` and `lookup(map, identity, default)`."""
    args = _call_arguments(toks, index + 1)
    if len(args) < _MIN_CALL_ARGS:
        return None
    if toks[index] == _CONTAINS:
        haystack, needle = args[0], args[1]
        if not _is_literal_list(haystack) or not _is_single_identity(needle):
            return None
        return _Use(needle[0], f"contains([...], {needle[0]})")
    key = args[1]
    if not _is_single_identity(key):
        return None
    return _Use(key[0], f"lookup(..., {key[0]}, ...)")


def _call_arguments(toks: tuple[str, ...], open_index: int) -> list[list[str]]:
    """Split a call's tokens on top-level commas so argument position is readable."""
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


def _is_single_identity(arg: list[str]) -> bool:
    """Report whether an argument is exactly one environment-identity token."""
    return len(arg) == 1 and _is_environment_identity(arg[0])


def _is_literal_list(arg: list[str]) -> bool:
    """Report whether an argument is a non-empty list of string literals."""
    if len(arg) < _LIST_TOKENS or arg[0] != "[" or arg[-1] != "]":
        return False
    items = [tok for tok in arg[1:-1] if tok != ","]
    return bool(items) and all(_is_literal_string(tok) for tok in items)


def _is_environment_identity(tok: str) -> bool:
    """Report whether one token reads the environment the code is deployed into."""
    if tok == _WORKSPACE:
        return True
    if not tok.startswith(_IDENTITY_PREFIXES):
        return False
    return _is_environment_name(tok.rsplit(".", 1)[-1])


def _is_environment_name(name: str) -> bool:
    """Match environment segments whole, so a product word never reads as identity."""
    segments = [segment for segment in name.split("_") if segment]
    if not segments:
        return False
    if ENVIRONMENT_SEGMENTS & set(segments):
        return True
    if not QUALIFIED_SEGMENTS & set(segments):
        return False
    return all(segment in QUALIFIED_SEGMENTS or segment in _NEUTRAL_QUALIFIERS for segment in segments)


def _is_literal_string(tok: str) -> bool:
    """Report whether a token is a non-empty, non-interpolated string literal."""
    if len(tok) < _MIN_QUOTED_LENGTH or not tok.startswith('"') or not tok.endswith('"'):
        return False
    if "${" in tok:
        return False
    return bool(tok[1:-1].strip())


def _message(owner: Block, attr: Attribute, use: _Use) -> str:
    """Name the branch, where it sits, and the input that should replace it."""
    where = " ".join([owner.type, *(f'"{label}"' for label in owner.labels)])
    return (
        f"`{attr.name}` in {where} branches on the environment name ({use.shape}) — "
        "adding an environment means editing this expression, and the decision is code rather than "
        f"configuration. Declare `{attr.name}` as its own variable and pass the value in per "
        "environment from tfvars."
    )
