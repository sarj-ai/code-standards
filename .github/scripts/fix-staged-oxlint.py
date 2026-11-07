#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- catch failures from the shared fixed-argv TypeScript builder.
import sys
from typing import TYPE_CHECKING

import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption import lifecycle, manifest, transaction
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting import oxlint, runner
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.repository import rule_catalog_artifact


if TYPE_CHECKING:
    from collections.abc import Sequence


_PACKAGE = Path("packages/typescript")
_EXECUTION_ERROR = 2


@dataclass(frozen=True, slots=True)
class _Postimages:
    changed: bool
    issues: tuple[str, ...]


def main() -> int:
    try:
        return fix_staged(Path.cwd().resolve())
    except (OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"error: cannot apply authored Oxlint fixes: {exc}\n")
        return 2


def fix_staged(root: Path) -> int:
    policy = Policy.from_manifest(root, manifest.load(root))
    selected = _selected_sources(root, policy)
    if not selected:
        return 0
    ownership = oxlint.select_oxlint_commands(root, selected, fix=True, include_config_sources=True)
    if ownership.unowned_count or not ownership.commands:
        msg = "a selected source has no owning authored Oxlint project"
        raise ValueError(msg)
    paths = tuple(Path(name) for name in selected)
    transaction.validate_targets(root, paths)
    preimages = {path: path.read_bytes() for path in paths}
    status = 0
    try:
        commands = _fix_commands(root, ownership.commands, policy)
        if any(_loads_local_plugin(root, command) for command in commands):
            rule_catalog_artifact.build_typescript(root)
        status = _execute(commands)
    finally:
        postimages = _postimages(root, preimages)
        if postimages.changed:
            sys.stderr.write("Safe fixes applied. Review and stage the changes, then retry the commit.\n")
            status = max(status, 1)
        for issue in postimages.issues:
            sys.stderr.write(f"error: {issue}\n")
        if postimages.issues:
            status = 2
    return status


def _selected_sources(root: Path, policy: Policy) -> tuple[str, ...]:
    # Verify every staged path before selecting TypeScript: a partial Python
    # input must stop this hook before either an Oxlint write or a build.
    staged = cli.staged_fix_paths(root, ())
    return tuple(
        name
        for name in policy.filter_paths(staged)
        if oxlint.is_oxlint_source(Path(name), include_config_sources=True)
        and runner.accepts_hook_path(Path(name), root=root)
    )


def _loads_local_plugin(root: Path, command: lifecycle.Command) -> bool:
    # This package's own config loads the built plugin, as does any project
    # that depends on it through a `file:` specifier.
    package = (root / _PACKAGE).resolve()
    if command.cwd.resolve() == package:
        return True
    filename = command.cwd / "package.json"
    if not filename.is_file():
        return False
    document = manifest.as_table(parse_json(filename.read_text(encoding="utf-8")))
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        dependency = manifest.table_field(document, section).get("@sarj/eslint-plugin")
        if (
            isinstance(dependency, str)
            and dependency.startswith("file:")
            and (command.cwd / dependency[5:]).resolve() == package
        ):
            return True
    return False


def _fix_commands(root: Path, commands: Sequence[lifecycle.Command], policy: Policy) -> tuple[lifecycle.Command, ...]:
    local: list[lifecycle.Command] = []
    for command in commands:
        argv = command.argv[next(i for i, value in enumerate(command.argv) if Path(value).name == "oxlint") + 1 :]
        binary = oxlint.local_binary("oxlint", command.cwd, root)
        if binary is None:
            msg = "the source repository's installed Oxlint is required"
            raise RuntimeError(msg)
        local.append(
            lifecycle.Command(
                command.label,
                (str(binary), *argv),
                command.cwd,
                tuple(oxlint.oxlint_environment(command.cwd, root).items()),
                prepare=partial(oxlint.selected_config, request=lifecycle.oxlint_exclusions(command, policy)),
            )
        )
    return tuple(local)


def _execute(commands: Sequence[lifecycle.Command]) -> int:
    status = 0
    for command in commands:
        result = lifecycle.execute((command,))
        if result not in {0, 1}:
            return _EXECUTION_ERROR
        status = max(status, result)
    return status


def _postimages(root: Path, preimages: dict[Path, bytes]) -> _Postimages:
    changed = False
    issues: list[str] = []
    for path, original in preimages.items():
        try:
            transaction.validate_targets(root, (path,))
            current = path.read_bytes()
        except OSError as exc:
            changed = True
            issues.append(f"cannot verify the authored Oxlint source postimage {path}: {exc}")
        else:
            changed |= current != original
    return _Postimages(changed, tuple(issues))


if __name__ == "__main__":
    raise SystemExit(main())
