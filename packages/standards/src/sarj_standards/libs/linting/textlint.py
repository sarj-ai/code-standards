"""Deterministic comment and repository-noise checks for text/config files."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
import re
import shlex
import sys
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

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
_WORKFLOW_ACTION_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<value>[^\s#]+)", re.IGNORECASE)
_FULL_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_FULL_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$", re.IGNORECASE)
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


@dataclass(frozen=True)
class Finding:
    """One stable, editor-friendly text diagnostic."""

    path: Path
    line: int
    code: str
    message: str

    def render(self) -> str:
        """Render in the same path/line/column shape as the sibling linters."""
        rollout = " warning:" if not _META_BY_CODE[self.code].blocking else ""
        return f"{self.path}:{self.line}:1: {self.code}{rollout} {self.message}"


@dataclass(frozen=True)
class RuleMeta:
    """Source-owned behavior, documentation, and compatibility metadata."""

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
        """Adapt this text-native record to the engine-neutral catalog contract."""
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
    """Opt one reviewed single-file example into generated public documentation."""
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
            remediation="Name configuration entries clearly and keep comments only for constraints or rationale.",
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
        # New rules spend one release as visible, non-blocking findings.
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
                    source="# Operations\n\nRun `sarj-standards check` before merging.\n",
                    expected_count=0,
                ),
            ),
            limitations=(
                "Short artifacts with neutral names and no execution-log headings are intentionally not inferred from prose alone.",
            ),
            blocking=False,
        ),
        # Supply-chain rules start as warnings so existing consumers can ratchet deliberately.
        "unpinned-github-action": RuleMeta(
            code="SARJ303",
            summary="remote GitHub Action or container action without an immutable digest",
            rationale="Mutable action tags can resolve to different code without a reviewed repository change.",
            remediation="Pin repository actions to a full commit SHA and container actions to a sha256 digest.",
            category=RuleCategory.SECURITY,
            languages=frozenset({Language.CONFIG}),
            file_patterns=(".github/workflows/**/*.yaml", ".github/workflows/**/*.yml"),
            examples=(
                _public_example(
                    example_id="mutable-action-tag",
                    title="A version tag is mutable",
                    outcome=ExpectedOutcome.MATCH,
                    path=".github/workflows/ci.yml",
                    source="jobs:\n  test:\n    steps:\n      - uses: actions/checkout@v4\n",
                    expected_count=1,
                ),
                _public_example(
                    example_id="immutable-action-commit",
                    title="A full action commit SHA is immutable",
                    outcome=ExpectedOutcome.NO_MATCH,
                    path=".github/workflows/ci.yml",
                    source="jobs:\n  test:\n    steps:\n"
                    "      - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567\n",
                    expected_count=0,
                ),
            ),
            limitations=(
                "Only remote uses entries in .github/workflows YAML files are checked; local actions are excluded.",
            ),
            references=(
                "https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions",
            ),
            blocking=False,
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
            blocking=False,
        ),
    }
)

_META_BY_CODE: Final[Mapping[str, RuleMeta]] = MappingProxyType({meta.code: meta for meta in REGISTRY.values()})


def is_text_path(path: Path) -> bool:
    """Return whether the cross-file checker owns this path."""
    name = path.name.lower()
    return (
        path.suffix.lower() in _TEXT_SUFFIXES
        or name in _TEXT_NAMES
        or name == ".env"
        or name.startswith(("dockerfile.", ".env."))
    )


def check_paths(paths: Sequence[str], *, root: Path | None = None) -> list[Finding]:
    """Check routed files, returning findings in stable path/line order."""
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
            *_workflow_action_findings(path, relative, source),
            *_artifact_findings(path, relative, source, durable_patterns),
            *_shell_iac_source_findings(path, relative, source),
            *_comment_findings(path, source),
        ]
        suppressed: frozenset[str] = (
            _markdown_suppressions(source) if path.suffix.lower() in {".md", ".mdx"} else frozenset()
        )
        findings.extend(finding for finding in path_findings if finding.code not in suppressed)
    return sorted(findings, key=lambda item: (str(item.path), item.line, item.code))


def run(paths: Sequence[str]) -> int:
    """Print all text findings and return a conventional lint status."""
    findings = check_paths(paths)
    for finding in findings:
        _ = sys.stdout.write(f"{finding.render()}\n")
    return 1 if any(_META_BY_CODE[finding.code].blocking for finding in findings) else 0


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _markdown_suppressions(source: str) -> frozenset[str]:
    prose = "\n".join(_markdown_prose_lines(source))
    return frozenset(
        code.strip().upper()
        for match in _MARKDOWN_SUPPRESSION_RE.finditer(prose)
        for code in match.group("codes").split(",")
    )


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
    """Find direct and local-flow IaC text assertions in shell test programs."""
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


def _shell_logical_lines(source: str) -> list[tuple[int, str]]:
    """Join ordinary backslash continuations while retaining the first source line."""
    logical: list[tuple[int, str]] = []
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
        logical.append((start, " ".join(pending)))
        pending = []
    if pending:
        logical.append((start, " ".join(pending)))
    return logical


def _shell_segments(tokens: Sequence[str]) -> list[tuple[str | None, list[str]]]:
    segments: list[tuple[str | None, list[str]]] = []
    current: list[str] = []
    separator: str | None = None
    for token in tokens:
        if token in _SHELL_SEPARATORS:
            if current:
                segments.append((separator, current))
                current = []
            separator = token
            continue
        current.append(token)
    if current:
        segments.append((separator, current))
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


def _shell_operands(
    tokens: Sequence[str], value_options: frozenset[str], pattern_options: set[str]
) -> tuple[list[str], bool]:
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
    return operands, explicit_pattern


def _shell_reads_iac(tokens: Sequence[str], path_names: set[str]) -> bool:
    if not tokens:
        return False
    command = _shell_command(tokens[0])
    if command not in _SHELL_SOURCE_READ_COMMANDS:
        return False
    return _shell_has_iac_path(tokens[1:], path_names)


def _shell_embeds_iac_read(tokens: Sequence[str], path_names: set[str]) -> bool:
    """Recognize a simple ``$(cat source.tf)`` inside a shell test predicate."""
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


def _workflow_action_findings(path: Path, relative: str, source: str) -> list[Finding]:
    """Reject mutable remote refs in GitHub workflow ``uses`` entries."""
    if not relative.startswith(".github/workflows/") or path.suffix.lower() not in {".yaml", ".yml"}:
        return []
    lines = source.splitlines()
    findings: list[Finding] = []
    for index, line in enumerate(lines):
        match = _WORKFLOW_ACTION_RE.match(line)
        if match is None:
            continue
        indent = len(line) - len(line.lstrip())
        if _inside_yaml_block_scalar(lines, index, indent) or _suppresses_previous_line(lines, index, "SARJ303"):
            continue
        value = match.group("value").strip("\"'")
        if value.startswith("./"):
            continue
        if value.startswith("docker://"):
            digest = value.removeprefix("docker://").partition("@")[2]
            pinned = bool(_FULL_IMAGE_DIGEST_RE.fullmatch(digest))
        else:
            reference = value.rpartition("@")[2]
            pinned = bool(_FULL_GIT_SHA_RE.fullmatch(reference))
        if not pinned:
            findings.append(
                Finding(
                    path,
                    index + 1,
                    "SARJ303",
                    "Remote action uses a mutable ref — pin it to a full commit SHA or container sha256 digest.",
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


def _markdown_prose_lines(source: str) -> list[str]:
    """Blank fenced examples while preserving line numbers for diagnostics."""
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
    """Stop counting once the large-artifact threshold is known to be met."""
    return next((True for index, _match in enumerate(_WORD_RE.finditer(source), start=1) if index >= minimum), False)


def _text_policy(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Load the text policy once per run instead of parsing its manifest twice."""
    manifest = root / ".sarj-standards.toml"
    if not manifest.is_file():
        return _DURABLE_MARKDOWN, ()
    try:
        parsed: object = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return _DURABLE_MARKDOWN, ()
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
    return durable, excluded


def _comment_findings(path: Path, source: str) -> list[Finding]:
    if path.suffix.lower() in {".md", ".mdx"}:
        return []
    lines = source.splitlines()
    attached: list[tuple[int, int, bool]] = []
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
        next_index = _next_content_line(lines, index + 1)
        if next_index is None:
            continue
        next_line = lines[next_index]
        if len(next_line) - len(next_line.lstrip()) != indent:
            continue
        attached.append((index + 1, indent, False if protected else _weak_narration(body, next_line)))

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
                    f"Config comment wall ({len(weak)} narrated entries) — name jobs, steps, targets, and keys clearly; keep only constraints or rationale.",
                )
            )
    return findings


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


def _standalone_comment(path: Path, line: str) -> tuple[int, str] | None:
    stripped = line.lstrip()
    if path.suffix.lower() == ".jsonc":
        for marker in ("//", "/*", "*"):
            if stripped.startswith(marker):
                body = stripped.removeprefix(marker).removesuffix("*/").strip()
                return len(line) - len(stripped), body
        return None
    if not stripped.startswith("#"):
        return None
    return len(line) - len(stripped), stripped.removeprefix("#").strip()


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
    attached: list[tuple[int, int, bool]],
) -> list[list[tuple[int, int, bool]]]:
    groups: list[list[tuple[int, int, bool]]] = []
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
    """Extract typed word matches from regular-expression results."""
    words: list[str] = []
    for match in _WORD_RE.finditer(text):
        expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", match.group(0))
        words.extend(part for part in re.split(r"[-_]+", expanded) if part)
    return words


def _normalize_word(word: str) -> str:
    return word.lower().replace("-", "_")
