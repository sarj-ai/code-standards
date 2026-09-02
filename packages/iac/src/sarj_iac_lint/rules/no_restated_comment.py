from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_iac_lint._hcl import heredoc_body_mask
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


_COMMENT_RE = re.compile(r"^(?P<indent>\s*)(?:#|//)\s?(?P<body>.*)$")
_BLOCK_START_RE = re.compile(r"^(?P<indent>\s*)/\*\s?(?P<body>.*)$")
_ATTRIBUTE_RE = re.compile(r"^(?P<name>[A-Za-z_][\w-]*)\s*=(?!=)")
_BLOCK_RE = re.compile(r'^(?P<kind>[A-Za-z_][\w-]*)(?P<labels>(?:\s+(?:"(?:\\.|[^"\\])*"|[A-Za-z_][\w.-]*)){0,3})\s*\{')
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DIRECTIVE_RE = re.compile(
    r"^(?:sarj-noqa|tflint|checkov|tfsec|trivy|terrascan|kics|semgrep|snyk|infracost|renovate|"
    r"dependabot|noinspection|pragma|terraform|todo|fixme|hack|noqa)\b",
    re.IGNORECASE,
)
_PROTECTED_RE = re.compile(
    r"https?://|\b(?:because|otherwise|must|never|requires?|workaround|upstream|race|invariant)\b|"
    r"\b[A-Z][A-Z0-9]{1,9}-\d+\b|\d+\s*(?:ms|seconds?|minutes?|hours?|days?|%|MB|GB)\b",
    re.IGNORECASE,
)
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "this",
        "that",
        "to",
        "of",
        "for",
        "in",
        "on",
        "by",
        "with",
        "from",
        "and",
        "or",
        "is",
        "are",
        "be",
        "set",
        "create",
        "define",
        "configure",
    ]
)
_GENERATED_RE = re.compile(r"generated.*do not edit|do not edit.*generated", re.IGNORECASE)
_TRAILING_SUPPRESSION_RE = re.compile(
    r"\s+(?:#|//)\s*sarj-noqa:\s*SARJ\d+(?:\s*,\s*SARJ\d+)*(?:\s*(?:—|--)\s*.+)?$",
    re.IGNORECASE,
)
_MAX_COMMENT_WORDS = 8
_MIN_CONTENT_WORDS = 2
_MIN_STEM_LENGTH = 3
_RESOURCE_LABEL_COUNT = 2


class _CommentCandidate(NamedTuple):
    body: str
    declaration: str
    subject: str
    line: int
    column: int
    indent: int
    declaration_index: int


@final
class NoRestatedComment(Rule):
    id = "no-restated-comment"
    code = "SARJ207"
    documentation = RuleDocumentation(
        summary=(
            "Flag a short comment attached to an HCL declaration when it only repeats that declaration's kind, "
            "label, or attribute name."
        ),
        rationale=(
            "A declaration-label comment adds no durable information and can drift; comments that explain constraints, "
            "grouping, or operational rationale remain useful."
        ),
        remediation=(
            "Delete the restatement or replace it with the constraint the configuration cannot express. Improve an "
            "author-controlled label when the declaration itself is unclear."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only short comments immediately above native HCL declarations at the same indentation are compared.",
            (
                "Comment groups, sibling headings, heredocs, directives, generated files, fixtures, references, "
                "units, modality, and causal explanations are preserved."
            ),
        ),
        examples=(
            RuleExample(
                example_id="attribute-restatement",
                title="Comment merely narrates an assignment",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.iac("main.tf", "# Set instance type\ninstance_type = var.instance_type\n"),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="single-declaration-label",
                title="Comment repeats one declaration label",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        "# Service account\nservice_account_email = module.iam.api_email\n",
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                scenario="sibling-group",
                public=True,
            ),
            RuleExample(
                example_id="group-heading",
                title="Comment labels a group of sibling attributes",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        "# Service accounts\n"
                        "api_service_account_email = module.iam.api_email\n"
                        "worker_service_account_email = module.iam.worker_email\n",
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                scenario="sibling-group",
                public=True,
            ),
            RuleExample(
                example_id="provider-constraint",
                title="Comment records a provider constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        "# Keep this type because the provider rejects ARM nodes.\ninstance_type = var.instance_type\n",
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="generated-block-header",
                title="Generated HCL is owned by its generator",
                outcome=ExampleOutcome.NO_MATCH,
                scenario="generated-file",
                files=(
                    ExampleFile.iac(
                        "generated.tf",
                        "/* Code generated by schema compiler.\n * DO NOT EDIT.\n */\n"
                        "# Set instance type\ninstance_type = var.instance_type\n",
                    ),
                ),
                focus_path=PurePosixPath("generated.tf"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="maintained-block-comment-restatement",
                title="Maintained block comment repeats its attribute",
                outcome=ExampleOutcome.MATCH,
                scenario="generated-file",
                files=(
                    ExampleFile.iac(
                        "main.tf",
                        "/* Set instance type */\ninstance_type = var.instance_type\n",
                    ),
                ),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not _path_is_hcl(path) or _fixture_path(path) or _generated_header(source):
            return []
        lines = source.splitlines()
        in_heredoc = heredoc_body_mask(lines)
        findings: list[Diagnostic] = []
        for body, declaration, subject, line, column, indent, declaration_index in _comment_candidates(
            lines, in_heredoc
        ):
            normalized_body = _TRAILING_SUPPRESSION_RE.sub("", body).strip()
            if not _eligible(normalized_body, declaration, indent) or _labels_sibling_group(
                normalized_body, lines, declaration_index, indent
            ):
                continue
            findings.append(
                Diagnostic(
                    path,
                    line,
                    column,
                    self.code,
                    f"Comment only repeats the following `{subject}` declaration; delete it or state its constraint.",
                )
            )
        return findings


def _comment_candidates(lines: list[str], in_heredoc: tuple[bool, ...]) -> list[_CommentCandidate]:
    candidates: list[_CommentCandidate] = []
    index = 0
    while index < len(lines) - 1:
        if in_heredoc[index]:
            index += 1
            continue
        raw = lines[index]
        if (line_match := _COMMENT_RE.match(raw)) is not None:
            start = index
            indent = len(line_match["indent"])
            bodies = [line_match["body"]]
            while index + 1 < len(lines) and (following := _COMMENT_RE.match(lines[index + 1])) is not None:
                if len(following["indent"]) != indent:
                    break
                index += 1
                bodies.append(following["body"])
            declaration_index = index + 1
            if declaration_index < len(lines) and not in_heredoc[declaration_index]:
                declaration = lines[declaration_index]
                if (subject := _declaration_subject(declaration.strip())) is not None:
                    candidates.append(
                        _CommentCandidate(
                            " ".join(bodies),
                            declaration,
                            subject,
                            start + 1,
                            indent + 1,
                            indent,
                            declaration_index,
                        )
                    )
            index += 1
            continue
        block_match = _BLOCK_START_RE.match(raw)
        if block_match is None:
            index += 1
            continue
        indent = len(block_match["indent"])
        body_lines = [block_match["body"]]
        end = index
        while end < len(lines) and "*/" not in lines[end]:
            end += 1
            if end >= len(lines) or in_heredoc[end]:
                break
            body_lines.append(lines[end].strip().removeprefix("*").strip())
        if end + 1 < len(lines) and "*/" in lines[end] and not in_heredoc[end + 1]:
            body_lines[-1] = body_lines[-1].split("*/", 1)[0].strip()
            body = " ".join(part for part in body_lines if part)
            declaration = lines[end + 1]
            if (subject := _declaration_subject(declaration.strip())) is not None:
                candidates.append(_CommentCandidate(body, declaration, subject, index + 1, indent + 1, indent, end + 1))
        index = max(index + 1, end + 1)
    return candidates


def _eligible(body: str, declaration: str, indent: int) -> bool:
    if not body or body.endswith("?") or _DIRECTIVE_RE.match(body) or _PROTECTED_RE.search(body):
        return False
    if len(body.split()) > _MAX_COMMENT_WORDS or len(declaration) - len(declaration.lstrip()) != indent:
        return False
    code = declaration.strip()
    if _declaration_subject(body) is not None:
        return False
    content = [word for match in _WORD_RE.finditer(body) if (word := match.group(0).lower()) not in _STOPWORDS]
    if len(content) < _MIN_CONTENT_WORDS:
        return False
    present = _declaration_words(code)
    return bool(present) and all(_word_matches(word, present) for word in content)


def _declaration_subject(code: str) -> str | None:
    if (attribute := _ATTRIBUTE_RE.match(code)) is not None:
        return attribute["name"]
    if (block := _BLOCK_RE.match(code)) is not None:
        labels = [match.group(0).strip('"') for match in _WORD_RE.finditer(block["labels"])]
        if block["kind"] in {"resource", "data"} and len(labels) >= _RESOURCE_LABEL_COUNT:
            return f'{block["kind"]} {labels[0]}.{labels[1]}'
        return f'{block["kind"]} {labels[-1]}' if labels else block["kind"]
    return None


def _declaration_words(code: str) -> set[str]:
    if (attribute := _ATTRIBUTE_RE.match(code)) is not None:
        text = attribute["name"]
    elif (block := _BLOCK_RE.match(code)) is not None:
        text = f"{block['kind']} {block['labels']}"
    else:
        return set()
    return {part.lower() for match in _WORD_RE.finditer(text) for part in re.split(r"_+", match.group(0)) if part}


def _word_matches(word: str, present: set[str]) -> bool:
    return bool(_word_forms(word) & {form for item in present for form in _word_forms(item)})


def _word_forms(word: str) -> set[str]:
    stem = _stem(word)
    return {word, stem, f"{stem}e"}


def _labels_sibling_group(body: str, lines: list[str], declaration_index: int, indent: int) -> bool:
    content = [word for match in _WORD_RE.finditer(body) if (word := match.group(0).lower()) not in _STOPWORDS]
    if not content:
        return False
    cursor = declaration_index + 1
    while cursor < len(lines) and not lines[cursor].strip():
        cursor += 1
    if cursor >= len(lines) or len(lines[cursor]) - len(lines[cursor].lstrip()) != indent:
        return False
    sibling_words = _declaration_words(lines[cursor].strip())
    return bool(sibling_words) and all(_word_matches(word, sibling_words) for word in content)


def _path_is_hcl(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith((".tf", ".tfvars")) or name == "terragrunt.hcl"


def _fixture_path(path: Path) -> bool:
    return any(part.lower() in {"fixture", "fixtures", "testdata", "generated"} for part in path.parts)


def _generated_header(source: str) -> bool:
    lines = source.splitlines()[:20]
    fragments: list[str] = []
    in_block = False
    for line in lines:
        stripped = line.lstrip()
        if in_block:
            fragments.append(stripped.removeprefix("*").strip())
            if "*/" in stripped:
                in_block = False
            continue
        if not stripped:
            continue
        if stripped.startswith(("#", "//")):
            fragments.append(stripped.lstrip("#/ "))
            continue
        if stripped.startswith("/*"):
            fragments.append(stripped.removeprefix("/*").strip())
            in_block = "*/" not in stripped
            continue
        break
    return _GENERATED_RE.search(" ".join(fragments)) is not None


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM_LENGTH:
            return word[: -len(suffix)]
    return word
