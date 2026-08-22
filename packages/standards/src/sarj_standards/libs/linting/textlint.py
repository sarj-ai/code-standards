from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
import re
import shlex
import sys
import tomllib
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Final,
    NamedTuple,
)

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sarj_standards.libs.adoption.manifest import as_table, list_field, table_field
from sarj_standards.libs.rules.contracts import (
    AutofixPolicy,
    ExampleFile,
    ExpectedOutcome,
    Language,
    MessageId,
    RuleCategory,
    RuleEngine,
    RuleExample,
    RuleId,
    RuleSpec,
)


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class _ShellOperands(NamedTuple):
    operands: list[str]
    explicit_pattern: bool


class _TextPolicy(NamedTuple):
    durable: tuple[str, ...]
    excluded: tuple[str, ...]


class _StandaloneComment(NamedTuple):
    indent: int
    body: str


class _MarkdownHtmlComment(NamedTuple):
    line: int
    body: str


class _ConfigScalarEntry(NamedTuple):
    key: str
    value: str


class _AttachedComment(NamedTuple):
    line: int
    owner_indent: int
    weak: bool


class _ClaudePermissions(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    allow: list[str] = Field(default_factory=list)


class _ClaudeSettings(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    permissions: _ClaudePermissions = Field(default_factory=_ClaudePermissions)


_TEXT_SUFFIXES: Final = frozenset(
    {
        ".bash",
        ".cfg",
        ".conf",
        ".env",
        ".ini",
        ".jsonc",
        ".md",
        ".mdx",
        ".properties",
        ".sh",
        ".tftpl",
        ".toml",
        ".yaml",
        ".yml",
        ".zsh",
    }
)
_TEXT_NAMES: Final = frozenset({"dockerfile", "gnumakefile", "justfile", "makefile"})
_MIN_EPHEMERAL_HEADINGS: Final = 2
_MIN_NUMBERED_FINDINGS: Final = 2
_LARGE_ARTIFACT_MIN_LINES: Final = 200
_LARGE_ARTIFACT_MIN_WORDS: Final = 1_500
_LARGE_ARTIFACT_MIN_SIGNALS: Final = 2
_WALL_MIN_ATTACHED: Final = 4
_WALL_MIN_WEAK: Final = 3
_WALL_MIN_WEAK_RATIO: Final = 0.75
_WALL_MAX_WORDS: Final = 18
_WALL_MIN_MATCHED_RATIO: Final = 0.5
_WALL_MAX_NOVEL_WORDS: Final = 2
_WALL_GROUP_MAX_LINES: Final = 24
_COMMENTED_CONFIG_MAX_WORDS: Final = 8
_COMMENTED_CONFIG_RUN_MIN: Final = 1
_COMMENTED_CONFIG_RUN_RATIO: Final = 0.5
_DURABLE_MARKDOWN: Final = (
    "README.md",
    "**/README.md",
    "CHANGELOG.md",
    "**/CHANGELOG.md",
    "CONTRIBUTING.md",
    "**/CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "AGENTS.md",
    "**/AGENTS.md",
    "CLAUDE.md",
    "**/CLAUDE.md",
    "docs/**",
    "**/docs/**",
    ".github/**",
    "adr/**",
    "**/adr/**",
    "architecture/**",
    "**/architecture/**",
)
_ARTIFACT_NAME_RE = re.compile(
    r"(?:^|[-_])(?:build|fix|implementation|qa)[-_]?(?:brief|report|"
    r"log|notes?|plan|summary|results?)|^report[-_]|(?:improvement|end[-_]to[-_]end)[-_]plan|"
    r"morning[-_]summary|diagnosis[-_]handoff|project[-_]status|validation[-_]report|"
    r"meeting[-_]brief|merge[-_]brief|qa[-_]fixlist|debug[-_]todo|kroki[-_]notes",
    re.IGNORECASE,
)
_STRONG_ARTIFACT_NAME_RE = re.compile(
    r"(?:build|fix|merge|meeting)[-_]?brief|diagnosis[-_]handoff|morning[-_]summary|"
    r"debug[-_]todo|project[-_]status|qa[-_]fixlist|end[-_]to[-_]end[-_]plan|"
    r"clone[-_]notes|authenticity[-_]fixes[-_]prompt|fable[-_]loop[-_]findings|"
    r"(?:^|[-_])bugs?[-_]found(?:[-_][a-z0-9]+)*$",
    re.IGNORECASE,
)
_EPHEMERAL_HEADING_RE = re.compile(
    r"^#{1,6}\s+(?:fixes?\s*[+&/]\s*learnings?|verification pass(?:es)?|what (?:i|we) "
    r"changed|implementation status|(?:e2e |merged-site )?qa (?:pass|log|results?)|"
    r"work completed|session summary|remaining work|changes made|bugs found \+ fixed|"
    r"what'?s left|build log|issues? fixed|errors? fixed|pitfalls?\s*/\s*learnings?|"
    r"what changed this session|(?:qa )?round\s+\d+)(?:\s|$)",
    re.IGNORECASE,
)
_STRONG_DIARY_HEADING_RE = re.compile(
    r"^#{1,6}\s+(?:fixes?\s*[+&/]\s*learnings?|build log|what changed this session|"
    r"issues? fixed|errors? fixed|pitfalls?\s*/\s*learnings?)(?:\s|$)",
    re.IGNORECASE,
)
_LIFECYCLE_HEADING_RE = re.compile(
    r"^#{1,6}\s+(?:findings|what (?:was )?(?:actually )?changed|"
    r"recommended (?:order|actions?)|post[- ]change verification|further findings|"
    r"not completed|implementation status|session summary|changes made|"
    r"bugs? found|issues? fixed|verification results?|action items?|deep pass)(?:\s|$)",
    re.IGNORECASE,
)
_DATED_ARTIFACT_RE = re.compile(
    r"\b(?:audit|report|review|assessment|findings?)\b.*\b20\d{2}(?:[-_/]\d{1,2}){1,2}\b|"
    r"\b20\d{2}(?:[-_/]\d{1,2}){1,2}\b.*\b(?:audit|report|review|assessment|findings?)\b",
    re.IGNORECASE,
)
_NUMBERED_FINDING_RE = re.compile(r"^\s*\*{0,2}\d+[a-z]?\.(?:\s|\*)", re.IGNORECASE)
_RESULTS_TABLE_RE = re.compile(r"^\s*\|\s*(?:check|change|finding|object|result)\s*\|", re.IGNORECASE)
_ARTIFACT_SELF_DESCRIPTION_RE = re.compile(
    r"\b(?:investigation|audit|execution) log\b|\bchange diary\b|\bpoint-in-time (?:audit|report)\b",
    re.IGNORECASE,
)
_AI_GENERATION_RE = re.compile(
    r"generated with \[(?:claude|chatgpt|codex)|generated (?:with|by) (?:claude|chatgpt|codex)|"
    r"co-authored-by:\s*(?:claude|chatgpt|codex)",
    re.IGNORECASE,
)
_DIRECTIVE_RE = re.compile(
    r"^(?:!|shellcheck|yamllint|markdownlint|prettier|eslint|renovate|dependabot|"
    r"pragma|noqa|sarj-noqa|type:|pyright|mypy|syntax=|hadolint|nosec|note:|"
    r"examples?:|flags:|format:|tool:|inputs?:|outputs?:|defaults?:|usage:|spdx)",
    re.IGNORECASE,
)
_SARJ_SUPPRESSION_RE = re.compile(r"^sarj-noqa:\s*(?P<codes>SARJ\d+(?:\s*,\s*SARJ\d+)*)\s*$", re.IGNORECASE)
_MARKDOWN_HIDDEN_DIRECTIVE_RE = re.compile(
    r"^(?:sarj-noqa|markdownlint|prettier|cspell|spellcheck|vale|doctoc|toc\b|more\b|"
    r"begin\b|end\b|generated\b|copyright|spdx|template\b)",
    re.IGNORECASE,
)
_MARKDOWN_ATX_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_MARKDOWN_SUPPRESSION_RE = re.compile(
    r"^\s*<!--\s*sarj-noqa:\s*(?P<codes>SARJ\d+(?:\s*,\s*SARJ\d+)*)\s*-->\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_PROTECTED_RE = re.compile(
    r"https?://|\b(?:RFC|PEP|CVE)[- ]?\d+|\b[A-Z][A-Z0-9]{1,9}-\d+\b|"
    r"\b(?:because|otherwise|so that|to avoid|workaround|upstream|requires?|must |"
    r"intentionally|security|invariant|idempotent|race|deprecated|compatibility)\b|"
    r"\d+(?:\.\d+)?\s?(?:ms|sec|minutes?|hours?|days?|KB|MB|MiB|GiB|%|rps|qps)\b",
    re.IGNORECASE,
)
_CONFIG_SHAPE_RE = re.compile(
    r"""^(?:-\s+)?(?:uses|run|name|if|env|with|image|services|steps|jobs|stages|"""
    r"""[A-Za-z_][\w.-]*|["'][^"']+["'])\s*[:=]\s*\S""",
    re.IGNORECASE,
)
_DOCKER_SHAPE_RE = re.compile(
    r"^(?:ADD|ARG|CMD|COPY|ENTRYPOINT|ENV|EXPOSE|FROM|HEALTHCHECK|LABEL|RUN|SHELL|USER|VOLUME|WORKDIR)\s+"
)
_NARRATION_RE = re.compile(
    r"^(?:first|then|next|now|finally|add|build|call|check|configure|create|define|"
    r"deploy|fetch|get|install|load|publish|run|set|setup|test|update|validate|write)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_STOPWORDS: Final = frozenset({"a", "an", "and", "for", "from", "in", "of", "on", "the", "then", "this", "to", "we"})
_CONFIG_RESTATEMENT_RE = re.compile(r"^(?P<key>.+?)\s+(?:is|equals)\s+(?P<value>.+?)[.!]?\s*$", re.IGNORECASE)
_YAML_SCALAR_ENTRY_RE = re.compile(r"^\s*(?:-\s+)?(?P<key>[A-Za-z_][\w.-]*)\s*:\s*(?P<value>[^\s].*?)\s*$")
_TOML_SCALAR_ENTRY_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][\w.-]*)\s*=\s*(?P<value>[^\s].*?)\s*$")
_CONFIG_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*|\d+(?:\.\d+)?")
_QUOTED_SCALAR_MIN_LENGTH: Final = 2
_COMMAND_ARGUMENT_RE: Final = re.compile(r"(?<![A-Za-z0-9_])\$ARGUMENTS(?![A-Za-z0-9_])")
_QUERY_LANGUAGE_NAMES: Final = frozenset({"logql", "postgres", "postgresql", "psql", "sql"})
_SHELL_LANGUAGE_NAMES: Final = frozenset({"", "bash", "console", "sh", "shell", "zsh"})
_QUERY_TOKEN_RE: Final = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE|WHERE|FROM|logQl)\b", re.IGNORECASE)
_QUOTED_ARGUMENT_RE: Final = re.compile(r'(?<!\S)"\$ARGUMENTS"(?!\S)')
_MAX_MARKDOWN_FENCE_INDENT: Final = 3
_MIN_MARKDOWN_FENCE_LENGTH: Final = 3
_SECRET_READ_PERMISSION_PREFIXES: Final = (
    "Bash(aws secretsmanager get-secret-value:",
    "Bash(gcloud secrets versions access:",
    "Bash(vault kv get:",
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    code: str
    message: str

    def render(self) -> str:
        rollout = " warning:" if not _META_BY_CODE[self.code].blocking else ""
        return f"{self.path}:{self.line}:1: {self.code}{rollout} {self.message}"


@dataclass(frozen=True)
class RuleMeta:
    code: str
    summary: str
    rationale: str
    remediation: str
    category: RuleCategory
    languages: frozenset[Language]
    file_patterns: tuple[str, ...]
    examples: tuple[RuleExample, ...]
    autofix: AutofixPolicy = AutofixPolicy.NONE
    aliases: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    message_ids: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    since: str | None = None
    blocking: bool = True

    @property
    def description(self) -> str:
        """Preserve the existing analysis adapter while ``summary`` becomes canonical."""
        return self.summary

    @property
    def public_examples(self) -> tuple[RuleExample, ...]:
        """Return only examples explicitly reviewed for public documentation."""
        return tuple(example for example in self.examples if example.public)

    def native_spec(self, rule_id: str) -> RuleSpec:
        return RuleSpec(
            engine=RuleEngine.TEXT,
            rule_id=RuleId(rule_id),
            code=self.code,
            summary=self.summary,
            rationale=self.rationale,
            remediation=self.remediation,
            category=self.category,
            languages=self.languages,
            autofix=self.autofix,
            aliases=self.aliases,
            examples=self.examples,
            limitations=self.limitations,
            file_patterns=self.file_patterns,
            message_ids=tuple(MessageId(message_id) for message_id in self.message_ids),
            references=self.references,
            since=self.since,
        )


def _public_example(
    *,
    example_id: str,
    title: str,
    outcome: ExpectedOutcome,
    path: str,
    source: str,
    expected_count: int,
) -> RuleExample:
    focus_path = PurePosixPath(path)
    return RuleExample(
        example_id=example_id,
        title=title,
        outcome=outcome,
        files=(ExampleFile(path=focus_path, source=source),),
        focus_path=focus_path,
        expected_count=expected_count,
        public=True,
    )


REGISTRY: Final[Mapping[str, RuleMeta]] = MappingProxyType(
    {
        "config-comment-wall": RuleMeta(
            code="SARJ300",
            summary="four-entry config narration wall with 75% weak restatements",
            rationale=(
                "Repeated comments that merely narrate adjacent configuration hide constraints and make the file harder "
                "to scan."
            ),
            remediation=(
                "Delete narration. Where names are author-controlled, clarify jobs, steps, targets, keys, or sections; "
                "keep comments only for constraints or rationale."
            ),
            category=RuleCategory.MAINTAINABILITY,
            languages=frozenset({Language.CONFIG}),
            file_patterns=("**/*.{yaml,yml,toml,jsonc,ini,cfg,conf,properties,sh,zsh,bash}",),
            examples=(
                _public_example(
                    example_id="narrated-config-wall",
                    title="Repeated comments restate adjacent entries",
                    outcome=ExpectedOutcome.MATCH,
                    path="workflow.yml",
                    source="# Set build name\nname: build\n"
                    "# Run build command\nrun: make build\n"
                    "# Set deploy image\nimage: app\n"
                    "# Run deploy command\ncommand: deploy\n",
                    expected_count=1,
                ),
                _public_example(
                    example_id="self-explanatory-config",
                    title="Clear entries need no narration",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path="workflow.yml",
                    source="name: build\nrun: make build\nimage: app\ncommand: deploy\n",
                    expected_count=0,
                ),
            ),
            limitations=("Only groups of attached standalone comments at the same indentation level are compared.",),
        ),
        "commented-out-config": RuleMeta(
            code="SARJ301",
            summary="commented-out config syntax",
            rationale="Disabled configuration becomes stale while version control already preserves its history.",
            remediation="Delete disabled configuration; document a default or constraint when that information remains useful.",
            category=RuleCategory.MAINTAINABILITY,
            languages=frozenset({Language.CONFIG}),
            file_patterns=("**/*.{yaml,yml,toml,jsonc,ini,cfg,conf,properties,sh,zsh,bash}",),
            examples=(
                _public_example(
                    example_id="disabled-config-entry",
                    title="A commented-out assignment is stale configuration",
                    outcome=ExpectedOutcome.MATCH,
                    path="config.toml",
                    source="# timeout = 30\ntimeout = 10\n",
                    expected_count=1,
                ),
                _public_example(
                    example_id="documented-default",
                    title="An explicitly labeled default is documentation",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path="config.toml",
                    source="# Default:\n# timeout = 30\ntimeout = 10\n",
                    expected_count=0,
                ),
            ),
            limitations=(
                "Directive, rationale, documented-example, and YAML block-scalar comments are intentionally excluded.",
            ),
        ),
        "ephemeral-execution-artifact": RuleMeta(
            code="SARJ302",
            summary="ephemeral execution brief, audit report, or change diary",
            rationale=(
                "Point-in-time execution narratives quickly become misleading and obscure the durable usage or design "
                "facts a repository needs."
            ),
            remediation="Move durable facts into maintained documentation or issues, then delete the execution artifact.",
            category=RuleCategory.MAINTAINABILITY,
            languages=frozenset({Language.MARKDOWN}),
            file_patterns=("**/*.md", "**/*.mdx"),
            aliases=("ephemeral-ai-artifact",),
            examples=(
                _public_example(
                    example_id="temporary-fix-brief",
                    title="A named fix brief is an execution artifact",
                    outcome=ExpectedOutcome.MATCH,
                    path="FIX-BRIEF.md",
                    source="# Temporary execution record\n",
                    expected_count=1,
                ),
                _public_example(
                    example_id="maintained-operations-guide",
                    title="A durable operations guide records current usage",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path="docs/operations.md",
                    source="# Operations\n\nRun `code-standards check` before merging.\n",
                    expected_count=0,
                ),
            ),
            limitations=(
                "Short artifacts with neutral names and no execution-log headings are intentionally not inferred from prose alone.",
            ),
        ),
        "iac-source-coupled-test": RuleMeta(
            code="SARJ304",
            summary="shell test asserts on raw IaC source text",
            rationale=(
                "Text searches can pass on comments, formatting, or unreachable Terraform configuration without proving provider or runtime behavior."
            ),
            remediation="Inspect rendered plan JSON, provider state, or deployed runtime behavior instead of grepping IaC source.",
            category=RuleCategory.TESTING,
            languages=frozenset({Language.CONFIG}),
            file_patterns=("**/*.sh", "**/*.bash", "**/*.zsh"),
            examples=(
                _public_example(
                    example_id="terraform-source-grep",
                    title="Do not grep Terraform source in a shell test",
                    outcome=ExpectedOutcome.MATCH,
                    path="tests/observability.test.sh",
                    source="#!/bin/sh\ngrep -q 'alert_policy' iac/alerts.tf\n",
                    expected_count=1,
                ),
                _public_example(
                    example_id="rendered-plan-query",
                    title="Query structured rendered plan output",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path="tests/observability.test.sh",
                    source="#!/bin/sh\nterraform show -json plan.out | jq -e '.resource_changes | length > 0'\n",
                    expected_count=0,
                ),
            ),
            limitations=(
                "The scanner tokenizes shell quoting, comments, pipelines, direct command substitutions, and local variable flows; sourced helpers and eval remain unreported.",
                "Only test-named shell files or shell files below a tests directory are checked.",
            ),
        ),
        "hidden-markdown-heading": RuleMeta(
            code="SARJ305",
            summary="HTML comment hides a Markdown heading",
            rationale=(
                "A heading hidden from rendered documentation is disabled documentation that silently drifts while "
                "version control already preserves removed sections."
            ),
            remediation="Delete the hidden section, or restore it as maintained rendered documentation.",
            category=RuleCategory.MAINTAINABILITY,
            languages=frozenset({Language.MARKDOWN}),
            file_patterns=("**/*.md", "**/*.mdx"),
            examples=(
                _public_example(
                    example_id="hidden-obsolete-section",
                    title="A hidden heading disables a documentation section",
                    outcome=ExpectedOutcome.MATCH,
                    path="README.md",
                    source="<!--\n## Legacy setup\nUse the retired command.\n-->\n",
                    expected_count=1,
                ),
                _public_example(
                    example_id="visible-current-section",
                    title="Current documentation stays rendered",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path="README.md",
                    source="## Setup\n\nRun the current command.\n",
                    expected_count=0,
                ),
            ),
            limitations=(
                "Only standalone, closed HTML comments containing an ATX heading outside Markdown code are checked; template instructions and protected rationale are preserved.",
            ),
        ),
        "exact-config-comment-restatement": RuleMeta(
            code="SARJ306",
            summary="YAML or TOML comment exactly repeats the adjacent scalar assignment",
            rationale=(
                "A comment that repeats the key and scalar value adds no information and can drift independently from "
                "the configuration it narrates."
            ),
            remediation=(
                "Delete the restatement. If the entry is author-controlled and unclear, clarify its key or section; "
                "keep comments only for constraints or rationale absent from the value."
            ),
            category=RuleCategory.MAINTAINABILITY,
            languages=frozenset({Language.CONFIG}),
            file_patterns=("**/*.yaml", "**/*.yml", "**/*.toml"),
            examples=(
                _public_example(
                    example_id="scalar-value-restatement",
                    title="A prose comment repeats the assignment",
                    outcome=ExpectedOutcome.MATCH,
                    path="config.toml",
                    source="# Retry count is 3\nretry_count = 3\n",
                    expected_count=1,
                ),
                _public_example(
                    example_id="scalar-value-rationale",
                    title="A rationale adds information absent from the assignment",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path="config.toml",
                    source="# Keep three retries because the upstream API is eventually consistent.\nretry_count = 3\n",
                    expected_count=0,
                ),
            ),
            limitations=(
                "Only an immediately adjacent standalone comment using exact `key is value` or `key equals value` wording over a simple scalar entry is checked.",
            ),
        ),
        "no-unsafe-command-argument-interpolation": RuleMeta(
            code="SARJ307",
            summary="raw Claude command argument interpolated into an executable shell or query fence",
            rationale=(
                "Slash-command arguments are user-controlled. Embedding them into a shell token or query string can "
                "change command structure or query semantics when the documented command is executed."
            ),
            remediation=(
                "Pass the argument as its own quoted shell token to a wrapper that validates or parameterizes it; never "
                "splice it into SQL, LogQL, or another query string."
            ),
            category=RuleCategory.SECURITY,
            languages=frozenset({Language.MARKDOWN}),
            file_patterns=(".claude/commands/*.md",),
            examples=(
                _public_example(
                    example_id="query-interpolation",
                    title="Do not splice command arguments into queries",
                    outcome=ExpectedOutcome.MATCH,
                    path=".claude/commands/lookup.md",
                    source="```sql\nSELECT id FROM records WHERE id = '$ARGUMENTS';\n```\n",
                    expected_count=1,
                ),
                _public_example(
                    example_id="quoted-wrapper-argument",
                    title="Pass an opaque argument to a validating wrapper",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path=".claude/commands/lookup.md",
                    source='```bash\nscripts/lookup.sh "$ARGUMENTS"\n```\n',
                    expected_count=0,
                ),
            ),
            limitations=(
                "Only fenced executable examples in .claude/commands Markdown are checked.",
                "A standalone quoted shell argument is accepted on the assumption that the called wrapper validates or parameterizes it.",
            ),
        ),
        "no-wildcard-secret-read-permission": RuleMeta(
            code="SARJ308",
            summary="Claude settings grant wildcard access to secret values",
            rationale=(
                "A wildcard allow entry for a secret-read command lets an agent retrieve every secret visible to the "
                "developer's cloud credentials without a per-command approval boundary."
            ),
            remediation=(
                "Remove the wildcard permission. Allow a narrowly scoped wrapper that validates an explicit secret "
                "name, or require interactive approval for each secret-value read."
            ),
            category=RuleCategory.SECURITY,
            languages=frozenset({Language.CONFIG}),
            file_patterns=(".claude/settings*.json", "**/.claude/settings*.json"),
            examples=(
                _public_example(
                    example_id="wildcard-secret-read",
                    title="Do not preapprove every secret-value read",
                    outcome=ExpectedOutcome.MATCH,
                    path=".claude/settings.json",
                    source='{"permissions":{"allow":["Bash(gcloud secrets versions access:*)"]}}\n',
                    expected_count=1,
                ),
                _public_example(
                    example_id="narrow-secret-wrapper",
                    title="Allow a validating project wrapper instead",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path=".claude/settings.json",
                    source='{"permissions":{"allow":["Bash(make pull-development-secrets)"]}}\n',
                    expected_count=0,
                ),
            ),
            limitations=(
                "Only literal wildcard allow entries for recognized cloud secret-value commands in Claude settings JSON are checked.",
            ),
        ),
    }
)

_META_BY_CODE: Final[Mapping[str, RuleMeta]] = MappingProxyType({meta.code: meta for meta in REGISTRY.values()})


def is_text_path(path: Path) -> bool:
    name = path.name.lower()
    return (
        path.suffix.lower() in _TEXT_SUFFIXES
        or name in _TEXT_NAMES
        or name == ".env"
        or name.startswith(("dockerfile.", ".env."))
        or (path.suffix.casefold() == ".json" and ".claude" in path.parts and name.startswith("settings"))
    )


def check_paths(paths: Sequence[str], *, root: Path | None = None) -> list[Finding]:
    base = (root or Path.cwd()).resolve()
    durable_patterns, excluded_patterns = _text_policy(base)
    findings: list[Finding] = []
    for raw in paths:
        path = Path(raw)
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = _relative(path.resolve(), base)
        if any(fnmatch(relative, pattern) for pattern in excluded_patterns):
            continue
        path_findings = [
            *_artifact_findings(path, relative, source, durable_patterns),
            *_shell_iac_source_findings(path, relative, source),
            *_markdown_hidden_comment_findings(path, source),
            *_markdown_command_argument_findings(path, relative, source),
            *_claude_settings_secret_permission_findings(path, relative, source),
            *_comment_findings(path, source),
        ]
        findings.extend(
            finding
            for finding in path_findings
            if not (path.suffix.lower() in {".md", ".mdx"} and _markdown_suppresses_finding(source, finding))
        )
    return sorted(findings, key=lambda item: (str(item.path), item.line, item.code))


def run(paths: Sequence[str]) -> int:
    findings = check_paths(paths)
    for finding in findings:
        _ = sys.stdout.write(f"{finding.render()}\n")
    return 1 if any(_META_BY_CODE[finding.code].blocking for finding in findings) else 0


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _markdown_suppresses_finding(source: str, finding: Finding) -> bool:
    if finding.code == "SARJ302":
        prose = "\n".join(_markdown_prose_lines(source))
        return any(
            finding.code in {code.strip().upper() for code in match.group("codes").split(",")}
            for match in _MARKDOWN_SUPPRESSION_RE.finditer(prose)
        )
    lines = source.splitlines()
    if finding.line <= 1 or finding.line > len(lines):
        return False
    match = _MARKDOWN_SUPPRESSION_RE.fullmatch(lines[finding.line - 2])
    return match is not None and finding.code in {code.strip().upper() for code in match.group("codes").split(",")}


_SHELL_SUFFIXES: Final = frozenset({".bash", ".sh", ".zsh"})
_IAC_SOURCE_SUFFIXES: Final = (".hcl", ".tf", ".tf.json", ".tfvars", ".tftest.hcl", ".tftest.json")
_SHELL_SOURCE_ASSERT_COMMANDS: Final = frozenset({"awk", "grep", "rg", "sed"})
_SHELL_SOURCE_READ_COMMANDS: Final = frozenset({"cat", "read"})
_SHELL_ASSERT_TOKENS: Final = frozenset({"[", "[[", "assert", "grep", "rg", "test"})
_SHELL_SEPARATORS: Final = frozenset({"&&", ";", "|", "||"})
_GREP_VALUE_OPTIONS: Final = frozenset(
    {
        "--after-context",
        "--before-context",
        "--context",
        "--file",
        "--max-count",
        "--regexp",
        "-A",
        "-B",
        "-C",
        "-e",
        "-f",
        "-m",
    }
)
_SED_VALUE_OPTIONS: Final = frozenset({"--expression", "--file", "-e", "-f"})
_AWK_VALUE_OPTIONS: Final = frozenset({"--assign", "--field-separator", "--file", "-F", "-f", "-v"})


def _shell_iac_source_findings(path: Path, relative: str, source: str) -> list[Finding]:
    if path.suffix.casefold() not in _SHELL_SUFFIXES or not _shell_test_path(relative):
        return []
    findings: list[Finding] = []
    tainted: set[str] = set()
    path_names: set[str] = set()
    for number, line in _shell_logical_lines(source):
        tokens = _shell_tokens(line)
        if not tokens:
            continue
        assignment = _shell_assignment(tokens)
        has_iac = _shell_has_iac_path(tokens, path_names)
        if assignment is not None:
            path_names.discard(assignment)
            tainted.discard(assignment)
            if has_iac and not _shell_has_source_read(tokens):
                path_names.add(assignment)
            elif has_iac and _shell_has_source_read(tokens):
                tainted.add(assignment)
            continue

        direct_assert = False
        pipeline_iac = False
        for separator, segment in _shell_segments(tokens):
            if separator != "|":
                pipeline_iac = False
            command = _shell_command(segment[0]) if segment else ""
            if command in _SHELL_SOURCE_ASSERT_COMMANDS and (
                _shell_assertion_reads_iac(segment, path_names) or pipeline_iac
            ):
                direct_assert = True
            if command in _SHELL_ASSERT_TOKENS and any(_shell_uses_variable(segment, name) for name in tainted):
                direct_assert = True
            if command in _SHELL_ASSERT_TOKENS and _shell_embeds_iac_read(segment, path_names):
                direct_assert = True
            pipeline_iac = _shell_reads_iac(segment, path_names) or pipeline_iac

        if direct_assert:
            findings.append(
                Finding(
                    path,
                    number,
                    "SARJ304",
                    "Raw IaC source text is the shell test oracle — inspect rendered plan JSON, provider state, or runtime behavior.",
                )
            )
            continue
        read_target = _shell_read_target(tokens) if has_iac else None
        if read_target is not None:
            tainted.add(read_target)
    return findings


def _shell_test_path(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    name = parts[-1].casefold() if parts else ""
    return (
        any(part.casefold() in {"test", "tests"} for part in parts[:-1]) or name.startswith("test_") or ".test." in name
    )


def _shell_tokens(line: str) -> list[str]:
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars="|;&()<>[]")
        lexer.commenters = "#"
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return []


class _ShellLogicalLine(NamedTuple):
    line: int
    command: str


class _ShellSegment(NamedTuple):
    separator: str | None
    tokens: list[str]


def _shell_logical_lines(source: str) -> list[_ShellLogicalLine]:
    logical: list[_ShellLogicalLine] = []
    pending: list[str] = []
    start = 1
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.rstrip()
        slash_count = len(stripped) - len(stripped.rstrip("\\"))
        continued = slash_count % 2 == 1
        if not pending:
            start = number
        pending.append(stripped[:-1] if continued else line)
        if continued:
            continue
        logical.append(_ShellLogicalLine(start, " ".join(pending)))
        pending = []
    if pending:
        logical.append(_ShellLogicalLine(start, " ".join(pending)))
    return logical


def _shell_segments(tokens: Sequence[str]) -> list[_ShellSegment]:
    segments: list[_ShellSegment] = []
    current: list[str] = []
    separator: str | None = None
    for token in tokens:
        if token in _SHELL_SEPARATORS:
            if current:
                segments.append(_ShellSegment(separator, current))
                current = []
            separator = token
            continue
        current.append(token)
    if current:
        segments.append(_ShellSegment(separator, current))
    return segments


def _shell_command(token: str) -> str:
    return PurePosixPath(token.casefold()).name


def _shell_has_iac_path(tokens: Sequence[str], path_names: set[str]) -> bool:
    return any(_iac_source_token(token) for token in tokens) or any(
        _shell_uses_variable(tokens, name) for name in path_names
    )


def _iac_source_token(token: str) -> bool:
    return token.strip("'\"),;:[]{}>").casefold().endswith(_IAC_SOURCE_SUFFIXES)


def _shell_assertion_reads_iac(tokens: Sequence[str], path_names: set[str]) -> bool:
    if not tokens:
        return False
    command = _shell_command(tokens[0])
    redirected = [tokens[index + 1] for index, item in enumerate(tokens[:-1]) if item == "<"]
    if command in {"grep", "rg"}:
        operands, explicit_pattern = _shell_operands(
            tokens[1:], _GREP_VALUE_OPTIONS, {"--regexp", "-e", "--file", "-f"}
        )
        inputs = operands if explicit_pattern else operands[1:]
    elif command == "sed":
        operands, explicit_pattern = _shell_operands(
            tokens[1:], _SED_VALUE_OPTIONS, {"--expression", "-e", "--file", "-f"}
        )
        inputs = operands if explicit_pattern else operands[1:]
    elif command == "awk":
        operands, explicit_pattern = _shell_operands(tokens[1:], _AWK_VALUE_OPTIONS, {"--file", "-f"})
        inputs = operands if explicit_pattern else operands[1:]
    else:
        return False
    return _shell_has_iac_path([*inputs, *redirected], path_names)


def _shell_operands(tokens: Sequence[str], value_options: frozenset[str], pattern_options: set[str]) -> _ShellOperands:
    operands: list[str] = []
    explicit_pattern = False
    consume_value = False
    options = True
    for item in tokens:
        if consume_value:
            consume_value = False
            continue
        if options and item == "--":
            options = False
            continue
        option, separator, _value = item.partition("=")
        if options and option in value_options:
            explicit_pattern = explicit_pattern or option in pattern_options
            consume_value = not separator
            continue
        if options and item.startswith("-") and item != "-":
            if any(
                item.startswith(prefix) and len(item) > len(prefix)
                for prefix in value_options
                if prefix.startswith("-")
            ):
                explicit_pattern = explicit_pattern or any(
                    item.startswith(prefix) and len(item) > len(prefix) for prefix in pattern_options
                )
            continue
        operands.append(item)
    return _ShellOperands(operands, explicit_pattern)


def _shell_reads_iac(tokens: Sequence[str], path_names: set[str]) -> bool:
    if not tokens:
        return False
    command = _shell_command(tokens[0])
    if command not in _SHELL_SOURCE_READ_COMMANDS:
        return False
    return _shell_has_iac_path(tokens[1:], path_names)


def _shell_embeds_iac_read(tokens: Sequence[str], path_names: set[str]) -> bool:
    for index, item in enumerate(tokens):
        if item == "$" and tokens[index + 1 : index + 3] == ["(", "cat"]:
            try:
                end = tokens.index(")", index + 3)
            except ValueError:
                continue
            if _shell_has_iac_path(tokens[index + 3 : end], path_names):
                return True
        match = re.search(r"\$\(cat\s+(?P<input>[^)]+)\)", item)
        if match is not None and _shell_has_iac_path(_shell_tokens(match.group("input")), path_names):
            return True
    return False


def _shell_assignment(tokens: Sequence[str]) -> str | None:
    if not tokens:
        return None
    match = re.match(r"^(?:local\s+)?([A-Za-z_][A-Za-z0-9_]*)=", " ".join(tokens))
    return match.group(1) if match is not None else None


def _shell_has_source_read(tokens: Sequence[str]) -> bool:
    if any(_shell_command(token) in _SHELL_SOURCE_READ_COMMANDS for token in tokens):
        return True
    return bool(re.search(r"(?:^|[$(])(?:cat|read)\s", " ".join(tokens)))


def _shell_read_target(tokens: Sequence[str]) -> str | None:
    try:
        index = next(index for index, token in enumerate(tokens) if _shell_command(token) == "read")
    except StopIteration:
        return None
    for token in tokens[index + 1 :]:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            return token
    return None


def _shell_uses_variable(tokens: Sequence[str], name: str) -> bool:
    patterns = {f"${name}", f"${{{name}}}"}
    return any(token in patterns or any(pattern in token for pattern in patterns) for token in tokens)


def _artifact_findings(
    path: Path,
    relative: str,
    source: str,
    durable_patterns: tuple[str, ...],
) -> list[Finding]:
    if path.suffix.lower() not in {".md", ".mdx"}:
        return []
    if path.name.lower() == "changelog.md":
        return []
    if any(part.lower() in {"_backups", "backups"} for part in path.parts):
        return [
            Finding(
                path,
                1,
                "SARJ302",
                "Backup work artifact — recover durable facts into maintained documentation and remove the backup copy.",
            )
        ]
    durable = any(fnmatch(relative, pattern) for pattern in durable_patterns)
    if _STRONG_ARTIFACT_NAME_RE.search(path.stem) or (not durable and _ARTIFACT_NAME_RE.search(path.stem)):
        return [
            Finding(
                path,
                1,
                "SARJ302",
                "Ephemeral AI work artifact — move durable knowledge into README/docs/ADR and delete the execution brief or report.",
            )
        ]
    source_lines = _markdown_prose_lines(source)
    prose = "\n".join(source_lines)
    headings = [
        number for number, line in enumerate(source_lines, start=1) if _EPHEMERAL_HEADING_RE.match(line.strip())
    ]
    has_change_diary = any(_STRONG_DIARY_HEADING_RE.match(line.strip()) for line in source_lines)
    if len(headings) >= _MIN_EPHEMERAL_HEADINGS or has_change_diary:
        return [
            Finding(
                path,
                headings[0],
                "SARJ302",
                "Chronological AI execution log — keep current usage/design facts; remove passes, change diary, and session narration.",
            )
        ]
    if _large_artifact(prose, path, source_lines):
        line = next(
            (
                number
                for number, source_line in enumerate(source_lines, start=1)
                if _LIFECYCLE_HEADING_RE.match(source_line.strip())
            ),
            1,
        )
        return [
            Finding(
                path,
                line,
                "SARJ302",
                "Point-in-time audit or execution report — move durable facts to maintained documentation and track findings in the issue system.",
            )
        ]
    return []


def _markdown_command_argument_findings(path: Path, relative: str, source: str) -> list[Finding]:
    if not fnmatch(relative, ".claude/commands/*.md"):
        return []
    findings: list[Finding] = []
    fence: tuple[str, int, str] | None = None
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip(" ") if len(line) - len(line.lstrip(" ")) <= _MAX_MARKDOWN_FENCE_INDENT else ""
        marker = stripped[:1]
        marker_length = len(stripped) - len(stripped.lstrip(marker)) if marker in {"`", "~"} else 0
        if fence is None:
            if marker_length < _MIN_MARKDOWN_FENCE_LENGTH:
                continue
            info = stripped[marker_length:].strip().split(maxsplit=1)
            language = info[0].casefold() if info else ""
            fence = (marker, marker_length, language)
            continue
        fence_marker, fence_length, language = fence
        if marker == fence_marker and marker_length >= fence_length and not stripped[marker_length:].strip():
            fence = None
            continue
        if language not in _QUERY_LANGUAGE_NAMES | _SHELL_LANGUAGE_NAMES or not _COMMAND_ARGUMENT_RE.search(line):
            continue
        unsafe = language in _QUERY_LANGUAGE_NAMES or bool(_QUERY_TOKEN_RE.search(line))
        if not unsafe:
            without_safe_arguments = _QUOTED_ARGUMENT_RE.sub("", line)
            unsafe = bool(_COMMAND_ARGUMENT_RE.search(without_safe_arguments))
        if unsafe:
            findings.append(
                Finding(
                    path,
                    line_number,
                    "SARJ307",
                    "User-controlled $ARGUMENTS is spliced into an executable command or query. Pass it as a standalone quoted argument to a validating wrapper.",
                )
            )
    return findings


def _claude_settings_secret_permission_findings(path: Path, relative: str, source: str) -> list[Finding]:
    if not (fnmatch(relative, ".claude/settings*.json") or fnmatch(relative, "**/.claude/settings*.json")):
        return []
    try:
        settings = _ClaudeSettings.model_validate_json(source)
    except ValidationError:
        return []
    findings: list[Finding] = []
    lines = source.splitlines()
    for permission in settings.permissions.allow:
        if "*" not in permission:
            continue
        if not any(permission.startswith(prefix) for prefix in _SECRET_READ_PERMISSION_PREFIXES):
            continue
        line_number = next((number for number, line in enumerate(lines, start=1) if permission in line), 1)
        findings.append(
            Finding(
                path,
                line_number,
                "SARJ308",
                "Wildcard secret-value access is preapproved. Require per-read approval or a validating, narrowly scoped wrapper.",
            )
        )
    return findings


def _markdown_prose_lines(source: str) -> list[str]:
    max_fence_indent = 3
    min_fence_length = 3
    indented_code_spaces = 4
    visible: list[str] = []
    fence: tuple[str, int] | None = None
    for line in source.splitlines():
        leading_spaces = len(line) - len(line.lstrip(" "))
        candidate = line[leading_spaces:] if leading_spaces <= max_fence_indent else ""
        marker = candidate[:1]
        marker_length = len(candidate) - len(candidate.lstrip(marker)) if marker in {"`", "~"} else 0
        if fence is not None:
            fence_marker, fence_length = fence
            if marker == fence_marker and marker_length >= fence_length and not candidate[marker_length:].strip():
                fence = None
            visible.append("")
            continue
        if marker_length >= min_fence_length and (marker != "`" or "`" not in candidate[marker_length:]):
            fence = (marker, marker_length)
            visible.append("")
            continue
        if leading_spaces >= indented_code_spaces or line.startswith("\t"):
            visible.append("")
            continue
        visible.append(line)
    return visible


def _markdown_hidden_comment_findings(path: Path, source: str) -> list[Finding]:
    if path.suffix.casefold() not in {".md", ".mdx"}:
        return []
    return [
        Finding(
            path,
            comment.line,
            "SARJ305",
            "HTML comment hides a Markdown heading — delete the disabled section or restore it as maintained documentation.",
        )
        for comment in _markdown_html_comments(source)
        if _hidden_markdown_heading(comment.body)
    ]


def _markdown_html_comments(source: str) -> list[_MarkdownHtmlComment]:
    comments: list[_MarkdownHtmlComment] = []
    pending_line: int | None = None
    pending: list[str] = []
    for line_number, line in enumerate(_markdown_prose_lines(source), start=1):
        if pending_line is None:
            match = re.fullmatch(r"\s*<!--(?P<body>.*)", line)
            if match is None:
                continue
            pending_line = line_number
            remainder = match.group("body")
        else:
            remainder = line
        before, marker, after = remainder.partition("-->")
        if marker:
            if after.strip():
                pending_line = None
                pending = []
                continue
            pending.append(before)
            comments.append(_MarkdownHtmlComment(pending_line, "\n".join(pending).strip()))
            pending_line = None
            pending = []
            continue
        pending.append(remainder)
    return comments


def _hidden_markdown_heading(body: str) -> bool:
    lines = [stripped for line in body.splitlines() if (stripped := line.strip())]
    if not lines or _MARKDOWN_HIDDEN_DIRECTIVE_RE.match(lines[0]):
        return False
    prose = "\n".join(lines)
    if _PROTECTED_RE.search(prose):
        return False
    return any(_MARKDOWN_ATX_HEADING_RE.match(line) for line in lines)


def _large_artifact(source: str, path: Path, lines: list[str]) -> bool:
    if len(lines) < _LARGE_ARTIFACT_MIN_LINES and not _has_word_count(source, _LARGE_ARTIFACT_MIN_WORDS):
        return False
    title = next((line.removeprefix("#").strip() for line in lines if line.startswith("#")), "")
    dated_subject = f"{path.stem} {title}"
    lifecycle_headings = {
        match.group(0).casefold() for line in lines if (match := _LIFECYCLE_HEADING_RE.match(line.strip())) is not None
    }
    has_findings_section = any(
        re.match(r"^#{1,6}\s+(?:further )?findings(?:\s|$)", line, re.IGNORECASE) for line in lines
    )
    numbered_findings = sum(bool(_NUMBERED_FINDING_RE.match(line)) for line in lines)
    dated_artifact = bool(_DATED_ARTIFACT_RE.search(dated_subject))
    ai_generation = bool(_AI_GENERATION_RE.search(source))
    self_description = bool(_ARTIFACT_SELF_DESCRIPTION_RE.search(source))
    structural_signal = len(lifecycle_headings) >= _MIN_EPHEMERAL_HEADINGS or (
        has_findings_section and numbered_findings >= _MIN_NUMBERED_FINDINGS
    )
    signals = (
        dated_artifact,
        structural_signal,
        any(_RESULTS_TABLE_RE.match(line) for line in lines),
        ai_generation,
        self_description,
    )
    has_provenance = dated_artifact or ai_generation or self_description
    return has_provenance and sum(signals) >= _LARGE_ARTIFACT_MIN_SIGNALS


def _has_word_count(source: str, minimum: int) -> bool:
    return next((True for index, _match in enumerate(_WORD_RE.finditer(source), start=1) if index >= minimum), False)


def _text_policy(root: Path) -> _TextPolicy:
    manifest = root / ".sarj-standards.toml"
    if not manifest.is_file():
        return _TextPolicy(_DURABLE_MARKDOWN, ())
    try:
        parsed: object = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return _TextPolicy(_DURABLE_MARKDOWN, ())
    table = as_table(parsed)
    configured_durable = list_field(table_field(table, "artifacts"), "durable")
    durable = (
        tuple(dict.fromkeys((*_DURABLE_MARKDOWN, *(item for item in configured_durable if isinstance(item, str)))))
        if configured_durable and all(isinstance(item, str) for item in configured_durable)
        else _DURABLE_MARKDOWN
    )
    configured_excluded = list_field(table_field(table, "text"), "exclude")
    excluded = (
        tuple(item for item in configured_excluded if isinstance(item, str))
        if configured_excluded and all(isinstance(item, str) for item in configured_excluded)
        else ()
    )
    return _TextPolicy(durable, excluded)


def _comment_findings(path: Path, source: str) -> list[Finding]:
    if path.suffix.lower() in {".md", ".mdx"}:
        return []
    lines = source.splitlines()
    attached: list[_AttachedComment] = []
    findings: list[Finding] = []
    config_run_lines = _commented_config_runs(path, lines)
    if config_run_lines:
        findings.extend(
            Finding(
                path,
                line,
                "SARJ301",
                "Commented-out config block — delete it; version control preserves history.",
            )
            for line in sorted(config_run_lines)
        )
    for index, line in enumerate(lines):
        parsed = _standalone_comment(path, line)
        if parsed is None:
            continue
        indent, body = parsed
        if path.suffix.lower() in {".yaml", ".yml"} and _inside_yaml_block_scalar(lines, index, indent):
            continue
        if index + 1 in config_run_lines:
            continue
        if not body or _DIRECTIVE_RE.match(body):
            continue
        protected = bool(_PROTECTED_RE.search(body))
        if not protected and _looks_commented_config(path, body) and not _inside_comment_run(path, lines, index):
            findings.append(
                Finding(
                    path, index + 1, "SARJ301", "Commented-out config — delete it; version control preserves history."
                )
            )
            continue
        if (
            not protected
            and _exact_config_restatement(path, body, lines, index)
            and not _suppresses_previous_line(lines, index, "SARJ306")
        ):
            findings.append(
                Finding(
                    path,
                    index + 1,
                    "SARJ306",
                    "Comment repeats the adjacent assignment — delete it; clarify an author-controlled key or section "
                    "if the entry is unclear.",
                )
            )
            continue
        next_index = _next_content_line(lines, index + 1)
        if next_index is None:
            continue
        next_line = lines[next_index]
        if len(next_line) - len(next_line.lstrip()) != indent:
            continue
        attached.append(_AttachedComment(index + 1, indent, False if protected else _weak_narration(body, next_line)))

    for group in _attached_groups(attached):
        weak = [line for line, _indent, is_weak in group if is_weak]
        if (
            len(group) >= _WALL_MIN_ATTACHED
            and len(weak) >= _WALL_MIN_WEAK
            and len(weak) / len(group) >= _WALL_MIN_WEAK_RATIO
        ):
            findings.append(
                Finding(
                    path,
                    weak[0],
                    "SARJ300",
                    f"Config comment wall ({len(weak)} narrated entries) — where names are author-controlled, clarify "
                    "jobs, steps, targets, keys, or sections; keep only constraints or rationale.",
                )
            )
    return findings


def _suppresses_previous_line(lines: list[str], index: int, code: str) -> bool:
    if index == 0:
        return False
    parsed = _standalone_comment(Path("workflow.yml"), lines[index - 1])
    if parsed is None:
        return False
    match = _SARJ_SUPPRESSION_RE.fullmatch(parsed[1])
    return match is not None and code in {item.strip().upper() for item in match.group("codes").split(",")}


def _commented_config_runs(path: Path, lines: list[str]) -> set[int]:
    leaders: set[int] = set()
    index = 0
    while index < len(lines):
        if _standalone_comment(path, lines[index]) is None:
            index += 1
            continue
        run: list[tuple[int, str]] = []
        while index < len(lines) and (parsed := _standalone_comment(path, lines[index])) is not None:
            indent, body = parsed
            if not (path.suffix.lower() in {".yaml", ".yml"} and _inside_yaml_block_scalar(lines, index, indent)):
                run.append((index + 1, body))
            index += 1
        suppressions = {
            code.upper()
            for _line, body in run
            if (match := _SARJ_SUPPRESSION_RE.match(body)) is not None
            for code in match.group("codes").split(",")
        }
        if "SARJ301" in suppressions:
            continue
        effective = [(line, body) for line, body in run if _SARJ_SUPPRESSION_RE.match(body) is None]
        if not effective:
            continue
        if any(_DIRECTIVE_RE.match(body) for _line, body in effective):
            continue
        shaped = [line for line, body in effective if _looks_commented_config(path, body)]
        if len(shaped) >= _COMMENTED_CONFIG_RUN_MIN and len(shaped) / len(effective) >= _COMMENTED_CONFIG_RUN_RATIO:
            leaders.add(shaped[0])
    return leaders


def _standalone_comment(path: Path, line: str) -> _StandaloneComment | None:
    stripped = line.lstrip()
    if path.suffix.lower() == ".jsonc":
        for marker in ("//", "/*", "*"):
            if stripped.startswith(marker):
                body = stripped.removeprefix(marker).removesuffix("*/").strip()
                return _StandaloneComment(len(line) - len(stripped), body)
        return None
    if not stripped.startswith("#"):
        return None
    return _StandaloneComment(len(line) - len(stripped), stripped.removeprefix("#").strip())


def _looks_commented_config(path: Path, body: str) -> bool:
    if path.name.lower().startswith("dockerfile") and _DOCKER_SHAPE_RE.match(body):
        return True
    if path.suffix.lower() == ".toml" and body.startswith("[") and body.endswith("]"):
        return True
    # Reject prose-shaped text before recognizing disabled configuration.
    if len(body.split()) > _COMMENTED_CONFIG_MAX_WORDS or ". " in body or not _CONFIG_SHAPE_RE.match(body):
        return False
    _key, separator, value = body.partition(":" if ":" in body else "=")
    if not separator:
        return False
    compact = value.strip()
    return bool(compact) and (
        not any(character.isspace() for character in compact)
        or compact.startswith(("[", "{"))
        or (compact[0] in {'"', "'"} and compact[-1] == compact[0])
    )


def _exact_config_restatement(path: Path, body: str, lines: list[str], index: int) -> bool:
    if path.suffix.casefold() not in {".toml", ".yaml", ".yml"} or index + 1 >= len(lines):
        return False
    if (
        index > 0
        and (previous := _standalone_comment(path, lines[index - 1])) is not None
        and _SARJ_SUPPRESSION_RE.fullmatch(previous.body) is None
    ):
        return False
    comment = _CONFIG_RESTATEMENT_RE.fullmatch(body)
    entry = _config_scalar_entry(path, lines[index + 1])
    if comment is None or entry is None:
        return False
    return _config_words(comment.group("key")) == _config_words(entry.key) and _config_value(
        comment.group("value")
    ) == _config_value(entry.value)


def _config_scalar_entry(path: Path, line: str) -> _ConfigScalarEntry | None:
    pattern = _TOML_SCALAR_ENTRY_RE if path.suffix.casefold() == ".toml" else _YAML_SCALAR_ENTRY_RE
    match = pattern.fullmatch(line)
    if match is None:
        return None
    value = match.group("value").strip()
    if value.startswith(("[", "{")) or value in {"|", ">", "|-", "|+", ">-", ">+"} or " #" in value or "${{" in value:
        return None
    if len(value) >= _QUOTED_SCALAR_MIN_LENGTH and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return _ConfigScalarEntry(match.group("key"), value)


def _config_words(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in _CONFIG_TOKEN_RE.finditer(text):
        expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", match.group(0))
        tokens.extend(part.casefold() for part in re.split(r"[-_]+", expanded) if part)
    return tuple(tokens)


def _config_value(text: str) -> str:
    value = text.strip()
    if len(value) >= _QUOTED_SCALAR_MIN_LENGTH and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return " ".join(value.split()).casefold()


def _inside_comment_run(path: Path, lines: list[str], index: int) -> bool:
    return (index > 0 and _standalone_comment(path, lines[index - 1]) is not None) or (
        index + 1 < len(lines) and _standalone_comment(path, lines[index + 1]) is not None
    )


def _inside_yaml_block_scalar(lines: list[str], index: int, indent: int) -> bool:
    for previous in range(index - 1, -1, -1):
        candidate = lines[previous]
        if not candidate.strip():
            continue
        candidate_indent = len(candidate) - len(candidate.lstrip())
        if candidate_indent >= indent:
            continue
        return bool(re.search(r"[>|][+-]?\s*$", candidate))
    return False


def _attached_groups(
    attached: list[_AttachedComment],
) -> list[list[_AttachedComment]]:
    groups: list[list[_AttachedComment]] = []
    for entry in attached:
        if (
            groups
            and groups[-1]
            and entry[1] == groups[-1][-1][1]
            and entry[0] <= groups[-1][-1][0] + _WALL_GROUP_MAX_LINES
        ):
            groups[-1].append(entry)
        else:
            groups.append([entry])
    return groups


def _next_content_line(lines: list[str], start: int) -> int | None:
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if not stripped:
            return None
        if not stripped.startswith(("#", "//")):
            return index
    return None


def _weak_narration(body: str, statement: str) -> bool:
    if len(body.split()) > _WALL_MAX_WORDS or not _NARRATION_RE.match(body):
        return False
    words = [_normalize_word(word) for word in _words(body)][1:]
    content = [word for word in words if word not in _STOPWORDS]
    if not content:
        return False
    code = {_normalize_word(word) for word in _words(statement)}
    matched = sum(word in code or word.rstrip("s") in code for word in content)
    return matched / len(content) >= _WALL_MIN_MATCHED_RATIO and len(content) - matched <= _WALL_MAX_NOVEL_WORDS


def _words(text: str) -> list[str]:
    words: list[str] = []
    for match in _WORD_RE.finditer(text):
        expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", match.group(0))
        words.extend(part for part in re.split(r"[-_]+", expanded) if part)
    return words


def _normalize_word(word: str) -> str:
    return word.lower().replace("-", "_")
