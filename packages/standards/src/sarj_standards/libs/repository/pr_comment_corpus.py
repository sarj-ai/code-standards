"""Build a private comment corpus from merged pull-request history.

The raw corpus deliberately has no stdout representation: callers may write it
only to owner-only files.  ``CollectionSummary.render`` is the safe, aggregate
view intended for logs and reports.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed gh/git argv, never a shell.
import tempfile
import tokenize
from typing import Final, Protocol, TypedDict, TypeIs, override


_PYTHON_SUFFIXES: Final = frozenset({".py", ".pyi"})
_JAVASCRIPT_SUFFIXES: Final = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"})
_HUNK_RE: Final = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_SHA_RE: Final = re.compile(r"^[0-9a-fA-F]{40,64}$")
_SAFE_NAME_RE: Final = re.compile(r"[^A-Za-z0-9_.-]+")
_WRITE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
_DIRECTIVE_RE: Final = re.compile(
    r"^(?:#!|coding[=:]|(?:noqa|type:\s*ignore|pyright:|mypy:|ruff:|eslint(?:-|\s)|istanbul\s|c8\s|prettier-ignore|"
    r"ts-(?:ignore|expect-error|nocheck|check)|sarj-noqa)\b)",
    re.IGNORECASE,
)
_LICENSE_RE: Final = re.compile(r"\b(?:copyright|spdx-license-identifier|licensed under)\b", re.IGNORECASE)
_GENERATED_RE: Final = re.compile(
    r"(?:@generated\b|\bauto[- ]?generated\b|\bgenerated (?:file|code)\b|\bdo not edit\b)", re.IGNORECASE
)


class CommandRunner(Protocol):
    """Injection seam for all external GitHub and Git operations."""

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> str:
        """Return stdout or raise when the command fails."""
        ...


class SubprocessRunner(CommandRunner):
    """Run fixed argv without a shell."""

    @override
    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> str:
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            argv,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return completed.stdout


@dataclass(frozen=True, slots=True)
class CollectionConfig:
    organization: str
    limit: int
    changes: frozenset[str]
    cache_dir: Path | None
    output: Path
    manifest: Path | None = None

    def __post_init__(self) -> None:
        if not self.organization or "/" in self.organization:
            message = "organization must be a non-empty GitHub organization name"
            raise ValueError(message)
        if self.limit <= 0:
            message = "comment corpus limit must be positive"
            raise ValueError(message)
        if not self.changes or not self.changes <= {"added", "deleted"}:
            message = "changes must contain added, deleted, or both"
            raise ValueError(message)
        if self.output == self.manifest:
            message = "raw output and manifest must be different files"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class CollectionSummary:
    requested: int
    collected: int
    processed_pull_requests: int
    skips: int
    counts: Mapping[str, int]
    complete: bool

    def render(self) -> str:
        """Return an identity-free, stable tabular summary."""
        lines = [
            f"requested\t{self.requested}",
            f"collected\t{self.collected}",
            f"processed_pull_requests\t{self.processed_pull_requests}",
            f"skips\t{self.skips}",
            f"complete\t{str(self.complete).lower()}",
        ]
        lines.extend(f"{key}\t{self.counts[key]}" for key in sorted(self.counts))
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class ChangedRanges:
    old: tuple[tuple[int, int], ...]
    new: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class CommentGroup:
    start_line: int
    end_line: int
    language: str
    kind: str
    text: str
    tags: tuple[str, ...] = ()


class CorpusRecord(TypedDict):
    repository: str
    pull_request: int
    merged_at: str
    base_sha: str
    head_sha: str
    path: str
    side: str
    start_line: int
    end_line: int
    language: str
    kind: str
    text: str
    tags: list[str]
    context_before: list[str]
    context_after: list[str]


@dataclass(frozen=True, slots=True)
class _Repository:
    full_name: str
    clone_url: str


@dataclass(frozen=True, slots=True)
class _PullRequest:
    repository: _Repository
    number: int
    merged_at: str
    base_sha: str
    head_sha: str


@dataclass(frozen=True, slots=True)
class _LexedComment:
    start_line: int
    end_line: int
    kind: str
    text: str
    own_line: bool


def collect(config: CollectionConfig, *, runner: CommandRunner | None = None) -> CollectionSummary:
    """Collect exactly ``config.limit`` comment groups, newest merged PR first."""
    command_runner = runner or SubprocessRunner()
    repositories = _repositories(config.organization, command_runner)
    skip_counts: Counter[str] = Counter()
    pull_requests = _pull_requests(repositories, command_runner, skip_counts)
    records: list[CorpusRecord] = []
    processed = 0
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if config.cache_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="sarj-pr-comment-cache-")
        cache_root = Path(temporary.name)
    else:
        cache_root = config.cache_dir
        cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _require_private_directory(cache_root)
    try:
        for pull_request in pull_requests:
            if len(records) >= config.limit:
                break
            processed += 1
            try:
                cache = _prepare_cache(cache_root, pull_request, command_runner)
                for record in _records_for_pull_request(
                    pull_request, cache, config.changes, command_runner, skip_counts
                ):
                    records.append(record)
                    if len(records) == config.limit:
                        break
            except OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError:
                skip_counts["pull_request_error"] += 1
    finally:
        if temporary is not None:
            temporary.cleanup()

    counts: Counter[str] = Counter()
    for record in records:
        counts[f"language.{record['language']}"] += 1
        counts[f"side.{record['side']}"] += 1
        counts[f"kind.{record['kind']}"] += 1
    summary = CollectionSummary(
        requested=config.limit,
        collected=len(records),
        processed_pull_requests=processed,
        skips=sum(skip_counts.values()),
        counts=dict(counts),
        complete=len(records) == config.limit,
    )
    manifest = {
        "schema_version": 1,
        "organization": config.organization,
        "requested": config.limit,
        "collected": len(records),
        "complete": summary.complete,
        "changes": sorted(config.changes),
        "processed_pull_requests": processed,
        "repositories_discovered": len(repositories),
        "pull_requests_discovered": len(pull_requests),
        "skips": dict(sorted(skip_counts.items())),
        "counts": dict(sorted(counts.items())),
    }
    _write_jsonl_private(config.output, records)
    if config.manifest is not None:
        _write_json_private(config.manifest, manifest)
    if not summary.complete and summary.skips:
        message = f"comment corpus incomplete: collected {summary.collected} of {summary.requested}"
        raise RuntimeError(message)
    return summary


def _repositories(organization: str, runner: CommandRunner) -> tuple[_Repository, ...]:
    endpoint = f"orgs/{organization}/repos?per_page=100&type=all"
    raw = _json_items(runner.run(("gh", "api", "--paginate", "--slurp", endpoint)))
    repositories: list[_Repository] = []
    for item in raw:
        full_name = item.get("full_name")
        clone_url = item.get("clone_url")
        if isinstance(full_name, str) and isinstance(clone_url, str):
            repositories.append(_Repository(full_name, clone_url))
    return tuple(sorted(repositories, key=lambda repository: repository.full_name))


def _pull_requests(
    repositories: Sequence[_Repository], runner: CommandRunner, skips: Counter[str]
) -> tuple[_PullRequest, ...]:
    found: list[_PullRequest] = []
    for repository in repositories:
        endpoint = f"repos/{repository.full_name}/pulls?state=closed&sort=updated&direction=desc&per_page=100"
        try:
            items = _json_items(runner.run(("gh", "api", "--paginate", "--slurp", endpoint)))
        except OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError:
            skips["repository_history_unavailable"] += 1
            continue
        for item in items:
            merged_at = item.get("merged_at")
            number = item.get("number")
            base = item.get("base")
            head = item.get("head")
            merge_sha = item.get("merge_commit_sha")
            base_values = base if _is_string_mapping(base) else {}
            head_values = head if _is_string_mapping(head) else {}
            base_sha = base_values.get("sha")
            head_sha = head_values.get("sha")
            if not isinstance(merged_at, str) or not isinstance(number, int):
                continue
            if not isinstance(base_sha, str) or not isinstance(head_sha, str):
                continue
            if _SHA_RE.fullmatch(base_sha) is None or _SHA_RE.fullmatch(head_sha) is None:
                continue
            # The merged result is retained by the base repository even after a
            # fork branch or refs/pull/N/head disappears.  It is also the code
            # reviewers ultimately accepted, so prefer it over the ephemeral
            # source head while retaining the head as a compatibility fallback.
            effective_head = (
                merge_sha if isinstance(merge_sha, str) and _SHA_RE.fullmatch(merge_sha) is not None else head_sha
            )
            found.append(_PullRequest(repository, number, merged_at, base_sha.lower(), effective_head.lower()))
    return tuple(sorted(found, key=lambda pull: (-_timestamp(pull.merged_at), pull.repository.full_name, pull.number)))


def _json_items(payload: str) -> list[dict[str, object]]:
    decoded: object = json.loads(payload)  # pyright: ignore[reportAny] -- json.loads has an unavoidably Any return.
    if not _is_object_list(decoded):
        message = "paginated GitHub response must be a JSON array"
        raise TypeError(message)
    items: list[dict[str, object]] = []
    for value in decoded:
        page = value if _is_object_list(value) else [value]
        items.extend(item for item in page if _is_string_mapping(item))
    return items


def _is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_string_mapping(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


def _timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError as exc:
        message = "merged_at must be an ISO-8601 timestamp"
        raise ValueError(message) from exc


def _prepare_cache(cache_root: Path, pull_request: _PullRequest, runner: CommandRunner) -> Path:
    name = _SAFE_NAME_RE.sub("_", pull_request.repository.full_name) + ".git"
    cache = cache_root / name
    if not cache.exists():
        runner.run(("git", "init", "--bare", str(cache)))
        if cache.exists():
            cache.chmod(0o700)
    if cache.exists():
        _require_private_directory(cache)
    fetch = ("git", "fetch", "--no-tags", "--force", pull_request.repository.clone_url)
    try:
        runner.run((*fetch, pull_request.base_sha, pull_request.head_sha), cwd=cache)
    except OSError, subprocess.SubprocessError:
        runner.run((*fetch, pull_request.base_sha), cwd=cache)
        runner.run((*fetch, f"refs/pull/{pull_request.number}/head"), cwd=cache)
    return cache


def _records_for_pull_request(
    pull_request: _PullRequest,
    cache: Path,
    changes: frozenset[str],
    runner: CommandRunner,
    skips: Counter[str],
) -> tuple[CorpusRecord, ...]:
    raw_names = runner.run(
        (
            "git",
            "diff",
            "--name-status",
            "-z",
            "--no-renames",
            pull_request.base_sha,
            pull_request.head_sha,
            "--",
        ),
        cwd=cache,
    )
    candidates = _changed_paths(raw_names)
    records: list[CorpusRecord] = []
    for status, path in candidates:
        language = _language(path)
        if language is None:
            skips["unsupported_path"] += 1
            continue
        diff = runner.run(
            (
                "git",
                "diff",
                "--unified=0",
                "--no-renames",
                pull_request.base_sha,
                pull_request.head_sha,
                "--",
                path,
            ),
            cwd=cache,
        )
        ranges = parse_changed_ranges(diff)
        sides = (
            ("deleted", pull_request.base_sha, ranges.old, status != "A"),
            ("added", pull_request.head_sha, ranges.new, status != "D"),
        )
        for side, revision, changed, exists in sides:
            if side not in changes or not exists or not changed:
                continue
            try:
                source = runner.run(("git", "show", f"{revision}:{path}"), cwd=cache)
            except OSError, subprocess.SubprocessError:
                skips["blob_unavailable"] += 1
                continue
            if "\0" in source:
                skips["binary_blob"] += 1
                continue
            for group in extract_comment_groups(path, source=source):
                if not _intersects(group.start_line, group.end_line, changed):
                    continue
                source_lines = source.splitlines()
                records.append(
                    {
                        "repository": pull_request.repository.full_name,
                        "pull_request": pull_request.number,
                        "merged_at": pull_request.merged_at,
                        "base_sha": pull_request.base_sha,
                        "head_sha": pull_request.head_sha,
                        "path": path,
                        "side": side,
                        "start_line": group.start_line,
                        "end_line": group.end_line,
                        "language": group.language,
                        "kind": group.kind,
                        "text": group.text,
                        "tags": list(group.tags),
                        "context_before": source_lines[max(0, group.start_line - 4) : group.start_line - 1],
                        "context_after": source_lines[group.end_line : group.end_line + 3],
                    }
                )
    return tuple(records)


def _changed_paths(payload: str) -> tuple[tuple[str, str], ...]:
    if payload and not payload.endswith("\0"):
        message = "malformed NUL-delimited git name-status output"
        raise ValueError(message)
    fields = payload.split("\0")
    if fields and not fields[-1]:
        fields.pop()
    if len(fields) % 2:
        message = "malformed NUL-delimited git name-status output"
        raise ValueError(message)
    found: list[tuple[str, str]] = []
    for index in range(0, len(fields), 2):
        status, path = fields[index : index + 2]
        if status not in {"A", "D", "M"} or not path or "\0" in path:
            continue
        found.append((status, path))
    return tuple(found)


def parse_changed_ranges(diff: str) -> ChangedRanges:
    """Parse old/new one-based inclusive ranges from a unified diff."""
    old: list[tuple[int, int]] = []
    new: list[tuple[int, int]] = []
    for line in diff.splitlines():
        match = _HUNK_RE.match(line)
        if match is None:
            continue
        old_start, old_count, new_start, new_count = match.groups()
        _append_range(old, int(old_start), int(old_count or "1"))
        _append_range(new, int(new_start), int(new_count or "1"))
    return ChangedRanges(tuple(old), tuple(new))


def _append_range(destination: list[tuple[int, int]], start: int, count: int) -> None:
    if count > 0:
        destination.append((start, start + count - 1))


def _intersects(start: int, end: int, changed: Sequence[tuple[int, int]]) -> bool:
    return any(start <= changed_end and changed_start <= end for changed_start, changed_end in changed)


def _language(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix in _PYTHON_SUFFIXES:
        return "python"
    if suffix in _JAVASCRIPT_SUFFIXES:
        return "typescript"
    return None


def extract_comment_groups(path: str, *, source: str) -> tuple[CommentGroup, ...]:
    """Extract syntax-aware comment groups from one complete source blob."""
    language = _language(path)
    if language is None:
        return ()
    lexed = _python_lexed(source) if language == "python" else _javascript_lexed(source)
    return tuple(
        CommentGroup(group.start_line, group.end_line, group.language, group.kind, group.text, _tags(path, group.text))
        for group in _group_comments(lexed, language)
    )


def _python_lexed(source: str) -> list[_LexedComment]:
    found: list[_LexedComment] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
                continue
            expression = node.body[0]
            if (
                isinstance(expression, ast.Expr)
                and isinstance(expression.value, ast.Constant)
                and isinstance(expression.value.value, str)
            ):
                end_line = expression.end_lineno or expression.lineno
                found.append(
                    _LexedComment(
                        expression.lineno,
                        end_line,
                        "docstring",
                        expression.value.value,
                        own_line=False,
                    )
                )
    lines = source.splitlines()
    with suppress(tokenize.TokenError, IndentationError, SyntaxError):
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type != tokenize.COMMENT:
                continue
            line = lines[token.start[0] - 1] if token.start[0] <= len(lines) else ""
            own_line = not line[: token.start[1]].strip()
            found.append(
                _LexedComment(
                    token.start[0],
                    token.end[0],
                    "comment",
                    token.string.removeprefix("#").strip(),
                    own_line,
                )
            )
    return sorted(found, key=lambda item: (item.start_line, item.end_line, item.kind))


def _javascript_lexed(source: str) -> list[_LexedComment]:
    found: list[_LexedComment] = []
    index = 0
    line = 1
    line_start = 0
    can_start_regex = True
    if source.startswith("#!"):
        end = source.find("\n")
        end = len(source) if end < 0 else end
        found.append(_LexedComment(1, 1, "comment", source[1:end].strip(), own_line=True))
        index = end
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if char in " \t\r":
            index += 1
            continue
        if char == "\n":
            line += 1
            index += 1
            line_start = index
            continue
        if char in {'"', "'", "`"}:
            index, line, line_start = _skip_js_quoted(source, index, line, line_start, char)
            can_start_regex = False
            continue
        if char == "/" and following == "/":
            end = source.find("\n", index + 2)
            end = len(source) if end < 0 else end
            found.append(
                _LexedComment(
                    line, line, "comment", source[index + 2 : end].strip(), not source[line_start:index].strip()
                )
            )
            index = end
            continue
        if char == "/" and following == "*":
            end = source.find("*/", index + 2)
            content_end = len(source) if end < 0 else end
            raw = source[index + 2 : content_end]
            end_line = line + raw.count("\n")
            prefix = source[line_start:index]
            jsx = prefix.rstrip().endswith("{") and source[content_end + 2 :].lstrip().startswith("}")
            kind = "jsx_comment" if jsx else "jsdoc" if raw.startswith("*") else "block_comment"
            found.append(_LexedComment(line, end_line, kind, _clean_block_comment(raw), not prefix.strip(" \t{")))
            index = len(source) if end < 0 else end + 2
            line = end_line
            last_newline = source.rfind("\n", 0, index)
            line_start = last_newline + 1
            can_start_regex = False
            continue
        if char == "/" and can_start_regex:
            index, line, line_start = _skip_js_regex(source, index, line, line_start)
            can_start_regex = False
            continue
        can_start_regex = char in "([{=,:;!&|?+-*%^~<>"
        index += 1
    return found


def _skip_js_quoted(source: str, index: int, line: int, line_start: int, quote: str) -> tuple[int, int, int]:
    index += 1
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1, line, line_start
        if char == "\n":
            line += 1
            line_start = index + 1
        index += 1
    return index, line, line_start


def _skip_js_regex(source: str, index: int, line: int, line_start: int) -> tuple[int, int, int]:
    index += 1
    in_class = False
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "\n":
            return index, line, line_start
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            index += 1
            while index < len(source) and source[index].isalpha():
                index += 1
            return index, line, line_start
        index += 1
    return index, line, line_start


def _clean_block_comment(value: str) -> str:
    return "\n".join(line.strip().removeprefix("*").strip() for line in value.strip().splitlines()).strip()


def _group_comments(comments: Sequence[_LexedComment], language: str) -> tuple[CommentGroup, ...]:
    groups: list[CommentGroup] = []
    pending: list[_LexedComment] = []

    def flush() -> None:
        if not pending:
            return
        groups.append(
            CommentGroup(
                pending[0].start_line,
                pending[-1].end_line,
                language,
                "comment",
                "\n".join(item.text for item in pending),
            )
        )
        pending.clear()

    for comment in comments:
        if comment.kind == "comment" and comment.own_line:
            if pending and comment.start_line != pending[-1].end_line + 1:
                flush()
            pending.append(comment)
            continue
        flush()
        groups.append(CommentGroup(comment.start_line, comment.end_line, language, comment.kind, comment.text))
    flush()
    return tuple(groups)


def _tags(path: str, text: str) -> tuple[str, ...]:
    tags: list[str] = []
    normalized_path = path.lower()
    path_parts = Path(normalized_path).parts
    generated_path = Path(normalized_path).stem in {"generated", "gen"} or any(
        part in {"generated", "gen", "vendor", "vendored"} for part in path_parts
    )
    if generated_path or _GENERATED_RE.search(text):
        tags.append("generated")
    if text.lstrip().startswith("!/") or _DIRECTIVE_RE.search(text.strip()):
        tags.append("directive")
    if _LICENSE_RE.search(text):
        tags.append("license")
    return tuple(tags)


def _write_jsonl_private(path: Path, records: Sequence[CorpusRecord]) -> None:
    _write_private(path, "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records))


def _write_json_private(path: Path, value: object) -> None:
    _write_private(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_private(path: Path, content: str) -> None:
    parent = path.parent.resolve(strict=True)
    if parent.stat().st_mode & 0o077:
        message = "private corpus output parent must be owner-only"
        raise PermissionError(message)
    staging = parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    descriptor = os.open(staging, _WRITE_FLAGS, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staging, path, follow_symlinks=False)
        path.chmod(0o600, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            staging.unlink()


def _require_private_directory(path: Path) -> None:
    status = path.lstat()
    if path.is_symlink() or not path.is_dir():
        message = "private corpus cache must be a real directory"
        raise PermissionError(message)
    if status.st_mode & 0o077:
        message = "private corpus cache must be owner-only"
        raise PermissionError(message)


__all__ = [
    "ChangedRanges",
    "CollectionConfig",
    "CollectionSummary",
    "CommandRunner",
    "CommentGroup",
    "SubprocessRunner",
    "collect",
    "extract_comment_groups",
    "parse_changed_ranges",
]
