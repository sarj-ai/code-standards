from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from fnmatch import fnmatch
from itertools import pairwise
import json
import os
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- git enumerates authored files without executing repository code.
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, NamedTuple

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.filesystem import is_link_like
from sarj_standards.libs.repository import ledger

from . import hooks, launcher, manifest, packagemanager, retired_suppressions, scaffold
from .configs import PYTHON_COMPANION_CONFIGS


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from typing import TypeGuard


class Level(StrEnum):
    OK = "ok"
    WARN = "warn"
    DRIFT = "drift"


@dataclass(frozen=True)
class Finding:
    level: Level
    where: str
    detail: str
    id: str = "doctor.unknown"
    remediation: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "level": self.level.value,
            "where": self.where,
            "detail": self.detail,
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class VersionPinUpdate:
    path: Path
    contents: str
    packages: tuple[str, ...]


class VersionPinRewrite(NamedTuple):
    contents: str
    packages: tuple[str, ...]


class AgeGateRewrite(NamedTuple):
    contents: str
    packages: frozenset[str]


class _PackageEslintPinRewrite(NamedTuple):
    contents: str
    changed: bool


#: `sarj-python-lint==0.25.0`, `"code-standards>=0.9"`, `--from sarj-sql-lint==1.2.3`.
_PIN = re.compile(
    r"(?P<name>sarj-(?:python|sql|iac)-lint|sarj-standards-bootstrap|(?:code|sarj)-standards)\s*"
    r"(?P<op>==|>=|~=)\s*"
    r"(?P<version>[0-9][0-9A-Za-z._+\-]*)"
)
_PREAPPROVED_ESLINT = re.compile(
    r"(?m)^(?P<prefix>[ \t]*(?:npmPreapprovedPackages|minimumReleaseAgeExclude):[^\n]*\n"
    r'(?:[ \t]+-[^\n]*\n)*?[ \t]+-\s*["\']?@sarj/eslint-plugin@)'
    r'(?P<version>[0-9][0-9A-Za-z._+\-]*)(?P<suffix>["\']?\s*(?:#.*)?)$'
)
_AGE_GATE_YAML_HEADER = re.compile(
    r"^(?P<indent>[ \t]*)(?:npmPreapprovedPackages|minimumReleaseAgeExclude):[ \t]*(?:#.*)?$"
)
_AGE_GATE_YAML_ITEM = re.compile(
    r"^(?P<indent>[ \t]*)-[ \t]*(?P<quote>['\"]?)(?P<value>[^'\"#\s]+)(?P=quote)[ \t]*(?:#.*)?$"
)
_NPM_AGE_GATE_EXCLUDE = re.compile(
    r"(?m)^(?P<prefix>[ \t]*min-release-age-exclude[ \t]*=[ \t]*)(?P<value>[^\r\n#]*)(?P<suffix>[ \t]*(?:#.*)?)$"
)
_PACKAGE_DEPENDENCY_SECTION = re.compile(
    r'(?P<prefix>"(?:dependencies|devDependencies)"\s*:\s*\{)(?P<body>[^{}]*)(?P<suffix>\})',
    re.DOTALL,
)
_PACKAGE_ESLINT_PIN = re.compile(
    r'(?P<prefix>"@sarj/eslint-plugin"\s*:\s*")'
    r"(?P<version>[0-9][0-9A-Za-z._+\-]*)"
    r'(?P<suffix>")'
)

#: Standards must not inherit a consumer repository's ``uv.toml`` policy. In
#: particular, ``exclude-newer`` can make a just-published exact bundle appear
#: unavailable in CI for days. Keep custom pin-bearing launchers isolated too.
_UVX_STANDARDS = re.compile(r"\buvx(?P<args>[^\n]*?--from\s+(?:code|sarj)-standards(?:==[^\s]+)?)")
_PERSISTED_CREDENTIALS_OFF = re.compile(r"(?m)^(?P<indent>[ \t]*)persist-credentials:\s*false\s*$")

#: `rev: python-v0.19.0`, `rev: "standards-v0.10.0"`, `rev: 9d073e83b2...`.
#:
#: Raw commit pins can silently become stale, so report them as unverifiable.
_REV = re.compile(r"""rev:\s*['"]?(?P<rev>[a-z-]+-v[0-9][0-9A-Za-z.\-]*|[0-9a-f]{7,40})['"]?""")
_HOOK_ID = re.compile(r"(?m)^\s*-\s+id:\s*(?P<id>[^\s#]+)")

#: A `rev:` that is a raw commit, not a release tag.
_SHA_REV = re.compile(r"^[0-9a-f]{7,40}$")

_ESLINT_PLUGIN: Final = "@sarj/eslint-plugin"
_ESLINT_CONFIG_NAMES: Final = (
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.cjs",
    "eslint.config.ts",
    "eslint.config.mts",
    "eslint.config.cts",
)
_LOCAL_SPECIFIERS: Final = ("file:", "link:", "workspace:", "portal:")
_PYRIGHT_CONFIG_NAMES: Final = frozenset(
    {
        ".basedpyright-strict.json",
        ".pyright-strict.json",
        "basedpyright.strict.json",
        "pyright.strict.json",
        "pyrightconfig.json",
        "pyrightconfig.jsonc",
        "pyproject.toml",
    }
)
_PYRIGHT_REPORT_DEPRECATED = re.compile(
    r"^\s*[\"']?reportDeprecated[\"']?\s*(?::|=)\s*(?P<value>[^,#/\n]+)", re.MULTILINE
)
_RUFF_CONFIG_NAMES: Final = frozenset({".ruff.toml", "ruff.toml", "pyproject.toml"})
_STANDALONE_RUFF_CONFIG_NAMES: Final = (".ruff.toml", "ruff.toml")
_RUFF_REPLACEMENT_KEYS: Final = frozenset({"ignore", "per-file-ignores", "select"})
_CONFIG_TARGETS: Final = MappingProxyType(
    {
        "ruff": ("ruff.strict.toml", "ruff.application.toml", ".ruff-strict.toml", "python"),
        "pyright": ("pyright.strict.json", "pyright.strict.json", ".pyright-strict.json", "python"),
        "eslint": ("eslint.strict.mjs", "eslint.application.mjs", "eslint.strict.mjs", "typescript"),
        "markdownlint": ("markdownlint.strict.yaml", "markdownlint.strict.yaml", ".markdownlint.yaml", "root"),
        "shellcheck": ("shellcheck.strict.rc", "shellcheck.strict.rc", ".shellcheckrc", "root"),
        "taplo": ("taplo.strict.toml", "taplo.strict.toml", ".taplo.toml", "root"),
        "yamllint": ("yamllint.strict.yaml", "yamllint.strict.yaml", ".yamllint.yaml", "root"),
    }
)

#: Where a rule identifier can be written: configs and suppression baselines, but
#: also ordinary source, because an `eslint-disable-next-line @sarj/<rule>` for a
#: rule that no longer exists is its own error under the shipped strict config's
#: `reportUnusedDisableDirectives: "error"`, and a `sarj-noqa: SARJnnn` comment
#: outlives the code it named.
_REFERENCE_SUFFIXES: Final = (
    ".cjs",
    ".cts",
    ".hcl",
    ".js",
    ".json",
    ".jsx",
    ".mjs",
    ".mts",
    ".py",
    ".pyi",
    ".toml",
    ".ts",
    ".tsx",
    ".tf",
    ".tfvars",
    ".yaml",
    ".yml",
)
_RULE_MAPPING_REFERENCE = re.compile(r"^\s*(?:-\s*)?(?:id|entry)\s*:\s*.*sarj", re.IGNORECASE)
_ESLINT_RULE_REFERENCE = re.compile(r"[\"']@sarj/[^\"']+[\"']\s*:")
_STANDARD_BASELINE_NAMES: Final = frozenset({".sarj-python-baseline.json", "suppression-baseline.json"})
_IGNORE_RETIRED_RULE_REFERENCES = "sarj-doctor-ignore-retired-rules"

_SKIP_DIRS: Final = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".playwright-mcp",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".uv-cache",
        ".venv",
        ".next",
        ".open-next",
        ".turbo",
        ".wrangler",
        ".yarn",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "out",
        "target",
        "vendor",
    }
)
_SKILL_ARTIFACT_ROOTS: Final = frozenset({".agents", ".claude"})
_GIT_SAFE_ENV: Final = frozenset(
    {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TMPDIR", "XDG_CONFIG_HOME"}
)
_GIT_DISCOVERY_TIMEOUT: Final = timedelta(seconds=5)
_SHELLCHECK_VERSION: Final = "0.11.0"
_SHELLCHECK_VERSION_RE: Final = re.compile(r"^version:\s*(?P<version>\S+)\s*$", re.MULTILINE)


def _git_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- Git hook variables must not redirect child commands.
        if name in _GIT_SAFE_ENV
    }


def diagnose(root: Path) -> list[Finding]:
    installed = manifest.installed_versions()
    installed[launcher.BOOTSTRAP_PACKAGE] = launcher.BOOTSTRAP_VERSION
    installed[_ESLINT_PLUGIN] = manifest.eslint_peers()[_ESLINT_PLUGIN]
    files = authored_files(root)
    findings = [*_check_manifest(root)]
    findings.extend(_check_repository_launcher(root))
    findings.extend(_check_hook_manager(root))
    findings.extend(_check_pin_files(root, files, installed))
    findings.extend(_check_legacy_in_project_launcher(root))
    if not _has_adopted_eslint(root):
        findings.extend(_check_eslint_plugin(root, files))
    findings.extend(check_retired_rules(root, files))
    findings.extend(check_pyright_deprecated(root, files))
    findings.extend(check_ruff_policy_authority(root, files))
    findings.extend(_check_adoption_wiring(root))
    findings.extend(_check_shellcheck(root, files))
    findings.extend(_check_ci_gate(root))
    unique = dict.fromkeys(findings)
    return sorted(unique, key=lambda finding: (finding.where, finding.id, finding.detail))


def authored_files(root: Path) -> tuple[Path, ...]:
    exclusions = _doctor_exclusions(root)
    return tuple(
        path
        for path in _walk(root)
        if not any(fnmatch(path.relative_to(root).as_posix(), pattern) for pattern in exclusions)
    )


def diagnose_adoption_health(root: Path, selected: Sequence[Path] = ()) -> list[Finding]:
    installed = manifest.installed_versions()
    installed[launcher.BOOTSTRAP_PACKAGE] = launcher.BOOTSTRAP_VERSION
    installed[_ESLINT_PLUGIN] = manifest.eslint_peers()[_ESLINT_PLUGIN]
    files = _adoption_health_files(root, selected)
    findings = [*_check_manifest(root)]
    findings.extend(_check_repository_launcher(root))
    findings.extend(_check_hook_manager(root))
    findings.extend(_check_pin_files(root, files, installed))
    findings.extend(_check_legacy_in_project_launcher(root))
    if not _has_adopted_eslint(root):
        findings.extend(_check_eslint_plugin(root, files))
    findings.extend(check_retired_rules(root, files))
    findings.extend(check_pyright_deprecated(root, files))
    findings.extend(check_ruff_policy_authority(root, files))
    findings.extend(_check_adoption_wiring(root))
    findings.extend(_check_shellcheck(root, files))
    findings.extend(_check_ci_gate(root))
    return sorted(dict.fromkeys(findings), key=lambda finding: (finding.where, finding.id, finding.detail))


def _check_repository_launcher(root: Path) -> Iterator[Finding]:
    try:
        adopted = manifest.load(root)
    except OSError, TypeError, ValueError:
        return
    if adopted is None:
        return
    path = root / launcher.RETIRED_REPOSITORY_LAUNCHER
    if not path.exists():
        return
    yield Finding(
        Level.DRIFT,
        launcher.RETIRED_REPOSITORY_LAUNCHER.as_posix(),
        "repository-local launcher protocol 1 is retired; immutable bootstrap owns repository dispatch",
        "doctor.launcher.retired",
        "run `code-standards setup`",
    )


def _check_shellcheck(root: Path, files: Sequence[Path]) -> Iterator[Finding]:
    try:
        adopted = manifest.load(root)
    except OSError, TypeError, ValueError:
        return
    if adopted is None or "shellcheck" not in adopted.configs:
        return
    from sarj_standards.libs.linting import textlint  # ruff: ignore[import-outside-top-level]

    eligible = tuple(path for path in files if textlint.shell_dialect(path) not in {None, "zsh"})
    if not eligible:
        return
    executable = shutil.which("shellcheck")
    if executable is None:
        yield Finding(
            Level.DRIFT,
            "shellcheck",
            f"ShellCheck is required for {len(eligible)} authored shell file(s) but is not installed",
            "doctor.shellcheck.missing",
            "install the pinned shellcheck-py companion or system ShellCheck 0.11.0",
        )
        return
    try:
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            (executable, "--version"),
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=_git_environment(),
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        yield Finding(
            Level.DRIFT,
            "shellcheck",
            f"cannot attest ShellCheck version: {type(exc).__name__}",
            "doctor.shellcheck.version",
            "install the pinned shellcheck-py companion or system ShellCheck 0.11.0",
        )
        return
    match = _SHELLCHECK_VERSION_RE.search(completed.stdout)
    version = None if match is None else match.group("version")
    if completed.returncode != 0 or version != _SHELLCHECK_VERSION:
        yield Finding(
            Level.DRIFT,
            "shellcheck",
            f"ShellCheck version is {version or 'unknown'}; expected {_SHELLCHECK_VERSION}",
            "doctor.shellcheck.version",
            "install the pinned shellcheck-py companion or system ShellCheck 0.11.0",
        )
        return
    yield Finding(
        Level.OK,
        "shellcheck",
        f"ShellCheck {_SHELLCHECK_VERSION} covers {len(eligible)} authored shell file(s)",
        "doctor.shellcheck.version",
    )


def _adoption_health_files(root: Path, selected: Sequence[Path]) -> tuple[Path, ...]:
    candidates = [
        *(path if path.is_absolute() else root / path for path in selected),
        manifest.manifest_path(root),
    ]
    candidates.extend(
        root / name for name in (*hooks.PRECOMMIT_NAMES, "pyproject.toml", "package.json", "pyrightconfig.json")
    )
    candidates.extend(root.glob("requirements*.txt"))
    candidates.extend(root.glob("requirements*.in"))
    candidates.extend(root.glob("*/pyproject.toml"))
    candidates.extend(root.glob("*/*/pyproject.toml"))
    candidates.extend((root / ".github" / "workflows").glob("*.yml"))
    candidates.extend((root / ".github" / "workflows").glob("*.yaml"))
    try:
        adopted = manifest.load(root)
    except OSError, TypeError, ValueError:
        adopted = None
    if adopted is not None:
        for destination in (adopted.python_dest, adopted.typescript_dest):
            base = _manifest_destination(root, destination)
            if base is not None:
                candidates.extend(base / name for name in ("pyproject.toml", "package.json", "pyrightconfig.json"))
    repository = root.resolve()
    contained: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved.is_relative_to(repository):
            contained.append(resolved)
    return tuple(dict.fromkeys(contained))


def _check_hook_manager(root: Path) -> Iterator[Finding]:
    try:
        adopted = manifest.load(root)
    except OSError, TypeError, ValueError:
        return
    if adopted is None or adopted.hook_manager == "none":
        return
    configured = {
        manager
        for manager, active in (
            ("pre-commit", hooks.precommit_runs_staged_check(root)),
            ("lefthook", hooks.lefthook_runs_staged_check(root)),
        )
        if active
    }
    unexpected_configured = configured - {adopted.hook_manager}
    if unexpected_configured:
        names = ", ".join(sorted(unexpected_configured))
        yield Finding(
            Level.DRIFT,
            manifest.MANIFEST_NAME,
            f"declares {adopted.hook_manager}, but a canonical {names} Standards hook is also active",
            "doctor.hooks.manager-conflict",
            f"rerun `code-standards setup --hooks {adopted.hook_manager}` to keep one hook owner",
        )
    installed = _installed_hook_managers(root) if _git_worktree(root) else frozenset[str]()
    unexpected_installed = installed - {adopted.hook_manager}
    if unexpected_installed:
        names = ", ".join(sorted(unexpected_installed))
        yield Finding(
            Level.DRIFT,
            ".git/hooks/pre-commit",
            f"installed hook chain includes {names}, but the manifest selects {adopted.hook_manager}",
            "doctor.hooks.manager-conflict",
            (
                "run `code-standards maintain hooks install`"
                if adopted.hook_manager == "lefthook"
                else f"reinstall the selected manager with `code-standards setup --hooks {adopted.hook_manager}`"
            ),
        )
    if adopted.hook_manager == "pre-commit":
        if hooks.precommit_runs_staged_check(root):
            yield Finding(
                Level.OK,
                ".pre-commit-config.yaml",
                "runs exactly one canonical staged check",
                "doctor.hooks.precommit",
            )
            if _git_worktree(root) and "pre-commit" not in installed:
                yield Finding(
                    Level.WARN,
                    ".git/hooks/pre-commit",
                    "the configuration is healthy, but this checkout has no installed commit hook",
                    "doctor.hooks.precommit-install",
                    "run `code-standards doctor --repair`",
                )
            return
        yield Finding(
            Level.DRIFT,
            ".pre-commit-config.yaml",
            "pre-commit does not run exactly one canonical `code-standards check --staged` hook",
            "doctor.hooks.precommit",
            "run `code-standards update --offline`",
        )
        return
    path = hooks.lefthook_config(root)
    if path is not None and hooks.lefthook_runs_staged_check(root):
        yield Finding(Level.OK, path.name, "runs the canonical staged check", "doctor.hooks.lefthook")
        if _git_worktree(root) and "lefthook" not in installed:
            yield Finding(
                Level.WARN,
                ".git/hooks/pre-commit",
                "the configuration is healthy, but this checkout has no installed Lefthook commit hook",
                "doctor.hooks.lefthook-install",
                "run `code-standards maintain hooks install`",
            )
        return
    yield Finding(
        Level.DRIFT,
        "lefthook.yml",
        "Lefthook does not run `code-standards check --staged` during pre-commit",
        "doctor.hooks.lefthook",
        "add a Lefthook pre-commit command that runs `code-standards check --staged`",
    )


def _git_worktree(root: Path) -> bool:
    git = shutil.which("git")
    if git is None:
        return False
    try:
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed executable and argv.
            (git, "rev-parse", "--is-inside-work-tree"),
            cwd=root,
            check=False,
            capture_output=True,
            env=_git_environment(),
            text=True,
            timeout=_GIT_DISCOVERY_TIMEOUT.total_seconds(),
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def _installed_hook_managers(root: Path) -> frozenset[str]:
    git = shutil.which("git")
    if git is None:
        return frozenset()
    try:
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed executable and argv.
            (git, "rev-parse", "--git-path", "hooks/pre-commit"),
            cwd=root,
            check=False,
            capture_output=True,
            env=_git_environment(),
            text=True,
            timeout=_GIT_DISCOVERY_TIMEOUT.total_seconds(),
        )
    except OSError, subprocess.TimeoutExpired:
        return frozenset()
    if completed.returncode:
        return frozenset()
    hook = Path(completed.stdout.strip())
    path = hook if hook.is_absolute() else root / hook
    managers: set[str] = set()
    for candidate in (path, path.with_name(f"{path.name}.legacy")):
        if not candidate.is_file():
            continue
        try:
            contents = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "LEFTHOOK_BIN=" in contents or "lefthook" in contents.lower():
            managers.add("lefthook")
        if "hook-type=pre-commit" in contents or "pre_commit" in contents:
            managers.add("pre-commit")
    return frozenset(managers)


def _has_adopted_eslint(root: Path) -> bool:
    try:
        adopted = manifest.load(root)
    except OSError, TypeError, ValueError:
        return False
    return adopted is not None and "eslint" in adopted.configs


def _doctor_exclusions(root: Path) -> tuple[str, ...]:
    path = manifest.manifest_path(root)
    if not path.is_file():
        return ()
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return ()
    values = manifest.list_field(manifest.table_field(manifest.as_table(parsed), "doctor"), "exclude")
    return tuple(value for value in values if isinstance(value, str))


def check_retired_rules(root: Path, files: Sequence[Path] | None = None) -> Iterator[Finding]:
    retired = ledger.load().retired
    if not retired:
        return
    configured_references = _configured_rule_reference_files(root)
    for path in _candidate_files(files if files is not None else _walk(root), _REFERENCE_SUFFIXES):
        if path.name in {"rule-ledger.json", "code_ledger.json"}:
            continue
        counts = retired_rule_counts(path, _read(path), configured=path.resolve() in configured_references)
        for entry in retired:
            hits = counts.get(entry.id, 0)
            if hits:
                where = f"{path.relative_to(root)}: {entry.id} x{hits}"
                yield Finding(
                    Level.DRIFT,
                    where,
                    entry.advice,
                    "doctor.rule.retired",
                    entry.advice,
                )


def retired_rule_references(path: Path, text: str) -> frozenset[str]:
    return frozenset(retired_rule_counts(path, text))


def retired_rule_counts(path: Path, text: str, *, configured: bool = False) -> dict[str, int]:
    if retired_suppressions.supports(path):
        return retired_suppressions.reference_counts(path, text)
    references = _reference_text(text, configured=configured)
    return {entry.id: hits for entry in ledger.load().retired if (hits := len(entry.pattern.findall(references)))}


def _configured_rule_reference_files(root: Path) -> frozenset[Path]:
    paths = {(root / name).resolve() for name in _STANDARD_BASELINE_NAMES}
    paths.add(manifest.manifest_path(root).resolve())
    try:
        adopted = manifest.load(root)
    except OSError, TypeError, ValueError:
        adopted = None
    if adopted is not None and adopted.diagnostic_baseline is not None:
        paths.add((root / adopted.diagnostic_baseline).resolve())
    return frozenset(paths)


def _reference_text(text: str, *, configured: bool = False) -> str:
    if _IGNORE_RETIRED_RULE_REFERENCES in text:
        return ""
    if configured:
        return text
    if "sarj" not in text.lower():
        return ""
    lines: list[str] = []
    for line in text.splitlines():
        normalized = line.lower()
        if "sarj" not in normalized:
            continue
        directive = any(marker in normalized for marker in ("sarj-noqa", "eslint-disable", "--rule"))
        mapped = bool(_RULE_MAPPING_REFERENCE.search(line) or _ESLINT_RULE_REFERENCE.search(line))
        if directive or mapped:
            lines.append(line)
    return "\n".join(lines)


def check_pyright_deprecated(root: Path, files: Sequence[Path] | None = None) -> Iterator[Finding]:
    for path in files if files is not None else _walk(root):
        if path.name not in _PYRIGHT_CONFIG_NAMES:
            continue
        for match in _PYRIGHT_REPORT_DEPRECATED.finditer(_read(path)):
            value = match.group("value").strip()
            if value.strip("\"'") == "error":
                continue
            where = f"{path.relative_to(root)}: reportDeprecated = {value}"
            yield Finding(
                Level.DRIFT,
                where,
                'sets `reportDeprecated` away from "error"; restore it to keep deprecated APIs visible',
                "doctor.pyright.report-deprecated",
                'set `reportDeprecated` to "error"',
            )


def check_ruff_policy_authority(root: Path, files: Sequence[Path] | None = None) -> Iterator[Finding]:
    for path in files if files is not None else _walk(root):
        if path.name not in _RUFF_CONFIG_NAMES:
            continue
        try:
            parsed: object = tomllib.loads(_read(path))
        except tomllib.TOMLDecodeError:
            continue
        document = manifest.as_table(parsed)
        ruff = manifest.as_table(manifest.as_table(document.get("tool")).get("ruff"))
        if not ruff and path.name != "pyproject.toml":
            ruff = document
        if not ruff:
            continue
        extended = ruff.get("extend")
        if not isinstance(extended, str):
            continue
        if not _ruff_extend_reaches_canonical(root, path, extended):
            yield Finding(
                Level.DRIFT,
                f"{path.relative_to(root)}: Ruff config",
                f"extends another project config ({extended}) instead of the canonical .ruff-strict.toml",
                "doctor.ruff.authority",
                "extend the project directly from `.ruff-strict.toml`",
            )
        lint = manifest.as_table(ruff.get("lint"))
        table = "tool.ruff.lint" if path.name == "pyproject.toml" else "lint"
        for key in sorted(_RUFF_REPLACEMENT_KEYS.intersection(lint)):
            yield Finding(
                Level.DRIFT,
                f"{path.relative_to(root)}: [{table}].{key}",
                f"replaces inherited Ruff policy; use `extend-{key}` so the canonical config remains authoritative",
                "doctor.ruff.replaces-policy",
                f"replace `{key}` with `extend-{key}`",
            )
        tidy_imports = manifest.as_table(lint.get("flake8-tidy-imports"))
        if "banned-api" in tidy_imports:
            yield Finding(
                Level.DRIFT,
                f"{path.relative_to(root)}: [{table}.flake8-tidy-imports.banned-api]",
                (
                    "replaces the inherited banned API map and can silently re-enable canonical bans; "
                    "move repository-wide bans into Standards and remove this table"
                ),
                "doctor.ruff.replaces-policy",
                "remove the local `banned-api` table after contributing any additional bans to Standards",
            )


def _ruff_extend_reaches_canonical(root: Path, source: Path, extended: str) -> bool:
    current = source
    value = extended
    seen: set[Path] = set()
    canonical = (root / ".ruff-strict.toml").resolve()
    while True:
        requested = current.parent / value
        target = requested.resolve()
        # The installed config is commonly a symlink, so resolving it changes
        # the basename from `.ruff-strict.toml` to `ruff.strict.toml`.
        if requested.name == ".ruff-strict.toml" or target == canonical:
            try:
                target.relative_to(root.resolve())
            except ValueError:
                return False
            return True
        try:
            target.relative_to(root.resolve())
        except ValueError:
            return False
        if target in seen or not target.is_file():
            return False
        seen.add(target)
        try:
            parsed: object = tomllib.loads(_read(target))
        except tomllib.TOMLDecodeError:
            return False
        document = manifest.as_table(parsed)
        ruff = manifest.as_table(manifest.as_table(document.get("tool")).get("ruff"))
        if not ruff and target.name != "pyproject.toml":
            ruff = document
        next_value = ruff.get("extend")
        if not isinstance(next_value, str):
            return False
        current = target
        value = next_value


def _check_manifest(root: Path) -> Iterator[Finding]:
    try:
        found = manifest.load(root)
    except (OSError, TypeError, ValueError) as exc:
        yield Finding(
            Level.DRIFT,
            manifest.MANIFEST_NAME,
            str(exc),
            "doctor.manifest.invalid",
            "repair the named manifest field, then run `code-standards doctor` again",
        )
        return

    if found is None:
        yield Finding(
            Level.WARN,
            manifest.MANIFEST_NAME,
            "absent -- run `code-standards setup` so the adopted version has one home",
            "doctor.manifest.absent",
            "run `code-standards setup`",
        )
        return

    current = manifest.adopted_version()
    if found.version == current:
        yield Finding(Level.OK, manifest.MANIFEST_NAME, f"version {found.version}", "doctor.manifest.version")
        return
    yield Finding(
        Level.DRIFT,
        manifest.MANIFEST_NAME,
        f"declares {found.version} but the installed wheel is {current}"
        " -- run `code-standards update` so every owned site moves together",
        "doctor.manifest.version",
        "run `code-standards update`",
    )


def _check_pin_files(root: Path, files: Sequence[Path], installed: Mapping[str, str]) -> Iterator[Finding]:
    candidates = (path for path in files if _is_pin_site(path))
    for path in candidates:
        for match in _PIN.finditer(_read(path)):
            name = match.group("name")
            pinned = match.group("version")
            canonical = "code-standards" if name == "sarj-standards" else name
            current = installed.get(canonical)
            where = f"{path.relative_to(root)}: {name}{match.group('op')}{pinned}"
            if current is None:
                yield Finding(
                    Level.WARN,
                    where,
                    f"{name} is not installed here, so the pin is unverified",
                    "doctor.version.unverified",
                )
            elif name == canonical and pinned == current and match.group("op") == "==":
                yield Finding(Level.OK, where, "matches the installed wheel", "doctor.version.pin")
            else:
                yield Finding(
                    Level.DRIFT,
                    where,
                    f"installed {canonical} is {current}; Sarj toolchain dependencies must use the canonical name "
                    "and exact `==` pins",
                    "doctor.version.pin",
                    "run `code-standards update`",
                )
        for match in _PREAPPROVED_ESLINT.finditer(_read(path)):
            pinned = match.group("version")
            current = installed.get(_ESLINT_PLUGIN)
            where = f"{path.relative_to(root)}: {_ESLINT_PLUGIN}@{pinned}"
            if current is None:
                yield Finding(
                    Level.WARN,
                    where,
                    "the preapproved internal package version is unverified",
                    "doctor.version.unverified",
                )
            elif pinned == current:
                yield Finding(Level.OK, where, "matches the tested peer set", "doctor.version.pin")
            else:
                yield Finding(
                    Level.DRIFT,
                    where,
                    f"the tested internal plugin is {_ESLINT_PLUGIN}@{current}",
                    "doctor.version.pin",
                    "run `code-standards update`",
                )


def _check_legacy_in_project_launcher(root: Path) -> Iterator[Finding]:
    try:
        adopted = manifest.load(root)
    except OSError, TypeError, ValueError:
        return
    if adopted is None:
        return
    python_root = _manifest_destination(root, adopted.python_dest)
    if python_root is None:
        return
    pyproject = python_root / "pyproject.toml"
    text = _read(pyproject) if pyproject.is_file() else ""
    installed_names = {
        name for match in _PIN.finditer(text) if (name := match.group("name")) in {"code-standards", "sarj-standards"}
    }
    if not installed_names:
        return
    removal = " ".join(sorted(installed_names))
    where = str(pyproject.relative_to(root))
    yield Finding(
        Level.DRIFT,
        where,
        "code-standards is installed inside the consumer project; the isolated launcher owns the tool runtime",
        "doctor.python.legacy-in-project-tool",
        f"run `uv remove --dev {removal}` in {python_root.relative_to(root).as_posix() or '.'}",
    )


def _is_pin_site(path: Path) -> bool:
    name = path.name.lower()
    if name in {
        "pyproject.toml",
        ".pre-commit-config.yaml",
        ".pre-commit-config.yml",
        "package.json",
        "makefile",
        "gnumakefile",
        "lefthook.yml",
        "lefthook.yaml",
        ".yarnrc.yml",
        ".yarnrc.yaml",
        ".npmrc",
        "pnpm-workspace.yaml",
    }:
        return True
    if name.startswith("requirements") and path.suffix.lower() in {"", ".in", ".txt"}:
        return True
    if "scripts" in path.parts and path.suffix.lower() in {".py", ".sh"}:
        return True
    return ".github" in path.parts and "workflows" in path.parts and path.suffix.lower() in {".yml", ".yaml"}


def rewrite_version_pins(text: str, installed: Mapping[str, str]) -> VersionPinRewrite:
    changed: set[str] = set()
    text, migrated_launchers = launcher.rewrite_legacy_repository_invocations(text)
    if migrated_launchers:
        changed.add("code-standards")

    def isolate_launcher(match: re.Match[str]) -> str:
        if "--no-config" in match.group("args").split():
            return match.group(0)
        changed.add("code-standards")
        return f"uvx --no-config{match.group('args')}"

    def replacement(match: re.Match[str]) -> str:
        name = match.group("name")
        canonical = "code-standards" if name == "sarj-standards" else name
        current = installed.get(canonical) or installed.get(name)
        if current is None or (name == canonical and match.group("version") == current and match.group("op") == "=="):
            return match.group(0)
        changed.add(canonical)
        relative_end = match.end("version") - match.start()
        return f"{canonical}=={current}{match.group(0)[relative_end:]}"

    def preapproved_eslint(match: re.Match[str]) -> str:
        current = installed.get(_ESLINT_PLUGIN)
        if current is None or match.group("version") == current:
            return match.group(0)
        changed.add(_ESLINT_PLUGIN)
        return f"{match.group('prefix')}{current}{match.group('suffix')}"

    isolated = _UVX_STANDARDS.sub(isolate_launcher, text)
    if (
        any(name in isolated for name in ("code-standards", "sarj-standards"))
        and "actions/checkout@" in isolated
        and "fetch-depth:" not in isolated
    ):
        migrated = _PERSISTED_CREDENTIALS_OFF.sub(
            r"\g<0>\n\g<indent>fetch-depth: 0",
            isolated,
            count=1,
        )
        if migrated != isolated:
            changed.add("code-standards")
            isolated = migrated
    pinned = _PIN.sub(replacement, isolated)
    pinned = _PREAPPROVED_ESLINT.sub(preapproved_eslint, pinned)
    preapprovals = manifest.eslint_age_gate_preapprovals()
    if current_plugin := installed.get(_ESLINT_PLUGIN):
        preapprovals[_ESLINT_PLUGIN] = current_plugin
    pinned, age_gate_changed = _rewrite_age_gate_preapprovals(pinned, preapprovals)
    changed.update(age_gate_changed)
    return VersionPinRewrite(pinned, tuple(sorted(changed)))


def _rewrite_age_gate_preapprovals(  # ruff: ignore[too-many-locals] -- lossless policy rewriting tracks layout.
    text: str,
    approvals: Mapping[str, str],
) -> AgeGateRewrite:
    managed = frozenset(approvals)
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        header = _AGE_GATE_YAML_HEADER.fullmatch(line.rstrip("\r\n"))
        if header is None:
            continue
        end = index + 1
        retained: list[str] = []
        trailing: list[str] = []
        saw_item = False
        while end < len(lines):
            candidate = lines[end]
            stripped = candidate.strip()
            indentation = len(candidate) - len(candidate.lstrip(" \t"))
            if stripped and indentation <= len(header.group("indent")) and (not stripped.startswith("#") or saw_item):
                while retained and not retained[-1].strip():
                    trailing.insert(0, retained.pop())
                break
            item = _AGE_GATE_YAML_ITEM.fullmatch(candidate.rstrip("\r\n"))
            if item is None:
                retained.append(candidate)
            else:
                saw_item = True
                value = item.group("value")
                package = next(
                    (name for name in managed if value == name or value.startswith(f"{name}@")),
                    None,
                )
                if package is None:
                    retained.append(candidate)
            end += 1
        item_indent = f"{header.group('indent')}  "
        rendered = [f'{item_indent}- "{name}@{approvals[name]}"\n' for name in sorted(managed)]
        replacement = [line, *retained, *rendered, *trailing]
        original = lines[index:end]
        if replacement != original:
            lines[index:end] = replacement
            return AgeGateRewrite("".join(lines), managed)
        return AgeGateRewrite(text, frozenset())

    def npm_replacement(match: re.Match[str]) -> str:
        existing = [trimmed for item in match.group("value").split(",") if (trimmed := item.strip())]
        retained = [item for item in existing if item not in managed]
        values = ",".join((*retained, *sorted(managed)))
        prefix, suffix = match.group("prefix", "suffix")
        return f"{prefix}{values}{suffix}"

    rewritten = _NPM_AGE_GATE_EXCLUDE.sub(npm_replacement, text, count=1)
    return AgeGateRewrite(rewritten, managed if rewritten != text else frozenset())


def plan_version_pin_updates(
    root: Path,
    installed: Mapping[str, str] | None = None,
) -> tuple[VersionPinUpdate, ...]:
    versions = dict(manifest.installed_versions() if installed is None else installed)
    versions.setdefault(launcher.BOOTSTRAP_PACKAGE, launcher.BOOTSTRAP_VERSION)
    versions.setdefault(_ESLINT_PLUGIN, manifest.eslint_peers()[_ESLINT_PLUGIN])
    exclusions = _doctor_exclusions(root)
    updates: list[VersionPinUpdate] = []
    for path in _walk(root):
        if not _is_pin_site(path):
            continue
        relative = path.relative_to(root).as_posix()
        if any(fnmatch(relative, pattern) for pattern in exclusions):
            continue
        original = _read(path)
        contents, packages = rewrite_version_pins(original, versions)
        if path.name == "package.json":
            contents, plugin_changed = _rewrite_package_eslint_pins(
                contents,
                versions[_ESLINT_PLUGIN],
            )
            if plugin_changed:
                packages = tuple(sorted({*packages, _ESLINT_PLUGIN}))
        if packages:
            updates.append(VersionPinUpdate(path, contents, packages))
    return tuple(updates)


def _rewrite_package_eslint_pins(text: str, version: str) -> _PackageEslintPinRewrite:
    changed = False

    def dependency_section(match: re.Match[str]) -> str:
        nonlocal changed

        def plugin_pin(pin: re.Match[str]) -> str:
            nonlocal changed
            if pin.group("version") == version:
                return pin.group(0)
            changed = True
            return f"{pin.group('prefix')}{version}{pin.group('suffix')}"

        body = _PACKAGE_ESLINT_PIN.sub(plugin_pin, match.group("body"))
        return f"{match.group('prefix')}{body}{match.group('suffix')}"

    return _PackageEslintPinRewrite(_PACKAGE_DEPENDENCY_SECTION.sub(dependency_section, text), changed)


def _check_eslint_plugin(root: Path, files: Sequence[Path]) -> Iterator[Finding]:
    # A missing peer manifest is a packaging defect and must fail loudly.
    floor = manifest.eslint_peers()[_ESLINT_PLUGIN]
    for path in _candidate_files(files, (".json",)):
        if path.name != "package.json":
            continue
        text = _read(path)
        try:
            pinned = _package_json_pin_text(text)
        except json.JSONDecodeError as exc:
            if path != root / "package.json" and _ESLINT_PLUGIN not in text:
                continue
            yield Finding(
                Level.DRIFT,
                str(path.relative_to(root)),
                f"invalid package.json at line {exc.lineno}, column {exc.colno}: {exc.msg}",
                "doctor.package-json.invalid",
                "repair package.json, then rerun doctor",
            )
            continue
        except RecursionError:
            yield Finding(
                Level.DRIFT,
                str(path.relative_to(root)),
                "invalid package.json: document nesting is too deep",
                "doctor.package-json.invalid",
                "repair package.json, then rerun doctor",
            )
            continue
        if pinned is None:
            continue
        where = f"{path.relative_to(root)}: {_ESLINT_PLUGIN}@{pinned}"
        if pinned.startswith("file:") and _local_eslint_plugin_matches(root, path, pinned, floor):
            yield Finding(
                Level.OK,
                where,
                "local plugin package matches the tested peer version",
                "doctor.eslint.plugin",
            )
            continue
        if pinned.startswith(_LOCAL_SPECIFIERS):
            yield Finding(
                Level.WARN,
                f"{path.relative_to(root)}: {_ESLINT_PLUGIN}@{pinned}",
                "local/workspace plugin source cannot prove the published tested version",
                "doctor.eslint.plugin-unverified",
                "use the exact published peer outside local plugin development",
            )
            continue
        if _is_exact_pin(pinned, floor):
            yield Finding(Level.OK, where, "matches the tested peer set", "doctor.eslint.plugin")
        else:
            yield Finding(
                Level.DRIFT,
                where,
                f"the bundled eslint.strict.mjs is tested against {floor};"
                " see `code-standards show peers` for the whole resolvable set",
                "doctor.eslint.plugin",
                "run `code-standards update`",
            )


def _local_eslint_plugin_matches(root: Path, manifest_path: Path, pinned: str, floor: str) -> bool:
    candidate = (manifest_path.parent / pinned.removeprefix("file:")).resolve()
    repository = root.resolve()
    if not candidate.is_relative_to(repository):
        return False
    try:
        raw: object = json.loads((candidate / "package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except OSError, json.JSONDecodeError:
        return False
    return _is_object_table(raw) and raw.get("name") == _ESLINT_PLUGIN and raw.get("version") == floor


def _is_object_table(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _check_adoption_wiring(root: Path) -> Iterator[Finding]:  # ruff: ignore[too-many-locals] -- validates each declared adoption site once
    try:
        adopted = manifest.load(root)
    except OSError, TypeError, ValueError:
        return
    if adopted is None:
        return

    destinations: dict[str, Path | None] = {"root": root}
    for kind, value in (("python", adopted.python_dest), ("typescript", adopted.typescript_dest)):
        destinations[kind] = _manifest_destination(root, value)
        if destinations[kind] is None:
            yield Finding(
                Level.DRIFT,
                f"{manifest.MANIFEST_NAME}: dest.{kind}",
                f"destination {value!r} is missing, not a directory, or escapes the repository root",
                "doctor.manifest.destination",
                f"set `dest.{kind}` to an existing directory inside the repository",
            )
    for name in adopted.configs:
        spec = _CONFIG_TARGETS.get(name)
        if spec is None:
            yield Finding(
                Level.DRIFT,
                manifest.MANIFEST_NAME,
                f"declares unknown config {name!r}",
                "doctor.config.unknown",
                "remove or correct the unknown config name in the adoption manifest",
            )
            continue
        standard_source, application_source, target_name, kind = spec
        destination = destinations[kind]
        if destination is None:
            continue
        target = destination / target_name
        source_name = application_source if adopted.profile == "application" else standard_source
        expected = CONFIGS_DIR / source_name
        if not target.is_file():
            yield Finding(
                Level.DRIFT,
                str(target.relative_to(root)),
                f"declared {name} config is missing",
                "doctor.config.missing",
                "run `code-standards update`",
            )
        elif target.read_bytes() != expected.read_bytes():
            if is_link_like(target):
                linked = target.resolve(strict=False)
                yield Finding(
                    Level.DRIFT,
                    str(target.relative_to(root)),
                    f"declared {name} config is a source-controlled link to {linked.relative_to(root) if linked.is_relative_to(root) else linked} and differs from the executing bundle",
                    "doctor.config.source-drift",
                    "update or rebase the Standards source checkout; automatic repair will not replace a source-controlled link",
                )
                continue
            yield Finding(
                Level.DRIFT,
                str(target.relative_to(root)),
                f"declared {name} config differs from the installed bundle",
                "doctor.config.drift",
                "run `code-standards update`",
            )
        else:
            yield Finding(Level.OK, str(target.relative_to(root)), f"{name} config is current", "doctor.config.current")
        if name == "pyright":
            for companion_name, (companion_source, companion_target) in PYTHON_COMPANION_CONFIGS.items():
                companion = destination / companion_target
                companion_expected = CONFIGS_DIR / companion_source
                if not companion.is_file():
                    yield Finding(
                        Level.DRIFT,
                        str(companion.relative_to(root)),
                        f"{companion_name} companion config is missing",
                        "doctor.config.missing",
                        "run `code-standards update`",
                    )
                elif companion.read_bytes() != companion_expected.read_bytes():
                    yield Finding(
                        Level.DRIFT,
                        str(companion.relative_to(root)),
                        f"{companion_name} companion config differs from the installed bundle",
                        "doctor.config.drift",
                        "run `code-standards update`",
                    )
                else:
                    yield Finding(
                        Level.OK,
                        str(companion.relative_to(root)),
                        f"{companion_name} companion config is current",
                        "doctor.config.current",
                    )

    python_root = destinations["python"]
    if python_root is not None:
        if "ruff" in adopted.configs:
            competing = [path for name in _STANDALONE_RUFF_CONFIG_NAMES if (path := python_root / name).is_file()]
            if competing:
                rendered = ", ".join(path.name for path in competing)
                yield Finding(
                    Level.DRIFT,
                    str(python_root.relative_to(root) or "."),
                    f"standalone Ruff config(s) bypass pyproject.toml and the adopted chain: {rendered}",
                    "doctor.ruff.ambiguous-config",
                    "consolidate the standalone Ruff settings into pyproject.toml, remove them, then rerun doctor",
                )
            yield from _check_text_wiring(
                root,
                python_root / "pyproject.toml",
                ".ruff-strict.toml",
                "doctor.ruff.wiring",
                'add `extend = ".ruff-strict.toml"` under `[tool.ruff]`',
            )
        if "pyright" in adopted.configs:
            configs = (python_root / "pyrightconfig.json", python_root / "pyrightconfig.jsonc")
            active = next((path for path in configs if path.is_file()), configs[0])
            yield from _check_text_wiring(
                root,
                active,
                ".basedpyright-strict.json",
                "doctor.pyright.wiring",
                "set `extends` to `.basedpyright-strict.json`",
            )

    typescript_root = destinations["typescript"]
    if typescript_root is not None and "eslint" in adopted.configs:
        entrypoints = [typescript_root / name for name in _ESLINT_CONFIG_NAMES if (typescript_root / name).is_file()]
        if len(entrypoints) > 1:
            yield Finding(
                Level.DRIFT,
                str(typescript_root.relative_to(root)),
                f"multiple ESLint flat configs are active: {', '.join(path.name for path in entrypoints)}",
                "doctor.eslint.ambiguous-config",
                "keep one ESLint flat config and remove the shadowed duplicates",
            )
        active_entrypoint = entrypoints[0] if entrypoints else typescript_root / "eslint.config.mjs"
        if _eslint_wiring_reaches_strict(active_entrypoint, typescript_root):
            yield Finding(
                Level.OK,
                str(active_entrypoint.relative_to(root)),
                "references eslint.strict.mjs",
                "doctor.eslint.wiring",
            )
        else:
            yield Finding(
                Level.DRIFT,
                str(active_entrypoint.relative_to(root)),
                "does not reference eslint.strict.mjs directly or through a local config",
                "doctor.eslint.wiring",
                "import and spread `./eslint.strict.mjs` from the active ESLint config chain",
            )
        shadowing = _nested_eslint_configs(typescript_root, active_entrypoint)
        if shadowing:
            rendered = ", ".join(path.relative_to(root).as_posix() for path in shadowing)
            yield Finding(
                Level.DRIFT,
                str(typescript_root.relative_to(root)),
                f"package-local ESLint configs can bypass the adopted config: {rendered}",
                "doctor.eslint.shadowed-config",
                "make each package config import the adopted eslint.strict.mjs chain, or remove the shadowing config",
            )
        yield from _check_eslint_peer_set(root, typescript_root)


def _check_ci_gate(root: Path) -> Iterator[Finding]:
    try:
        adopted = manifest.load(root)
    except OSError, TypeError, ValueError:
        return
    if adopted is None:
        return
    workflows = scaffold.standards_check_workflows(root)
    if workflows:
        rendered = ", ".join(path.relative_to(root).as_posix() for path in workflows)
        yield Finding(Level.OK, rendered, "runs the canonical Standards check", "doctor.ci.gate")
        return
    yield Finding(
        Level.DRIFT,
        ".github/workflows",
        "no executable workflow step runs `code-standards ... check`",
        "doctor.ci.gate",
        "run `code-standards show ci --output .github/workflows/standards.yml`",
    )


def _nested_eslint_configs(typescript_root: Path, active_entrypoint: Path) -> tuple[Path, ...]:
    names = {*_ESLINT_CONFIG_NAMES, ".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs"}
    found: list[Path] = []
    for path in _walk(typescript_root):
        if path == active_entrypoint or path.name not in names:
            continue
        if path.parent == typescript_root and path.name == "eslint.strict.mjs":
            continue
        if _eslint_wiring_reaches_strict(path, typescript_root):
            continue
        found.append(path)
    return tuple(sorted(found))


def _manifest_destination(root: Path, value: str) -> Path | None:
    try:
        destination = (root / value).resolve()
        destination.relative_to(root.resolve())
    except OSError, ValueError:
        destination = None
    if destination is None or not destination.is_dir():
        # This helper cannot yield, so the caller gets the finding through a
        # sentinel file check below; keep the path invalid rather than escaping.
        return None
    return destination


def _check_text_wiring(
    root: Path,
    path: Path,
    needle: str,
    finding_id: str,
    remediation: str,
) -> Iterator[Finding]:
    if not path.is_file():
        yield Finding(Level.DRIFT, str(path.relative_to(root)), "wiring file is missing", finding_id, remediation)
        return
    text = _read(path)
    if needle not in text:
        yield Finding(Level.DRIFT, str(path.relative_to(root)), f"does not reference {needle}", finding_id, remediation)
    else:
        yield Finding(Level.OK, str(path.relative_to(root)), f"references {needle}", finding_id)


_LOCAL_MODULE = re.compile(
    r"(?m)^\s*(?:import\b[^;\n]*?\bfrom\s+|import\s*|export\b[^;\n]*?\bfrom\s+)"
    r"[\"'](?P<path>\.[^\"']+)[\"']"
)


def _eslint_wiring_reaches_strict(path: Path, root: Path, seen: set[Path] | None = None) -> bool:
    visited: set[Path] = set() if seen is None else seen
    resolved = path.resolve()
    if resolved in visited or not resolved.is_file():
        return False
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return False
    visited.add(resolved)
    text = _read(resolved)
    for match in _LOCAL_MODULE.finditer(text):
        target = (resolved.parent / match.group("path")).resolve()
        if target.name == "eslint.strict.mjs" and target.is_file():
            return True
        candidates = (target, *(target.with_suffix(suffix) for suffix in (".js", ".mjs", ".cjs", ".ts")))
        if any(_eslint_wiring_reaches_strict(candidate, root, visited) for candidate in candidates):
            return True
    return False


def _check_eslint_peer_set(root: Path, typescript_root: Path) -> Iterator[Finding]:
    package_root = packagemanager.workspace_root(typescript_root, root)
    package_json = package_root / "package.json"
    if not package_json.is_file():
        yield Finding(
            Level.DRIFT,
            str(package_json.relative_to(root)),
            "package.json is missing for the declared TypeScript project",
            "doctor.eslint.package",
            "restore package.json or correct dest.typescript",
        )
        return
    try:
        parsed: object = json.loads(_read(package_json))  # pyright: ignore[reportAny] -- untyped stdlib boundary
    except json.JSONDecodeError as exc:
        yield Finding(
            Level.DRIFT,
            str(package_json.relative_to(root)),
            f"invalid package.json at line {exc.lineno}, column {exc.colno}: {exc.msg}",
            "doctor.package-json.invalid",
            "repair package.json, then rerun doctor",
        )
        return
    except RecursionError:
        yield Finding(
            Level.DRIFT,
            str(package_json.relative_to(root)),
            "invalid package.json: document nesting is too deep",
            "doctor.package-json.invalid",
            "repair package.json, then rerun doctor",
        )
        return
    document = manifest.as_table(parsed)
    if not isinstance(parsed, dict):
        yield Finding(
            Level.DRIFT,
            str(package_json.relative_to(root)),
            f"package.json must contain a JSON object, found {type(parsed).__name__}",
            "doctor.package-json.invalid",
            "repair package.json, then rerun doctor",
        )
        return
    declared: dict[str, object] = {}
    for key in ("dependencies", "devDependencies"):
        declared.update(manifest.table_field(document, key))
    for name, expected in sorted(manifest.eslint_peers().items()):
        actual = declared.get(name)
        if isinstance(actual, str) and _is_exact_pin(actual, expected):
            continue
        yield Finding(
            Level.DRIFT,
            f"{package_json.relative_to(root)}: {name}",
            f"expected exact tested peer {expected}, found {actual!r}",
            "doctor.eslint.peer",
            "run `code-standards update`",
        )

    client = packagemanager.detect(package_root)
    overrides = packagemanager.overrides_for(client)
    pnpm_workspace = package_root / "pnpm-workspace.yaml"
    if client is packagemanager.PackageManager.PNPM:
        if not pnpm_workspace.is_file():
            yield Finding(
                Level.DRIFT,
                str(pnpm_workspace.relative_to(root)),
                "required pnpm 11 workspace policy is missing",
                "doctor.eslint.override",
                "run `code-standards update`",
            )
            return
        workspace_text = _read(pnpm_workspace)
        values = packagemanager.pnpm_workspace_values(workspace_text)
        if all(values.get(key) == str(value) for key, value in overrides.entries.items()):
            return
        yield Finding(
            Level.DRIFT,
            str(pnpm_workspace.relative_to(root)),
            "required pnpm peer override is missing",
            "doctor.eslint.override",
            "run `code-standards update`",
        )
        return
    table: Mapping[str, object] = document
    for key in overrides.key_path:
        table = manifest.table_field(table, key)
    if not _contains_expected_mapping(table, overrides.entries):
        yield Finding(
            Level.DRIFT,
            str(package_json.relative_to(root)),
            f"required {client} peer override is missing",
            "doctor.eslint.override",
            "run `code-standards update`",
        )


def _contains_expected_mapping(actual: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        expected_table = manifest.as_table(expected_value)
        if expected_table:
            actual_table = manifest.as_table(actual_value)
            if not actual_table or not _contains_expected_mapping(actual_table, expected_table):
                return False
        elif actual_value != expected_value:
            return False
    return True


def _is_exact_pin(pinned: str, expected: str) -> bool:
    normalized = pinned.strip()
    if normalized.startswith("=="):
        normalized = normalized[2:].strip()
    elif normalized.startswith("="):
        normalized = normalized[1:].strip()
    return normalized == expected


def _package_json_pin_text(text: str) -> str | None:
    parsed: object = json.loads(text)  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
    package_json = manifest.as_table(parsed)
    for field in ("dependencies", "devDependencies"):
        pinned = manifest.as_table(package_json.get(field)).get(_ESLINT_PLUGIN)
        if isinstance(pinned, str):
            return pinned
    return None


def _candidate_files(files: Sequence[Path], suffixes: Sequence[str]) -> Iterator[Path]:
    wanted = frozenset(suffixes)
    for path in files:
        if path.suffix.lower() in wanted:
            yield path


def _walk(root: Path) -> tuple[Path, ...]:
    git = shutil.which("git")
    try:
        completed = (
            subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed Git executable and argv.
                (git, "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"),
                check=False,
                capture_output=True,
                env=_git_environment(),
                shell=False,
                timeout=_GIT_DISCOVERY_TIMEOUT.total_seconds(),
            )
            if git is not None
            else None
        )
    except OSError, subprocess.TimeoutExpired:
        completed = None
    if completed is not None and completed.returncode == 0:
        found = []
        for raw in completed.stdout.split(b"\0"):
            if not raw:
                continue
            path = root / raw.decode("utf-8", errors="surrogateescape")
            relative = path.relative_to(root)
            if (
                not any(part in _SKIP_DIRS for part in relative.parts)
                and not _is_skill_artifact(relative)
                and not path.is_symlink()
                and path.is_file()
            ):
                found.append(path)
        return tuple(sorted(found))

    found: list[Path] = []
    for parent, directories, names in os.walk(root):
        here = Path(parent)
        directories[:] = sorted(
            name
            for name in directories
            if name not in _SKIP_DIRS and not (here.name in _SKILL_ARTIFACT_ROOTS and name == "skills")
        )
        found.extend(path for name in sorted(names) if not (path := here / name).is_symlink() and path.is_file())
    return tuple(found)


def _is_skill_artifact(path: Path) -> bool:
    return any(root in _SKILL_ARTIFACT_ROOTS and child == "skills" for root, child in pairwise(path.parts))


def _read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""


def parse_pins(text: str) -> dict[str, str]:
    return {match.group("name"): match.group("version") for match in _PIN.finditer(text)}


def parse_revs(text: str) -> list[str]:
    return [match.group("rev") for match in _REV.finditer(text)]
