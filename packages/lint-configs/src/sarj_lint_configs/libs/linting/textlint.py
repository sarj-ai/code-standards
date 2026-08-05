"""Deterministic comment and repository-noise checks for text/config files."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
import re
import sys
import tomllib
from typing import TYPE_CHECKING, Final

from sarj_lint_configs.libs.adoption.manifest import as_table, list_field, table_field


if TYPE_CHECKING:
    from collections.abc import Sequence


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
    """Stable ownership metadata for the shared SARJ code namespace."""

    code: str
    description: str
    blocking: bool = True


REGISTRY: Final = {
    "config-comment-wall": RuleMeta("SARJ300", "four-entry config narration wall with 75% weak restatements"),
    "commented-out-config": RuleMeta("SARJ301", "commented-out config syntax"),
    # New rules spend one release as visible, non-blocking findings.
    "ephemeral-ai-artifact": RuleMeta(
        "SARJ302",
        "AI execution brief, audit report, or change diary",
        blocking=False,
    ),
}

_META_BY_CODE: Final = {meta.code: meta for meta in REGISTRY.values()}


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
        findings.extend(_artifact_findings(path, relative, source, durable_patterns))
        findings.extend(_comment_findings(path, source))
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
    source_lines = source.splitlines()
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
    if _large_artifact(source, path, source_lines):
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
        tuple(item for item in configured_durable if isinstance(item, str))
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
        if any(_DIRECTIVE_RE.match(body) for _line, body in run):
            continue
        shaped = [line for line, body in run if _looks_commented_config(path, body)]
        if len(shaped) >= _COMMENTED_CONFIG_RUN_MIN and len(shaped) / len(run) >= _COMMENTED_CONFIG_RUN_RATIO:
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
