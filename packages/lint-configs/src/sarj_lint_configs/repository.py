"""Configurable repository maintenance gates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed-argument git queries are required repository inputs.
import tomllib
from typing import Final

import yaml

from .manifest import as_table, list_field, table_field, text_field


_CONFLICT_RE: Final = re.compile(r"^(?:<<<<<<< |>>>>>>> |\|\|\|\|\|\|\| )", re.MULTILINE)
_TEST_COMMAND_RE: Final = re.compile(r"(?:npm test|pytest|make (?:verify|test)\b)")
_PYPROJECT_VERSION_RE: Final = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)
_ESLINT_RULE_RE: Final = re.compile(r'^\s*"([a-z0-9-]+)":', re.MULTILINE)
_ESLINT_MAP_RE: Final = re.compile(r"^const rules = \{$(?P<body>.*?)^\};$", re.MULTILINE | re.DOTALL)
_MARKDOWN_LOCATIONS: Final = (
    "README.md",
    "CLAUDE.md",
    "packages/*/README.md",
    "plugins/*/commands/*.md",
    "plugins/*/skills/*/SKILL.md",
    "plugins/*/README.md",
)


@dataclass(frozen=True, slots=True)
class Finding:
    check: str
    where: str
    message: str

    def render(self) -> str:
        return f"error[{self.check}]: {self.where}: {self.message}"


@dataclass(frozen=True, slots=True)
class FilenameRule:
    glob: str
    pattern: re.Pattern[str]
    label: str


@dataclass(frozen=True, slots=True)
class RuleFamily:
    name: str
    source: str
    tests: str
    registry: str
    extension: str
    test_pattern: str
    registry_pattern: str


@dataclass(frozen=True, slots=True)
class ConfigReference:
    glob: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class VersionReference:
    path: str
    format: str
    version: str
    selector: str


@dataclass(frozen=True, slots=True)
class RepositoryPolicy:
    distinctive: tuple[str, ...]
    contextual: tuple[str, ...]
    private_excludes: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    filename_rules: tuple[FilenameRule, ...]
    rule_families: tuple[RuleFamily, ...]
    config_references: tuple[ConfigReference, ...]
    version_references: tuple[VersionReference, ...]
    canonical_config_dir: str
    versions: Mapping[str, tuple[str, ...]]
    known_manifests: tuple[str, ...]
    known_locks: tuple[str, ...]


def load_policy(root: Path) -> RepositoryPolicy:
    path = root / ".sarj-standards.toml"
    try:
        raw: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f"cannot load repository policy from {path}: {exc}"
        raise ValueError(msg) from exc
    repository = table_field(as_table(raw), "repository")
    private = table_field(repository, "private_refs")
    coverage = table_field(repository, "version_coverage")
    return RepositoryPolicy(
        distinctive=_strings(private, "distinctive"),
        contextual=_strings(private, "contextual"),
        private_excludes=_strings(private, "exclude"),
        forbidden_paths=_strings(repository, "forbidden_paths"),
        filename_rules=tuple(_filename_rules(list_field(repository, "filename_rules"))),
        rule_families=tuple(_rule_families(list_field(repository, "rule_families"))),
        config_references=tuple(_config_references(list_field(repository, "config_references"))),
        version_references=tuple(_version_references(list_field(repository, "version_references"))),
        canonical_config_dir=text_field(repository, "canonical_config_dir") or "",
        versions={key: _string_values(value) for key, value in table_field(repository, "versions").items()},
        known_manifests=_strings(coverage, "manifests"),
        known_locks=_strings(coverage, "locks"),
    )


def check(root: Path, *, selected: frozenset[str] = frozenset(), commits: str | None = None) -> list[Finding]:
    policy = load_policy(root)
    checks = {
        "ci-history": lambda: check_ci_history(root),
        "file-conventions": lambda: check_file_conventions(root, policy),
        "private-refs": lambda: check_private_refs(root, policy, commits=commits),
        "versions": lambda: check_versions(root, policy),
    }
    unknown = selected.difference(checks)
    if unknown:
        msg = f"unknown repository check(s): {', '.join(sorted(unknown))}"
        raise ValueError(msg)
    findings: list[Finding] = []
    for name, checker in checks.items():
        if not selected or name in selected:
            findings.extend(checker())
    return sorted(findings, key=lambda item: (item.check, item.where, item.message))


def check_private_refs(root: Path, policy: RepositoryPolicy, *, commits: str | None) -> list[Finding]:
    distinctive = _alternation(policy.distinctive)
    contextual = _alternation(policy.contextual)
    broad = re.compile(rf"(^|[^A-Za-z0-9])(?:{distinctive})(?:[^A-Za-z0-9]|$)", re.IGNORECASE)
    scoped = re.compile(
        rf"(^|[^A-Za-z0-9])(?:{contextual})(?:/[A-Za-z0-9_.]|'s[^A-Za-z0-9]|'\s)|"
        rf"^\s*\|\s*(?:{contextual})\s*\|",
        re.IGNORECASE | re.MULTILINE,
    )
    findings: list[Finding] = []
    for relative in _tracked(root):
        if any(fnmatch(relative, pattern) for pattern in policy.private_excludes):
            continue
        text = _read_text(root / relative)
        if broad.search(text) or scoped.search(text):
            findings.append(Finding("private-refs", relative, "private repository or client reference"))
        if _CONFLICT_RE.search(text):
            findings.append(Finding("private-refs", relative, "unresolved conflict marker"))
    if commits:
        completed = _git(root, "log", "--format=%h %s%n%b", commits, check=False)
        if completed.returncode != 0:
            findings.append(Finding("private-refs", commits, "commit range does not resolve; fetch full history"))
        elif broad.search(completed.stdout) or scoped.search(completed.stdout) or _CONFLICT_RE.search(completed.stdout):
            findings.append(Finding("private-refs", commits, "private reference or conflict marker in commit message"))
    return findings


def check_ci_history(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        try:
            document: object = yaml.safe_load(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
        except (OSError, yaml.YAMLError) as exc:
            findings.append(Finding("ci-history", str(path.relative_to(root)), f"invalid workflow YAML: {exc}"))
            continue
        jobs = table_field(as_table(document), "jobs")
        for job_name, raw_job in jobs.items():
            job = as_table(raw_job)
            steps = list_field(job, "steps")
            runs_tests = any(_TEST_COMMAND_RE.search(str(as_table(step).get("run", ""))) for step in steps)
            if not runs_tests:
                continue
            full_history = any(_is_full_checkout(as_table(step)) for step in steps)
            if not full_history:
                relative = path.relative_to(root)
                findings.append(
                    Finding("ci-history", f"{relative}:{job_name}", "test job needs checkout fetch-depth: 0")
                )
    return findings


def check_file_conventions(root: Path, policy: RepositoryPolicy) -> list[Finding]:
    tracked = _tracked(root)
    findings = [
        Finding("file-conventions", relative, "path is forbidden by repository policy")
        for relative in tracked
        if any(fnmatch(relative, pattern) for pattern in policy.forbidden_paths)
    ]
    for rule in policy.filename_rules:
        findings.extend(
            Finding("file-conventions", relative, rule.label)
            for relative in tracked
            if fnmatch(relative, rule.glob) and not rule.pattern.fullmatch(Path(relative).name)
        )
    findings.extend(_check_markdown_locations(tracked))
    for family in policy.rule_families:
        findings.extend(_check_rule_family(root, family))
    findings.extend(_check_config_copies(root, tracked, policy.canonical_config_dir))
    findings.extend(_check_config_references(root, tracked, policy))
    return findings


def check_versions(root: Path, policy: RepositoryPolicy) -> list[Finding]:
    versions = {name: _manifest_version(root / paths[0]) for name, paths in policy.versions.items() if paths}
    findings: list[Finding] = []
    for name, paths in policy.versions.items():
        expected = versions.get(name)
        for relative in paths:
            actual = _manifest_version(root / relative)
            if expected is None or actual is None:
                findings.append(Finding("versions", relative, f"cannot read {name} version"))
            elif actual != expected:
                findings.append(Finding("versions", relative, f"version {actual} does not match {expected}"))
    for reference in policy.version_references:
        expected = versions.get(reference.version)
        actual = _reference_version(root / reference.path, reference)
        if expected != actual:
            findings.append(
                Finding(
                    "versions",
                    reference.path,
                    f"{reference.selector} is {actual or 'missing'}, expected {expected}",
                )
            )
    findings.extend(_check_version_coverage(root, policy))
    return findings


def _reference_version(path: Path, reference: VersionReference) -> str | None:
    if reference.format == "uv-lock":
        return _uv_lock_version(path, reference.selector)
    if reference.format == "exact-pin":
        match = re.search(rf'"{re.escape(reference.selector)}==([^"]+)"', _read_text(path))
        return match.group(1) if match else None
    if reference.format != "json-pointer":
        msg = f"unknown version reference format: {reference.format}"
        raise ValueError(msg)
    try:
        document: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except OSError, json.JSONDecodeError:
        return None
    value = document
    for token in reference.selector.removeprefix("/").split("/"):
        value = as_table(value).get(token.replace("~1", "/").replace("~0", "~"))
    return value if isinstance(value, str) else None


def _check_markdown_locations(tracked: Sequence[str]) -> list[Finding]:
    return [
        Finding("file-conventions", path, "Markdown is outside the maintained locations")
        for path in tracked
        if path.endswith(".md") and not any(fnmatch(path, pattern) for pattern in _MARKDOWN_LOCATIONS)
    ]


def _check_rule_family(root: Path, family: RuleFamily) -> list[Finding]:
    source = root / family.source
    tests = root / family.tests
    registry = _read_text(root / family.registry)
    findings: list[Finding] = []
    for path in sorted(source.glob(f"*.{family.extension}")):
        if path.stem.startswith("_"):
            continue
        test = tests / family.test_pattern.format(name=path.stem)
        if not test.is_file():
            findings.append(
                Finding("file-conventions", str(path.relative_to(root)), f"missing {test.relative_to(root)}")
            )
        if family.registry_pattern.format(name=path.stem) not in registry:
            findings.append(
                Finding("file-conventions", str(path.relative_to(root)), "rule is absent from its registry")
            )
    test_glob = family.test_pattern.format(name="*")
    prefix, suffix = family.test_pattern.split("{name}", maxsplit=1)
    for path in sorted(tests.glob(test_glob)):
        name = path.name.removeprefix(prefix).removesuffix(suffix)
        if (
            not (source / f"{name}.{family.extension}").is_file()
            and not (source / f"_{name}.{family.extension}").is_file()
        ):
            findings.append(Finding("file-conventions", str(path.relative_to(root)), "test names no rule or helper"))
    return findings


def _check_config_copies(root: Path, tracked: Sequence[str], canonical_dir: str) -> list[Finding]:
    canonical_root = root / canonical_dir
    hashes = {_digest(path): path for path in canonical_root.iterdir() if path.is_file()}
    findings: list[Finding] = []
    for relative in tracked:
        path = root / relative
        if path.is_symlink() or not path.is_file() or canonical_root in path.parents:
            continue
        original = hashes.get(_digest(path))
        if original is not None:
            findings.append(
                Finding(
                    "file-conventions",
                    relative,
                    f"duplicates {original.relative_to(root)}; use a symlink or synced config",
                )
            )
    return findings


def _is_full_checkout(step: Mapping[str, object]) -> bool:
    if step.get("uses") is None or not str(step["uses"]).startswith("actions/checkout@"):
        return False
    depth = table_field(step, "with").get("fetch-depth")
    return depth in {0, "0"}


def _manifest_version(path: Path) -> str | None:
    if path.suffix == ".json":
        try:
            value: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
        except OSError, json.JSONDecodeError:
            return None
        return text_field(as_table(value), "version")
    match = _PYPROJECT_VERSION_RE.search(_read_text(path)[:2000])
    return match.group(1) if match else None


def _uv_lock_version(path: Path, distribution: str) -> str | None:
    try:
        document: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return None
    packages = list_field(as_table(document), "package")
    for raw in packages:
        package = as_table(raw)
        if text_field(package, "name") == distribution:
            return text_field(package, "version")
    return None


def _tracked(root: Path) -> tuple[str, ...]:
    output = _git(root, "ls-files", "-z").stdout
    return tuple(path for path in output.split("\0") if path and (root / path).exists())


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git")
    if executable is None:
        msg = "git is required for repository checks"
        raise OSError(msg)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [executable, *args],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
    )


def _read_text(path: Path) -> str:
    content = path.read_bytes() if path.is_file() else b""
    return "" if b"\0" in content else content.decode("utf-8", errors="replace")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _alternation(values: Sequence[str]) -> str:
    if not values:
        msg = "repository private-reference policy must not be empty"
        raise ValueError(msg)
    return "|".join(f"(?:{value})" for value in values)


def _strings(table: Mapping[str, object], key: str) -> tuple[str, ...]:
    return _string_values(list_field(table, key))


def _string_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items: list[object] = value  # pyright: ignore[reportUnknownVariableType]
    strings = tuple(item for item in items if isinstance(item, str))
    return strings if len(strings) == len(items) else ()


def _filename_rules(values: Iterable[object]) -> Iterable[FilenameRule]:
    for value in values:
        table = as_table(value)
        glob = text_field(table, "glob")
        pattern = text_field(table, "pattern")
        label = text_field(table, "label")
        if glob and pattern and label:
            yield FilenameRule(glob, re.compile(pattern), label)


def _rule_families(values: Iterable[object]) -> Iterable[RuleFamily]:
    for value in values:
        table = as_table(value)
        fields = tuple(
            text_field(table, key)
            for key in ("name", "source", "tests", "registry", "extension", "test_pattern", "registry_pattern")
        )
        if all(fields):
            name, source, tests, registry, extension, test_pattern, registry_pattern = fields
            yield RuleFamily(
                name or "",
                source or "",
                tests or "",
                registry or "",
                extension or "",
                test_pattern or "",
                registry_pattern or "",
            )


def _config_references(values: Iterable[object]) -> Iterable[ConfigReference]:
    for value in values:
        table = as_table(value)
        glob = text_field(table, "glob")
        pattern = text_field(table, "pattern")
        if glob and pattern:
            yield ConfigReference(glob, re.compile(pattern, re.MULTILINE))


def _version_references(values: Iterable[object]) -> Iterable[VersionReference]:
    for value in values:
        table = as_table(value)
        fields = tuple(text_field(table, key) for key in ("path", "format", "version", "selector"))
        if all(fields):
            path, format_name, version, selector = fields
            yield VersionReference(path or "", format_name or "", version or "", selector or "")


def _check_config_references(root: Path, tracked: Sequence[str], policy: RepositoryPolicy) -> list[Finding]:
    canonical = (root / policy.canonical_config_dir).resolve()
    findings: list[Finding] = []
    for rule in policy.config_references:
        for relative in tracked:
            if not fnmatch(relative, rule.glob):
                continue
            match = rule.pattern.search(_read_text(root / relative))
            if match is None:
                continue
            reference = match.group(1)
            target = root / Path(relative).parent / reference
            if not target.exists():
                findings.append(Finding("file-conventions", relative, f"extended config does not exist: {reference}"))
            elif canonical not in target.resolve().parents:
                findings.append(
                    Finding("file-conventions", relative, f"extended config is outside {policy.canonical_config_dir}")
                )
    return findings


def _check_version_coverage(root: Path, policy: RepositoryPolicy) -> list[Finding]:
    known_manifests = set(policy.known_manifests)
    known_locks = set(policy.known_locks)
    tracked = _tracked(root)
    manifests = {
        path
        for path in tracked
        if fnmatch(path, "packages/*/pyproject.toml") or fnmatch(path, "packages/*/package.json")
    }
    locks = {path for path in tracked if path.endswith(("uv.lock", "package-lock.json"))}
    return [
        Finding("versions", path, "versioned package manifest is absent from version policy")
        for path in sorted(manifests - known_manifests)
    ] + [Finding("versions", path, "lockfile is absent from version policy") for path in sorted(locks - known_locks)]


def eslint_rule_names(root: Path) -> list[str]:
    source = _read_text(root / "packages/typescript/src/index.ts")
    body = _ESLINT_MAP_RE.search(source)
    if body is None:
        return []
    return sorted(_ESLINT_RULE_RE.findall(body.group("body")))
