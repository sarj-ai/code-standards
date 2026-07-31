"""The one file a consumer repo pins, and the versions everything else must match.

A consumer had three independent pin sites -- `pyproject.toml`, the pre-commit
`rev:`, and whatever the CI job typed on its own command line -- and nothing
compared them, so they drifted apart silently and stayed drifted. This module
makes one of them authoritative: `.sarj-standards.toml` records the
`sarj-lint-configs` version a repo adopted and which configs it actually uses.
Every other pin is DERIVED from the installed wheel rather than restated by
hand, because `sarj-lint-configs` already pins its siblings exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
import json
import tomllib
from typing import TYPE_CHECKING, Final

from ._meta import CONFIGS_DIR, __version__


if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path


MANIFEST_NAME: Final = ".sarj-standards.toml"
_CONFIGS_KEY: Final = "configs"

PEERS_JSON: Final = CONFIGS_DIR / "eslint.peers.json"

#: Sibling distributions whose versions `sarj-lint-configs` pins exactly. A
#: consumer never chooses these; a pin site naming one is checked against the
#: version that shipped inside the wheel it already installed.
LINT_CONFIGS: Final = "sarj-lint-configs"
_PYTHON_LINT: Final = "sarj-python-lint"
SIBLING_PACKAGES: Final = (_PYTHON_LINT, "sarj-sql-lint", "sarj-iac-lint")


def adopted_version() -> str:
    """Report the `sarj-lint-configs` version this environment provides.

    Returns:
        The installed wheel's version.

    """
    return __version__


#: Configs each ecosystem actually consumes. The old `sync` wrote all six
#: unconditionally, so a Python-only repo had to commit `eslint.strict.mjs` --
#: and keep it byte-identical -- or give up on `sync --check` in CI entirely.
PYTHON_CONFIGS: Final = ("ruff", "pyright")
TYPESCRIPT_CONFIGS: Final = ("eslint",)
SHARED_CONFIGS: Final = ("markdownlint", "taplo", "yamllint")


@dataclass(frozen=True)
class Manifest:
    """A consumer repo's declared adoption of this package."""

    version: str
    configs: tuple[str, ...]
    python_dest: str
    typescript_dest: str

    def render(self) -> str:
        """Serialise to the TOML text written at the repo root.

        Returns:
            The full file contents, comments included.

        """
        configs = ", ".join(f'"{name}"' for name in self.configs)
        return (
            "# Written by `sarj-lint-configs init`. Commit this file.\n"
            "#\n"
            "# This is the ONE version for the whole toolchain. Your pyproject pin, your\n"
            "# pre-commit `rev:` and your CI job must all agree with it; run\n"
            "# `sarj-lint-configs doctor` to prove they do. The sibling linter versions are\n"
            "# not listed because they are not yours to choose -- sarj-lint-configs pins them\n"
            "# exactly, and `doctor` reads them out of the installed wheel.\n"
            f'version = "{self.version}"\n'
            "\n"
            "# Only the configs this repo actually uses. `sync` and `sync --check` operate on\n"
            "# exactly this list, so a Python repo is not asked to carry an ESLint config.\n"
            f"configs = [{configs}]\n"
            "\n"
            "[dest]\n"
            f'python = "{self.python_dest}"\n'
            f'typescript = "{self.typescript_dest}"\n'
        )


def as_table(value: object) -> dict[str, object]:
    """Read an untyped mapping as a string-keyed table of unknown values.

    `json.loads` and `tomllib.loads` hand back `Any`, and narrowing one with
    `isinstance(x, dict)` only gets as far as `dict[Unknown, Unknown]`. Funnelling
    every parsed table through here is what lets the rest of this package stay
    fully typed while reading files it does not control.

    Returns:
        The mapping's string-keyed entries, or an empty table for anything else.

    """
    if not isinstance(value, dict):
        return {}
    # A `dict` narrowed out of an untyped parser is `dict[Unknown, Unknown]`, and
    # the three suppressions below are the entire cost of that, paid once for the
    # whole package. Everything downstream of this return sees `dict[str, object]`
    # and is checked normally -- which is the point of routing every parsed table
    # through one function instead of narrowing at each call site.
    mapping: Mapping[object, object] = value  # pyright: ignore[reportUnknownVariableType]
    entries: Iterable[tuple[object, object]] = mapping.items()  # pyright: ignore[reportUnknownVariableType]
    return {
        key: item for key, item in entries if isinstance(key, str)  # pyright: ignore[reportUnknownVariableType]
    }


def text_field(table: Mapping[str, object], key: str) -> str | None:
    """Read one string out of an untyped table.

    Returns:
        The value when it is a string, else `None`.

    """
    value = table.get(key)
    return value if isinstance(value, str) else None


def list_field(table: Mapping[str, object], key: str) -> list[object]:
    """Read one list out of an untyped table.

    Returns:
        The value when it is a list, else an empty list.

    """
    value = table.get(key)
    return value if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType] — a narrowed `list` from an untyped parser has Unknown leaves


def table_field(table: Mapping[str, object], key: str) -> dict[str, object]:
    """Read one nested table out of an untyped table.

    Returns:
        The nested table, or an empty one.

    """
    return as_table(table.get(key))


def default_configs(*, has_python: bool, has_typescript: bool) -> tuple[str, ...]:
    """Pick the config set for a repo's detected ecosystems.

    Returns:
        Config names in the CLI's canonical order.

    """
    selected: set[str] = set(SHARED_CONFIGS)
    if has_python:
        selected.update(PYTHON_CONFIGS)
    if has_typescript:
        selected.update(TYPESCRIPT_CONFIGS)
    order = (*PYTHON_CONFIGS, *TYPESCRIPT_CONFIGS, *SHARED_CONFIGS)
    return tuple(name for name in order if name in selected)


def manifest_path(root: Path) -> Path:
    """Locate the manifest for a repo root.

    Returns:
        The path the manifest occupies, whether or not it exists.

    """
    return root / MANIFEST_NAME


def load(root: Path) -> Manifest | None:
    """Read a repo's manifest.

    Returns:
        The parsed manifest, or `None` when the repo has not run `init`.

    Raises:
        ValueError: If the manifest exists but is not valid TOML.
        TypeError: If the manifest is valid TOML with the wrong shape.

    """
    path = manifest_path(root)
    if not path.is_file():
        return None
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{path} is not valid TOML: {exc}"
        raise ValueError(msg) from exc

    data = as_table(parsed)
    declared = text_field(data, "version")
    names = list_field(data, _CONFIGS_KEY)
    declares_a_list = isinstance(_configs_entry(data), list)
    if declared is None or not declares_a_list:
        msg = f"{path} must set a string `version` and a list `configs`"
        raise TypeError(msg)
    if not all(isinstance(name, str) for name in names):
        msg = f"{path} `configs` must contain only strings"
        raise TypeError(msg)

    dest_table = table_field(data, "dest")
    return Manifest(
        version=declared,
        configs=tuple(name for name in names if isinstance(name, str)),
        python_dest=_dest_value(dest_table, "python"),
        typescript_dest=_dest_value(dest_table, "typescript"),
    )


def _configs_entry(table: Mapping[str, object]) -> object:
    """Read the raw `configs` entry so its TYPE can be validated, not just its contents."""
    return table.get(_CONFIGS_KEY)


def _dest_value(table: dict[str, object], key: str) -> str:
    return text_field(table, key) or "."


def installed_versions() -> dict[str, str]:
    """Report the versions of every Sarj distribution in the current environment.

    Returns:
        Distribution name to version; absent packages are omitted.

    """
    found = {LINT_CONFIGS: __version__}
    for name in SIBLING_PACKAGES:
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            continue
    return found


def expected_precommit_rev() -> str | None:
    """Derive the `rev:` a repo's pre-commit config must carry.

    The hooks in `.pre-commit-hooks.yaml` are published from the ROOT package,
    which is `sarj-python-lint`, so the tag is `python-v<its version>` -- not
    the `sarj-lint-configs` version a consumer pinned. Deriving it removes the
    one place a consumer was expected to know that mapping by heart.

    Returns:
        The expected tag, or `None` when `sarj-python-lint` is not installed.

    """
    installed = text_field(installed_versions(), _PYTHON_LINT)
    return None if installed is None else f"python-v{installed}"


def eslint_peers() -> dict[str, str]:
    """Read the tested npm version set for the bundled ESLint config.

    Returns:
        Package name to exact version.

    Raises:
        TypeError: If the bundled manifest is malformed.

    """
    parsed: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
        PEERS_JSON.read_text(encoding="utf-8")
    )
    table = table_field(as_table(parsed), "peers")
    if not table:
        msg = f"{PEERS_JSON} must contain a `peers` object"
        raise TypeError(msg)
    return {name: pin for name, pin in table.items() if isinstance(pin, str)}


def eslint_overrides() -> dict[str, object]:
    """Read the npm `overrides` the peer set needs to install at all.

    Not a nicety. The config's `eslint-plugin-unicorn` floor pulls
    `eslint >= 10.4`, while the newest published `eslint-plugin-react` peers
    `eslint <= ^9.7`; npm exits ERESOLVE and the config is simply unreachable.
    An `overrides` entry is the documented npm escape, and it belongs in the
    consumer's `package.json` where they can see it.

    Returns:
        The `overrides` object to merge into a consumer `package.json`.

    """
    parsed: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
        PEERS_JSON.read_text(encoding="utf-8")
    )
    return table_field(as_table(parsed), "npmOverrides")


def eslint_install_command() -> str:
    """Build the npm command that installs every ESLint peer at a resolvable version.

    Returns:
        A single copy-pasteable `npm install` invocation.

    """
    peers = eslint_peers()
    specs = " ".join(f"{name}@{pin}" for name, pin in sorted(peers.items()))
    return f"npm install -D --save-exact {specs}"
