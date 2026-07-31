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

from . import manifest


if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class Ecosystems:
    """What kind of repo this is, decided by files that are already there."""

    python: bool
    typescript: bool

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


def detect(root: Path) -> Ecosystems:
    """Decide which ecosystems a repo contains.

    A repo counts as TypeScript when it has a `package.json` anywhere outside
    `node_modules`, because the sub-project case is the common one: one repo we
    measured ships the strict config at its root while only a fraction of its
    sub-projects wire it in, and a root-only check would call that repo done.

    Returns:
        The detected ecosystems.

    """
    return Ecosystems(
        python=(root / "pyproject.toml").is_file(),
        typescript=_has_package_json(root),
    )


def _has_package_json(root: Path) -> bool:
    if (root / "package.json").is_file():
        return True
    return any(
        "node_modules" not in path.relative_to(root).parts
        for path in root.rglob("package.json")
    )


def build_plan(root: Path, *, force: bool, configs: Sequence[str] | None = None) -> Plan:
    """Work out every file `init` would create or amend.

    Returns:
        The plan, whose `writes`/`edits`/`skips` are the whole effect.

    """
    ecosystems = detect(root)
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
    if ecosystems.python:
        _plan_python(root, plan, force=force)
    if ecosystems.typescript:
        _plan_typescript(root, plan, force=force)
    _plan_precommit(root, plan, force=force)
    return plan


def _plan_manifest(root: Path, plan: Plan, *, force: bool) -> None:
    path = manifest.manifest_path(root)
    contents = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=plan.configs,
        python_dest=".",
        typescript_dest=".",
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
    _plan_npm_overrides(root, plan)
    plan.notes.append(f"install the tested ESLint peer set:\n    {manifest.eslint_install_command()}")


def _plan_npm_overrides(root: Path, plan: Plan) -> None:
    """Write the `overrides` without which `npm install` cannot resolve the peers.

    This used to only PRINT the block, while the README and `eslint.peers.json`
    both said `init` writes it. So the documented one-command adoption path ended
    at `npm error code ERESOLVE` for every TypeScript consumer: the shipped config
    needs ESLint 10 (its unicorn floor pulls `>= 10.4`) and the newest published
    `eslint-plugin-react` peers `eslint <= ^9.7`. This repo only installs because
    `packages/typescript/package.json` carries the same `overrides` privately --
    a workaround present in nothing shipped.

    The file is merged rather than templated because `package.json` is the
    consumer's and may already carry overrides of its own: existing keys are
    preserved and only the ESLint peer entries are added or corrected.
    """
    overrides = manifest.eslint_overrides()
    if not overrides:
        return
    package_json = root / "package.json"
    if not package_json.is_file():
        plan.notes.append(
            "no package.json at the repo root, so the npm `overrides` could not be"
            " merged. npm cannot resolve the peer set without it -- add it by hand"
            f" to whichever package.json installs ESLint:\n"
            f"{textwrap.indent(json.dumps({'overrides': overrides}, indent=2), '    ')}"
        )
        return
    try:
        merged = _merged_npm_overrides(
            package_json.read_text(encoding="utf-8"), overrides
        )
    except (TypeError, ValueError):
        plan.notes.append(
            "package.json could not be parsed, so the npm `overrides` were not"
            " merged. npm cannot resolve the peer set without them -- add by hand:\n"
            f"{textwrap.indent(json.dumps({'overrides': overrides}, indent=2), '    ')}"
        )
        return
    if merged is None:
        plan.skips.append((package_json, "already carries the ESLint peer overrides"))
        return
    plan.writes.append((package_json, merged))
    plan.notes.append(
        "merged the npm `overrides` into package.json:\n"
        f"{textwrap.indent(json.dumps({'overrides': overrides}, indent=2), '    ')}\n"
        "    npm exits ERESOLVE without it -- eslint-plugin-react peers"
        " eslint <=9.7 and the unicorn floor needs >=10.4."
    )


def _merged_npm_overrides(text: str, overrides: dict[str, object]) -> str | None:
    """Merge the ESLint peer `overrides` into a package.json's text.

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
    existing = manifest.table_field(data, "overrides")
    updated = dict(existing)
    for name, value in overrides.items():
        # A consumer may already override the same package for a different
        # reason, so merge the inner table rather than replacing it.
        current_entry = manifest.table_field(updated, name)
        new_entry = manifest.as_table(value)
        updated[name] = {**current_entry, **new_entry} if new_entry else value
    if updated == existing and "overrides" in data:
        return None
    data["overrides"] = updated
    rendered = json.dumps(data, indent=_indent_of(text))
    return rendered + "\n" if text.endswith("\n") else rendered


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
    expressed in a different namespace (`python-v0.34.0` for
    `sarj-lint-configs==0.22.0`). Nobody kept them equal.

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
        "uv run --frozen sarj-lint-configs"
        if python
        else f"uvx --from sarj-lint-configs=={version} sarj-lint-configs"
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
    if not python:
        return block
    return block + (
        "      - id: sarj-standards-check\n"
        "        name: sarj standards -- custom rules\n"
        f"        entry: {runner_prefix} check\n"
        "        language: system\n"
        "        types_or: [python, sql, yaml]\n"
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
        "uv run --frozen sarj-lint-configs"
        if plan.ecosystems.python
        else f"uvx --from sarj-lint-configs=={version} sarj-lint-configs"
    )
    commands = ["doctor", "sync --check"]
    if plan.ecosystems.python:
        commands.append("check .")
    checks = "\n".join(f"          {runner_prefix} {command}" for command in commands)
    names = ", ".join(plan.configs)
    lines = [
        "      - name: sarj standards",
        "        run: |",
        checks,
        f"        # doctor: every version pin agrees. sync --check: {names} are unmodified.",
    ]
    if plan.ecosystems.python:
        lines.append("        # check: the custom Python/SQL/IaC rules pass.")
    return "\n".join(lines) + "\n"
