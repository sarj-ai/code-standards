"""Detect a repo's npm client, and speak its dialect for overrides and installs.

The shipped ESLint peer set does not resolve without an override -- the config's
unicorn floor needs `eslint >= 10.4` and the newest `eslint-plugin-react` peers
`eslint <= ^9.7` -- and every package manager spells that override differently:
npm nests it under `overrides`, pnpm under `pnpm.overrides` with a `parent>child`
selector, Yarn under `resolutions` with a `parent/child` path and no `$dep`
indirection. `init` emitted the npm spelling unconditionally, which is not a
degraded experience for the others: pnpm and Yarn ignore a stray `overrides` key
entirely, so the install fails exactly as it would have with no override at all,
and the printed next step is an `npm install` the repo must not run.

Detection is by lockfile first because the lockfile is also what says WHERE the
project root is, which is the same question `init` has to answer to place the
config next to a `node_modules`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import TYPE_CHECKING, Final

from . import manifest


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path


class PackageManager(StrEnum):
    """The npm clients a consumer repo can be built on."""

    NPM = "npm"
    PNPM = "pnpm"
    YARN = "yarn"
    BUN = "bun"


#: Lockfile name to the client that writes it. Checked in this order, so a repo
#: carrying two lockfiles resolves the same way every run.
LOCKFILES: Final[tuple[tuple[str, PackageManager], ...]] = (
    ("pnpm-lock.yaml", PackageManager.PNPM),
    ("yarn.lock", PackageManager.YARN),
    ("bun.lock", PackageManager.BUN),
    ("bun.lockb", PackageManager.BUN),
    ("package-lock.json", PackageManager.NPM),
)

_ESLINT: Final = "eslint"


def detect(root: Path) -> PackageManager:
    """Decide which npm client a directory is managed by.

    The `packageManager` field is authoritative when present -- Corepack enforces
    it, so a repo that declares Yarn cannot be installed with npm whatever its
    lockfiles say -- and the lockfile answers for everyone else.

    Returns:
        The detected client, defaulting to npm.

    """
    declared = _declared_manager(root / "package.json")
    if declared is not None:
        return declared
    for name, client in LOCKFILES:
        if (root / name).is_file():
            return client
    return PackageManager.NPM


def _declared_manager(package_json: Path) -> PackageManager | None:
    if not package_json.is_file():
        return None
    try:
        parsed: object = json.loads(  # pyright: ignore[reportAny] -- json.loads is an untyped stdlib boundary; the shape is narrowed below
            package_json.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    declared = manifest.text_field(manifest.as_table(parsed), "packageManager")
    if declared is None:
        return None
    name = declared.split("@", 1)[0]
    return next((client for client in PackageManager if client == name), None)


@dataclass(frozen=True)
class Overrides:
    """One package manager's spelling of the peer overrides."""

    #: The `package.json` key path the block lives under, outermost first.
    key_path: tuple[str, ...]
    entries: dict[str, object]

    def as_document(self) -> dict[str, object]:
        """Nest the entries under their key path, for printing.

        Returns:
            A `package.json` fragment a reader can paste.

        """
        document: dict[str, object] = dict(self.entries)
        for key in reversed(self.key_path):
            document = {key: document}
        return document


def overrides_for(client: PackageManager) -> Overrides:
    """Translate the bundled npm overrides into one client's dialect.

    Returns:
        The key path and entries to merge into a consumer `package.json`.

    """
    npm_entries = manifest.eslint_overrides()
    match client:
        case PackageManager.NPM | PackageManager.BUN:
            return Overrides(("overrides",), npm_entries)
        case PackageManager.PNPM:
            return Overrides(("pnpm", "overrides"), dict(_flatten(npm_entries, ">")))
        case PackageManager.YARN:
            return Overrides(("resolutions",), dict(_flatten(npm_entries, "/")))


def _flatten(entries: Mapping[str, object], separator: str) -> Iterator[tuple[str, str]]:
    """Rewrite npm's nested overrides as the flat selectors pnpm and Yarn take.

    npm expresses "force this version of `child` only underneath `parent`" by
    nesting; pnpm and Yarn express it as one `parent>child` / `parent/child` key.
    npm's `$dep` indirection ("whatever the root depends on") is resolved here
    against the shipped peer set, because Yarn has no equivalent and a literal
    `$eslint` in a `resolutions` entry is a version range Yarn cannot parse.

    Yields:
        Selector and version, one per leaf.

    """
    peers = manifest.eslint_peers()
    for parent, value in entries.items():
        nested = manifest.as_table(value)
        if not nested:
            yield parent, _resolved(value, peers)
            continue
        for child, pin in nested.items():
            yield f"{parent}{separator}{child}", _resolved(pin, peers)


def _resolved(value: object, peers: Mapping[str, str]) -> str:
    if not isinstance(value, str):
        return str(value)
    if not value.startswith("$"):
        return value
    return peers.get(value.removeprefix("$"), value)


def install_command(client: PackageManager) -> str:
    """Build the command that installs every ESLint peer at a resolvable version.

    Returns:
        A single copy-pasteable invocation for the detected client.

    """
    specs = " ".join(f"{name}@{pin}" for name, pin in sorted(manifest.eslint_peers().items()))
    match client:
        case PackageManager.NPM:
            return f"npm install -D --save-exact {specs}"
        case PackageManager.PNPM:
            return f"pnpm add -D --save-exact {specs}"
        case PackageManager.YARN:
            return f"yarn add -D --exact {specs}"
        case PackageManager.BUN:
            return f"bun add -d --exact {specs}"


def install_note(client: PackageManager) -> str | None:
    """Explain the one thing each client needs beyond the install command.

    Returns:
        A caveat to print, or None when there is none.

    """
    if client is PackageManager.YARN:
        return (
            "Yarn resolves `resolutions` at install time, so re-run `yarn install`"
            f" after the block is written -- and note Yarn pins {_ESLINT} for"
            " eslint-plugin-react to an exact version rather than tracking your own."
            " Yarn 4.15+ also refuses a package published within its minimum release"
            " age (`All versions satisfying ... are quarantined`); if a fresh"
            " @sarj/eslint-plugin trips that, set `npmMinimalAgeGate: 0` in"
            " .yarnrc.yml or wait it out."
        )
    if client is PackageManager.PNPM:
        return (
            "pnpm reads overrides only from the workspace root package.json;"
            " keep the block there if this project is part of a pnpm workspace."
        )
    return None
