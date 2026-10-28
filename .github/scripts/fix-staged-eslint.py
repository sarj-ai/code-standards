#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- catch failures from the shared fixed-argv TypeScript builder.
import sys
from typing import TYPE_CHECKING

import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption import lifecycle, manifest, packagemanager, transaction
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting import runner
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.repository import rule_catalog_artifact


if TYPE_CHECKING:
    from collections.abc import Sequence


_ESLINT_SUFFIXES = frozenset({".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx"})
_CUSTOM_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts", ".mjs"})
_EXECUTION_ERROR = 2


@dataclass(frozen=True, slots=True)
class _Postimages:
    changed: bool
    issues: tuple[str, ...]


def main() -> int:
    try:
        return fix_staged(Path.cwd().resolve())
    except (OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"error: cannot apply authored ESLint fixes: {exc}\n")
        return 2


def fix_staged(root: Path) -> int:
    policy = Policy.from_manifest(root, manifest.load(root))
    selected = _selected_sources(root, policy)
    if not selected:
        return 0
    custom = _dogfood_sources(root, selected)
    ownership = lifecycle.select_eslint_commands(root, selected, include_config_sources=True)
    if ownership.unowned_count or not ownership.commands:
        msg = "a selected source has no owning authored ESLint project"
        raise ValueError(msg)
    paths = tuple(Path(name) for name in selected)
    transaction.validate_targets(root, paths)
    preimages = {path: path.read_bytes() for path in paths}
    status = 0
    try:
        native = lifecycle.eslint_fix_commands(root, selected, policy, include_config_sources=True)
        if _requires_local_plugin(root, native):
            rule_catalog_artifact.build_typescript(root)
        status = _execute(_local_commands(root, native))
        if status != _EXECUTION_ERROR and custom:
            rule_catalog_artifact.build_typescript(root)
            status = max(status, _execute(_local_commands(root, _custom_commands(root, custom, policy))))
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
    # input must stop this hook before either an ESLint write or a build.
    staged = cli.staged_fix_paths(root, ())
    return tuple(
        name
        for name in policy.filter_paths(staged)
        if Path(name).suffix.lower() in _ESLINT_SUFFIXES and runner.accepts_hook_path(Path(name), root=root)
    )


def _dogfood_sources(root: Path, selected: Sequence[str]) -> tuple[str, ...]:
    package = root / "packages" / "typescript"
    document = manifest.as_table(parse_json((package / "package.json").read_text(encoding="utf-8")))
    script = manifest.table_field(document, "scripts").get("dogfood:built")
    if not isinstance(script, str):
        msg = "the authored TypeScript dogfood command is missing"
        raise TypeError(msg)
    words = shlex.split(script)
    end = words.index("&&") if "&&" in words else len(words)
    arguments = words[3:end]
    if words[:3] != ["eslint", "--config", "eslint.dogfood.config.ts"] or arguments[-2:] != [
        "--max-warnings",
        "0",
    ]:
        msg = "the authored TypeScript dogfood command has an unsupported shape"
        raise ValueError(msg)
    targets = tuple(package / name for name in arguments[:-2])
    if not targets or any(
        not target.is_relative_to(package) or ".." in target.parts or target.name.startswith("-") for target in targets
    ):
        msg = "the authored TypeScript dogfood scope is invalid"
        raise ValueError(msg)
    return tuple(
        name
        for name in selected
        if Path(name).suffix.lower() in _CUSTOM_SUFFIXES
        and any(Path(name) == target or (target.is_dir() and Path(name).is_relative_to(target)) for target in targets)
    )


def _requires_local_plugin(root: Path, commands: Sequence[lifecycle.Command]) -> bool:
    package = (root / "packages/typescript").resolve()
    for command in commands:
        filename = command.cwd / "package.json"
        if not filename.is_file():
            continue
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


def _custom_commands(root: Path, selected: Sequence[str], policy: Policy) -> tuple[lifecycle.Command, ...]:
    package = root / "packages" / "typescript"
    custom = rule_catalog_artifact.selector_index().canonical
    grouped: dict[frozenset[str], list[str]] = {}
    for name in selected:
        disabled = frozenset(
            f"@sarj/{rule}" if f"eslint:{rule}" in custom else rule for rule in policy.excluded_rule_ids(name, "eslint")
        )
        grouped.setdefault(disabled, []).append(Path(name).relative_to(package).as_posix())
    client = packagemanager.detect(packagemanager.workspace_root(package, root))
    return tuple(
        lifecycle.Command(
            "Authored TypeScript custom fixes",
            packagemanager.exec_argv(
                client,
                "eslint",
                "--config",
                "eslint.dogfood.config.ts",
                "--fix",
                "--max-warnings",
                "0",
                *(argument for rule in sorted(disabled) for argument in ("--rule", f"{rule}:off")),
                "--",
                *sorted(names),
            ),
            package,
        )
        for disabled, names in sorted(grouped.items(), key=lambda item: sorted(item[0]))
    )


def _local_commands(root: Path, commands: Sequence[lifecycle.Command]) -> tuple[lifecycle.Command, ...]:
    node = shutil.which("node")
    entry = root / "packages/typescript/node_modules/eslint/bin/eslint.js"
    if node is None or not entry.is_file():
        msg = "the source repository's installed Node.js and ESLint are required"
        raise RuntimeError(msg)
    return tuple(
        lifecycle.Command(
            command.label,
            (node, str(entry), "--no-warn-ignored", *command.argv[command.argv.index("eslint") + 1 :]),
            command.cwd,
        )
        for command in commands
    )


def _execute(commands: Sequence[lifecycle.Command]) -> int:
    status = 0
    for command in commands:
        result = lifecycle.execute((command,))
        if result not in {0, 1}:
            return 2
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
            issues.append(f"cannot verify the authored ESLint source postimage {path}: {exc}")
        else:
            changed |= current != original
    return _Postimages(changed, tuple(issues))


if __name__ == "__main__":
    raise SystemExit(main())
