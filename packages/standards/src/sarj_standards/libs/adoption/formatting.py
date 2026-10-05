from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- pinned formatter migration and Git-owned input selection.
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from sarj_standards.libs.filesystem import is_link_like
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping
from sarj_standards.libs.yaml_boundary import parse_yaml

from . import manifest
from .configs import OXFMT_CONFIG_NAMES


if TYPE_CHECKING:
    from collections.abc import Sequence


SUPPORTED_SUFFIXES: Final = frozenset(
    {
        ".cjs",
        ".cts",
        ".js",
        ".jsx",
        ".mjs",
        ".mts",
        ".ts",
        ".tsx",
        ".json",
        ".jsonc",
        ".json5",
        ".yaml",
        ".yml",
        ".md",
        ".mdx",
        ".markdown",
        ".css",
        ".scss",
        ".less",
        ".pcss",
        ".postcss",
        ".toml",
        ".graphql",
        ".graphqls",
        ".gql",
        ".html",
        ".htm",
        ".xhtml",
        ".vue",
        ".svelte",
        ".hbs",
        ".handlebars",
        ".mjml",
    }
)

_PRETTIER_NAMES: Final = (
    ".prettierrc",
    ".prettierrc.json",
    ".prettierrc.jsonc",
    ".prettierrc.json5",
    ".prettierrc.toml",
    ".prettierrc.yaml",
    ".prettierrc.yml",
    ".prettierrc.js",
    ".prettierrc.mjs",
    ".prettierrc.cjs",
    ".prettierrc.ts",
    ".prettierrc.mts",
    ".prettierrc.cts",
    "prettier.config.js",
    "prettier.config.mjs",
    "prettier.config.cjs",
    "prettier.config.ts",
    "prettier.config.mts",
    "prettier.config.cts",
)
_PRETTIER_OPTIONS: Final = frozenset(
    {
        "arrowParens",
        "bracketSameLine",
        "bracketSpacing",
        "embeddedLanguageFormatting",
        "endOfLine",
        "experimentalOperatorPosition",
        "htmlWhitespaceSensitivity",
        "jsxSingleQuote",
        "objectWrap",
        "overrides",
        "printWidth",
        "proseWrap",
        "quoteProps",
        "semi",
        "singleAttributePerLine",
        "singleQuote",
        "tabWidth",
        "trailingComma",
        "useTabs",
        "vueIndentScriptAndStyle",
    }
)
_TAILWIND_OPTIONS: Final = MappingProxyType(
    {
        "tailwindAttributes": "attributes",
        "tailwindConfig": "config",
        "tailwindFunctions": "functions",
        "tailwindPreserveDuplicates": "preserveDuplicates",
        "tailwindPreserveWhitespace": "preserveWhitespace",
        "tailwindStylesheet": "stylesheet",
    }
)
_IGNORED_DIRECTORIES: Final = frozenset(
    {"node_modules", "dist", "build", "coverage", ".next", ".turbo", "vendor", ".git", ".venv"}
)
_PRETTIER_SOURCE_NAMES: Final = frozenset((*_PRETTIER_NAMES, ".prettierignore"))
_ALLOWED_PRETTIER_OPTIONS: Final = _PRETTIER_OPTIONS | frozenset(_TAILWIND_OPTIONS) | {"$schema", "plugins"}


def oxfmt_policy(root: Path, *, install_root: Path | None = None) -> dict[str, object]:
    _check_extra_prettier_sources(root)
    ignore_patterns = [
        "**/node_modules/**",
        "**/dist/**",
        "**/build/**",
        "**/coverage/**",
        "**/.next/**",
        "**/.turbo/**",
        "**/vendor/**",
        "**/*.generated.*",
        "**/*.min.*",
    ]
    document: dict[str, object] = {
        "$schema": "./node_modules/oxfmt/configuration_schema.json",
        "printWidth": 80,
        "sortImports": False,
        "sortPackageJson": False,
        "sortTailwindcss": False,
        "ignorePatterns": ignore_patterns,
    }
    ignore = root / ".prettierignore"
    if ignore.is_file():
        ignore_patterns.extend(
            line for line in ignore.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")
        )
    migrated = _existing_formatter_policy(root, install_root or root)
    migration_ignores = migrated.pop("ignorePatterns", [])
    if not is_object_list(migration_ignores):
        msg = "Oxfmt migration must return an ignore pattern array"
        raise ValueError(msg)
    document.update(migrated)
    document["ignorePatterns"] = [*ignore_patterns, *migration_ignores]
    return document


def _existing_formatter_policy(root: Path, install_root: Path) -> dict[str, object]:
    sources = [root / name for name in _PRETTIER_NAMES if (root / name).is_file()]
    package = root / "package.json"
    package_document = _read_object(package) if package.is_file() else {}
    package_policy = package_document.get("prettier")
    if len(sources) > 1 or (sources and package_policy is not None):
        msg = "multiple Prettier policy sources; consolidate them before migrating formatting"
        raise ValueError(msg)
    if sources:
        source = sources[0]
        if source.suffix in {".json5", ".toml"}:
            msg = f"{source.name} requires explicit formatter policy migration before Oxfmt adoption"
            raise ValueError(msg)
        if source.suffix in {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"}:
            return _migrate_executable(root, source, install_root)
        source_policy = _read_object(source)
    elif package_policy is not None:
        if not is_object_mapping(package_policy):
            msg = "package.json prettier configuration must be an object for automatic migration"
            raise ValueError(msg)
        source_policy = _configuration_object(package_policy)
    else:
        return _existing_biome_policy(root, install_root)
    return _translate_prettier(source_policy)


def _existing_biome_policy(root: Path, install_root: Path) -> dict[str, object]:
    sources = [root / name for name in ("biome.json", "biome.jsonc") if (root / name).is_file()]
    if len(sources) > 1:
        msg = "multiple Biome policy sources; retain one before formatting migration"
        raise ValueError(msg)
    return _migrate_executable(root, sources[0], install_root, source_kind="biome") if sources else {}


def _check_extra_prettier_sources(root: Path) -> None:
    for parent, directories, names in os.walk(root):
        directory = Path(parent)
        directories[:] = [
            name for name in directories if name not in _IGNORED_DIRECTORIES and not is_link_like(directory / name)
        ]
        for name in names:
            path = directory / name
            if is_link_like(path):
                continue
            _check_prettier_source(path, root)


def _check_prettier_source(path: Path, root: Path) -> None:
    if path.name == "package.yaml" and "prettier" in _read_object(path):
        msg = f"{path.relative_to(root)} Prettier policy requires explicit migration before Oxfmt adoption"
        raise ValueError(msg)
    if path.parent == root:
        return
    if path.name in _PRETTIER_SOURCE_NAMES or (path.name == "package.json" and "prettier" in _read_object(path)):
        msg = f"nested Prettier policy {path.relative_to(root)} requires explicit migration before Oxfmt adoption"
        raise ValueError(msg)


def _read_object(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    try:
        value: object = parse_json(text)
    except ValueError:
        value = parse_yaml(text)
    if not is_object_mapping(value):
        msg = f"{path.name} must contain a configuration object"
        raise ValueError(msg)
    return _configuration_object(value)


def _configuration_object(value: object) -> dict[str, object]:
    if not is_object_mapping(value) or any(not isinstance(key, str) for key in value):
        msg = "formatter configuration objects must have string keys"
        raise TypeError(msg)
    return manifest.as_table(value)


def _translate_prettier(policy: dict[str, object]) -> dict[str, object]:
    unknown = set(policy).difference(_ALLOWED_PRETTIER_OPTIONS)
    if unknown:
        msg = f"unsupported Prettier options require review: {', '.join(sorted(unknown))}"
        raise ValueError(msg)
    plugins = policy.get("plugins", [])
    if not is_object_list(plugins) or any(plugin != "prettier-plugin-tailwindcss" for plugin in plugins):
        msg = "unsupported Prettier plugins; retain their policy until an equivalent Oxfmt integration exists"
        raise ValueError(msg)
    result = {name: value for name, value in policy.items() if name in _PRETTIER_OPTIONS}
    if "overrides" in result:
        result["overrides"] = _translate_prettier_overrides(result["overrides"])
    tailwind = {target: policy[name] for name, target in _TAILWIND_OPTIONS.items() if name in policy}
    if plugins or tailwind:
        result["sortTailwindcss"] = tailwind or True
    return result


def _translate_prettier_overrides(overrides: object) -> list[dict[str, object]]:
    if not is_object_list(overrides):
        msg = "Prettier overrides must be an array"
        raise ValueError(msg)
    translated: list[dict[str, object]] = []
    for entry in overrides:
        if not is_object_mapping(entry):
            msg = "each Prettier override must be an object"
            raise ValueError(msg)
        options = entry.get("options", {})
        if not is_object_mapping(options):
            msg = "Prettier override options must be an object"
            raise ValueError(msg)
        translated.append(
            {**_configuration_object(entry), "options": _translate_prettier(_configuration_object(options))}
        )
    return translated


def _migrate_executable(
    root: Path, source: Path, install_root: Path, *, source_kind: str = "prettier"
) -> dict[str, object]:
    try:
        return _execute_migration(root, source, install_root, source_kind=source_kind)
    except subprocess.SubprocessError as exc:
        msg = "Oxfmt policy migration could not complete"
        raise ValueError(msg) from exc


def _execute_migration(
    root: Path,
    source: Path,
    install_root: Path,
    *,
    source_kind: str,
) -> dict[str, object]:
    binary = install_root / "node_modules" / ".bin" / "oxfmt"
    if not binary.is_file():
        discovered = shutil.which("oxfmt")
        if discovered is None:
            msg = "automatic formatter policy migration requires the pinned Oxfmt dependency"
            raise ValueError(msg)
        binary = Path(discovered)
    expected = manifest.oxlint_peers()["oxfmt"]
    version = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed argv, no shell.
        (str(binary), "--version"),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    if version != f"Version: {expected}":
        msg = f"formatter migration requires Oxfmt {expected}; found {version}"
        raise ValueError(msg)
    with TemporaryDirectory(prefix="sarj-oxfmt-migration-") as temporary:
        projected = Path(temporary)
        (projected / source.name).symlink_to(source.resolve())
        for name in ("package.json", ".prettierignore"):
            original = root / name
            if original.is_file():
                (projected / name).symlink_to(original.resolve())
        modules = install_root / "node_modules"
        if modules.is_dir():
            (projected / "node_modules").symlink_to(modules.resolve(), target_is_directory=True)
        result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- pinned tool owns migration.
            (str(binary), "--migrate", source_kind),
            cwd=projected,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = f"{result.stdout}\n{result.stderr}"
        if result.returncode != 0 or any(
            marker in output.lower() for marker in ("unsupported", "not supported", "skipping", "warning")
        ):
            msg = "Oxfmt could not preserve executable Prettier policy; review its unsupported options or plugins"
            raise ValueError(msg)
        return _read_object(projected / ".oxfmtrc.json")


def selected_formatter_projects(files: Sequence[str], root: Path) -> dict[Path, set[Path]]:
    grouped: dict[Path, set[Path]] = defaultdict(set)
    adopted = manifest.load(root)
    fallback = root / adopted.typescript_dest if adopted is not None else root
    paths: list[Path] = []
    for name in files:
        unresolved = Path(name) if Path(name).is_absolute() else root / name
        if is_link_like(unresolved):
            continue
        path = unresolved.resolve()
        if not path.is_relative_to(root):
            msg = "Oxfmt selected path escapes the repository"
            raise ValueError(msg)
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if "\n" in str(path) or "\r" in str(path):
            msg = "Oxfmt filename-only protocol cannot represent newline-containing filenames"
            raise ValueError(msg)
        paths.append(path)
    ignored = _git_ignored_paths(paths, root)
    for path in paths:
        if path in ignored:
            continue
        config = _nearest_config(path.parent, root) or _nearest_config(fallback, root)
        if config is None:
            msg = "Oxfmt configuration is missing for selected maintained files; run code-standards update"
            raise ValueError(msg)
        grouped[config].add(path)
    return dict(grouped)


def _git_ignored_paths(paths: Sequence[Path], root: Path) -> frozenset[Path]:
    if not paths or not any((parent / ".git").exists() for parent in (root, *root.parents)):
        return frozenset()
    git = shutil.which("git")
    if git is None:
        msg = "Git is required to select maintained formatter inputs in a Git worktree"
        raise ValueError(msg)
    environment = {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- hook-local Git variables must not redirect input selection.
        if not name.startswith("GIT_")
    }
    try:
        result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed Git argv, no shell.
            (git, "-c", f"core.excludesFile={os.devnull}", "check-ignore", "--stdin", "-z"),
            cwd=root,
            input=b"\0".join(os.fsencode(path) for path in paths) + b"\0",
            check=False,
            capture_output=True,
            env=environment,
            shell=False,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        msg = "Git formatter input selection exceeded five seconds"
        raise ValueError(msg) from exc
    if result.returncode not in {0, 1}:
        msg = "Git could not determine maintained formatter inputs"
        raise ValueError(msg)
    return frozenset(Path(os.fsdecode(path)) for path in result.stdout.split(b"\0") if path)


def _nearest_config(start: Path, root: Path) -> Path | None:
    current = start
    while current.is_relative_to(root):
        configs = [current / name for name in OXFMT_CONFIG_NAMES if (current / name).is_file()]
        if len(configs) > 1:
            msg = "multiple Oxfmt configurations share one directory"
            raise ValueError(msg)
        if configs:
            return configs[0]
        if current == root:
            break
        current = current.parent
    return None
