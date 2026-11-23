from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from repo_standards.repository import GitIdentity
from sarj_rule_contracts import AutofixPolicy, RuleDocumentation

from sarj_standards.libs.adoption import manifest, transaction
from sarj_standards.libs.diagnostics import Diagnostic, Location, Severity

from . import runner, textlint
from .policy import Policy


if TYPE_CHECKING:
    from sarj_standards.libs.adoption.lifecycle import Command


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
class _ModuleInputs:
    inputs: Mapping[Path, bytes]
    directories: Mapping[Path, tuple[str, ...]]
    index: GitIdentity | None = None


@dataclass(frozen=True, slots=True)
class _FixPlan:
    changes: tuple[_Change, ...]
    inputs: Mapping[Path, bytes]
    directories: Mapping[Path, tuple[str, ...]]
    index: GitIdentity | None = None


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
    typescript: bool = True,
    machine_output: bool = False,
    default_scope: bool = False,
    format_only_paths: frozenset[str] = frozenset(),
    staged: bool = False,
) -> FixResult:
    from sarj_standards.libs.adoption import lifecycle  # ruff: ignore[import-outside-top-level] -- third-party execution is needed only for explicit fix operations.

    adopted = manifest.load(root)
    policy = Policy.from_manifest(root, adopted)
    selection = _selection(root, paths, policy=policy, default_scope=default_scope)
    selected = selection.formatter
    format_only_paths |= _historical_paths(root, selected)
    targets = tuple(Path(path) for path in selected)
    transaction.validate_targets(root, targets)
    originals = {path: path.read_bytes() for path in targets}
    fix_paths(
        root,
        tuple(path for path in selection.native if policy.relative(path) not in format_only_paths),
        policy=policy,
        staged=staged,
        terraform=adopted is None or "terraform" in adopted.enabled_capabilities,
    )
    commands = [
        _with_local_oxlint(command, root)
        for command in lifecycle.selected_format_commands(
            root, selected, trusted=trusted, typescript=typescript, format_only_paths=format_only_paths
        )
    ]
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


def _historical_paths(root: Path, paths: Sequence[str]) -> frozenset[str]:
    from sarj_standards.libs.diagnostics import baseline  # ruff: ignore[import-outside-top-level] -- baseline parsing is needed only for explicit fix operations.
    from sarj_standards.libs.linting import oxlint  # ruff: ignore[import-outside-top-level] -- Oxlint imports lifecycle; discover ledger owners only at execution time.

    adopted = manifest.load(root)
    protected = set(
        baseline.historical_paths(root / adopted.diagnostic_baseline)
        if adopted is not None and adopted.diagnostic_baseline is not None
        else ()
    )
    for command in oxlint.select_oxlint_commands(root, paths).commands:
        for path, rules in oxlint.read_suppressions(command.cwd).items():
            if any(count > 0 for count in rules.values()):
                protected.add((command.cwd / path).relative_to(root).as_posix())
    return frozenset(protected)


def _with_local_oxlint(command: Command, root: Path) -> Command:
    from .external import local_node_binary_argv  # ruff: ignore[import-outside-top-level] -- the checking adapter imports lifecycle at module load; resolve its local binary only for Oxlint fix commands.

    if "oxlint" not in command.argv:
        return command
    argv = local_node_binary_argv("oxlint", command.argv, command.cwd, root)
    return command if argv is None else replace(command, argv=argv)


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
    if default_scope and adopted is not None and set(adopted.configs) == set(manifest.TYPESCRIPT_CONFIGS):
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


def fix_paths(
    root: Path, paths: Sequence[str], *, policy: Policy | None = None, staged: bool = False, terraform: bool = False
) -> tuple[Path, ...]:
    repository = root.resolve()
    effective = policy if policy is not None else Policy.from_manifest(repository, manifest.load(repository))
    grouped = runner.group_paths([str(repository / path) for path in paths], policy=effective)
    plan = _plan(repository, effective, grouped, staged=staged, terraform=terraform)
    changes = plan.changes
    written: dict[Path, bytes] = {}
    _assert_inputs(repository, plan, written=written)
    mutation = transaction.FileTransaction.capture(
        repository, tuple(change.path for change in changes), mode=transaction.CaptureMode.SOURCE
    )
    for change in changes:
        if mutation.before[change.path].contents != change.original:
            msg = f"planned mutation target changed concurrently: {change.path}; rerun the command"
            raise OSError(msg)
        transaction.assert_expected(repository, change.path, change.original)
    try:
        for change in changes:
            _assert_inputs(repository, plan, written=written)
            mutation.write_bytes(change.path, change.replacement)
            written[change.path] = change.replacement
        _assert_inputs(repository, plan, written=written)
    except BaseException as exc:
        report = mutation.rollback()
        if report.issues:
            exc.add_note(str(report))
        raise
    return tuple(change.path for change in changes)


def _plan(root: Path, policy: Policy, grouped: runner.GroupedPaths, *, staged: bool, terraform: bool) -> _FixPlan:
    from sarj_iac_lint.terraform import is_terraform_override  # ruff: ignore[import-outside-top-level] -- reuse Terraform's override-loading boundary.

    guarded = _guarded_repository(root, staged=staged) if grouped.iac else False
    module = _declaration_inputs(root, grouped.iac, policy=policy, staged=staged, terraform=terraform)
    overridden = frozenset(path.parent for path in module.inputs if is_terraform_override(path))
    changes = _native_changes(root, policy, grouped, guarded=guarded, overridden=overridden)
    if module.inputs:
        _preserve_observed_sources(changes, module.inputs)
        _project_changes(changes, module.inputs, policy=policy)
        if terraform:
            _format_terraform(changes, module.inputs, policy=policy)
    module = _environment_input_changes(root, changes, module, policy=policy, staged=staged)
    return _FixPlan(
        tuple(change for change in changes.values() if change.original != change.replacement),
        module.inputs,
        module.directories,
        module.index,
    )


def _environment_input_changes(
    root: Path, changes: dict[Path, _Change], module: _ModuleInputs, *, policy: Policy, staged: bool
) -> _ModuleInputs:
    from sarj_iac_lint.rules.no_dead_environment_input import remove_stale_assignments  # ruff: ignore[import-outside-top-level] -- only explicit project fixes may delete proven stale assignments.

    selected = tuple(
        path
        for path in changes
        if path.name.endswith((".tfvars", ".tfvars.json"))
        and policy.allows_rule(
            Diagnostic(
                "SARJ205",
                "",
                Severity.INFO,
                "sarj-iac-lint",
                Location(policy.relative(path)),
                "no-dead-environment-input",
            )
        )
    )
    if not selected:
        return module
    context = _environment_inputs(root, staged=staged)
    if context is None:
        return module
    sources = {path: raw.decode("utf-8-sig") for path, raw in context.inputs.items()}
    for path, change in changes.items():
        if path in sources:
            if change.original != context.inputs[path]:
                message = "Terraform input changed while planning; no files changed"
                raise OSError(message)
            sources[path] = change.replacement.decode(_encoding(path, change.original))
    for path, source in remove_stale_assignments(sources, selected=selected).items():
        original = changes[path].original
        changes[path] = _Change(path, original, source.encode(_encoding(path, original)))
    return _ModuleInputs(
        {**module.inputs, **context.inputs}, {**module.directories, **context.directories}, context.index
    )


def _environment_inputs(root: Path, *, staged: bool) -> _ModuleInputs | None:
    from repo_standards.repository import git_index_identity  # ruff: ignore[import-outside-top-level] -- pin the selected index before collecting contextual files.

    from .iac_module_outputs import selected_sources  # ruff: ignore[import-outside-top-level] -- reuse the exact tracked source boundary and contract acquisition.

    index = git_index_identity(root) if staged else None
    snapshot = selected_sources(root, staged=staged)
    if snapshot is None:
        return None
    if staged and git_index_identity(root) != index:
        message = "Git index changed while collecting Terraform fix inputs; no files changed"
        raise ValueError(message)
    paths = tuple(root / path for path in snapshot.sources)
    transaction.validate_targets(root, paths)
    inputs = {path: path.read_bytes() for path in paths}
    directories = _environment_directories(paths)
    if staged and any(
        raw.decode("utf-8-sig") != snapshot.sources[PurePosixPath(path.relative_to(root).as_posix())]
        for path, raw in inputs.items()
    ):
        message = "Terraform context differs from the staged index; no stale inputs were fixed"
        raise ValueError(message)
    return _ModuleInputs(inputs, directories, index)


def _environment_directories(paths: Sequence[Path]) -> dict[Path, tuple[str, ...]]:
    from sarj_iac_lint.terraform import is_terraform  # ruff: ignore[import-outside-top-level] -- reuse supported module membership.

    expected: dict[Path, set[Path]] = {}
    for path in paths:
        if is_terraform(path):
            expected.setdefault(path.parent, set()).add(path)
    directories: dict[Path, tuple[str, ...]] = {}
    for directory, members in expected.items():
        names = _terraform_names(directory)
        if {directory / name for name in names} != members:
            message = "Terraform worktree membership differs from the selected tracked tree; no stale inputs were fixed"
            raise ValueError(message)
        directories[directory] = names
    return directories


def _native_changes(
    root: Path, policy: Policy, grouped: runner.GroupedPaths, *, guarded: bool, overridden: frozenset[Path]
) -> dict[Path, _Change]:
    changes: dict[Path, _Change] = {}
    for engine in _engines(grouped, root):
        for name in engine.paths:
            path = Path(name)
            transaction.validate_targets(root, (path,))
            prior = changes.get(path)
            original = path.read_bytes() if prior is None else prior.original
            encoding = _encoding(path, original)
            source = (original if prior is None else prior.replacement).decode(encoding)
            rules = _selected_rules(policy, engine, path, guarded=guarded or path.parent in overridden)
            fixed = engine.fix(path, source, rules) if rules else source
            changes[path] = _Change(path, original, fixed.encode(encoding))
    return changes


def _preserve_observed_sources(changes: Mapping[Path, _Change], inputs: Mapping[Path, bytes]) -> None:
    from sarj_iac_lint.declaration_fixes import observes_source  # ruff: ignore[import-outside-top-level] -- reuse the source-observation proof shared with declaration movement.
    from sarj_iac_lint.terraform import terraform_blocks  # ruff: ignore[import-outside-top-level] -- use the established complete-module parser.

    directories = {
        path.parent for path, change in changes.items() if path in inputs and change.original != change.replacement
    }
    for directory in directories:
        parsed = {
            path: terraform_blocks(path, raw.decode(_encoding(path, raw)))
            for path, raw in inputs.items()
            if path.parent == directory
        }
        if observes_source(parsed):
            message = f"Terraform fixes require review of source-reading functions in {directory}; no files changed"
            raise ValueError(message)


def _project_changes(changes: dict[Path, _Change], inputs: Mapping[Path, bytes], *, policy: Policy) -> None:
    from sarj_iac_lint.declaration_fixes import consolidate_declarations  # ruff: ignore[import-outside-top-level] -- only selected Terraform project fixes need module facts.

    sources = {path: raw.decode(_encoding(path, raw)) for path, raw in inputs.items()}
    for path, change in changes.items():
        if path not in inputs:
            continue
        if change.original != inputs[path]:
            message = f"Terraform fix input changed while planning: {path}"
            raise OSError(message)
        sources[path] = change.replacement.decode(_encoding(path, change.original))
    selected = tuple(path for path in changes if path in sources and _allows_declaration_fix(policy, path))
    for path, source in consolidate_declarations(sources, selected=selected).items():
        original = changes[path].original
        changes[path] = _Change(path, original, source.encode(_encoding(path, original)))


def _format_terraform(changes: dict[Path, _Change], inputs: Mapping[Path, bytes], *, policy: Policy) -> None:
    from .terraform_format import format_sources  # ruff: ignore[import-outside-top-level] -- native Terraform is needed only for the actual CLI formatter operation.

    sources = {path: raw.decode(_encoding(path, raw)) for path, raw in inputs.items()}
    for path, change in changes.items():
        if path in sources:
            sources[path] = change.replacement.decode(_encoding(path, change.original))
    selected = tuple(
        path
        for path in changes
        if path in sources
        and policy.allows_rule(
            Diagnostic("fmt", "", Severity.INFO, "terraform", Location(policy.relative(path)), "fmt")
        )
    )
    for path, source in format_sources(policy.root, sources, selected=selected).items():
        original = changes[path].original
        changes[path] = _Change(path, original, source.encode(_encoding(path, original)))


def _selected_rules(policy: Policy, engine: _Engine, path: Path, *, guarded: bool) -> tuple[str, ...]:
    protected: set[str] = {"no-redundant-variable-validation", "no-terraform-data-condition"} if guarded else set()
    return tuple(
        rule_id
        for rule_id, code in engine.codes.items()
        if not (engine.source == "sarj-iac-lint" and rule_id in protected)
        if policy.allows_rule(
            Diagnostic(code, "", Severity.INFO, engine.source, Location(policy.relative(path)), rule_id)
        )
    )


def _guarded_repository(root: Path, *, staged: bool) -> bool:
    from .iac_guard_contracts import CoreIAC  # ruff: ignore[import-outside-top-level] -- validate existing safeguard provenance before selecting any guard-removal fix.

    return CoreIAC(root, staged=staged).prepare() is not None


def _declaration_inputs(
    root: Path, paths: Sequence[str], *, policy: Policy, staged: bool, terraform: bool
) -> _ModuleInputs:
    selected = [
        Path(path) for path in paths if Path(path).name.endswith((".tf", ".tf.json")) and policy.allows_path(Path(path))
    ]
    misplaced = {path.parent for path in selected if terraform or _requires_module_proof(path, policy=policy)}
    if not misplaced:
        return _ModuleInputs({}, {})
    directories = {directory: _terraform_names(directory) for directory in misplaced}
    members = tuple(directory / name for directory, names in directories.items() for name in names)
    transaction.validate_targets(root, members)
    inputs = {path: path.read_bytes() for path in members}
    from .iac_module_outputs import staged_module_index  # ruff: ignore[import-outside-top-level] -- reuse the complete staged module proof shared with analysis.

    index = staged_module_index(root, inputs) if staged else None
    return _ModuleInputs(inputs, directories, index)


def _requires_module_proof(path: Path, *, policy: Policy) -> bool:
    from sarj_iac_lint.autofix import fix_source  # ruff: ignore[import-outside-top-level] -- safe Terraform changes require complete source-observation evidence.
    from sarj_iac_lint.rules.canonical_terraform_declarations import CanonicalTerraformDeclarations  # ruff: ignore[import-outside-top-level] -- selected source-semantic project owner.

    if path.suffix != ".tf":
        return False
    source = path.read_text(encoding="utf-8-sig")
    if _allows_declaration_fix(policy, path) and CanonicalTerraformDeclarations().check(path, source):
        return True
    rules = _selected_rules(policy, _native("sarj_iac_lint", "sarj-iac-lint", ()), path, guarded=False)
    return bool(rules) and fix_source(path, source, rule_ids=rules) != source


def _allows_declaration_fix(policy: Policy, path: Path) -> bool:
    return policy.allows_path(path) and policy.allows_rule(
        Diagnostic(
            "SARJ224",
            "",
            Severity.INFO,
            "sarj-iac-lint",
            Location(policy.relative(path)),
            "canonical-terraform-declarations",
        )
    )


def _terraform_names(directory: Path) -> tuple[str, ...]:
    return tuple(
        sorted(path.name for path in directory.iterdir() if path.is_file() and path.name.endswith((".tf", ".tf.json")))
    )


def _assert_inputs(root: Path, plan: _FixPlan, *, written: Mapping[Path, bytes]) -> None:
    if plan.index is not None:
        from repo_standards.repository import git_index_identity  # ruff: ignore[import-outside-top-level] -- compare the original selected index before every project write.

        if git_index_identity(root) != plan.index:
            message = "Git index changed during Terraform fix planning; rerun the command"
            raise OSError(message)
    if any(_terraform_names(directory) != names for directory, names in plan.directories.items()):
        message = "Terraform module membership changed during fix planning; rerun the command"
        raise OSError(message)
    for path, contents in plan.inputs.items():
        transaction.assert_expected(root, path, written.get(path, contents))


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
        if getattr(  # sarj-noqa: SARJ557 -- Support native plugin rule classes whose legacy metadata omits enabled_by_default.
            rule, "enabled_by_default", True
        )
        and rule.documentation is not None
        and rule.documentation.autofix is AutofixPolicy.SAFE
    }

    def fix(path: Path, text: str, rules: Sequence[str]) -> str:
        return fixer.fix_source(path, text, rule_ids=rules)

    return _Engine(source, paths, codes, fix)
