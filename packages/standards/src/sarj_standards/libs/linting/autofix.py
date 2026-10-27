from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, runtime_checkable

from sarj_rule_contracts import AutofixPolicy, RuleDocumentation

from sarj_standards.libs.adoption import manifest, transaction
from sarj_standards.libs.diagnostics import Diagnostic, Location, Severity

from . import runner, textlint
from .policy import Policy


class _Rule(Protocol):
    code: str
    enabled_by_default: bool
    documentation: RuleDocumentation | None


@runtime_checkable
class _Registry(Protocol):
    REGISTRY: Mapping[str, type[_Rule]]


@runtime_checkable
class _Fixer(Protocol):
    def fix_source(self, path: Path, source: str, *, rule_ids: Sequence[str] | None = None) -> str: ...


@dataclass(frozen=True, slots=True)
class _Engine:
    source: str
    paths: Sequence[str]
    codes: Mapping[str, str]
    fix: Callable[[Path, str, Sequence[str]], str]


@dataclass(frozen=True, slots=True)
class _Change:
    path: Path
    original: bytes
    replacement: bytes


@dataclass(frozen=True, slots=True)
class FixResult:
    status: int
    changed: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _Selection:
    formatter: tuple[str, ...]
    native: tuple[str, ...]


def run(
    root: Path,
    paths: Sequence[str],
    *,
    trusted: bool = False,
    eslint: bool = True,
    machine_output: bool = False,
    default_scope: bool = False,
) -> FixResult:
    from sarj_standards.libs.adoption import lifecycle  # ruff: ignore[import-outside-top-level] -- third-party execution is needed only for explicit fix operations.

    policy = Policy.from_manifest(root, manifest.load(root))
    selection = _selection(root, paths, policy=policy, default_scope=default_scope)
    selected = selection.formatter
    targets = tuple(Path(path) for path in selected)
    transaction.validate_targets(root, targets)
    originals = {path: path.read_bytes() for path in targets}
    fix_paths(root, selection.native, policy=policy)
    commands = lifecycle.selected_format_commands(root, selected, trusted=trusted, eslint=eslint)
    status = 0
    for command in commands:
        result = (
            lifecycle.execute((command,), stdout_to_stderr=True) if machine_output else lifecycle.execute((command,))
        )
        result = 2 if result < 0 else result
        status = max(status, result)
        if result > 1:
            break
    return FixResult(status, tuple(path for path, original in originals.items() if path.read_bytes() != original))


def _selection(root: Path, paths: Sequence[str], *, policy: Policy, default_scope: bool) -> _Selection:
    from sarj_standards.libs.adoption import scaffold  # ruff: ignore[import-outside-top-level] -- only default fix discovery needs adopted ecosystem ownership.

    adopted = manifest.load(root) if default_scope else None
    python_roots = None
    if default_scope:
        ecosystems = scaffold.detect(root) if adopted is None else scaffold.detect_adopted(root, adopted)
        python_roots = () if ecosystems.python_root is None else (ecosystems.python_root,)
    grouped = runner.group_format_paths([str(root / path) for path in paths], policy=policy, python_roots=python_roots)
    python = tuple(grouped.python)
    native_other = (*grouped.sql, *grouped.iac, *grouped.text)
    if default_scope and adopted is not None and set(adopted.configs) == {"eslint"}:
        native_other = ()
    return _Selection(
        tuple(
            dict.fromkeys(
                (
                    *python,
                    *grouped.sql,
                    *grouped.iac,
                    *grouped.text,
                    *grouped.typescript,
                    *grouped.shellcheck,
                    *grouped.swift,
                    *grouped.kotlin,
                )
            )
        ),
        tuple(dict.fromkeys((*python, *native_other))),
    )


def selected_paths(root: Path, paths: Sequence[str], *, policy: Policy) -> tuple[str, ...]:
    grouped = runner.group_paths([str(root / path) for path in paths], policy=policy)
    return tuple(
        dict.fromkeys(
            (
                *grouped.python,
                *grouped.sql,
                *grouped.iac,
                *grouped.text,
                *grouped.typescript,
                *grouped.shellcheck,
                *grouped.swift,
                *grouped.kotlin,
            )
        )
    )


def fix_paths(root: Path, paths: Sequence[str], *, policy: Policy | None = None) -> tuple[Path, ...]:
    repository = root.resolve()
    effective = policy if policy is not None else Policy.from_manifest(repository, manifest.load(repository))
    grouped = runner.group_paths([str(repository / path) for path in paths], policy=effective)
    changes = _plan(repository, effective, grouped)
    mutation = transaction.FileTransaction.capture(
        repository, tuple(change.path for change in changes), explicit_only=True, source_writes=True
    )
    # Validate every captured preimage before the first source write.
    for change in changes:
        if mutation.before[change.path].contents != change.original:
            msg = f"planned mutation target changed concurrently: {change.path}; rerun the command"
            raise OSError(msg)
        transaction.assert_expected(repository, change.path, change.original)
    try:
        for change in changes:
            mutation.write_bytes(change.path, change.replacement)
    except BaseException as exc:
        report = mutation.rollback()
        if report.issues:
            exc.add_note(str(report))
        raise
    return tuple(change.path for change in changes)


def _plan(root: Path, policy: Policy, grouped: runner.GroupedPaths) -> tuple[_Change, ...]:
    originals: dict[Path, bytes] = {}
    sources: dict[Path, str] = {}
    encodings: dict[Path, str] = {}
    for engine in _engines(grouped, root):
        for name in engine.paths:
            path = Path(name)
            transaction.validate_targets(root, (path,))
            if path not in originals:
                originals[path] = path.read_bytes()
                encodings[path] = _encoding(path, originals[path])
                sources[path] = originals[path].decode(encodings[path])
            rules = tuple(
                rule_id
                for rule_id, code in engine.codes.items()
                if policy.allows_rule(
                    Diagnostic(code, "", Severity.INFO, engine.source, Location(policy.relative(path)), rule_id)
                )
            )
            if rules:
                sources[path] = engine.fix(path, sources[path], rules)
    return tuple(
        _Change(path, original, fixed)
        for path, original in originals.items()
        if (fixed := sources[path].encode(encodings[path])) != original
    )


def _encoding(path: Path, raw: bytes) -> str:
    if path.suffix.lower() in {".py", ".pyi"}:
        from sarj_python_lint import python_source_encoding  # ruff: ignore[import-outside-top-level] -- Python owns cookie and BOM decoding.

        return python_source_encoding(raw)
    return "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"


def _engines(grouped: runner.GroupedPaths, root: Path) -> tuple[_Engine, ...]:
    engines = [
        _native(package, source, paths)
        for package, source, paths in (
            ("sarj_python_lint", "sarj-python-lint", grouped.python),
            ("sarj_sql_lint", "sarj-sql-lint", grouped.sql),
            ("sarj_iac_lint", "sarj-iac-lint", grouped.iac),
        )
        if paths
    ]
    if grouped.text:

        def fix_text(path: Path, text: str, rules: Sequence[str]) -> str:
            return textlint.fix_source(path, text, rule_ids=rules, root=root)

        engines.append(
            _Engine(
                "sarj-text-lint",
                grouped.text,
                {name: rule.code for name, rule in textlint.REGISTRY.items() if rule.autofix is AutofixPolicy.SAFE},
                fix_text,
            )
        )
    return tuple(engines)


def _native(package: str, source: str, paths: Sequence[str]) -> _Engine:
    registry = import_module(f"{package}.rules")
    fixer = import_module(f"{package}.autofix")
    if not isinstance(registry, _Registry) or not isinstance(fixer, _Fixer):
        msg = f"{package} does not expose the expected safe-fix API"
        raise TypeError(msg)
    codes = {
        name: rule.code
        for name, rule in registry.REGISTRY.items()
        if getattr(rule, "enabled_by_default", True)
        and rule.documentation is not None
        and rule.documentation.autofix is AutofixPolicy.SAFE
    }

    def fix(path: Path, text: str, rules: Sequence[str]) -> str:
        return fixer.fix_source(path, text, rule_ids=rules)

    return _Engine(source, paths, codes, fix)
