"""Hook-manager detection and validation shared by setup, update, and doctor."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePath
import re
import shlex
from typing import TYPE_CHECKING, Final, NamedTuple

import yaml

from . import launcher, manifest


if TYPE_CHECKING:
    from .manifest import HookManager


LEFTHOOK_NAMES: Final = ("lefthook.yml", "lefthook.yaml")
PRECOMMIT_NAMES: Final = (".pre-commit-config.yaml", ".pre-commit-config.yml")
PRECOMMIT_FILES_PATTERN: Final = (
    r"(?i)(\.py|\.[cm]?[jt]s|\.[jt]sx|\.sql|\.tf|\.tfvars|\.hcl|\.ya?ml|\.toml|\.jsonc|\.mdx?|"
    r"\.(?:bash|cfg|conf|env|ini|properties|sh|tftpl|zsh)|(?:^|/)\.env(?:\..*)?$|"
    r"(?:^|/)requirements(?:/.*|[^/]*\.(?:txt|in))$|"
    r"(?:^|/)(?:Dockerfile(?:\..*)?|Gnumakefile|Justfile|Makefile|package\.json|pyrightconfig\.json))$"
)
_COMMANDS_BLOCK: Final = re.compile(r"(?m)^(?P<indent> +)commands:(?P<tail>[^\n]*)$")
_JOBS_BLOCK: Final = re.compile(r"(?m)^(?P<indent> +)jobs:(?P<tail>[^\n]*)$")
_MAX_JOB_DEPTH: Final = 64
_REPO_LINE: Final = re.compile(r"^(?P<indent> *)-\s+repo:\s*(?P<value>[^\r\n]+)(?:\r?\n)?$")
_OFFICIAL_STANDARDS_REPO: Final = re.compile(
    r"(?i)(?:https?://github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"sarj-ai/standards(?:\.git)?/?"
)


class LefthookWrite(NamedTuple):
    """One comment-preserving Lefthook repair ready for a scaffold plan."""

    path: Path
    contents: str


class PrecommitRepoBlock(NamedTuple):
    """One byte-preserving repository list item from a pre-commit config."""

    start: int
    end: int
    indent: int
    repository: str | None
    text: str


class _PrecommitRepoSection(NamedTuple):
    header: int
    section_end: int
    item_indent: int


class _LefthookEntries(NamedTuple):
    text: str
    layout: str
    entries: Mapping[str, object]


class _LocatedBlock(NamedTuple):
    match: re.Match[str]
    section_end: int


def precommit_repo_blocks(text: str) -> tuple[PrecommitRepoBlock, ...]:
    """Split top-level-looking pre-commit repository items without reformatting YAML."""
    lines = text.splitlines(keepends=True)
    section = _precommit_repo_section(lines)
    if section is None:
        return ()
    header, section_end, item_indent = section
    offsets = _line_offsets(lines)
    blocks: list[PrecommitRepoBlock] = []
    for index in range(header + 1, section_end):
        line = lines[index]
        match = _REPO_LINE.match(line)
        if match is None or len(match.group("indent")) != item_indent:
            continue
        end_index = yaml_list_item_end(lines, index, item_indent)
        start = offsets[index]
        end = offsets[end_index] if end_index < len(offsets) else len(text)
        repository = _repository_scalar(match.group("value"))
        blocks.append(PrecommitRepoBlock(start, end, item_indent, repository, text[start:end]))
    return tuple(blocks)


def _line_offsets(lines: list[str]) -> list[int]:
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    return offsets


def _repository_scalar(raw: str) -> str | None:
    try:
        parsed: object = yaml.safe_load(f"value: {raw}\n")  # pyright: ignore[reportAny] -- narrowed below.
        value = manifest.as_table(parsed).get("value")
    except yaml.YAMLError:
        return None
    return value if isinstance(value, str) else None


def _precommit_repo_section(lines: list[str]) -> _PrecommitRepoSection | None:
    """Locate direct sequence children of the top-level ``repos`` key."""
    header = next((index for index, line in enumerate(lines) if re.match(r"^repos:\s*(?:#.*)?(?:\r?\n)?$", line)), None)
    if header is None:
        return None
    section_end = len(lines)
    for index in range(header + 1, len(lines)):
        stripped = lines[index].strip()
        repo_item = _REPO_LINE.match(lines[index]) is not None
        if (
            stripped
            and not stripped.startswith("#")
            and not repo_item
            and len(lines[index]) == len(lines[index].lstrip(" "))
        ):
            section_end = index
            break
    item_indent = next(
        (
            len(match.group("indent"))
            for line in lines[header + 1 : section_end]
            if (match := _REPO_LINE.match(line)) is not None
        ),
        None,
    )
    return None if item_indent is None else _PrecommitRepoSection(header, section_end, item_indent)


def yaml_list_item_end(lines: list[str], start: int, indent: int) -> int:
    """Return a list item's end without consuming following comments or parent keys."""
    trailing: int | None = None
    index = start + 1
    while index < len(lines):
        stripped = lines[index].lstrip(" ")
        if not stripped.strip() or stripped.startswith("#"):
            trailing = index if trailing is None else trailing
            index += 1
            continue
        candidate_indent = len(lines[index]) - len(stripped)
        if candidate_indent <= indent:
            return trailing if trailing is not None else index
        trailing = None
        index += 1
    return trailing if trailing is not None else len(lines)


def is_official_standards_repo(repository: str | None) -> bool:
    """Recognize only the exact GitHub sarj-ai/standards repository identity."""
    return repository is not None and _OFFICIAL_STANDARDS_REPO.fullmatch(repository.strip()) is not None


def lefthook_config(root: Path) -> Path | None:
    """Return the active Lefthook configuration, if present."""
    return next((root / name for name in LEFTHOOK_NAMES if (root / name).is_file()), None)


def detect_manager(root: Path) -> HookManager:
    """Preserve an existing Lefthook setup; otherwise manage pre-commit."""
    return "lefthook" if lefthook_config(root) is not None else "pre-commit"


def precommit_runs_staged_check(root: Path) -> bool:
    """Require exactly one canonical local staged-check hook."""
    paths = [root / name for name in PRECOMMIT_NAMES if (root / name).is_file()]
    if len(paths) != 1:
        return False
    try:
        parsed: object = yaml.safe_load(  # pyright: ignore[reportAny] -- narrowed below.
            paths[0].read_text(encoding="utf-8")
        )
    except OSError, UnicodeError, yaml.YAMLError:
        return False
    candidates: list[dict[str, object]] = []
    for raw_repository in manifest.list_field(manifest.as_table(parsed), "repos"):
        repository = manifest.as_table(raw_repository)
        if repository.get("repo") != "local":
            continue
        candidates.extend(
            hook
            for raw_hook in manifest.list_field(repository, "hooks")
            if (hook := manifest.as_table(raw_hook)).get("id") in {"sarj-standards-check", "sarj-standards-drift"}
        )
    if len(candidates) != 1:
        return False
    candidate = candidates[0]
    return (
        candidate.get("id") == "sarj-standards-check"
        and _runs_staged_check(candidate.get("entry"))
        and candidate.get("language") == "system"
        and "verbose" not in candidate
        and candidate.get("always_run") is True
        and candidate.get("pass_filenames") is True
        and candidate.get("require_serial") is True
        and candidate.get("files") == PRECOMMIT_FILES_PATTERN
        and candidate.get("stages") == ["pre-commit"]
    )


def lefthook_runs_staged_check(root: Path) -> bool:
    """Require exactly one pinned, filename-aware staged command."""
    path = lefthook_config(root)
    if path is None:
        return False
    try:
        parsed: object = yaml.safe_load(  # pyright: ignore[reportAny] -- narrow the untyped YAML parser boundary below.
            path.read_text(encoding="utf-8")
        )
    except OSError, UnicodeError, yaml.YAMLError:
        return False
    document = manifest.as_table(parsed)
    pre_commit = manifest.as_table(document.get("pre-commit"))
    values = tuple(_lefthook_run_values(pre_commit))
    return values.count(_canonical_lefthook_command(root)) == 1


def wire_lefthook_staged_check(root: Path) -> LefthookWrite:
    """Add the canonical command to a conventional Lefthook mapping without reformatting it."""
    path = lefthook_config(root)
    if path is None:
        msg = "--hooks lefthook requires lefthook.yml or lefthook.yaml"
        raise ValueError(msg)
    text, layout, entries = _load_lefthook_entries(path)
    staged_values = tuple(value for value in _lefthook_run_values_from_entries(entries) if _runs_staged_check(value))
    if len(staged_values) > 1:
        msg = f"cannot safely wire {path.name}: multiple staged Standards commands are active"
        raise ValueError(msg)
    if staged_values:
        repaired = _replace_lefthook_run(
            text,
            old=staged_values[0],
            new=_canonical_lefthook_command(root),
        )
        if repaired is None:
            msg = f"cannot safely wire {path.name}: staged Standards command is not a scalar run value"
            raise ValueError(msg)
        return LefthookWrite(path, repaired)
    block_match, section_end = _locate_block(path, text, layout)
    name = "sarj-standards" if "sarj-standards" not in entries else "sarj-standards-staged"
    if layout == "commands":
        contents = _insert_staged_command(path, text, block_match, section_end, name)
    else:
        contents = _insert_staged_job(path, text, block_match, section_end, name)
    return LefthookWrite(path, contents)


def _load_lefthook_entries(path: Path) -> _LefthookEntries:
    try:
        text = path.read_text(encoding="utf-8")
        parsed: object = yaml.safe_load(text)  # pyright: ignore[reportAny] -- narrowed immediately below.
        document = manifest.as_table(parsed)
        pre_commit = manifest.as_table(document.get("pre-commit"))
    except (OSError, UnicodeError, TypeError, yaml.YAMLError) as exc:
        msg = f"cannot safely wire {path.name}: expected valid pre-commit commands or jobs"
        raise ValueError(msg) from exc
    if "commands" in pre_commit:
        return _LefthookEntries(text, "commands", manifest.as_table(pre_commit.get("commands")))
    jobs = manifest.list_field(pre_commit, "jobs")
    if "jobs" in pre_commit:
        names = {
            str(job.get("name")): job for value in jobs if (job := manifest.as_table(value)).get("name") is not None
        }
        return _LefthookEntries(text, "jobs", names)
    msg = f"cannot safely wire {path.name}: expected block-style pre-commit commands or jobs"
    raise ValueError(msg)


def _locate_block(path: Path, text: str, layout: str) -> _LocatedBlock:
    pre_commit_match = re.search(r"(?m)^pre-commit:\s*(?:#.*)?$", text)
    if pre_commit_match is None:
        msg = f"cannot safely wire {path.name}: expected a block-style pre-commit.commands mapping"
        raise ValueError(msg)
    section_end_match = re.search(r"(?m)^[^\s#][^:]*:\s*", text[pre_commit_match.end() :])
    section_end = len(text) if section_end_match is None else pre_commit_match.end() + section_end_match.start()
    pattern = _COMMANDS_BLOCK if layout == "commands" else _JOBS_BLOCK
    block_match = pattern.search(text, pre_commit_match.end(), section_end)
    if block_match is None:
        msg = f"cannot safely wire {path.name}: expected block-style pre-commit {layout}"
        raise ValueError(msg)
    return _LocatedBlock(block_match, section_end)


def _insert_staged_job(
    path: Path,
    text: str,
    jobs_match: re.Match[str],
    section_end: int,
    name: str,
) -> str:
    block_indent = len(jobs_match.group("indent"))
    child_indent = " " * (block_indent + 2)
    rendered = f"{child_indent}- name: {name}\n{child_indent}  run: {_canonical_lefthook_command(path.parent)}\n"
    tail = jobs_match.group("tail")
    if tail.strip():
        msg = f"cannot safely wire {path.name}: expected block-style pre-commit jobs"
        raise ValueError(msg)
    insertion = jobs_match.end() + (1 if text[jobs_match.end() :].startswith("\n") else 0)
    for line in text[insertion:section_end].splitlines(keepends=True):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and len(line) - len(line.lstrip(" ")) <= block_indent:
            break
        insertion += len(line)
    separator = "" if insertion > jobs_match.end() else "\n"
    return "".join((text[:insertion], separator, rendered, text[insertion:]))


def _insert_staged_command(
    path: Path,
    text: str,
    commands_match: re.Match[str],
    section_end: int,
    name: str,
) -> str:
    command_indent = len(commands_match.group("indent"))
    child_indent = " " * (command_indent + 2)
    rendered = f"{child_indent}{name}:\n{child_indent}  run: {_canonical_lefthook_command(path.parent)}\n"
    absolute_start = commands_match.start()
    absolute_end = commands_match.end()
    tail = commands_match.group("tail")
    if re.fullmatch(r"\s*\{\}\s*(?:#.*)?", tail):
        comment = tail[tail.find("#") :] if "#" in tail else ""
        replacement = f"{commands_match.group('indent')}commands:"
        if comment:
            replacement = f"{replacement}  {comment}"
        return "".join((text[:absolute_start], replacement, "\n", rendered, text[absolute_end + 1 :]))
    if tail.strip():
        msg = f"cannot safely wire {path.name}: expected a block-style pre-commit.commands mapping"
        raise ValueError(msg)

    insertion = absolute_end + (1 if text[absolute_end:].startswith("\n") else 0)
    for line in text[insertion:section_end].splitlines(keepends=True):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and len(line) - len(line.lstrip(" ")) <= command_indent:
            break
        insertion += len(line)
    separator = "" if insertion > absolute_end else "\n"
    return "".join((text[:insertion], separator, rendered, text[insertion:]))


def _runs_staged_check(value: object) -> bool:
    if not isinstance(value, str) or re.search(r"(?:&&|\|\||[;|`]|\$\()", value):
        return False
    try:
        tokens = shlex.split(value)
    except ValueError:
        return False
    executable = next(
        (index for index, token in enumerate(tokens) if PurePath(token).name == launcher.REPOSITORY_LAUNCHER.name),
        None,
    )
    if executable is None:
        return False
    prefix = tokens[:executable]
    if prefix and PurePath(prefix[0]).name not in {"uv", "uvx"}:
        return False
    if any(PurePath(token).name in {"echo", "printf"} for token in prefix):
        return False
    return tokens[executable + 1 : executable + 3] == ["check", "--staged"]


def _canonical_lefthook_command(root: Path | None = None) -> str:
    if root is not None and (root / "packages" / "standards" / "pyproject.toml").is_file():
        return (
            "uv run --project packages/standards --frozen sarj-standards check --staged "
            "--trust-repository-code -- {staged_files}"
        )
    return f"{launcher.repository_command()} check --staged --trust-repository-code -- {{staged_files}}"


def _lefthook_run_values(value: object, *, depth: int = 0, seen: set[int] | None = None) -> list[str]:
    """Collect scalar run commands from a bounded YAML object graph."""
    if depth > _MAX_JOB_DEPTH:
        return []
    visited: set[int] = set() if seen is None else seen
    if isinstance(value, (dict, list)):
        identity = id(value)  # pyright: ignore[reportUnknownArgumentType] -- identity is the cycle guard.
        if identity in visited:
            return []
        visited.add(identity)
    table = manifest.as_table(value)  # pyright: ignore[reportUnknownArgumentType] -- narrowed parser value.
    if table:
        found: list[str] = [run for run in (table.get("run"),) if isinstance(run, str)]
        for child in table.values():
            found.extend(_lefthook_run_values(child, depth=depth + 1, seen=visited))
        return found
    if isinstance(value, list):
        found = []
        for child in manifest.list_field(
            {"items": value},  # pyright: ignore[reportUnknownArgumentType] -- narrowed parser list.
            "items",
        ):
            found.extend(_lefthook_run_values(child, depth=depth + 1, seen=visited))
        return found
    return []


def _lefthook_run_values_from_entries(entries: Mapping[str, object]) -> list[str]:
    return _lefthook_run_values(entries)


def _replace_lefthook_run(text: str, *, old: str, new: str) -> str | None:
    """Replace one plain scalar run command without reformatting the YAML document."""
    matches: list[re.Match[str]] = []
    for match in re.finditer(r"(?m)^(?P<prefix>\s*run:\s*)(?P<value>[^\r\n]+)$", text):
        try:
            parsed: object = yaml.safe_load(f"value: {match.group('value')}\n")  # pyright: ignore[reportAny]
            value = manifest.as_table(parsed).get("value")
        except yaml.YAMLError:
            continue
        if value == old:
            matches.append(match)
    if len(matches) != 1:
        return None
    match = matches[0]
    return f"{text[: match.start()]}{match.group('prefix')}{new}{text[match.end() :]}"


def _jobs_run_staged_check(value: object, seen: set[int] | None = None, *, depth: int = 0) -> bool:
    if not isinstance(value, list):
        return False
    if depth > _MAX_JOB_DEPTH:
        return False
    visited: set[int] = set() if seen is None else seen
    identity = id(value)  # pyright: ignore[reportUnknownArgumentType] -- YAML list identity detects alias cycles.
    if identity in visited:
        return False
    visited.add(identity)
    holder: dict[str, object] = {"jobs": value}
    jobs = manifest.list_field(holder, "jobs")
    for raw_job in jobs:
        job = manifest.as_table(raw_job)
        if _runs_staged_check(job.get("run")):
            return True
        group = manifest.as_table(job.get("group"))
        if _jobs_run_staged_check(group.get("jobs"), visited, depth=depth + 1):
            return True
    return False
