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
from typing import TYPE_CHECKING, Final

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
import yaml

from sarj_lint_configs.libs.filesystem import is_link_like

from . import hooks, launcher, manifest, packagemanager
from .packagemanager import LOCKFILES, Overrides, PackageManager


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

    @property
    def any(self) -> bool:
        """Whether anything at all was detected."""
        return self.python or self.typescript


@dataclass
class Plan:
    """Everything `init` intends to do, so `--dry-run` and the real run agree."""

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
_PRECOMMIT_CONFIG_NAMES: Final = (".pre-commit-config.yaml", ".pre-commit-config.yml")
_ECOSYSTEM_CONFIGS: Final = frozenset((*manifest.PYTHON_CONFIGS, *manifest.TYPESCRIPT_CONFIGS))
_CUSTOM_HOOK_SCOPE_KEYS: Final = frozenset({"always_run", "args", "exclude", "exclude_types", "types", "types_or"})
_RUFF_REDUNDANT_SELECT_ALL: Final = re.compile(r"(?m)^[ \t]*select\s*=\s*\[\s*['\"]ALL['\"]\s*\]\s*(?:#.*)?\r?\n?")
_PYTHON_MAJOR: Final = 3

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
        ".next",
        ".open-next",
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
    return Ecosystems(
        python=python_root is not None,
        typescript=typescript_root is not None,
        python_root=python_root,
        typescript_root=typescript_root,
        typescript_install_root=install_root,
        client=packagemanager.detect(install_root) if install_root else PackageManager.NPM,
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
    configs: Sequence[str] | None = None,
    python_dest: str | None = None,
    typescript_dest: str | None = None,
    profile: manifest.Profile = "standard",
    hook_manager: manifest.HookManager | None = None,
) -> Plan:
    """Work out every file `init` would create or amend."""
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

    _plan_manifest(root, plan, force=force)
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
    if plan.hook_manager == "pre-commit":
        _plan_precommit(root, plan, force=force)
    elif plan.hook_manager == "lefthook":
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
    _note_subproject_destinations(root, plan)
    return plan


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
        f"multiple independent {label} roots detected: {roots}; run init in each independent project"
        f" or select one with {option}"
    )


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
        profile=plan.profile,
        hook_manager=plan.hook_manager,
    ).render()
    _record(plan, path, contents, force=force, reason="already declares an adopted version")


def _plan_python(root: Path, plan: Plan, *, force: bool) -> None:
    pyproject = root / "pyproject.toml"
    python_target: str | None = None
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        try:
            parsed: object = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            plan.errors.append(f"cannot safely wire {pyproject}: {exc}")
            return
        python_target = _python_target(manifest.as_table(parsed))
        ruff = manifest.as_table(manifest.as_table(manifest.as_table(parsed).get("tool")).get("ruff"))
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
                "combine each pair under the extend-* key, then rerun init"
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
    if pyright.is_file():
        document, error = _json_object(pyright)
        if error is not None:
            plan.errors.append(f"cannot safely wire {pyright}: {error}")
        elif document is not None:
            changed = document.get("extends") != ".pyright-strict.json"
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
        plan.errors.append(f"multiple active ESLint flat configs in {root}: {names}; keep one before running init")
        return
    eslint = existing_configs[0] if existing_configs else root / _ESLINT_CONFIG
    if eslint.is_file():
        text = eslint.read_text(encoding="utf-8")
        if _eslint_wiring_reaches_strict(eslint, root):
            plan.skips.append((eslint, "already imports eslint.strict.mjs"))
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
    is_workspace = install_root != root or (install_root / "pnpm-workspace.yaml").is_file()
    plan.notes.append(
        f"detected {client} -- install the tested ESLint peer set:\n"
        f"    {packagemanager.install_command(client, workspace=is_workspace)}"
    )
    caveat = packagemanager.install_note(client)
    if caveat is not None:
        plan.notes.append(caveat)


_LOCAL_MODULE = re.compile(
    r"(?m)^\s*(?:import\b[^;\n]*?\bfrom\s+|import\s*|export\b[^;\n]*?\bfrom\s+)"
    r"[\"'](?P<path>\.[^\"']+)[\"']"
)


def _eslint_wiring_reaches_strict(path: Path, root: Path, seen: set[Path] | None = None) -> bool:
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
        if target.name == "eslint.strict.mjs":
            return True
        candidates = (target, *(target.with_suffix(suffix) for suffix in (".js", ".mjs", ".cjs", ".ts")))
        if any(_eslint_wiring_reaches_strict(candidate, root, visited) for candidate in candidates):
            return True
    return False


def _plan_npm_overrides(root: Path, plan: Plan, client: PackageManager) -> None:
    """Pin peers in package.json and write the client-specific overrides."""
    overrides = packagemanager.overrides_for(client)
    pnpm_workspace = root / "pnpm-workspace.yaml"
    package_overrides: Overrides | None = overrides
    if client is PackageManager.PNPM and pnpm_workspace.is_file():
        current = pnpm_workspace.read_text(encoding="utf-8")
        try:
            merged = _merged_pnpm_workspace(current, overrides.entries)
        except ValueError as exc:
            plan.errors.append(f"cannot safely merge pnpm overrides into {pnpm_workspace}: {exc}")
            return
        if merged == current:
            plan.skips.append((pnpm_workspace, "already carries the pnpm peer overrides"))
        else:
            plan.writes.append((pnpm_workspace, merged))
        package_overrides = None
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
        merged = _merged_npm_overrides(package_json.read_text(encoding="utf-8"), package_overrides)
    except TypeError, ValueError:
        plan.notes.append(
            f"package.json could not be parsed, so the {client} overrides were not"
            f" merged. {client} cannot resolve the peer set without them -- add by"
            f" hand:\n{printed}"
        )
        return
    if merged is None:
        plan.skips.append((package_json, f"already pins the tested ESLint peers and {client} overrides"))
        return
    plan.writes.append((package_json, merged))
    plan.notes.append(
        f"pinned the tested ESLint peers and merged the {client} overrides into {package_json}:\n{printed}\n"
        f"    {client} cannot resolve the tree without them -- eslint-plugin-react"
        " peers eslint <=9.7 and the unicorn floor needs >=10.4."
    )


def _merged_pnpm_workspace(text: str, entries: Mapping[str, object]) -> str:
    """Merge pnpm 11 workspace overrides without reformatting its policy file."""
    if re.search(r"""(?m)^(?:overrides|"overrides"|'overrides'):[ \t]*[^\s#]""", text):
        msg = "flow-style `overrides` is unsupported; convert it to a YAML block mapping and rerun init"
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


def _merged_npm_overrides(text: str, overrides: Overrides | None) -> str | None:
    """Merge exact ESLint peers and optional overrides into package.json text."""
    parsed: object = json.loads(text)  # pyright: ignore[reportAny] -- untyped stdlib boundary
    data = manifest.as_table(parsed)
    if not data:
        msg = "package.json must contain a non-empty JSON object"
        raise TypeError(msg)
    changed = False
    existing_peers = manifest.table_field(data, "devDependencies")
    updated_peers = {**existing_peers, **manifest.eslint_peers()}
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
        if updated != existing or not _has_path(data, overrides.key_path):
            _set_path(data, overrides.key_path, updated)
            changed = True
    if not changed:
        return None
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
    """Read a JSON file's indentation so a merge does not reformat the whole file."""
    match = re.search(r"\n(?P<indent> +)\S", text)
    return len(match.group("indent")) if match else 2


def _eslint_entrypoint() -> str:
    """Render the ESLint entrypoint, with the extension seam spelled out."""
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
    existing = [root / name for name in _PRECOMMIT_CONFIG_NAMES if (root / name).is_file()]
    if len(existing) > 1:
        plan.errors.append(
            "multiple pre-commit configurations are active: "
            + ", ".join(path.name for path in existing)
            + "; keep one before running init"
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
            missing = _precommit_check_block(runner_prefix, repo_indent=_precommit_repo_indent(text))
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
            if hook_id != "sarj-standards" or custom_keys:
                detail = (
                    f"hook {hook_id!r} has custom keys {custom_keys}"
                    if custom_keys
                    else f"hook {hook_id!r} is an individual rule"
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
    indent_match = re.match(r"^(?P<indent>\s*)", lines[first])
    hook_indent = "      " if indent_match is None else indent_match["indent"]
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
        f"{field}entry: {runner_prefix} check --staged --\n"
        f"{field}language: system\n"
        f"{field}verbose: true\n"
        f"{field}pass_filenames: true\n"
        f"{field}require_serial: true\n"
        f"{field}files: '{hooks.PRECOMMIT_FILES_PATTERN}'\n"
        f"{field}stages: [pre-commit]\n"
    )


def _block_indent(text: str) -> str:
    match = re.match(r"^(?P<indent> *)-\s+repo:", text)
    return "  " if match is None else match["indent"]


def _precommit_repo_indent(text: str) -> str:
    blocks = hooks.precommit_repo_blocks(text)
    return "  " if not blocks else _block_indent(blocks[0].text)


def _record(plan: Plan, path: Path, contents: str, *, force: bool, reason: str) -> None:
    if path.exists() and not force:
        plan.skips.append((path, reason))
        return
    plan.writes.append((path, contents))


def apply(plan: Plan) -> None:
    """Carry out a plan's file writes and appends."""
    from . import transaction  # ruff: ignore[import-outside-top-level] -- avoid a scaffold/transaction import cycle

    if plan.root is None:
        msg = "scaffold plan has no repository root"
        raise OSError(msg)
    transaction.validate_targets(plan.root, tuple(path for path, _contents in (*plan.writes, *plan.edits)))
    for path, contents in plan.writes:
        _ = path.write_text(contents, encoding="utf-8")
    for path, addition in plan.edits:
        with path.open("a", encoding="utf-8") as handle:
            _ = handle.write(addition)


def ci_snippet(plan: Plan, *, version: str) -> str:
    """Render the CI job that keeps a repo honest between upgrades."""
    _ = plan  # Retain the public call shape for compatibility with existing integrations.
    runner_prefix = _runner_prefix(version=version)
    lines = [
        "      - name: sarj standards",
        f"        run: {runner_prefix} check",
    ]
    return "\n".join(lines) + "\n"


def github_ci_workflow(root: Path, *, version: str) -> str:
    """Render a complete, pinned GitHub Actions workflow for an adopted repository."""
    ecosystems = detect(root)
    adopted = manifest.load(root)
    python_dest = "." if adopted is None else adopted.python_dest
    runner = _runner_prefix(version=version)
    lines = [
        "name: Standards",
        "",
        "on:",
        "  pull_request:",
        "  push:",
        "    branches: [main]",
        "",
        "permissions:",
        "  contents: read",
        "",
        "jobs:",
        "  standards:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7",
        "      - uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0",
        "        with:",
        "          enable-cache: true",
        "          cache-dependency-glob: '**/uv.lock'",
    ]
    if ecosystems.typescript:
        lines.extend(
            (
                "      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7",
                "      - name: Install JavaScript dependencies",
                f"        run: corepack enable && {_ci_javascript_install(ecosystems.client)}",
            )
        )
    if ecosystems.python:
        project = "" if python_dest == "." else f" --project {shlex.quote(python_dest)}"
        lines.extend(("      - name: Install Python dependencies", f"        run: uv sync --locked{project}"))
    lines.extend(("      - name: Run standards", f"        run: {runner} check"))
    return "\n".join(lines) + "\n"


def _ci_javascript_install(client: PackageManager) -> str:
    return {
        PackageManager.NPM: "npm ci --no-audit --no-fund",
        PackageManager.PNPM: "pnpm install --frozen-lockfile",
        PackageManager.YARN: "yarn install --immutable",
        PackageManager.BUN: "bun install --frozen-lockfile",
    }[client]


def _runner_prefix(*, version: str) -> str:
    return launcher.pinned(version)
