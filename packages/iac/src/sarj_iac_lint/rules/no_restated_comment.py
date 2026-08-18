from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

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
_DECLARATION_RE = re.compile(
    r"^(?:resource|data|module|variable|output|provider|locals|terraform|dynamic|moved)\b|^[A-Za-z_][\w-]*\s*=",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DIRECTIVE_RE = re.compile(r"^(?:sarj-noqa|tflint|checkov|terraform|todo|fixme|hack|noqa)\b", re.IGNORECASE)
_PROTECTED_RE = re.compile(
    r"https?://|\b(?:because|otherwise|must|never|requires?|workaround|upstream|security|race|invariant)\b|"
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
_MAX_COMMENT_WORDS = 8
_MIN_CONTENT_WORDS = 2
_MIN_STEM_LENGTH = 3


@final
class NoRestatedComment(Rule):
    id = "no-restated-comment"
    code = "SARJ207"
    documentation = RuleDocumentation(
        summary="HCL comments must not merely restate the adjacent declaration.",
        rationale="Narrating a resource, block, or attribute duplicates executable configuration and can drift from it.",
        remediation="Delete the comment or replace it with an external constraint, provider quirk, or operational reason.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only isolated short comments immediately above a declaration at the same indentation are compared.",
            "Heredocs, directives, generated files, references, units, modality, and causal explanations are preserved.",
        ),
        examples=(
            RuleExample(
                example_id="attribute-restatement",
                title="Comment repeats an attribute name and value",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.iac("main.tf", "# Set instance type\ninstance_type = var.instance_type\n"),),
                focus_path=PurePosixPath("main.tf"),
                expected_count=1,
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
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if _GENERATED_RE.search(source[:2048]):
            return []
        lines = source.splitlines()
        in_heredoc = heredoc_body_mask(lines)
        findings: list[Diagnostic] = []
        for index, raw in enumerate(lines[:-1]):
            if in_heredoc[index] or in_heredoc[index + 1]:
                continue
            match = _COMMENT_RE.match(raw)
            if match is None or (index > 0 and _COMMENT_RE.match(lines[index - 1])):
                continue
            if index + 2 < len(lines) and _COMMENT_RE.match(lines[index + 1]):
                continue
            body = match["body"].strip()
            declaration = lines[index + 1]
            if not _eligible(body, declaration, len(match["indent"])):
                continue
            findings.append(Diagnostic(path, index + 1, len(match["indent"]) + 1, self.code, self.description))
        return findings


def _eligible(body: str, declaration: str, indent: int) -> bool:
    if not body or body.endswith(("?", ":")) or _DIRECTIVE_RE.match(body) or _PROTECTED_RE.search(body):
        return False
    if len(body.split()) > _MAX_COMMENT_WORDS or len(declaration) - len(declaration.lstrip()) != indent:
        return False
    code = declaration.strip()
    if not _DECLARATION_RE.match(code):
        return False
    content = [word for match in _WORD_RE.finditer(body) if (word := match.group(0).lower()) not in _STOPWORDS]
    if len(content) < _MIN_CONTENT_WORDS:
        return False
    present = {part.lower() for match in _WORD_RE.finditer(code) for part in re.split(r"_+", match.group(0)) if part}
    return all(word in present or _stem(word) in {_stem(item) for item in present} for word in content)


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM_LENGTH:
            return word[: -len(suffix)]
    return word
