"""Find every place a consumer repo states a Sarj version, and prove they agree.

The failure this exists for is not "a repo is out of date". It is that a repo is
out of date in three DIFFERENT ways at once and nothing tells anyone: the
`pyproject.toml` pin, the pre-commit `rev:` and the version a CI job types on its
own command line are separate strings that no tool has ever compared. A repo can
pass its own CI while running one linter version at commit time, a second in the
`lint` job, and a third for anyone who runs it locally.

`doctor` reads every pin site it can find and compares each to the installed
wheel. It reports, it never rewrites: the fix is a one-line edit the reader can
see, and a tool that silently rewrote pins would just move the surprise.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import re
from typing import TYPE_CHECKING, Final

from . import manifest


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path


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

#: `rev: python-v0.19.0`, `rev: "lint-configs-v0.10.0"`.
_REV = re.compile(r"""rev:\s*['"]?(?P<rev>[a-z-]+-v[0-9][0-9A-Za-z.\-]*)['"]?""")

_ESLINT_PLUGIN: Final = "@sarj/eslint-plugin"
_LOCAL_SPECIFIERS: Final = ("file:", "link:", "workspace:", "portal:")

_SKIP_DIRS: Final = frozenset({
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".uv-cache",
    ".venv",
    "dist",
    "node_modules",
    "target",
    "vendor",
})


def diagnose(root: Path) -> list[Finding]:
    """Check every version-bearing file under a repo root.

    Returns:
        One finding per checked site, in reading order.

    """
    installed = manifest.installed_versions()
    findings = [*_check_manifest(root)]
    findings.extend(_check_pin_files(root, installed))
    findings.extend(_check_precommit_revs(root))
    findings.extend(_check_eslint_plugin(root))
    return findings


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


def _check_pin_files(root: Path, installed: Mapping[str, str]) -> Iterator[Finding]:
    for path in _candidate_files(root, (".toml", ".yml", ".yaml", ".cfg", ".txt", ".sh")):
        for match in _PIN.finditer(_read(path)):
            name = match.group("name")
            pinned = match.group("version")
            current = installed.get(name)
            where = f"{path.relative_to(root)}: {name}{match.group("op")}{pinned}"
            if current is None:
                yield Finding(Level.WARN, where, f"{name} is not installed here, so the pin is unverified")
            elif pinned == current:
                yield Finding(Level.OK, where, "matches the installed wheel")
            else:
                yield Finding(Level.DRIFT, where, f"installed {name} is {current}")


def _check_precommit_revs(root: Path) -> Iterator[Finding]:
    expected = manifest.expected_precommit_rev()
    for path in _candidate_files(root, (".yml", ".yaml")):
        text = _read(path)
        if "sarj-ai/standards" not in text:
            continue
        for match in _REV.finditer(text):
            rev = match.group("rev")
            where = f"{path.relative_to(root)}: rev {rev}"
            if expected is None:
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


def _check_eslint_plugin(root: Path) -> Iterator[Finding]:
    # The peer manifest ships inside this wheel, so a missing or malformed one is
    # a packaging bug in THIS package, not a condition a consumer repo can be in.
    # Letting it raise is the point: swallowing it would turn "we shipped a broken
    # wheel" into "your package.json is fine".
    floor = manifest.eslint_peers()[_ESLINT_PLUGIN]
    for path in _candidate_files(root, (".json",)):
        if path.name != "package.json":
            continue
        pinned = _package_json_pin(path)
        if pinned is None or pinned.startswith(_LOCAL_SPECIFIERS):
            # `file:`, `link:` and `workspace:` name a checkout, not a release.
            # Reporting those as drift would make `doctor` cry wolf in exactly
            # the repos that are developing against an unreleased build.
            continue
        where = f"{path.relative_to(root)}: {_ESLINT_PLUGIN}@{pinned}"
        if pinned.lstrip("^~=") == floor:
            yield Finding(Level.OK, where, "matches the tested peer set")
        else:
            yield Finding(
                Level.DRIFT,
                where,
                f"the bundled eslint.strict.mjs is tested against {floor};"
                " see `sarj-lint-configs peers` for the whole resolvable set",
            )


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


def _candidate_files(root: Path, suffixes: Sequence[str]) -> Iterator[Path]:
    wanted = frozenset(suffixes)
    for path in sorted(root.rglob("*")):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.lower() in wanted:
            yield path


def _read(path: Path) -> str:
    """Read a repo file as text, tolerating anything that is not UTF-8.

    Decoding with `errors="replace"` rather than catching: every caller only
    ever regex-searches the result for ASCII pins, so a mangled byte cannot
    change an answer, and there is no exception to swallow into a sentinel.

    Returns:
        The file's text, with undecodable bytes replaced.

    """
    return path.read_bytes().decode("utf-8", errors="replace")


def parse_pins(text: str) -> dict[str, str]:
    """Extract every Sarj version pin from a file's text.

    Exposed so tests can assert on the pattern that does the real work rather
    than on a formatted report.

    Returns:
        Distribution name to pinned version; the last pin in the text wins.

    """
    return {match.group("name"): match.group("version") for match in _PIN.finditer(text)}


def parse_revs(text: str) -> list[str]:
    """Extract every pre-commit `rev:` tag from a file's text.

    Returns:
        Tags in the order they appear.

    """
    return [match.group("rev") for match in _REV.finditer(text)]


def worst(findings: Sequence[Finding]) -> Level:
    """Reduce a report to the level that should decide the exit status.

    Returns:
        The most severe level present, or `OK` for an empty report.

    """
    if any(finding.level is Level.DRIFT for finding in findings):
        return Level.DRIFT
    if any(finding.level is Level.WARN for finding in findings):
        return Level.WARN
    return Level.OK
