from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
import json
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
import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import ScalarToken

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

    from yaml.error import Mark


class _ShellOperands(NamedTuple):
    operands: list[str]
    explicit_pattern: bool


class _WorkflowAction(NamedTuple):
    line: int
    uses: str
    command: str


class _HeredocSpec(NamedTuple):
    delimiter: str
    strip_tabs: bool


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
_OPERATIONAL_ROOTS: Final = frozenset(
    {"cloudbuild", "deploy", "deployments", "iac", "infra", "k8s", "scripts", "terraform", "tools"}
)
_SHELL_CONTROL_PREFIXES: Final = frozenset(
    {"!", "command", "do", "elif", "else", "exec", "if", "then", "time", "until", "while"}
)
_GCLOUD_RELEASE_TRACKS: Final = frozenset({"alpha", "beta", "preview"})
_ENV_VALUE_OPTIONS: Final = frozenset({"--chdir", "--split-string", "--unset", "-C", "-S", "-u"})
_GCLOUD_GLOBAL_VALUE_OPTIONS: Final = frozenset(
    {
        "--account",
        "--billing-project",
        "--configuration",
        "--flags-file",
        "--format",
        "--impersonate-service-account",
        "--project",
        "--trace-token",
        "--verbosity",
    }
)
_GCLOUD_MUTATIONS: Final = frozenset(
    {
        ("builds", "triggers", "create"),
        ("builds", "triggers", "delete"),
        ("builds", "triggers", "update"),
        ("compute", "instances", "create"),
        ("compute", "instances", "delete"),
        ("deploy", "releases", "create"),
        ("functions", "delete"),
        ("functions", "deploy"),
        ("iam", "service-accounts", "add-iam-policy-binding"),
        ("iam", "service-accounts", "remove-iam-policy-binding"),
        ("projects", "add-iam-policy-binding"),
        ("projects", "remove-iam-policy-binding"),
        ("pubsub", "subscriptions", "create"),
        ("pubsub", "subscriptions", "delete"),
        ("pubsub", "subscriptions", "update"),
        ("pubsub", "topics", "create"),
        ("pubsub", "topics", "delete"),
        ("pubsub", "topics", "update"),
        ("run", "deploy"),
        ("run", "jobs", "delete"),
        ("run", "jobs", "deploy"),
        ("run", "jobs", "replace"),
        ("run", "jobs", "update"),
        ("run", "services", "add-iam-policy-binding"),
        ("run", "services", "delete"),
        ("run", "services", "remove-iam-policy-binding"),
        ("run", "services", "replace"),
        ("run", "services", "update"),
        ("scheduler", "jobs", "create"),
        ("scheduler", "jobs", "delete"),
        ("scheduler", "jobs", "update"),
        ("secrets", "create"),
        ("secrets", "delete"),
        ("secrets", "versions", "add"),
        ("secrets", "versions", "destroy"),
        ("secrets", "versions", "disable"),
        ("secrets", "versions", "enable"),
        ("services", "disable"),
        ("services", "enable"),
        ("sql", "instances", "clone"),
        ("sql", "instances", "create"),
        ("sql", "instances", "delete"),
        ("sql", "instances", "patch"),
        ("tasks", "queues", "create"),
        ("tasks", "queues", "delete"),
        ("tasks", "queues", "update"),
        ("workflows", "delete"),
        ("workflows", "deploy"),
    }
)
_GCLOUD_RUN_RELEASE_COMMANDS: Final = (
    ("run", "deploy"),
    ("run", "jobs", "update"),
    ("run", "services", "update"),
)
_GCLOUD_RUN_ARTIFACT_OPTIONS: Final = frozenset({"--image", "--source"})
_GCLOUD_RUN_RELEASE_VALUE_OPTIONS: Final = _GCLOUD_GLOBAL_VALUE_OPTIONS | frozenset(
    {"--image", "--platform", "--region", "--source", "--tag"}
)
_GCLOUD_RUN_RELEASE_BOOLEAN_OPTIONS: Final = frozenset({"--async", "--no-traffic", "--quiet", "--wait"})
_KUBECTL_GLOBAL_VALUE_OPTIONS: Final = frozenset(
    {
        "--as",
        "--as-group",
        "--cache-dir",
        "--cluster",
        "--context",
        "--kubeconfig",
        "--namespace",
        "--request-timeout",
        "--server",
        "--token",
        "--user",
        "-n",
    }
)
_KUBECTL_MUTATIONS: Final = frozenset(
    {
        "annotate",
        "apply",
        "create",
        "delete",
        "edit",
        "expose",
        "label",
        "patch",
        "replace",
        "scale",
        "set",
        "taint",
    }
)
_KUBECTL_MUTATION_PREFIXES: Final = frozenset(
    {
        ("auth", "reconcile"),
        ("certificate", "approve"),
        ("certificate", "deny"),
    }
)
_TERRAFORM_STATE_MUTATIONS: Final = frozenset({"mv", "push", "replace-provider", "rm"})
_TERRAFORM_DIRECT_MUTATIONS: Final = frozenset({"import", "taint", "untaint"})
_WRANGLER_MUTATIONS: Final = frozenset({("d1", "create")})
_PACKAGE_EXEC_VALUE_OPTIONS: Final = frozenset(
    {"--cache", "--prefix", "--userconfig", "--workspace", "--workspace-root", "-C", "-w"}
)
_CONFIG_KEY_RE: Final = re.compile(r"[\"']?(?P<key>[A-Za-z_][\w.-]*)[\"']?\s*[:=]")
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
_COMMENTED_CONFIG_RUN_MIN: Final = 2
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
_SHELL_DIALECT_BY_SUFFIX: Final = MappingProxyType(
    {
        ".bash": "bash",
        ".bats": "bash",
        ".dash": "dash",
        ".ksh": "ksh",
        ".sh": "sh",
        ".zsh": "zsh",
    }
)
_SHELL_SHEBANG_RE: Final = re.compile(
    rb"^#!\s*(?:/usr/bin/env(?:\s+-S)?\s+|/(?:usr/)?bin/)(?P<shell>bash|busybox|dash|ksh|sh|zsh)(?:\s|$)"
)
_LARGE_SHELL_SUBSTANTIVE_LINES: Final = 200
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
    scenario: str = "primary",
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
        scenario=scenario,
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
            blocking=False,
            summary="unexplained disabled config blocks or adjacent alternatives",
            rationale="Disabled configuration becomes stale while version control already preserves its history.",
            remediation="Delete inactive settings, or explain the supported default, optional override, or constraint.",
            category=RuleCategory.MAINTAINABILITY,
            languages=frozenset({Language.CONFIG}),
            file_patterns=("**/*.{yaml,yml,toml,jsonc}",),
            examples=(
                _public_example(
                    example_id="disabled-config-entry",
                    title="An unexplained alternative repeats the adjacent active key",
                    outcome=ExpectedOutcome.MATCH,
                    path="config.toml",
                    source="# timeout = 30\ntimeout = 10\n",
                    expected_count=1,
                ),
                _public_example(
                    example_id="documented-default",
                    title="A labeled optional override remains documentation",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path="config.toml",
                    source="# Optional local override:\n# timeout = 30\ntimeout = 10\n",
                    expected_count=0,
                ),
            ),
            limitations=(
                "Only YAML, TOML, and JSONC are analyzed; other configuration dialects need dedicated syntax support.",
                "Requires two same-indent entries or one entry repeating an immediately adjacent active key.",
                "Explanatory comment blocks, references, directives, and multiline string payloads are preserved.",
                "YAML detection covers scalar mapping entries, not sequence entries or collection-valued mappings.",
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
        "declarative-deployment-boundary": RuleMeta(
            code="SARJ309",
            blocking=False,
            summary="recognized control-plane commands mutate infrastructure outside Terraform",
            rationale=(
                "Imperative control-plane commands and plan-address allowlists split deployment ownership between "
                "Terraform and repository-specific orchestration, so drift and safety depend on execution order. "
                "Publishing an application artifact is a release operation and remains outside this rule."
            ),
            remediation=(
                "Model the resource, identity, and lifecycle in Terraform; let CI select inputs and apply the saved "
                "plan without maintaining a second mutation path."
            ),
            category=RuleCategory.ARCHITECTURE,
            languages=frozenset({Language.CONFIG}),
            file_patterns=(
                ".github/workflows/*.{yaml,yml}",
                "{cloudbuild,deploy,deployments,iac,infra,k8s,scripts,terraform,tools}/**",
            ),
            examples=(
                _public_example(
                    example_id="workflow-control-plane-mutation",
                    title="Keep Cloud Run infrastructure in Terraform",
                    outcome=ExpectedOutcome.MATCH,
                    path=".github/workflows/deploy.yml",
                    source="jobs:\n  deploy:\n    steps:\n      - run: gcloud run deploy api --image $IMAGE --memory 1Gi\n",
                    expected_count=1,
                ),
                _public_example(
                    example_id="cloud-run-infrastructure-update",
                    title="A Cloud Run configuration update owns infrastructure",
                    outcome=ExpectedOutcome.MATCH,
                    path=".github/workflows/deploy.yml",
                    source="jobs:\n  deploy:\n    steps:\n      - run: gcloud run deploy api --image $IMAGE --memory 1Gi\n",
                    expected_count=1,
                    scenario="cloud-run-release",
                ),
                _public_example(
                    example_id="cloud-run-application-publish",
                    title="CI publishes a Cloud Run application artifact",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path=".github/workflows/deploy.yml",
                    source="jobs:\n  deploy:\n    steps:\n      - run: gcloud run deploy api --image $IMAGE --region us\n",
                    expected_count=0,
                    scenario="cloud-run-release",
                ),
                _public_example(
                    example_id="saved-plan-apply",
                    title="CI applies the reviewed Terraform plan",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path=".github/workflows/deploy.yml",
                    source="jobs:\n  deploy:\n    steps:\n      - run: terraform apply saved.tfplan\n",
                    expected_count=0,
                ),
                _public_example(
                    example_id="worker-resource-create",
                    title="Keep Worker resource creation in Terraform",
                    outcome=ExpectedOutcome.MATCH,
                    path=".github/workflows/deploy.yml",
                    source="jobs:\n  deploy:\n    steps:\n      - run: pnpm exec wrangler d1 create app\n",
                    expected_count=1,
                    scenario="worker-publish",
                ),
                _public_example(
                    example_id="worker-application-publish",
                    title="CI publishes a Worker application artifact",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path=".github/workflows/deploy.yml",
                    source="jobs:\n  deploy:\n    steps:\n      - run: pnpm exec wrangler deploy --tag $GITHUB_SHA\n",
                    expected_count=0,
                    scenario="worker-publish",
                ),
            ),
            limitations=(
                "The bounded scanner reports explicitly recognized commands and deployment Actions; dynamic command construction and unlisted provider surfaces are intentionally unreported.",
                "Wrapper-indirected commands are intentionally unreported; full-tree CI scans wrapper files directly only when they live in an operational root.",
                "Wrangler deploy and versions deploy publish application artifacts and are intentionally not treated as infrastructure mutation; Wrangler resource-creation commands remain reportable.",
                "Cloud Run image/source-only deploys and updates publish application artifacts; configuration, identity, scaling, networking, secret, and other infrastructure flags remain reportable.",
                "Read-only diagnostics such as terraform show, gcloud describe/list, and kubectl get are allowed.",
            ),
        ),
        "workflow-embedded-program": RuleMeta(
            code="SARJ310",
            summary="GitHub workflow run: embeds procedural logic",
            rationale=(
                "Procedural programs embedded in run scalars are difficult to exercise locally and move business or "
                "validation behavior into GitHub-specific YAML instead of a tested repository-owned entrypoint. "
                "Repeating this pattern across component-specific workflows makes the Actions surface noisy. Workflows "
                "should select events, permissions, and stable commands—not implement programs."
            ),
            remediation=(
                "Move the control flow or inline interpreter source into a tested repository-owned script, Make target, "
                "or package command. Invoke that entrypoint from an existing shared workflow when it already owns the "
                "component; add a distinct workflow only for a genuinely distinct trigger or delivery boundary."
            ),
            category=RuleCategory.ARCHITECTURE,
            languages=frozenset({Language.CONFIG}),
            file_patterns=(".github/workflows/*.{yaml,yml}",),
            examples=(
                _public_example(
                    example_id="workflow-inline-program",
                    title="Keep procedural validation out of workflow YAML",
                    outcome=ExpectedOutcome.MATCH,
                    path=".github/workflows/ci.yml",
                    source=(
                        "jobs:\n  test:\n    steps:\n      - run: |\n"
                        "          for package in api worker; do\n"
                        '            make test-package PACKAGE="$package"\n'
                        "          done\n"
                    ),
                    expected_count=1,
                ),
                _public_example(
                    example_id="workflow-repository-entrypoint",
                    title="Call a tested repository-owned entrypoint",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path=".github/workflows/ci.yml",
                    source="jobs:\n  test:\n    steps:\n      - run: make test\n",
                    expected_count=0,
                ),
            ),
            limitations=(
                "Only direct files in .github/workflows are checked; shell control-flow openers, shell function declarations, inline interpreter flags, and interpreter heredocs in run scalars are reported.",
                "Quoted source, including multiline jq filters, is treated as an argument rather than reinterpreted as shell syntax.",
                "Long linear command lists and wrapper-indirected behavior are intentionally unreported because complexity or ownership cannot be inferred reliably from those forms alone.",
                "Workflow topology, ownership, and redundancy require repository review and are not inferred by this semantic rule.",
                "A run scalar containing a recognized SARJ309 infrastructure mutation is left to the more specific deployment-boundary diagnostic.",
            ),
            blocking=False,
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
        "large-shell-program": RuleMeta(
            code="SARJ311",
            summary="shell program contains at least 200 substantive lines",
            rationale=(
                "Large shell programs lack the static type checking and structured interfaces available to application "
                "languages, making orchestration and domain logic harder to evolve safely."
            ),
            remediation=(
                "Move substantive logic into a fully annotated Python CLI or module covered by Ruff, Sarj Python, and "
                "strict BasedPyright; retain only a thin shell adapter when the platform requires one."
            ),
            category=RuleCategory.ARCHITECTURE,
            languages=frozenset({Language.SHELL}),
            file_patterns=("**/*.sh", "**/*.bash", "**/*.zsh", "extensionless shell scripts"),
            examples=(
                _public_example(
                    example_id="large-shell-program",
                    title="A large shell program moves typed logic to Python",
                    outcome=ExpectedOutcome.MATCH,
                    path="scripts/release.sh",
                    source="#!/bin/sh\n" + "run_step\n" * _LARGE_SHELL_SUBSTANTIVE_LINES,
                    expected_count=1,
                ),
                _public_example(
                    example_id="thin-shell-adapter",
                    title="A thin shell adapter remains at the platform boundary",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path="scripts/release.sh",
                    source='#!/bin/sh\nexec python -m tools.release "$@"\n',
                    expected_count=0,
                ),
            ),
            limitations=(
                "Blank lines, comment-only lines, the shebang, and heredoc bodies do not count toward the threshold.",
                "Embedded shell in YAML, Makefiles, and Dockerfiles is intentionally outside this advisory.",
            ),
            blocking=False,
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
        or (path.suffix.casefold() == ".json" and any(part.casefold() in _OPERATIONAL_ROOTS for part in path.parts))
        or shell_dialect(path) is not None
    )


def shell_dialect(path: Path) -> str | None:
    if dialect := _SHELL_DIALECT_BY_SUFFIX.get(path.suffix.casefold()):
        return dialect
    if path.suffix:
        return None
    try:
        with path.open("rb") as stream:
            first_line = stream.readline(256)
    except OSError:
        return None
    match = _SHELL_SHEBANG_RE.match(first_line)
    return None if match is None else match.group("shell").decode("ascii")


def check_paths(
    paths: Sequence[str],
    *,
    root: Path | None = None,
    rule_ids: frozenset[str] | None = None,
) -> list[Finding]:
    base = (root or Path.cwd()).resolve()
    durable_patterns, excluded_patterns = _text_policy(base)
    enabled_codes = None if rule_ids is None else frozenset(REGISTRY[rule_id].code for rule_id in rule_ids)
    deployment_boundary_enabled = rule_ids is None or "declarative-deployment-boundary" in rule_ids
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
        path_findings: list[Finding] = []
        if enabled_codes is None or "SARJ302" in enabled_codes:
            path_findings.extend(_artifact_findings(path, relative, source, durable_patterns))
        if enabled_codes is None or "SARJ309" in enabled_codes:
            path_findings.extend(_declarative_deployment_findings(path, relative, source))
        if enabled_codes is None or "SARJ310" in enabled_codes:
            path_findings.extend(
                _workflow_embedded_program_findings(
                    path,
                    relative,
                    source,
                    suppress_deployment_mutations=deployment_boundary_enabled,
                )
            )
        if enabled_codes is None or "SARJ304" in enabled_codes:
            path_findings.extend(_shell_iac_source_findings(path, relative, source))
        if enabled_codes is None or "SARJ311" in enabled_codes:
            path_findings.extend(_large_shell_program_findings(path, source))
        if enabled_codes is None or "SARJ305" in enabled_codes:
            path_findings.extend(_markdown_hidden_comment_findings(path, source))
        if enabled_codes is None or "SARJ307" in enabled_codes:
            path_findings.extend(_markdown_command_argument_findings(path, relative, source))
        if enabled_codes is None or "SARJ308" in enabled_codes:
            path_findings.extend(_claude_settings_secret_permission_findings(path, relative, source))
        if enabled_codes is None or enabled_codes.intersection({"SARJ300", "SARJ301", "SARJ306"}):
            path_findings.extend(_comment_findings(path, source))
        findings.extend(
            finding
            for finding in path_findings
            if enabled_codes is None or finding.code in enabled_codes
            if not (path.suffix.lower() in {".md", ".mdx"} and _markdown_suppresses_finding(source, finding))
        )
    return sorted(findings, key=lambda item: (str(item.path), item.line, item.code))


class _ShellHeredoc(NamedTuple):
    delimiter: str
    strip_tabs: bool


def _large_shell_program_findings(path: Path, source: str) -> list[Finding]:
    if shell_dialect(path) is None:
        return []
    count = 0
    first_substantive = 1
    pending_heredocs: list[_ShellHeredoc] = []
    for number, line in enumerate(source.splitlines(), start=1):
        if pending_heredocs:
            delimiter, strip_tabs = pending_heredocs[0]
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate == delimiter:
                pending_heredocs.pop(0)
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if count == 0:
            first_substantive = number
        count += 1
        pending_heredocs.extend(_shell_heredoc_delimiters(line))
        if count >= _LARGE_SHELL_SUBSTANTIVE_LINES:
            return [
                Finding(
                    path,
                    first_substantive,
                    "SARJ311",
                    "Large shell program — move substantive logic to a fully annotated Python CLI/module covered by "
                    "Ruff, Sarj Python, and strict BasedPyright; keep only a thin shell adapter.",
                )
            ]
    return []


def _shell_heredoc_delimiters(line: str) -> list[_ShellHeredoc]:
    tokens = _shell_tokens(line)
    delimiters: list[_ShellHeredoc] = []
    index = 0
    while index < len(tokens):
        if tokens[index] != "<<":
            index += 1
            continue
        index += 1
        strip_tabs = index < len(tokens) and tokens[index] == "-"
        if strip_tabs:
            index += 1
        if index < len(tokens) and tokens[index] not in _SHELL_SEPARATORS:
            delimiters.append(_ShellHeredoc(tokens[index], strip_tabs))
        index += 1
    return delimiters


def _declarative_deployment_findings(path: Path, relative: str, source: str) -> list[Finding]:
    pure = PurePosixPath(relative)
    in_workflow = _workflow_path(path, relative)
    in_operational_tree = bool(pure.parts) and pure.parts[0].casefold() in _OPERATIONAL_ROOTS
    if (not in_workflow and not in_operational_tree) or path.suffix.casefold() in {".md", ".mdx"}:
        return []
    for command in _deployment_shell_lines(source, workflow=in_workflow):
        if _shell_line_mutates_control_plane(command.command):
            return [
                Finding(
                    path,
                    command.line,
                    "SARJ309",
                    "Infrastructure mutation is outside Terraform — model it in Terraform and keep CI to plan/apply orchestration.",
                )
            ]
    if in_workflow:
        action = next((item for item in _workflow_actions(source) if _workflow_action_mutates(item)), None)
        if action is not None:
            return [
                Finding(
                    path,
                    action.line,
                    "SARJ309",
                    "Deployment Action mutates infrastructure outside Terraform — model it in Terraform and keep CI to plan/apply orchestration.",
                )
            ]
    if path.suffix.casefold() in {".json", ".jsonc", ".toml", ".yaml", ".yml"}:
        number = _plan_address_allowlist_line(path, source)
        if number is not None:
            return [
                Finding(
                    path,
                    number,
                    "SARJ309",
                    "Plan-address allowlist duplicates Terraform intent — remove the guard and make the plan authoritative.",
                )
            ]
    return []


def _workflow_path(path: Path, relative: str) -> bool:
    pure = PurePosixPath(relative)
    return (
        len(pure.parts) == _WORKFLOW_PATH_PARTS
        and pure.parts[:2] == (".github", "workflows")
        and path.suffix.casefold() in {".yaml", ".yml"}
    )


_WORKFLOW_PATH_PARTS: Final = 3
_WORKFLOW_CONTROL_FLOW_OPENERS: Final = frozenset({"case", "for", "if", "select", "until", "while"})
_INLINE_INTERPRETERS: Final = frozenset(
    {"bash", "dash", "node", "perl", "php", "python", "python2", "python3", "ruby", "sh", "zsh"}
)
_INLINE_INTERPRETER_FLAGS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "bash": frozenset({"-c"}),
        "dash": frozenset({"-c"}),
        "node": frozenset({"--eval", "--print", "-e", "-p"}),
        "perl": frozenset({"-E", "-e"}),
        "php": frozenset({"-r"}),
        "python": frozenset({"-c"}),
        "python2": frozenset({"-c"}),
        "python3": frozenset({"-c"}),
        "ruby": frozenset({"-e"}),
        "sh": frozenset({"-c"}),
        "zsh": frozenset({"-c"}),
    }
)
_INLINE_INTERPRETER_SHORT_SOURCE_OPTIONS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "bash": frozenset({"c"}),
        "dash": frozenset({"c"}),
        "node": frozenset({"e", "p"}),
        "perl": frozenset({"E", "e"}),
        "php": frozenset({"r"}),
        "python": frozenset({"c"}),
        "python2": frozenset({"c"}),
        "python3": frozenset({"c"}),
        "ruby": frozenset({"e"}),
        "sh": frozenset({"c"}),
        "zsh": frozenset({"c"}),
    }
)
_MIN_SHELL_FUNCTION_TOKENS: Final = 3
_HEREDOC_WORD_BREAKS: Final = frozenset(";|&()<>")


def _workflow_embedded_program_findings(
    path: Path,
    relative: str,
    source: str,
    *,
    suppress_deployment_mutations: bool,
) -> list[Finding]:
    if not _workflow_path(path, relative):
        return []
    findings: list[Finding] = []
    for step in _workflow_steps(source):
        logical_lines = _offset_shell_lines(_shell_without_heredoc_bodies(step.command), step.line)
        if suppress_deployment_mutations and any(
            _shell_line_mutates_control_plane(item.command) for item in logical_lines
        ):
            continue
        if _workflow_run_embeds_program(step.command):
            findings.append(
                Finding(
                    path,
                    step.line,
                    "SARJ310",
                    "Workflow run: embeds procedural logic — move it into a locally tested repository entrypoint and keep GitHub Actions to orchestration.",
                )
            )
    return findings


def _workflow_run_embeds_program(source: str) -> bool:
    shell_source = _shell_without_quoted_content(_shell_without_heredoc_bodies(source))
    for logical_line in _shell_logical_lines(shell_source):
        tokens = _shell_tokens(logical_line.command)
        if not tokens:
            continue
        segments = _shell_segments(tokens)
        for segment in segments:
            if segment.tokens and segment.tokens[0] in _WORKFLOW_CONTROL_FLOW_OPENERS:
                return True
            argv = _command_argv(segment.tokens)
            if not argv:
                continue
            executable = _shell_command(argv[0])
            if _shell_function_declaration(segment.tokens):
                return True
            if executable in _INLINE_INTERPRETERS and _interpreter_embeds_source(executable, argv):
                return True
    return False


def _shell_without_quoted_content(source: str) -> str:
    masked: list[str] = []
    quote: str | None = None
    escaped = False
    comment = False
    for index, character in enumerate(source):
        if character == "\n":
            masked.append(character)
            comment = False
            escaped = False
            continue
        if comment:
            masked.append(" ")
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif quote == '"' and character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            masked.append(" ")
            continue
        if character in {"'", '"'}:
            quote = character
            masked.append(" ")
            continue
        if character == "#" and (index == 0 or source[index - 1].isspace() or source[index - 1] in ";|&("):
            comment = True
            masked.append(" ")
            continue
        masked.append(character)
    return "".join(masked)


def _interpreter_embeds_source(executable: str, argv: Sequence[str]) -> bool:
    flags = _INLINE_INTERPRETER_FLAGS[executable]
    short_source_options = _INLINE_INTERPRETER_SHORT_SOURCE_OPTIONS[executable]
    for argument in argv[1:]:
        if argument in flags or any(argument.startswith(f"{flag}=") for flag in flags if flag.startswith("--")):
            return True
        if argument in {"<<", "<<-"}:
            return True
        if argument == "--":
            continue
        if argument.startswith("-") and not argument.startswith("--") and argument != "-":
            if short_source_options.intersection(argument[1:]):
                return True
            continue
        if argument == "-" or argument.startswith("--"):
            continue
        return False
    return False


def _shell_without_heredoc_bodies(source: str) -> str:
    rendered: list[str] = []
    pending: list[_HeredocSpec] = []
    for line in source.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending = line[len(content) :]
        if pending:
            current = pending[0]
            candidate = content.lstrip("\t") if current.strip_tabs else content
            rendered.append(" " * len(content) + ending)
            if candidate == current.delimiter:
                pending.pop(0)
            continue
        rendered.append(line)
        pending.extend(_shell_heredoc_specs(content))
    return "".join(rendered)


def _shell_heredoc_specs(line: str) -> list[_HeredocSpec]:
    specs: list[_HeredocSpec] = []
    index = 0
    quote: str | None = None
    while index < len(line):
        character = line[index]
        if quote is not None:
            if character == quote:
                quote = None
            elif character == "\\" and quote == '"' and index + 1 < len(line):
                index += 1
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character == "\\" and index + 1 < len(line):
            index += 2
            continue
        if character == "#" and (index == 0 or line[index - 1].isspace() or line[index - 1] in ";|&("):
            break
        if not line.startswith("<<", index) or line.startswith("<<<", index) or (index > 0 and line[index - 1] == "<"):
            index += 1
            continue

        cursor = index + 2
        strip_tabs = cursor < len(line) and line[cursor] == "-"
        if strip_tabs:
            cursor += 1
        while cursor < len(line) and line[cursor] in {" ", "\t"}:
            cursor += 1

        delimiter: list[str] = []
        word_started = False
        word_quote: str | None = None
        while cursor < len(line):
            character = line[cursor]
            if word_quote is not None:
                word_started = True
                if character == word_quote:
                    word_quote = None
                elif character == "\\" and word_quote == '"' and cursor + 1 < len(line):
                    cursor += 1
                    delimiter.append(line[cursor])
                else:
                    delimiter.append(character)
                cursor += 1
                continue
            if character in {"'", '"'}:
                word_started = True
                word_quote = character
                cursor += 1
                continue
            if character == "\\" and cursor + 1 < len(line):
                word_started = True
                cursor += 1
                delimiter.append(line[cursor])
                cursor += 1
                continue
            if character.isspace() or character in _HEREDOC_WORD_BREAKS:
                break
            word_started = True
            delimiter.append(character)
            cursor += 1

        if word_started and word_quote is None:
            specs.append(_HeredocSpec("".join(delimiter), strip_tabs))
        index = max(cursor, index + 2)
    return specs


def _shell_function_declaration(tokens: Sequence[str]) -> bool:
    if len(tokens) >= _MIN_SHELL_FUNCTION_TOKENS and tokens[1:3] == ["()", "{"]:
        return re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tokens[0]) is not None
    return (
        len(tokens) >= _MIN_SHELL_FUNCTION_TOKENS
        and tokens[0] == "function"
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tokens[1]) is not None
        and (tokens[2] == "{" or tokens[2:4] == ["()", "{"])
    )


def _deployment_shell_lines(source: str, *, workflow: bool) -> list[_ShellLogicalLine]:
    return _workflow_run_lines(source) if workflow else _shell_logical_lines(source)


def _workflow_run_lines(source: str) -> list[_ShellLogicalLine]:
    commands: list[_ShellLogicalLine] = []
    for step in _workflow_steps(source):
        commands.extend(_offset_shell_lines(_shell_without_heredoc_bodies(step.command), step.line))
    return commands


def _workflow_actions(source: str) -> list[_WorkflowAction]:
    actions: list[_WorkflowAction] = []
    for step in _workflow_step_nodes(source):
        uses = _mapping_value(step, "uses")
        if not isinstance(uses, ScalarNode):
            continue
        command = _scalar_value(_mapping_value(_mapping_value(step, "with"), "command"))
        actions.append(_WorkflowAction(uses.start_mark.line + 1, _scalar_value(uses), command))
    return actions


def _workflow_document(source: str) -> MappingNode | None:
    try:
        document: object = yaml.compose(source)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    except yaml.YAMLError:
        return None
    return document if isinstance(document, MappingNode) else None


def _mapping_value(node: Node | None, key: str) -> Node | None:
    if not isinstance(node, MappingNode):
        return None
    pairs: list[tuple[Node, Node]] = node.value  # pyright: ignore[reportAny]
    return next(
        (value for candidate, value in pairs if isinstance(candidate, ScalarNode) and _scalar_value(candidate) == key),
        None,
    )


def _scalar_value(node: Node | None) -> str:
    if not isinstance(node, ScalarNode):
        return ""
    value: object = node.value  # pyright: ignore[reportAny]
    return value if isinstance(value, str) else ""


def _workflow_step_nodes(source: str) -> list[MappingNode]:
    document = _workflow_document(source)
    if document is None:
        return []
    steps: list[MappingNode] = []
    top_level_steps = _mapping_value(document, "steps")
    if isinstance(top_level_steps, SequenceNode):
        children: list[Node] = top_level_steps.value  # pyright: ignore[reportAny]
        steps.extend(step for step in children if isinstance(step, MappingNode))
    jobs = _mapping_value(document, "jobs")
    if not isinstance(jobs, MappingNode):
        return steps
    job_items: list[tuple[Node, Node]] = jobs.value  # pyright: ignore[reportAny]
    for _job_name, job in job_items:
        if not isinstance(job, MappingNode):
            continue
        sequence = _mapping_value(job, "steps")
        if not isinstance(sequence, SequenceNode):
            continue
        children = sequence.value  # pyright: ignore[reportAny]
        steps.extend(step for step in children if isinstance(step, MappingNode))
    unique: list[MappingNode] = []
    seen: set[int] = set()
    for step in steps:
        identity = id(step)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(step)
    return unique


def _workflow_steps(source: str) -> list[_ShellLogicalLine]:
    commands: list[_ShellLogicalLine] = []
    for step in _workflow_step_nodes(source):
        run = _mapping_value(step, "run")
        if not isinstance(run, ScalarNode):
            continue
        commands.append(_ShellLogicalLine(run.start_mark.line + 1, _scalar_value(run)))
    return commands


def _workflow_action_mutates(action: _WorkflowAction) -> bool:
    identifier = action.uses.partition("@")[0].casefold()
    if identifier == "google-github-actions/deploy-cloud-functions":
        return True
    return identifier == "cloudflare/wrangler-action" and _shell_line_mutates_control_plane(
        f"wrangler {action.command}"
    )


def _plan_address_allowlist_line(path: Path, source: str) -> int | None:
    suffix = path.suffix.casefold()
    if suffix in {".yaml", ".yml"}:
        return _yaml_plan_address_allowlist_line(_workflow_document(source))
    document = _structured_config_document(suffix, source)
    if document is None or not _contains_plan_address_allowlist_key(document):
        return None
    return _config_key_line(source)


def _structured_config_document(suffix: str, source: str) -> object | None:
    try:
        if suffix in {".json", ".jsonc"}:
            payload = _strip_jsonc_comments(source) if suffix == ".jsonc" else source
            if suffix == ".jsonc":
                payload = re.sub(r",(?=\s*[}\]])", "", payload)
            return json.loads(payload)  # pyright: ignore[reportAny]
        if suffix == ".toml":
            return tomllib.loads(source)
    except json.JSONDecodeError, tomllib.TOMLDecodeError:
        return None
    return None


def _strip_jsonc_comments(source: str) -> str:
    result = list(source)
    index = 0
    quote = False
    while index < len(source):
        if source[index] == '"' and (index == 0 or source[index - 1] != "\\"):
            quote = not quote
            index += 1
            continue
        if quote or source[index : index + 2] not in {"//", "/*"}:
            index += 1
            continue
        closing = source.find("\n", index + 2) if source[index : index + 2] == "//" else source.find("*/", index + 2)
        end = len(source) if closing < 0 else closing + (0 if source[index : index + 2] == "//" else 2)
        for offset in range(index, end):
            if result[offset] not in {"\n", "\r"}:
                result[offset] = " "
        index = end
    return "".join(result)


def _yaml_plan_address_allowlist_line(node: Node | None) -> int | None:
    match node:
        case MappingNode():
            mapping_items: list[tuple[Node, Node]] = node.value  # pyright: ignore[reportAny]
            for key, value in mapping_items:
                if isinstance(key, ScalarNode) and _is_plan_address_allowlist_key(_scalar_value(key)):
                    return key.start_mark.line + 1
                if (nested := _yaml_plan_address_allowlist_line(value)) is not None:
                    return nested
        case SequenceNode():
            sequence_items: list[Node] = node.value  # pyright: ignore[reportAny]
            for value in sequence_items:
                if (nested := _yaml_plan_address_allowlist_line(value)) is not None:
                    return nested
        case _:
            pass
    return None


def _contains_plan_address_allowlist_key(value: object) -> bool:
    match value:
        case dict():
            mapping: dict[object, object] = value  # pyright: ignore[reportUnknownVariableType]
            return any(
                (isinstance(key, str) and _is_plan_address_allowlist_key(key))
                or _contains_plan_address_allowlist_key(item)
                for key, item in mapping.items()
            )
        case list():
            sequence: list[object] = value  # pyright: ignore[reportUnknownVariableType]
            return any(_contains_plan_address_allowlist_key(item) for item in sequence)
        case _:
            return False


def _is_plan_address_allowlist_key(value: str) -> bool:
    return _config_words(value) == ("allowed", "change", "addresses")


def _config_key_line(source: str) -> int:
    return next(
        (
            number
            for number, line in enumerate(source.splitlines(), start=1)
            if any(_is_plan_address_allowlist_key(match.group("key")) for match in _CONFIG_KEY_RE.finditer(line))
        ),
        1,
    )


def _offset_shell_lines(source: str, first_line: int) -> list[_ShellLogicalLine]:
    return [_ShellLogicalLine(first_line + item.line - 1, item.command) for item in _shell_logical_lines(source)]


def _shell_line_mutates_control_plane(command: str) -> bool:
    return any(_command_mutates_control_plane(segment.tokens) for segment in _shell_segments(_shell_tokens(command)))


def _command_mutates_control_plane(tokens: Sequence[str]) -> bool:
    argv = _command_argv(tokens)
    if not argv:
        return False
    executable = _shell_command(argv[0])
    arguments = [item.casefold() for item in argv[1:]]
    if executable in {"npm", "npx", "pnpm", "yarn"}:
        nested = _drop_leading_cli_options(argv[1:], _PACKAGE_EXEC_VALUE_OPTIONS)
        if nested[:1] == ["exec"]:
            nested = nested[1:]
        if nested and (executable == "npx" or _shell_command(nested[0]) == "wrangler"):
            return _command_mutates_control_plane(nested)
    if executable == "gcloud":
        return _gcloud_mutates(arguments)
    if executable == "kubectl":
        return _kubectl_mutates(arguments)
    if executable in {"terraform", "tofu", "opentofu"}:
        return _terraform_mutates(arguments)
    if executable == "wrangler":
        return _wrangler_mutates(arguments)
    return False


def _command_argv(tokens: Sequence[str]) -> list[str]:
    argv = list(tokens)
    while argv and argv[0] in {"(", "[", "[["}:
        argv.pop(0)
    while argv and argv[0].casefold() in _SHELL_CONTROL_PREFIXES:
        prefix = argv.pop(0).casefold()
        if prefix == "command":
            if argv[:1] and argv[0] in {"-v", "-V"}:
                return []
            argv = _drop_leading_cli_options(argv, frozenset())
        elif prefix == "time":
            argv = _drop_leading_cli_options(argv, frozenset({"--format", "-f", "-o"}))
    while argv and _shell_assignment_token(argv[0]):
        argv.pop(0)
    if argv and _shell_command(argv[0].lstrip("@+-")) == "env":
        argv = _drop_env_prefix(argv[1:])
        while argv and _shell_assignment_token(argv[0]):
            argv.pop(0)
    if argv and _shell_command(argv[0].lstrip("@+-")) == "sudo":
        argv = _drop_leading_cli_options(
            argv[1:], frozenset({"--chdir", "--group", "--host", "--prompt", "--user", "-C", "-g", "-h", "-p", "-u"})
        )
    if argv:
        argv[0] = argv[0].lstrip("@+-")
    return argv


def _shell_assignment_token(token: str) -> bool:
    return re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token) is not None


def _drop_env_prefix(arguments: Sequence[str]) -> list[str]:
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            return list(arguments[index + 1 :])
        option, separator, _value = argument.partition("=")
        if option in _ENV_VALUE_OPTIONS:
            index += 1 if separator else 2
            continue
        if argument.startswith("-") or _shell_assignment_token(argument):
            index += 1
            continue
        return list(arguments[index:])
    return []


def _drop_leading_cli_options(arguments: Sequence[str], value_options: frozenset[str]) -> list[str]:
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            return list(arguments[index + 1 :])
        if not argument.startswith("-") or argument == "-":
            return list(arguments[index:])
        option, separator, _value = argument.partition("=")
        index += 1
        if option in value_options and not separator:
            index += 1
    return []


def _drop_cli_options(arguments: Sequence[str], value_options: frozenset[str]) -> list[str]:
    remaining: list[str] = []
    consume = False
    passthrough = False
    for argument in arguments:
        if passthrough:
            remaining.append(argument)
            continue
        if consume:
            consume = False
            continue
        option, separator, _value = argument.partition("=")
        if argument == "--":
            passthrough = True
            continue
        if option in value_options:
            consume = not separator
            continue
        if argument.startswith("-"):
            continue
        remaining.append(argument)
    return remaining


def _gcloud_mutates(arguments: Sequence[str]) -> bool:
    command = _drop_leading_cli_options(_collapse_github_expressions(arguments), _GCLOUD_GLOBAL_VALUE_OPTIONS)
    if command and command[0] in _GCLOUD_RELEASE_TRACKS:
        command = command[1:]
    if any(tuple(command[: len(prefix)]) == prefix for prefix in _GCLOUD_RUN_RELEASE_COMMANDS):
        return not _gcloud_run_is_application_publish(command)
    return _matches_prefix(command, _GCLOUD_MUTATIONS)


def _gcloud_run_is_application_publish(command: Sequence[str]) -> bool:
    prefix = next(
        (candidate for candidate in _GCLOUD_RUN_RELEASE_COMMANDS if tuple(command[: len(candidate)]) == candidate),
        None,
    )
    if prefix is None:
        return False
    arguments = command[len(prefix) :]
    artifact_selected = False
    resource_seen = False
    consume_value = False
    for argument in arguments:
        if consume_value:
            consume_value = False
            continue
        option, separator, _value = argument.partition("=")
        if option in _GCLOUD_RUN_ARTIFACT_OPTIONS:
            artifact_selected = True
        if option in _GCLOUD_RUN_RELEASE_VALUE_OPTIONS:
            consume_value = not separator
            continue
        if option in _GCLOUD_RUN_RELEASE_BOOLEAN_OPTIONS:
            continue
        if argument.startswith("-"):
            return False
        if resource_seen:
            return False
        resource_seen = True
    return artifact_selected and resource_seen and not consume_value


def _collapse_github_expressions(arguments: Sequence[str]) -> list[str]:
    collapsed: list[str] = []
    expression: list[str] = []
    for argument in arguments:
        if expression:
            expression.append(argument)
            if "}}" in argument:
                collapsed.append("".join(expression))
                expression = []
            continue
        if "${{" in argument and "}}" not in argument:
            expression = [argument]
            continue
        collapsed.append(argument)
    collapsed.extend(expression)
    return collapsed


def _kubectl_mutates(arguments: Sequence[str]) -> bool:
    command = _drop_cli_options(arguments, _KUBECTL_GLOBAL_VALUE_OPTIONS)
    if not command:
        return False
    if command[0] in _KUBECTL_MUTATIONS:
        return True
    return _matches_prefix(command, _KUBECTL_MUTATION_PREFIXES)


def _terraform_mutates(arguments: Sequence[str]) -> bool:
    command = _drop_cli_options(arguments, frozenset({"-chdir"}))
    if command[:1] and command[0] in _TERRAFORM_DIRECT_MUTATIONS:
        return True
    action = command[1] if command[:1] == ["state"] and command[1:] else None
    return action in _TERRAFORM_STATE_MUTATIONS


def _wrangler_mutates(arguments: Sequence[str]) -> bool:
    if "--dry-run" in arguments:
        return False
    command = _drop_cli_options(arguments, frozenset({"--config", "--cwd", "--env"}))
    return _matches_prefix(command, _WRANGLER_MUTATIONS)


def _matches_prefix(arguments: Sequence[str], patterns: frozenset[tuple[str, ...]]) -> bool:
    return any(tuple(arguments[: len(pattern)]) == pattern for pattern in patterns)


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
    for logical_line in _shell_logical_lines(source):
        number = logical_line.line
        tokens = _shell_tokens(logical_line.command)
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
                "Unexplained inactive configuration — delete it, or explain the supported default or optional override.",
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
    if path.suffix.lower() not in {".yaml", ".yml", ".toml", ".jsonc"}:
        return set()
    literal_lines = _config_literal_lines(path, lines)
    leaders: set[int] = set()
    index = 0
    while index < len(lines):
        first = _standalone_comment(path, lines[index])
        if index in literal_lines or first is None or not first.body:
            index += 1
            continue
        start = index
        run: list[tuple[int, str]] = []
        while (
            index < len(lines)
            and index not in literal_lines
            and (parsed := _standalone_comment(path, lines[index])) is not None
            and parsed.indent == first.indent
            and parsed.body
        ):
            run.append((index + 1, parsed.body))
            index += 1
        suppressions = {
            code.upper()
            for _line, body in run
            if (match := _SARJ_SUPPRESSION_RE.match(body)) is not None
            for code in (item.strip() for item in match.group("codes").split(","))
        }
        if "SARJ301" in suppressions:
            continue
        effective = [
            (line, body)
            for line, body in run
            if _SARJ_SUPPRESSION_RE.match(body) is None and not _CONFIG_TOOL_DIRECTIVE_RE.match(body)
        ]
        if not effective:
            continue
        if any(_PROTECTED_RE.search(body) for _line, body in effective):
            continue
        shaped = [line for line, body in effective if _commented_config_key(path, body) is not None]
        if len(shaped) != len(effective):
            continue
        shaped_key = next((_commented_config_key(path, body) for line, body in effective if line in shaped), None)
        adjacent = (
            any(
                0 <= neighbor < len(lines)
                and len(lines[neighbor]) - len(lines[neighbor].lstrip()) == first.indent
                and _standalone_comment(path, lines[neighbor]) is None
                and _commented_config_key(path, lines[neighbor].strip()) == shaped_key
                for neighbor in (start - 1, index)
            )
            if len(shaped) == 1
            else False
        )
        if len(shaped) >= _COMMENTED_CONFIG_RUN_MIN or adjacent:
            leaders.add(shaped[0])
    return leaders


_CONFIG_TOOL_DIRECTIVE_RE = re.compile(
    r"^(?:!|shellcheck\b|yamllint\b|prettier\b|eslint\b|renovate\b|dependabot\b)", re.IGNORECASE
)
_TOML_STRING_OR_COMMENT_RE = re.compile(
    r"#[^\n]*|\"\"\"(?:\\.|(?!\"\"\").)*\"\"\"|'''(?:(?!''').)*'''|\"(?:\\.|[^\"\\])*\"|'[^'\n]*'",
    re.DOTALL,
)


def _config_literal_lines(path: Path, lines: list[str]) -> set[int]:
    source = "\n".join(lines)
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            tokens: list[object] = list(yaml.scan(source))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        except yaml.YAMLError:
            return set(range(len(lines)))
        literal_lines: set[int] = set()
        for token in tokens:
            if not isinstance(token, ScalarToken):
                continue
            start: Mark = token.start_mark  # pyright: ignore[reportAny]
            end: Mark = token.end_mark  # pyright: ignore[reportAny]
            if end.line > start.line:
                literal_lines.update(range(start.line, end.line + (end.column > 0)))
        return literal_lines
    if path.suffix.lower() != ".toml":
        return set()
    try:
        tomllib.loads(source)
    except tomllib.TOMLDecodeError:
        return set(range(len(lines)))
    return {
        line
        for match in _TOML_STRING_OR_COMMENT_RE.finditer(source)
        if not match.group().startswith("#") and "\n" in match.group()
        for line in range(source.count("\n", 0, match.start()), source.count("\n", 0, match.end()) + 1)
    }


def _standalone_comment(path: Path, line: str) -> _StandaloneComment | None:
    stripped = line.lstrip()
    if path.suffix.lower() == ".jsonc":
        if stripped == "*/":
            return _StandaloneComment(len(line) - len(stripped), "")
        for marker in ("//", "/*", "*"):
            if stripped.startswith(marker):
                body = stripped.removeprefix(marker).removesuffix("*/").strip()
                return _StandaloneComment(len(line) - len(stripped), body)
        return None
    if not stripped.startswith("#"):
        return None
    return _StandaloneComment(len(line) - len(stripped), stripped.removeprefix("#").strip())


def _commented_config_key(path: Path, body: str) -> str | None:
    if path.suffix.lower() == ".toml":
        try:
            parsed: dict[str, object] = tomllib.loads(body)
        except tomllib.TOMLDecodeError:
            return None
        keys: list[str] = []
        while len(parsed) == 1:
            key, value = next(iter(parsed.items()))
            keys.append(key)
            parsed = as_table(value)
        return json.dumps(keys) if keys else None
    if path.suffix.lower() == ".jsonc":
        try:
            parsed_json = as_table(_structured_config_document(".json", "{" + body.rstrip(",") + "}"))
        except json.JSONDecodeError:
            return None
        return next(iter(parsed_json)) if len(parsed_json) == 1 else None
    if re.match(r"^(?:Optional|Required|Defaults?|Examples?|Note|Usage|Format|Type):", body):
        return None
    if not re.match(r"^(?:[A-Za-z_][\w.-]*|\"[^\"]+\"|'[^']+'):\s+\S", body):
        return None
    node = _workflow_document(body)
    if node is None:
        return None
    pairs: list[tuple[Node, Node]] = node.value  # pyright: ignore[reportAny]
    if len(pairs) != 1:
        return None
    key, value = pairs[0]
    if not isinstance(key, ScalarNode) or not isinstance(value, ScalarNode):
        return None
    return _scalar_value(key)


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
