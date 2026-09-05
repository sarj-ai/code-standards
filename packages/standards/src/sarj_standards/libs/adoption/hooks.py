from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
import shlex
from typing import TYPE_CHECKING, Final, NamedTuple

import yaml
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver

from . import launcher, manifest


if TYPE_CHECKING:
    from yaml.nodes import MappingNode

    from .manifest import HookManager


LEFTHOOK_NAMES: Final = ("lefthook.yml", "lefthook.yaml")
PRECOMMIT_NAMES: Final = (".pre-commit-config.yaml", ".pre-commit-config.yml")
PRECOMMIT_FILES_PATTERN: Final = (
    r"(?i)(\.py|\.[cm]?[jt]s|\.[jt]sx|\.kts?|\.swift|\.sql|\.tf|\.tfvars|\.hcl|\.ya?ml|\.toml|\.jsonc|\.mdx?|"
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
    r"sarj-ai/(?:code-)?standards(?:\.git)?/?"
)


class LefthookWrite(NamedTuple):
    path: Path
    contents: str


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate resolved keys at every depth."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: MappingNode,
    deep: bool = False,  # ruff: ignore[boolean-type-hint-positional-argument,boolean-default-value-positional-argument] -- PyYAML callback signature.
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:  # pyright: ignore[reportAny]
        key: object = loader.construct_object(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
            key_node,  # pyright: ignore[reportAny]
            deep=deep,
        )
        try:
            duplicate = key in mapping
        except TypeError as exc:
            context = "while constructing a mapping"
            problem = "found an unhashable mapping key"
            raise ConstructorError(
                context,
                node.start_mark,
                problem,
                key_node.start_mark,  # pyright: ignore[reportAny]
            ) from exc
        if duplicate:
            context = "while constructing a mapping"
            problem = f"found duplicate key {key!r}"
            raise ConstructorError(
                context,
                node.start_mark,
                problem,
                key_node.start_mark,  # pyright: ignore[reportAny]
            )
        mapping[key] = loader.construct_object(  # pyright: ignore[reportUnknownMemberType]
            value_node,  # pyright: ignore[reportAny]
            deep=deep,
        )
    return mapping


_UniqueKeyLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,  # pyright: ignore[reportAny]
    _construct_unique_mapping,
)


class PrecommitRepoBlock(NamedTuple):
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


def insert_precommit_repository(text: str, block: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    rendered = block.replace("\n", newline)
    inline = re.search(
        r"(?m)^repos:\s*\[\s*\]\s*(?P<comment>#.*)?(?P<newline>\r?\n|$)",
        text,
    )
    if inline is not None:
        comment = inline.group("comment")
        header = "repos:" if comment is None else f"repos: {comment}"
        updated = text[: inline.start()] + header + newline + rendered + text[inline.end() :]
        validate_precommit_configuration(updated)
        return updated
    lines = text.splitlines(keepends=True)
    section = _precommit_repo_section(lines)
    if section is None:
        header = re.search(r"(?m)^repos:\s*(?:#.*)?(?P<newline>\r?\n|$)", text)
        if header is None:
            msg = "pre-commit configuration has no block-style top-level repos sequence"
            raise ValueError(msg)
        updated = text[: header.end()] + rendered + text[header.end() :]
        validate_precommit_configuration(updated)
        return updated
    offsets = _line_offsets(lines)
    insertion = offsets[section.section_end] if section.section_end < len(offsets) else len(text)
    prefix = text[:insertion]
    separator = "" if not prefix or prefix.endswith(("\n", "\r")) else newline
    updated = prefix + separator + rendered + text[insertion:]
    validate_precommit_configuration(updated)
    return updated


def validate_precommit_configuration(text: str) -> None:
    loader = _UniqueKeyLoader(text)
    try:
        parsed: object = loader.get_single_data()  # pyright: ignore[reportAny] -- parser boundary
    except yaml.YAMLError as exc:
        msg = f"pre-commit configuration is not valid YAML: {exc}"
        raise ValueError(msg) from exc
    finally:
        loader.dispose()  # pyright: ignore[reportUnknownMemberType]
    document = manifest.as_table(parsed)
    if not document and text.strip():
        msg = "pre-commit configuration must be a YAML mapping"
        raise ValueError(msg)
    repositories = document.get("repos")
    if repositories is not None and not isinstance(repositories, list):
        msg = "pre-commit configuration top-level repos must be a list"
        raise ValueError(msg)


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
    return repository is not None and _OFFICIAL_STANDARDS_REPO.fullmatch(repository.strip()) is not None


def lefthook_config(root: Path) -> Path | None:
    return next((root / name for name in LEFTHOOK_NAMES if (root / name).is_file()), None)


def detect_manager(root: Path) -> HookManager:
    return "lefthook" if lefthook_config(root) is not None else "pre-commit"


def precommit_runs_staged_check(root: Path) -> bool:
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


def precommit_runs_commit_message_check(root: Path, *, runner_prefix: str | None = None) -> bool:
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
            if (hook := manifest.as_table(raw_hook)).get("id") == "repo-standards-commit-message"
        )
    if len(candidates) != 1:
        return False
    candidate = candidates[0]
    return (
        _is_canonical_precommit_commit_message(candidate.get("entry"), root=root, runner_prefix=runner_prefix)
        and candidate.get("language") == "system"
        and candidate.get("always_run") is True
        and candidate.get("pass_filenames") is True
        and candidate.get("require_serial") is True
        and "files" not in candidate
        and candidate.get("stages") == ["commit-msg"]
    )


def lefthook_runs_staged_check(root: Path) -> bool:
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


def lefthook_runs_commit_message_check(root: Path, *, runner_prefix: str | None = None) -> bool:
    path = lefthook_config(root)
    if path is None:
        return False
    try:
        parsed: object = yaml.safe_load(  # pyright: ignore[reportAny] -- narrowed below.
            path.read_text(encoding="utf-8")
        )
    except OSError, UnicodeError, yaml.YAMLError:
        return False
    commit_message = manifest.as_table(manifest.as_table(parsed).get("commit-msg"))
    values = tuple(_lefthook_run_values(commit_message))
    commands = {_canonical_commit_message_command(path.parent, runner_prefix=runner_prefix)}
    if runner_prefix is None and not manifest.manifest_path(root).exists():
        commands.add(
            _canonical_commit_message_command(
                root, runner_prefix=shlex.join(launcher.argv(version=manifest.adopted_version()))
            )
        )
    return sum(values.count(command) for command in commands) == 1


def wire_lefthook_commit_message_check(  # ruff: ignore[too-many-locals] -- parser-safe migration keeps semantic and textual state explicit.
    root: Path,
    *,
    contents: str | None = None,
    runner_prefix: str | None = None,
) -> LefthookWrite:
    path = lefthook_config(root)
    if path is None:
        msg = "--hooks lefthook requires lefthook.yml or lefthook.yaml"
        raise ValueError(msg)
    text = path.read_text(encoding="utf-8") if contents is None else contents
    try:
        parsed: object = yaml.safe_load(text)  # pyright: ignore[reportAny] -- narrowed below.
        document = manifest.as_table(parsed)
    except (OSError, UnicodeError, TypeError, yaml.YAMLError) as exc:
        msg = f"cannot safely wire {path.name}: expected valid YAML"
        raise ValueError(msg) from exc
    if "commit-msg" in document:
        commit_message = manifest.as_table(document.get("commit-msg"))
        if "commands" in commit_message:
            layout = "commands"
            entries = manifest.as_table(commit_message.get("commands"))
        elif "jobs" in commit_message:
            layout = "jobs"
            entries = {
                str(job.get("name")): job
                for raw_job in manifest.list_field(commit_message, "jobs")
                if (job := manifest.as_table(raw_job)).get("name") is not None
            }
        else:
            msg = f"cannot safely wire {path.name}: expected block-style commit-msg commands or jobs"
            raise ValueError(msg)
        values = tuple(
            value for value in _lefthook_run_values_from_entries(entries) if _runs_commit_message_check(value)
        )
        if len(values) > 1:
            msg = f"cannot safely wire {path.name}: multiple commit-message Standards commands are active"
            raise ValueError(msg)
        if values:
            replacement = _replace_lefthook_run(
                text,
                old=values[0],
                new=_canonical_commit_message_command(root, runner_prefix=runner_prefix),
            )
            if replacement is None:
                msg = f"cannot safely wire {path.name}: commit-message Standards command is not a scalar run value"
                raise ValueError(msg)
            return LefthookWrite(path, replacement)
        block_match, section_end = _locate_block(path, text, layout, hook_name="commit-msg")
        name = (
            "repo-standards-commit-message"
            if "repo-standards-commit-message" not in entries
            else "repo-standards-commit-message-check"
        )
        command = _canonical_commit_message_command(root, runner_prefix=runner_prefix)
        updated = (
            _insert_staged_command(path, text, block_match, section_end, name, run=command)
            if layout == "commands"
            else _insert_staged_job(path, text, block_match, section_end, name, run=command)
        )
        return LefthookWrite(path, updated)
    separator = "" if not text or text.endswith("\n") else "\n"
    addition = (
        "\ncommit-msg:\n"
        "  commands:\n"
        "    repo-standards-commit-message:\n"
        f"      run: {_canonical_commit_message_command(root, runner_prefix=runner_prefix)}\n"
    )
    return LefthookWrite(path, f"{text}{separator}{addition}")


def wire_lefthook_staged_check(root: Path) -> LefthookWrite:
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


def _locate_block(path: Path, text: str, layout: str, *, hook_name: str = "pre-commit") -> _LocatedBlock:
    pre_commit_match = re.search(rf"(?m)^{re.escape(hook_name)}:\s*(?:#.*)?$", text)
    if pre_commit_match is None:
        msg = f"cannot safely wire {path.name}: expected a block-style {hook_name}.{layout} value"
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
    *,
    run: str | None = None,
) -> str:
    block_indent = len(jobs_match.group("indent"))
    child_indent = " " * (block_indent + 2)
    command = _canonical_lefthook_command(path.parent) if run is None else run
    rendered = f"{child_indent}- name: {name}\n{child_indent}  run: {command}\n"
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
    *,
    run: str | None = None,
) -> str:
    command_indent = len(commands_match.group("indent"))
    child_indent = " " * (command_indent + 2)
    command = _canonical_lefthook_command(path.parent) if run is None else run
    rendered = f"{child_indent}{name}:\n{child_indent}  run: {command}\n"
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
    migrated, count = launcher.rewrite_legacy_repository_invocations(value)
    if count:
        value = migrated
    try:
        tokens = shlex.split(value)
    except ValueError:
        return False
    prefix = launcher.repository_argv()
    if _is_exact_standards_argv(tokens):
        prefix = tuple(tokens[: len(launcher.repository_argv())])
    return tuple(tokens[: len(prefix)]) == prefix and tokens[len(prefix) : len(prefix) + 2] == ["check", "--staged"]


def _runs_commit_message_check(value: object) -> bool:
    if not isinstance(value, str) or re.search(r"(?:&&|\|\||[;|`]|\$\()", value):
        return False
    value, _ = launcher.rewrite_legacy_repository_invocations(value)
    try:
        tokens = shlex.split(value)
    except ValueError:
        return False
    prefixes = (
        launcher.repository_argv(),
        launcher.argv(version=manifest.adopted_version()),
    )
    if _is_exact_standards_argv(tokens):
        prefixes = (*prefixes, tuple(tokens[: len(launcher.repository_argv())]))
    return any(
        tuple(tokens[: len(prefix)]) == prefix
        and tokens[len(prefix) :] in (["commit-message"], ["commit-message", "{1}"])
        for prefix in prefixes
    )


def _is_canonical_precommit_commit_message(value: object, *, root: Path, runner_prefix: str | None = None) -> bool:
    if not isinstance(value, str):
        return False
    try:
        tokens = shlex.split(value)
    except ValueError:
        return False
    prefix = launcher.repository_command() if runner_prefix is None else runner_prefix
    prefixes = [shlex.split(prefix)]
    if runner_prefix is None and not manifest.manifest_path(root).exists():
        prefixes.append(list(launcher.argv(version=manifest.adopted_version())))
    return any(tokens == [*candidate, "commit-message"] for candidate in prefixes)


def _is_exact_standards_argv(tokens: list[str]) -> bool:
    prefix = launcher.repository_argv()
    if len(tokens) < len(prefix):
        return False
    candidate = tokens[: len(prefix)]
    return (
        candidate[:6] == list(prefix[:6])
        and re.fullmatch(r"(?:sarj-standards-bootstrap|code-standards)==[0-9]+\.[0-9]+\.[0-9]+", candidate[6])
        is not None
        and candidate[7] == launcher.COMMAND
    )


def _canonical_lefthook_command(root: Path | None = None) -> str:
    if root is not None and (root / "packages" / "standards" / "pyproject.toml").is_file():
        return (
            "uv run --no-config --project packages/standards --frozen code-standards check --staged "
            "--trust-repository-code -- {staged_files}"
        )
    return f"{launcher.repository_command()} check --staged --trust-repository-code -- {{staged_files}}"


def _canonical_commit_message_command(root: Path | None = None, *, runner_prefix: str | None = None) -> str:
    if root is not None and (root / "packages" / "standards" / "pyproject.toml").is_file():
        return "uv run --no-config --project packages/standards --frozen code-standards commit-message {1}"
    prefix = launcher.repository_command() if runner_prefix is None else runner_prefix
    argument = '"{1}"'
    return f"{prefix} commit-message {argument}"


def _lefthook_run_values(value: object, *, depth: int = 0, seen: set[int] | None = None) -> list[str]:
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
