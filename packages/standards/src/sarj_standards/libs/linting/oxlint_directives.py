# Remove unused ``eslint-*``/``oxlint-*`` directives that Oxlint reports.
#
# Oxlint 1.91 reports unused directives but ``--fix`` never removes them, so
# this module plans the byte edits itself. For ``rollout.py``, ``plan`` is a
# read-only audit of tracked sources that returns frozen ``SourcePostimage``
# values, ``apply`` writes them transactionally and ``validate`` proves the tree
# still holds them. ``remove_unused_directives`` is the pure edit.
# ``fix_sources`` (``python -m``) applies the same edits to working-tree files
# after ``oxlint --fix``, which leaves unused directives in place.
#
# Edits keep the surrounding source: a directive on its own line removes the
# line, a trailing one removes the comment and the space before it, and a partly
# unused directive loses only the unused rule names. Oxlint reports an unused
# ``/* x-disable */ ... /* x-enable */`` pair at the enable comment, so both
# comments go. Anything else raises instead of guessing.

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed read-only Git metadata queries.
import sys
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Final

import typer

from sarj_standards.libs.adoption import lifecycle, manifest, transaction
from sarj_standards.libs.staged_git import isolated_environment

from . import directive_formatter, native_byte_bridge, oxlint, runner
from .policy import Policy
from .process import ProcessOutput


if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Sequence


_GIT_TIMEOUT: Final = timedelta(seconds=5)
_SOURCE_MODE_MAX: Final = 0o7777
_DIRECTIVE_TOKENS: Final = (b"eslint-disable", b"eslint-enable", b"oxlint-disable", b"oxlint-enable")
_KEYWORD_RE: Final = re.compile(
    r"(?P<lead>\s*)(?P<keyword>(?P<tool>eslint|oxlint)-(?P<kind>disable-next-line|disable-line|disable|enable))"
    r"(?P<rest>(?:\s.*)?)",
    re.DOTALL,
)
_BLOCK_COMMENT_RE: Final = re.compile(rb"/\*.*?\*/", re.DOTALL)
SUPPORTS_DIRECTIVE_REWRITES: Final = os.name == "posix"
_POSIX_ONLY: Final = "canonical directive rewrites require POSIX ownership and private-file permission checks"


@dataclass(frozen=True, slots=True)
class SourcePostimage:
    before: bytes
    after: bytes
    mode: int


@dataclass(frozen=True, slots=True)
class UnusedDirective:
    # One Oxlint unused-directive report: its message and UTF-8 byte span.
    message: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Directive:
    start: int
    end: int
    block: bool
    tool: str
    kind: str
    rules: tuple[str, ...]
    head: str
    tail: str


@dataclass(frozen=True, slots=True)
class _Edit:
    start: int
    end: int
    replacement: bytes = b""


@dataclass(frozen=True, slots=True)
class _Reported:
    directive: _Directive
    # The unused rule name, or None when the whole directive is unused.
    rule: str | None


@dataclass(frozen=True, slots=True)
class _File:
    contents: bytes
    mode: int
    identity: tuple[int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class _Index:
    path: Path
    file: _File
    entries: bytes
    flags: bytes


@dataclass(frozen=True, slots=True)
class _PlanInputs:
    index: _Index
    tracked: Mapping[str, str]
    originals: Mapping[str, _File]
    selected: Mapping[str, _File]


def remove_unused_directives(source: bytes, unused: Iterable[UnusedDirective]) -> bytes:
    deleted: dict[int, _Directive] = {}
    dropped: dict[int, tuple[_Directive, set[str]]] = {}
    for report in unused:
        reported = _reported(source, report)
        directive = reported.directive
        # Oxlint reports an unused block disable at its enable comment; edit both comments of the pair.
        pair = report.message.startswith(f"Unused {directive.tool}-disable") and directive.kind == "enable"
        for item in (directive, _opening(source, directive)) if pair else (directive,):
            if reported.rule is None:
                deleted[item.start] = item
            else:
                dropped.setdefault(item.start, (item, set()))[1].add(reported.rule)
    edits = [_Edit(item.start, item.end) for item in deleted.values()]
    edits.extend(_without(directive, rules) for start, (directive, rules) in dropped.items() if start not in deleted)
    result = source
    for edit in sorted(edits, key=lambda item: item.start, reverse=True):
        result = (
            result[: edit.start] + edit.replacement + result[edit.end :]
            if edit.replacement
            else _delete(result, edit.start, edit.end)
        )
    return result


def _reported(source: bytes, report: UnusedDirective) -> _Reported:
    match = oxlint.UNUSED_DIRECTIVE_RE.fullmatch(report.message)
    if match is None:
        msg = f"not an Oxlint unused-directive report: {report.message!r}"
        raise ValueError(msg)
    directive = _directive_at(source, report.start)
    rule = match["disabled"] or match["enabled"]
    if rule is not None and (source[report.start : report.end] != rule.encode("utf-8") or rule not in directive.rules):
        msg = f"unused rule span does not name {rule!r} in its directive"
        raise ValueError(msg)
    return _Reported(directive, rule)


def _without(directive: _Directive, rules: set[str]) -> _Edit:
    kept = tuple(rule for rule in directive.rules if rule not in rules)
    text = f"{directive.head} {', '.join(kept)}{directive.tail}" if kept else ""
    return _Edit(directive.start, directive.end, text.encode("utf-8"))


def _directive_at(source: bytes, offset: int) -> _Directive:
    line_start = source.rfind(b"\n", 0, offset) + 1
    window = source[line_start : offset + 2]
    opening = max(window.rfind(b"//"), window.rfind(b"/*"))
    if opening < 0:
        msg = "unused directive span is not inside a comment"
        raise ValueError(msg)
    start = line_start + opening
    block = source.startswith(b"/*", start)
    if block:
        close = source.find(b"*/", start + 2)
        if close < 0:
            msg = "unused directive block comment is not closed"
            raise ValueError(msg)
        end, body = close + 2, source[start + 2 : close]
    else:
        newline = source.find(b"\n", start)
        end = len(source) if newline < 0 else newline
        if source[start:end].endswith(b"\r"):
            end -= 1
        body = source[start + 2 : end]
    if end <= offset:
        msg = "unused directive span is not inside a comment"
        raise ValueError(msg)
    return _parse_directive(start, end, block=block, body=body.decode("utf-8"))


def _parse_directive(start: int, end: int, *, block: bool, body: str) -> _Directive:
    match = _KEYWORD_RE.fullmatch(body)
    if match is None:
        msg = "unused directive comment is not an eslint/oxlint directive"
        raise ValueError(msg)
    rest = match["rest"]
    description = rest.find(" --")
    listed, description_text = (rest, "") if description < 0 else (rest[:description], rest[description:])
    trailing = listed[len(listed.rstrip()) :]
    rules = tuple(rule for rule in (part.strip() for part in listed.split(",")) if rule)
    opener, closer = ("/*", "*/") if block else ("//", "")
    return _Directive(
        start,
        end,
        block,
        match["tool"],
        match["kind"],
        rules,
        f"{opener}{match['lead']}{match['keyword']}",
        f"{trailing if not description_text else ''}{description_text}{closer}",
    )


def _opening(source: bytes, enable: _Directive) -> _Directive:
    for match in reversed(list(_BLOCK_COMMENT_RE.finditer(source, 0, enable.start))):
        try:
            candidate = _parse_directive(
                match.start(), match.end(), block=True, body=match.group()[2:-2].decode("utf-8")
            )
        except ValueError:
            continue
        if candidate.tool == enable.tool and candidate.kind == "disable":
            if not enable.rules or set(candidate.rules) == set(enable.rules):
                return candidate
            break
    msg = f"no {enable.tool}-disable comment opens the unused {enable.tool}-enable block"
    raise ValueError(msg)


def _delete(source: bytes, start: int, end: int) -> bytes:
    line_start = source.rfind(b"\n", 0, start) + 1
    newline = source.find(b"\n", end)
    line_end = len(source) if newline < 0 else newline
    before, after = source[line_start:start], source[end:line_end]
    if not before.strip() and not after.strip():
        if newline >= 0:
            return source[:line_start] + source[newline + 1 :]
        return source[: max(line_start - 1, 0)] if line_start else b""
    if not after.strip():
        return source[: line_start + len(before.rstrip())] + source[end:]
    return source[:start] + source[end + len(after) - len(after.lstrip()) :]


def plan(
    root: Path,
    paths: Sequence[str],
    *,
    run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
    owned: Collection[str] = (),
) -> Mapping[str, SourcePostimage]:
    # `owned` names untracked files the caller already admitted that the formatter may read, such
    # as the oxfmt configs a migrating update seeded; every other formatter input must be tracked.
    if not paths:
        return MappingProxyType({})
    if not SUPPORTS_DIRECTIVE_REWRITES:
        raise ValueError(_POSIX_ONLY)
    repository = root.resolve()
    inputs = _collect_plan_inputs(repository, paths)
    selection = oxlint.select_oxlint_commands(repository, inputs.selected, label="directive-only")
    if selection.unowned_count:
        msg = "directive-fix inputs have no canonical Oxlint project owner"
        raise ValueError(msg)
    rewrites: dict[str, SourcePostimage] = {}
    covered: set[str] = set()
    runtimes: dict[Path, directive_formatter.RuntimeProof] = {}
    formatter_inputs = frozenset((*inputs.tracked, *owned))
    try:
        for command in selection.commands:
            operands = frozenset(path.relative_to(repository).as_posix() for path in oxlint.command_files(command))
            if covered & operands or not operands <= inputs.selected.keys():
                msg = "canonical Oxlint selection contains unknown or duplicate source operands"
                raise ValueError(msg)
            covered.update(operands)
            for relative, postimage in _audit(repository, command, inputs.selected, run=run).items():
                rewrites[relative] = _formatted(
                    repository, relative, postimage, tracked=formatter_inputs, runtimes=runtimes, run=run
                )
        if covered != set(inputs.selected):
            msg = "canonical Oxlint selection did not cover every eligible directive input"
            raise ValueError(msg)
    finally:
        _unchanged(repository, inputs.index, inputs.originals)
    return MappingProxyType(rewrites)


def fix_sources(root: Path, paths: Sequence[str]) -> int:
    from .external import local_node_binary_argv, redact_message  # ruff: ignore[import-outside-top-level] -- external imports oxlint, which this module imports.

    if not SUPPORTS_DIRECTIVE_REWRITES:
        sys.stderr.write(f"oxlint unused directives: {_POSIX_ONLY}\n")
        return 2
    repository = root.resolve()
    files = _directive_sources(repository, paths)
    selection = oxlint.select_oxlint_commands(repository, files, label="unused directives")
    batch = transaction.FileTransaction.capture(
        repository, tuple(repository / name for name in files), explicit_only=True, source_writes=True
    )
    try:
        for command in selection.commands:
            argv = local_node_binary_argv("oxlint", command.argv, command.cwd, repository) or tuple(command.argv)
            local = lifecycle.Command(command.label, argv, command.cwd)
            for relative, postimage in _audit(repository, local, files, run=_run).items():
                transaction.assert_expected(repository, repository / relative, postimage.before)
                batch.write_bytes(repository / relative, postimage.after)
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as error:
        rollback = batch.rollback().render()
        sys.stderr.write(f"oxlint unused directives: {redact_message(str(error), repository)}\n")
        if rollback:
            sys.stderr.write(f"{rollback}\n")
        return 2
    return 0


def _directive_sources(repository: Path, paths: Sequence[str]) -> dict[str, _File]:
    files: dict[str, _File] = {}
    for raw in paths:
        path = Path(raw) if Path(raw).is_absolute() else repository / raw
        if oxlint.is_oxlint_source(path) and path.is_file():
            current = _read(path)
            if any(token in current.contents for token in _DIRECTIVE_TOKENS):
                files[path.resolve().relative_to(repository).as_posix()] = current
    return files


def _run(command: lifecycle.Command) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed Oxlint argv from select_oxlint_commands.
        tuple(command.argv), cwd=command.cwd, capture_output=True, text=True, check=False, timeout=600
    )


def _audit(
    root: Path,
    command: lifecycle.Command,
    selected: Mapping[str, _File],
    *,
    run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
) -> dict[str, SourcePostimage]:
    environment = oxlint.oxlint_environment(command.cwd, root)
    with oxlint.selected_config(command, oxlint.OxlintRequest()) as configured:
        argv = oxlint.with_options(
            configured.argv, "-f", "json", "--type-aware", "--report-unused-disable-directives-severity=error"
        )
        # The rollout runner owns the environment, so pass the typed-lint binary in argv.
        variables = (f"{key}={value}" for key, value in environment.items())
        completed = run(lifecycle.Command(command.label, ("env", *variables, *argv), command.cwd))
    result = oxlint.read_oxlint(
        ProcessOutput(completed.returncode, completed.stdout, completed.stderr),
        root=root,
        cwd=command.cwd,
        selected=False,
    )
    if result.issues:
        msg = f"Oxlint failed before producing a directive-only plan: {result.issues[0].message}"
        raise ValueError(msg)
    unused: dict[str, list[UnusedDirective]] = {}
    for diagnostic in result.diagnostics:
        region = diagnostic.location.region
        if diagnostic.rule_id != oxlint.UNUSED_DIRECTIVE or region is None:
            continue
        unused.setdefault(diagnostic.location.path, []).append(
            UnusedDirective(diagnostic.message, region.start.byte_offset, region.end.byte_offset)
        )
    rewrites: dict[str, SourcePostimage] = {}
    for relative, reports in unused.items():
        original = selected.get(relative)
        if original is None:
            msg = f"Oxlint reported an unused directive outside the plan: {relative}"
            raise ValueError(msg)
        after = remove_unused_directives(original.contents, reports)
        _text(after)
        if after != original.contents:
            rewrites[relative] = SourcePostimage(original.contents, after, original.mode)
    return rewrites


def _formatted(
    root: Path,
    relative: str,
    postimage: SourcePostimage,
    *,
    tracked: Collection[str],
    runtimes: dict[Path, directive_formatter.RuntimeProof],
    run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
) -> SourcePostimage:
    # Deleting a directive can leave layout oxfmt would change; format the postimage the way the
    # project's oxfmt config would, unless the source already differs from it (that formatter debt
    # belongs to the rollout's own oxfmt commit, not to directive cleanup).
    if not directive_formatter.configured(root, relative):
        return postimage
    owner = directive_formatter.select(
        root, relative, tracked, runtimes=runtimes, _node=lambda cwd: native_byte_bridge.resolve_node(cwd, run=run)
    )

    def format_bytes(source: bytes) -> bytes:
        directive_formatter.validate(owner)
        result = native_byte_bridge.run_bytes(owner.invocation, source, run=run)
        directive_formatter.validate(owner)
        if result.returncode != 0:
            msg = f"oxfmt failed to format the directive-fix postimage of {relative}"
            raise ValueError(msg)
        _text(result.stdout)
        return result.stdout

    if format_bytes(postimage.before) != postimage.before:
        return postimage
    normalized = format_bytes(postimage.after)
    if format_bytes(normalized) != normalized:
        msg = f"oxfmt did not reach a fixed point on {relative}"
        raise ValueError(msg)
    return SourcePostimage(postimage.before, normalized, postimage.mode)


def _collect_plan_inputs(repository: Path, paths: Sequence[str]) -> _PlanInputs:
    index = _index(repository)
    tracked = _tracked(index)
    originals: dict[str, _File] = {}
    selected: dict[str, _File] = {}
    adopted = manifest.load(repository)
    policy = Policy.from_manifest(repository, adopted)
    enabled = adopted is None or lifecycle.TYPESCRIPT_CAPABILITY in adopted.enabled_capabilities
    for relative in paths:
        path = _path(repository, relative)
        if relative in originals or tracked.get(relative) not in {"100644", "100755"}:
            msg = "directive-fix input is duplicate, untracked or not a Git source blob"
            raise ValueError(msg)
        original = _read(path)
        originals[relative] = original
        if (
            enabled
            and oxlint.is_oxlint_source(path)
            and policy.allows_path(relative)
            and runner.accepts_hook_path(path, root=repository)
            and any(token in original.contents for token in _DIRECTIVE_TOKENS)
        ):
            _text(original.contents)
            selected[relative] = original
    return _PlanInputs(index, tracked, originals, selected)


def apply(root: Path, expected: Mapping[str, SourcePostimage]) -> None:
    repository = root.resolve()
    frozen = dict(expected)
    index = _index(repository) if frozen else None
    paths = _expected(repository, frozen, after=False)
    batch = transaction.FileTransaction.capture(
        repository, tuple(paths.values()), explicit_only=True, source_writes=True
    )
    _expected(repository, frozen, after=False)
    try:
        _write_postimages(repository, frozen, paths=paths, batch=batch, index=index)
    except BaseException:
        report = batch.rollback()
        if not report.ok:
            msg = f"directive-fix rollback could not restore its owned writes: {report.render()}"
            raise OSError(msg) from None
        raise


def _write_postimages(
    root: Path,
    expected: Mapping[str, SourcePostimage],
    *,
    paths: Mapping[str, Path],
    batch: transaction.FileTransaction,
    index: _Index | None,
) -> None:
    for relative, path in paths.items():
        if expected[relative].before != expected[relative].after:
            batch.write_bytes(path, expected[relative].after)
    validate(root, expected)
    if index is not None and _index(root) != index:
        msg = "Git index changed while applying directive-fix source postimages"
        raise ValueError(msg)


def validate(root: Path, expected: Mapping[str, SourcePostimage]) -> frozenset[str]:
    frozen = dict(expected)
    _expected(root.resolve(), frozen, after=True)
    return frozenset(frozen)


def _expected(root: Path, expected: Mapping[str, SourcePostimage], *, after: bool) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    tracked = _tracked(_index(root)) if expected else {}
    for relative, postimage in expected.items():
        path = _path(root, relative)
        if tracked.get(relative) not in {"100644", "100755"}:
            msg = f"directive-fix target is no longer a tracked source blob: {relative}"
            raise ValueError(msg)
        if isinstance(postimage.mode, bool) or not 0 <= postimage.mode <= _SOURCE_MODE_MAX:
            msg = "invalid directive-fix source mode"
            raise ValueError(msg)
        _text(postimage.before)
        _text(postimage.after)
        current = _read(path)
        if current.contents != (postimage.after if after else postimage.before) or current.mode != postimage.mode:
            msg = f"directive-fix {'postimage' if after else 'preimage'} differs from the frozen plan: {relative}"
            raise ValueError(msg)
        paths[relative] = path
    return paths


def _read(path: Path) -> _File:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or path.is_symlink() or path.is_junction() or before.st_nlink != 1:
        msg = f"directive-fix input is not an unlinked regular file: {path}"
        raise ValueError(msg)
    contents = path.read_bytes()
    after = path.lstat()
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        msg = f"directive-fix input changed while reading: {path}"
        raise ValueError(msg)
    return _File(contents, stat.S_IMODE(before.st_mode), identity)


def _path(root: Path, relative: str) -> Path:
    value = PurePosixPath(relative)
    if (
        not relative
        or "\0" in relative
        or value.is_absolute()
        or value.as_posix() != relative
        or any(part in {".", "..", ".git"} for part in value.parts)
    ):
        msg = f"directive-fix path is not canonical and repository-relative: {relative}"
        raise ValueError(msg)
    path = root / relative
    transaction.validate_targets(root, (path,))
    return path


def _index(root: Path) -> _Index:
    top = Path(os.fsdecode(_git(root, "rev-parse", "--show-toplevel").removesuffix(b"\n")))
    if top.resolve() != root:
        msg = "directive-fix root is not the Git worktree root"
        raise ValueError(msg)
    path = Path(
        os.fsdecode(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "index").removesuffix(b"\n"))
    )
    before = _read(path)
    entries = _git(root, "ls-files", "--cached", "--stage", "-z")
    flags = _git(root, "ls-files", "-v", "-z")
    if _read(path) != before:
        msg = "Git index changed during directive-fix planning"
        raise ValueError(msg)
    return _Index(path, before, entries, flags)


def _git(root: Path, *arguments: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        msg = "Git is required to establish tracked directive-fix ownership"
        raise ValueError(msg)
    environment = isolated_environment()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed executable and argv.
            (
                executable,
                "--no-replace-objects",
                "--no-lazy-fetch",
                "--no-optional-locks",
                "--literal-pathspecs",
                "-C",
                str(root),
                *arguments,
            ),
            env=environment,
            capture_output=True,
            check=False,
            timeout=_GIT_TIMEOUT.total_seconds(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        msg = "Git metadata discovery failed during directive-fix planning"
        raise ValueError(msg) from exc
    if result.returncode != 0:
        msg = "Git could not establish tracked directive-fix ownership"
        raise ValueError(msg)
    return result.stdout


def _tracked(index: _Index) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in index.entries.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, _blob, stage = header.decode("ascii").split()
        relative = os.fsdecode(name)
        if stage != "0" or relative in result:
            msg = "unmerged or duplicate Git index entries prevent directive-fix planning"
            raise ValueError(msg)
        result[relative] = mode
    return result


def _text(contents: bytes) -> str:
    if b"\0" in contents:
        msg = "binary content is outside directive-fix ownership"
        raise ValueError(msg)
    return contents.decode("utf-8")


def _unchanged(root: Path, index: _Index, files: Mapping[str, _File]) -> None:
    if _index(root) != index or any(_read(_path(root, name)) != original for name, original in files.items()):
        msg = "source or Git index changed during directive-only planning"
        raise ValueError(msg)


def main(
    root: Annotated[Path, typer.Option("--root")],
    paths: Annotated[list[str], typer.Argument()],
) -> None:
    raise typer.Exit(fix_sources(root, paths))


if __name__ == "__main__":
    typer.run(main)
