"""Find every place a consumer repo states a Sarj version, and prove they agree."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatch
import json
import os
from pathlib import Path
import re
import tomllib
from typing import TYPE_CHECKING, Final, NamedTuple

from sarj_lint_configs._meta import CONFIGS_DIR
from sarj_lint_configs.libs.repository import ledger

from . import manifest, packagemanager


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence


class Level(StrEnum):
    """How much a finding matters."""

    OK = "ok"
    WARN = "warn"
    DRIFT = "drift"


@dataclass(frozen=True)
class Finding:
    """One checked pin site and its verdict."""

    level: Level
    where: str
    detail: str
    id: str = "doctor.unknown"
    remediation: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        """Return a stable machine-readable representation."""
        return {
            "id": self.id,
            "level": self.level.value,
            "where": self.where,
            "detail": self.detail,
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class VersionPinUpdate:
    """One pin-bearing file rewritten to the installed compatibility bundle."""

    path: Path
    contents: str
    packages: tuple[str, ...]


class VersionPinRewrite(NamedTuple):
    """Updated text and the packages whose pins changed."""

    contents: str
    packages: tuple[str, ...]


#: `sarj-python-lint==0.25.0`, `"sarj-lint-configs>=0.9"`, `--from sarj-sql-lint==1.2.3`.
_PIN = re.compile(
    r"(?P<name>sarj-(?:python|sql|iac)-lint|sarj-lint-configs)\s*(?P<op>==|>=|~=)\s*(?P<version>[0-9][0-9A-Za-z.\-]*)"
)

#: `rev: python-v0.19.0`, `rev: "lint-configs-v0.10.0"`, `rev: 9d073e83b2...`.
#:
#: Raw commit pins can silently become stale, so report them as unverifiable.
_REV = re.compile(r"""rev:\s*['"]?(?P<rev>[a-z-]+-v[0-9][0-9A-Za-z.\-]*|[0-9a-f]{7,40})['"]?""")

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
    {".pyright-strict.json", "pyright.strict.json", "pyrightconfig.json", "pyrightconfig.jsonc", "pyproject.toml"}
)
_PYRIGHT_REPORT_DEPRECATED = re.compile(
    r"^\s*[\"']?reportDeprecated[\"']?\s*(?::|=)\s*(?P<value>[^,#/\n]+)", re.MULTILINE
)
_RUFF_CONFIG_NAMES: Final = frozenset({".ruff.toml", "ruff.toml", "pyproject.toml"})
_RUFF_REPLACEMENT_KEYS: Final = frozenset({"ignore", "select"})
_CONFIG_TARGETS: Final = {
    "ruff": ("ruff.strict.toml", "ruff.application.toml", ".ruff-strict.toml", "python"),
    "pyright": ("pyright.strict.json", "pyright.strict.json", ".pyright-strict.json", "python"),
    "eslint": ("eslint.strict.mjs", "eslint.application.mjs", "eslint.strict.mjs", "typescript"),
    "markdownlint": ("markdownlint.strict.yaml", "markdownlint.strict.yaml", ".markdownlint.yaml", "root"),
    "taplo": ("taplo.strict.toml", "taplo.strict.toml", ".taplo.toml", "root"),
    "yamllint": ("yamllint.strict.yaml", "yamllint.strict.yaml", ".yamllint.yaml", "root"),
}

#: Where a rule identifier can be written: configs and suppression baselines, but
#: also ordinary source, because an `eslint-disable-next-line @sarj/<rule>` for a
#: rule that no longer exists is its own error under the shipped strict config's
#: `reportUnusedDisableDirectives: "error"`, and a `sarj-noqa: SARJnnn` comment
#: outlives the code it named.
_REFERENCE_SUFFIXES: Final = (
    ".cjs",
    ".cts",
    ".js",
    ".json",
    ".jsx",
    ".mjs",
    ".mts",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
)
_RULE_MAPPING_REFERENCE = re.compile(r"^\s*(?:-\s*)?(?:id|entry)\s*:\s*.*sarj", re.IGNORECASE)
_ESLINT_RULE_REFERENCE = re.compile(r"[\"']@sarj/[^\"']+[\"']\s*:")

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


def diagnose(root: Path) -> list[Finding]:
    """Check version pins and required policy settings under a repo root."""
    installed = manifest.installed_versions()
    exclusions = _doctor_exclusions(root)
    files = tuple(
        path
        for path in _walk(root)
        if not any(fnmatch(path.relative_to(root).as_posix(), pattern) for pattern in exclusions)
    )
    findings = [*_check_manifest(root)]
    findings.extend(_check_pin_files(root, files, installed))
    findings.extend(_check_precommit_revs(root, files))
    findings.extend(_check_eslint_plugin(root, files))
    findings.extend(check_retired_rules(root, files))
    findings.extend(check_pyright_deprecated(root, files))
    findings.extend(check_ruff_policy_authority(root, files))
    findings.extend(_check_adoption_wiring(root))
    return sorted(findings, key=lambda finding: (finding.where, finding.id, finding.detail))


def _doctor_exclusions(root: Path) -> tuple[str, ...]:
    """Read explicit fixture/generated-file exclusions without weakening defaults."""
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
    """Name every reference to a rule that no longer exists."""
    retired = ledger.load().retired
    if not retired:
        return
    for path in _candidate_files(files if files is not None else _walk(root), _REFERENCE_SUFFIXES):
        if path.name in {"rule-ledger.json", "code_ledger.json"}:
            continue
        text = _reference_text(path, _read(path))
        if "sarj" not in text.lower():
            continue
        for entry in retired:
            hits = len(entry.pattern.findall(text))
            if hits:
                where = f"{path.relative_to(root)}: {entry.id} x{hits}"
                yield Finding(
                    Level.DRIFT,
                    where,
                    entry.advice,
                    "doctor.rule.retired",
                    entry.advice,
                )


def _reference_text(path: Path, text: str) -> str:
    """Keep only syntactic rule-reference sites, never explanatory prose."""
    lowered = path.name.lower()
    if "baseline" in lowered:
        return text
    if "sarj" not in text.lower():
        return ""
    lines: list[str] = []
    for line in text.splitlines():
        normalized = line.lower()
        if "sarj" not in normalized:
            continue
        if (
            "sarj-noqa" in normalized
            or "eslint-disable" in normalized
            or "--rule" in normalized
            or _RULE_MAPPING_REFERENCE.search(line)
            or _ESLINT_RULE_REFERENCE.search(line)
        ):
            lines.append(line)
    return "\n".join(lines)


def check_pyright_deprecated(root: Path, files: Sequence[Path] | None = None) -> Iterator[Finding]:
    """Require consumers to keep Pyright's deprecated-API protection enabled."""
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
    """Require one Ruff authority and additive policy in extending configs."""
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


def _ruff_extend_reaches_canonical(root: Path, source: Path, extended: str) -> bool:
    """Follow a bounded Ruff config chain until the manifest-owned config."""
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
            "repair the named manifest field, then run `sarj-standards doctor` again",
        )
        return

    if found is None:
        yield Finding(
            Level.WARN,
            manifest.MANIFEST_NAME,
            "absent -- run `sarj-standards init` so the adopted version has one home",
            "doctor.manifest.absent",
            "run `sarj-standards init`",
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
        " -- run `sarj-standards upgrade` so every owned site moves together",
        "doctor.manifest.version",
        "run `sarj-standards upgrade`",
    )


def _check_pin_files(root: Path, files: Sequence[Path], installed: Mapping[str, str]) -> Iterator[Finding]:
    candidates = (path for path in files if _is_pin_site(path))
    for path in candidates:
        for match in _PIN.finditer(_read(path)):
            name = match.group("name")
            pinned = match.group("version")
            current = installed.get(name)
            where = f"{path.relative_to(root)}: {name}{match.group('op')}{pinned}"
            if current is None:
                yield Finding(
                    Level.WARN,
                    where,
                    f"{name} is not installed here, so the pin is unverified",
                    "doctor.version.unverified",
                )
            elif pinned == current:
                yield Finding(Level.OK, where, "matches the installed wheel", "doctor.version.pin")
            else:
                yield Finding(
                    Level.DRIFT,
                    where,
                    f"installed {name} is {current}",
                    "doctor.version.pin",
                    "run `sarj-standards upgrade`",
                )


def _is_pin_site(path: Path) -> bool:
    name = path.name.lower()
    if name in {"pyproject.toml", ".pre-commit-config.yaml", ".pre-commit-config.yml", "package.json"}:
        return True
    if name.startswith("requirements") and path.suffix.lower() in {"", ".in", ".txt"}:
        return True
    return ".github" in path.parts and "workflows" in path.parts and path.suffix.lower() in {".yml", ".yaml"}


def rewrite_version_pins(text: str, installed: Mapping[str, str]) -> VersionPinRewrite:
    """Refresh recognized Sarj pins without changing their operator or surrounding syntax."""
    changed: set[str] = set()

    def replacement(match: re.Match[str]) -> str:
        name = match.group("name")
        current = installed.get(name)
        if current is None or match.group("version") == current:
            return match.group(0)
        changed.add(name)
        relative_start = match.start("version") - match.start()
        relative_end = match.end("version") - match.start()
        return f"{match.group(0)[:relative_start]}{current}{match.group(0)[relative_end:]}"

    return VersionPinRewrite(_PIN.sub(replacement, text), tuple(sorted(changed)))


def plan_version_pin_updates(
    root: Path,
    installed: Mapping[str, str] | None = None,
) -> tuple[VersionPinUpdate, ...]:
    """Plan every doctor-owned pin migration while honoring fixture exclusions."""
    versions = manifest.installed_versions() if installed is None else installed
    exclusions = _doctor_exclusions(root)
    updates: list[VersionPinUpdate] = []
    for path in _walk(root):
        if not _is_pin_site(path):
            continue
        relative = path.relative_to(root).as_posix()
        if any(fnmatch(relative, pattern) for pattern in exclusions):
            continue
        contents, packages = rewrite_version_pins(_read(path), versions)
        if packages:
            updates.append(VersionPinUpdate(path, contents, packages))
    return tuple(updates)


def _check_precommit_revs(root: Path, files: Sequence[Path]) -> Iterator[Finding]:
    expected = manifest.expected_precommit_rev()
    for path in _candidate_files(files, (".yml", ".yaml")):
        text = _read(path)
        for block in _standards_repo_blocks(text):
            for match in _REV.finditer(block):
                yield from _precommit_rev_finding(root, path, match.group("rev"), expected)


def _standards_repo_blocks(text: str) -> Iterator[str]:
    """Yield only YAML list items for the sarj-ai/standards repository."""
    starts = list(re.finditer(r"(?m)^\s*-\s+repo:\s*[^\n]*sarj-ai/standards[^\n]*$", text))
    all_repos = list(re.finditer(r"(?m)^\s*-\s+repo:\s*", text))
    for start in starts:
        start_offset = start.start()
        end = next((offset for item in all_repos if (offset := item.start()) > start_offset), len(text))
        yield text[start.start() : end]


def _precommit_rev_finding(root: Path, path: Path, rev: str, expected: str | None) -> Iterator[Finding]:
    where = f"{path.relative_to(root)}: rev {rev}"
    if _SHA_REV.match(rev):
        yield Finding(
            Level.DRIFT,
            where,
            "pins the hooks to a commit, not a release, so no tool can tell"
            f" whether it is current -- pin {expected or 'the release tag'} instead",
            "doctor.precommit.rev",
            f"pin `{expected or 'the current release tag'}`",
        )
    elif expected is None:
        yield Finding(
            Level.WARN,
            where,
            "the hook package is not installed, so the rev is unverified",
            "doctor.precommit.rev-unverified",
        )
    elif rev == expected:
        yield Finding(Level.OK, where, "matches the installed hook package", "doctor.precommit.rev")
    else:
        yield Finding(
            Level.DRIFT,
            where,
            f"expected {expected} -- the hooks ship from the root package, whose version"
            " your sarj-lint-configs pin already fixes",
            "doctor.precommit.rev",
            f"pin `{expected}` or migrate to the local hook emitted by `sarj-standards upgrade`",
        )


def _check_eslint_plugin(root: Path, files: Sequence[Path]) -> Iterator[Finding]:
    # A missing peer manifest is a packaging defect and must fail loudly.
    floor = manifest.eslint_peers()[_ESLINT_PLUGIN]
    for path in _candidate_files(files, (".json",)):
        if path.name != "package.json":
            continue
        try:
            pinned = _package_json_pin(path)
        except json.JSONDecodeError as exc:
            yield Finding(
                Level.DRIFT,
                str(path.relative_to(root)),
                f"invalid package.json at line {exc.lineno}, column {exc.colno}: {exc.msg}",
                "doctor.package-json.invalid",
                "repair package.json, then rerun doctor",
            )
            continue
        if pinned is None or pinned.startswith(_LOCAL_SPECIFIERS):
            # Local specs represent unreleased checkouts, not version drift.
            continue
        where = f"{path.relative_to(root)}: {_ESLINT_PLUGIN}@{pinned}"
        if _without_range_operator(pinned) == floor:
            yield Finding(Level.OK, where, "matches the tested peer set", "doctor.eslint.plugin")
        else:
            yield Finding(
                Level.DRIFT,
                where,
                f"the bundled eslint.strict.mjs is tested against {floor};"
                " see `sarj-standards peers` for the whole resolvable set",
                "doctor.eslint.plugin",
                "run `sarj-standards upgrade`",
            )


def _check_adoption_wiring(root: Path) -> Iterator[Finding]:  # ruff: ignore[too-many-locals] -- validates each declared adoption site once
    """Prove that a declared adoption is present and actually connected."""
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
    if any(value is None for value in destinations.values()):
        return

    for name in adopted.configs:
        spec = _CONFIG_TARGETS.get(name)
        if spec is None:
            yield Finding(
                Level.DRIFT,
                manifest.MANIFEST_NAME,
                f"declares unknown config {name!r}",
                "doctor.config.unknown",
                "remove the unknown config or run `sarj-standards upgrade`",
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
                "run `sarj-standards upgrade`",
            )
        elif target.read_bytes() != expected.read_bytes():
            yield Finding(
                Level.DRIFT,
                str(target.relative_to(root)),
                f"declared {name} config differs from the installed bundle",
                "doctor.config.drift",
                "run `sarj-standards upgrade`",
            )
        else:
            yield Finding(Level.OK, str(target.relative_to(root)), f"{name} config is current", "doctor.config.current")

    python_root = destinations["python"]
    if python_root is not None:
        if "ruff" in adopted.configs:
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
                ".pyright-strict.json",
                "doctor.pyright.wiring",
                "set `extends` to `.pyright-strict.json`",
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
        yield from _check_eslint_peer_set(root, typescript_root)


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
        if target.name == "eslint.strict.mjs":
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
    except json.JSONDecodeError:
        return
    document = manifest.as_table(parsed)
    declared: dict[str, object] = {}
    for key in ("dependencies", "devDependencies"):
        declared.update(manifest.table_field(document, key))
    for name, expected in sorted(manifest.eslint_peers().items()):
        actual = declared.get(name)
        if isinstance(actual, str) and _without_range_operator(actual) == expected:
            continue
        yield Finding(
            Level.DRIFT,
            f"{package_json.relative_to(root)}: {name}",
            f"expected exact tested peer {expected}, found {actual!r}",
            "doctor.eslint.peer",
            "run `sarj-standards upgrade`",
        )

    client = packagemanager.detect(package_root)
    overrides = packagemanager.overrides_for(client)
    pnpm_workspace = package_root / "pnpm-workspace.yaml"
    if client is packagemanager.PackageManager.PNPM and pnpm_workspace.is_file():
        workspace_text = _read(pnpm_workspace)
        values = packagemanager.pnpm_workspace_values(workspace_text)
        if all(values.get(key) == str(value) for key, value in overrides.entries.items()):
            return
        yield Finding(
            Level.DRIFT,
            str(pnpm_workspace.relative_to(root)),
            "required pnpm peer override is missing",
            "doctor.eslint.override",
            "run `sarj-standards upgrade`",
        )
        return
    if package_root != typescript_root:
        package_json = package_root / "package.json"
        try:
            root_parsed: object = json.loads(  # pyright: ignore[reportAny] -- untyped stdlib boundary
                _read(package_json)
            )
        except json.JSONDecodeError:
            return
        document = manifest.as_table(root_parsed)
    table: Mapping[str, object] = document
    for key in overrides.key_path:
        table = manifest.table_field(table, key)
    if not _contains_expected_mapping(table, overrides.entries):
        yield Finding(
            Level.DRIFT,
            str(package_json.relative_to(root)),
            f"required {client} peer override is missing",
            "doctor.eslint.override",
            "run `sarj-standards upgrade`",
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


#: Single-version range operators in longest-first match order.
_RANGE_OPERATORS: Final = (">=", "<=", "~=", "==", "^", "~", ">", "<", "=", "v")


def _without_range_operator(pinned: str) -> str:
    """Remove at most one leading range operator from a version pin."""
    for operator in _RANGE_OPERATORS:
        if pinned.startswith(operator):
            return pinned[len(operator) :].strip()
    return pinned


def _package_json_pin(path: Path) -> str | None:
    parsed: object = json.loads(_read(path))  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; the shape is narrowed below
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
    """List a repo's files once, pruning the directories nothing is ever found in."""
    found: list[Path] = []
    for parent, directories, names in os.walk(root):
        directories[:] = sorted(name for name in directories if name not in _SKIP_DIRS)
        here = Path(parent)
        found.extend(path for name in sorted(names) if not (path := here / name).is_symlink() and path.is_file())
    return tuple(found)


def _read(path: Path) -> str:
    """Read a repository file while replacing invalid UTF-8 bytes."""
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""


def parse_pins(text: str) -> dict[str, str]:
    """Extract every Sarj version pin from a file's text."""
    return {match.group("name"): match.group("version") for match in _PIN.finditer(text)}


def parse_revs(text: str) -> list[str]:
    """Extract every pre-commit `rev:` tag from a file's text."""
    return [match.group("rev") for match in _REV.finditer(text)]
