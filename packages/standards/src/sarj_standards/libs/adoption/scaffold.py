"""Turn adoption into one command."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shlex
import textwrap
import tomllib
from typing import TYPE_CHECKING, Final, cast  # ruff: ignore[banned-api] -- narrow untyped YAML at one boundary.

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
import yaml

from sarj_standards.libs.filesystem import is_link_like

from . import hooks, launcher, manifest, packagemanager
from .packagemanager import LOCKFILES, Overrides, PackageManager, YarnVariant


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class Ecosystems:
    """What kind of repo this is, and WHERE, decided by files already there."""

    python: bool
    typescript: bool
    python_root: Path | None = None
    typescript_root: Path | None = None
    typescript_install_root: Path | None = None
    client: PackageManager = PackageManager.NPM
    yarn: YarnVariant = YarnVariant.CLASSIC

    @property
    def any(self) -> bool:
        """Whether anything at all was detected."""
        return self.python or self.typescript


@dataclass
class Plan:
    """Everything `setup` intends to do, so `--dry-run` and the real run agree."""

    ecosystems: Ecosystems
    root: Path | None = None
    profile: manifest.Profile = "standard"
    configs: tuple[str, ...] = ()
    hook_manager: manifest.HookManager = "pre-commit"
    writes: list[tuple[Path, str]] = field(default_factory=list)
    edits: list[tuple[Path, str]] = field(default_factory=list)
    skips: list[tuple[Path, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_ESLINT_CONFIG: Final = "eslint.config.mjs"
_ESLINT_CONFIG_NAMES: Final = (
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.cjs",
    "eslint.config.ts",
    "eslint.config.mts",
    "eslint.config.cts",
)
_PYRIGHT_CONFIG: Final = "pyrightconfig.json"
_STANDALONE_RUFF_CONFIG_NAMES: Final = (".ruff.toml", "ruff.toml")
_PRECOMMIT_CONFIG_NAMES: Final = (".pre-commit-config.yaml", ".pre-commit-config.yml")
_ECOSYSTEM_CONFIGS: Final = frozenset((*manifest.PYTHON_CONFIGS, *manifest.TYPESCRIPT_CONFIGS))
_CUSTOM_HOOK_SCOPE_KEYS: Final = frozenset({"args", "exclude", "exclude_types", "types", "types_or"})
_RUFF_REDUNDANT_SELECT_ALL: Final = re.compile(r"(?m)^[ \t]*select\s*=\s*\[\s*['\"]ALL['\"]\s*\]\s*(?:#.*)?\r?\n?")
_PYTHON_MAJOR: Final = 3
_LEGACY_WORKFLOW_VERIFY: Final = re.compile(
    r"(?P<command>(?:[^\s\"']*/)?sarj-standards(?:\s+--root\s+[^\s;&|]+)?)\s+verify\b"
)
_SCHEMA_LESS_VERSION_LINE: Final = re.compile(r'(?m)^[ \t]*version\s*=\s*"[^"]*"\s*$')
_SCHEMA_LESS_CONFIGS_START: Final = re.compile(r"^[ \t]*configs\s*=")
_FIRST_TOML_TABLE: Final = re.compile(r"(?m)^\s*\[")

_RUFF_EXTEND = re.compile(r"^[ \t]*\[tool\.ruff\][ \t]*$", re.MULTILINE)
_RUFF_LINT_SECTION = re.compile(
    r"(?ms)^(?P<header>[ \t]*\[tool\.ruff\.lint\][ \t]*(?:#[^\n]*)?\n)"
    r"(?P<body>.*?)(?=^[ \t]*\[|\Z)"
)
_RUFF_REPLACEMENT_KEY = re.compile(r"(?m)^(?P<indent>[ \t]*)(?P<key>select|ignore)(?P<equals>[ \t]*=)")

#: Directories a detection walk must not descend into: an installed dependency
#: carries thousands of `package.json` files and a vendored tree carries the
#: pyproject of something this repo did not write.
_SKIP_DIRS: Final = frozenset(
    {
        ".git",
        ".agents",
        ".cache",
        ".claude",
        ".next",
        ".open-next",
        ".turbo",
        ".uv-cache",
        ".wrangler",
        ".yarn",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "build",
        "coverage",
        ".tox",
        ".venv",
        "dist",
        "node_modules",
        "out",
        "target",
        "vendor",
    }
)


def detect(
    root: Path,
    *,
    python_dest: str | None = None,
    typescript_dest: str | None = None,
) -> Ecosystems:
    """Detect each ecosystem and the directory that owns it."""
    python_root = _override(root, python_dest) or _python_root(root)
    typescript_root = _override(root, typescript_dest) or _typescript_root(root)
    install_root = packagemanager.workspace_root(typescript_root, root) if typescript_root else None
    client = packagemanager.detect(install_root) if install_root else PackageManager.NPM
    return Ecosystems(
        python=python_root is not None,
        typescript=typescript_root is not None,
        python_root=python_root,
        typescript_root=typescript_root,
        typescript_install_root=install_root,
        client=client,
        yarn=(
            packagemanager.yarn_variant(install_root)
            if install_root is not None and client is PackageManager.YARN
            else YarnVariant.CLASSIC
        ),
    )


def detect_adopted(root: Path, adopted: manifest.Manifest) -> Ecosystems:
    """Resolve only the ecosystem destinations recorded during setup."""
    python = bool({"ruff", "pyright"}.intersection(adopted.configs))
    typescript = "eslint" in adopted.configs
    detected = detect(
        root,
        python_dest=adopted.python_dest if python else None,
        typescript_dest=adopted.typescript_dest if typescript else None,
    )
    return Ecosystems(
        python=python,
        typescript=typescript,
        python_root=detected.python_root if python else None,
        typescript_root=detected.typescript_root if typescript else None,
        typescript_install_root=detected.typescript_install_root if typescript else None,
        client=detected.client,
        yarn=detected.yarn,
    )


def _override(root: Path, dest: str | None) -> Path | None:
    if dest is None:
        return None
    lexical = root
    for part in Path(dest).parts:
        lexical /= part
        if is_link_like(lexical):
            msg = f"destination {dest!r} traverses a symlink or junction: {lexical}"
            raise ValueError(msg)
    resolved = (root / dest).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        msg = f"destination {dest!r} escapes repository root {root}"
        raise ValueError(msg) from exc
    if not resolved.is_dir():
        msg = f"destination {dest!r} is not a directory"
        raise ValueError(msg)
    return resolved


def _python_root(root: Path) -> Path | None:
    return _shallowest(root, ("pyproject.toml",))


def _typescript_root(root: Path) -> Path | None:
    """Locate the directory an npm client would call the project root."""
    lockfiles = tuple(name for name, _ in LOCKFILES)
    return _shallowest(root, lockfiles) or _shallowest(root, ("package.json",))


def _shallowest(root: Path, names: Sequence[str]) -> Path | None:
    """Find the least-nested directory holding any of `names`."""
    if any((root / name).is_file() for name in names):
        return root
    wanted = frozenset(names)
    found: list[Path] = []
    for parent, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in _SKIP_DIRS)
        if wanted.intersection(filenames):
            found.append(Path(parent))
    if not found:
        return None
    return min(found, key=lambda path: (len(path.relative_to(root).parts), str(path)))


def _all_roots(root: Path, names: Sequence[str]) -> list[Path]:
    wanted = frozenset(names)
    found: list[Path] = []
    for parent, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in _SKIP_DIRS)
        if wanted.intersection(filenames):
            found.append(Path(parent))
    return found


def build_plan(
    root: Path,
    *,
    force: bool,
    update_manifest: bool = False,
    configs: Sequence[str] | None = None,
    python_dest: str | None = None,
    typescript_dest: str | None = None,
    profile: manifest.Profile = "standard",
    hook_manager: manifest.HookManager | None = None,
    allow_existing_nested_eslint: bool = False,
) -> Plan:
    """Work out every file `setup` would create or amend."""
    ecosystems = detect(root, python_dest=python_dest, typescript_dest=typescript_dest)
    selected = (
        tuple(configs)
        if configs is not None
        else manifest.default_configs(has_python=ecosystems.python, has_typescript=ecosystems.typescript)
    )
    selected_hook_manager: manifest.HookManager = hook_manager or hooks.detect_manager(root)
    plan = Plan(
        ecosystems=ecosystems,
        root=root,
        profile=profile,
        configs=selected,
        hook_manager=selected_hook_manager,
    )

    if python_dest is None and ecosystems.python_root is not None:
        _report_independent_roots(root, ecosystems.python_root, ("pyproject.toml",), "Python", plan)
    if typescript_dest is None and ecosystems.typescript_root is not None:
        lockfiles = tuple(name for name, _client in LOCKFILES)
        candidates = lockfiles if _all_roots(root, lockfiles) else ("package.json",)
        _report_independent_roots(root, ecosystems.typescript_root, candidates, "TypeScript", plan)
    if not ecosystems.any:
        if configs is None:
            plan.notes.append("no pyproject.toml and no package.json found -- pass --config to scaffold anyway")
            return plan
        unsupported = tuple(name for name in selected if name in _ECOSYSTEM_CONFIGS)
        if unsupported:
            names = ", ".join(unsupported)
            plan.errors.append(
                f"cannot scaffold ecosystem-specific config(s) without an owning project: {names}; "
                "add pyproject.toml/package.json or select only markdownlint, taplo, and yamllint"
            )
            return plan
        plan.notes.append("no Python or TypeScript project found; adopting repository-wide shared configs only")

    _plan_manifest(root, plan, force=force, update_existing=update_manifest)
    if (
        ecosystems.python
        and ecosystems.python_root is not None
        and any(name in selected for name in manifest.PYTHON_CONFIGS)
    ):
        _plan_python(ecosystems.python_root, plan, force=force)
    if (
        ecosystems.typescript
        and ecosystems.typescript_root is not None
        and any(name in selected for name in manifest.TYPESCRIPT_CONFIGS)
    ):
        _plan_typescript(ecosystems.typescript_root, plan, force=force)
        # Nested configs are only Standards' concern when ESLint was actually
        # selected. At this point eslint.strict.mjs is either present or a
        # target in the config sync plan built by ``plan_init``.
        if "eslint" in selected and not allow_existing_nested_eslint:
            _report_unwired_nested_eslint_configs(root, ecosystems.typescript_root, plan)
    if plan.hook_manager == "pre-commit":
        _plan_precommit(root, plan, force=force)
    elif plan.hook_manager == "lefthook":
        _plan_retire_precommit_staged_check(root, plan)
        if hooks.lefthook_config(root) is None:
            plan.errors.append("--hooks lefthook requires lefthook.yml or lefthook.yaml")
        elif not hooks.lefthook_runs_staged_check(root):
            try:
                plan.writes.append(hooks.wire_lefthook_staged_check(root))
            except ValueError as exc:
                plan.errors.append(str(exc))
            else:
                plan.notes.append("added the canonical staged check to the existing Lefthook configuration")
        else:
            plan.notes.append("preserving validated Lefthook management; no pre-commit config was generated")
    else:
        plan.notes.append(f"preserving {plan.hook_manager} hook management; no pre-commit config was generated")
    workflow = root / ".github" / "workflows" / "standards.yml"
    workflow_contents = github_ci_workflow(root, version=manifest.adopted_version())
    existing_gates = standards_check_workflows(root)
    if workflow.is_file() and _is_managed_workflow(workflow):
        if workflow.read_text(encoding="utf-8") == workflow_contents:
            plan.skips.append((workflow, "already runs the canonical pinned Standards gate"))
        else:
            plan.writes.append((workflow, workflow_contents))
    elif existing_gates:
        names = ", ".join(path.relative_to(root).as_posix() for path in existing_gates)
        plan.skips.append((workflow, f"existing workflow already runs the canonical Standards check: {names}"))
    elif workflow.is_file() and (migrated := _migrate_legacy_workflow_gate(workflow)) is not None:
        plan.writes.append((workflow, migrated))
        plan.notes.append("migrated the removed Standards `verify` CI command to the canonical check")
    elif workflow.is_file() and workflow.read_text(encoding="utf-8") == workflow_contents:
        plan.skips.append((workflow, "already runs the canonical pinned Standards gate"))
    else:
        _record(
            plan,
            workflow,
            workflow_contents,
            force=force,
            reason=(
                "exists; preserve repository-specific CI changes or regenerate explicitly with "
                "`sarj-standards show ci --output .github/workflows/standards.yml`"
            ),
        )
    _note_subproject_destinations(root, plan)
    return plan


def _is_managed_workflow(path: Path) -> bool:
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
    except OSError, IndexError:
        return False
    return (
        first_line.startswith("# Managed by sarj-standards ")
        and "regenerate with `sarj-standards show ci" in first_line
    )


def _report_independent_roots(
    repository: Path,
    selected: Path,
    names: Sequence[str],
    label: str,
    plan: Plan,
) -> None:
    independent = [path for path in _all_roots(repository, names) if not path.is_relative_to(selected)]
    if not independent:
        return
    roots = ", ".join(path.relative_to(repository).as_posix() or "." for path in (selected, *independent))
    option = "--python-dest" if label == "Python" else "--typescript-dest"
    plan.errors.append(
        f"multiple independent {label} roots detected: {roots}; run setup in each independent project"
        f" or select one with {option}"
    )


def _report_unwired_nested_eslint_configs(repository: Path, selected: Path, plan: Plan) -> None:
    for config_root in _all_roots(repository, _ESLINT_CONFIG_NAMES):
        if config_root == selected:
            continue
        configs = tuple(config_root / name for name in _ESLINT_CONFIG_NAMES if (config_root / name).is_file())
        strict = selected / "eslint.strict.mjs"
        if not configs or any(
            _eslint_wiring_reaches_strict(path, repository, planned_strict=strict) for path in configs
        ):
            continue
        relative = config_root.relative_to(repository).as_posix()
        if len(configs) == 1 and (wired := _wire_nested_eslint(configs[0], strict)) is not None:
            plan.writes.append((configs[0], wired))
            plan.notes.append(f"wired nested ESLint policy in {relative}")
            continue
        plan.errors.append(
            f"nested ESLint config in {relative} would shadow Standards and cannot be merged safely; "
            f"run setup with --typescript-dest {shlex.quote(relative)} or wire that config to eslint.strict.mjs"
        )


_NAMED_ESLINT_EXPORT = re.compile(r"(?m)^\s*export\s+default\s+(?P<name>[A-Za-z_$][\w$]*)\s*;?\s*$")


def _wire_nested_eslint(path: Path, strict: Path) -> str | None:
    """Compose a locally declared array flat config with repository policy."""
    text = path.read_text(encoding="utf-8")
    exported = _NAMED_ESLINT_EXPORT.search(text)
    if exported is None:
        return None
    name = re.escape(exported.group("name"))
    if (
        re.search(
            rf"(?m)^\s*(?:const|let)\s+{name}(?:\s*:[^=\n]+)?\s*=\s*(?:defineConfig\s*\(\s*)?\[",
            text[: exported.start()],
        )
        is None
    ):
        # An imported identifier, function result, or object is not known to be
        # iterable. Spreading it could make ESLint crash after setup.
        return None
    relative = os.path.relpath(strict, path.parent).replace(os.sep, "/")
    specifier = relative if relative.startswith(".") else f"./{relative}"
    prefix = f'import sarjStrict from "{specifier}";\n\n'
    replacement = f"export default [...sarjStrict, ...{exported.group('name')}];"
    return f"{prefix}{text[: exported.start()]}{replacement}{text[exported.end() :]}"


def dest_of(root: Path, subdirectory: Path | None) -> str:
    """Express one detected project root the way the manifest records it."""
    if subdirectory is None:
        return "."
    return subdirectory.relative_to(root).as_posix() or "."


def _note_subproject_destinations(root: Path, plan: Plan) -> None:
    """Report configs written outside the repository root."""
    for label, subdirectory in (
        ("python", plan.ecosystems.python_root),
        ("typescript", plan.ecosystems.typescript_root),
    ):
        dest = dest_of(root, subdirectory)
        if dest != ".":
            plan.notes.append(
                f"the {label} project is {dest}/, not the repo root, so its configs"
                f" were written there. Future setup and update runs read the same destinations from"
                f" {manifest.MANIFEST_NAME}."
            )


def _plan_manifest(root: Path, plan: Plan, *, force: bool, update_existing: bool) -> None:
    path = manifest.manifest_path(root)
    current = manifest.load_for_setup(root) if path.is_file() else None
    detected_generated = _generated_python_exclusions(root, plan.ecosystems.python_root)
    existing_exclusions = () if current is None else current.excluded_paths
    desired = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=plan.configs,
        python_dest=dest_of(root, plan.ecosystems.python_root),
        typescript_dest=dest_of(root, plan.ecosystems.typescript_root),
        profile=plan.profile,
        hook_manager=plan.hook_manager,
        verify_paths=(".",) if current is None else current.verify_paths,
        excluded_paths=tuple(dict.fromkeys((*existing_exclusions, *detected_generated))),
        excluded_rules=() if current is None else current.excluded_rules,
        exclusion_overrides=() if current is None else current.exclusion_overrides,
        durable_artifacts=manifest.DEFAULT_DURABLE_ARTIFACTS if current is None else current.durable_artifacts,
        text_excluded_paths=() if current is None else current.text_excluded_paths,
        doctor_excluded_paths=() if current is None else current.doctor_excluded_paths,
        diagnostic_baseline=None if current is None else current.diagnostic_baseline,
        ci_bootstrap=() if current is None else current.ci_bootstrap,
    )
    contents = desired.render()
    if current is not None:
        try:
            strict = manifest.load(root)
        except ValueError:
            strict = None
        if strict is None:
            legacy_text = path.read_text(encoding="utf-8")
            plan.writes.append((path, _migrate_schema_less_manifest(legacy_text, desired)))
            plan.notes.append("migrated the legacy manifest to the current schema")
            return
        if strict != desired:
            if not force and not update_existing:
                plan.skips.append((path, "exists; preserve repository-specific adoption settings"))
                return
            plan.writes.append((path, contents))
            plan.notes.append("updated the manifest to match the requested capabilities and profile")
            return
    _record(plan, path, contents, force=force, reason="already declares an adopted version")


def _migrate_schema_less_manifest(text: str, desired: manifest.Manifest) -> str:
    """Add current metadata without discarding consumer-owned TOML tables."""
    version_line = _SCHEMA_LESS_VERSION_LINE.search(text)
    if version_line is None:  # The legacy loader proves this before planning.
        return text
    prefix = f'schema = {manifest.MANIFEST_SCHEMA}\nbundle = "{desired.version}"\nrule_profile = "all"\n'
    migrated = f"{text[: version_line.start()]}{prefix}{text[version_line.end() :]}"
    migrated = _without_schema_less_configs(migrated)
    disabled = tuple(name for name in manifest.ALL_CONFIGS if name not in desired.configs)
    disabled_text = ", ".join(f'"{name}"' for name in disabled)
    policy = f"\n[capabilities]\ndisable = [{disabled_text}]\n"
    table = _FIRST_TOML_TABLE.search(migrated)
    if table is None:
        return f"{migrated.rstrip()}\n{policy}"
    return f"{migrated[: table.start()].rstrip()}\n{policy}\n{migrated[table.start() :]}"


def _without_schema_less_configs(text: str) -> str:
    """Remove the validated legacy configs array, including multiline arrays."""
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    skipping = False
    depth = 0
    for line in lines:
        if not skipping and _SCHEMA_LESS_CONFIGS_START.match(line):
            skipping = True
        if skipping:
            depth += line.count("[") - line.count("]")
            if depth <= 0:
                skipping = False
            continue
        kept.append(line)
    return "".join(kept)


def _generated_python_exclusions(repository: Path, python_root: Path | None) -> tuple[str, ...]:
    """Detect only generator-owned Python trees backed by explicit metadata."""
    if python_root is None:
        return ()
    exclusions: list[str] = []
    for project in _all_roots(python_root, ("pyproject.toml",)):
        if project == repository:
            continue
        if _is_speakeasy_project(project):
            exclusions.append(f"{project.relative_to(repository).as_posix()}/**")
            continue
        package = _openapi_python_client_package(project)
        if package is not None:
            exclusions.append(f"{package.relative_to(repository).as_posix()}/**")
    return tuple(sorted(set(exclusions)))


def _is_speakeasy_project(project: Path) -> bool:
    """Require both Speakeasy's manifest and its exact source ownership header."""
    if not (project / ".speakeasy" / "gen.yaml").is_file():
        return False
    source = project / "src"
    if not source.is_dir():
        return False
    marker = "Code generated by Speakeasy (https://speakeasy.com). DO NOT EDIT."
    for candidate in sorted(source.rglob("*.py"))[:8]:
        try:
            if marker in candidate.read_text(encoding="utf-8", errors="replace")[:512]:
                return True
        except OSError:
            continue
    return False


def _openapi_python_client_package(project: Path) -> Path | None:
    """Return a Hatch package only when pinned OpenAPI generation owns it."""
    generator = project / "generate.py"
    pyproject = project / "pyproject.toml"
    if not (project / "codegen.config.yml").is_file() or not generator.is_file():
        return None
    try:
        generator_text = generator.read_text(encoding="utf-8", errors="replace")
        parsed: object = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return None
    data = manifest.as_table(parsed)
    description = manifest.text_field(manifest.table_field(data, "project"), "description") or ""
    if not description.casefold().startswith("generated ") or "openapi-python-client" not in generator_text:
        return None
    tool = manifest.table_field(data, "tool")
    hatch = manifest.table_field(tool, "hatch")
    build = manifest.table_field(hatch, "build")
    targets = manifest.table_field(build, "targets")
    wheel = manifest.table_field(targets, "wheel")
    packages = manifest.list_field(wheel, "packages")
    if len(packages) != 1 or not isinstance(packages[0], str):
        return None
    package = (project / packages[0]).resolve()
    if package.parent != project.resolve() or not package.is_dir() or is_link_like(package):
        return None
    return package


def _plan_python(  # ruff: ignore[too-many-locals] -- one TOML boundary preserves consumer policy while wiring bases.
    root: Path, plan: Plan, *, force: bool
) -> None:
    standalone_ruff = [root / name for name in _STANDALONE_RUFF_CONFIG_NAMES if (root / name).is_file()]
    if standalone_ruff:
        names = ", ".join(path.name for path in standalone_ruff)
        plan.errors.append(
            f"cannot safely adopt Ruff while standalone config(s) are active in {root}: {names}; "
            "consolidate their settings into pyproject.toml, remove them, and rerun setup"
        )
        return
    pyproject = root / "pyproject.toml"
    python_target: str | None = None
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        try:
            parsed: object = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            plan.errors.append(f"cannot safely wire {pyproject}: {exc}")
            return
        document = manifest.as_table(parsed)
        python_target = _python_target(document)
        tool = manifest.as_table(document.get("tool"))
        pyright_tables = tuple(name for name in ("pyright", "basedpyright") if name in tool)
        if pyright_tables:
            tables = " and ".join(f"[tool.{name}]" for name in pyright_tables)
            plan.errors.append(
                f"cannot safely wire {pyproject}: {tables} cannot inherit the canonical JSON configuration; "
                "move those settings to pyrightconfig.json, remove the TOML table, then rerun setup"
            )
            return
        ruff = manifest.as_table(tool.get("ruff"))
        lint = manifest.as_table(ruff.get("lint"))
        conflicts = tuple(
            (key, f"extend-{key}")
            for key in ("select", "ignore")
            if key in lint and f"extend-{key}" in lint and not (key == "select" and lint.get("select") == ["ALL"])
        )
        if conflicts:
            rendered = ", ".join(f"{first}/{second}" for first, second in conflicts)
            plan.errors.append(
                f"cannot safely wire {pyproject}: [tool.ruff.lint] defines both {rendered}; "
                "combine each pair under the extend-* key, then rerun setup"
            )
            return
        existing_extend = ruff.get("extend")
        if existing_extend is not None and existing_extend != ".ruff-strict.toml":
            plan.errors.append(
                f"cannot safely wire {pyproject}: [tool.ruff] already extends {existing_extend!r}; "
                "preserve that config chain manually before adding .ruff-strict.toml"
            )
            return
        updated = _extend_ruff_replacement_policy(text)
        if ruff.get("extend") == ".ruff-strict.toml" and updated != text:
            plan.writes.append((pyproject, updated))
        elif ruff.get("extend") == ".ruff-strict.toml":
            plan.skips.append((pyproject, "already extends .ruff-strict.toml"))
        elif _RUFF_EXTEND.search(updated):
            wired = _RUFF_EXTEND.sub('[tool.ruff]\nextend = ".ruff-strict.toml"', updated, count=1)
            plan.writes.append((pyproject, wired))
        elif updated != text:
            plan.writes.append((pyproject, f'{updated}\n[tool.ruff]\nextend = ".ruff-strict.toml"\n'))
        else:
            plan.edits.append((pyproject, '\n[tool.ruff]\nextend = ".ruff-strict.toml"\n'))

    pyright = root / _PYRIGHT_CONFIG
    pyright_jsonc = root / "pyrightconfig.jsonc"
    if pyright_jsonc.is_file():
        competing = f" alongside {pyright}" if pyright.is_file() else ""
        plan.errors.append(
            f"cannot safely wire {pyright_jsonc}{competing}; Pyright JSONC may contain comments and only one "
            "extends parent, so compose .pyright-strict.json manually before rerunning setup"
        )
        return
    if pyright.is_file():
        document, error = _json_object(pyright)
        if error is not None:
            plan.errors.append(f"cannot safely wire {pyright}: {error}")
        elif document is not None:
            existing_pyright_extend = document.get("extends")
            if existing_pyright_extend is not None and existing_pyright_extend != ".pyright-strict.json":
                plan.errors.append(
                    f"cannot safely wire {pyright}: it already extends {existing_pyright_extend!r}; "
                    "Pyright supports one parent, so preserve that config chain manually before adding "
                    ".pyright-strict.json"
                )
                return
            changed = existing_pyright_extend != ".pyright-strict.json"
            document["extends"] = ".pyright-strict.json"
            if python_target is not None and "pythonVersion" not in document:
                document["pythonVersion"] = python_target
                changed = True
            if changed:
                plan.writes.append((pyright, json.dumps(document, indent=_indent_of(pyright.read_text())) + "\n"))
            else:
                plan.skips.append((pyright, "already extends .pyright-strict.json"))
    else:
        generated_document: dict[str, object] = {"extends": ".pyright-strict.json"}
        if python_target is not None:
            generated_document["pythonVersion"] = python_target
        _record(
            plan,
            pyright,
            json.dumps(generated_document, indent=2) + "\n",
            force=force,
            reason='exists; add `"extends": ".pyright-strict.json"` yourself',
        )


def _python_target(document: Mapping[str, object]) -> str | None:
    requires_python = manifest.table_field(document, "project").get("requires-python")
    if not isinstance(requires_python, str):
        return None
    try:
        specifiers = SpecifierSet(requires_python)
    except InvalidSpecifier:
        return None
    boundary_versions: list[Version] = []
    for specifier in specifiers:
        try:
            boundary_versions.append(Version(specifier.version.rstrip(".*")))
        except InvalidVersion:
            continue
    for minor in range(8, 15):
        candidates = [Version(f"3.{minor}.0"), Version(f"3.{minor}.999"), *boundary_versions]
        if any(
            candidate.major == _PYTHON_MAJOR and candidate.minor == minor and candidate in specifiers
            for candidate in candidates
        ):
            return f"3.{minor}"
    return None


def _extend_ruff_replacement_policy(text: str) -> str:
    """Make consumer Ruff selections additive before inheriting our policy."""

    def rewrite_section(section: re.Match[str]) -> str:
        def rewrite_key(match: re.Match[str]) -> str:
            replacement = "extend-select" if match.group("key") == "select" else "extend-ignore"
            return f"{match.group('indent')}{replacement}{match.group('equals')}"

        body = section.group("body")
        if _RUFF_REPLACEMENT_KEY.search(body) and re.search(r"(?m)^\s*extend-select\s*=", body):
            body = _RUFF_REDUNDANT_SELECT_ALL.sub("", body)
        body = _RUFF_REPLACEMENT_KEY.sub(rewrite_key, body)
        return f"{section.group('header')}{body}"

    return _RUFF_LINT_SECTION.sub(rewrite_section, text)


def _json_object(path: Path) -> tuple[dict[str, object] | None, str | None]:
    try:
        parsed: object = json.loads(  # pyright: ignore[reportAny] -- untyped stdlib boundary
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        return None, str(exc)
    if not isinstance(parsed, dict):
        return None, "expected a JSON object"
    document = manifest.as_table(parsed)  # pyright: ignore[reportUnknownArgumentType] -- isinstance establishes the JSON object boundary; as_table narrows its leaves
    return document, None


def _plan_typescript(root: Path, plan: Plan, *, force: bool) -> None:
    existing_configs = [root / name for name in _ESLINT_CONFIG_NAMES if (root / name).is_file()]
    if len(existing_configs) > 1:
        names = ", ".join(path.name for path in existing_configs)
        plan.errors.append(f"multiple active ESLint flat configs in {root}: {names}; keep one before running setup")
        return
    eslint = existing_configs[0] if existing_configs else root / _ESLINT_CONFIG
    if eslint.is_file():
        text = eslint.read_text(encoding="utf-8")
        if _eslint_wiring_reaches_strict(eslint, root, planned_strict=root / "eslint.strict.mjs"):
            plan.skips.append((eslint, "already imports eslint.strict.mjs"))
        elif re.search(r"(?m)^[ \t]*export\s+default\s+defineConfig\s*\(\s*\[", text):
            wired = f'import strict from "./eslint.strict.mjs";\n\n{
                re.sub(
                    r"(?m)^[ \t]*export\s+default\s+defineConfig\s*\(\s*\[",
                    "export default defineConfig([\n  ...strict,",
                    text,
                    count=1,
                )
            }'
            plan.writes.append((eslint, wired))
        elif re.search(r"(?m)^[ \t]*export\s+default\s*\[", text):
            wired = f'import strict from "./eslint.strict.mjs";\n\n{
                re.sub(
                    r"(?m)^[ \t]*export\s+default\s*\[",
                    "export default [\n  ...strict,",
                    text,
                    count=1,
                )
            }'
            plan.writes.append((eslint, wired))
        else:
            plan.errors.append(
                f"cannot safely wire {eslint}; import `./eslint.strict.mjs` and spread it in the exported flat config"
            )
    else:
        _record(plan, eslint, _eslint_entrypoint(), force=force, reason="exists; import ./eslint.strict.mjs from it")
    client = plan.ecosystems.client
    install_root = plan.ecosystems.typescript_install_root or root
    _plan_npm_overrides(install_root, plan, client)
    typescript_root = plan.ecosystems.typescript_root
    if (
        client is PackageManager.YARN
        and typescript_root is not None
        and typescript_root.resolve() != install_root.resolve()
    ):
        _plan_yarn_workspace_peers(typescript_root, plan)
    # pnpm 11 reads overrides from pnpm-workspace.yaml even for a standalone
    # package. Setup creates that policy file below, so the ensuing install is
    # always a workspace install for pnpm.
    is_workspace = (
        client is PackageManager.PNPM or install_root != root or (install_root / "pnpm-workspace.yaml").is_file()
    )
    plan.notes.append(
        f"detected {client} -- install the tested ESLint peer set:\n"
        f"    {packagemanager.install_command(client, workspace=is_workspace, yarn=plan.ecosystems.yarn)}"
    )
    caveat = packagemanager.install_note(client, yarn=plan.ecosystems.yarn)
    if caveat is not None:
        plan.notes.append(caveat)


_LOCAL_MODULE = re.compile(
    r"(?m)^\s*(?:import\b[^;\n]*?\bfrom\s+|import\s*|export\b[^;\n]*?\bfrom\s+)"
    r"[\"'](?P<path>\.[^\"']+)[\"']"
)


def _eslint_wiring_reaches_strict(
    path: Path,
    root: Path,
    seen: set[Path] | None = None,
    *,
    planned_strict: Path | None = None,
) -> bool:
    """Follow local config re-exports without leaving the TypeScript project."""
    visited: set[Path] = set() if seen is None else seen
    resolved = path.resolve()
    if resolved in visited or not resolved.is_file():
        return False
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return False
    visited.add(resolved)
    text = resolved.read_text(encoding="utf-8", errors="replace")
    for match in _LOCAL_MODULE.finditer(text):
        target = (resolved.parent / match.group("path")).resolve()
        if target.name == "eslint.strict.mjs" and (
            target.is_file() or (planned_strict is not None and target == planned_strict.resolve())
        ):
            return True
        candidates = (target, *(target.with_suffix(suffix) for suffix in (".js", ".mjs", ".cjs", ".ts")))
        if any(
            _eslint_wiring_reaches_strict(candidate, root, visited, planned_strict=planned_strict)
            for candidate in candidates
        ):
            return True
    return False


def _plan_npm_overrides(root: Path, plan: Plan, client: PackageManager) -> None:
    """Pin peers in package.json and write the client-specific overrides."""
    overrides = packagemanager.overrides_for(client)
    pnpm_workspace = root / "pnpm-workspace.yaml"
    package_overrides: Overrides | None = overrides
    if client is PackageManager.PNPM:
        current = pnpm_workspace.read_text(encoding="utf-8") if pnpm_workspace.is_file() else ""
        try:
            merged = _merged_pnpm_workspace(current, overrides.entries)
        except ValueError as exc:
            plan.errors.append(f"cannot safely merge pnpm overrides into {pnpm_workspace}: {exc}")
            return
        if merged == current and pnpm_workspace.is_file():
            plan.skips.append((pnpm_workspace, "already carries the pnpm peer overrides"))
        else:
            plan.writes.append((pnpm_workspace, merged))
        package_overrides = None
    override_target = package_json = root / "package.json"
    if client is PackageManager.PNPM:
        override_target = pnpm_workspace
        rendered_overrides = "".join(
            f"      {json.dumps(key)}: {json.dumps(value)}\n" for key, value in overrides.entries.items()
        ).rstrip()
        printed = f"    overrides:\n{rendered_overrides}"
    else:
        printed = textwrap.indent(json.dumps(overrides.as_document(), indent=2), "    ")
    if not package_json.is_file():
        plan.errors.append(
            f"cannot adopt TypeScript in {root}: no package.json exists at the detected install root, so the "
            f"tested ESLint peers and {client} overrides cannot be installed; select the correct workspace root"
        )
        return
    try:
        merged = _merged_npm_overrides(package_json.read_text(encoding="utf-8"), package_overrides, client=client)
    except (TypeError, ValueError) as exc:
        plan.errors.append(f"cannot safely merge tested ESLint peers into {package_json}: {exc}")
        return
    if merged is None:
        plan.skips.append((package_json, f"already pins the tested ESLint peers and {client} overrides"))
        return
    plan.writes.append((package_json, merged))
    plan.notes.append(
        f"pinned the tested ESLint peers in {package_json} and merged the {client} overrides into "
        f"{override_target}:\n{printed}\n"
        f"    {client} cannot resolve the tree without them -- eslint-plugin-react"
        " peers eslint <=9.7 and the unicorn floor needs >=10.4."
    )


def _plan_yarn_workspace_peers(typescript_root: Path, plan: Plan) -> None:
    """Declare ESLint peers in the Yarn workspace that imports them."""
    package_json = typescript_root / "package.json"
    if not package_json.is_file():
        plan.errors.append(f"cannot adopt TypeScript in {typescript_root}: package.json is missing")
        return
    try:
        merged = _merged_npm_overrides(package_json.read_text(encoding="utf-8"), None, client=PackageManager.YARN)
    except (TypeError, ValueError) as exc:
        plan.errors.append(f"cannot safely merge tested ESLint peers into {package_json}: {exc}")
        return
    if merged is None:
        plan.skips.append((package_json, "Yarn workspace already pins the tested ESLint peers"))
        return
    plan.writes.append((package_json, merged))
    plan.notes.append(
        f"pinned the tested ESLint peers in Yarn workspace {package_json};"
        " Plug'n'Play resolves config imports from that workspace rather than its install root"
    )


def _merged_pnpm_workspace(text: str, entries: Mapping[str, object]) -> str:
    """Merge pnpm 11 workspace overrides without reformatting its policy file."""
    if re.search(r"""(?m)^(?:overrides|"overrides"|'overrides'):[ \t]*[^\s#]""", text):
        msg = "flow-style `overrides` is unsupported; convert it to a YAML block mapping and rerun setup"
        raise ValueError(msg)
    current = packagemanager.pnpm_workspace_values(text)
    for key, value in entries.items():
        if key not in current or current[key] == str(value):
            continue
        pattern = re.compile(rf"(?m)^(?P<indent>\s*)(?:{re.escape(json.dumps(key))}|{re.escape(key)}):[^\n]*$")
        text = pattern.sub(rf"\g<indent>{json.dumps(key)}: {json.dumps(value)}", text, count=1)
    current = packagemanager.pnpm_workspace_values(text)
    missing = [(key, value) for key, value in entries.items() if current.get(key) != str(value)]
    if not missing:
        return text
    rendered = "".join(f"  {json.dumps(key)}: {json.dumps(value)}\n" for key, value in missing)
    heading = re.search(r"(?m)^overrides:\s*$", text)
    if heading is None:
        prefix = "" if not text or text.endswith("\n") else "\n"
        return f"{text}{prefix}overrides:\n{rendered}"
    insertion = heading.end() + (1 if text[heading.end() :].startswith("\n") else 0)
    return text[:insertion] + rendered + text[insertion:]


def _merged_npm_overrides(  # ruff: ignore[too-many-locals] -- explicit JSON merge state preserves consumer fields.
    text: str, overrides: Overrides | None, *, client: PackageManager
) -> str | None:
    """Merge exact ESLint peers and optional overrides into package.json text."""
    parsed: object = json.loads(text)  # pyright: ignore[reportAny] -- untyped stdlib boundary
    data = manifest.as_table(parsed)
    if not data:
        msg = "package.json must contain a non-empty JSON object"
        raise TypeError(msg)
    changed = False
    runtime_dependencies = manifest.table_field(data, "dependencies")
    existing_peers = manifest.table_field(data, "devDependencies")
    updated_runtime = dict(runtime_dependencies)
    updated_peers = dict(existing_peers)
    for name, peer_version in manifest.eslint_peers().items():
        # Preserve dependency-section ownership while repairing duplicate peers.
        if name in runtime_dependencies:
            current = runtime_dependencies[name]
            current_major = _semver_major(current)
            required_major = _semver_major(peer_version)
            if current != peer_version and (current_major is None or current_major != required_major):
                msg = (
                    f"{name} is an application runtime dependency at {current!r}, but Standards requires "
                    f"{peer_version!r}; setup will not silently change its major version. Move lint tooling to "
                    "devDependencies or upgrade the runtime dependency explicitly, then rerun setup"
                )
                raise ValueError(msg)
            updated_runtime[name] = peer_version
            updated_peers.pop(name, None)
        else:
            updated_peers[name] = peer_version
    if updated_runtime != runtime_dependencies:
        data["dependencies"] = updated_runtime
        changed = True
    if updated_peers != existing_peers:
        data["devDependencies"] = updated_peers
        changed = True
    if overrides is not None:
        *outer, final = overrides.key_path
        container = data
        for key in outer:
            container = manifest.table_field(container, key)
        existing = manifest.table_field(container, final)
        updated = dict(existing)
        for name, value in overrides.entries.items():
            # A consumer may already override the same package for a different
            # reason, so merge the inner table rather than replacing it.
            current_value = updated.get(name)
            current_entry = manifest.table_field(updated, name)
            new_entry = manifest.as_table(value)
            if new_entry and current_value is not None and not isinstance(current_value, dict):
                current_entry = {".": current_value}
            updated[name] = {**current_entry, **new_entry} if new_entry else value
        if client is PackageManager.NPM:
            _align_npm_direct_dependency_overrides(updated)
        if updated != existing or not _has_path(data, overrides.key_path):
            _set_path(data, overrides.key_path, updated)
            changed = True
    if not changed:
        return None
    rendered = json.dumps(data, indent=_indent_of(text), ensure_ascii=False)
    return rendered + "\n" if text.endswith("\n") else rendered


def _align_npm_direct_dependency_overrides(overrides: dict[str, object]) -> None:
    """Keep consumer overrides valid after setup pins npm's direct ESLint peers.

    npm rejects a direct dependency override whose spec differs from the direct
    dependency with EOVERRIDE. Its ``$name`` reference expresses the same
    override without duplicating the version. Preserve nested child overrides
    and exact existing specs; only repair entries that setup's own peer pinning
    would otherwise make invalid.
    """
    for name, pinned in manifest.eslint_peers().items():
        current = overrides.get(name)
        if isinstance(current, str):
            if current not in {pinned, f"${name}"}:
                overrides[name] = f"${name}"
            continue
        current_table = manifest.as_table(current)
        root_spec = current_table.get(".")
        if root_spec is not None and root_spec not in {pinned, f"${name}"}:
            overrides[name] = {**current_table, ".": f"${name}"}


def _semver_major(value: object) -> int | None:
    """Read the first conventional semantic-version major from an npm range."""
    if not isinstance(value, str):
        return None
    match = re.match(r"^\s*(?:[~^]|>=?|<=?|=)?\s*v?(?P<major>\d+)(?:\.|\s|$)", value)
    return int(match.group("major")) if match is not None else None


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
    """Read a JSON file's indentation so a merge does not reformat the whole file."""
    match = re.search(r"\n(?P<indent> +)\S", text)
    return len(match.group("indent")) if match else 2


def _eslint_entrypoint() -> str:
    """Render the ESLint entrypoint, with the extension seam spelled out."""
    return """// Flat config entrypoint. `eslint.strict.mjs` next to this file is SYNCED --
// `sarj-standards setup` overwrites it, and `setup --dry-run` fails CI if
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
    existing = [root / name for name in _PRECOMMIT_CONFIG_NAMES if (root / name).is_file()]
    if len(existing) > 1:
        plan.errors.append(
            "multiple pre-commit configurations are active: "
            + ", ".join(path.name for path in existing)
            + "; keep one before running setup"
        )
        return
    path = existing[0] if existing else root / _PRECOMMIT_CONFIG_NAMES[0]
    owns_python = plan.ecosystems.python and any(name in plan.configs for name in manifest.PYTHON_CONFIGS)
    block = precommit_block(
        python=owns_python,
        version=manifest.adopted_version(),
        python_dest=dest_of(root, plan.ecosystems.python_root),
    )
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        runner_prefix = _runner_prefix(version=manifest.adopted_version())
        migrated, migration_error = _migrate_official_remote_hook(text, runner_prefix)
        if migration_error is not None:
            plan.errors.append(f"cannot safely migrate {path}: {migration_error}")
            return
        if migrated is not None:
            plan.writes.append((path, migrated))
            return
        custom_legacy = re.search(r"(?m)^\s*-\s+id:\s+['\"]?sarj-standards['\"]?\s*$", text) is not None
        owned_hook = _has_owned_hooks(text)
        if custom_legacy:
            plan.skips.append((path, "preserving a custom legacy sarj-standards hook"))
        elif owned_hook:
            canonical = _canonicalize_owned_hooks(text, runner_prefix)
            if canonical == text:
                plan.skips.append((path, "already runs the canonical sarj-standards hook"))
            else:
                plan.writes.append((path, canonical))
        elif inline := re.search(r"(?m)^repos:\s*\[\s*\]\s*(?P<comment>#.*)?$", text):
            comment = inline.group("comment")
            opened = "repos:" if comment is None else f"repos: {comment}"
            text = f"{text[: inline.start()]}{opened}{text[inline.end() :]}"
            missing = _precommit_check_block(runner_prefix, item_indent=_precommit_item_indent(text))
            addition = missing if text.endswith("\n") else "\n" + missing
            plan.writes.append((path, text + addition))
        elif re.search(r"(?m)^repos:\s*(?:#.*)?$", text):
            missing = _precommit_check_block(runner_prefix, item_indent=_precommit_item_indent(text))
            addition = missing if text.endswith("\n") else "\n" + missing
            plan.edits.append((path, addition))
        else:
            plan.errors.append(f"cannot safely merge hooks into {path}; add this block under `repos:`:\n{block}")
        return
    _record(plan, path, f"repos:\n{block}", force=force, reason="exists")


def _plan_retire_precommit_staged_check(root: Path, plan: Plan) -> None:
    """Remove only the generated Standards hook when Lefthook becomes authoritative."""
    existing = [root / name for name in _PRECOMMIT_CONFIG_NAMES if (root / name).is_file()]
    if len(existing) > 1:
        plan.errors.append(
            "multiple pre-commit configurations are active: "
            + ", ".join(path.name for path in existing)
            + "; keep one before switching hook managers"
        )
        return
    if not existing:
        return
    path = existing[0]
    text = path.read_text(encoding="utf-8")
    if not _has_owned_hooks(text):
        return
    try:
        updated = _remove_owned_precommit_hooks(text)
    except ValueError as exc:
        plan.errors.append(f"cannot safely retire the Standards pre-commit hook in {path}: {exc}")
        return
    plan.writes.append((path, updated))
    plan.notes.append("removed the generated Standards pre-commit hook because Lefthook is authoritative")


def _migrate_official_remote_hook(text: str, runner_prefix: str) -> tuple[str | None, str | None]:
    """Replace a plain official umbrella hook while retaining every unrelated byte."""
    official = tuple(
        block for block in hooks.precommit_repo_blocks(text) if hooks.is_official_standards_repo(block.repository)
    )
    if not official:
        return None, None
    for block in official:
        try:
            parsed: object = yaml.safe_load(f"repos:\n{block.text}")  # pyright: ignore[reportAny] -- narrowed below.
        except yaml.YAMLError as exc:
            return None, f"official Standards hook contains invalid YAML: {exc}"
        repos = manifest.list_field(manifest.as_table(parsed), "repos")
        if len(repos) != 1:
            return None, "official Standards repository block is not a single YAML list item"
        repository = manifest.as_table(repos[0])
        hook_values = manifest.list_field(repository, "hooks")
        if not hook_values:
            return None, "official Standards repository block has no hooks"
        for hook_value in hook_values:
            hook = manifest.as_table(hook_value)
            hook_id = hook.get("id")
            custom_keys = sorted(set(hook) - {"id"})
            is_owned = isinstance(hook_id, str) and (hook_id == "sarj-standards" or hook_id.startswith("sarj-"))
            if not is_owned or custom_keys:
                detail = (
                    f"hook {hook_id!r} has custom keys {custom_keys}"
                    if custom_keys
                    else f"hook {hook_id!r} is not owned by Standards"
                )
                return None, f"{detail}; preserve its scope manually before replacing the remote block"
    first = official[0].start
    removed = text
    for block in reversed(official):
        removed = removed[: block.start] + removed[block.end :]
    item_indents = {block.indent for block in official}
    if len(item_indents) != 1:
        return None, "official Standards repository blocks use inconsistent indentation"
    insertion = _precommit_check_block(runner_prefix, item_indent=item_indents.pop())
    migrated = removed[:first] + insertion + removed[first:]
    return _canonicalize_owned_hooks(migrated, runner_prefix), None


def _precommit_item_indent(text: str) -> int:
    blocks = hooks.precommit_repo_blocks(text)
    return blocks[0].indent if blocks else 2


def _canonicalize_owned_hooks(text: str, runner_prefix: str) -> str:
    """Replace recognized generated hooks with one current staged hook."""
    local_blocks = tuple(
        block
        for block in hooks.precommit_repo_blocks(text)
        if block.repository == "local" and _has_owned_hook_in_block(block.text)
    )
    if not local_blocks:
        return text
    for block in local_blocks:
        custom_keys = _owned_hook_custom_keys(block.text)
        if custom_keys:
            names = ", ".join(sorted(custom_keys))
            msg = (
                f"cannot replace a customized local Sarj hook ({names}); remove those keys or migrate their scope "
                "to the canonical umbrella hook explicitly"
            )
            raise ValueError(msg)
    keeper = local_blocks[0]
    canonical = text
    for block in reversed(local_blocks):
        replacement = _canonicalize_local_hook_block(
            block.text,
            runner_prefix,
            item_indent=block.indent,
            insert_canonical=block.start == keeper.start,
        )
        canonical = canonical[: block.start] + replacement + canonical[block.end :]
    return canonical


def _remove_owned_precommit_hooks(text: str) -> str:
    """Remove generated staged hooks while preserving unrelated local hooks byte-for-byte."""
    local_blocks = tuple(
        block
        for block in hooks.precommit_repo_blocks(text)
        if block.repository == "local" and _has_owned_hook_in_block(block.text)
    )
    updated = text
    for block in reversed(local_blocks):
        custom_keys = _owned_hook_custom_keys(block.text)
        if custom_keys:
            names = ", ".join(sorted(custom_keys))
            msg = f"customized local Sarj hook has consumer-owned keys: {names}"
            raise ValueError(msg)
        replacement = _canonicalize_local_hook_block(
            block.text,
            "",
            item_indent=block.indent,
            insert_canonical=False,
        )
        try:
            parsed = cast("object", yaml.safe_load(f"repos:\n{replacement}"))
        except yaml.YAMLError as exc:
            msg = "generated local hook block is not valid YAML"
            raise ValueError(msg) from exc
        repositories = manifest.list_field(manifest.as_table(parsed), "repos")
        repository = manifest.as_table(repositories[0]) if repositories else {}
        if not manifest.list_field(repository, "hooks"):
            replacement = ""
        updated = updated[: block.start] + replacement + updated[block.end :]
    return updated


def _has_owned_hooks(text: str) -> bool:
    return any(
        _has_owned_hook_in_block(block.text)
        for block in hooks.precommit_repo_blocks(text)
        if block.repository == "local"
    )


def _has_owned_hook_in_block(text: str) -> bool:
    return (
        re.search(
            r"(?m)^\s*-\s+id:\s+['\"]?sarj-standards-(?:check|drift)['\"]?\s*(?:#.*)?$",
            text,
        )
        is not None
    )


def _owned_hook_custom_keys(text: str) -> frozenset[str]:
    lines = text.splitlines(keepends=True)
    owned = {"sarj-standards-check", "sarj-standards-drift"}
    found: set[str] = set()
    for index, line in enumerate(lines):
        match = re.match(
            r"^(?P<indent>\s*)-\s+id:\s+['\"]?(?P<id>[^\s'\"#]+)['\"]?\s*(?:#.*)?$",
            line.rstrip("\r\n"),
        )
        if match is None or match["id"] not in owned:
            continue
        end = hooks.yaml_list_item_end(lines, index, len(match["indent"]))
        for property_line in lines[index + 1 : end]:
            if (key_match := re.match(r"^\s+(?P<key>[a-z_][a-z0-9_-]*):", property_line)) and key_match[
                "key"
            ] in _CUSTOM_HOOK_SCOPE_KEYS:
                found.add(key_match["key"])
    return frozenset(found)


def _canonicalize_local_hook_block(
    text: str,
    runner_prefix: str,
    *,
    item_indent: int,
    insert_canonical: bool,
) -> str:
    """Canonicalize only hooks inside an explicitly local pre-commit repository."""
    lines = text.splitlines(keepends=True)
    owned = {"sarj-standards-check", "sarj-standards-drift"}
    spans: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        match = re.match(
            r"^(?P<indent>\s*)-\s+id:\s+['\"]?(?P<id>[^\s'\"#]+)['\"]?\s*(?:#.*)?$",
            line.rstrip("\r\n"),
        )
        if match is None or match["id"] not in owned:
            continue
        indent = len(match["indent"])
        end = hooks.yaml_list_item_end(lines, index, indent)
        spans.append((index, end))
    if not spans:
        return text
    first = spans[0][0]
    removed = {index for start, end in spans for index in range(start, end)}
    output: list[str] = []
    for index, line in enumerate(lines):
        if insert_canonical and index == first:
            output.append(_precommit_hook(runner_prefix, hook_indent=item_indent + 4))
        if index not in removed:
            output.append(line)
    return "".join(output)


def precommit_block(*, python: bool, version: str, python_dest: str = ".") -> str:
    """Render one staged-file orchestrator, deliberately without a second version pin."""
    _ = python, python_dest
    runner_prefix = _runner_prefix(version=version)
    return _precommit_check_block(runner_prefix)


def _precommit_check_block(runner_prefix: str, *, item_indent: int = 2) -> str:
    repo_indent = " " * item_indent
    return (
        f"{repo_indent}- repo: local\n"
        f"{repo_indent}  hooks:\n"
        f"{_precommit_hook(runner_prefix, hook_indent=item_indent + 4)}"
    )


def _precommit_hook(runner_prefix: str, *, hook_indent: int = 6) -> str:
    item = " " * hook_indent
    field = " " * (hook_indent + 2)
    return (
        f"{item}- id: sarj-standards-check\n"
        f"{field}name: sarj standards -- staged checks\n"
        f"{field}entry: {runner_prefix} check --staged --trust-repository-code --\n"
        f"{field}language: system\n"
        f"{field}always_run: true\n"
        f"{field}pass_filenames: true\n"
        f"{field}require_serial: true\n"
        f"{field}files: '{hooks.PRECOMMIT_FILES_PATTERN}'\n"
        f"{field}stages: [pre-commit]\n"
    )


def _record(plan: Plan, path: Path, contents: str, *, force: bool, reason: str) -> None:
    if path.exists() and not force:
        plan.skips.append((path, reason))
        return
    plan.writes.append((path, contents))


def apply(plan: Plan, *, preconditions: Mapping[Path, bytes | None] | None = None) -> None:
    """Carry out a plan's file writes and appends."""
    from . import transaction  # ruff: ignore[import-outside-top-level] -- avoid a scaffold/transaction import cycle

    if plan.root is None:
        msg = "scaffold plan has no repository root"
        raise OSError(msg)
    transaction.validate_targets(plan.root, tuple(path for path, _contents in (*plan.writes, *plan.edits)))
    for path, contents in plan.writes:
        if preconditions is not None and path in preconditions:
            transaction.assert_expected(plan.root, path, preconditions[path])
        transaction.atomic_write_text(plan.root, path, contents)
    for path, addition in plan.edits:
        if preconditions is not None and path in preconditions:
            transaction.assert_expected(plan.root, path, preconditions[path])
        current = path.read_text(encoding="utf-8")
        transaction.atomic_write_text(plan.root, path, current + addition)


def ci_snippet(plan: Plan, *, version: str) -> str:
    """Render the CI job that keeps a repo honest between upgrades."""
    _ = plan  # Retain the public call shape for compatibility with existing integrations.
    runner_prefix = _runner_prefix(version=version)
    lines = [
        "      - name: sarj standards",
        f"        run: {runner_prefix} check --trust-repository-code",
    ]
    return "\n".join(lines) + "\n"


def github_ci_workflow(root: Path, *, version: str) -> str:
    """Render a complete, pinned GitHub Actions workflow for an adopted repository."""
    root = root.resolve()
    adopted = manifest.load_for_setup(root)
    python_dest = "." if adopted is None else adopted.python_dest
    python_override = (
        None
        if adopted is None or not any(name in adopted.configs for name in manifest.PYTHON_CONFIGS)
        else adopted.python_dest
    )
    typescript_override = (
        None
        if adopted is None or not any(name in adopted.configs for name in manifest.TYPESCRIPT_CONFIGS)
        else adopted.typescript_dest
    )
    ecosystems = detect(root, python_dest=python_override, typescript_dest=typescript_override)
    install_root = ecosystems.typescript_install_root or ecosystems.typescript_root
    runner = _runner_prefix(version=version)
    lines = [
        f"# Managed by sarj-standards {version}; regenerate with `sarj-standards show ci --output .github/workflows/standards.yml`.",
        "name: Standards",
        "",
        "on:",
        "  pull_request:",
        "  push:",
        "",
        "permissions:",
        "  contents: read",
        "",
        "concurrency:",
        "  group: standards-${{ github.workflow }}-${{ github.ref }}",
        "  cancel-in-progress: true",
        "",
        "jobs:",
        "  standards:",
        "    runs-on: ubuntu-latest",
        "    timeout-minutes: 15",
        "    steps:",
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7",
        "        with:",
        "          persist-credentials: false",
        "      - uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0",
        "        with:",
        "          version: '0.12.3'",
        "          enable-cache: true",
        "          cache-dependency-glob: '**/uv.lock'",
    ]
    if ecosystems.typescript:
        if ecosystems.client is PackageManager.BUN:
            lines.append("      - uses: oven-sh/setup-bun@0c5077e51419868618aeaa5fe8019c62421857d6 # v2")
        else:
            lines.extend(
                (
                    "      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7",
                    "        with:",
                    "          node-version: 24",
                )
            )
        if (
            ecosystems.client is PackageManager.NPM
            and install_root is not None
            and (npm_version := packagemanager.declared_version(install_root, PackageManager.NPM)) is not None
        ):
            lines.extend(
                (
                    "      - name: Activate declared npm version",
                    f"        run: npm install --global npm@{npm_version} --ignore-scripts",
                )
            )
        javascript_command = _ci_javascript_install(ecosystems.client, ecosystems.yarn)
        if ecosystems.client in {PackageManager.PNPM, PackageManager.YARN}:
            javascript_command = f"corepack enable && {javascript_command}"
        lines.extend(("      - name: Install JavaScript dependencies", f"        run: {javascript_command}"))
        if install_root is not None and install_root != root:
            relative_install_root = install_root.relative_to(root).as_posix()
            lines.append(f"        working-directory: {json.dumps(relative_install_root)}")
    if ecosystems.python:
        python_root = root / python_dest
        if (python_root / "uv.lock").is_file():
            project = "" if python_dest == "." else f" --project {shlex.quote(python_dest)}"
            workspace = " --all-packages" if _is_uv_workspace(python_root) else ""
            lines.extend(
                ("      - name: Install Python dependencies", f"        run: uv sync --locked{project}{workspace}")
            )
    for index, command in enumerate(() if adopted is None else adopted.ci_bootstrap, start=1):
        label = "Bootstrap analysis inputs" if index == 1 else f"Bootstrap analysis inputs ({index})"
        lines.extend((f"      - name: {label}", f"        run: {json.dumps(command)}"))
    lines.extend(
        (
            "      - name: Run standards",
            f"        run: {runner} check --trust-repository-code --format github",
        )
    )
    return "\n".join(lines) + "\n"


def _is_uv_workspace(project: Path) -> bool:
    """Return whether the locked Python project declares uv workspace members."""
    pyproject = project / "pyproject.toml"
    try:
        parsed: object = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return False
    tool = manifest.table_field(manifest.as_table(parsed), "tool")
    uv = manifest.table_field(tool, "uv")
    return bool(manifest.table_field(uv, "workspace"))


def standards_check_workflows(root: Path) -> tuple[Path, ...]:
    """Return existing workflows whose executable steps run the canonical check."""
    directory = root / ".github" / "workflows"
    if not directory.is_dir():
        return ()
    return tuple(
        path
        for path in sorted((*directory.glob("*.yml"), *directory.glob("*.yaml")))
        if _workflow_runs_standards_check(path)
    )


def _workflow_runs_standards_check(path: Path) -> bool:
    """Inspect only YAML ``run`` values, so comments and step names cannot suppress CI generation."""
    try:
        parsed = cast("object", yaml.safe_load(path.read_text(encoding="utf-8")))
    except OSError, yaml.YAMLError:
        return False
    return any(_run_value_executes_standards_check(command) for command in _workflow_run_commands(parsed))


def _run_value_executes_standards_check(command: str) -> bool:
    """Recognize a direct Standards invocation, not inert shell text mentioning one."""
    logical = command.replace("\\\n", " ")
    for line in logical.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        try:
            tokens = tuple(lexer)
        except ValueError:
            continue
        if _tokens_execute_standards_check(tokens):
            return True
    return False


def _tokens_execute_standards_check(tokens: tuple[str, ...]) -> bool:
    if not tokens or any(token in {";", "&&", "||", "|", "&"} for token in tokens):
        return False
    try:
        executable_index = next(index for index, token in enumerate(tokens) if Path(token).name == "sarj-standards")
    except StopIteration:
        return False
    prefix = tokens[:executable_index]
    direct = not prefix
    uvx = (
        bool(prefix)
        and Path(prefix[0]).name == "uvx"
        and _launcher_options_are_valid(
            prefix[1:],
            flags=frozenset({"--isolated", "--no-cache"}),
            valued=frozenset({"--python", "--from", "--with"}),
        )
    )
    uv_run = (
        bool(prefix)
        and Path(prefix[0]).name == "uv"
        and prefix[1:2] == ("run",)
        and _launcher_options_are_valid(
            prefix[2:],
            flags=frozenset({"--frozen", "--isolated", "--no-project", "--no-sync"}),
            valued=frozenset({"--directory", "--project", "--python", "--with"}),
        )
    )
    if not (direct or uvx or uv_run):
        return False
    arguments = tokens[executable_index + 1 :]
    while arguments and (arguments[0] == "--root" or arguments[0].startswith("--root=")):
        arguments = arguments[2:] if arguments[0] == "--root" else arguments[1:]
    return bool(arguments) and arguments[0] == "check"


def _launcher_options_are_valid(
    tokens: tuple[str, ...],
    *,
    flags: frozenset[str],
    valued: frozenset[str],
) -> bool:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in flags:
            index += 1
            continue
        if token in valued and index + 1 < len(tokens):
            index += 2
            continue
        if any(token.startswith(f"{option}=") for option in valued):
            index += 1
            continue
        return False
    return True


def _migrate_legacy_workflow_gate(path: Path) -> str | None:
    """Rewrite only the removed umbrella verb inside an existing Standards workflow."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    migrated, count = _LEGACY_WORKFLOW_VERIFY.subn(r"\g<command> check --trust-repository-code", text)
    return migrated if count else None


def _workflow_run_commands(value: object) -> tuple[str, ...]:
    if isinstance(value, dict):
        commands: list[str] = []
        table = cast("dict[object, object]", value)
        for key, item in table.items():
            if key == "run" and isinstance(item, str):
                commands.append(item)
            else:
                commands.extend(_workflow_run_commands(item))
        return tuple(commands)
    if isinstance(value, list):
        items = cast("list[object]", value)
        return tuple(command for item in items for command in _workflow_run_commands(item))
    return ()


def _ci_javascript_install(client: PackageManager, yarn: YarnVariant) -> str:
    if client is PackageManager.YARN:
        return (
            "yarn install --immutable --mode=skip-build"
            if yarn is YarnVariant.BERRY
            else "yarn install --frozen-lockfile --ignore-scripts"
        )
    return {
        PackageManager.NPM: "npm ci --no-audit --no-fund --ignore-scripts",
        PackageManager.PNPM: "pnpm install --frozen-lockfile --ignore-scripts",
        PackageManager.BUN: "bun install --frozen-lockfile --ignore-scripts",
    }[client]


def _runner_prefix(*, version: str) -> str:
    return launcher.pinned(version)
