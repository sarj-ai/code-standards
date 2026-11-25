from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from itertools import pairwise
import json
import os
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel

from sarj_standards.libs.adoption import manifest, packagemanager
from sarj_standards.libs.adoption.configs import (
    LEGACY_ESLINT_CONFIG_NAMES,
    OXLINT_CONFIG_NAMES,
    OXLINT_SUPPRESSIONS,
    TYPESCRIPT_SOURCE_SUFFIXES,
)
from sarj_standards.libs.adoption.lifecycle import Command
from sarj_standards.libs.diagnostics import (
    Completion,
    Diagnostic,
    ExecutionIssue,
    Location,
    RelatedLocation,
    RuleExecution,
    RuleExecutionState,
    Severity,
    SourceDocument,
    ToolReport,
)
from sarj_standards.libs.filesystem import is_link_like

from .process import ProcessRequest


_ERROR_PREVIEW_LINES = 3


if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable, Sequence

    from .process import ProcessExecutor, ProcessOutput


UNUSED_DIRECTIVE: Final = "oxlint/unused-directive"
UNUSED_SUPPRESSION: Final = "oxlint/unused-suppression"
TSCONFIG_ERROR: Final = "tsc/tsconfig-error"
REQUIRED_TAGS: Final = ("non-baselineable", "required-source-policy")
type OxlintEnvironment = Mapping[str, str]

PLUGIN_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "eslint": "",
        "@typescript-eslint": "typescript",
        "jsx_a11y": "jsx-a11y",
        "react_perf": "react-perf",
        "react-hooks": "react",
        "next": "nextjs",
        "@next/next": "nextjs",
    }
)

_DIRECTIVES = "@sarj/directive-"
_PROTECTED_RULES: Final = (
    *(
        f"{_DIRECTIVES}{name}"
        for name in (
            "require-description",
            "no-use",
            "disable-enable-pair",
            "no-aggregating-enable",
            "no-duplicate-disable",
            "no-unused-enable",
            "no-restricted-disable",
        )
    ),
    "no-console",
    "eslint/no-console",
    "react-hooks/exhaustive-deps",
    "react/exhaustive-deps",
    "unicorn/no-abusive-eslint-disable",
    "@sarj/no-vague-suppression-description",
    "@sarj/no-oxlint-directive",
    "typescript/ban-ts-comment",
    "@typescript-eslint/ban-ts-comment",
)
REQUIRED_RULES: Final[Mapping[str, JsonValue]] = MappingProxyType(
    {
        f"{_DIRECTIVES}require-description": ["error", {"ignore": []}],
        "unicorn/no-abusive-eslint-disable": "error",
        f"{_DIRECTIVES}no-use": [
            "error",
            {
                "allow": [
                    "eslint-disable-line",
                    "eslint-disable-next-line",
                    "eslint-env",
                    "exported",
                    "global",
                    "globals",
                ]
            },
        ],
        f"{_DIRECTIVES}disable-enable-pair": ["error", {"allowWholeFile": False}],
        f"{_DIRECTIVES}no-aggregating-enable": "error",
        f"{_DIRECTIVES}no-duplicate-disable": "error",
        f"{_DIRECTIVES}no-unused-enable": "error",
        f"{_DIRECTIVES}no-restricted-disable": ["error", *_PROTECTED_RULES],
        "@sarj/no-vague-suppression-description": "error",
        "@sarj/no-oxlint-directive": "error",
        "typescript/ban-ts-comment": [
            "error",
            {
                "ts-check": False,
                "ts-expect-error": "allow-with-description",
                "ts-ignore": True,
                "ts-nocheck": True,
                "minimumDescriptionLength": 3,
            },
        ],
    }
)
JS_PLUGINS: Final[Mapping[str, str]] = MappingProxyType({"@sarj": "@sarj/eslint-plugin"})

_UNLINTED_NAMES: Final = frozenset(
    {
        *OXLINT_CONFIG_NAMES,
        *(f"{name}.{suffix}" for name in ("oxlint.strict", "oxfmt.config", "oxfmt.strict") for suffix in ("ts", "mts")),
        *LEGACY_ESLINT_CONFIG_NAMES,
        "eslint.strict.mjs",
        "eslint.strict.ts",
        "syncpack.strict.mts",
        ".pnp.cjs",
        ".pnp.loader.mjs",
    }
)
_IGNORED_DIRS: Final = frozenset(
    {
        ".astro",
        ".next",
        ".nuxt",
        ".output",
        ".svelte-kit",
        ".turbo",
        ".wrangler",
        "__generated__",
        "build",
        "cjs",
        "coverage",
        "dist",
        "esm",
        "generated",
        "node_modules",
        "out",
        "storybook-static",
        "umd",
    }
)
_MINIFIED_RE: Final = re.compile(r"\.min\.[cm]?js\Z")
_PROJECT_SKIP_DIRS: Final = frozenset({".git", ".venv", "build", "dist", "node_modules", "target", "vendor"})
_SKILL_ARTIFACT_ROOTS: Final = frozenset({".agents", ".claude"})
_LOCK_NAMES: Final = tuple(name for name, _client in packagemanager.LOCKFILES)
_SELECTED_CONFIG: Final = Path(__file__).parents[2] / "configs" / "oxlint-selected-config.mts"
_CODE_RE: Final = re.compile(r"(?P<namespace>[^()]+)\((?P<rule>[^()]+)\)")
_TYPE_CHECK_RE: Final = re.compile(r"TS[0-9]+")
_TYPE_CHECK_CODE: Final = re.compile(r"typescript\((TS[1-9]\d*|tsconfig-error)\)")
_TSCONFIG_NOTE: Final = "Oxlint type-checks no file of this project until its tsconfig loads."
_JSON_START_RE: Final = re.compile(r"^\{", re.MULTILINE)
_CONFIGURATION_FAILURES: Final = ("Failed to parse oxlint configuration file.", "Failed to build configuration.")
_MISSING_TSGOLINT: Final = "Failed to find tsgolint executable"
_PLUGIN_CRASH: Final = "Error running JS plugin."
_STALE_SUPPRESSIONS: Final = "There are suppressions that do not occur anymore."
_NEW_SUPPRESSIONS: Final = "There are new violations not covered by the suppressions file."
_MISSING_FILE_LIMIT: Final = 5
TSRS_FAILURE: Final = "@sarj: tsrs request failed"
UNUSED_DIRECTIVE_RE: Final = re.compile(
    r"Unused (?P<tool>eslint|oxlint)-(?P<kind>disable|enable) directive \("
    r"(?:no problems were reported(?: from (?P<disabled>.+))?"
    r"|no matching (?:eslint|oxlint)-disable directives were found(?: for (?P<enabled>.+))?)\)\."
)


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True)


class _Span(_Wire):
    offset: int = Field(ge=0)
    length: int = Field(ge=0)


class _Label(_Wire):
    label: str | None = None
    span: _Span


class _Record(_Wire):
    message: str
    code: str | None = None
    severity: Literal["error", "warning"]
    filename: str
    help: str | None = None
    url: str | None = None
    note: str | None = None
    labels: tuple[_Label, ...] = ()


class _Report(_Wire):
    diagnostics: tuple[_Record, ...]
    number_of_files: int = Field(ge=0)


class _Count(_Wire):
    count: int = Field(ge=1)


class _Package(_Wire):
    name: str | None = None
    main: str | None = None


class _Suppressions(RootModel[dict[str, dict[str, _Count]]]):
    model_config = ConfigDict(frozen=True)


class OxlintSelection(NamedTuple):
    commands: tuple[Command, ...]
    unowned_count: int


@dataclass(frozen=True, slots=True)
class OxlintRequest:
    rules: frozenset[str] | None = None
    forced: Mapping[str, JsonValue] = REQUIRED_RULES
    disabled: tuple[tuple[tuple[str, ...], frozenset[str]], ...] = ()


@dataclass(frozen=True, slots=True)
class OxlintResult:
    diagnostics: tuple[Diagnostic, ...]
    issues: tuple[ExecutionIssue, ...] = ()
    file_count: int = 0


@dataclass(slots=True)
class _Documents:
    cache: dict[Path, SourceDocument] = field(default_factory=dict)

    def get(self, path: Path) -> SourceDocument:
        if path not in self.cache:
            self.cache[path] = SourceDocument.read(path)
        return self.cache[path]


def canonical_rule_id(name: str) -> str:
    namespace, slash, rule = name.rpartition("/")
    if not slash:
        return name
    target = PLUGIN_ALIASES.get(namespace, namespace)
    return f"{target}/{rule}" if target else rule


_REACT_HOOK_RULES: Final = frozenset({"react/exhaustive-deps", "react/rules-of-hooks"})


def reported_rule_id(name: str) -> str:
    canonical = canonical_rule_id(name)
    if canonical in _REACT_HOOK_RULES:
        return f"react-hooks/{canonical.removeprefix('react/')}"
    return f"next/{canonical.removeprefix('nextjs/')}" if canonical.startswith("nextjs/") else canonical


def oxlint_rule_id(code: str) -> str:
    match = _CODE_RE.fullmatch(code)
    if match is None:
        msg = f"unsupported Oxlint diagnostic code: {code!r}"
        raise ValueError(msg)
    namespace, rule = match["namespace"], match["rule"]
    if namespace == "typescript" and _TYPE_CHECK_RE.fullmatch(rule):
        return f"tsc/{rule}"
    if namespace == "TS" and rule.isdigit():
        return f"tsc/TS{rule}"
    return canonical_rule_id(f"{namespace}/{rule}")


_REQUIRED_IDS: Final = frozenset(canonical_rule_id(rule) for rule in REQUIRED_RULES)


def oxlint_config(project: Path) -> Path | None:
    return next((project / name for name in OXLINT_CONFIG_NAMES if (project / name).is_file()), None)


def config_directory(command: Command) -> Path:
    config = _command_config(command)
    return command.cwd.resolve() if config is None else config.parent


def _command_config(command: Command) -> Path | None:
    argv = list(command.argv)
    return (command.cwd / argv[argv.index("-c") + 1]).resolve() if "-c" in argv else None


def is_oxlint_source(path: Path, *, include_config_sources: bool = False) -> bool:
    return path.suffix.lower() in TYPESCRIPT_SOURCE_SUFFIXES and (
        include_config_sources or path.name not in _UNLINTED_NAMES
    )


def _is_ignored(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return (
        any(part in _IGNORED_DIRS for part in relative.parts[:-1])
        or "/.yarn/releases/" in f"/{relative.as_posix()}"
        or _MINIFIED_RE.search(path.name) is not None
    )


def select_oxlint_commands(
    root: Path,
    paths: Iterable[str],
    *,
    label: str = "selected",
    fix: bool = False,
    include_config_sources: bool = False,
) -> OxlintSelection:
    repository = root.resolve()
    adopted = _adopted_root(repository)
    fallback = adopted if adopted is not None and oxlint_config(adopted) is not None else None
    candidates = _candidates(repository, paths, include_config_sources=include_config_sources)
    grouped: dict[Path, set[Path]] = {}
    owners: dict[Path, Path | None] = {}
    unowned = 0
    for candidate in candidates:
        directory = candidate.parent
        if directory not in owners:
            owners[directory] = _owning_project(directory, repository, fallback=fallback)
        project = owners[directory]
        if project is None:
            unowned += 1
            continue
        grouped.setdefault(project, set()).add(candidate)
    commands: list[Command] = []
    for project, scoped in sorted(grouped.items(), key=lambda item: str(item[0])):
        client = packagemanager.detect(packagemanager.workspace_root(project, repository))
        cwd = _suppressions_owner(project, repository)
        config = oxlint_config(project)
        arguments = (
            *(() if config is None else ("-c", Path(os.path.relpath(config, cwd)).as_posix())),
            *(("--fix",) if fix else ()),
            "--",
            *sorted(_operand(path, cwd) for path in scoped),
        )
        commands.append(
            Command(
                f"Oxlint ({label}: {project.relative_to(repository).as_posix() or '.'})",
                _oxlint_argv(client, cwd, repository, adopted, arguments),
                cwd,
            )
        )
    return OxlintSelection(tuple(commands), unowned)


def _oxlint_argv(
    client: packagemanager.PackageManager,
    cwd: Path,
    repository: Path,
    adopted: Path | None,
    arguments: Sequence[str],
) -> tuple[str, ...]:
    if (
        adopted is not None
        and _nearest_binary("oxlint", cwd, repository) is None
        and (binary := _nearest_binary("oxlint", adopted, repository)) is not None
    ):
        return (str(binary), *arguments)
    return tuple(packagemanager.exec_argv(client, "oxlint", *arguments))


def command_files(command: Command) -> frozenset[Path]:
    boundary = max(index for index, value in enumerate(command.argv) if value == "--")
    return frozenset((command.cwd / value).resolve() for value in command.argv[boundary + 1 :])


def local_binary(name: str, cwd: Path, root: Path) -> Path | None:
    repository = root.resolve()
    if (nearest := _nearest_binary(name, cwd.resolve(), repository)) is not None:
        return nearest
    adopted = _adopted_root(repository)
    return None if adopted is None else _nearest_binary(name, adopted, repository)


def _nearest_binary(name: str, start: Path, repository: Path) -> Path | None:
    executable = f"{name}.cmd" if os.name == "nt" else name
    current = start
    while current.is_relative_to(repository):
        binary = current / "node_modules" / ".bin" / executable
        if binary.is_file():
            return binary
        if current == repository:
            break
        current = current.parent
    return None


def missing_binary_message(name: str, cwd: Path, root: Path) -> str:
    relative = cwd.resolve().relative_to(root.resolve()).as_posix() or "."
    return (
        f"{name} is not installed locally for {relative}; node_modules/.bin/{name} is missing. "
        "Run the repository's locked package install or rerun `code-standards setup`, then retry."
    )


def oxlint_environment(cwd: Path, root: Path) -> OxlintEnvironment:
    binary = local_binary("tsgolint", cwd, root)
    if binary is None:
        raise FileNotFoundError(missing_binary_message("tsgolint", cwd, root))
    return {"OXLINT_TSGOLINT_PATH": str(binary), "SARJ_TYPE_AWARE": "1"}


@contextmanager
def selected_config(command: Command, request: OxlintRequest, *, discover_ignored: bool = False) -> Generator[Command]:
    argv = list(command.argv)
    config = _command_config(command)
    payload = {
        "config": None if config is None else str(config),
        "rules": None if request.rules is None else sorted(request.rules),
        "forced": dict(request.forced),
        "disabled": [{"files": list(files), "rules": sorted(rules)} for files, rules in request.disabled],
        "jsPlugins": _js_plugins(argv),
        "aliases": dict(PLUGIN_ALIASES),
    }
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix=".sarj-oxlint-",
        suffix=".mts",
        dir=command.cwd if config is None else config.parent,
    ) as overlay:
        export = "{ ...config, ignorePatterns: [] }" if discover_ignored else "config"
        overlay.write(
            f"import {{ createSelectedConfig }} from {json.dumps(_SELECTED_CONFIG.as_uri())};\n"
            f"const config = await createSelectedConfig({json.dumps(payload)});\n"
            f"export default {export};\n"
        )
        overlay.flush()
        if config is None:
            index = _executable_index(argv) + 1
            argv[index:index] = ["-c", overlay.name]
        else:
            argv[argv.index("-c") + 1] = overlay.name
        yield replace(command, argv=tuple(argv), prepare=None)


def _js_plugins(argv: Sequence[str]) -> dict[str, str]:
    executable = Path(argv[_executable_index(argv)])
    bin_directory = executable.parent
    install = (
        bin_directory.parent.parent
        if executable.is_absolute() and (bin_directory.parent.name, bin_directory.name) == ("node_modules", ".bin")
        else None
    )
    return {namespace: _installed_package(install, package) or package for namespace, package in JS_PLUGINS.items()}


def _installed_package(install: Path | None, package: str) -> str | None:
    if install is None:
        return None
    for directory in (install / "node_modules" / package, install):
        manifest = directory / "package.json"
        if manifest.is_file():
            metadata = _Package.model_validate_json(manifest.read_bytes())
            if metadata.name == package and metadata.main is not None:
                return str(directory / metadata.main)
    return None


def run_oxlint(
    command: Command,
    *,
    root: Path,
    runner: ProcessExecutor,
    environment: Mapping[str, str],
    request: OxlintRequest,
    timeout_seconds: float = 900,
) -> ToolReport:
    repository = root.resolve()
    selected = command_files(command)
    try:
        variables = {**environment, **oxlint_environment(command.cwd, repository)}
    except FileNotFoundError as exc:
        issue = ExecutionIssue("oxlint", "missing-dependency", str(exc))
        return ToolReport("oxlint", Completion.FAILED, issues=(issue,), file_count=len(selected))
    excluded: frozenset[Path] = frozenset()
    type_check = ("--type-check",) if request.rules is None else ()
    with selected_config(command, request) as configured:
        output = runner.run(
            ProcessRequest(
                with_options(configured.argv, "-f", "json", "--type-aware", *type_check),
                command.cwd,
                variables,
                timeout_seconds=timeout_seconds,
            )
        )
        result = read_oxlint(output, root=repository, cwd=command.cwd, selected=request.rules is not None)
        issues = result.issues
        if not issues and result.file_count != len(selected):
            coverage = _coverage_exclusions(
                command,
                configured,
                request,
                result.file_count,
                root=repository,
                runner=runner,
                variables=variables,
                timeout_seconds=timeout_seconds,
            )
            issues, excluded = coverage.issues, coverage.excluded
    diagnostics = (*result.diagnostics, *required_suppressions(command, root=repository))
    return ToolReport(
        "oxlint",
        Completion.FAILED if issues else Completion.COMPLETE,
        diagnostics=diagnostics,
        issues=issues,
        file_count=result.file_count,
        rule_executions=_excluded_scope(excluded, repository),
    )


def _excluded_scope(excluded: frozenset[Path], root: Path) -> tuple[RuleExecution, ...]:
    if not excluded:
        return ()
    return (
        RuleExecution(
            "oxlint/source-scope",
            RuleExecutionState.SKIPPED,
            len(excluded),
            None,
            "skipped-scope: native Oxlint ignore policy excludes "
            + ", ".join(sorted(path.relative_to(root).as_posix() for path in excluded)),
        ),
    )


@dataclass(frozen=True)
class _CoverageExclusions:
    issues: tuple[ExecutionIssue, ...]
    excluded: frozenset[Path] = frozenset()


def _coverage_exclusions(
    command: Command,
    configured: Command,
    request: OxlintRequest,
    file_count: int,
    *,
    root: Path,
    runner: ProcessExecutor,
    variables: Mapping[str, str],
    timeout_seconds: float,
) -> _CoverageExclusions:
    selected = command_files(command)

    def discover(target: Command, *options: str) -> ProcessOutput:
        return runner.run(
            ProcessRequest(
                with_options(target.argv, "--debug=files", *options),
                command.cwd,
                variables,
                timeout_seconds=timeout_seconds,
            )
        )

    discovery = discover(configured)
    discovered = _discovery_files(discovery, root=root, cwd=command.cwd)
    if discovered is None:
        return _CoverageExclusions((coverage_issue(discovery, root=root, cwd=command.cwd, selected=selected),))
    if len(discovered) != file_count or not discovered <= selected:
        issue = ExecutionIssue(
            "oxlint",
            "protocol-mismatch",
            "Native file discovery disagrees with the analyzed file count or selected input ownership",
        )
        return _CoverageExclusions((issue,))
    with selected_config(command, request, discover_ignored=True) as unignored:
        proof = discover(unignored, "--no-ignore")
    eligible = _discovery_files(proof, root=root, cwd=command.cwd)
    if eligible != selected:
        return _CoverageExclusions((coverage_issue(proof, root=root, cwd=command.cwd, selected=selected),))
    return _CoverageExclusions((), selected - discovered)


def _discovery_files(output: ProcessOutput, *, root: Path, cwd: Path) -> frozenset[Path] | None:
    if output.returncode != 0:
        return None
    return frozenset(_reported_path(line, cwd, root) for line in output.stdout.splitlines() if line)


def coverage_issue(output: ProcessOutput, *, root: Path, cwd: Path, selected: frozenset[Path]) -> ExecutionIssue:
    if output.returncode != 0:
        return ExecutionIssue(
            "oxlint", "tool-failure", _redact(output.stdout or output.stderr, root), output.returncode
        )
    discovered = frozenset(_reported_path(line, cwd, root) for line in output.stdout.splitlines() if line)
    missing = sorted(path.relative_to(root).as_posix() for path in selected - discovered)
    shown = ", ".join(missing[:_MISSING_FILE_LIMIT]) + (", ..." if len(missing) > _MISSING_FILE_LIMIT else "")
    return ExecutionIssue(
        "oxlint",
        "coverage-missing",
        f"Oxlint did not analyze {len(missing)} of {len(selected)} selected maintained file(s) ({shown}); "
        "review the Oxlint ignorePatterns",
    )


def read_oxlint(output: ProcessOutput, *, root: Path, cwd: Path, selected: bool) -> OxlintResult:
    if output.returncode not in {0, 1}:
        message = _redact(output.stderr.strip() or output.stdout.strip() or f"oxlint exited {output.returncode}", root)
        return OxlintResult((), (ExecutionIssue("oxlint", "tool-failure", message, output.returncode),))
    start = _JSON_START_RE.search(output.stdout)
    if start is None:
        return OxlintResult((), (_text_failure(output, root),))
    report = _Report.model_validate_json(output.stdout[start.start() :])
    documents = _Documents()
    diagnostics: list[Diagnostic] = []
    issues: list[ExecutionIssue] = []
    for record in report.diagnostics:
        outcome = _classify(record, root=root, cwd=cwd, selected=selected, documents=documents)
        if isinstance(outcome, Diagnostic):
            diagnostics.append(outcome)
        elif outcome is not None:
            issues.append(outcome)
    issues.extend(_run_issues(output, report, root))
    return OxlintResult(tuple(diagnostics), tuple(issues), report.number_of_files)


def _run_issues(output: ProcessOutput, report: _Report, root: Path) -> list[ExecutionIssue]:
    issues: list[ExecutionIssue] = []
    if output.returncode == 1 and not report.diagnostics and report.number_of_files > 0:
        message = _redact(output.stderr.strip() or "oxlint exited 1 but reported no diagnostics", root)
        issues.append(ExecutionIssue("oxlint", "protocol-mismatch", message, output.returncode))
    tsrs_failure = next((line for line in output.stderr.splitlines() if line.startswith(TSRS_FAILURE)), None)
    if tsrs_failure is not None:
        issues.append(ExecutionIssue("oxlint", "tool-failure", _redact(tsrs_failure, root), output.returncode))
    return issues


def read_suppressions(cwd: Path) -> dict[str, dict[str, int]]:
    path = cwd / OXLINT_SUPPRESSIONS
    if not path.is_file():
        return {}
    ledger = _Suppressions.model_validate_json(path.read_bytes())
    return {file: {rule: entry.count for rule, entry in rules.items()} for file, rules in ledger.root.items()}


def required_suppressions(command: Command, *, root: Path) -> tuple[Diagnostic, ...]:
    entries = read_suppressions(command.cwd)
    ledger = _relative(command.cwd / OXLINT_SUPPRESSIONS, root)
    return tuple(
        Diagnostic(
            canonical_rule_id(rule),
            f"{OXLINT_SUPPRESSIONS} suppresses {count} {canonical_rule_id(rule)} finding(s) in {_relative(path, root)}; "
            "the suppression policy cannot be bulk-suppressed",
            Severity.ERROR,
            "oxlint",
            Location(ledger),
            rule_id=canonical_rule_id(rule),
            tags=REQUIRED_TAGS,
        )
        for path in sorted(command_files(command))
        for rule, count in sorted(entries.get(path.relative_to(command.cwd.resolve()).as_posix(), {}).items())
        if canonical_rule_id(rule) in _REQUIRED_IDS
    )


def _classify(
    record: _Record, *, root: Path, cwd: Path, selected: bool, documents: _Documents
) -> Diagnostic | ExecutionIssue | None:
    message = record.message
    if message == _NEW_SUPPRESSIONS:
        return None
    if message == _STALE_SUPPRESSIONS:
        return None if selected else _stale_suppressions(message, root=root, cwd=cwd)
    if message.startswith(_PLUGIN_CRASH):
        lines = [*message.splitlines(), message, message][:_ERROR_PREVIEW_LINES]
        failure = f"Oxlint JS plugin failed on {record.filename}: {lines[2]}"
        return ExecutionIssue("oxlint", "tool-failure", _redact(failure, root))
    path = _reported_path(record.filename, cwd, root)
    if record.code is None:
        if UNUSED_DIRECTIVE_RE.fullmatch(message):
            return _diagnostic(record, UNUSED_DIRECTIVE, path=path, root=root, documents=documents)
        failure = f"Oxlint could not parse {record.filename}: {message}"
        return ExecutionIssue("oxlint", "tool-failure", _redact(failure, root))
    type_check = type_check_diagnostic(
        record.code,
        _redact(record.message, root),
        _primary_location(record, path, root, documents),
        help_text=None if record.help is None else _redact(record.help, root),
    )
    return type_check or _diagnostic(record, oxlint_rule_id(record.code), path=path, root=root, documents=documents)


def type_check_diagnostic(code: str, message: str, location: Location, *, help_text: str | None) -> Diagnostic | None:
    match = _TYPE_CHECK_CODE.fullmatch(code)
    if match is None:
        return None
    rule = match[1]
    rule_id = f"tsc/{rule}"
    tsconfig = rule_id == TSCONFIG_ERROR
    return Diagnostic(
        rule,
        (help_text or message).partition("\n")[0] if tsconfig else message,
        Severity.ERROR,
        "oxlint",
        location,
        rule_id=rule_id,
        notes=(_TSCONFIG_NOTE,) if tsconfig else (),
        tags=("type-check", "non-baselineable") if tsconfig else ("type-check",),
    )


def _diagnostic(record: _Record, rule: str, *, path: Path, root: Path, documents: _Documents) -> Diagnostic:
    relative = _relative(path, root)
    return Diagnostic(
        rule,
        _redact(record.message, root),
        Severity.ERROR if record.severity == "error" else Severity.WARNING,
        "oxlint",
        _primary_location(record, path, root, documents),
        rule_id=rule,
        help=None if record.help is None else _redact(record.help, root),
        help_url=record.url,
        related=tuple(
            RelatedLocation(_redact(label.label, root), _location(label.span, path, relative, documents))
            for label in record.labels
            if label.label
        ),
        notes=(_redact(record.note, root),) if record.note else (),
        tags=REQUIRED_TAGS if rule in _REQUIRED_IDS else (),
    )


def _primary_location(record: _Record, path: Path, root: Path, documents: _Documents) -> Location:
    relative = _relative(path, root)
    return _location(record.labels[0].span, path, relative, documents) if record.labels else Location(relative)


def _location(span: _Span, path: Path, relative: str, documents: _Documents) -> Location:
    region = documents.get(path).region(start_byte=span.offset, end_byte=span.offset + span.length)
    return Location(relative, region=region)


def _stale_suppressions(message: str, *, root: Path, cwd: Path) -> Diagnostic:
    return Diagnostic(
        UNUSED_SUPPRESSION,
        message,
        Severity.ERROR,
        "oxlint",
        Location(_relative(cwd / OXLINT_SUPPRESSIONS, root)),
        rule_id=UNUSED_SUPPRESSION,
        help="Run `oxlint --prune-suppressions` to remove unused suppressions.",
        tags=("non-baselineable",),
    )


def _text_failure(output: ProcessOutput, root: Path) -> ExecutionIssue:
    text = output.stdout.strip() or output.stderr.strip() or "oxlint returned no JSON report"
    if text.startswith(_CONFIGURATION_FAILURES):
        kind = "configuration-failure"
    elif text.startswith(_MISSING_TSGOLINT):
        kind = "missing-dependency"
    else:
        kind = "protocol-mismatch"
    return ExecutionIssue("oxlint", kind, _redact(text, root), output.returncode)


def with_options(argv: Sequence[str], *options: str) -> tuple[str, ...]:
    index = _executable_index(argv) + 1
    return (*argv[:index], *options, *argv[index:])


def _executable_index(argv: Sequence[str]) -> int:
    try:
        return next(index for index, value in enumerate(argv) if Path(value).name in {"oxlint", "oxlint.cmd"})
    except (
        StopIteration
    ) as exc:  # sarj-noqa: SARJ585 -- Invalid command ownership uses ValueError, not iterator exhaustion.
        msg = "Oxlint command does not contain an oxlint executable"
        raise ValueError(msg) from exc


def _operand(path: Path, cwd: Path) -> str:
    return path.relative_to(cwd).as_posix() if path.is_relative_to(cwd) else str(path)


def _suppressions_owner(project: Path, repository: Path) -> Path:
    for candidate in (project, *project.parents):
        if not candidate.is_relative_to(repository):
            break
        if (candidate / OXLINT_SUPPRESSIONS).is_file():
            return candidate
    return project


def _adopted_root(repository: Path) -> Path | None:
    try:
        adopted = manifest.load(repository)
    except OSError, TypeError, ValueError:
        return None
    if adopted is None:
        return None
    project = (repository / adopted.typescript_dest).resolve()
    return project if project.is_dir() else None


def _owning_project(start: Path, repository: Path, *, fallback: Path | None) -> Path | None:
    bounded = (start, *(parent for parent in start.parents if parent == repository or repository in parent.parents))
    if (configured := _nearest(bounded, lambda path: oxlint_config(path) is not None)) is not None:
        return configured
    if (locked := _nearest(bounded, lambda path: any((path / name).is_file() for name in _LOCK_NAMES))) is not None:
        return fallback if fallback is not None and locked == repository else locked
    packaged = _nearest(bounded, lambda path: (path / "package.json").is_file())
    if fallback is not None and (packaged is None or packaged == repository):
        return fallback
    return packaged


def _nearest(bounded: Sequence[Path], owns: Callable[[Path], bool]) -> Path | None:
    return next((path for path in bounded if owns(path)), None)


def _candidates(root: Path, paths: Iterable[str], *, include_config_sources: bool) -> set[Path]:
    candidates: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        unresolved = path if path.is_absolute() else root / path
        if is_link_like(unresolved):
            continue
        candidate = unresolved.resolve()
        if not candidate.is_relative_to(root) or _is_skill_artifact(candidate, root):
            continue
        if candidate.is_dir() and candidate.name not in _PROJECT_SKIP_DIRS:
            candidates.update(_sources(candidate, include_config_sources=include_config_sources))
        elif is_oxlint_source(candidate, include_config_sources=include_config_sources) and candidate.is_file():
            candidates.add(candidate)
    return {candidate for candidate in candidates if not _is_ignored(candidate, root)}


def _sources(directory: Path, *, include_config_sources: bool) -> set[Path]:
    sources: set[Path] = set()
    for parent, directories, names in os.walk(directory):
        base = Path(parent)
        directories[:] = [
            name
            for name in directories
            if name not in _PROJECT_SKIP_DIRS
            and not (base.name in _SKILL_ARTIFACT_ROOTS and name == "skills")
            and not is_link_like(base / name)
        ]
        sources.update(
            base / name
            for name in names
            if is_oxlint_source(base / name, include_config_sources=include_config_sources)
            and not is_link_like(base / name)
        )
    return sources


def _is_skill_artifact(path: Path, repository: Path) -> bool:
    parts = path.relative_to(repository).parts
    return any(parent in _SKILL_ARTIFACT_ROOTS and child == "skills" for parent, child in pairwise(parts))


def _reported_path(value: str, cwd: Path, root: Path) -> Path:
    path = Path(value)
    resolved = (path if path.is_absolute() else cwd / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        msg = "Oxlint reported a path outside the repository root"
        raise ValueError(msg)
    return resolved


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _redact(value: str, root: Path) -> str:
    from .external import redact_message  # ruff: ignore[import-outside-top-level] -- external imports this module.

    return redact_message(value, root)
