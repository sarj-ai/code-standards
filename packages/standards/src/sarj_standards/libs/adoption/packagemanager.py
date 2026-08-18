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
    NPM = "npm"
    PNPM = "pnpm"
    YARN = "yarn"
    BUN = "bun"


class YarnVariant(StrEnum):
    CLASSIC = "classic"
    BERRY = "berry"


#: Lockfiles in deterministic package-manager precedence order.
LOCKFILES: Final[tuple[tuple[str, PackageManager], ...]] = (
    ("pnpm-lock.yaml", PackageManager.PNPM),
    ("yarn.lock", PackageManager.YARN),
    ("bun.lock", PackageManager.BUN),
    ("bun.lockb", PackageManager.BUN),
    ("package-lock.json", PackageManager.NPM),
)

_ESLINT: Final = "eslint"
_YARN_BERRY_MINIMUM_MAJOR: Final = 2
_YAML_ENTRY = re.compile(r'^\s*(?P<key>"[^"]+"|\'[^\']+\'|[^:#]+):\s*(?P<value>[^#\n]+?)\s*(?:#.*)?$')
_EXACT_VERSION = re.compile(
    r"^(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)"
    r"(?:\+sha(?:224|256|384|512)\.[0-9a-f]+)?$"
)


def detect(root: Path) -> PackageManager:
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


def yarn_variant(root: Path) -> YarnVariant:
    declared = _declared_manager_spec(root / "package.json")
    if declared is not None and declared.split("@", 1)[0] == PackageManager.YARN:
        major = declared.partition("@")[2].partition(".")[0]
        if major.isdigit():
            return YarnVariant.CLASSIC if int(major) < _YARN_BERRY_MINIMUM_MAJOR else YarnVariant.BERRY
    if (root / ".yarnrc.yml").is_file():
        return YarnVariant.BERRY
    return YarnVariant.CLASSIC


def declared_version(root: Path, client: PackageManager) -> str | None:
    declared = _declared_manager_spec(root / "package.json")
    if declared is None:
        return None
    name, separator, raw_version = declared.partition("@")
    if name != client or not separator:
        return None
    match = _EXACT_VERSION.fullmatch(raw_version)
    if match is None:
        msg = f"packageManager {declared!r} must pin an exact semantic version"
        raise ValueError(msg)
    return match.group("version")


def _declared_manager_spec(package_json: Path) -> str | None:
    if not package_json.is_file():
        return None
    try:
        parsed: object = json.loads(  # pyright: ignore[reportAny] -- json.loads is an untyped stdlib boundary; the shape is narrowed below
            package_json.read_text(encoding="utf-8")
        )
    except OSError, ValueError:
        return None
    return manifest.text_field(manifest.as_table(parsed), "packageManager")


def _declared_manager(package_json: Path) -> PackageManager | None:
    declared = _declared_manager_spec(package_json)
    if declared is None:
        return None
    name = declared.split("@", 1)[0]
    selected = next((client for client in PackageManager if client == name), None)
    if selected is None:
        supported = ", ".join(str(client) for client in PackageManager)
        msg = f"unsupported packageManager {declared!r} in {package_json}; supported managers: {supported}"
        raise ValueError(msg)
    return selected


@dataclass(frozen=True)
class Overrides:
    #: The package-manager policy document key path, outermost first.
    key_path: tuple[str, ...]
    entries: dict[str, object]

    def as_document(self) -> dict[str, object]:
        document: dict[str, object] = dict(self.entries)
        for key in reversed(self.key_path):
            document = {key: document}
        return document


def overrides_for(client: PackageManager) -> Overrides:
    npm_entries = manifest.eslint_overrides()
    match client:
        case PackageManager.NPM:
            return Overrides(("overrides",), {name: _resolved_tree(value) for name, value in npm_entries.items()})
        case PackageManager.PNPM:
            return Overrides(("overrides",), dict(_flatten(npm_entries, ">")))
        case PackageManager.YARN:
            return Overrides(("resolutions",), dict(_flatten(npm_entries, "/")))
        case PackageManager.BUN:
            # Bun ignores nested npm overrides, so pin ESLint at the root.
            return Overrides(("overrides",), {_ESLINT: manifest.eslint_peers()[_ESLINT]})


def pnpm_workspace_values(text: str) -> dict[str, str]:
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


def _resolved_tree(value: object) -> object:
    nested = manifest.as_table(value)
    if nested:
        return {name: _resolved_tree(pin) for name, pin in nested.items()}
    return _resolved(value, manifest.eslint_peers())


def install_command(
    client: PackageManager,
    *,
    workspace: bool = False,
    yarn: YarnVariant = YarnVariant.CLASSIC,
) -> str:
    match client:
        case PackageManager.NPM:
            return "npm install --ignore-scripts --no-audit --no-fund"
        case PackageManager.PNPM:
            suffix = "" if workspace else " --ignore-workspace"
            return f"pnpm install --no-frozen-lockfile --ignore-scripts{suffix}"
        case PackageManager.YARN:
            if yarn is YarnVariant.BERRY:
                return "yarn install --no-immutable --mode=skip-build"
            return "yarn install --ignore-scripts"
        case PackageManager.BUN:
            return "bun install --ignore-scripts"


def install_argv(
    client: PackageManager,
    *,
    workspace: bool = False,
    yarn: YarnVariant = YarnVariant.CLASSIC,
) -> Sequence[str]:
    return tuple(install_command(client, workspace=workspace, yarn=yarn).split())


def exec_argv(client: PackageManager, *command: str) -> Sequence[str]:
    match client:
        case PackageManager.NPM:
            return ("npm", "exec", "--offline", "--", *command)
        case PackageManager.PNPM:
            # `pnpm exec` only resolves binaries from the installed dependency
            # tree. Unlike `pnpm dlx`, it never downloads a missing package, so
            # an `--offline` flag is both unnecessary and invalid on pnpm 11.
            return ("pnpm", "exec", *command)
        case PackageManager.YARN:
            return ("yarn", "exec", *command)
        case PackageManager.BUN:
            return ("bunx", "--bun", "--no-install", *command)


def install_note(client: PackageManager, *, yarn: YarnVariant = YarnVariant.CLASSIC) -> str | None:
    if client is PackageManager.YARN:
        note = (
            "Yarn resolves `resolutions` at install time, so re-run `yarn install`"
            f" after the block is written -- and note Yarn pins {_ESLINT} for"
            " eslint-plugin-react to an exact version rather than tracking your own."
        )
        if yarn is YarnVariant.BERRY:
            note += (
                " Yarn 4.15+ also refuses a package published within its minimum release"
                " age (`All versions satisfying ... are quarantined`); if a fresh"
                " @sarj/eslint-plugin trips that, set `npmMinimalAgeGate: 0` in"
                " .yarnrc.yml or wait it out."
            )
        return note
    if client is PackageManager.PNPM:
        return (
            "Keep pnpm overrides in pnpm-workspace.yaml at the detected install root;"
            " pnpm 11 ignores package.json#pnpm.overrides even for standalone packages."
        )
    return None
