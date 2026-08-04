"""Find every place a consumer repo states a Sarj version, and prove they agree."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
import re
import tomllib
from typing import TYPE_CHECKING, Final

from . import ledger, manifest


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence


class Level(StrEnum):
    """How much a finding matters."""

    OK = "ok"
    WARN = "warn"
    DRIFT = "drift"


@dataclass(frozen=True)
class Finding:
    """One checked pin site and its verdict."""

    level: Level
    where: str
    detail: str


#: `sarj-python-lint==0.25.0`, `"sarj-lint-configs>=0.9"`, `--from sarj-sql-lint==1.2.3`.
_PIN = re.compile(
    r"(?P<name>sarj-(?:python|sql|iac)-lint|sarj-lint-configs)\s*(?P<op>==|>=|~=)\s*(?P<version>[0-9][0-9A-Za-z.\-]*)"
)

#: `rev: python-v0.19.0`, `rev: "lint-configs-v0.10.0"`, `rev: 9d073e83b2...`.
#:
#: Raw commit pins can silently become stale, so report them as unverifiable.
_REV = re.compile(r"""rev:\s*['"]?(?P<rev>[a-z-]+-v[0-9][0-9A-Za-z.\-]*|[0-9a-f]{7,40})['"]?""")

#: A `rev:` that is a raw commit, not a release tag.
_SHA_REV = re.compile(r"^[0-9a-f]{7,40}$")

_ESLINT_PLUGIN: Final = "@sarj/eslint-plugin"
_LOCAL_SPECIFIERS: Final = ("file:", "link:", "workspace:", "portal:")
_PYRIGHT_CONFIG_NAMES: Final = frozenset(
    {".pyright-strict.json", "pyright.strict.json", "pyrightconfig.json", "pyrightconfig.jsonc", "pyproject.toml"}
)
_PYRIGHT_REPORT_DEPRECATED = re.compile(
    r"^\s*[\"']?reportDeprecated[\"']?\s*(?::|=)\s*(?P<value>[^,#/\n]+)", re.MULTILINE
)
_RUFF_CONFIG_NAMES: Final = frozenset({".ruff.toml", "ruff.toml", "pyproject.toml"})
_RUFF_REPLACEMENT_KEYS: Final = frozenset({"ignore", "select"})

#: Where a rule identifier can be written: configs and suppression baselines, but
#: also ordinary source, because an `eslint-disable-next-line @sarj/<rule>` for a
#: rule that no longer exists is its own error under the shipped strict config's
#: `reportUnusedDisableDirectives: "error"`, and a `sarj-noqa: SARJnnn` comment
#: outlives the code it named.
_REFERENCE_SUFFIXES: Final = (
    ".cjs",
    ".cts",
    ".js",
    ".json",
    ".jsx",
    ".mjs",
    ".mts",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
)

_SKIP_DIRS: Final = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".uv-cache",
        ".venv",
        ".next",
        ".turbo",
        ".wrangler",
        ".yarn",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "out",
        "target",
        "vendor",
    }
)


def diagnose(root: Path) -> list[Finding]:
    """Check version pins and required policy settings under a repo root."""
    installed = manifest.installed_versions()
    files = _walk(root)
    findings = [*_check_manifest(root)]
    findings.extend(_check_pin_files(root, files, installed))
    findings.extend(_check_precommit_revs(root, files))
    findings.extend(_check_eslint_plugin(root, files))
    findings.extend(check_retired_rules(root, files))
    findings.extend(check_pyright_deprecated(root, files))
    findings.extend(check_ruff_policy_authority(root, files))
    return findings


def check_retired_rules(root: Path, files: Sequence[Path] | None = None) -> Iterator[Finding]:
    """Name every reference to a rule that no longer exists."""
    retired = ledger.load().retired
    if not retired:
        return
    for path in _candidate_files(files if files is not None else _walk(root), _REFERENCE_SUFFIXES):
        text = _read(path)
        if "sarj" not in text.lower():
            continue
        for entry in retired:
            hits = len(entry.pattern.findall(text))
            if hits:
                where = f"{path.relative_to(root)}: {entry.id} x{hits}"
                yield Finding(Level.DRIFT, where, entry.advice)


def check_pyright_deprecated(root: Path, files: Sequence[Path] | None = None) -> Iterator[Finding]:
    """Require consumers to keep Pyright's deprecated-API protection enabled."""
    for path in files if files is not None else _walk(root):
        if path.name not in _PYRIGHT_CONFIG_NAMES:
            continue
        for match in _PYRIGHT_REPORT_DEPRECATED.finditer(_read(path)):
            value = match.group("value").strip()
            if value.strip("\"'") == "error":
                continue
            where = f"{path.relative_to(root)}: reportDeprecated = {value}"
            yield Finding(
                Level.DRIFT,
                where,
                'sets `reportDeprecated` away from "error"; restore it to keep deprecated APIs visible',
            )


def check_ruff_policy_authority(root: Path, files: Sequence[Path] | None = None) -> Iterator[Finding]:
    """Reject extending Ruff configs that replace inherited rule policy."""
    for path in files if files is not None else _walk(root):
        if path.name not in _RUFF_CONFIG_NAMES:
            continue
        try:
            parsed: object = tomllib.loads(_read(path))
        except tomllib.TOMLDecodeError:
            continue
        document = manifest.as_table(parsed)
        ruff = manifest.as_table(manifest.as_table(document.get("tool")).get("ruff"))
        if not ruff:
            ruff = document
        if not isinstance(ruff.get("extend"), str):
            continue
        lint = manifest.as_table(ruff.get("lint"))
        table = "tool.ruff.lint" if path.name == "pyproject.toml" else "lint"
        for key in sorted(_RUFF_REPLACEMENT_KEYS.intersection(lint)):
            yield Finding(
                Level.DRIFT,
                f"{path.relative_to(root)}: [{table}].{key}",
                f"replaces inherited Ruff policy; use `extend-{key}` so the canonical config remains authoritative",
            )


def _check_manifest(root: Path) -> Iterator[Finding]:
    try:
        found = manifest.load(root)
    except ValueError as exc:
        yield Finding(Level.DRIFT, manifest.MANIFEST_NAME, str(exc))
        return

    if found is None:
        yield Finding(
            Level.WARN,
            manifest.MANIFEST_NAME,
            "absent -- run `sarj-lint-configs init` so the adopted version has one home",
        )
        return

    current = manifest.adopted_version()
    if found.version == current:
        yield Finding(Level.OK, manifest.MANIFEST_NAME, f"version {found.version}")
        return
    yield Finding(
        Level.DRIFT,
        manifest.MANIFEST_NAME,
        f"declares {found.version} but the installed wheel is {current}"
        " -- re-run `init` (or edit the pin) so they agree",
    )


def _check_pin_files(root: Path, files: Sequence[Path], installed: Mapping[str, str]) -> Iterator[Finding]:
    candidates = (
        path
        for path in files
        if path.name == "package.json" or path.suffix.lower() in {".toml", ".yml", ".yaml", ".cfg", ".txt", ".sh"}
    )
    for path in candidates:
        for match in _PIN.finditer(_read(path)):
            name = match.group("name")
            pinned = match.group("version")
            current = installed.get(name)
            where = f"{path.relative_to(root)}: {name}{match.group('op')}{pinned}"
            if current is None:
                yield Finding(Level.WARN, where, f"{name} is not installed here, so the pin is unverified")
            elif pinned == current:
                yield Finding(Level.OK, where, "matches the installed wheel")
            else:
                yield Finding(Level.DRIFT, where, f"installed {name} is {current}")


def _check_precommit_revs(root: Path, files: Sequence[Path]) -> Iterator[Finding]:
    expected = manifest.expected_precommit_rev()
    for path in _candidate_files(files, (".yml", ".yaml")):
        text = _read(path)
        if "sarj-ai/standards" not in text:
            continue
        for match in _REV.finditer(text):
            rev = match.group("rev")
            where = f"{path.relative_to(root)}: rev {rev}"
            if _SHA_REV.match(rev):
                yield Finding(
                    Level.DRIFT,
                    where,
                    "pins the hooks to a commit, not a release, so no tool can tell"
                    f" whether it is current -- pin {expected or 'the release tag'} instead",
                )
            elif expected is None:
                yield Finding(Level.WARN, where, "sarj-python-lint is not installed, so the rev is unverified")
            elif rev == expected:
                yield Finding(Level.OK, where, "matches the installed hook package")
            else:
                yield Finding(
                    Level.DRIFT,
                    where,
                    f"expected {expected} -- the hooks ship from the root package, whose version"
                    " your sarj-lint-configs pin already fixes",
                )


def _check_eslint_plugin(root: Path, files: Sequence[Path]) -> Iterator[Finding]:
    # A missing peer manifest is a packaging defect and must fail loudly.
    floor = manifest.eslint_peers()[_ESLINT_PLUGIN]
    for path in _candidate_files(files, (".json",)):
        if path.name != "package.json":
            continue
        pinned = _package_json_pin(path)
        if pinned is None or pinned.startswith(_LOCAL_SPECIFIERS):
            # Local specs represent unreleased checkouts, not version drift.
            continue
        where = f"{path.relative_to(root)}: {_ESLINT_PLUGIN}@{pinned}"
        if _without_range_operator(pinned) == floor:
            yield Finding(Level.OK, where, "matches the tested peer set")
        else:
            yield Finding(
                Level.DRIFT,
                where,
                f"the bundled eslint.strict.mjs is tested against {floor};"
                " see `sarj-lint-configs peers` for the whole resolvable set",
            )


#: Single-version range operators in longest-first match order.
_RANGE_OPERATORS: Final = (">=", "<=", "~=", "==", "^", "~", ">", "<", "=", "v")


def _without_range_operator(pinned: str) -> str:
    """Remove at most one leading range operator from a version pin."""
    for operator in _RANGE_OPERATORS:
        if pinned.startswith(operator):
            return pinned[len(operator) :].strip()
    return pinned


def _package_json_pin(path: Path) -> str | None:
    try:
        parsed: object = json.loads(_read(path))  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
    except json.JSONDecodeError:
        return None
    package_json = manifest.as_table(parsed)
    for field in ("dependencies", "devDependencies"):
        pinned = manifest.as_table(package_json.get(field)).get(_ESLINT_PLUGIN)
        if isinstance(pinned, str):
            return pinned
    return None


def _candidate_files(files: Sequence[Path], suffixes: Sequence[str]) -> Iterator[Path]:
    wanted = frozenset(suffixes)
    for path in files:
        if path.suffix.lower() in wanted:
            yield path


def _walk(root: Path) -> tuple[Path, ...]:
    """List a repo's files once, pruning the directories nothing is ever found in."""
    found: list[Path] = []
    for parent, directories, names in os.walk(root):
        directories[:] = sorted(name for name in directories if name not in _SKIP_DIRS)
        here = Path(parent)
        found.extend(path for name in sorted(names) if not (path := here / name).is_symlink() and path.is_file())
    return tuple(found)


def _read(path: Path) -> str:
    """Read a repository file while replacing invalid UTF-8 bytes."""
    return path.read_bytes().decode("utf-8", errors="replace")


def parse_pins(text: str) -> dict[str, str]:
    """Extract every Sarj version pin from a file's text."""
    return {match.group("name"): match.group("version") for match in _PIN.finditer(text)}


def parse_revs(text: str) -> list[str]:
    """Extract every pre-commit `rev:` tag from a file's text."""
    return [match.group("rev") for match in _REV.finditer(text)]
