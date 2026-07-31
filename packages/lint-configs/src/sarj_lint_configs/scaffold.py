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
    """Add the `overrides` without which `npm install` cannot resolve the peers.

    This is edited rather than templated because `package.json` is the consumer's
    file and may already carry overrides of its own. Merging one key is safe;
    rewriting the file is not.
    """
    overrides = manifest.eslint_overrides()
    if not overrides:
        return
    package_json = root / "package.json"
    if not package_json.is_file():
        return
    text = package_json.read_text(encoding="utf-8")
    missing = [name for name in overrides if f'"{name}"' not in text]
    if not missing:
        plan.skips.append((package_json, "already carries the ESLint peer overrides"))
        return
    rendered = json.dumps({"overrides": overrides}, indent=2)
    plan.notes.append(
        "npm cannot resolve the peer set without this. Merge it into package.json:\n"
        f"{textwrap.indent(rendered, '    ')}\n"
        "    (eslint-plugin-react peers eslint <=9.7; the unicorn floor needs >=10.4)"
    )


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
    block = precommit_block()
    if path.is_file() and not force:
        if "sarj-lint-configs" in path.read_text(encoding="utf-8"):
            plan.skips.append((path, "already runs sarj-lint-configs"))
        else:
            plan.notes.append(f"add this to {_PRECOMMIT_CONFIG}:\n{block}")
        return
    _record(plan, path, f"repos:\n{block}", force=force, reason="exists")


def precommit_block() -> str:
    """Render the pre-commit hooks, deliberately without a `rev:`.

    This is the whole "one version, not three" fix. The documented block used
    `repo: https://github.com/sarj-ai/standards` with `rev: python-v<x>`, which
    is a SECOND version string a human has to keep equal to the pyproject pin,
    expressed in a different namespace (`python-v0.33.0` for
    `sarj-lint-configs==0.16.0`). Nobody kept them equal.

    A `repo: local` hook has no `rev:`. It runs the CLI from the environment the
    pyproject pin already fixed, so upgrading is a single-line change and the
    two can no longer disagree -- there is nothing left to disagree with.

    Returns:
        The `repos:` entry, indented for splicing into an existing file.

    """
    return (
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: sarj-standards-drift\n"
        "        name: sarj standards -- config + version drift\n"
        "        entry: uv run --frozen sarj-lint-configs doctor\n"
        "        language: system\n"
        "        pass_filenames: false\n"
        "      - id: sarj-standards-check\n"
        "        name: sarj standards -- custom rules\n"
        "        entry: uv run --frozen sarj-lint-configs check\n"
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
