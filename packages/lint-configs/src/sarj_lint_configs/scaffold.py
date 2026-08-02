"""Turn adoption into one command.

Before this, adopting the standards meant reading two READMEs, running `sync`,
then hand-editing four more files that the READMEs describe but no tool writes:
the `[tool.ruff] extend`, `pyrightconfig.json`, `eslint.config.mjs`, and a
pre-commit block. Every one of those is mechanical, and every one of them was a
place to get it subtly wrong -- which is most of why the checked-in state across
consumers looks nothing like the documented state.

`init` writes all of them, for the ecosystems it detects, and never overwrites
something that already exists unless asked. It is deliberately a code generator
with a `--dry-run`, not a framework: everything it emits is plain text the repo
now owns and can read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import textwrap
from typing import TYPE_CHECKING, Final

from . import manifest, packagemanager
from .packagemanager import LOCKFILES, Overrides, PackageManager


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class Ecosystems:
    """What kind of repo this is, and WHERE, decided by files already there.

    The "where" is not a refinement. A repo whose TypeScript lives in a
    subdirectory has no `node_modules` and no `tsconfig.json` at its root, and
    ESLint's flat config is not searched for upward from a subdirectory -- so a
    scaffolder with one destination writes a config that is never loaded, next to
    a `package.json` that does not exist, and reports success. That was two of
    every three layouts measured.
    """

    python: bool
    typescript: bool
    python_root: Path | None = None
    typescript_root: Path | None = None
    client: PackageManager = PackageManager.NPM

    @property
    def any(self) -> bool:
        """Whether anything at all was detected.

        Returns:
            True when at least one ecosystem was found.

        """
        return self.python or self.typescript


@dataclass
class Plan:
    """Everything `init` intends to do, so `--dry-run` and the real run agree."""

    ecosystems: Ecosystems
    configs: tuple[str, ...] = ()
    writes: list[tuple[Path, str]] = field(default_factory=list)
    edits: list[tuple[Path, str]] = field(default_factory=list)
    skips: list[tuple[Path, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


_ESLINT_CONFIG: Final = "eslint.config.mjs"
_PYRIGHT_CONFIG: Final = "pyrightconfig.json"
_PRECOMMIT_CONFIG: Final = ".pre-commit-config.yaml"

_RUFF_EXTEND = re.compile(r"^\s*\[tool\.ruff\]\s*$", re.MULTILINE)

#: Directories a detection walk must not descend into: an installed dependency
#: carries thousands of `package.json` files and a vendored tree carries the
#: pyproject of something this repo did not write.
_SKIP_DIRS: Final = frozenset({
    ".git",
    ".next",
    ".turbo",
    ".wrangler",
    ".yarn",
    "build",
    "coverage",
    ".tox",
    ".venv",
    "dist",
    "node_modules",
    "out",
    "target",
    "vendor",
})


def detect(
    root: Path,
    *,
    python_dest: str | None = None,
    typescript_dest: str | None = None,
) -> Ecosystems:
    """Decide which ecosystems a repo contains, and which directory owns each.

    A repo counts as TypeScript when it has a `package.json` anywhere outside
    `node_modules`, because the sub-project case is the common one: one repo we
    measured ships the strict config at its root while only a fraction of its
    sub-projects wire it in, and a root-only check would call that repo done.

    """
    python_root = _override(root, python_dest) or _python_root(root)
    typescript_root = _override(root, typescript_dest) or _typescript_root(root)
    return Ecosystems(
        python=python_root is not None,
        typescript=typescript_root is not None,
        python_root=python_root,
        typescript_root=typescript_root,
        client=packagemanager.detect(typescript_root) if typescript_root else PackageManager.NPM,
    )


def _override(root: Path, dest: str | None) -> Path | None:
    if dest is None:
        return None
    resolved = (root / dest).resolve()
    return resolved if resolved.is_dir() else None


def _python_root(root: Path) -> Path | None:
    return _shallowest(root, ("pyproject.toml",))


def _typescript_root(root: Path) -> Path | None:
    """Locate the directory an npm client would call the project root.

    The lockfile is the signal, not `package.json`: it is written where installs
    happen, which is where `node_modules`, the `tsconfig.json` and therefore the
    only ESLint config that can load live. A repo can carry a `package.json` at
    its root that declares nothing but `packageManager` while the real project
    is a directory down, and placing the config by `package.json` alone puts it
    where no `node_modules` will ever be.

    Returns:
        The project root, or None when the repo has no TypeScript at all.

    """
    lockfiles = tuple(name for name, _ in LOCKFILES)
    return _shallowest(root, lockfiles) or _shallowest(root, ("package.json",))


def _shallowest(root: Path, names: Sequence[str]) -> Path | None:
    """Find the least-nested directory holding any of `names`.

    Returns:
        That directory, or None when no file matches.

    """
    if any((root / name).is_file() for name in names):
        return root
    found = [
        path.parent
        for name in names
        for path in root.rglob(name)
        if not any(part in _SKIP_DIRS for part in path.relative_to(root).parts)
    ]
    if not found:
        return None
    return min(found, key=lambda path: (len(path.relative_to(root).parts), str(path)))


def build_plan(
    root: Path,
    *,
    force: bool,
    configs: Sequence[str] | None = None,
    python_dest: str | None = None,
    typescript_dest: str | None = None,
) -> Plan:
    """Work out every file `init` would create or amend.

    Returns:
        The plan, whose `writes`/`edits`/`skips` are the whole effect.

    """
    ecosystems = detect(root, python_dest=python_dest, typescript_dest=typescript_dest)
    selected = tuple(configs) if configs else manifest.default_configs(
        has_python=ecosystems.python, has_typescript=ecosystems.typescript
    )
    plan = Plan(ecosystems=ecosystems, configs=selected)

    if not ecosystems.any:
        plan.notes.append(
            "no pyproject.toml and no package.json found -- pass --configs to scaffold anyway"
        )
        return plan

    _plan_manifest(root, plan, force=force)
    if ecosystems.python and ecosystems.python_root is not None:
        _plan_python(ecosystems.python_root, plan, force=force)
    if ecosystems.typescript and ecosystems.typescript_root is not None:
        _plan_typescript(ecosystems.typescript_root, plan, force=force)
    _plan_precommit(root, plan, force=force)
    _note_subproject_destinations(root, plan)
    return plan


def dest_of(root: Path, subdirectory: Path | None) -> str:
    """Express one detected project root the way the manifest records it.

    Returns:
        A repo-root-relative POSIX path, `.` for the root itself.

    """
    if subdirectory is None:
        return "."
    return subdirectory.relative_to(root).as_posix() or "."


def _note_subproject_destinations(root: Path, plan: Plan) -> None:
    """Say out loud when a config landed somewhere other than the repo root.

    Silence here is how the single-destination bug survived: the tool reported
    `wrote: eslint.config.mjs` and the reader had no reason to check whether that
    was the directory their `node_modules` is in.
    """
    for label, subdirectory in (
        ("python", plan.ecosystems.python_root),
        ("typescript", plan.ecosystems.typescript_root),
    ):
        dest = dest_of(root, subdirectory)
        if dest != ".":
            plan.notes.append(
                f"the {label} project is {dest}/, not the repo root, so its configs"
                f" were written there. `sync` reads the same destinations back out of"
                f" {manifest.MANIFEST_NAME}."
            )


def _plan_manifest(root: Path, plan: Plan, *, force: bool) -> None:
    path = manifest.manifest_path(root)
    contents = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=plan.configs,
        python_dest=dest_of(root, plan.ecosystems.python_root),
        typescript_dest=dest_of(root, plan.ecosystems.typescript_root),
    ).render()
    _record(plan, path, contents, force=force, reason="already declares an adopted version")


def _plan_python(root: Path, plan: Plan, *, force: bool) -> None:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        if "extend" in text and ".ruff-strict.toml" in text:
            plan.skips.append((pyproject, "already extends .ruff-strict.toml"))
        elif _RUFF_EXTEND.search(text):
            plan.notes.append(
                f"{pyproject.name} has a [tool.ruff] table already;"
                ' add `extend = ".ruff-strict.toml"` to it by hand'
            )
        else:
            plan.edits.append((pyproject, '\n[tool.ruff]\nextend = ".ruff-strict.toml"\n'))

    _record(
        plan,
        root / _PYRIGHT_CONFIG,
        '{ "extends": ".pyright-strict.json" }\n',
        force=force,
        reason='exists; add `"extends": ".pyright-strict.json"` yourself',
    )


def _plan_typescript(root: Path, plan: Plan, *, force: bool) -> None:
    _record(
        plan,
        root / _ESLINT_CONFIG,
        _eslint_entrypoint(),
        force=force,
        reason="exists; import ./eslint.strict.mjs from it",
    )
    client = plan.ecosystems.client
    _plan_npm_overrides(root, plan, client)
    plan.notes.append(
        f"detected {client} -- install the tested ESLint peer set:"
        f"\n    {packagemanager.install_command(client)}"
    )
    caveat = packagemanager.install_note(client)
    if caveat is not None:
        plan.notes.append(caveat)


def _plan_npm_overrides(root: Path, plan: Plan, client: PackageManager) -> None:
    """Write the overrides without which the peer set cannot be installed at all.

    This used to only PRINT the block, while the README and `eslint.peers.json`
    both said `init` writes it. So the documented one-command adoption path ended
    at `npm error code ERESOLVE` for every TypeScript consumer: the shipped config
    needs ESLint 10 (its unicorn floor pulls `>= 10.4`) and the newest published
    `eslint-plugin-react` peers `eslint <= ^9.7`. This repo only installs because
    `packages/typescript/package.json` carries the same `overrides` privately --
    a workaround present in nothing shipped.

    It then wrote npm's spelling of the block into every repo, which for a pnpm or
    Yarn repo is worse than writing nothing: both ignore a bare `overrides` key,
    so the install fails identically while `package.json` claims to be fixed. The
    block is now translated to the detected client's dialect.

    The file is merged rather than templated because `package.json` is the
    consumer's and may already carry overrides of its own: existing keys are
    preserved and only the ESLint peer entries are added or corrected.
    """
    overrides = packagemanager.overrides_for(client)
    if not overrides.entries:
        return
    printed = textwrap.indent(json.dumps(overrides.as_document(), indent=2), "    ")
    package_json = root / "package.json"
    if not package_json.is_file():
        plan.notes.append(
            f"no package.json in {root}, so the {client} overrides could not be"
            f" merged. {client} cannot resolve the peer set without them -- add by"
            f" hand to whichever package.json installs ESLint:\n{printed}"
        )
        return
    try:
        merged = _merged_npm_overrides(package_json.read_text(encoding="utf-8"), overrides)
    except (TypeError, ValueError):
        plan.notes.append(
            f"package.json could not be parsed, so the {client} overrides were not"
            f" merged. {client} cannot resolve the peer set without them -- add by"
            f" hand:\n{printed}"
        )
        return
    if merged is None:
        plan.skips.append((package_json, f"already carries the {client} peer overrides"))
        return
    plan.writes.append((package_json, merged))
    plan.notes.append(
        f"merged the {client} overrides into {package_json}:\n{printed}\n"
        f"    {client} cannot resolve the tree without them -- eslint-plugin-react"
        " peers eslint <=9.7 and the unicorn floor needs >=10.4."
    )


def _merged_npm_overrides(text: str, overrides: Overrides) -> str | None:
    """Merge the ESLint peer overrides into a package.json's text.

    Returns:
        The rewritten file, or None when every entry is already present and equal.

    Raises:
        TypeError: when the text parses to something other than a JSON object.
            An empty object counts: there is nothing to merge into.
            The caller also catches the `ValueError` `json.loads` raises on text
            that is not JSON at all, so a malformed consumer `package.json`
            degrades to a printed block rather than being overwritten.

    """
    parsed: object = json.loads(text)  # pyright: ignore[reportAny] -- untyped stdlib boundary
    data = manifest.as_table(parsed)
    if not data:
        msg = "package.json must contain a non-empty JSON object"
        raise TypeError(msg)
    *outer, final = overrides.key_path
    container = data
    for key in outer:
        container = manifest.table_field(container, key)
    existing = manifest.table_field(container, final)
    updated = dict(existing)
    for name, value in overrides.entries.items():
        # A consumer may already override the same package for a different
        # reason, so merge the inner table rather than replacing it.
        current_entry = manifest.table_field(updated, name)
        new_entry = manifest.as_table(value)
        updated[name] = {**current_entry, **new_entry} if new_entry else value
    if updated == existing and _has_path(data, overrides.key_path):
        return None
    _set_path(data, overrides.key_path, updated)
    rendered = json.dumps(data, indent=_indent_of(text))
    return rendered + "\n" if text.endswith("\n") else rendered


def _has_path(data: Mapping[str, object], key_path: Sequence[str]) -> bool:
    table: Mapping[str, object] = data
    for key in key_path[:-1]:
        table = manifest.table_field(table, key)
    return key_path[-1] in table


def _set_path(data: dict[str, object], key_path: Sequence[str], value: object) -> None:
    """Write `value` at a nested key path, creating the tables on the way down.

    pnpm reads its overrides from `pnpm.overrides`, so the merge has to reach two
    levels in without discarding whatever else lives under `pnpm`.
    """
    table = data
    for key in key_path[:-1]:
        nested = manifest.table_field(table, key)
        table[key] = nested
        table = nested
    table[key_path[-1]] = value


def _indent_of(text: str) -> int:
    """Read a JSON file's indentation so a merge does not reformat the whole file.

    Returns:
        The number of leading spaces on the first indented line; 2 if none.

    """
    match = re.search(r"\n(?P<indent> +)\S", text)
    return len(match.group("indent")) if match else 2


def _eslint_entrypoint() -> str:
    """Render the ESLint entrypoint, with the extension seam spelled out.

    The seam is the point. Consumers fork `eslint.strict.mjs` to add a framework
    exemption -- a router's `[slug].tsx`, a generated directory -- and once
    forked it stops receiving upstream rules; one measured copy had fallen 30
    rules behind while carrying 5 that no longer exist. Appending an override
    block does the same job and survives `sync --force`, but nothing said so.

    Returns:
        The file contents.

    """
    return """// Flat config entrypoint. `eslint.strict.mjs` next to this file is SYNCED --
// `sarj-lint-configs sync --force` overwrites it, and `sync --check` fails CI if
// you edit it. Put every repo-specific decision HERE instead, in the override
// block below: later entries win, so you can relax a rule, add a framework
// exemption, or scope one to a directory without forking the canonical file.
import strict from "./eslint.strict.mjs";

export default [
  ...strict,

  // --- repo-specific overrides -------------------------------------------
  // Example: your router generates bracketed filenames that unicorn rejects.
  //
  // {
  //   files: ["src/routes/**/*.tsx"],
  //   rules: {
  //     "unicorn/filename-case": ["error", {
  //       cases: { kebabCase: true },
  //       ignore: [String.raw`^\\[`],
  //     }],
  //   },
  // },
];
"""


def _plan_precommit(root: Path, plan: Plan, *, force: bool) -> None:
    path = root / _PRECOMMIT_CONFIG
    block = precommit_block(
        python=plan.ecosystems.python, version=manifest.adopted_version()
    )
    if path.is_file() and not force:
        if "sarj-lint-configs" in path.read_text(encoding="utf-8"):
            plan.skips.append((path, "already runs sarj-lint-configs"))
        else:
            plan.notes.append(f"add this to {_PRECOMMIT_CONFIG}:\n{block}")
        return
    _record(plan, path, f"repos:\n{block}", force=force, reason="exists")


def precommit_block(*, python: bool, version: str) -> str:
    """Render the pre-commit hooks, deliberately without a `rev:`.

    This is the whole "one version, not three" fix. The documented block used
    `repo: https://github.com/sarj-ai/standards` with `rev: python-v<x>`, which
    is a SECOND version string a human has to keep equal to the pyproject pin,
    expressed in a different namespace (`python-v0.36.0` for
    `sarj-lint-configs==0.27.0`). Nobody kept them equal.

    A `repo: local` hook has no `rev:`. It runs the CLI from the environment the
    pyproject pin already fixed, so upgrading is a single-line change and the
    two can no longer disagree -- there is nothing left to disagree with.

    The runner is chosen the same way `ci_snippet` chooses it, and for the same
    reason. This was a hardcoded constant, so a TypeScript-only repo got
    `entry: uv run --frozen sarj-lint-configs doctor` -- and `uv run` in a repo
    with no `pyproject.toml` is `error: Failed to spawn: sarj-lint-configs`,
    exit 2, on every commit. It also got the `check` hook, which runs the
    Python/SQL/IaC rules a TypeScript repo has nothing to feed.

    Returns:
        The `repos:` entry, indented for splicing into an existing file.

    """
    runner_prefix = (
        "uv run --frozen sarj-standards"
        if python
        else f"uvx --from sarj-lint-configs=={version} sarj-standards"
    )
    block = (
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: sarj-standards-drift\n"
        "        name: sarj standards -- config + version drift\n"
        f"        entry: {runner_prefix} doctor\n"
        "        language: system\n"
        "        pass_filenames: false\n"
    )
    return block + (
        "      - id: sarj-standards-check\n"
        "        name: sarj standards -- custom rules\n"
        f"        entry: {runner_prefix} check\n"
        "        language: system\n"
        "        files: '(?i)(\\.py|\\.sql|\\.tf|\\.tfvars|\\.hcl|\\.ya?ml|\\.toml|\\.jsonc|\\.mdx?|Dockerfile|Makefile)$'\n"
    )


def _record(plan: Plan, path: Path, contents: str, *, force: bool, reason: str) -> None:
    if path.exists() and not force:
        plan.skips.append((path, reason))
        return
    plan.writes.append((path, contents))


def apply(plan: Plan) -> None:
    """Carry out a plan's file writes and appends."""
    for path, contents in plan.writes:
        _ = path.write_text(contents, encoding="utf-8")
    for path, addition in plan.edits:
        with path.open("a", encoding="utf-8") as handle:
            _ = handle.write(addition)


def ci_snippet(plan: Plan, *, version: str) -> str:
    """Render the CI job that keeps a repo honest between upgrades.

    A TypeScript-only repo gets `uvx`, not `uv run --frozen`. Telling it to
    `uv run` would mean adding Python and a lockfile to a repo that has neither,
    just to obtain an ESLint config -- which is a fair description of why
    TypeScript repos copied the file instead of installing anything.

    Returns:
        A GitHub Actions step block.

    """
    runner_prefix = (
        "uv run --frozen sarj-standards"
        if plan.ecosystems.python
        else f"uvx --from sarj-lint-configs=={version} sarj-standards"
    )
    commands = ["doctor", "sync --check"]
    commands.append("check .")
    checks = "\n".join(f"          {runner_prefix} {command}" for command in commands)
    names = ", ".join(plan.configs)
    lines = [
        "      - name: sarj standards",
        "        run: |",
        checks,
        f"        # doctor: every version pin agrees. sync --check: {names} are unmodified.",
    ]
    lines.append("        # check: custom code, config, text, and artifact rules pass.")
    return "\n".join(lines) + "\n"
