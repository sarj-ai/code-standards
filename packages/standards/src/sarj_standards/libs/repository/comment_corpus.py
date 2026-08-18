from __future__ import annotations

import ast
from collections import Counter
from contextlib import suppress
import errno
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tokenize
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple, TypedDict


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from typing import TextIO


_SUFFIXES = MappingProxyType(
    {
        ".hcl": "iac",
        ".js": "typescript",
        ".jsx": "typescript",
        ".md": "markdown",
        ".mdx": "markdown",
        ".py": "python",
        ".sql": "sql",
        ".tf": "iac",
        ".tfvars": "iac",
        ".toml": "config",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".yaml": "config",
        ".yml": "config",
    }
)
_SKIP_PARTS = frozenset(
    {".git", ".venv", ".worktrees", "node_modules", "dist", "build", "coverage", "vendor", "vendored"}
)
_BOUNDARY_RE = re.compile(r"(?<=[.!?])[\"'`)\]]*\s+(?=[A-Z0-9`])")
_BULLET_RE = re.compile(r"^\s*(?:[-*+] |\d+[.)] )")
_SQL_DOLLAR_TAG_RE: re.Pattern[str] = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")
_SECOND_SENTENCE = 2
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


class Record(TypedDict):
    repository: str
    path: str
    line: int
    language: str
    kind: str
    sentences: int
    text: str


class _CommentUnit(NamedTuple):
    line: int
    kind: str
    text: str


def _require_supported_platform() -> None:
    if os.name == "nt" or not hasattr(os, "fwalk"):
        msg = "comment-corpus maintenance requires POSIX descriptor-relative filesystem operations"
        raise OSError(msg)


def records(roots: Sequence[Path]) -> Iterator[Record]:
    _require_supported_platform()
    for root in roots:
        resolved_root = root.resolve(strict=True)
        root_descriptor = os.open(resolved_root, _DIRECTORY_FLAGS)
        try:
            for directory, names, filenames, directory_descriptor in os.fwalk(
                ".", topdown=True, follow_symlinks=False, dir_fd=root_descriptor
            ):
                names[:] = [name for name in names if name not in _SKIP_PARTS and not name.startswith(".")]
                for filename in filenames:
                    relative = Path(directory, filename)
                    language = _SUFFIXES.get(relative.suffix.lower())
                    if language is None:
                        continue
                    try:
                        source = _read_regular_file(directory_descriptor, filename)
                    except OSError:
                        continue
                    if source is None:
                        continue
                    comments = _comments(language, source)
                    for line, kind, value in comments:
                        yield {
                            "repository": resolved_root.name,
                            "path": relative.as_posix().removeprefix("./"),
                            "line": line,
                            "language": language,
                            "kind": kind,
                            "sentences": _sentence_units(value),
                            "text": value,
                        }
        finally:
            os.close(root_descriptor)


def _read_regular_file(directory_descriptor: int, filename: str) -> str | None:
    descriptor = os.open(filename, _READ_FLAGS, dir_fd=directory_descriptor)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        with os.fdopen(descriptor, encoding="utf-8", errors="replace") as source:
            descriptor = -1
            return source.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _comments(language: str, source: str) -> list[_CommentUnit]:
    return {
        "config": _hash_comments,
        "iac": _hcl_comments,
        "markdown": _markdown_comments,
        "python": _python_comments,
        "sql": _sql_comments,
        "typescript": _javascript_comments,
    }[language](source)


def emit_summary(roots: Sequence[Path], output: TextIO) -> int:
    _require_supported_platform()
    counts: Counter[tuple[str, str]] = Counter()
    for index, root in enumerate(roots, start=1):
        repository = f"repository-{index}"
        for record in records([root]):
            sentences = record["sentences"]
            band = "0-1" if sentences <= 1 else "2" if sentences == _SECOND_SENTENCE else "3+"
            counts[repository, band] += 1
    output.write("repository\t0-1\t2\t3+\n")
    output.writelines(
        f"{repository}\t{counts[repository, '0-1']}\t{counts[repository, '2']}\t{counts[repository, '3+']}\n"
        for repository in sorted({key[0] for key in counts})
    )
    return 0


def write_records(roots: Sequence[Path], destination: Path) -> int:
    _require_supported_platform()
    parent = destination.parent.resolve(strict=True)
    staging = f".{destination.name}.{secrets.token_hex(8)}.tmp"
    parent_descriptor = os.open(parent, _DIRECTORY_FLAGS)
    staging_descriptor = -1
    staging_status: os.stat_result | None = None
    source_status: os.stat_result | None = None
    source_status_box: list[os.stat_result] = []
    records_owned = False
    try:
        _require_safe_output_parent(os.fstat(parent_descriptor))
        _ = os.mkdir(staging, 0o700, dir_fd=parent_descriptor)
        staging_status = os.stat(staging, dir_fd=parent_descriptor, follow_symlinks=False)
        staging_descriptor = os.open(staging, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
        if not _same_inode(staging_status, os.fstat(staging_descriptor)):
            message = "raw corpus staging directory changed before it was opened"
            raise RuntimeError(message)
        descriptor = os.open("records", _WRITE_FLAGS, 0o600, dir_fd=staging_descriptor)
        records_owned = True
        source_status = _write_and_publish(
            roots,
            destination_name=destination.name,
            descriptor=descriptor,
            staging_descriptor=staging_descriptor,
            parent_descriptor=parent_descriptor,
            source_status_box=source_status_box,
        )
    finally:
        if source_status_box:
            source_status = source_status_box[0]
        _cleanup_staging(
            staging=staging,
            staging_status=staging_status,
            staging_descriptor=staging_descriptor,
            source_status=source_status,
            records_owned=records_owned,
            parent_descriptor=parent_descriptor,
        )
    return 0


def _write_and_publish(
    roots: Sequence[Path],
    *,
    destination_name: str,
    descriptor: int,
    staging_descriptor: int,
    parent_descriptor: int,
    source_status_box: list[os.stat_result],
) -> os.stat_result:
    try:
        source_status = os.fstat(descriptor)
        source_status_box.append(source_status)
        stream = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        with stream as output:
            output.writelines(json.dumps(record, ensure_ascii=False) + "\n" for record in records(roots))
            output.flush()
            os.fsync(output.fileno())
            if not _path_matches("records", source_status, staging_descriptor):
                message = "raw corpus staging file changed before publication"
                raise RuntimeError(message)
            os.link(
                "records",
                destination_name,
                src_dir_fd=staging_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            destination_status = os.stat(destination_name, dir_fd=parent_descriptor, follow_symlinks=False)
            if not _same_inode(destination_status, source_status):
                message = "raw corpus staging file changed before publication"
                raise RuntimeError(message)
            os.fsync(parent_descriptor)
        return source_status
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _cleanup_staging(
    *,
    staging: str,
    staging_status: os.stat_result | None,
    staging_descriptor: int,
    source_status: os.stat_result | None,
    records_owned: bool,
    parent_descriptor: int,
) -> None:
    try:
        if staging_descriptor >= 0:
            try:
                if source_status is not None:
                    _unlink_if_owned("records", source_status, staging_descriptor)
                elif records_owned:
                    with suppress(FileNotFoundError):
                        os.unlink("records", dir_fd=staging_descriptor)
            finally:
                os.close(staging_descriptor)
    finally:
        try:
            if staging_status is not None:
                _rmdir_if_owned(staging, staging_status, parent_descriptor)
        finally:
            os.close(parent_descriptor)


def _require_safe_output_parent(parent_status: os.stat_result) -> None:
    writable_by_others = parent_status.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    if writable_by_others and not parent_status.st_mode & stat.S_ISVTX:
        message = "raw corpus output directory must not be group/world writable unless it has the sticky bit"
        raise PermissionError(message)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _path_matches(name: str, expected: os.stat_result, directory_descriptor: int) -> bool:
    try:
        current = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return _same_inode(current, expected)


def _unlink_if_owned(name: str, expected: os.stat_result, directory_descriptor: int) -> None:
    if _path_matches(name, expected, directory_descriptor):
        os.unlink(name, dir_fd=directory_descriptor)


def _rmdir_if_owned(name: str, expected: os.stat_result, directory_descriptor: int) -> None:
    if _path_matches(name, expected, directory_descriptor):
        try:
            os.rmdir(name, dir_fd=directory_descriptor)
        except OSError as error:
            if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                raise


def _python_comments(source: str) -> list[_CommentUnit]:
    found: list[_CommentUnit] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
                continue
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.append(_CommentUnit(first.lineno, "docstring", first.value.value))
    with suppress(tokenize.TokenError, IndentationError):
        found.extend(
            _CommentUnit(token.start[0], "comment", token.string.removeprefix("#").strip())
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type == tokenize.COMMENT
        )
    return found


def _sentence_units(text: str) -> int:
    cleaned = re.sub(r"https?://\S+", "URL", text)
    cleaned = re.sub(r"`[^`\n]+`", "CODE", cleaned)
    cleaned = re.sub(r"\b\d+\.\d+\b", "NUMBER", cleaned)
    cleaned = re.sub(r"\b(?:e\.g\.|i\.e\.|vs\.|etc\.)", "ABBREVIATION", cleaned, flags=re.IGNORECASE)
    units = 0
    prose: list[str] = []
    for raw in cleaned.splitlines():
        line = raw.strip().lstrip("*").strip()
        if not line or re.fullmatch(r"[A-Za-z][A-Za-z ]+:", line):
            continue
        if _BULLET_RE.match(line):
            units += 1
        else:
            prose.append(line)
    paragraph = " ".join(prose).strip()
    return units + (len(_BOUNDARY_RE.split(paragraph)) if paragraph else 0)


def _javascript_comments(source: str) -> list[_CommentUnit]:
    found: list[_CommentUnit] = []
    index = 0
    line = 1
    quote: str | None = None
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            line += char == "\n"
            index += 1
            continue
        if char in {'"', "'", "`"}:
            quote = char
            index += 1
            continue
        if char == "/" and following == "/":
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            found.append(_CommentUnit(line, "comment", source[index + 2 : end].strip()))
            index = end
            continue
        if char == "/" and following == "*":
            end = source.find("*/", index + 2)
            end = len(source) - 2 if end < 0 else end
            value = source[index + 2 : end]
            found.append(_CommentUnit(line, "jsdoc" if value.startswith("*") else "comment", value.strip("* \n")))
            line += value.count("\n")
            index = end + 2
            continue
        line += char == "\n"
        index += 1
    return found


def _sql_comments(source: str) -> list[_CommentUnit]:
    found: list[_CommentUnit] = []
    index = 0
    line = 1
    quote: str | None = None
    dollar_tag: str | None = None
    while index < len(source):
        char = source[index]
        pair = source[index : index + 2]
        if dollar_tag is not None:
            if source.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
                continue
            line += char == "\n"
            index += 1
            continue
        if quote is not None:
            if char == quote and source[index + 1 : index + 2] == quote:
                index += 2
                continue
            if char == quote:
                quote = None
            line += char == "\n"
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "$" and (match := _SQL_DOLLAR_TAG_RE.match(source, index)):
            dollar_tag = str(match.group(0))
            index += len(dollar_tag)
            continue
        if pair == "--":
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            found.append(_CommentUnit(line, "comment", source[index + 2 : end].strip()))
            index = end
            continue
        if pair == "/*":
            end = source.find("*/", index + 2)
            end = len(source) if end < 0 else end
            value = source[index + 2 : end]
            found.append(_CommentUnit(line, "comment", value.strip("* \n")))
            line += value.count("\n")
            index = min(len(source), end + 2)
            continue
        line += char == "\n"
        index += 1
    return found


def _hash_comments(source: str) -> list[_CommentUnit]:
    found: list[_CommentUnit] = []
    block_indent: int | None = None
    for line_number, raw in enumerate(source.splitlines(), start=1):
        indent = len(raw) - len(raw.lstrip())
        if block_indent is not None:
            if raw.strip() and indent > block_indent:
                continue
            block_indent = None
        if re.search(r"[>|][+-]?\s*(?:#.*)?$", raw):
            block_indent = indent
        marker = _hash_comment_index(raw)
        if marker is not None:
            found.append(_CommentUnit(line_number, "comment", raw[marker + 1 :].strip()))
    return found


def _hcl_comments(source: str) -> list[_CommentUnit]:
    masked = _mask_hcl_heredocs(source)
    found = _javascript_comments(masked)
    found.extend(_hash_comments(masked))
    return sorted(set(found))


def _mask_hcl_heredocs(source: str) -> str:
    lines = source.splitlines(keepends=True)
    terminator: str | None = None
    masked: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if terminator is not None:
            masked.append(raw if stripped == terminator else "\n" if raw.endswith("\n") else "")
            if stripped == terminator:
                terminator = None
            continue
        match = re.search(r"<<-?\s*([A-Za-z_][A-Za-z0-9_]*)\s*$", raw.rstrip("\n"))
        terminator = match.group(1) if match is not None else None
        masked.append(raw)
    return "".join(masked)


def _hash_comment_index(line: str) -> int | None:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char == "#":
            return index
    return None


def _markdown_comments(source: str) -> list[_CommentUnit]:  # ruff: ignore[too-many-locals] -- scanner keeps independent fence and HTML-comment state
    found: list[_CommentUnit] = []
    in_fence = False
    fence = ""
    in_html = False
    html_start = 0
    html_parts: list[str] = []
    for line_number, raw in enumerate(source.splitlines(), start=1):
        stripped = raw.lstrip()
        if not in_html and (match := re.match(r"(`{3,}|~{3,})", stripped)):
            marker = match.group(1)
            if not in_fence:
                in_fence, fence = True, marker[0]
            elif marker[0] == fence:
                in_fence, fence = False, ""
            continue
        if in_fence:
            continue
        if in_html:
            before, separator, _after = raw.partition("-->")
            html_parts.append(before)
            if separator:
                found.append(_CommentUnit(html_start, "comment", "\n".join(html_parts).strip()))
                in_html = False
                html_parts = []
            continue
        if stripped.startswith("[//]:"):
            found.append(_CommentUnit(line_number, "comment", stripped.removeprefix("[//]:").strip()))
            continue
        before, opener, rest = raw.partition("<!--")
        if not opener:
            continue
        _ = before
        body, closer, _after = rest.partition("-->")
        if closer:
            found.append(_CommentUnit(line_number, "comment", body.strip()))
        else:
            in_html = True
            html_start = line_number
            html_parts = [rest]
    if in_html:
        found.append(_CommentUnit(html_start, "comment", "\n".join(html_parts).strip()))
    return found
