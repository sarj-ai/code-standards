from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed read-only Git metadata queries.
from types import MappingProxyType
from typing import TYPE_CHECKING

from sarj_standards.libs.adoption import lifecycle, manifest, transaction
from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.staged_git import isolated_environment

from . import directive_formatter, native_byte_bridge, runner
from .policy import Policy


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pydantic import JsonValue


_GIT_TIMEOUT = timedelta(seconds=5)
_ERROR_SEVERITY = 2
_NATIVE_ERROR_DETAIL_LIMIT = 4000
_SOURCE_MODE_MAX = 0o7777
SUPPORTS_DIRECTIVE_REWRITES = os.name == "posix"
type Diagnostic = tuple[bool, bool, str, int, str, str]


@dataclass(frozen=True, slots=True)
class NativeProjection:
    native: bytes
    normalized: bytes
    formatter: directive_formatter.FormatterOwner
    eslint: directive_formatter.FormatterOwner
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class SourcePostimage:
    before: bytes
    after: bytes
    mode: int
    projection: NativeProjection | None = None


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
class _Counts:
    errors: int
    warnings: int


@dataclass(frozen=True, slots=True)
class _PlanInputs:
    index: _Index
    tracked: Mapping[str, str]
    originals: Mapping[str, _File]
    selected: Mapping[str, _File]


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
        msg = "source or Git index changed during directive-only dry-run planning"
        raise ValueError(msg)


def _postimages(
    root: Path,
    completed: subprocess.CompletedProcess[str],
    operands: frozenset[str],
    selected: Mapping[str, _File],
    diagnostics: dict[str, tuple[Diagnostic, ...]] | None = None,
) -> dict[str, SourcePostimage]:
    if completed.returncode not in {0, 1}:
        msg = f"native ESLint failed before producing a directive-only plan (exit {completed.returncode})"
        detail = completed.stderr.strip() or completed.stdout.strip()
        if detail:
            msg = f"{msg}:\n{detail[:_NATIVE_ERROR_DETAIL_LIMIT]}"
        raise ValueError(msg)
    try:
        parsed = parse_unique_json(completed.stdout)
    except RecursionError as exc:
        msg = "ESLint JSON output is too deeply nested"
        raise ValueError(msg) from exc
    if type(parsed) is not list:
        msg = "ESLint JSON output must be a result array"
        raise ValueError(msg)
    seen: set[str] = set()
    rewrites: dict[str, SourcePostimage] = {}
    errors = 0
    for result in parsed:
        if type(result) is not dict:
            msg = "invalid ESLint JSON result"
            raise ValueError(msg)
        relative = _result_path(root, result, operands, seen)
        seen.add(relative)
        counts = _result_counts(result)
        if diagnostics is not None:
            diagnostics[relative] = _diagnostics(result)
        errors += counts.errors
        try:
            postimage = _result_postimage(relative, result, selected)
        except TypeError as exc:
            msg = "ESLint returned a nontext source postimage"
            raise ValueError(msg) from exc
        if postimage is not None:
            rewrites[relative] = postimage
    if seen != operands or bool(errors) != (completed.returncode == 1):
        msg = "ESLint result coverage or exit status is inconsistent"
        raise ValueError(msg)
    return rewrites


def _result_path(root: Path, result: Mapping[str, JsonValue], operands: frozenset[str], seen: set[str]) -> str:
    name = result.get("filePath")
    if (
        not isinstance(name, str)
        or not Path(name).is_absolute()
        or Path(name).as_posix() != name
        or ".." in Path(name).parts
    ):
        msg = "ESLint returned a nonabsolute or malformed result path"
        raise ValueError(msg)
    relative = Path(name).relative_to(root).as_posix()
    if relative not in operands or relative in seen or _path(root, relative) != Path(name):
        msg = "ESLint returned an unknown, duplicate or noncanonical result path"
        raise ValueError(msg)
    return relative


def _result_counts(result: Mapping[str, JsonValue]) -> _Counts:
    counts = _messages(result)
    if (
        _count(result, "fatalErrorCount")
        or _count(result, "errorCount") != counts.errors
        or _count(result, "warningCount") != counts.warnings
    ):
        msg = "fatal or inconsistent ESLint diagnostic counts"
        raise ValueError(msg)
    if _count(result, "fixableErrorCount") > counts.errors or _count(result, "fixableWarningCount") > counts.warnings:
        msg = "inconsistent ESLint fixable diagnostic counts"
        raise ValueError(msg)
    return counts


def _count(result: Mapping[str, JsonValue], name: str) -> int:
    value = result.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        msg = f"invalid ESLint JSON {name}"
        raise ValueError(msg)
    return value


def _messages(result: Mapping[str, JsonValue]) -> _Counts:
    messages = result.get("messages")
    if type(messages) is not list:
        msg = "invalid ESLint JSON messages"
        raise ValueError(msg)
    errors = warnings = 0
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("message"), str) or "ruleId" not in message:
            msg = "invalid ESLint JSON message"
            raise ValueError(msg)
        severity = message.get("severity")
        if (
            not isinstance(severity, int)
            or isinstance(severity, bool)
            or severity not in {1, 2}
            or message.get("fatal", False) is not False
        ):
            msg = "fatal or malformed ESLint diagnostic prevents directive-fix planning"
            raise ValueError(msg)
        rule = message.get("ruleId")
        if rule is not None and not isinstance(rule, str):
            msg = "invalid ESLint JSON ruleId"
            raise ValueError(msg)
        errors += severity == _ERROR_SEVERITY
        warnings += severity == 1
    return _Counts(errors, warnings)


def _result_postimage(
    relative: str, result: Mapping[str, JsonValue], selected: Mapping[str, _File]
) -> SourcePostimage | None:
    if "output" not in result:
        return None
    output = result["output"]
    if not isinstance(output, str):
        msg = "ESLint returned a nontext source postimage"
        raise TypeError(msg)
    after = output.encode("utf-8")
    _text(after)
    original = selected[relative]
    if after == original.contents:
        return None
    return SourcePostimage(original.contents, after, original.mode)


def _diagnostics(result: Mapping[str, JsonValue]) -> tuple[Diagnostic, ...]:
    fingerprints: list[Diagnostic] = []
    for key, suppressed in (("messages", False), ("suppressedMessages", True)):
        messages = result.get(key)
        if type(messages) is not list:
            msg = "invalid ESLint JSON diagnostic list"
            raise ValueError(msg)
        for message in messages:
            if type(message) is not dict:
                msg = "invalid ESLint JSON diagnostic fingerprint"
                raise ValueError(msg)
            fingerprints.append(_diagnostic_fingerprint(message, suppressed=suppressed))
    return tuple(sorted(fingerprints))


def _diagnostic_fingerprint(message: Mapping[str, JsonValue], *, suppressed: bool) -> Diagnostic:
    rule, severity, text, identifier = (
        message.get("ruleId"),
        message.get("severity"),
        message.get("message"),
        message.get("messageId", ""),
    )
    if (
        (rule is not None and not isinstance(rule, str))
        or not isinstance(severity, int)
        or isinstance(severity, bool)
        or severity not in {1, 2}
    ):
        msg = "invalid ESLint JSON diagnostic fingerprint"
        raise ValueError(msg)
    if not isinstance(text, str) or not isinstance(identifier, str) or message.get("fatal", False) is not False:
        msg = "invalid ESLint JSON diagnostic fingerprint"
        raise ValueError(msg)
    return (suppressed, rule is None, rule or "", severity, text, identifier)


def plan(
    root: Path,
    paths: Sequence[str],
    *,
    run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
) -> Mapping[str, SourcePostimage]:
    if not paths:
        return MappingProxyType({})
    if not SUPPORTS_DIRECTIVE_REWRITES:
        msg = "canonical directive rewrites require POSIX ownership and private-file permission checks"
        raise ValueError(msg)
    repository = root.resolve()
    inputs = _collect_plan_inputs(repository, paths)
    selection = lifecycle.select_eslint_commands(
        repository, inputs.selected, label="directive-only", _directive_dry_run=True
    )
    if selection.unowned_count:
        msg = "directive-fix inputs have no canonical ESLint project owner"
        raise ValueError(msg)
    rewrites: dict[str, SourcePostimage] = {}
    covered: set[str] = set()
    runtimes: dict[Path, directive_formatter.RuntimeProof] = {}
    nodes: dict[Path, Path] = {}
    try:
        for command in selection.commands:
            _plan_command(
                repository,
                command,
                inputs,
                runtimes=runtimes,
                nodes=nodes,
                covered=covered,
                rewrites=rewrites,
                run=run,
            )
        if covered != set(inputs.selected):
            msg = "canonical ESLint selection did not cover every eligible directive input"
            raise ValueError(msg)
    finally:
        _unchanged(repository, inputs.index, inputs.originals)
    return MappingProxyType(rewrites)


def _collect_plan_inputs(repository: Path, paths: Sequence[str]) -> _PlanInputs:
    index = _index(repository)
    tracked = _tracked(index)
    originals: dict[str, _File] = {}
    selected: dict[str, _File] = {}
    adopted = manifest.load(repository)
    policy = Policy.from_manifest(repository, adopted)
    eslint_enabled = adopted is None or "eslint" in adopted.enabled_capabilities
    for relative in paths:
        path = _path(repository, relative)
        if relative in originals or tracked.get(relative) not in {"100644", "100755"}:
            msg = "directive-fix input is duplicate, untracked or not a Git source blob"
            raise ValueError(msg)
        original = _read(path)
        originals[relative] = original
        if (
            eslint_enabled
            and lifecycle.is_eslint_source(path)
            and policy.allows_path(relative)
            and runner.accepts_hook_path(path, root=repository)
        ):
            _text(original.contents)
            if b"eslint-disable" in original.contents or b"eslint-enable" in original.contents:
                selected[relative] = original
    return _PlanInputs(index, tracked, originals, selected)


def _plan_command(
    repository: Path,
    command: lifecycle.Command,
    inputs: _PlanInputs,
    *,
    runtimes: dict[Path, directive_formatter.RuntimeProof],
    nodes: dict[Path, Path],
    covered: set[str],
    rewrites: dict[str, SourcePostimage],
    run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
) -> None:
    operands = _operands(repository, command, inputs.selected)
    if covered & operands:
        msg = "canonical ESLint selection contains duplicate source operands"
        raise ValueError(msg)
    covered.update(operands)
    owners = _owners(repository, command, operands, tracked=inputs.tracked, runtimes=runtimes, nodes=nodes, run=run)
    completed = run(command)
    _unchanged(repository, inputs.index, inputs.originals)
    diagnostics: dict[str, tuple[Diagnostic, ...]] = {}
    proposed = _postimages(repository, completed, operands, inputs.selected, diagnostics)
    _normalize_proposals(
        repository,
        command,
        inputs,
        owners=owners,
        proposed=proposed,
        diagnostics=diagnostics,
        rewrites=rewrites,
        run=run,
    )


def _operands(root: Path, command: lifecycle.Command, selected: Mapping[str, _File]) -> frozenset[str]:
    arguments = tuple(command.argv)
    start = arguments.index("--fix-dry-run")
    separator = arguments.index("--", start)
    if arguments[start:separator] != ("--fix-dry-run", "--fix-type", "directive", "--format", "json", "--no-cache"):
        msg = "directive-fix command differs from the canonical dry-run mode"
        raise ValueError(msg)
    paths: set[str] = set()
    for operand in arguments[separator + 1 :]:
        absolute = command.cwd / operand
        relative = absolute.resolve().relative_to(root).as_posix()
        if relative not in selected or relative in paths or _path(root, relative) != absolute.resolve():
            msg = "directive-fix command contains an unknown or duplicate operand"
            raise ValueError(msg)
        paths.add(relative)
    if not paths:
        msg = "directive-fix commands must contain explicit file operands"
        raise ValueError(msg)
    return frozenset(paths)


def _owners(
    root: Path,
    command: lifecycle.Command,
    operands: frozenset[str],
    *,
    tracked: Mapping[str, str],
    runtimes: dict[Path, directive_formatter.RuntimeProof],
    nodes: dict[Path, Path],
    run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
) -> dict[str, tuple[directive_formatter.FormatterOwner, directive_formatter.FormatterOwner] | ValueError]:
    prepared: dict[str, tuple[directive_formatter.FormatterOwner, directive_formatter.FormatterOwner] | ValueError] = {}

    def project_node(cwd: Path) -> Path:
        selected = nodes.get(cwd)
        if selected is None:
            selected = native_byte_bridge.resolve_node(cwd, run=run)
            nodes[cwd] = selected
        return selected

    for relative in operands:
        try:
            prepared[relative] = (
                directive_formatter.select(root, relative, tracked, runtimes=runtimes, _node=project_node),
                directive_formatter.eslint(root, command.cwd, relative, tracked, runtimes=runtimes, _node=project_node),
            )
        except (OSError, TypeError, ValueError) as exc:
            # A matching string can be ordinary source text. Ownership is required only if native ESLint proposes an edit.
            prepared[relative] = ValueError(str(exc))
    return prepared


def _normalize_proposals(
    repository: Path,
    command: lifecycle.Command,
    inputs: _PlanInputs,
    *,
    owners: Mapping[str, tuple[directive_formatter.FormatterOwner, directive_formatter.FormatterOwner] | ValueError],
    proposed: Mapping[str, SourcePostimage],
    diagnostics: Mapping[str, tuple[Diagnostic, ...]],
    rewrites: dict[str, SourcePostimage],
    run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
) -> None:
    for relative, postimage in proposed.items():
        if relative in rewrites:
            msg = "ESLint selected one source path more than once"
            raise ValueError(msg)
        ownership = owners[relative]
        if isinstance(ownership, ValueError):
            raise ownership
        formatter, eslint = ownership
        directive_formatter.validate(formatter)
        directive_formatter.validate(eslint)
        rewrites[relative] = _normalize(
            repository,
            relative,
            postimage,
            command=command,
            formatter=formatter,
            eslint=eslint,
            diagnostics=diagnostics[relative],
            run=run,
        )
        _unchanged(repository, inputs.index, inputs.originals)


def _normalize(
    root: Path,
    relative: str,
    postimage: SourcePostimage,
    *,
    command: lifecycle.Command,
    formatter: directive_formatter.FormatterOwner,
    eslint: directive_formatter.FormatterOwner,
    diagnostics: tuple[Diagnostic, ...],
    run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
) -> SourcePostimage:
    if _formatted(formatter, postimage.before, run) != postimage.before:
        msg = "directive cleanup cannot absorb pre-existing project formatter debt"
        raise ValueError(msg)
    normalized = _formatted(formatter, postimage.after, run)
    if _formatted(formatter, normalized, run) != normalized:
        msg = "project-owned formatter did not reach a native fixed point"
        raise ValueError(msg)
    directive_formatter.validate(eslint)
    repeated = native_byte_bridge.run_bytes(eslint.invocation, normalized, run=run)
    directive_formatter.validate(eslint)
    completed = subprocess.CompletedProcess(
        command.argv,
        repeated.returncode,
        repeated.stdout.decode("utf-8", errors="strict" if repeated.returncode in {0, 1} else "replace"),
        repeated.stderr.decode("utf-8", errors="replace"),
    )
    observed: dict[str, tuple[Diagnostic, ...]] = {}
    selected = {relative: _File(normalized, postimage.mode, (0, 0, 0, 0, 0))}
    if _postimages(root, completed, frozenset({relative}), selected, observed) or observed.get(relative) != diagnostics:
        msg = "formatter projection changed genuine ESLint findings or left another directive edit"
        raise ValueError(msg)
    proof = NativeProjection(postimage.after, normalized, formatter, eslint, diagnostics)
    return SourcePostimage(postimage.before, normalized, postimage.mode, proof)


def _formatted(
    owner: directive_formatter.FormatterOwner,
    source: bytes,
    run: Callable[[lifecycle.Command], subprocess.CompletedProcess[str]],
) -> bytes:
    directive_formatter.validate(owner)
    result = native_byte_bridge.run_bytes(owner.invocation, source, run=run)
    directive_formatter.validate(owner)
    if result.returncode != 0:
        msg = "project-owned native formatter failed to produce a source postimage"
        raise ValueError(msg)
    _text(result.stdout)
    return result.stdout


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
        if postimage.projection is not None:
            if postimage.projection.normalized != postimage.after:
                msg = "directive formatter proof differs from its frozen source postimage"
                raise ValueError(msg)
            directive_formatter.validate(postimage.projection.formatter)
            directive_formatter.validate(postimage.projection.eslint)
        current = _read(path)
        if current.contents != (postimage.after if after else postimage.before) or current.mode != postimage.mode:
            msg = (
                f"directive-fix {'postimage' if after else 'preimage'} differs from the frozen native plan: {relative}"
            )
            raise ValueError(msg)
        paths[relative] = path
    return paths


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
