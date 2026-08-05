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

from . import manifest, packagemanager
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
_PRECOMMIT_CONFIG: Final = ".pre-commit-config.yaml"

_RUFF_EXTEND = re.compile(r"^\s*\[tool\.ruff\]\s*$", re.MULTILINE)

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
) -> Plan:
    """Work out every file `init` would create or amend."""
    ecosystems = detect(root, python_dest=python_dest, typescript_dest=typescript_dest)
    selected = (
        tuple(configs)
        if configs is not None
        else manifest.default_configs(has_python=ecosystems.python, has_typescript=ecosystems.typescript)
    )
    plan = Plan(ecosystems=ecosystems, root=root, profile=profile, configs=selected)

    if python_dest is None and ecosystems.python_root is not None:
        _report_independent_roots(root, ecosystems.python_root, ("pyproject.toml",), "Python", plan)
    if typescript_dest is None and ecosystems.typescript_root is not None:
        lockfiles = tuple(name for name, _client in LOCKFILES)
        candidates = lockfiles if _all_roots(root, lockfiles) else ("package.json",)
        _report_independent_roots(root, ecosystems.typescript_root, candidates, "TypeScript", plan)

    if not ecosystems.any:
        plan.notes.append("no pyproject.toml and no package.json found -- pass --configs to scaffold anyway")
        return plan

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
    _plan_precommit(root, plan, force=force)
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
    ).render()
    _record(plan, path, contents, force=force, reason="already declares an adopted version")


def _plan_python(root: Path, plan: Plan, *, force: bool) -> None:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        try:
            parsed: object = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            plan.errors.append(f"cannot safely wire {pyproject}: {exc}")
            return
        ruff = manifest.as_table(manifest.as_table(manifest.as_table(parsed).get("tool")).get("ruff"))
        if ruff.get("extend") == ".ruff-strict.toml":
            plan.skips.append((pyproject, "already extends .ruff-strict.toml"))
        elif _RUFF_EXTEND.search(text):
            updated = _RUFF_EXTEND.sub('[tool.ruff]\nextend = ".ruff-strict.toml"', text, count=1)
            plan.writes.append((pyproject, updated))
        else:
            plan.edits.append((pyproject, '\n[tool.ruff]\nextend = ".ruff-strict.toml"\n'))

    pyright = root / _PYRIGHT_CONFIG
    if pyright.is_file():
        document, error = _json_object(pyright)
        if error is not None:
            plan.errors.append(f"cannot safely wire {pyright}: {error}")
        elif document is not None and document.get("extends") == ".pyright-strict.json":
            plan.skips.append((pyright, "already extends .pyright-strict.json"))
        elif document is not None:
            document["extends"] = ".pyright-strict.json"
            plan.writes.append((pyright, json.dumps(document, indent=_indent_of(pyright.read_text())) + "\n"))
    else:
        _record(
            plan,
            pyright,
            '{ "extends": ".pyright-strict.json" }\n',
            force=force,
            reason='exists; add `"extends": ".pyright-strict.json"` yourself',
        )


def _json_object(path: Path) -> tuple[dict[str, object] | None, str | None]:
    try:
        parsed: object = json.loads(  # pyright: ignore[reportAny] -- untyped stdlib boundary
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        return None, str(exc)
    document = manifest.as_table(parsed)
    if not document:
        return None, "expected a non-empty JSON object"
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
    """Write the overrides without which the peer set cannot be installed at all."""
    overrides = packagemanager.overrides_for(client)
    if not overrides.entries:
        return
    pnpm_workspace = root / "pnpm-workspace.yaml"
    if client is PackageManager.PNPM and pnpm_workspace.is_file():
        current = pnpm_workspace.read_text(encoding="utf-8")
        merged = _merged_pnpm_workspace(current, overrides.entries)
        if merged == current:
            plan.skips.append((pnpm_workspace, "already carries the pnpm peer overrides"))
        else:
            plan.writes.append((pnpm_workspace, merged))
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
    except TypeError, ValueError:
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


def _merged_pnpm_workspace(text: str, entries: Mapping[str, object]) -> str:
    """Merge pnpm 11 workspace overrides without reformatting its policy file."""
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


def _merged_npm_overrides(text: str, overrides: Overrides) -> str | None:
    """Merge the ESLint peer overrides into a package.json's text."""
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
    path = root / _PRECOMMIT_CONFIG
    block = precommit_block(
        python=plan.ecosystems.python,
        version=manifest.adopted_version(),
        python_dest=dest_of(root, plan.ecosystems.python_root),
    )
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        runner_prefix = _runner_prefix(
            python=plan.ecosystems.python,
            version=manifest.adopted_version(),
            python_dest=dest_of(root, plan.ecosystems.python_root),
        )
        has_drift = re.search(r"(?m)^\s*-\s+id:\s+sarj-standards-drift\s*$", text) is not None
        has_check = re.search(r"(?m)^\s*-\s+id:\s+sarj-standards-check\s*$", text) is not None
        has_legacy_check = re.search(r"(?m)^\s*-\s+id:\s+sarj-standards\s*$", text) is not None
        if has_drift and (has_check or has_legacy_check):
            visible = _ensure_hook_verbose(text, "sarj-standards-check") if has_check else text
            if visible == text:
                plan.skips.append((path, "already runs both sarj-standards hooks"))
            else:
                plan.writes.append((path, visible))
        elif re.search(r"(?m)^repos:\s*$", text):
            missing = ""
            if not has_drift:
                missing += _precommit_drift_block(runner_prefix)
            if not has_check and not has_legacy_check:
                missing += _precommit_check_block(runner_prefix)
            if has_legacy_check:
                plan.notes.append("preserved the existing sarj-standards check hook and its baseline arguments")
            addition = missing if text.endswith("\n") else "\n" + missing
            plan.edits.append((path, addition))
        else:
            plan.errors.append(f"cannot safely merge hooks into {path}; add this block under `repos:`:\n{block}")
        return
    _record(plan, path, f"repos:\n{block}", force=force, reason="exists")


def _ensure_hook_verbose(text: str, hook_id: str) -> str:
    """Expose non-blocking rule output from one generated local hook."""
    start = re.search(rf"(?m)^(?P<indent>\s*)-\s+id:\s+{re.escape(hook_id)}\s*$", text)
    if start is None:
        return text
    next_hook = re.search(r"(?m)^\s*-\s+(?:id|repo):\s+", text[start.end() :])
    end = len(text) if next_hook is None else start.end() + next_hook.start()
    block = text[start.start() : end]
    if verbose := re.search(r"(?m)^(?P<indent>\s*)verbose:\s*(?:true|false)\s*$", block):
        if verbose.group(0).rstrip().endswith("true"):
            return text
        absolute_start = start.start() + verbose.start()
        absolute_end = start.start() + verbose.end()
        replacement = f"{verbose.group('indent')}verbose: true"
        return f"{text[:absolute_start]}{replacement}{text[absolute_end:]}"
    insertion = start.end()
    return f"{text[:insertion]}\n{start.group('indent')}  verbose: true{text[insertion:]}"


def precommit_block(*, python: bool, version: str, python_dest: str = ".") -> str:
    """Render the pre-commit hooks, deliberately without a `rev:`."""
    runner_prefix = _runner_prefix(python=python, version=version, python_dest=python_dest)
    return _precommit_drift_block(runner_prefix) + _precommit_check_block(runner_prefix)


def _precommit_drift_block(runner_prefix: str) -> str:
    return (
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: sarj-standards-drift\n"
        "        name: sarj standards -- config + version drift\n"
        f"        entry: {runner_prefix} doctor\n"
        "        language: system\n"
        "        pass_filenames: false\n"
    )


def _precommit_check_block(runner_prefix: str) -> str:
    return (
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: sarj-standards-check\n"
        "        name: sarj standards -- custom rules\n"
        f"        entry: {runner_prefix} check\n"
        "        language: system\n"
        "        verbose: true\n"
        "        files: '(?i)(\\.py|\\.sql|\\.tf|\\.tfvars|\\.hcl|\\.ya?ml|\\.toml|\\.jsonc|\\.mdx?|\\.(?:bash|cfg|conf|env|ini|properties|sh|tftpl|zsh)|(?:^|/)\\.env(?:\\..*)?$|(?:^|/)(?:Dockerfile(?:\\..*)?|Gnumakefile|Justfile|Makefile))$'\n"
    )


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
    python_dest = dest_of(plan.root, plan.ecosystems.python_root) if plan.root is not None else "."
    runner_prefix = _runner_prefix(
        python=plan.ecosystems.python,
        version=version,
        python_dest=python_dest,
    )
    lines = [
        "      - name: sarj standards",
        f"        run: {runner_prefix} verify",
    ]
    return "\n".join(lines) + "\n"


def _runner_prefix(*, python: bool, version: str, python_dest: str) -> str:
    if not python:
        return f"uvx --from sarj-lint-configs=={version} sarj-standards"
    project = "" if python_dest == "." else f" --project {shlex.quote(python_dest)}"
    return f"uv run{project} --frozen sarj-standards"
