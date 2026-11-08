from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
import json
from pathlib import Path
import re
import shlex
from typing import TYPE_CHECKING, Final

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.rules import oxlint_ids

from . import eslint_config, manifest, retired_suppressions, tsconfigs
from .configs import (
    LEGACY_ESLINT_CONFIG_NAMES,
    LEGACY_ESLINT_PRESET_NAMES,
    LEGACY_ESLINT_SUPPRESSIONS,
    OXLINT_CONFIG_NAMES,
    OXLINT_ENTRYPOINT,
    OXLINT_SUPPRESSIONS,
    TYPESCRIPT_SOURCE_SUFFIXES,
)


if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Mapping, Sequence

    from pydantic import JsonValue


_ENTRYPOINT_HEADER: Final = """// Repository-owned Oxlint entrypoint. `oxlint.strict.mts` next to this file is SYNCED:
// `code-standards update` overwrites it. Put every repository-specific decision here.
// Later overrides win, so you can relax a rule, add a framework exemption, or scope one
// to a directory without forking the managed policy.
import { defineConfig } from "oxlint";

import { createConfig, ignorePatterns } from "./oxlint.strict.mts";

// Bun, Testing Library and Playwright are opt-in because their global test syntax overlaps
// other runners. To enable them, pass options to createConfig:
//   createConfig({
//     testFrameworks: ["vitest", "bun", "node", "testing-library", "playwright"],
//     playwrightTestFiles: ["tests/browser/**/*.spec.ts"],
//   })
"""
_EXAMPLE_OVERRIDE: Final = """    // Example: your router generates bracketed filenames that unicorn rejects.
    //
    // {
    //   files: ["src/routes/**/*.tsx"],
    //   rules: {
    //     "unicorn/filename-case": ["error", { cases: { kebabCase: true }, ignore: [String.raw`^\\[`] }],
    //   },
    // },
"""
_ESLINT_TSCONFIG: Final = "tsconfig.eslint.json"
#: Sources whose imports keep an ESLint-era package in use.
_IMPORTING_SUFFIXES: Final = frozenset({*TYPESCRIPT_SOURCE_SUFFIXES, ".astro", ".mdx", ".svelte", ".vue"})
#: ESLint-era packages Standards pinned (eslint.peers.json); the ones the TypeScript peers keep are excluded.
_LEGACY_PEERS: Final = frozenset(
    {
        "@eslint-community/eslint-plugin-eslint-comments",
        "@eslint/compat",
        "@eslint-react/eslint-plugin",
        "@tanstack/eslint-plugin-query",
        "@biomejs/biome",
        "prettier",
        "react-doctor",
        "eslint-plugin-react-you-might-not-need-an-effect",
        "@eslint/js",
        "@shadcn/lint",
        "@types/eslint-plugin-no-unsanitized",
        "@typescript-eslint/eslint-plugin",
        "@typescript-eslint/parser",
        "@typescript-eslint/project-service",
        "@typescript-eslint/scope-manager",
        "@typescript-eslint/tsconfig-utils",
        "@typescript-eslint/type-utils",
        "@typescript-eslint/types",
        "@typescript-eslint/typescript-estree",
        "@typescript-eslint/utils",
        "@typescript-eslint/visitor-keys",
        "@typescript/native",
        "@vitest/eslint-plugin",
        "eslint",
        "eslint-config-next",
        "eslint-config-expo",
        "eslint-config-prettier",
        "eslint-node-test",
        "eslint-plugin-better-tailwindcss",
        "eslint-plugin-jest",
        "eslint-plugin-jsdoc",
        "eslint-plugin-n",
        "eslint-plugin-no-unsanitized",
        "eslint-plugin-perfectionist",
        "eslint-plugin-playwright",
        "eslint-plugin-promise",
        "eslint-plugin-react",
        "eslint-plugin-react-hooks",
        "eslint-plugin-regexp",
        "eslint-plugin-security",
        "eslint-plugin-simple-import-sort",
        "eslint-plugin-testing-library",
        "eslint-plugin-unicorn",
        "eslint-plugin-zod",
        "jiti",
        "typescript-eslint",
        "zod",
    }
)
_HOOK_AND_CI_NAMES: Final = frozenset({".lefthook.yml", ".pre-commit-config.yaml", "Makefile", "lefthook.yml"})
_PACKAGE_BINARIES: Final[Mapping[str, str]] = {"@typescript/native": "tsc", "eslint": "eslint", "jiti": "jiti"}
_SPECIFIER: Final = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|^\s*import\s+)["'](?P<spec>[^"'\s]+)["']""", re.MULTILINE
)
_SHELL_OPERATOR: Final = re.compile(r"[;&|<>`$()]")
_WARNING_BUDGET: Final = re.compile(r"(?:^|\s)--max-warnings(?:=|\s+)\d+(?=\s|$)")
_RUNNER: Final = re.compile(r"^\s*(?:(?:npx|bunx)\s+|(?:pnpm|npm|yarn|bun)\s+(?:exec|run)\s+)?")
#: The formatter flag a `format` script runs with -> the oxfmt command doing the same.
_FORMATTER_MODES: Final[Mapping[tuple[str, ...], str]] = {
    ("prettier", "--write"): "oxfmt",
    ("prettier", "-w"): "oxfmt",
    ("prettier", "--check"): "oxfmt --check",
    ("prettier", "-c"): "oxfmt --check",
    ("biome", "format", "--write"): "oxfmt",
    ("biome", "format"): "oxfmt --check",
}
_TYPE_CHECK: Final = re.compile(
    r"(?P<prefix>^|[\s;&|(])(?P<binary>(?:node\s+)?(?:[^\s;&|()]*/)?tsc6?)(?=\s|$)(?P<arguments>[^;&|()]*)"
)
_NO_EMIT: Final = re.compile(r"(?:^|\s)--noEmit(?:\s|$)")


@dataclass(frozen=True, slots=True)
class Migration:
    writes: tuple[tuple[Path, str], ...] = ()
    deletes: tuple[Path, ...] = ()
    notes: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    #: ESLint-era packages Standards added that nothing in the repository uses any more.
    retired_dependencies: frozenset[str] = field(default_factory=frozenset)
    #: Whether a repository-owned ESLint config stays because it could not be translated.
    keeps_eslint: bool = False


def render_entrypoint(
    *,
    options: JsonValue | None = None,
    ignore_patterns: Sequence[str] = (),
    overrides: Sequence[JsonValue] = (),
) -> str:
    arguments = "" if options is None else _literal(options, indent=2)
    ignores = "".join(f",\n    {json.dumps(pattern, ensure_ascii=False)}" for pattern in ignore_patterns)
    rendered = "".join(f"    {_literal(override, indent=4)},\n" for override in overrides)
    return (
        f"{_ENTRYPOINT_HEADER}\n"
        f"const managed = createConfig({arguments});\n\n"
        "export default defineConfig({\n"
        "  extends: [managed],\n"
        "  // Oxlint reads `settings` only from this root config.\n"
        "  settings: managed.settings,\n"
        f"  ignorePatterns: [\n    ...ignorePatterns{ignores},\n  ],\n"
        f"  overrides: [\n{rendered or _EXAMPLE_OVERRIDE}  ],\n"
        "});\n"
    )


def plan(root: Path, typescript_root: Path, files: Sequence[Path]) -> Migration:
    sources = tuple(path for path in files if path.is_relative_to(typescript_root))
    changes = _Changes()
    keeps_eslint = _plan_entrypoint(typescript_root, sources, changes)
    if changes.errors:
        return Migration(errors=tuple(changes.errors))
    kept = [
        path for path in sources if path.suffix.lower() in TYPESCRIPT_SOURCE_SUFFIXES and path not in changes.deletes
    ]
    _plan_presets(typescript_root, kept, changes)
    for directory in dict.fromkeys((typescript_root, root)):
        _plan_suppressions(directory, changes, keeps_eslint=keeps_eslint)
    _plan_directives(kept, changes)
    _plan_tsconfig_references(typescript_root, sources, changes)
    _plan_workspace_type_checks(typescript_root, sources, changes)
    _validate_retired_commands(typescript_root, sources, changes)
    if changes.errors:
        return Migration(errors=tuple(changes.errors))
    retired = _retired_dependencies(sources, changes.deletes, replace_eslint=not keeps_eslint)
    if not keeps_eslint and changes.deletes:
        _note_eslint_invocations(typescript_root, sources, changes)
    return Migration(
        tuple(changes.writes),
        tuple(changes.deletes),
        tuple(changes.notes),
        retired_dependencies=retired,
        keeps_eslint=keeps_eslint,
    )


def _validate_retired_commands(typescript_root: Path, sources: Sequence[Path], changes: _Changes) -> None:
    for source in sources:
        if source.name != "package.json" and (
            source.name in _HOOK_AND_CI_NAMES or source.suffix == ".sh" or ".github" in source.parts
        ):
            command = source.read_text(encoding="utf-8", errors="replace")
            if any(_invokes(binary, command) for binary in ("eslint", "prettier", "biome")):
                changes.errors.append(
                    f"{_relative(source, typescript_root)} invokes retired tooling; use code-standards check/fix before update"
                )
        if source.name == "package.json":
            _validate_package_commands(typescript_root, source, changes)


def _validate_package_commands(root: Path, source: Path, changes: _Changes) -> None:
    for name, command in _scripts(source).items():
        migrated = _migrated_script(command, lint="oxlint", replace_eslint=True)
        if not isinstance(migrated, str):
            continue
        if any(_invokes(binary, migrated) for binary in ("eslint", "prettier", "biome")):
            changes.errors.append(
                f"{_relative(source, root)} script {name}: port unsupported command `{command}` to code-standards before update"
            )


def migrated_scripts(scripts: Mapping[str, JsonValue], *, lint: str, replace_eslint: bool) -> dict[str, JsonValue]:
    updated = {
        name: _migrated_script(command, lint=lint, replace_eslint=replace_eslint) for name, command in scripts.items()
    }
    updated.setdefault("lint", lint)
    updated.setdefault("format", "oxfmt")
    updated.setdefault("format:check", "oxfmt --check")
    return updated


@dataclass
class _Changes:
    writes: list[tuple[Path, str]] = field(default_factory=list)
    deletes: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _plan_entrypoint(typescript_root: Path, sources: Sequence[Path], changes: _Changes) -> bool:
    # Returns whether an ESLint config stays in the repository.
    configs = [typescript_root / name for name in LEGACY_ESLINT_CONFIG_NAMES if (typescript_root / name).is_file()]
    if len(configs) > 1:
        names = ", ".join(path.name for path in configs)
        changes.errors.append(
            f"multiple ESLint flat configs in {typescript_root}: {names}; keep one before running update"
        )
        return True
    nested = [path for path in sources if path.name in LEGACY_ESLINT_CONFIG_NAMES and path.parent != typescript_root]
    keeps_root = _plan_root_config(typescript_root, configs[0] if configs else None, changes)
    aliases = [path for path in nested if _reexports_deleted_config(path, changes)]
    changes.deletes.extend(aliases)
    nested = [path for path in nested if path not in aliases]
    changes.errors.extend(
        f"kept nested ESLint config {path.relative_to(typescript_root).as_posix()}: Oxlint does not read it; "
        f"port its overrides into {OXLINT_ENTRYPOINT} and delete it"
        for path in nested
    )
    return keeps_root or bool(nested)


def _reexports_deleted_config(path: Path, changes: _Changes) -> bool:
    match = re.fullmatch(
        r"""\s*export\s*\{\s*default\s*\}\s*from\s*(["'])(\.[^"']+)\1\s*;?\s*""",
        path.read_text(encoding="utf-8"),
    )
    return match is not None and (path.parent / match.group(2)).resolve() in changes.deletes


def _plan_root_config(typescript_root: Path, config: Path | None, changes: _Changes) -> bool:
    # Writes the Oxlint entrypoint, translated from `config` when it can be; returns whether `config` stays.
    if any((typescript_root / name).is_file() for name in OXLINT_CONFIG_NAMES):
        if config is not None:
            changes.errors.append(_kept_note(config, "Oxlint already exists; merge these overrides before update"))
        return config is not None
    target = typescript_root / OXLINT_ENTRYPOINT
    if config is None:
        changes.writes.append((target, render_entrypoint()))
        return False
    try:
        translation = eslint_config.translate(config.read_text(encoding="utf-8"))
    except eslint_config.UntranslatableError as exc:
        changes.errors.append(_kept_note(config, f"it is not a static Standards config: {exc}"))
        return True
    rendered = render_entrypoint(
        options=translation.options, ignore_patterns=translation.ignore_patterns, overrides=translation.overrides
    )
    changes.writes.append((target, rendered))
    changes.deletes.append(config)
    changes.notes.append(f"translated {config.name} into {OXLINT_ENTRYPOINT}")
    changes.notes.extend(f"{OXLINT_ENTRYPOINT}: {note}" for note in translation.notes)
    return False


def _kept_note(config: Path, reason: str) -> str:
    return (
        f"kept {config.name}: {reason}. Standards now lints with {OXLINT_ENTRYPOINT}; port the repository "
        f"overrides into it and delete {config.name} and the eslint.strict.* files it imports"
    )


def _plan_presets(typescript_root: Path, kept: Sequence[Path], changes: _Changes) -> None:
    candidates = [typescript_root / name for name in LEGACY_ESLINT_PRESET_NAMES]
    presets = [preset for preset in candidates if preset.is_file()]
    if not presets:
        return
    importers: dict[Path, list[str]] = {}
    for path in kept:
        if path in candidates:
            continue
        for target in _local_imports(path):
            importers.setdefault(target, []).append(_relative(path, typescript_root))
    for preset in presets:
        # The declaration describes eslint.strict.mjs and goes with it.
        imported = preset.with_name("eslint.strict.mjs") if preset.name == "eslint.strict.d.mts" else preset
        if users := importers.get(imported):
            changes.notes.append(f"kept {preset.name}: {', '.join(users)} imports it")
        else:
            changes.deletes.append(preset)


def _local_imports(path: Path) -> frozenset[Path]:
    text = path.read_text(encoding="utf-8", errors="replace")
    found: set[Path] = set()
    for match in _SPECIFIER.finditer(text):
        specifier = match.group("spec")
        if not specifier.startswith("."):
            continue
        target = tsconfigs.normalized(path.parent / specifier)
        found.add(target)
        found.update(target.with_name(target.name + suffix) for suffix in (".mjs", ".ts", ".js"))
        if target.suffix == ".js":
            found.update(target.with_suffix(suffix) for suffix in (".ts", ".mjs"))
    return frozenset(found)


def _plan_suppressions(directory: Path, changes: _Changes, *, keeps_eslint: bool) -> None:
    source = directory / LEGACY_ESLINT_SUPPRESSIONS
    target = directory / OXLINT_SUPPRESSIONS
    if not source.is_file() or (keeps_eslint and target.is_file()):
        return
    try:
        document = _suppressions(source)
        existing = _suppressions(target) if target.is_file() else {}
    except (TypeError, ValueError) as exc:
        changes.errors.append(f"cannot convert {source}: {exc}")
        return
    converted: dict[str, dict[str, dict[str, int]]] = {
        file: {rule: {"count": count} for rule, count in rules.items()} for file, rules in existing.items()
    }
    rule_map = oxlint_ids.bundled()
    for file, rules in document.items():
        targets = dict(converted.get(file, {}))
        for rule, count in rules.items():
            for key in map(_suppression_key, rule_map.rule_ids(rule)):
                # Summing is an upper bound; pruning after install trims it to what Oxlint reports.
                targets[key] = {"count": targets.get(key, {"count": 0})["count"] + count}
        if targets:
            converted[file] = targets
    changes.writes.append((target, json.dumps(converted, ensure_ascii=False, indent=2) + "\n"))
    if not keeps_eslint:
        changes.deletes.append(source)
    changes.notes.append(f"converted {source.name} into {target.name}")


def _suppression_key(rule_id: str) -> str:
    # Oxlint keys bulk suppressions by the namespace it reports, not the config one.
    from sarj_standards.libs.linting import oxlint  # ruff: ignore[import-outside-top-level] -- oxlint imports adoption.lifecycle.

    return oxlint.reported_rule_id(rule_id)


def _suppressions(path: Path) -> dict[str, dict[str, int]]:
    document = parse_json(path.read_text(encoding="utf-8").removeprefix("\ufeff"))
    if not isinstance(document, dict):
        msg = "expected an object of files"
        raise TypeError(msg)
    parsed: dict[str, dict[str, int]] = {}
    for file, rules in document.items():
        if not isinstance(rules, dict):
            msg = f"{file} must map rule IDs to counts"
            raise TypeError(msg)
        counts: dict[str, int] = {}
        for rule, entry in rules.items():
            count = entry.get("count") if isinstance(entry, dict) else None
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                msg = f"{file} {rule} needs a non-negative integer count"
                raise ValueError(msg)
            counts[rule] = count
        parsed[file] = counts
    return parsed


def _plan_directives(kept: Sequence[Path], changes: _Changes) -> None:
    targets = {**_renamed_rules(), **retired_suppressions.retired_lint_targets()}
    # These proven aliases already suppress the same native rules; retain source identity.
    targets.pop("@typescript-eslint/no-deprecated", None)
    targets.pop("@typescript-eslint/no-unnecessary-type-parameters", None)
    targets.pop("@typescript-eslint/no-unnecessary-condition", None)
    targets.pop("@typescript-eslint/strict-void-return", None)
    for path in kept:
        try:
            text = path.read_bytes().decode("utf-8")
        except OSError, UnicodeDecodeError:
            continue
        rewritten = retired_suppressions.rewrite_directives(path, text, targets)
        if rewritten != text:
            changes.writes.append((path, rewritten))


@cache
def _renamed_rules() -> dict[str, tuple[str, ...]]:
    return {rule: targets for rule, targets in oxlint_ids.bundled().oxlint_ids.items() if targets != (rule,)}


def _plan_tsconfig_references(typescript_root: Path, sources: Sequence[Path], changes: _Changes) -> None:
    documents = tsconfigs.read(sources)
    additions: dict[Path, list[Path]] = {}
    for path in tsconfigs.unreferenced_projects(documents):
        owner = path.parent / tsconfigs.TSCONFIG_JSON
        if path.name == _ESLINT_TSCONFIG:
            changes.notes.append(f"{_relative(path, typescript_root)} only served ESLint's typed rules; delete it")
        elif owner in documents and tsconfigs.can_reference(documents[owner], documents[path]):
            additions.setdefault(owner, []).append(path)
        else:
            changes.notes.append(_reference_by_hand(typescript_root, owner, [path]))
    for owner, projects in sorted(additions.items()):
        updated = _with_references(owner, [f"./{project.name}" for project in sorted(projects)])
        if updated is None:
            changes.notes.append(_reference_by_hand(typescript_root, owner, projects))
            continue
        listed = ", ".join(_relative(project, typescript_root) for project in sorted(projects))
        changes.writes.append((owner, updated))
        changes.notes.append(f"referenced {listed} from {_relative(owner, typescript_root)} so Oxlint type-checks it")


def _reference_by_hand(typescript_root: Path, owner: Path, projects: Sequence[Path]) -> str:
    listed = ", ".join(_relative(project, typescript_root) for project in sorted(projects))
    return (
        f"Oxlint type-checks only tsconfig.json projects and their references; reference {listed} from "
        f"{_relative(owner, typescript_root)} so its files are type-checked ({tsconfigs.REFERENCE_RULE})"
    )


def _with_references(owner: Path, names: Sequence[str]) -> str | None:
    text = owner.read_text(encoding="utf-8")
    try:
        document = parse_json(text)
    except ValueError:
        document = None
    if isinstance(document, dict):
        references = document.get("references", [])
        if not isinstance(references, list):
            return None
        document["references"] = [*references, *({"path": name} for name in names)]
        indent = re.search(r"\n(?P<indent>[ \t]+)\S", text)
        rendered = json.dumps(document, indent=indent.group("indent") if indent else 2, ensure_ascii=False)
        return rendered + "\n" if text.endswith("\n") else rendered
    opening = re.search(r'"references"\s*:\s*\[', text)
    if opening is None:
        return None
    inserted = "".join(f'\n    {{ "path": {json.dumps(name)} }},' for name in names)
    return text[: opening.end()] + inserted + text[opening.end() :]


def _retired_dependencies(
    sources: Sequence[Path], deletes: Collection[Path], *, replace_eslint: bool
) -> frozenset[str]:
    candidates = _dependency_candidates(sources)
    # ESLint loads a kept TypeScript config through jiti.
    used: set[str] = set() if replace_eslint else {"jiti"}
    for path in sources:
        if path in deletes:
            continue
        if path.suffix.lower() in _IMPORTING_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
            used.update(_package_name(match.group("spec")) for match in _SPECIFIER.finditer(text))
        elif path.name == "package.json":
            used.update(_script_packages(path, candidates, replace_eslint=replace_eslint))
    return frozenset(candidates - used)


def _dependency_candidates(sources: Sequence[Path]) -> set[str]:
    candidates = set(_LEGACY_PEERS - manifest.typescript_peers().keys())
    for source in sources:
        if source.name == "package.json":
            document = parse_json(source.read_text(encoding="utf-8"))
            dependencies = document.get("devDependencies") if isinstance(document, dict) else None
            if isinstance(dependencies, dict):
                candidates.update(
                    name for name in dependencies if name.startswith(("prettier-plugin-", "@prettier/plugin-"))
                )
    return candidates


def _script_packages(path: Path, candidates: Collection[str], *, replace_eslint: bool) -> Iterator[str]:
    for raw in _scripts(path).values():
        if not isinstance(raw, str):
            continue
        command = str(_migrated_script(raw, lint="oxlint", replace_eslint=replace_eslint))
        for package in candidates:
            binary = _PACKAGE_BINARIES.get(package)
            if (binary is not None and _invokes(binary, command)) or f"node_modules/{package}/" in command:
                yield package


def _invokes(binary: str, command: str) -> bool:
    return re.search(rf"(?:^|[\s;&|(])(?:[^\s;&|]*/)?{re.escape(binary)}(?:\s|$)", command) is not None


def _scripts(path: Path) -> Mapping[str, JsonValue]:
    document = parse_json(path.read_text(encoding="utf-8"))
    scripts = document.get("scripts") if isinstance(document, dict) else None
    return scripts if isinstance(scripts, dict) else {}


def _plan_workspace_type_checks(typescript_root: Path, sources: Sequence[Path], changes: _Changes) -> None:
    package = typescript_root / "package.json"
    root_document = parse_json(package.read_text(encoding="utf-8")) if package.is_file() else {}
    manager = str(root_document.get("packageManager", "npm") if isinstance(root_document, dict) else "npm").split(
        "@", 1
    )[0]
    retired = _retired_dependencies(sources, changes.deletes, replace_eslint=True)
    for path in sources:
        if path.name != "package.json" or path.parent == typescript_root:
            continue
        document = parse_json(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        updated = _workspace_document(document, path, typescript_root, manager, retired)
        if updated != document:
            changes.writes.append((path, json.dumps(updated, indent=2, ensure_ascii=False) + "\n"))


def _workspace_document(
    document: Mapping[str, JsonValue], path: Path, root: Path, manager: str, retired: Collection[str]
) -> dict[str, JsonValue]:
    scripts = document.get("scripts")
    scripts = scripts if isinstance(scripts, dict) else {}
    rewritten: dict[str, JsonValue] = {
        name: _workspace_script(command, path, root, manager) for name, command in scripts.items()
    }
    updated = {key: value for key, value in document.items() if key != "prettier"}
    updated["scripts"] = rewritten
    dependencies = document.get("devDependencies")
    if isinstance(dependencies, dict):
        updated["devDependencies"] = {key: value for key, value in dependencies.items() if key not in retired}
    return updated


def _workspace_script(command: JsonValue, path: Path, root: Path, manager: str) -> JsonValue:
    migrated = _migrated_script(command, lint="code-standards check --trust-repository-code", replace_eslint=True)
    if migrated == command or not isinstance(migrated, str) or migrated.startswith("tsrs"):
        return migrated
    script = _workspace_script_name(migrated)
    scope = shlex.quote(path.parent.relative_to(root).as_posix())
    relative_root = shlex.quote(str(Path(*(".." for _ in path.parent.relative_to(root).parts))))
    invocation = _workspace_invocation(manager, script, scope, relative_root)
    if "--fix" in str(_migrated_script(command, lint="lint", replace_eslint=True)):
        invocation += " --fix"
    return invocation


def _workspace_script_name(command: str) -> str:
    if "--check" in command:
        return "format:check"
    return "format" if command.startswith("oxfmt") else "lint"


def _workspace_invocation(manager: str, script: str, scope: str, relative_root: str) -> str:
    if manager == "pnpm":
        return f"pnpm -w run {script} {scope}"
    runner = {"yarn": "yarn --cwd", "bun": "bun run --cwd"}.get(manager)
    if runner is not None:
        return f"{runner} {relative_root} {script} {scope}"
    return f"npm --prefix {relative_root} run {script} -- {scope}"


def _package_name(specifier: str) -> str:
    parts = specifier.split("/")
    return "/".join(parts[:2]) if specifier.startswith("@") else parts[0]


def _note_eslint_invocations(typescript_root: Path, sources: Sequence[Path], changes: _Changes) -> None:
    invoking = sorted(
        _relative(path, typescript_root)
        for path in sources
        if path not in changes.deletes and _invokes("eslint", _commands(path, typescript_root))
    )
    if invoking:
        changes.notes.append(
            f"still invoke ESLint, which has no config any more: {', '.join(invoking)}; run `code-standards check` "
            "(or the `lint` script) instead"
        )


def _commands(path: Path, typescript_root: Path) -> str:
    # What a hook, CI file or package.json runs once migrated; the root package.json's scripts are rewritten.
    if path.name == "package.json":
        scripts = _scripts(path)
        if path.parent == typescript_root:
            scripts = migrated_scripts(scripts, lint="oxlint", replace_eslint=True)
        return "\n".join(command for command in scripts.values() if isinstance(command, str))
    if path.name in _HOOK_AND_CI_NAMES or path.suffix == ".sh" or ".github" in path.parts:
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _migrated_script(command: JsonValue, *, lint: str, replace_eslint: bool) -> JsonValue:
    # Only plain invocations move: `eslint [.] [--fix]`, and a `format` script's `prettier --write|--check [.]`
    # or `biome format [--write] [.]`. A warning budget goes too: Standards owns warning promotion. Anything
    # with other arguments stays, and a remaining ESLint call is reported.
    if not isinstance(command, str):
        return command
    stripped = _RUNNER.sub("", command, count=1)
    stripped = re.sub(r"^OXLINT_TSGOLINT_PATH=\S+\s+", "", stripped)
    if _SHELL_OPERATOR.search(stripped):
        return _type_checked_with_tsrs(command)
    words = shlex.split(_WARNING_BUDGET.sub("", stripped))
    if not words:
        return command
    binary = words.pop(0)
    if binary == "biome" and words and words[0] in {"check", "lint", "format"}:
        mode = words.pop(0)
    else:
        mode = "format" if binary in {"prettier", "oxfmt"} else "lint"
    parsed = _simple_arguments(words, binary=binary, check=mode == "format" and binary != "oxfmt")
    if parsed is None:
        return _type_checked_with_tsrs(command)
    paths, fix, check = parsed
    if binary in {"eslint", "oxlint", "biome"} and mode != "format" and replace_eslint:
        return " ".join([lint, *(["--fix"] if fix else []), *paths])
    if binary in {"prettier", "biome", "oxfmt"} and mode == "format":
        return " ".join(["oxfmt", *(["--check"] if check else []), *paths])
    return _type_checked_with_tsrs(command)


def _simple_arguments(words: Sequence[str], *, binary: str, check: bool) -> tuple[list[str], bool, bool] | None:
    paths: list[str] = []
    fix = False
    index = 0
    while index < len(words):
        word = words[index]
        if word in {"--fix", "--write", "-w"}:
            fix = True
            check = False
        elif word in {"--check", "-c"}:
            check = True
        elif word in {"--config-path", "--config"}:
            index += 1
        elif word.startswith(("--config-path=", "--config=")) or (
            binary == "oxlint"
            and word
            in {
                "--type-aware",
                "--type-check",
                "--deny-warnings",
                "--report-unused-disable-directives",
            }
        ):
            pass
        elif word.startswith("-"):
            return None
        elif word != ".":
            paths.append(shlex.quote(word))
        index += 1
    return paths, fix, check


def _type_checked_with_tsrs(command: str) -> str:
    # DECISIONS #16: tsrs does all type checking; emitting builds keep their compiler.
    return _TYPE_CHECK.sub(
        lambda match: (
            f"{match.group('prefix')}tsrs{match.group('arguments')}"
            if _NO_EMIT.search(match.group("arguments"))
            else match.group(0)
        ),
        command,
    )


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _literal(value: JsonValue, *, indent: int) -> str:
    rendered = json.dumps(value, ensure_ascii=False, indent=2)
    return rendered.replace("\n", "\n" + " " * indent)
