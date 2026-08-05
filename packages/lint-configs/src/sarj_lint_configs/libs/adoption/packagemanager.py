"""Detect a repo's npm client, and speak its dialect for overrides and installs."""

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


class PackageManager(StrEnum):
    """The npm clients a consumer repo can be built on."""

    NPM = "npm"
    PNPM = "pnpm"
    YARN = "yarn"
    BUN = "bun"


#: Lockfiles in deterministic package-manager precedence order.
LOCKFILES: Final[tuple[tuple[str, PackageManager], ...]] = (
    ("pnpm-lock.yaml", PackageManager.PNPM),
    ("yarn.lock", PackageManager.YARN),
    ("bun.lock", PackageManager.BUN),
    ("bun.lockb", PackageManager.BUN),
    ("package-lock.json", PackageManager.NPM),
)

_ESLINT: Final = "eslint"
_YAML_ENTRY = re.compile(r'^\s*(?P<key>"[^"]+"|\'[^\']+\'|[^:#]+):\s*(?P<value>[^#\n]+?)\s*(?:#.*)?$')


def detect(root: Path) -> PackageManager:
    """Select the declared package manager or infer one from its lockfile."""
    declared = _declared_manager(root / "package.json")
    if declared is not None:
        return declared
    detected = {client for name, client in LOCKFILES if (root / name).is_file()}
    if len(detected) > 1:
        names = ", ".join(sorted(str(client) for client in detected))
        msg = f"conflicting package-manager lockfiles in {root}: {names}"
        raise ValueError(msg)
    if detected:
        return next(iter(detected))
    return PackageManager.NPM


def workspace_root(project_root: Path, repository_root: Path) -> Path:
    """Find the package-manager root without ever ascending past the repository."""
    repository = repository_root.resolve()
    project = project_root.resolve()
    try:
        project.relative_to(repository)
    except ValueError as exc:
        msg = f"TypeScript project {project} is outside repository {repository}"
        raise ValueError(msg) from exc
    candidates = (project, *project.parents)
    bounded = [path for path in candidates if path == repository or repository in path.parents]
    pnpm = next((path for path in bounded if (path / "pnpm-workspace.yaml").is_file()), None)
    if pnpm is not None:
        return pnpm
    roots = [path for path in bounded if _declared_manager(path / "package.json") is not None or _has_lock(path)]
    return roots[0] if roots else project


def _has_lock(root: Path) -> bool:
    return any((root / name).is_file() for name, _client in LOCKFILES)


def _declared_manager(package_json: Path) -> PackageManager | None:
    if not package_json.is_file():
        return None
    try:
        parsed: object = json.loads(  # pyright: ignore[reportAny] -- json.loads is an untyped stdlib boundary; the shape is narrowed below
            package_json.read_text(encoding="utf-8")
        )
    except OSError, ValueError:
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
        """Nest the entries under their key path, for printing."""
        document: dict[str, object] = dict(self.entries)
        for key in reversed(self.key_path):
            document = {key: document}
        return document


def overrides_for(client: PackageManager) -> Overrides:
    """Translate the bundled npm overrides into one client's dialect."""
    npm_entries = manifest.eslint_overrides()
    match client:
        case PackageManager.NPM:
            return Overrides(("overrides",), npm_entries)
        case PackageManager.PNPM:
            return Overrides(("pnpm", "overrides"), dict(_flatten(npm_entries, ">")))
        case PackageManager.YARN:
            return Overrides(("resolutions",), dict(_flatten(npm_entries, "/")))
        case PackageManager.BUN:
            # Bun ignores nested npm overrides, so pin ESLint at the root.
            return Overrides(("overrides",), {_ESLINT: manifest.eslint_peers()[_ESLINT]})


def pnpm_workspace_values(text: str) -> dict[str, str]:
    """Read scalar pnpm workspace override entries without accepting comments."""
    values: dict[str, str] = {}
    in_overrides = False
    for line in text.splitlines():
        if re.match(r"^overrides:\s*(?:#.*)?$", line):
            in_overrides = True
            continue
        if in_overrides and line and not line[0].isspace():
            break
        if not in_overrides or (match := _YAML_ENTRY.match(line)) is None:
            continue
        key = match.group("key").strip().strip("\"'")
        value = match.group("value").strip().strip("\"'")
        values[key] = value
    return values


def _flatten(entries: Mapping[str, object], separator: str) -> Iterator[tuple[str, str]]:
    """Rewrite npm's nested overrides as the flat selectors pnpm and Yarn take.

    npm expresses "force this version of `child` only underneath `parent`" by
    nesting; pnpm and Yarn express it as one `parent>child` / `parent/child` key.
    npm's `$dep` indirection ("whatever the root depends on") is resolved here
    against the shipped peer set, because Yarn has no equivalent and a literal
    `$eslint` in a `resolutions` entry is a version range Yarn cannot parse.

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


def install_command(client: PackageManager, *, workspace: bool = False) -> str:
    """Build the command that installs every ESLint peer at a resolvable version."""
    specs = " ".join(f"{name}@{pin}" for name, pin in sorted(manifest.eslint_peers().items()))
    match client:
        case PackageManager.NPM:
            return f"npm install -D --save-exact {specs}"
        case PackageManager.PNPM:
            root_flag = " -w" if workspace else ""
            return f"pnpm add{root_flag} -D --save-exact {specs}"
        case PackageManager.YARN:
            return f"yarn add -D --exact {specs}"
        case PackageManager.BUN:
            return f"bun add -d --exact {specs}"


def install_argv(client: PackageManager, *, workspace: bool = False) -> Sequence[str]:
    specs = tuple(f"{name}@{pin}" for name, pin in sorted(manifest.eslint_peers().items()))
    match client:
        case PackageManager.NPM:
            return ("npm", "install", "-D", "--save-exact", *specs)
        case PackageManager.PNPM:
            root_flag = ("-w",) if workspace else ()
            return ("pnpm", "add", *root_flag, "-D", "--save-exact", *specs)
        case PackageManager.YARN:
            return ("yarn", "add", "-D", "--exact", *specs)
        case PackageManager.BUN:
            return ("bun", "add", "-d", "--exact", *specs)


def exec_argv(client: PackageManager, *command: str) -> Sequence[str]:
    match client:
        case PackageManager.NPM:
            return ("npx", "--no-install", *command)
        case PackageManager.PNPM:
            return ("pnpm", "exec", *command)
        case PackageManager.YARN:
            return ("yarn", "exec", *command)
        case PackageManager.BUN:
            return ("bunx", "--bun", *command)


def install_note(client: PackageManager) -> str | None:
    """Explain the one thing each client needs beyond the install command."""
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
            "Keep pnpm overrides at the detected workspace root; pnpm 11 workspaces"
            " use pnpm-workspace.yaml while older layouts may use package.json."
        )
    return None
