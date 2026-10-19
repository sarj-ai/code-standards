from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO, Required, TextIO, TypedDict

from sarj_standards.api import AnalysisMode, TrustMode
from sarj_standards.libs.linting.external import ProcessRunner, UpstreamESLintRules
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.linting.runner import GroupedPaths
from sarj_standards.libs.release.process import ProcessRunner as ReleaseProcessRunner
from sarj_standards.libs.repository.repository import ConfigReference, FilenameRule, RuleFamily, VersionReference
from sarj_standards.libs.rules import RuleSelection, RuleSelector


class SubprocessCallOptions(TypedDict, total=False):
    cwd: str | Path | None
    check: bool
    capture_output: bool
    encoding: str | None
    errors: str | None
    text: bool
    timeout: float | None
    input: str | bytes | None
    stdout: int | BinaryIO | TextIO | None
    stderr: int | BinaryIO | TextIO | None
    stdin: int | BinaryIO | TextIO | None
    shell: bool
    start_new_session: bool


class SubprocessOptions(SubprocessCallOptions, total=False):
    env: Mapping[str, str] | None


class StandardsAnalyzeOptions(TypedDict, total=False):
    external: bool
    trust: TrustMode | str
    mode: AnalysisMode | str
    rules: Sequence[str | RuleSelector] | None
    staged: bool
    react_doctor_triggered: bool
    include_react_doctor: bool
    pass_on_unpruned_eslint_suppressions: bool
    jobs: int
    prepared_devops: Sequence[Path]
    prepared_targets: Sequence[str]
    prepared_only: bool
    python_type_check: bool
    eslint: bool


class NativeAnalyzeOptions(TypedDict, total=False):
    root: Required[Path]
    python_baseline: Path | None
    policy: Policy | None
    grouped: GroupedPaths | None
    rule_selection: RuleSelection | None


class ExternalAnalyzeOptions(TypedDict, total=False):
    root: Required[Path]
    trust: Required[TrustMode | str]
    runner: ProcessRunner | None
    policy: Policy | None
    capabilities: frozenset[str] | None
    grouped: GroupedPaths | None
    include_react_doctor: bool
    react_doctor_staged: bool
    force_react_doctor: bool
    react_doctor_full_scan: bool
    pass_on_unpruned_eslint_suppressions: bool
    rule_ids: frozenset[str] | None
    upstream_rules: UpstreamESLintRules
    security_selection: RuleSelection | None
    python_type_check: bool
    eslint: bool


class CorpusProcessOptions(TypedDict):
    cwd: Path
    env: dict[str, str]
    timeout: timedelta
    max_output_bytes: int


class CheckOptions(TypedDict, total=False):
    noise_only: bool
    python_baseline: str | None
    policy: Policy | None


class CanonicalCheckOptions(TypedDict, total=False):
    trusted: bool
    staged: bool
    raw: bool
    react_doctor_triggered: bool
    jobs: int
    python_type_check: bool
    eslint: bool


class EslintSelectionOptions(TypedDict, total=False):
    label: str
    fix: bool
    expand_directories: bool


class TemporaryDirectoryOptions(TypedDict, total=False):
    prefix: str
    ignore_cleanup_errors: bool


class VerifiedTagOptions(TypedDict):
    version: str
    commit: str
    runner: ReleaseProcessRunner


class TagVerifierOptions(TypedDict, total=False):
    runner: ReleaseProcessRunner
    commit: str
    targets: Sequence[str]


class RepositoryPolicyOptions(TypedDict, total=False):
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
