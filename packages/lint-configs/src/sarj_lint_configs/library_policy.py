"""Hypermodern application-library policy and direct-dependency scanner."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib
from typing import TYPE_CHECKING, Final, Literal

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from .manifest import as_table, list_field


if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


Ecosystem = Literal["python", "typescript"]
Category = Literal["obsolete", "platform-redundant", "preferred-stack"]


@dataclass(frozen=True, slots=True)
class LibraryMapping:
    """One stable, machine-consumable policy decision."""

    id: str
    ecosystem: Ecosystem
    category: Category
    imports: tuple[str, ...]
    packages: tuple[str, ...]
    replacement: str
    message: str


def _mapping(  # ruff: ignore[too-many-positional-arguments] - compact declarations keep the catalog auditable.
    id_: str,
    ecosystem: Ecosystem,
    category: Category,
    names: str,
    replacement: str,
    message: str,
    *,
    imports: str | None = None,
) -> LibraryMapping:
    packages = tuple(part.strip() for part in names.split(","))
    import_names = tuple(
        clean_name for part in (names if imports is None else imports).split(",") if (clean_name := part.strip())
    )
    return LibraryMapping(id_, ecosystem, category, import_names, packages, replacement, message)


# Adapters and the manifest scanner derive from this sole policy source.
CATALOG: Final[tuple[LibraryMapping, ...]] = (
    _mapping(
        "LIB001",
        "python",
        "preferred-stack",
        "argparse,optparse",
        "Typer",
        "The application profile standardizes command-line interfaces on Typer.",
    ),
    _mapping(
        "LIB002",
        "python",
        "preferred-stack",
        "click",
        "Typer",
        "Use Typer for typed command-line interfaces instead of direct Click APIs.",
    ),
    _mapping(
        "LIB003",
        "python",
        "preferred-stack",
        "pandas",
        "Polars",
        "Use Polars; migration must account for its expressions and lack of a pandas index model.",
    ),
    _mapping(
        "LIB004",
        "python",
        "preferred-stack",
        "requests",
        "HTTPX",
        "Use HTTPX; review timeout defaults, exception types, streaming, and client lifetimes.",
    ),
    _mapping(
        "LIB005",
        "python",
        "preferred-stack",
        "ujson",
        "orjson",
        "Use orjson; its dumps function returns bytes and option semantics differ.",
    ),
    _mapping(
        "LIB006",
        "python",
        "preferred-stack",
        "flask",
        "FastAPI",
        "The application profile standardizes HTTP APIs on FastAPI; this is an architectural migration.",
    ),
    _mapping(
        "LIB007",
        "python",
        "preferred-stack",
        "marshmallow,cerberus",
        "Pydantic",
        "The application profile standardizes validation and serialization on Pydantic.",
    ),
    _mapping(
        "LIB008",
        "python",
        "platform-redundant",
        "pytz",
        "zoneinfo",
        "Use zoneinfo; explicitly review DST ambiguity, localization, and fold behavior.",
    ),
    _mapping(
        "LIB009",
        "python",
        "platform-redundant",
        "pkg_resources",
        "importlib.metadata/importlib.resources/packaging",
        "Do not use pkg_resources; choose the focused importlib or packaging API.",
        imports="pkg_resources",
    ),
    _mapping("LIB010", "python", "obsolete", "tomli", "tomllib", "Python 3.14 provides tomllib."),
    _mapping("LIB011", "python", "obsolete", "pathlib2", "pathlib", "Python 3.14 provides pathlib."),
    _mapping(
        "LIB012",
        "python",
        "obsolete",
        "backports.zoneinfo",
        "zoneinfo",
        "Python 3.14 provides zoneinfo.",
        imports="backports.zoneinfo",
    ),
    _mapping(
        "LIB013",
        "python",
        "obsolete",
        "importlib-metadata",
        "importlib.metadata",
        "Python 3.14 provides importlib.metadata.",
        imports="importlib_metadata",
    ),
    _mapping(
        "LIB014",
        "python",
        "obsolete",
        "importlib-resources",
        "importlib.resources",
        "Python 3.14 provides importlib.resources.",
        imports="importlib_resources",
    ),
    _mapping(
        "LIB015",
        "python",
        "obsolete",
        "dataclasses",
        "dataclasses (stdlib)",
        "Remove the obsolete dataclasses backport on Python 3.14.",
        imports="",
    ),
    _mapping(
        "LIB016",
        "python",
        "obsolete",
        "enum34",
        "enum",
        "Remove the obsolete enum34 backport on Python 3.14.",
        imports="enum34",
    ),
    _mapping(
        "LIB017",
        "python",
        "obsolete",
        "futures",
        "concurrent.futures",
        "Remove the obsolete futures backport on Python 3.14.",
        imports="futures",
    ),
    _mapping(
        "LIB018",
        "python",
        "obsolete",
        "backports.cached-property",
        "functools.cached_property",
        "Python 3.14 provides functools.cached_property.",
        imports="backports.cached_property",
    ),
    _mapping(
        "LIB019",
        "python",
        "obsolete",
        "boto",
        "boto3",
        "Boto 2 is obsolete; migrate to boto3 and review API differences.",
    ),
    _mapping(
        "LIB020",
        "python",
        "obsolete",
        "aioredis",
        "redis.asyncio",
        "aioredis was merged into redis-py; use redis.asyncio.",
    ),
    _mapping("LIB021", "python", "obsolete", "nose", "pytest", "Nose is unmaintained; use pytest."),
    _mapping("LIB022", "python", "platform-redundant", "mock", "unittest.mock", "Python 3.14 provides unittest.mock."),
    _mapping(
        "LIB101",
        "typescript",
        "preferred-stack",
        "request,node-fetch,cross-fetch,isomorphic-fetch,axios",
        "ky",
        "The application profile standardizes HTTP clients on Ky; review errors, retries, hooks, and response parsing.",
    ),
    _mapping(
        "LIB102",
        "typescript",
        "preferred-stack",
        "moment,dayjs",
        "date-fns",
        "The application profile standardizes date utilities on date-fns; migration is not API-compatible.",
    ),
    _mapping(
        "LIB103",
        "typescript",
        "preferred-stack",
        "lodash,lodash-es,underscore",
        "remeda",
        "The application profile standardizes collection utilities on Remeda and native APIs.",
    ),
    _mapping(
        "LIB104",
        "typescript",
        "preferred-stack",
        "classnames",
        "clsx",
        "Use clsx for conditional class-name composition.",
    ),
    _mapping(
        "LIB105",
        "typescript",
        "preferred-stack",
        "joi,yup,superstruct,io-ts,runtypes",
        "zod",
        "The application profile standardizes runtime validation on Zod; schemas are not drop-in compatible.",
    ),
    _mapping(
        "LIB106",
        "typescript",
        "preferred-stack",
        "jsonwebtoken",
        "jose",
        "Use jose; review key formats and async signing and verification APIs.",
    ),
    _mapping(
        "LIB107",
        "typescript",
        "preferred-stack",
        "express,koa",
        "hono",
        "The application profile standardizes servers on Hono; Node deployments also need @hono/node-server.",
    ),
    _mapping(
        "LIB108",
        "typescript",
        "preferred-stack",
        "jest,mocha",
        "vitest",
        "The application profile standardizes tests on Vitest; review globals, timers, mocks, and environment setup.",
    ),
    _mapping(
        "LIB109",
        "typescript",
        "preferred-stack",
        "sinon",
        "Vitest mocks",
        "Use Vitest spies, mocks, and fake timers instead of Sinon.",
    ),
    _mapping(
        "LIB110",
        "typescript",
        "preferred-stack",
        "commander,yargs",
        "citty",
        "The application profile standardizes command-line interfaces on citty.",
    ),
    _mapping(
        "LIB111",
        "typescript",
        "platform-redundant",
        "bluebird",
        "native Promise",
        "Use native Promise, adding p-limit or p-map only for the extensions actually needed.",
    ),
    _mapping(
        "LIB112",
        "typescript",
        "platform-redundant",
        "rimraf,fs-extra",
        "node:fs/promises",
        "Prefer node:fs/promises; verify recursive removal, copy, path, and error semantics.",
    ),
    _mapping(
        "LIB113",
        "typescript",
        "platform-redundant",
        "abort-controller",
        "AbortController",
        "Node 22 provides global AbortController.",
    ),
    _mapping(
        "LIB114",
        "typescript",
        "platform-redundant",
        "querystring",
        "URLSearchParams",
        "Use URLSearchParams and explicitly review repeated keys, escaping, arrays, and object coercion.",
    ),
    _mapping(
        "LIB115",
        "typescript",
        "preferred-stack",
        "dotenv",
        "@dotenvx/dotenvx",
        "The application profile standardizes environment loading on @dotenvx/dotenvx.",
    ),
    _mapping("LIB116", "typescript", "preferred-stack", "chalk", "picocolors", "Use picocolors for terminal colors."),
    _mapping(
        "LIB117",
        "typescript",
        "obsolete",
        "faker",
        "@faker-js/faker",
        "The original faker package is abandoned; use @faker-js/faker.",
    ),
    _mapping("LIB118", "typescript", "obsolete", "node-sass", "sass", "node-sass is end-of-life; use Dart Sass."),
    _mapping(
        "LIB119",
        "typescript",
        "obsolete",
        "tslint",
        "eslint",
        "TSLint is deprecated; use ESLint with typescript-eslint.",
    ),
)


def catalog() -> tuple[LibraryMapping, ...]:
    """Return the immutable ordered policy catalog."""
    return CATALOG


def python_banned_api() -> dict[str, str]:
    """Build Ruff ``banned-api`` entries for Python imports."""
    return {
        name: f"{entry.id}: {entry.message} Replace with {entry.replacement}."
        for entry in CATALOG
        if entry.ecosystem == "python"
        for name in entry.imports
    }


@dataclass(frozen=True, slots=True)
class RestrictedImport:
    """One ESLint ``no-restricted-imports`` path entry."""

    name: str
    message: str


def typescript_restricted_imports() -> tuple[RestrictedImport, ...]:
    """Build ESLint ``no-restricted-imports`` path entries."""
    return tuple(
        RestrictedImport(name, f"{entry.id}: {entry.message} Replace with {entry.replacement}.")
        for entry in CATALOG
        if entry.ecosystem == "typescript"
        for name in entry.imports
    )


@dataclass(frozen=True, slots=True)
class Finding:
    """A forbidden direct dependency declaration."""

    id: str
    path: Path
    line: int
    column: int
    package: str
    replacement: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}:{self.column} {self.id} {self.message} Replace with {self.replacement}."


class ManifestPolicyError(ValueError):
    """An applicable dependency manifest cannot be parsed safely."""


_IGNORED_DIRS: Final = frozenset(
    {
        ".cache",
        ".git",
        ".hg",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".uv-cache",
        ".venv",
        "build",
        "dist",
        "node_modules",
        "site-packages",
        "vendor",
        "venv",
    }
)
_IGNORED_MANIFEST_DIRS: Final = frozenset({"fixture", "fixtures", "template", "templates", "test", "tests"})
_GENERATED_MARKERS: Final = (
    "autogenerated by uv",
    "autogenerated by pip-compile",
    "auto-generated",
    "generated by pip-compile",
    "do not edit this file",
)
_REQUIREMENTS_NAME: Final = re.compile(r"^requirements(?:[-_.].*)?\.(?:txt|in)$", re.IGNORECASE)


def scan(root: Path, *, allowed_ids: Iterable[str] = ()) -> tuple[Finding, ...]:
    """Scan authored direct-dependency manifests below ``root``."""
    root = root.resolve()
    allowed = frozenset(allowed_ids)
    package_index = _package_index()
    findings: list[Finding] = []
    for path in _manifest_paths(root):
        dependencies: tuple[tuple[Path, Ecosystem, str], ...]
        if path.name == "pyproject.toml":
            dependencies = tuple((path, ecosystem, package) for ecosystem, package in _pyproject_dependencies(path))
        elif path.name == "package.json":
            dependencies = tuple((path, ecosystem, package) for ecosystem, package in _package_json_dependencies(path))
        else:
            dependencies = _requirements_dependencies(path, root, frozenset())
        for source, ecosystem, package in dependencies:
            entry = package_index.get((ecosystem, _normalize(package, ecosystem)))
            if entry is None or entry.id in allowed:
                continue
            text = source.read_text(encoding="utf-8")
            line, column = _location(text, package)
            findings.append(
                Finding(entry.id, source.relative_to(root), line, column, package, entry.replacement, entry.message)
            )
    return tuple(sorted(set(findings), key=lambda item: (str(item.path), item.line, item.id, item.package)))


def _package_index() -> dict[tuple[Ecosystem, str], LibraryMapping]:
    return {(entry.ecosystem, _normalize(name, entry.ecosystem)): entry for entry in CATALOG for name in entry.packages}


def _normalize(name: str, ecosystem: Ecosystem) -> str:
    if ecosystem == "python":
        return canonicalize_name(name)
    return name.strip().lower()


def _manifest_paths(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if any(part in _IGNORED_DIRS for part in relative_parts):
            continue
        if not path.is_file():
            continue
        in_requirements_dir = "requirements" in relative_parts[:-1]
        ignored_requirements_fixture = any(part.lower() in _IGNORED_MANIFEST_DIRS for part in relative_parts[:-1])
        if path.name in {"pyproject.toml", "package.json"} or (
            not ignored_requirements_fixture
            and (_REQUIREMENTS_NAME.match(path.name) or (in_requirements_dir and path.suffix in {".txt", ".in"}))
        ):
            paths.append(path)
    return tuple(sorted(paths))


def _requirement_name(spec: str, where: str) -> str:
    try:
        return Requirement(spec).name
    except InvalidRequirement as exc:
        msg = f"invalid dependency in {where}: {spec!r}"
        raise ManifestPolicyError(msg) from exc


def _pyproject_dependencies(path: Path) -> tuple[tuple[Ecosystem, str], ...]:
    data = _read_toml(path)
    result: list[tuple[Ecosystem, str]] = []
    project = _table(data.get("project"))
    lists = [_string_list(project.get("dependencies"), f"{path} project.dependencies")]
    optional = _table(project.get("optional-dependencies"))
    lists.extend(
        _string_list(value, f"{path} project.optional-dependencies.{name}") for name, value in optional.items()
    )
    groups = _table(data.get("dependency-groups"))
    for name, value in groups.items():
        lists.append(_dependency_group_list(value, f"{path} dependency-groups.{name}"))
    tool = _table(data.get("tool"))
    poetry = _table(tool.get("poetry"))
    poetry_tables = [_table(poetry.get("dependencies")), _table(poetry.get("dev-dependencies"))]
    poetry_tables.extend(_table(_table(group).get("dependencies")) for group in _table(poetry.get("group")).values())
    for table in poetry_tables:
        result.extend(("python", name) for name in _table(table) if name.lower() != "python")
    pdm = _table(tool.get("pdm"))
    lists.extend(
        _string_list(value, f"{path} tool.pdm.dev-dependencies.{name}")
        for name, value in _table(pdm.get("dev-dependencies")).items()
    )
    uv = _table(tool.get("uv"))
    lists.append(_string_list(uv.get("dev-dependencies"), f"{path} tool.uv.dev-dependencies"))
    for specifications in lists:
        result.extend(("python", _requirement_name(spec, str(path))) for spec in specifications)
    return tuple(result)


def _read_toml(path: Path) -> dict[str, object]:
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        msg = f"cannot parse {path}: {exc}"
        raise ManifestPolicyError(msg) from exc
    return as_table(parsed)


def _table(value: object) -> Mapping[str, object]:
    return as_table(value)


def _string_list(value: object, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    values = list_field({"value": value}, "value")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in values):
        msg = f"{where} must be a list of dependency strings"
        raise ManifestPolicyError(msg)
    return tuple(item for item in values if isinstance(item, str))


def _dependency_group_list(value: object, where: str) -> tuple[str, ...]:
    items = list_field({"value": value}, "value")
    if not isinstance(value, list):
        msg = f"{where} must be a list"
        raise ManifestPolicyError(msg)
    specifications: list[str] = []
    for item in items:
        if isinstance(item, str):
            specifications.append(item)
            continue
        include = _table(item).get("include-group")
        if isinstance(item, dict) and isinstance(include, str):
            continue
        msg = f"{where} entries must be dependency strings or include-group tables"
        raise ManifestPolicyError(msg)
    return tuple(specifications)


def _package_json_dependencies(path: Path) -> tuple[tuple[Ecosystem, str], ...]:
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] - narrowed at the parser boundary
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        msg = f"cannot parse {path}: {exc}"
        raise ManifestPolicyError(msg) from exc
    if not isinstance(parsed, dict):
        msg = f"{path} must contain a JSON object"
        raise ManifestPolicyError(msg)
    data = as_table(parsed)  # pyright: ignore[reportUnknownArgumentType] - json object leaves are narrowed below
    result: list[tuple[Ecosystem, str]] = []
    for field in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        dependencies = data.get(field)
        if dependencies is None:
            continue
        dependency_table = as_table(dependencies)
        if not isinstance(dependencies, dict) or not all(isinstance(spec, str) for spec in dependency_table.values()):
            msg = f"{path} {field} must map package names to string versions"
            raise ManifestPolicyError(msg)
        for name, value in dependency_table.items():
            if not isinstance(value, str):
                continue
            spec = value
            alias = re.match(r"^npm:((?:@[^/]+/)?[^@]+)(?:@|$)", spec)
            result.append(("typescript", alias.group(1) if alias else name))
    return tuple(result)


def _requirements_dependencies(
    path: Path, root: Path, seen: frozenset[Path]
) -> tuple[tuple[Path, Ecosystem, str], ...]:
    resolved = path.resolve()
    if resolved in seen:
        msg = f"cyclic requirements include at {path}"
        raise ManifestPolicyError(msg)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        msg = f"cannot read {path}: {exc}"
        raise ManifestPolicyError(msg) from exc
    if any(marker in text[:500].lower() for marker in _GENERATED_MARKERS):
        return ()
    result: list[tuple[Path, Ecosystem, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-c ", "--constraint ")):
            continue
        if line.startswith(("-r ", "--requirement ")):
            target = line.split(maxsplit=1)[1].strip()
            included = (path.parent / target).resolve()
            if not included.is_relative_to(root) or not included.is_file():
                msg = f"requirements include from {path} is missing or outside the scan root: {target}"
                raise ManifestPolicyError(msg)
            result.extend(_requirements_dependencies(included, root, seen | {resolved}))
            continue
        editable = line.removeprefix("-e ").removeprefix("--editable ")
        editable = re.split(r"\s+#", editable, maxsplit=1)[0].rstrip()
        if not editable:
            continue
        if egg := re.search(r"[#&]egg=([^&]+)", editable):
            result.append((path, "python", egg.group(1)))
            continue
        if editable.startswith((".", "/", "http://", "https://", "git+", "hg+", "svn+", "bzr+")):
            continue
        # Strip pip-only hash/options while retaining PEP 508 markers and URLs.
        spec = re.split(r"\s+(?:--hash|--config-settings|--global-option)\b", editable, maxsplit=1)[0]
        result.append((path, "python", _requirement_name(spec, str(path))))
    return tuple(result)


def _location(text: str, package: str) -> tuple[int, int]:
    pattern = re.compile(re.escape(package), re.IGNORECASE)
    match = pattern.search(text)
    if match is None:
        return 1, 1
    return text.count("\n", 0, match.start()) + 1, match.start() - text.rfind("\n", 0, match.start())
