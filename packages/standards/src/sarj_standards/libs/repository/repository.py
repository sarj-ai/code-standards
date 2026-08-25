from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed-argument git queries are required repository inputs.
import tomllib
from typing import Final

import yaml

from sarj_standards.libs.adoption.manifest import as_table, list_field, table_field, text_field


_CONFLICT_RE: Final = re.compile(r"^(?:<<<<<<< |>>>>>>> |\|\|\|\|\|\|\| )", re.MULTILINE)
_GITHUB_MERGE_SUBJECT_RE: Final = re.compile(r"^Merge pull request #[1-9][0-9]* from [A-Za-z0-9_.-]+/[A-Za-z0-9._/-]+$")
_PRIVATE_REFS_FILE: Final = ".sarj-private-refs.toml"
_TEST_COMMAND_RE: Final = re.compile(r"(?:npm test|pytest|make (?:verify|test)\b)")
_PYPROJECT_VERSION_RE: Final = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)
_ESLINT_RULE_RE: Final = re.compile(r'^\s*"([a-z0-9-]+)":', re.MULTILINE)
_ESLINT_MAP_RE: Final = re.compile(r"^const (?:RULES|rules) = \{$(?P<body>.*?)^\};$", re.MULTILINE | re.DOTALL)
_MARKDOWN_LOCATIONS: Final = (
    ".github/SECURITY.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "packages/*/README.md",
    "plugins/*/commands/*.md",
    "plugins/*/skills/*/SKILL.md",
    "plugins/*/skills/*/references/*.md",
    "plugins/*/README.md",
    "docs/audits/*.md",
)
_MANAGED_ROOT_CONFIGS: Final = (
    (".ruff-strict.toml", "ruff.strict.toml"),
    (".pyright-strict.json", "pyright.strict.json"),
    ("pyright.strict.json", "pyright.strict.json"),
    (".basedpyright-strict.json", "basedpyright.strict.json"),
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


def load_policy(root: Path, *, private_refs_path: Path | None = None) -> RepositoryPolicy:
    path = root / ".sarj-standards.toml"
    try:
        raw: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f"cannot load repository policy from {path}: {exc}"
        raise ValueError(msg) from exc
    repository = _table(as_table(raw), "repository", required=True)
    _known_keys(
        repository,
        frozenset(
            {
                "canonical_config_dir",
                "config_references",
                "filename_rules",
                "forbidden_paths",
                "private_refs",
                "rule_families",
                "version_coverage",
                "version_references",
                "versions",
            }
        ),
        "repository",
    )
    private = _private_refs(root, _table(repository, "private_refs"), private_refs_path)
    _known_keys(
        private,
        frozenset({"contextual", "distinctive", "exclude"}),
        "private_refs",
    )
    coverage = _table(repository, "version_coverage")
    _known_keys(coverage, frozenset({"locks", "manifests"}), "version_coverage")
    return RepositoryPolicy(
        distinctive=_strings(private, "distinctive"),
        contextual=_strings(private, "contextual"),
        private_excludes=_strings(private, "exclude"),
        forbidden_paths=_strings(repository, "forbidden_paths"),
        filename_rules=tuple(_filename_rules(_objects(repository, "filename_rules"))),
        rule_families=tuple(_rule_families(_objects(repository, "rule_families"))),
        config_references=tuple(_config_references(_objects(repository, "config_references"))),
        version_references=tuple(_version_references(_objects(repository, "version_references"))),
        canonical_config_dir=_optional_text(repository, "canonical_config_dir"),
        versions={
            key: _string_values(value, f"repository.versions.{key}")
            for key, value in _table(repository, "versions").items()
        },
        known_manifests=_strings(coverage, "manifests"),
        known_locks=_strings(coverage, "locks"),
    )


def check(
    root: Path,
    *,
    selected: frozenset[str] = frozenset(),
    commits: str | None = None,
    policy_root: Path | None = None,
    private_refs_path: Path | None = None,
) -> list[Finding]:
    if policy_root is not None and policy_root.resolve() != root.resolve() and selected != frozenset({"private-refs"}):
        msg = "a separate policy root is restricted to the private-refs check"
        raise ValueError(msg)
    policy = load_policy(policy_root or root, private_refs_path=private_refs_path)
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
    defaults = frozenset(checks).difference({"private-refs"})
    for name, checker in checks.items():
        if name in (selected or defaults):
            findings.extend(checker())
    return sorted(findings, key=lambda item: (item.check, item.where, item.message))


def check_private_refs(root: Path, policy: RepositoryPolicy, *, commits: str | None) -> list[Finding]:
    if not any((policy.distinctive, policy.contextual)):
        msg = "private-reference policy is unavailable"
        raise ValueError(msg)
    broad = _broad_private_pattern(policy.distinctive)
    scoped = _scoped_private_pattern(policy.contextual)
    findings: list[Finding] = []
    for relative in _tracked(root):
        findings.extend(_private_text_findings(relative, relative, broad, scoped))
        if any(fnmatch(relative, pattern) for pattern in policy.private_excludes):
            continue
        text = _tracked_text(root, relative)
        findings.extend(_private_text_findings(relative, text, broad, scoped))
    if commits:
        revisions = _git(root, "rev-list", "--reverse", commits, check=False)
        if revisions.returncode != 0:
            findings.append(Finding("private-refs", commits, "commit range does not resolve; fetch full history"))
        else:
            findings.extend(_commit_findings(root, revisions.stdout.splitlines(), policy, broad, scoped))
    return list(dict.fromkeys(findings))


def _commit_findings(
    root: Path,
    revisions: Sequence[str],
    policy: RepositoryPolicy,
    broad: re.Pattern[str] | None,
    scoped: re.Pattern[str] | None,
) -> list[Finding]:
    findings: list[Finding] = []
    for revision in revisions:
        message = _git(root, "show", "--quiet", "--format=%H%n%s%n%b", revision).stdout
        parents = _git(root, "show", "--quiet", "--format=%P", revision).stdout.split()
        if len(parents) > 1:
            message = _without_generated_merge_subject(message)
        if _matches_private_ref(message, broad, scoped) or _CONFLICT_RE.search(message):
            findings.append(Finding("private-refs", revision, "private reference or conflict marker in commit message"))
        changed = _git(
            root,
            "diff-tree",
            "--root",
            "-m",
            "-r",
            "--no-commit-id",
            "--no-renames",
            "--name-only",
            "-z",
            revision,
        ).stdout
        for relative in (path for path in changed.split("\0") if path):
            where = f"{revision}:{relative}"
            findings.extend(_private_text_findings(where, relative, broad, scoped))
            if any(fnmatch(relative, pattern) for pattern in policy.private_excludes):
                continue
            text = _revision_text(root, revision, relative)
            if text is None:
                continue
            findings.extend(_private_text_findings(where, text, broad, scoped))
    return findings


def _without_generated_merge_subject(message: str) -> str:
    commit_hash, separator, remainder = message.partition("\n")
    subject, body_separator, body = remainder.partition("\n")
    if separator and _GITHUB_MERGE_SUBJECT_RE.fullmatch(subject):
        return f"{commit_hash}\n{body}" if body_separator else commit_hash
    return message


def _private_text_findings(
    where: str,
    text: str,
    broad: re.Pattern[str] | None,
    scoped: re.Pattern[str] | None,
) -> list[Finding]:
    findings: list[Finding] = []
    if _matches_private_ref(text, broad, scoped):
        findings.append(Finding("private-refs", where, "private repository or client reference"))
    if _CONFLICT_RE.search(text):
        findings.append(Finding("private-refs", where, "unresolved conflict marker"))
    return findings


def _revision_text(root: Path, revision: str, relative: str) -> str | None:
    entry = _git(root, "ls-tree", "-z", revision, "--", relative).stdout.rstrip("\0")
    if not entry:
        return None
    metadata, separator, _ = entry.partition("\t")
    if not separator:
        return None
    match metadata.split():
        case [_, "blob", object_id]:
            pass
        case _:
            return None
    text = _git(root, "cat-file", "blob", object_id).stdout
    return "" if "\0" in text else text


def _private_refs(
    root: Path,
    public: Mapping[str, object],
    private_refs_path: Path | None,
) -> Mapping[str, object]:
    local_path = private_refs_path or root / _PRIVATE_REFS_FILE
    if local_path.is_file():
        try:
            parsed: object = tomllib.loads(local_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            msg = f"cannot load private-reference policy from {local_path}: {exc}"
            raise ValueError(msg) from exc
        return {**public, **_table(as_table(parsed), "private_refs", required=True)}
    return public


def _broad_private_pattern(literals: Sequence[str]) -> re.Pattern[str] | None:
    if not literals:
        return None
    alternatives = _private_alternation(literals)
    return re.compile(rf"(^|[^A-Za-z0-9])(?:{alternatives})(?:[^A-Za-z0-9]|$)", re.IGNORECASE)


def _scoped_private_pattern(literals: Sequence[str]) -> re.Pattern[str] | None:
    if not literals:
        return None
    alternatives = _private_alternation(literals)
    return re.compile(
        rf"(^|[^A-Za-z0-9])(?:{alternatives})(?:/[A-Za-z0-9_.]|'s[^A-Za-z0-9]|'\s)|"
        rf"^\s*\|\s*(?:{alternatives})\s*\|",
        re.IGNORECASE | re.MULTILINE,
    )


def _matches_private_ref(
    text: str,
    broad: re.Pattern[str] | None,
    scoped: re.Pattern[str] | None,
) -> bool:
    return bool((broad and broad.search(text)) or (scoped and scoped.search(text)))


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
        managed_source = _managed_config_source(root, path, canonical_root)
        if managed_source is not None:
            if _digest(path) != _digest(managed_source):
                findings.append(
                    Finding(
                        "file-conventions",
                        relative,
                        f"generated config drifted from {managed_source.relative_to(root)}; run `code-standards setup`",
                    )
                )
            continue
        original = hashes.get(_digest(path))
        if original is not None:
            findings.append(
                Finding(
                    "file-conventions",
                    relative,
                    f"duplicates {original.relative_to(root)}; remove the unmanaged copy",
                )
            )
    return findings


def _managed_config_source(root: Path, path: Path, canonical_root: Path) -> Path | None:
    for destination, source in _MANAGED_ROOT_CONFIGS:
        candidate = canonical_root / source
        if path == root / destination and candidate.is_file():
            return candidate
    return None


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
    return tuple(path for path in output.split("\0") if path)


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git")
    if executable is None:
        msg = "git is required for repository checks"
        raise OSError(msg)
    environment = os.environ.copy()  # ruff: ignore[banned-api] -- preserve user Git configuration, but not a hook's repository binding.
    local_names = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [executable, "rev-parse", "--local-env-vars"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for name in local_names:
        environment.pop(name, None)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [executable, *args],
        cwd=root,
        check=check,
        capture_output=True,
        env=environment,
        errors="replace",
        text=True,
    )


def _read_text(path: Path) -> str:
    content = path.read_bytes() if path.is_file() else b""
    return "" if b"\0" in content else content.decode("utf-8", errors="replace")


def _tracked_text(root: Path, relative: str) -> str:
    path = root / relative
    if path.is_symlink():
        return path.readlink().as_posix()
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and not resolved.is_relative_to(resolved_root):
        msg = f"tracked path escapes repository: {relative}"
        raise ValueError(msg)
    return _read_text(resolved)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _private_alternation(literals: Sequence[str]) -> str:
    return "|".join(map(re.escape, literals))


def _strings(table: Mapping[str, object], key: str) -> tuple[str, ...]:
    if key not in table:
        return ()
    return _string_values(table[key], key)


def _string_values(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        msg = f"{label} must be a list of strings"
        raise TypeError(msg)
    items: list[object] = value  # pyright: ignore[reportUnknownVariableType]
    strings = tuple(item for item in items if isinstance(item, str))
    if len(strings) != len(items):
        msg = f"{label} must contain only strings"
        raise ValueError(msg)
    return strings


def _objects(table: Mapping[str, object], key: str) -> list[object]:
    if key not in table:
        return []
    value = table[key]
    if not isinstance(value, list):
        msg = f"repository.{key} must be an array of tables"
        raise TypeError(msg)
    return value  # pyright: ignore[reportUnknownVariableType]


def _table(table: Mapping[str, object], key: str, *, required: bool = False) -> Mapping[str, object]:
    if key not in table:
        if required:
            msg = f"missing [{key}] table"
            raise ValueError(msg)
        return {}
    value = table[key]
    if not isinstance(value, dict):
        msg = f"{key} must be a table"
        raise TypeError(msg)
    return as_table(value)  # pyright: ignore[reportUnknownArgumentType]


def _known_keys(table: Mapping[str, object], allowed: frozenset[str], label: str) -> None:
    unknown = set(table).difference(allowed)
    if unknown:
        msg = f"unknown {label} field(s): {', '.join(sorted(unknown))}"
        raise ValueError(msg)


def _optional_text(table: Mapping[str, object], key: str) -> str:
    if key not in table:
        return ""
    value = table[key]
    if not isinstance(value, str):
        msg = f"repository.{key} must be a string"
        raise TypeError(msg)
    return value


def _required_texts(table: Mapping[str, object], keys: tuple[str, ...], label: str) -> tuple[str, ...]:
    values = tuple(text_field(table, key) for key in keys)
    missing = tuple(key for key, value in zip(keys, values, strict=True) if not value)
    if missing:
        msg = f"{label} requires: {', '.join(missing)}"
        raise ValueError(msg)
    return tuple(value or "" for value in values)


def _filename_rules(values: Iterable[object]) -> Iterable[FilenameRule]:
    for value in values:
        table = as_table(value)
        _known_keys(table, frozenset({"glob", "label", "pattern"}), "filename rule")
        glob, pattern, label = _required_texts(table, ("glob", "pattern", "label"), "filename rule")
        yield FilenameRule(glob, _compile_policy_regex(pattern, "filename rule"), label)


def _rule_families(values: Iterable[object]) -> Iterable[RuleFamily]:
    for value in values:
        table = as_table(value)
        _known_keys(
            table,
            frozenset({"extension", "name", "registry", "registry_pattern", "source", "test_pattern", "tests"}),
            "rule family",
        )
        fields = _required_texts(
            table,
            ("name", "source", "tests", "registry", "extension", "test_pattern", "registry_pattern"),
            "rule family",
        )
        name, source, tests, registry, extension, test_pattern, registry_pattern = fields
        yield RuleFamily(name, source, tests, registry, extension, test_pattern, registry_pattern)


def _config_references(values: Iterable[object]) -> Iterable[ConfigReference]:
    for value in values:
        table = as_table(value)
        _known_keys(table, frozenset({"glob", "pattern"}), "config reference")
        glob, pattern = _required_texts(table, ("glob", "pattern"), "config reference")
        yield ConfigReference(glob, _compile_policy_regex(pattern, "config reference", re.MULTILINE))


def _version_references(values: Iterable[object]) -> Iterable[VersionReference]:
    for value in values:
        table = as_table(value)
        _known_keys(table, frozenset({"format", "path", "selector", "version"}), "version reference")
        path, format_name, version, selector = _required_texts(
            table, ("path", "format", "version", "selector"), "version reference"
        )
        yield VersionReference(path, format_name, version, selector)


def _compile_policy_regex(pattern: str, label: str, flags: re.RegexFlag = re.NOFLAG) -> re.Pattern[str]:
    try:
        return re.compile(pattern, flags)
    except re.PatternError as exc:
        msg = f"invalid {label} regex: {pattern}"
        raise ValueError(msg) from exc


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
            elif (
                canonical not in target.resolve().parents
                and _managed_config_source(root, target.resolve(), canonical) is None
            ):
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
