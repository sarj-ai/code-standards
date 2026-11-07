from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
from typing import TYPE_CHECKING, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from sarj_standards.libs.adoption import lifecycle
from sarj_standards.libs.adoption.configs import BIOME_CONFIG_NAMES
from sarj_standards.libs.diagnostics import (
    AnalyzerId,
    Completion,
    Diagnostic,
    ExecutionIssue,
    InvocationId,
    Location,
    Severity,
    ToolReport,
    TrustMode,
)
from sarj_standards.libs.json_boundary import parse_json

from . import external, oxlint
from .process import ToolResolution, executor_capabilities


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .process import ProcessExecutor, ProcessOutput


SOURCE: Final = "oxfmt"
RULE_ID: Final = "format"
# Mirrors `formatExtensions` in configs/oxfmt.strict.mts.
FORMAT_EXTENSIONS: Final = frozenset({
    "cjs", "css", "cts", "gql", "graphql", "gs", "handlebars", "hbs", "htm", "html", "js", "json", "json5", "jsonc",
    "jsx", "less", "markdown", "md", "mdx", "mjs", "mts", "pcss", "scss", "toml", "ts", "tsx", "vue", "yaml", "yml",
})  # fmt: skip
# Prettier has no TOML or Apps Script parser without plugins.
_PRETTIER_EXTENSIONS: Final = FORMAT_EXTENSIONS - {"gs", "toml"}
_BIOME_LANGUAGES: Final = {
    "javascript": frozenset({"cjs", "cts", "js", "jsx", "mjs", "mts", "ts", "tsx"}),
    "json": frozenset({"json", "jsonc"}),
    "css": frozenset({"css"}),
    "graphql": frozenset({"gql", "graphql"}),
}
# Biome formats HTML only when `html.formatter.enabled` is true.
_BIOME_HTML: Final = frozenset({"htm", "html"})
# Style for repositories without a formatter: Platform's `.oxfmtrc.json` without its repository paths.
_DEFAULT_STYLE: Final[Mapping[str, JsonValue]] = {
    "printWidth": 80,
    "sortPackageJson": False,
    "sortImports": {
        "groups": [
            ["side_effect", "side_effect_style"],
            ["builtin", "type-builtin"],
            ["external", "type-external"],
            ["internal", "type-internal", "subpath", "type-subpath", "unknown"],
            ["parent", "type-parent", "sibling", "type-sibling", "index", "type-index"],
        ],
        "newlinesBetween": True,
    },
}
# oxfmt's own config discovery order.
CONFIG_NAMES: Final = (".oxfmtrc.json", ".oxfmtrc.jsonc", "oxfmt.config.ts", "oxfmt.config.mts")
_PRETTIER_CONFIGS: Final = (
    ".prettierrc", ".prettierrc.json", ".prettierrc.yml", ".prettierrc.yaml", ".prettierrc.json5", ".prettierrc.js",
    "prettier.config.js", ".prettierrc.ts", "prettier.config.ts", ".prettierrc.mjs", "prettier.config.mjs",
    ".prettierrc.mts", "prettier.config.mts", ".prettierrc.cjs", "prettier.config.cjs", ".prettierrc.cts",
    "prettier.config.cts", ".prettierrc.toml",
)  # fmt: skip
_EMPTY_SELECTION: Final = re.compile(r"Finished in \d+ms on 0 files using \d+ threads\.\n?")
_NO_FILES: Final = "No files found matching the given patterns."
_FILE_TYPE_INCLUDE: Final = re.compile(r"(?P<prefix>.*/)?\*\.(?P<extension>[A-Za-z0-9]+)")


@dataclass(frozen=True, slots=True)
class OxfmtSeed:
    source: Literal["biome", "oxfmt", "prettier"] | None
    options: Mapping[str, JsonValue]
    warnings: tuple[str, ...] = ()


class _BiomeModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True, frozen=True)


class _BiomeFormatter(_BiomeModel):
    enabled: bool | None = None
    includes: tuple[str, ...] | None = None
    line_width: int | None = Field(default=None, alias="lineWidth")
    indent_width: int | None = Field(default=None, alias="indentWidth")
    indent_style: Literal["space", "tab"] | None = Field(default=None, alias="indentStyle")
    quote_style: Literal["double", "single"] | None = Field(default=None, alias="quoteStyle")
    trailing_commas: Literal["all", "es5", "none"] | None = Field(default=None, alias="trailingCommas")


class _BiomeLanguage(_BiomeModel):
    formatter: _BiomeFormatter | None = None


class _BiomeFiles(_BiomeModel):
    includes: tuple[str, ...] | None = None


class _BiomeLanguages(_BiomeModel):
    javascript: _BiomeLanguage = _BiomeLanguage()
    json_language: _BiomeLanguage = Field(default=_BiomeLanguage(), alias="json")
    css: _BiomeLanguage = _BiomeLanguage()
    graphql: _BiomeLanguage = _BiomeLanguage()
    html: _BiomeLanguage = _BiomeLanguage()

    def formatters(self) -> dict[str, _BiomeFormatter | None]:
        return {
            "javascript": self.javascript.formatter,
            "json": self.json_language.formatter,
            "css": self.css.formatter,
            "graphql": self.graphql.formatter,
        }


class _BiomeOverride(_BiomeLanguages):
    includes: tuple[str, ...] = ()
    formatter: _BiomeFormatter | None = None

    def sets_formatter_options(self) -> bool:
        return self.formatter is not None or self.html.formatter is not None or any(self.formatters().values())


class _BiomeConfig(_BiomeLanguages):
    files: _BiomeFiles = _BiomeFiles()
    formatter: _BiomeFormatter = _BiomeFormatter()
    overrides: tuple[_BiomeOverride, ...] = ()


def analyze(
    paths: Sequence[str],
    *,
    project: Path,
    root: Path,
    runner: ProcessExecutor | None = None,
) -> ToolReport:
    started = time.monotonic()
    root = root.resolve()
    project = project.resolve()
    execute = external.DEFAULT_EXECUTOR if runner is None else runner
    invocation = InvocationId(f"{SOURCE}:{project.relative_to(root).as_posix()}")
    selected = _project_paths(paths, project=project, root=root)
    if not selected:
        return ToolReport(SOURCE, Completion.COMPLETE, analyzer_id=AnalyzerId(SOURCE), invocation_id=invocation)
    binary = _binary(execute, project=project, root=root)
    if binary is None:
        message = oxlint.missing_binary_message(SOURCE, project, root)
        return _failure(ExecutionIssue(SOURCE, "missing-dependency", message), invocation)
    try:
        listed = execute.run(
            external.process_request(
                (*binary, "--list-different", "--no-error-on-unmatched-pattern", "--", *selected), cwd=project
            )
        )
        dirty = _dirty_paths(listed, selected)
    except (OSError, UnicodeError) as exc:
        return _failure(ExecutionIssue(SOURCE, "tool-failure", external.redact_message(str(exc), root)), invocation)
    if isinstance(dirty, ExecutionIssue):
        return _failure(replace(dirty, message=external.redact_message(dirty.message, root)), invocation)
    diagnostics = tuple(_diagnostic((project / name).relative_to(root).as_posix()) for name in sorted(dirty))
    return ToolReport(
        SOURCE,
        Completion.COMPLETE,
        diagnostics=diagnostics,
        analyzer_id=AnalyzerId(SOURCE),
        invocation_id=invocation,
        duration_ms=round((time.monotonic() - started) * 1_000),
        file_count=len(selected),
    )


def reports(
    inputs: Sequence[str],
    projects: Sequence[Path],
    *,
    root: Path,
    runner: ProcessExecutor,
    trust: TrustMode,
) -> list[ToolReport]:
    # `projects` are the selected Oxlint projects; each needs an oxfmt config.
    results: list[ToolReport] = []
    # Directories stay directories: oxfmt walks them faster than thousands of operands.
    operands: dict[Path, set[Path]] = {}
    for path in (Path(item).resolve() for item in inputs):
        if (owner := project_for(path, root)) is not None:
            operands.setdefault(owner, set()).add(path)
    for project in projects:
        owner = project_for(project, root)
        if owner is None:
            results.append(_missing_config(project, root))
        elif not _overlaps_selection(project, operands):
            # A selected ancestor directory outside every oxfmt project still covers this one.
            operands.setdefault(owner, set()).add(owner)
    for owner, paths in sorted(operands.items()):
        # oxfmt applies nested configs itself, so a selected ancestor directory covers nested projects.
        scoped = sorted(path for path in paths if not _covered_by_other_owner(path, owner, operands))
        if scoped:
            results.append(_report(scoped, owner, root=root, runner=runner, trust=trust))
    return results


def _missing_config(project: Path, root: Path) -> ToolReport:
    relative = project.relative_to(root).as_posix() or "."
    message = f"no oxfmt config owns the TypeScript project {relative}; run `code-standards update`"
    return _failure(ExecutionIssue(SOURCE, "configuration-failure", message), InvocationId(f"{SOURCE}:{relative}"))


def _overlaps_selection(project: Path, operands: Mapping[Path, set[Path]]) -> bool:
    return any(
        project.is_relative_to(path) or path.is_relative_to(project) for paths in operands.values() for path in paths
    )


def _covered_by_other_owner(path: Path, owner: Path, operands: Mapping[Path, set[Path]]) -> bool:
    return any(
        other != owner and outer.is_dir() and path != outer and path.is_relative_to(outer)
        for other, outers in operands.items()
        for outer in outers
    )


def _report(
    scoped: Sequence[Path], owner: Path, *, root: Path, runner: ProcessExecutor, trust: TrustMode
) -> ToolReport:
    config = config_path(owner)
    if trust is TrustMode.SAFE and config is not None and config.suffix in {".ts", ".mts"}:
        invocation = InvocationId(f"{SOURCE}:{owner.relative_to(root).as_posix() or '.'}")
        message = f"{config.name} is executable repository code; retry with TrustMode.TRUSTED"
        return _failure(ExecutionIssue(SOURCE, "trust-required", message), invocation)
    return analyze(tuple(map(str, scoped)), project=owner, root=root, runner=runner)


def config_path(project: Path) -> Path | None:
    return next((project / name for name in CONFIG_NAMES if (project / name).is_file()), None)


def project_for(path: Path, root: Path) -> Path | None:
    # The nearest directory holding an oxfmt config owns a path, as `oxfmt` run there would.
    repository = root.resolve()
    absolute = (path if path.is_absolute() else repository / path).resolve()
    start = absolute if absolute.is_dir() else absolute.parent
    return next(
        (
            candidate
            for candidate in (start, *start.parents)
            if candidate.is_relative_to(repository) and config_path(candidate) is not None
        ),
        None,
    )


def write_command(paths: Sequence[str], *, project: Path, root: Path) -> lifecycle.Command:
    root = root.resolve()
    project = project.resolve()
    argv = (
        "oxfmt",
        "--write",
        "--no-error-on-unmatched-pattern",
        "--",
        *_project_paths(paths, project=project, root=root),
    )
    return lifecycle.Command("oxfmt", external.local_node_binary_argv("oxfmt", argv, project, root) or argv, project)


def seed_config(root: Path, *, runner: ProcessExecutor | None = None) -> OxfmtSeed:
    root = root.resolve()
    existing = [name for name in CONFIG_NAMES if (root / name).is_file()]
    if existing == [".oxfmtrc.json"]:
        return OxfmtSeed("oxfmt", _without_schema(_json_object(root / ".oxfmtrc.json")))
    if existing:
        msg = f"{existing[0]} already configures oxfmt; port it to oxfmt.config.mts by hand"
        raise ValueError(msg)
    prettier = _has_prettier_config(root)
    biome = _biome_config(root)
    if prettier and biome is not None:
        msg = "both Prettier and the Biome formatter are configured; disable one before seeding oxfmt"
        raise ValueError(msg)
    if biome is not None:
        return _biome_seed(biome, _migrate(root, "biome", runner))
    if prettier:
        seed = _migrate(root, "prettier", runner)
        return replace(seed, options={**seed.options, "extensions": _sorted(_PRETTIER_EXTENSIONS)})
    return OxfmtSeed(None, dict(_DEFAULT_STYLE))


def render_config(seed: OxfmtSeed) -> str:
    origins = {None: "Platform's default oxfmt style", "oxfmt": ".oxfmtrc.json"}
    origin = origins.get(seed.source, f"{seed.source} by `oxfmt --migrate`")
    return (
        'import { createConfig } from "./oxfmt.strict.mts";\n\n'
        f"// Seeded once from {origin}. Repository-owned: edit style, ignores and overrides here.\n"
        f"export default createConfig({json.dumps(seed.options, indent=2)});\n"
    )


def _project_paths(paths: Sequence[str], *, project: Path, root: Path) -> tuple[str, ...]:
    selected: list[str] = []
    for raw in paths:
        path = Path(raw)
        absolute = Path(os.path.normpath(path if path.is_absolute() else root / path))
        if not absolute.is_relative_to(project):
            msg = f"{raw} is outside the oxfmt project {project.relative_to(root).as_posix() or '.'}"
            raise ValueError(msg)
        selected.append(absolute.relative_to(project).as_posix())
    return tuple(dict.fromkeys(selected))


def _binary(execute: ProcessExecutor, *, project: Path, root: Path) -> tuple[str, ...] | None:
    if executor_capabilities(execute).tool_resolution is ToolResolution.PROVIDED:
        return ("oxfmt",)
    return external.local_node_binary_argv("oxfmt", ("oxfmt",), project, root)


def _dirty_paths(output: ProcessOutput, selected: Sequence[str]) -> tuple[str, ...] | ExecutionIssue:
    stderr = output.stderr.strip()
    if output.returncode == 0 and _EMPTY_SELECTION.fullmatch(output.stdout) and stderr == _NO_FILES:
        return ()
    if output.returncode not in {0, 1} or stderr:
        message = stderr or output.stdout.strip() or f"oxfmt exited {output.returncode}"
        return ExecutionIssue(SOURCE, "tool-failure", message, output.returncode)
    names = tuple(output.stdout.splitlines())
    if (output.returncode == 1) != bool(names):
        message = f"oxfmt exited {output.returncode} but listed {len(names)} file(s)"
        return ExecutionIssue(SOURCE, "protocol-mismatch", message, output.returncode)
    if len(set(names)) != len(names) or not all(_within(name, selected) for name in names):
        return ExecutionIssue(SOURCE, "protocol-mismatch", "oxfmt listed a duplicate or unselected file")
    return names


def _within(name: str, selected: Sequence[str]) -> bool:
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and any(scope == "." or path == PurePosixPath(scope) or path.is_relative_to(scope) for scope in selected)
    )


def _diagnostic(path: str) -> Diagnostic:
    return Diagnostic(
        RULE_ID,
        "File does not match the repository's oxfmt config.",
        Severity.ERROR,
        SOURCE,
        Location(path),
        rule_id=RULE_ID,
        help="Run `code-standards fix` on this path.",
        help_url="https://oxc.rs/docs/guide/usage/formatter",
        tags=("formatting",),
    )


def _failure(issue: ExecutionIssue, invocation: InvocationId) -> ToolReport:
    return ToolReport(
        SOURCE, Completion.FAILED, issues=(issue,), analyzer_id=AnalyzerId(SOURCE), invocation_id=invocation
    )


def _migrate(root: Path, source: Literal["biome", "prettier"], runner: ProcessExecutor | None) -> OxfmtSeed:
    execute = external.DEFAULT_EXECUTOR if runner is None else runner
    binary = _binary(execute, project=root, root=root)
    if binary is None:
        msg = "oxfmt is not installed locally; install the repository's packages before seeding oxfmt"
        raise OSError(msg)
    target = root / ".oxfmtrc.json"
    try:
        output = execute.run(external.process_request((*binary, f"--migrate={source}"), cwd=root))
        if output.returncode != 0 or not target.is_file():
            msg = f"oxfmt --migrate={source} failed: {output.stderr.strip() or output.stdout.strip()}"
            raise ValueError(msg)
        migrated = _without_schema(_json_object(target))
    finally:
        target.unlink(missing_ok=True)
    # oxfmt lists review items as "  - <item>" on stderr; seeding handles Biome overrides itself.
    warnings = tuple(
        line.removeprefix("  - ")
        for line in output.stderr.splitlines()
        if line.startswith("  - ") and "cannot be migrated automatically" not in line
    )
    return OxfmtSeed(source, migrated, warnings)


def _has_prettier_config(root: Path) -> bool:
    if any((root / name).is_file() for name in _PRETTIER_CONFIGS):
        return True
    package = root / "package.json"
    return package.is_file() and "prettier" in _json_object(package)


def _biome_config(root: Path) -> _BiomeConfig | None:
    path = next((root / name for name in BIOME_CONFIG_NAMES if (root / name).is_file()), None)
    if path is None:
        return None
    config = _BiomeConfig.model_validate_json(path.read_bytes())
    return None if config.formatter.enabled is False else config


def _biome_seed(biome: _BiomeConfig, migrated: OxfmtSeed) -> OxfmtSeed:
    notes = list(migrated.warnings)
    options = dict(migrated.options)
    extensions = _biome_extensions(biome, notes)
    if biome.formatter.includes is not None:
        excluded = [pattern.removeprefix("!") for pattern in biome.formatter.includes if pattern.startswith("!")]
        options["ignorePatterns"] = [*_strings(options.pop("ignorePatterns", [])), *excluded]
    overrides: list[JsonValue] = [
        override
        for language in ("css", "json")
        if extensions & _BIOME_LANGUAGES[language] and (override := _biome_language_override(biome, language))
    ]
    notes.extend(
        f"Biome override {list(override.includes)} sets formatter options; port it to oxfmt overrides"
        for override in biome.overrides
        if override.sets_formatter_options()
    )
    # Biome never sorts package.json; oxfmt does unless told otherwise.
    options |= {"sortPackageJson": False, "extensions": _sorted(extensions)}
    if overrides:
        options["overrides"] = overrides
    return OxfmtSeed("biome", options, tuple(notes))


def _biome_extensions(biome: _BiomeConfig, notes: list[str]) -> set[str]:
    extensions = _biome_includes(biome.files.includes, notes)
    if biome.formatter.includes is not None:
        extensions &= _biome_includes(biome.formatter.includes, notes)
    for language, formatter in biome.formatters().items():
        if formatter is not None and formatter.enabled is False:
            extensions -= _BIOME_LANGUAGES[language]
    if biome.html.formatter is None or biome.html.formatter.enabled is not True:
        extensions -= _BIOME_HTML
    return extensions


def _biome_includes(patterns: Sequence[str] | None, notes: list[str]) -> set[str]:
    supported = _BIOME_HTML.union(*_BIOME_LANGUAGES.values())
    if patterns is None:
        return set(supported)
    extensions: set[str] = set()
    for pattern in patterns:
        match = _FILE_TYPE_INCLUDE.fullmatch(pattern)
        if pattern.startswith("!"):
            continue
        if match is not None:
            extensions |= {match["extension"]} & supported
        else:
            extensions |= supported
        if pattern not in {"**", "**/*"} and (match is None or match["prefix"] not in {None, "**/"}):
            notes.append(f"Biome include {pattern!r} kept by file type only; add oxfmt ignores for other paths")
    return extensions


def _biome_language_override(biome: _BiomeConfig, language: Literal["css", "json"]) -> dict[str, JsonValue] | None:
    javascript = _biome_style(biome, biome.javascript.formatter)
    javascript |= {
        "singleQuote": _quote_style(biome.javascript.formatter) == "single",
        "trailingComma": _trailing_commas(biome.javascript.formatter, "all"),
    }
    style = _biome_style(biome, biome.formatters()[language])
    if language == "css":
        style["singleQuote"] = _quote_style(biome.css.formatter) == "single"
    else:
        style["trailingComma"] = _trailing_commas(biome.json_language.formatter, "none")
    options = {key: value for key, value in style.items() if javascript[key] != value}
    members = sorted(_BIOME_LANGUAGES[language])
    files = f"**/*.{members[0]}" if len(members) == 1 else f"**/*.{{{','.join(members)}}}"
    return {"files": [files], "options": options} if options else None


def _biome_style(biome: _BiomeConfig, language: _BiomeFormatter | None) -> dict[str, JsonValue]:
    specific = _BiomeFormatter() if language is None else language
    general = biome.formatter
    return {
        "printWidth": specific.line_width or general.line_width or 80,
        "tabWidth": specific.indent_width or general.indent_width or 2,
        "useTabs": (specific.indent_style or general.indent_style or "tab") == "tab",
    }


def _quote_style(formatter: _BiomeFormatter | None) -> str:
    return "double" if formatter is None or formatter.quote_style is None else formatter.quote_style


def _trailing_commas(formatter: _BiomeFormatter | None, default: str) -> str:
    return default if formatter is None or formatter.trailing_commas is None else formatter.trailing_commas


def _sorted(values: Iterable[str]) -> list[JsonValue]:
    return [*sorted(values)]


def _strings(value: JsonValue) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _json_object(path: Path) -> dict[str, JsonValue]:
    value = parse_json(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        msg = f"{path.name} must contain a JSON object"
        raise TypeError(msg)
    return value


def _without_schema(config: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: value for key, value in config.items() if key != "$schema"}
