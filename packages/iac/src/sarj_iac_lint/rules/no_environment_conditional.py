from __future__ import annotations

from pathlib import PurePosixPath
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

# Words that read like identifiers but head expressions: `if (x)` groups, `foo(x)` calls.
_EXPRESSION_KEYWORDS = frozenset({"if", "for", "in"})

_HCL_SUFFIXES = (".tf", ".hcl")
# Checked first to avoid duplicate diagnostics: SARJ206 categorically owns these files.
_TEST_SUFFIXES = (".tftest.hcl", ".tftest.json")

_LIST_TOKENS = 3
# A parenthesized group is at least its two parens around one token.
_GROUP_TOKENS = 3
# A string literal is at least its two quotes.
_MIN_QUOTED_LENGTH = 2


class _Use(NamedTuple):
    identity: str
    shape: str


@final
class NoEnvironmentConditional(Rule):
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
            "Declare a typed variable carrying the selected value, set per environment in tfvars "
            "(`tier = var.redis_tier`); use one `enable_<thing>` bool consumed by count/for_each only when the "
            "branch gates existence, never computed from the environment name."
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
                "A function result such as upper(var.environment) is not treated as the environment identity, "
                "so a comparison against it is exempt."
            ),
            "Only .tf and .hcl are read: the suffix filter keeps .tfvars out of scope.",
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
            for owner, attr in _attributes((document(source),))
            if (use := _environment_use(attr.value)) is not None
        ]
        return sorted(diags, key=lambda d: (d.line, d.col))


def _attributes(bs: tuple[Block, ...]) -> Iterator[tuple[Block, Attribute]]:
    for block in bs:
        if block.type in _ASSERTION_BLOCKS:
            continue
        for attr in block.attributes:
            yield block, attr
        yield from _attributes(block.blocks)


def _environment_use(value: str) -> _Use | None:
    toks = tokens(value)
    for index, tok in enumerate(toks):
        if tok in _COMPARISONS:
            use = _comparison(toks, index)
        elif tok in {_CONTAINS, _LOOKUP} and index + 1 < len(toks) and toks[index + 1] == "(":
            use = _call(toks, index)
        elif tok == "[":
            use = _index(toks, index)
        else:
            continue
        if use is not None:
            return use
    return None


def _comparison(toks: tuple[str, ...], index: int) -> _Use | None:
    if index == 0 or index + 1 >= len(toks):
        return None
    left, right = _left_operand(toks, index), _right_operand(toks, index)
    if left is None or right is None:
        return None
    shape = f"{left} {toks[index]} {right}"
    if _is_environment_identity(left) and _is_literal_string(right):
        return _Use(left, shape)
    if _is_environment_identity(right) and _is_literal_string(left):
        return _Use(right, shape)
    return None


def _left_operand(toks: tuple[str, ...], index: int) -> str | None:
    if toks[index - 1] != ")":
        return toks[index - 1]
    open_index = _matching_open(toks, index - 1)
    if open_index is None:
        return None
    # A group closing a call — `upper(var.environment)` — is that function's
    # result, not the bare identity, so it never reads as the environment name.
    if open_index > 0 and _is_reference(toks[open_index - 1]):
        return None
    return _single_token(toks[open_index + 1 : index - 1])


def _right_operand(toks: tuple[str, ...], index: int) -> str | None:
    if toks[index + 1] != "(":
        return toks[index + 1]
    close_index = _matching_close(toks, index + 1)
    if close_index is None:
        return None
    return _single_token(toks[index + 2 : close_index])


def _call(toks: tuple[str, ...], index: int) -> _Use | None:
    args = _call_arguments(toks, index + 1)
    if len(args) < _MIN_CALL_ARGS:
        return None
    if toks[index] == _CONTAINS:
        needle = _single_identity(args[1])
        if needle is None:
            return None
        # Membership via an intermediate list is the same branch, so the haystack
        # only shapes the message; the needle is the anchor, as with lookup's map.
        listing = "[...]" if _is_literal_list(args[0]) else "..."
        return _Use(needle, f"contains({listing}, {needle})")
    key = _single_identity(args[1])
    if key is None:
        return None
    return _Use(key, f"lookup(..., {key}, ...)")


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
    tok = _single_token(arg)
    return tok if tok is not None and _is_environment_identity(tok) else None


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


def _index(toks: tuple[str, ...], index: int) -> _Use | None:
    if index == 0 or index + 2 >= len(toks):
        return None
    # An index needs a subject; a `[` after an operator, comma, or another
    # opener starts a list literal, so `contains([var.environment], "prod")`
    # holds the identity rather than branching on it.
    subject = toks[index - 1]
    if subject not in {")", "]"} and not _is_reference(subject):
        return None
    key = toks[index + 1]
    if toks[index + 2] != "]" or not _is_environment_identity(key):
        return None
    return _Use(key, f"...[{key}]")


def _is_reference(tok: str) -> bool:
    return tok not in _EXPRESSION_KEYWORDS and (tok[:1].isalpha() or tok[:1] == "_")


def _is_literal_list(arg: list[str]) -> bool:
    if len(arg) < _LIST_TOKENS or arg[0] != "[" or arg[-1] != "]":
        return False
    items = [tok for tok in arg[1:-1] if tok != ","]
    return bool(items) and all(_is_literal_string(tok) for tok in items)


def _is_environment_identity(tok: str) -> bool:
    if tok == _WORKSPACE:
        return True
    if not tok.startswith(_IDENTITY_PREFIXES):
        return False
    return _is_environment_name(tok.rsplit(".", 1)[-1])


def _is_environment_name(name: str) -> bool:
    segments = [segment for segment in name.split("_") if segment]
    if not segments:
        return False
    if ENVIRONMENT_SEGMENTS & set(segments):
        return True
    if not QUALIFIED_SEGMENTS & set(segments):
        return False
    return all(segment in QUALIFIED_SEGMENTS or segment in _NEUTRAL_QUALIFIERS for segment in segments)


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
        f"`{attr.name}` in {where} branches on the environment name ({use.shape}) — "
        "adding an environment means editing this expression, and the decision is code rather than "
        "configuration. Replace it with a typed variable set per environment in tfvars — the value "
        "itself, or one `enable_<thing>` bool when the branch gates whether the resource exists."
    )
