from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import timedelta
import json
import os
from pathlib import Path
import re
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- centralized argv-only adapter; shell is never enabled
import sys
import tempfile
import time
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple, Protocol, TypeGuard
from urllib.parse import quote

import yaml

from sarj_standards.libs.adoption import (
    doctor as adoption_doctor,
    hooks as adoption_hooks,
    launcher,
    manifest as adoption_manifest,
    packagemanager as adoption_packagemanager,
    scaffold as adoption_scaffold,
    uvtool as adoption_uvtool,
)
from sarj_standards.libs.repository import rule_catalog_artifact


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

DEFAULT_REGISTRY = Path(".sarj-standards-rollout.toml")
SOURCE_REPOSITORY = "https://github.com/sarj-ai/code-standards.git"
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.-]+)?\Z")
BOT_COMMIT_PREFIX = "chore(standards): adopt "
MANIFEST = ".sarj-standards.toml"
LS_REMOTE_FIELDS = 2
COMMIT_WITH_PARENT_FIELDS = 2
PORCELAIN_RECORD_MINIMUM = 4
MANAGED_TRAILER = "Standards-Rollout: managed/v1"
PR_MARKER_PREFIX = "<!-- sarj-standards-rollout:managed/v1"
REPOSITORY_VERSION_PIN = re.compile(r"^(STANDARDS_VERSION[ \t]*:?=[ \t]*)\S+[ \t]*$", re.MULTILINE)
PYRIGHT_COMMAND = re.compile(r"(?m)^(?P<indent>[ \t]*)cd python && uv run pyright[ \t]*$")
VERIFICATION_FAILED_MARKER = "<!-- sarj-standards-rollout:verification-failed -->"
RETIRED_ESLINT_SELECTORS = ("@sarj/prefer-single-sentence-comment", "@sarj/prefer-string-literal-union")
SOURCE_SUFFIXES = frozenset(
    {".py", ".pyi", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".sql"}
)
ROLLOUT_CHANNELS = ("canary", "early", "stable")
BASELINE_ENGINE_BY_SOURCE = MappingProxyType(
    {
        "sarj-iac-lint": "iac",
        "sarj-python-lint": "python",
        "sarj-sql-lint": "sql",
        "sarj-text-lint": "text",
    }
)
MANAGED_WORKFLOW_PATHS = frozenset({".github/workflows/standards.yml", ".github/workflows/ci.yml"})
MANAGED_ROLLOUT_NAMES = frozenset(
    {
        ".basedpyright-strict.json",
        ".lefthook.yml",
        ".lefthook.yaml",
        ".markdownlint.yaml",
        ".pre-commit-config.yaml",
        ".pre-commit-config.yml",
        ".pyright-strict.json",
        ".ruff-strict.toml",
        ".taplo.toml",
        ".tool-versions",
        ".yarnrc.yml",
        ".yamllint.yaml",
        "bun.lock",
        "doctor.config.json",
        "eslint.config.js",
        "eslint.config.mjs",
        "eslint.strict.mjs",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "pyproject.toml",
        "pyright.strict.json",
        "pyrightconfig.json",
        "uv.lock",
        "yarn.lock",
    }
)
DEFAULT_ALLOWED_ROLLOUT_PATHS = frozenset(
    {MANIFEST, ".shellcheckrc", "uv.lock", "eslint.config.mjs", *MANAGED_WORKFLOW_PATHS}
)
MAX_VERIFICATION_ATTEMPTS = 2
MISE_CONFIG_PATHS = (Path(".mise.toml"), Path("mise.toml"), Path(".tool-versions"), Path(".mise/config.toml"))
COREPACK_MANAGERS = frozenset({"pnpm", "yarn"})
WORKFLOW_TOOL_ACTIONS = MappingProxyType({"hashicorp/setup-terraform": ("terraform", "terraform_version")})
MANAGED_DELETIONS = frozenset({launcher.RETIRED_REPOSITORY_LAUNCHER.as_posix()})
RELEASE_VISIBILITY_ATTEMPTS = 7
RELEASE_VISIBILITY_DELAY = timedelta(seconds=10)
SECONDARY_JAVASCRIPT_ROOT_EXCLUSIONS = frozenset(
    {
        ".cache",
        ".git",
        ".next",
        ".nox",
        ".pnpm",
        ".tox",
        ".turbo",
        ".venv",
        ".yarn",
        "build",
        "dist",
        "example",
        "examples",
        "fixture",
        "fixtures",
        "node_modules",
        "test",
        "testdata",
        "tests",
        "vendor",
        "venv",
    }
)


class RolloutError(RuntimeError):
    pass


def is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def required_text(table: Mapping[str, object], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        msg = f"rollout registry field {key!r} must be a non-empty string"
        raise RolloutError(msg)
    return value


def optional_bool(table: Mapping[str, object], key: str) -> bool:
    value = table.get(key, False)
    if not isinstance(value, bool):
        msg = f"rollout registry field {key!r} must be a boolean"
        raise RolloutError(msg)
    return value


class RolloutArgs(argparse.Namespace):
    registry: Path = DEFAULT_REGISTRY
    command: str = ""
    version: str | None = None
    dry_run: bool = False
    channel: str = "stable"


class CommandRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    @staticmethod
    def run(
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- explicit argv; shell remains disabled
            list(command), cwd=cwd, check=check, text=True, capture_output=True, env=env
        )


@dataclass(frozen=True)
class Consumer:
    name: str
    repository: str
    branch: str
    verify: tuple[str, ...]
    requires_approval: bool = False
    auto_merge: bool = False
    channel: str = "stable"
    baseline_rules: tuple[str, ...] = ()
    baseline_paths: tuple[str, ...] = ()
    baseline_update: tuple[str, ...] = ()


@dataclass(frozen=True)
class Outcome:
    consumer: Consumer
    state: str
    url: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.consumer.name,
            "repository": self.consumer.repository,
            "branch": self.consumer.branch,
            "state": self.state,
            "url": self.url or None,
            "detail": self.detail or None,
        }


@dataclass(frozen=True)
class Plan:
    source_sha: str
    outcomes: tuple[Outcome, ...]


@dataclass(frozen=True)
class BranchPreparation:
    branch: str
    previous_sha: str | None


class ProvisionedTools(NamedTuple):
    environment: dict[str, str]
    command_prefix: tuple[str, ...]


class ReactDoctorPolicy(NamedTuple):
    config: bytes | None
    package_pin: str | None


def load_registry(path: Path) -> tuple[Consumer, ...]:  # ruff: ignore[too-many-locals] -- schema fields stay explicit
    with path.open("rb") as stream:
        parsed: object = tomllib.load(stream)
    if not is_object(parsed):
        msg = f"rollout registry must be a TOML table: {path}"
        raise RolloutError(msg)
    raw = parsed
    if raw.get("schema") != 1:
        msg = f"unsupported registry schema in {path}"
        raise RolloutError(msg)
    entries_value = raw.get("consumer")
    if not is_array(entries_value) or not entries_value:
        msg = "the rollout registry must contain at least one consumer"
        raise RolloutError(msg)
    consumers: list[Consumer] = []
    for entry_value in entries_value:
        if not is_object(entry_value) or set(entry_value) - {
            "name",
            "repository",
            "branch",
            "verify",
            "requires_approval",
            "auto_merge",
            "channel",
            "baseline_rules",
            "baseline_paths",
            "baseline_update",
        }:
            msg = f"invalid registry entry keys: {entry_value!r}"
            raise RolloutError(msg)
        entry = entry_value
        name = required_text(entry, "name")
        repository = required_text(entry, "repository")
        branch = required_text(entry, "branch")
        verify_value = entry.get("verify")
        requires_approval = optional_bool(entry, "requires_approval")
        auto_merge = optional_bool(entry, "auto_merge")
        channel_value = entry.get("channel", "stable")
        baseline_rules_value = entry.get("baseline_rules", [])
        baseline_paths_value = entry.get("baseline_paths", [])
        baseline_update_value = entry.get("baseline_update", [])
        if channel_value not in ROLLOUT_CHANNELS:
            msg = f"invalid rollout channel: {channel_value!r}"
            raise RolloutError(msg)
        if not is_array(verify_value) or not verify_value:
            msg = f"invalid registry verification command: {entry!r}"
            raise RolloutError(msg)
        if not is_array(baseline_rules_value) or not all(
            isinstance(item, str) and item for item in baseline_rules_value
        ):
            msg = f"invalid promoted baseline rules: {entry!r}"
            raise RolloutError(msg)
        if not is_array(baseline_paths_value) or not all(
            isinstance(item, str) and item for item in baseline_paths_value
        ):
            msg = f"invalid consumer baseline paths: {entry!r}"
            raise RolloutError(msg)
        if not is_array(baseline_update_value) or not all(
            isinstance(item, str) and item for item in baseline_update_value
        ):
            msg = f"invalid consumer baseline update command: {entry!r}"
            raise RolloutError(msg)
        if bool(baseline_paths_value) != bool(baseline_update_value):
            msg = "consumer baseline_paths and baseline_update must be declared together"
            raise RolloutError(msg)
        baseline_paths = tuple(item for item in baseline_paths_value if isinstance(item, str))
        if len(set(baseline_paths)) != len(baseline_paths) or any(
            Path(item).is_absolute() or "\\" in item or ".." in Path(item).parts or "baseline" not in item.casefold()
            for item in baseline_paths
        ):
            msg = f"unsafe consumer baseline paths: {entry!r}"
            raise RolloutError(msg)
        if not all(isinstance(item, str) and item for item in verify_value):
            msg = f"invalid registry values: {entry!r}"
            raise RolloutError(msg)
        verify = tuple(item for item in verify_value if isinstance(item, str))
        consumer = Consumer(
            name=name,
            repository=repository,
            branch=branch,
            verify=verify,
            requires_approval=requires_approval,
            auto_merge=auto_merge,
            channel=channel_value,
            baseline_rules=tuple(item for item in baseline_rules_value if isinstance(item, str)),
            baseline_paths=baseline_paths,
            baseline_update=tuple(item for item in baseline_update_value if isinstance(item, str)),
        )
        consumers.append(consumer)
    identities = tuple((item.repository, item.branch) for item in consumers)
    if len(set(identities)) != len(consumers):
        msg = "registry consumers must have unique repository and branch identities"
        raise RolloutError(msg)
    if sum(item.auto_merge for item in consumers) > 1:
        msg = "at most one consumer may enable rollout auto-merge"
        raise RolloutError(msg)
    return tuple(consumers)


def select_channel(consumers: Sequence[Consumer], channel: str) -> tuple[Consumer, ...]:
    if channel not in ROLLOUT_CHANNELS:
        msg = f"invalid rollout channel: {channel!r}"
        raise RolloutError(msg)
    ceiling = ROLLOUT_CHANNELS.index(channel)
    return tuple(item for item in consumers if ROLLOUT_CHANNELS.index(item.channel) <= ceiling)


def validate_version(version: str) -> str:
    if not VERSION_RE.fullmatch(version):
        msg = f"invalid immutable version: {version!r}"
        raise RolloutError(msg)
    return version


def rollout_branch(version: str) -> str:
    validate_version(version)
    return "standards-rollout/current"


def pr_marker(consumer: Consumer, version: str) -> str:
    validate_version(version)
    return f"{PR_MARKER_PREFIX} repository={consumer.repository} base={consumer.branch} channel={consumer.channel} -->"


def desired_marker(version: str) -> str:
    return f"<!-- sarj-standards-rollout:desired={validate_version(version)} -->"


def stdout(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout or "").strip()


def json_result(result: subprocess.CompletedProcess[str]) -> object:
    rendered = stdout(result)
    try:
        parsed: object = json.loads(rendered or "null")  # pyright: ignore[reportAny]
    except json.JSONDecodeError as exc:
        msg = f"command returned invalid JSON: {rendered[:200]}"
        raise RolloutError(msg) from exc
    else:
        return parsed


def verify_release(
    version: str,
    runner: CommandRunner,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    version = validate_version(version)
    package: subprocess.CompletedProcess[str] | None = None
    for attempt in range(RELEASE_VISIBILITY_ATTEMPTS):
        package = runner.run(
            (
                "uvx",
                "--isolated",
                "--python",
                "3.14",
                "--refresh-package",
                "code-standards",
                "--from",
                f"code-standards=={version}",
                "code-standards",
                "--version",
            ),
            check=False,
        )
        match = re.fullmatch(r"code-standards\s+([0-9a-zA-Z.-]+)", stdout(package))
        if package.returncode == 0 and match is not None and match.group(1) == version:
            break
        if attempt + 1 < RELEASE_VISIBILITY_ATTEMPTS:
            sleep(RELEASE_VISIBILITY_DELAY.total_seconds())
    else:
        msg = f"PyPI artifact did not report version {version}"
        raise RolloutError(msg)
    tag = f"refs/tags/standards-v{version}"
    peeled = tag + "^{}"
    remote = runner.run(("git", "ls-remote", SOURCE_REPOSITORY, tag, peeled))
    refs = {
        fields[1]: fields[0] for line in stdout(remote).splitlines() if len(fields := line.split()) == LS_REMOTE_FIELDS
    }
    sha = refs.get(peeled)
    if len(refs) != LS_REMOTE_FIELDS or sha is None or not re.fullmatch(r"[0-9a-f]{40}", sha):
        msg = f"published tag standards-v{version} is absent or invalid"
        raise RolloutError(msg)
    return sha


def manifest_version(contents: str) -> str | None:
    try:
        parsed = tomllib.loads(contents)
    except tomllib.TOMLDecodeError:
        return None
    value = parsed.get("bundle", parsed.get("version"))
    return value if isinstance(value, str) else None


def base_manifest(consumer: Consumer, runner: CommandRunner) -> str | None:
    result = runner.run(
        (
            "gh",
            "api",
            f"repos/{consumer.repository}/contents/{MANIFEST}",
            "--method",
            "GET",
            "-f",
            f"ref={consumer.branch}",
        ),
        check=False,
    )
    if result.returncode != 0:
        return None
    payload = json_result(result)
    if not is_object(payload):
        return None
    content = payload.get("content")
    if not isinstance(content, str):
        return None
    try:
        return base64.b64decode(content, validate=False).decode()
    except ValueError, UnicodeDecodeError:
        return None


def pull_request(consumer: Consumer, version: str, runner: CommandRunner) -> dict[str, object] | None:
    result = runner.run(
        (
            "gh",
            "pr",
            "list",
            "--repo",
            consumer.repository,
            "--state",
            "open",
            "--head",
            rollout_branch(version),
            "--json",
            "state,mergedAt,url,headRefName,baseRefName,headRefOid,body",
            "--limit",
            "2",
        )
    )
    payload = json_result(result)
    if not is_array(payload) or not payload:
        return None
    if len(payload) != 1:
        msg = f"{consumer.name}: multiple rollout PRs exist for {rollout_branch(version)}"
        raise RolloutError(msg)
    first = payload[0]
    return first if is_object(first) else None


def live_consumer_base_sha(consumer: Consumer, runner: CommandRunner) -> str:
    ref = quote(f"heads/{consumer.branch}", safe="")
    result = runner.run(
        ("gh", "api", f"repos/{consumer.repository}/git/ref/{ref}"),
        check=False,
    )
    if result.returncode != 0:
        msg = "managed rollout current consumer base ref could not be read"
        raise RolloutError(msg)
    try:
        payload = json_result(result)
    except RolloutError as exc:
        msg = "managed rollout current consumer base ref is malformed"
        raise RolloutError(msg) from exc
    target = payload.get("object") if is_object(payload) else None
    target_type = target.get("type") if is_object(target) else None
    sha = target.get("sha") if is_object(target) else None
    if target_type != "commit" or not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        msg = "managed rollout current consumer base ref has no valid commit SHA"
        raise RolloutError(msg)
    return sha


def open_pull_commit_provenance(
    consumer: Consumer,
    pull: Mapping[str, object],
    runner: CommandRunner,
) -> Outcome | None:
    url = str(pull.get("url", ""))
    head_sha = pull.get("headRefOid")
    if not isinstance(head_sha, str) or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None:
        return Outcome(consumer, "blocked", url, "managed rollout PR has no valid head commit SHA")
    commit = runner.run(
        ("gh", "api", f"repos/{consumer.repository}/commits/{head_sha}"),
        check=False,
    )
    if commit.returncode != 0:
        return Outcome(consumer, "blocked", url, "managed rollout commit provenance could not be read")
    try:
        payload = json_result(commit)
    except RolloutError:
        return Outcome(consumer, "blocked", url, "managed rollout commit provenance is malformed")
    parents_value = payload.get("parents") if is_object(payload) else None
    parents = parents_value if is_array(parents_value) else []
    parent_shas = tuple(sha for item in parents if is_object(item) and isinstance((sha := item.get("sha")), str))
    if len(parents) != 1 or len(parent_shas) != 1 or re.fullmatch(r"[0-9a-f]{40}", parent_shas[0]) is None:
        return Outcome(consumer, "blocked", url, "managed rollout head must be exactly one commit with one parent")
    try:
        base_sha = live_consumer_base_sha(consumer, runner)
    except RolloutError as exc:
        return Outcome(consumer, "blocked", url, str(exc))
    if parent_shas[0] != base_sha:
        return Outcome(
            consumer,
            "missing",
            url,
            f"managed rollout commit parent {parent_shas[0]} no longer matches current consumer base {base_sha}; "
            "reconcile will refresh this managed PR",
        )
    return None


def status_one(consumer: Consumer, version: str, runner: CommandRunner) -> Outcome:
    pull = pull_request(consumer, version, runner)
    if pull is not None:
        identity_is_valid = (
            pull.get("headRefName") == rollout_branch(version)
            and pull.get("baseRefName") == consumer.branch
            and pr_marker(consumer, version) in str(pull.get("body", ""))
        )
        if not identity_is_valid:
            return Outcome(
                consumer,
                "blocked",
                str(pull.get("url", "")),
                "rollout PR ownership marker, head, or base does not match",
            )
        if desired_marker(version) not in str(pull.get("body", "")):
            return Outcome(
                consumer,
                "missing",
                str(pull.get("url", "")),
                "open managed PR targets an older Standards release",
            )
        if VERIFICATION_FAILED_MARKER in str(pull.get("body", "")):
            return Outcome(
                consumer,
                "blocked",
                str(pull.get("url", "")),
                "consumer verification failed; reconcile will retry this managed PR",
            )
        if (
            pull.get("mergedAt") is None
            and (provenance := open_pull_commit_provenance(consumer, pull, runner)) is not None
        ):
            return provenance
        state = "merged" if pull.get("mergedAt") else "pr-open"
        return Outcome(consumer, state, str(pull.get("url", "")))
    adopted = manifest_version(base_manifest(consumer, runner) or "")
    if adopted == version:
        return Outcome(consumer, "already-current")
    return Outcome(consumer, "missing", detail=f"base branch has {adopted or 'no readable manifest'}")


def status(version: str, consumers: Sequence[Consumer], runner: CommandRunner) -> tuple[Outcome, ...]:
    validate_version(version)
    return tuple(status_one(item, version, runner) for item in consumers)


def changed_paths(repo: Path, runner: CommandRunner) -> tuple[str, ...]:
    result = runner.run(("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"), cwd=repo)
    fields = [field for field in (result.stdout or "").split("\0") if field]
    paths: list[str] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        if len(record) < PORCELAIN_RECORD_MINIMUM:
            msg = "git returned an invalid porcelain status record"
            raise RolloutError(msg)
        state, path = record[:2], record[3:]
        if "R" in state or ("D" in state and path not in MANAGED_DELETIONS):
            msg = f"update may not delete or rename files: {path}"
            raise RolloutError(msg)
        paths.append(path)
        index += 2 if "R" in state or "C" in state else 1
    return tuple(paths)


def committed_paths(repo: Path, base: str, runner: CommandRunner) -> tuple[str, ...]:
    comparison = f"origin/{base}...HEAD"
    renamed = stdout(runner.run(("git", "diff", "--name-only", "--diff-filter=R", comparison), cwd=repo))
    deleted = stdout(runner.run(("git", "diff", "--name-only", "--diff-filter=D", comparison), cwd=repo))
    unsafe_deletions = tuple(path for path in deleted.splitlines() if path not in MANAGED_DELETIONS)
    if renamed or unsafe_deletions:
        affected = renamed or ", ".join(unsafe_deletions)
        msg = f"rollout branch may not delete or rename files: {affected}"
        raise RolloutError(msg)
    result = runner.run(("git", "diff", "--name-only", "-z", "--diff-filter=ACMD", comparison), cwd=repo)
    return tuple(path for path in (result.stdout or "").split("\0") if path)


def reject_git_metadata(
    repo: Path,
    paths: Sequence[str],
    runner: CommandRunner,
    *,
    comparison: str = "",
) -> None:
    diff_args = (comparison,) if comparison else ()
    summary = stdout(runner.run(("git", "diff", "--summary", *diff_args), cwd=repo))
    if "mode change" in summary or "create mode 120000" in summary:
        msg = "update may not change file modes or create symlinks"
        raise RolloutError(msg)
    numbers = stdout(runner.run(("git", "diff", "--numstat", *diff_args, "--", *paths), cwd=repo))
    if any(line.startswith("-\t-\t") for line in numbers.splitlines()):
        msg = "update may not add or modify binary files"
        raise RolloutError(msg)
    for relative in paths:
        candidate = repo / relative
        tracked = runner.run(("git", "ls-files", "--error-unmatch", "--", relative), cwd=repo, check=False)
        untracked_executable = (
            tracked.returncode != 0
            and candidate.exists()
            and bool(stat.S_IMODE(candidate.stat().st_mode) & stat.S_IXUSR)
        )
        if candidate.is_symlink() or untracked_executable:
            msg = f"update may not create symlinks or executable files: {relative}"
            raise RolloutError(msg)
        if candidate.is_file() and b"\0" in candidate.read_bytes()[:8192]:
            msg = f"update may not add or modify binary files: {relative}"
            raise RolloutError(msg)


def reject_unsafe_diff(
    paths: Sequence[str],
    *,
    allowed_source_paths: frozenset[str] = frozenset(),
    allowed_workflow_paths: frozenset[str] = frozenset(),
    allowed_baseline_paths: frozenset[str] = frozenset(),
    allowed_paths: frozenset[str] = DEFAULT_ALLOWED_ROLLOUT_PATHS,
) -> None:
    if not paths:
        msg = "the update produced no changes but the base manifest is not current"
        raise RolloutError(msg)
    unsafe: list[str] = []
    for rendered in paths:
        path = Path(rendered)
        lowered = rendered.lower()
        workflow_is_unsafe = (
            rendered.startswith(".github/workflows/")
            and rendered not in MANAGED_WORKFLOW_PATHS
            and rendered not in allowed_workflow_paths
        )
        source_is_unsafe = (
            rendered not in allowed_source_paths and rendered not in allowed_paths and path.suffix in SOURCE_SUFFIXES
        )
        baseline_is_unsafe = "baseline" in lowered and rendered not in allowed_baseline_paths
        path_is_unsafe = (
            rendered not in allowed_paths
            and rendered not in allowed_baseline_paths
            and rendered not in allowed_workflow_paths
            and rendered not in allowed_source_paths
        )
        if workflow_is_unsafe or source_is_unsafe or baseline_is_unsafe or path_is_unsafe or "exclusion" in lowered:
            unsafe.append(rendered)
    if unsafe:
        msg = "update touched protected paths: " + ", ".join(unsafe)
        raise RolloutError(msg)


def amend_safe_changes(
    repo: Path,
    runner: CommandRunner,
    *,
    allowed_workflow_paths: frozenset[str],
    allowed_baseline_paths: frozenset[str] = frozenset(),
    allowed_paths: frozenset[str] = DEFAULT_ALLOWED_ROLLOUT_PATHS,
) -> bool:
    paths = changed_paths(repo, runner)
    if not paths:
        return False
    reject_unsafe_diff(
        paths,
        allowed_workflow_paths=allowed_workflow_paths,
        allowed_baseline_paths=allowed_baseline_paths,
        allowed_paths=allowed_paths,
    )
    reject_git_metadata(repo, paths, runner)
    runner.run(("git", "add", "--", *paths), cwd=repo)
    runner.run(
        ("git", "-c", "core.hooksPath=/dev/null", "commit", "--amend", "--no-edit"),
        cwd=repo,
    )
    return True


def remote_branch_sha(repo: Path, branch: str, runner: CommandRunner) -> str | None:
    result = runner.run(("git", "ls-remote", "--heads", "origin", branch), cwd=repo)
    fields = stdout(result).split()
    return fields[0] if len(fields) == LS_REMOTE_FIELDS else None


def force_with_lease(branch: str, previous_sha: str | None) -> str:
    return f"--force-with-lease=refs/heads/{branch}:{previous_sha or ''}"


def assert_consumer_base_unchanged(
    repo: Path,
    consumer: Consumer,
    expected_sha: str,
    runner: CommandRunner,
) -> None:
    runner.run(("git", "fetch", "origin", consumer.branch), cwd=repo)
    live_sha = stdout(runner.run(("git", "rev-parse", "FETCH_HEAD"), cwd=repo))
    if re.fullmatch(r"[0-9a-f]{40}", live_sha) is None:
        msg = f"{consumer.name}: refreshed consumer base did not resolve to a full commit SHA"
        raise RolloutError(msg)
    if live_sha != expected_sha:
        msg = (
            f"{consumer.name}: consumer base moved from {expected_sha} to {live_sha} during verification; "
            "reconcile will retry from the refreshed base"
        )
        raise RolloutError(msg)


def unauthenticated_environment() -> dict[str, str]:
    environment = dict(os.environ)  # ruff: ignore[banned-api] — copy before scrubbing auth
    environment.pop("GH_TOKEN", None)
    environment.pop("GITHUB_TOKEN", None)
    inherited_virtual_env = environment.pop("VIRTUAL_ENV", None)
    environment.pop("UV_PROJECT_ENVIRONMENT", None)
    if inherited_virtual_env:
        virtual_bin = Path(inherited_virtual_env) / ("Scripts" if os.name == "nt" else "bin")
        environment["PATH"] = os.pathsep.join(
            entry for entry in environment.get("PATH", "").split(os.pathsep) if Path(entry) != virtual_bin
        )
    for name in tuple(environment):
        if name.startswith("STANDARDS_ROLLOUT_"):
            environment.pop(name)
    return environment


def consumer_verification_environment(environment: Mapping[str, str], base_sha: str) -> dict[str, str]:
    prepared = dict(environment)
    prepared["SARJ_STANDARDS_BASE"] = base_sha
    prepared.pop("SARJ_REACT_DOCTOR_BASE", None)
    return prepared


def assert_baseline_unchanged(path: Path | None, expected: bytes | None) -> None:
    if path is None:
        return
    if not path.is_file() or path.read_bytes() != expected:
        msg = f"consumer verification mutated controller-owned diagnostic baseline: {path}"
        raise RolloutError(msg)


def assert_baselines_unchanged(expected: Mapping[Path, bytes]) -> None:
    for path, contents in expected.items():
        assert_baseline_unchanged(path, contents)


def managed_rollout_paths(repo: Path, workflow_paths: frozenset[str]) -> frozenset[str]:
    allowed = set(DEFAULT_ALLOWED_ROLLOUT_PATHS)
    allowed.update(workflow_paths)
    for path in repo.rglob("*"):
        if path.is_file() and path.name in MANAGED_ROLLOUT_NAMES:
            allowed.add(path.relative_to(repo).as_posix())
    adopted = adoption_manifest.load_for_setup(repo)
    roots = {repo}
    if adopted is not None:
        roots.update({repo / adopted.python_dest, repo / adopted.typescript_dest})
        if adopted.hook_manager == "lefthook" and (lefthook := adoption_hooks.lefthook_config(repo)) is not None:
            allowed.add(lefthook.relative_to(repo).as_posix())
    for root in roots:
        allowed.update((root / name).relative_to(repo).as_posix() for name in MANAGED_ROLLOUT_NAMES)
    allowed.update({path.as_posix() for path in MISE_CONFIG_PATHS})
    allowed.add("Makefile")
    return frozenset(allowed)


def declared_workflow_tools(repo: Path) -> tuple[str, ...]:
    requirements: dict[str, str] = {}
    workflow_root = repo / ".github/workflows"
    for path in sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml"))):
        try:
            parsed: object = yaml.safe_load(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
        except (OSError, yaml.YAMLError) as exc:
            msg = f"could not read consumer workflow tool declarations from {path}: {exc}"
            raise RolloutError(msg) from exc
        if not is_object(parsed):
            continue
        jobs = parsed.get("jobs")
        if not is_object(jobs):
            continue
        for job_value in jobs.values():
            if not is_object(job_value):
                continue
            steps = job_value.get("steps")
            if not is_array(steps):
                continue
            for step_value in steps:
                if not is_object(step_value):
                    continue
                uses = step_value.get("uses")
                if not isinstance(uses, str):
                    continue
                action = uses.partition("@")[0]
                declaration = WORKFLOW_TOOL_ACTIONS.get(action)
                if declaration is None:
                    continue
                tool, version_key = declaration
                options = step_value.get("with")
                version = options.get(version_key) if is_object(options) else None
                if not isinstance(version, str) or VERSION_RE.fullmatch(version) is None:
                    msg = f"{path}: {action} must declare an exact {version_key} for rollout verification"
                    raise RolloutError(msg)
                previous = requirements.setdefault(tool, version)
                if previous != version:
                    msg = f"consumer workflows declare conflicting {tool} versions: {previous} and {version}"
                    raise RolloutError(msg)
    return tuple(f"{tool}@{version}" for tool, version in sorted(requirements.items()))


def provision_consumer_tools(
    repo: Path,
    shim_directory: Path,
    runner: CommandRunner,
    environment: Mapping[str, str],
) -> ProvisionedTools:
    prepared = dict(environment)
    mise_prefix: tuple[str, ...] = ()
    has_mise_config = any((repo / relative).is_file() for relative in MISE_CONFIG_PATHS)
    workflow_tools = declared_workflow_tools(repo)
    if has_mise_config or workflow_tools:
        prepared["MISE_YES"] = "1"
        prepared["MISE_TRUSTED_CONFIG_PATHS"] = str(repo.resolve())
        if has_mise_config:
            installed = runner.run(("mise", "install"), cwd=repo, env=prepared, check=False)
            if installed.returncode != 0:
                msg = "could not provision repository-declared mise tools:\n" + verification_detail(installed)
                raise RolloutError(msg)
        if workflow_tools:
            installed = runner.run(("mise", "install", *workflow_tools), cwd=repo, env=prepared, check=False)
            if installed.returncode != 0:
                msg = "could not provision workflow-declared tools:\n" + verification_detail(installed)
                raise RolloutError(msg)
        mise_prefix = ("mise", "exec", *workflow_tools, "--")

    # Tool provisioning happens before `code-standards update`, so consumers
    # may still use the immediately preceding manifest schema here.
    adopted = adoption_manifest.load_for_setup(repo)
    python_root = None if adopted is None else repo / adopted.python_dest
    uv_source = adoption_uvtool.version_file(python_root)
    uv_required = None if uv_source is None else adoption_uvtool.required_version(uv_source)
    if uv_required is not None:
        shim_directory.mkdir(parents=True, exist_ok=True)
        install_environment = dict(prepared)
        install_environment["UV_TOOL_DIR"] = str(shim_directory.parent / "uv-tools")
        install_environment["UV_TOOL_BIN_DIR"] = str(shim_directory)
        installed = runner.run(
            ("uv", "--no-config", "tool", "install", "--force", f"uv{uv_required}"),
            cwd=repo,
            env=install_environment,
            check=False,
        )
        if installed.returncode != 0:
            msg = "could not provision repository-declared uv:\n" + verification_detail(installed)
            raise RolloutError(msg)

    manager = _declared_corepack_manager(repo)
    if manager is not None:
        shim_directory.mkdir(parents=True, exist_ok=True)
        enabled = runner.run(
            (*mise_prefix, "corepack", "enable", "--install-directory", str(shim_directory)),
            cwd=repo,
            env=prepared,
            check=False,
        )
        if enabled.returncode != 0:
            msg = f"could not provision isolated Corepack shims for {manager}:\n" + verification_detail(enabled)
            raise RolloutError(msg)
    if uv_required is not None or manager is not None:
        current_path = prepared.get("PATH", "")
        prepared["PATH"] = f"{shim_directory}{os.pathsep}{current_path}" if current_path else str(shim_directory)
    return ProvisionedTools(prepared, mise_prefix)


def run_consumer_bootstrap(
    repo: Path,
    tool_prefix: tuple[str, ...],
    runner: CommandRunner,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str] | None:
    adopted = adoption_manifest.load(repo)
    if adopted is None:
        return None
    python_install = adoption_scaffold.python_ci_install_argv(repo, adopted.python_dest)
    if python_install:
        python_root = repo / adopted.python_dest
        compatible_install = adoption_uvtool.argv(python_root, *python_install[1:])
        result = runner.run((*tool_prefix, *compatible_install), cwd=repo, env=environment, check=False)
        if result.returncode != 0:
            return result
    primary_typescript_root = adoption_packagemanager.workspace_root(
        repo / adopted.typescript_dest,
        repo,
    )
    for javascript_root in secondary_javascript_roots(repo, primary_typescript_root):
        manager = adoption_packagemanager.detect(javascript_root)
        install = adoption_packagemanager.frozen_install_argv(
            manager,
            yarn=adoption_packagemanager.yarn_variant(javascript_root),
        )
        result = runner.run((*tool_prefix, *install), cwd=javascript_root, env=environment, check=False)
        if result.returncode != 0:
            return result
    for command in adopted.ci_bootstrap:
        result = runner.run(
            (*tool_prefix, "bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", command),
            cwd=repo,
            env=environment,
            check=False,
        )
        if result.returncode != 0:
            return result
    return None


def secondary_javascript_roots(repo: Path, primary: Path) -> tuple[Path, ...]:
    repository = repo.resolve()
    primary_root = primary.resolve()
    roots: list[Path] = []
    for current, directories, files in os.walk(repository):
        directories[:] = sorted(
            directory for directory in directories if directory not in SECONDARY_JAVASCRIPT_ROOT_EXCLUSIONS
        )
        root = Path(current)
        if root == primary_root:
            directories.clear()
            continue
        if any(name in files for name, _manager in adoption_packagemanager.LOCKFILES):
            roots.append(root)
    return tuple(sorted(roots, key=lambda path: path.relative_to(repository).as_posix()))


def _declared_corepack_manager(repo: Path) -> str | None:
    for manifest in sorted(repo.glob("**/package.json")):
        if any(part in {"node_modules", ".git"} for part in manifest.parts):
            continue
        try:
            parsed: object = json.loads(manifest.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
        except OSError, json.JSONDecodeError:
            continue
        if not is_object(parsed):
            continue
        declared = parsed.get("packageManager")
        if not isinstance(declared, str):
            continue
        manager = declared.partition("@")[0]
        if manager in COREPACK_MANAGERS:
            return manager
    return None


def synchronize_repository_pin(repo: Path, version: str) -> bool:
    makefile = repo / "Makefile"
    if not makefile.is_file():
        return False
    original = makefile.read_text(encoding="utf-8")
    matches = tuple(REPOSITORY_VERSION_PIN.finditer(original))
    if not matches:
        return False
    if len(matches) != 1:
        msg = "repository Makefile must contain at most one STANDARDS_VERSION pin"
        raise RolloutError(msg)
    updated = REPOSITORY_VERSION_PIN.sub(rf"\g<1>{validate_version(version)}", original)
    if updated == original:
        return False
    makefile.write_text(updated, encoding="utf-8")
    return True


def synchronize_repository_checker(repo: Path) -> bool:
    makefile = repo / "Makefile"
    project = repo / "python/pyproject.toml"
    if not makefile.is_file() or not project.is_file():
        return False
    if "basedpyright" not in project.read_text(encoding="utf-8"):
        return False
    original = makefile.read_text(encoding="utf-8")
    updated, count = PYRIGHT_COMMAND.subn(r"\g<indent>cd python && uv run basedpyright", original)
    if count > 1:
        msg = "repository Makefile contains multiple ambiguous Python typecheck commands"
        raise RolloutError(msg)
    if updated == original:
        return False
    makefile.write_text(updated, encoding="utf-8")
    return True


def remove_retired_eslint_suppressions(repo: Path, runner: CommandRunner) -> frozenset[str]:
    matched = runner.run(
        ("git", "grep", "-lz", "eslint-disable", "--", "*.js", "*.jsx", "*.ts", "*.tsx"),
        cwd=repo,
        check=False,
    )
    if matched.returncode not in {0, 1}:
        msg = "could not enumerate retired ESLint suppressions"
        raise RolloutError(msg)
    changed: set[str] = set()
    for relative in (item for item in (matched.stdout or "").split("\0") if item):
        path = repo / relative
        original = path.read_text(encoding="utf-8")
        lines: list[str] = []
        for line in original.splitlines(keepends=True):
            updated = line
            if "eslint-disable" in updated:
                for selector in RETIRED_ESLINT_SELECTORS:
                    updated = updated.replace(f", {selector}", "").replace(f"{selector}, ", "").replace(selector, "")
            lines.append(updated)
        rendered = "".join(lines)
        if rendered != original:
            path.write_text(rendered, encoding="utf-8")
            changed.add(relative)
    return frozenset(changed)


def verification_detail(result: subprocess.CompletedProcess[str]) -> str:
    rendered = "\n".join(value.strip() for value in (result.stdout, result.stderr) if value)
    return rendered[-4000:] or f"verification command exited {result.returncode}"


def process_failure_detail(error: subprocess.CalledProcessError) -> str:
    stdout: object = error.stdout  # pyright: ignore[reportAny] - subprocess exception boundary
    stderr: object = error.stderr  # pyright: ignore[reportAny] - subprocess exception boundary
    values = [value.strip() for value in (stdout, stderr) if isinstance(value, str) and value]
    return ("\n".join(values)[-4000:] or str(error)).strip()


def prepare_branch(
    repo: Path,
    version: str,
    base_sha: str,
    runner: CommandRunner,
) -> BranchPreparation:
    branch = rollout_branch(version)
    previous_sha = remote_branch_sha(repo, branch, runner)
    if previous_sha is None:
        runner.run(("git", "switch", "-c", branch, base_sha), cwd=repo)
        return BranchPreparation(branch, None)
    runner.run(("git", "fetch", "origin", branch), cwd=repo)
    message = stdout(runner.run(("git", "show", "-s", "--format=%B", "FETCH_HEAD"), cwd=repo))
    fetched_commit = stdout(runner.run(("git", "rev-list", "--parents", "-n", "1", "FETCH_HEAD"), cwd=repo)).split()
    valid_commit_shape = (
        len(fetched_commit) == COMMIT_WITH_PARENT_FIELDS
        and fetched_commit[0] == previous_sha
        and all(re.fullmatch(r"[0-9a-f]{40}", sha) is not None for sha in fetched_commit)
    )
    parent_is_base_ancestor = False
    if valid_commit_shape:
        ancestry = runner.run(
            ("git", "merge-base", "--is-ancestor", fetched_commit[1], base_sha),
            cwd=repo,
            check=False,
        )
        parent_is_base_ancestor = ancestry.returncode == 0
    if (
        MANAGED_TRAILER not in message
        or not message.startswith(BOT_COMMIT_PREFIX)
        or not valid_commit_shape
        or not parent_is_base_ancestor
    ):
        msg = f"refusing human-modified rollout branch {branch}"
        raise RolloutError(msg)
    runner.run(("git", "switch", "-C", branch, base_sha), cwd=repo)
    return BranchPreparation(branch, previous_sha)


def react_doctor_policy_snapshot(repo: Path) -> ReactDoctorPolicy:
    # Capture the pre-update policy through the same compatibility boundary used
    # by setup/update. Fleet consumers can legitimately still be on the prior
    # manifest schema; the rollout is responsible for migrating them before the
    # strict current-schema loader is used below.
    adopted = adoption_manifest.load_for_setup(repo)
    if adopted is None:
        return ReactDoctorPolicy(None, None)
    project = repo / adopted.typescript_dest
    config_path = project / "doctor.config.json"
    config = config_path.read_bytes() if config_path.is_file() else None
    package_path = project / "package.json"
    package_pin: str | None = None
    if package_path.is_file():
        try:
            parsed: object = json.loads(package_path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
        except OSError, ValueError:
            parsed = None
        if is_object(parsed):
            for field in ("dependencies", "devDependencies", "peerDependencies"):
                dependencies = parsed.get(field)
                if is_object(dependencies) and isinstance(pin := dependencies.get("react-doctor"), str):
                    package_pin = pin
                    break
    return ReactDoctorPolicy(config, package_pin)


def rollout_baseline_rules(
    consumer: Consumer,
    before: ReactDoctorPolicy,
    after: ReactDoctorPolicy,
) -> tuple[str, ...]:
    catalog = rule_catalog_artifact.selector_index()
    selectors: list[str] = []
    for selector in consumer.baseline_rules:
        source, separator, rule_id = selector.partition(":")
        normalized = f"{BASELINE_ENGINE_BY_SOURCE.get(source, source)}:{rule_id}" if separator else selector
        selectors.append(catalog.resolve(normalized))
    if before != after and (after.config is not None or after.package_pin is not None):
        selectors.append("react-doctor:*")
    return tuple(dict.fromkeys(selectors))


def apply_one(  # ruff: ignore[too-many-locals] - one transaction keeps verification and mutation state bound
    consumer: Consumer,
    version: str,
    runner: CommandRunner,
    *,
    dry_run: bool = False,
) -> Outcome:
    existing = status_one(consumer, version, runner)
    retry_verification = existing.state == "blocked" and existing.detail.startswith("consumer verification failed")
    if existing.state == "blocked" and not retry_verification:
        msg = f"{consumer.name}: {existing.detail}: {existing.url}"
        raise RolloutError(msg)
    if existing.state != "missing" and not retry_verification:
        return existing
    if dry_run:
        return Outcome(consumer, "would-create", detail=rollout_branch(version))
    # Consumer package managers can leave short-lived background cleanup work
    # behind after their command exits. The hosted runner discards this
    # workspace, so a best-effort temporary-directory cleanup must never mask
    # the rollout outcome or prevent later consumers from being reconciled.
    with tempfile.TemporaryDirectory(prefix="standards-rollout-", ignore_cleanup_errors=True) as temporary:
        repo = Path(temporary) / "repo"
        runner.run(
            (
                "gh",
                "repo",
                "clone",
                consumer.repository,
                str(repo),
                "--",
                "--branch",
                consumer.branch,
            )
        )
        base_sha = stdout(runner.run(("git", "rev-parse", "HEAD"), cwd=repo))
        if re.fullmatch(r"[0-9a-f]{40}", base_sha) is None:
            msg = f"{consumer.name}: cloned base did not resolve to a full commit SHA"
            raise RolloutError(msg)
        preparation = prepare_branch(repo, version, base_sha, runner)
        branch = preparation.branch
        previous_sha = preparation.previous_sha
        previous_react_doctor_policy = react_doctor_policy_snapshot(repo)
        tool = (
            "uvx",
            "--isolated",
            "--python",
            "3.14",
            "--from",
            f"code-standards=={version}",
            "code-standards",
            "--root",
            ".",
        )
        unauthenticated, tool_prefix = provision_consumer_tools(
            repo,
            Path(temporary) / "corepack-bin",
            runner,
            unauthenticated_environment(),
        )
        allowed_workflow_paths = frozenset(
            relative
            for update in adoption_doctor.plan_version_pin_updates(repo)
            if (relative := update.path.relative_to(repo).as_posix()).startswith(".github/workflows/")
        )
        allowed_paths = managed_rollout_paths(repo, allowed_workflow_paths)
        failures: list[str] = []
        try:
            runner.run((*tool_prefix, *tool, "update", "--to", version), cwd=repo, env=unauthenticated)
        except subprocess.CalledProcessError as exc:
            msg = f"{consumer.name}: dependency installation failed before a coherent rollout patch was prepared:\n"
            raise RolloutError(msg + process_failure_detail(exc)) from exc
        baseline_rules = rollout_baseline_rules(
            consumer,
            previous_react_doctor_policy,
            react_doctor_policy_snapshot(repo),
        )
        adopted = adoption_manifest.load(repo)
        baseline_relative = None if adopted is None else adopted.diagnostic_baseline
        allowed_baseline_paths = frozenset(
            (*(() if baseline_relative is None else (baseline_relative,)), *consumer.baseline_paths)
        )
        baseline_path = None if baseline_relative is None else repo / baseline_relative
        if baseline_rules and (baseline_path is None or baseline_relative is None):
            msg = (
                f"{consumer.name}: registry declares promoted baseline rules, but the updated "
                "consumer manifest does not declare diagnostic_baseline"
            )
            raise RolloutError(msg)
        if baseline_path is not None and baseline_relative is not None and baseline_rules:
            baseline_command = [
                *tool_prefix,
                *tool,
                "baseline",
                "update",
                "--output",
                baseline_relative,
                "--trust-repository-code",
            ]
            for selector in baseline_rules:
                baseline_command.extend(("--rule", selector))
            try:
                runner.run(tuple(baseline_command), cwd=repo, env=unauthenticated)
            except subprocess.CalledProcessError as exc:
                msg = f"{consumer.name}: scoped diagnostic baseline generation failed:\n"
                raise RolloutError(msg + process_failure_detail(exc)) from exc
            if not baseline_path.is_file():
                msg = f"{consumer.name}: scoped diagnostic baseline generation did not create {baseline_path}"
                raise RolloutError(msg)
        expected_baseline = None if baseline_path is None or not baseline_path.is_file() else baseline_path.read_bytes()
        doctor = runner.run((*tool_prefix, *tool, "doctor"), cwd=repo, env=unauthenticated, check=False)
        if doctor.returncode != 0:
            failures.append("Standards doctor failed:\n" + verification_detail(doctor))
        bootstrap = run_consumer_bootstrap(repo, tool_prefix, runner, unauthenticated)
        assert_baseline_unchanged(baseline_path, expected_baseline)
        if bootstrap is None and consumer.baseline_update:
            baseline_update = runner.run(
                (*tool_prefix, *consumer.baseline_update),
                cwd=repo,
                env=unauthenticated,
                check=False,
            )
            if baseline_update.returncode != 0:
                failures.append("consumer baseline update failed:\n" + verification_detail(baseline_update))
        consumer_baselines: dict[Path, bytes] = {}
        for relative in consumer.baseline_paths:
            path = repo / relative
            if not path.is_file():
                msg = f"{consumer.name}: consumer baseline update did not create {path}"
                raise RolloutError(msg)
            consumer_baselines[path] = path.read_bytes()
        worktree_paths = changed_paths(repo, runner)
        reject_unsafe_diff(
            worktree_paths,
            allowed_workflow_paths=allowed_workflow_paths,
            allowed_baseline_paths=allowed_baseline_paths,
            allowed_paths=allowed_paths,
        )
        reject_git_metadata(repo, worktree_paths, runner)
        runner.run(("git", "add", "--", *worktree_paths), cwd=repo)
        message = f"{BOT_COMMIT_PREFIX}{version}\n\n{MANAGED_TRAILER}"
        runner.run(("git", "-c", "core.hooksPath=/dev/null", "commit", "-m", message), cwd=repo)
        if bootstrap is not None:
            failures.append("consumer bootstrap failed:\n" + verification_detail(bootstrap))
        else:
            verification_failure_detail = ""
            for attempt in range(MAX_VERIFICATION_ATTEMPTS):
                verification = runner.run(
                    (*tool_prefix, *consumer.verify),
                    cwd=repo,
                    env=consumer_verification_environment(unauthenticated, base_sha),
                    check=False,
                )
                assert_baseline_unchanged(baseline_path, expected_baseline)
                assert_baselines_unchanged(consumer_baselines)
                mutated = amend_safe_changes(
                    repo,
                    runner,
                    allowed_workflow_paths=allowed_workflow_paths,
                    allowed_baseline_paths=allowed_baseline_paths,
                    allowed_paths=allowed_paths,
                )
                if verification.returncode == 0 and not mutated:
                    break
                if mutated and attempt + 1 < MAX_VERIFICATION_ATTEMPTS:
                    continue
                verification_failure_detail = verification_detail(verification)
                if mutated:
                    verification_failure_detail += "\nconsumer verification did not converge after safe auto-fixes"
                break
            if verification_failure_detail:
                failures.append("consumer verification failed:\n" + verification_failure_detail)
        verification_failure = "\n\n".join(failures)[-4000:]
        branch_paths = committed_paths(repo, consumer.branch, runner)
        reject_unsafe_diff(
            branch_paths,
            allowed_workflow_paths=allowed_workflow_paths,
            allowed_baseline_paths=allowed_baseline_paths,
            allowed_paths=allowed_paths,
        )
        reject_git_metadata(
            repo,
            branch_paths,
            runner,
            comparison=f"origin/{consumer.branch}...HEAD",
        )
        assert_consumer_base_unchanged(repo, consumer, base_sha, runner)
        pushed_head_sha = stdout(runner.run(("git", "rev-parse", "HEAD"), cwd=repo))
        if re.fullmatch(r"[0-9a-f]{40}", pushed_head_sha) is None:
            msg = f"{consumer.name}: managed rollout head did not resolve to a full commit SHA"
            raise RolloutError(msg)
        lease = force_with_lease(branch, previous_sha)
        runner.run(("git", "push", lease, "-u", "origin", branch), cwd=repo)
    pull = pull_request(consumer, version, runner)
    body = f"{pr_marker(consumer, version)}\n{desired_marker(version)}\n\n"
    if verification_failure:
        body += (
            f"{VERIFICATION_FAILED_MARKER}\n\n"
            f"Consumer verification is blocked:\n\n```text\n{verification_failure}\n```\n\n"
        )
    body += f"Desired bundle: `code-standards=={version}`.\n\nGenerated by `make rollout`."
    if pull is None:
        created = runner.run(
            (
                "gh",
                "pr",
                "create",
                "--repo",
                consumer.repository,
                "--base",
                consumer.branch,
                "--head",
                branch,
                "--title",
                BOT_COMMIT_PREFIX + version,
                "--body",
                body,
            )
        )
        url = stdout(created)
    else:
        url = str(pull.get("url", ""))
        runner.run(
            (
                "gh",
                "pr",
                "edit",
                "--repo",
                consumer.repository,
                url,
                "--title",
                BOT_COMMIT_PREFIX + version,
                "--body",
                body,
            )
        )
    refreshed_pull = pull_request(consumer, version, runner)
    if refreshed_pull is None:
        return Outcome(
            consumer,
            "blocked",
            url,
            "managed rollout PR could not be read after create or edit",
        )
    refreshed_url = str(refreshed_pull.get("url", url))
    refreshed_identity_is_valid = (
        refreshed_pull.get("headRefName") == rollout_branch(version)
        and refreshed_pull.get("baseRefName") == consumer.branch
        and pr_marker(consumer, version) in str(refreshed_pull.get("body", ""))
    )
    if not refreshed_identity_is_valid:
        return Outcome(
            consumer,
            "blocked",
            refreshed_url,
            "rollout PR ownership marker, head, or base does not match after update",
        )
    if refreshed_pull.get("headRefOid") != pushed_head_sha:
        return Outcome(
            consumer,
            "missing",
            refreshed_url,
            "managed rollout PR head has not refreshed to the pushed commit; reconcile will retry",
        )
    if (provenance := open_pull_commit_provenance(consumer, refreshed_pull, runner)) is not None:
        return provenance
    url = refreshed_url
    if consumer.auto_merge and not verification_failure:
        runner.run(
            (
                "gh",
                "pr",
                "merge",
                "--repo",
                consumer.repository,
                "--auto",
                "--squash",
                "--match-head-commit",
                pushed_head_sha,
                url,
            ),
            check=False,
        )
    if verification_failure:
        return Outcome(consumer, "blocked", url, "consumer verification failed; PR opened for remediation")
    return Outcome(consumer, "pr-open", url)


def plan(version: str, consumers: Sequence[Consumer], runner: CommandRunner) -> Plan:
    sha = verify_release(version, runner)
    return Plan(sha, status(version, consumers, runner))


def apply(
    version: str,
    consumers: Sequence[Consumer],
    runner: CommandRunner,
    *,
    dry_run: bool = False,
) -> tuple[Outcome, ...]:
    verify_release(version, runner)
    selected_channel = max((ROLLOUT_CHANNELS.index(item.channel) for item in consumers), default=0)
    prior = tuple(item for item in consumers if ROLLOUT_CHANNELS.index(item.channel) < selected_channel)
    if prior:
        prior_status = status(version, prior, runner)
        if any(item.state not in {"merged", "already-current"} for item in prior_status):
            blocked = tuple(
                Outcome(item, "blocked", detail="prior rollout wave has not merged cleanly")
                for item in consumers
                if item not in prior
            )
            return (*prior_status, *blocked)
    outcomes: list[Outcome] = []
    for consumer in consumers:
        try:
            outcomes.append(apply_one(consumer, version, runner, dry_run=dry_run))
        except subprocess.CalledProcessError as exc:
            outcomes.append(Outcome(consumer, "error", detail=process_failure_detail(exc)))
        except (OSError, RolloutError) as exc:
            outcomes.append(Outcome(consumer, "error", detail=str(exc)))
    return tuple(outcomes)


def latest_version(runner: CommandRunner) -> str:
    result = runner.run(
        (
            "uvx",
            "--isolated",
            "--python",
            "3.14",
            "--refresh-package",
            "code-standards",
            "--from",
            "code-standards",
            "code-standards",
            "--version",
        )
    )
    match = re.search(r"([0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.-]+)?)", stdout(result))
    if match is None:
        msg = "could not determine the latest published Standards version"
        raise RolloutError(msg)
    return validate_version(match.group(1))


def print_outcomes(version: str, outcomes: Sequence[Outcome], *, source_sha: str = "") -> None:
    adopted = sum(item.state in {"merged", "already-current"} for item in outcomes)
    distributed = sum(item.state in {"pr-open", "merged", "already-current"} for item in outcomes)
    sys.stdout.write(
        json.dumps(
            {
                "version": version,
                "sourceSha": source_sha or None,
                "complete": adopted == len(outcomes),
                "count": f"{adopted}/{len(outcomes)}",
                "distributed": distributed == len(outcomes),
                "distributedCount": f"{distributed}/{len(outcomes)}",
                "adoptedCount": f"{adopted}/{len(outcomes)}",
                "consumers": [item.as_dict() for item in outcomes],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply", "status"):
        command = commands.add_parser(name)
        command.add_argument("--version", required=True)
        command.add_argument("--channel", choices=ROLLOUT_CHANNELS, default="stable")
        if name == "apply":
            command.add_argument("--dry-run", action="store_true")
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--version", help="default: latest published version")
    reconcile.add_argument("--dry-run", action="store_true")
    reconcile.add_argument("--channel", choices=ROLLOUT_CHANNELS, default="stable")
    return result


def execute(args: RolloutArgs, runner: CommandRunner) -> int:
    consumers = select_channel(load_registry(args.registry), args.channel)
    if not consumers:
        msg = f"rollout channel {args.channel!r} selects no consumers"
        raise RolloutError(msg)
    version = validate_version(args.version) if args.version else latest_version(runner)
    if args.command == "plan":
        rollout_plan = plan(version, consumers, runner)
        outcomes = rollout_plan.outcomes
        print_outcomes(version, outcomes, source_sha=rollout_plan.source_sha)
    elif args.command == "status":
        outcomes = status(version, consumers, runner)
        print_outcomes(version, outcomes)
        return 0 if all(item.state in {"merged", "already-current"} for item in outcomes) else 1
    else:
        outcomes = apply(version, consumers, runner, dry_run=args.dry_run)
        print_outcomes(version, outcomes)
        if any(item.state in {"blocked", "error"} for item in outcomes):
            return 1
    return 0


def main(argv: Sequence[str] | None = None, *, runner: CommandRunner | None = None) -> int:
    args = RolloutArgs()
    _ = parser().parse_args(argv, namespace=args)
    try:
        return execute(args, runner or SubprocessRunner())
    except subprocess.CalledProcessError as exc:
        stdout: object = exc.stdout  # pyright: ignore[reportAny] - subprocess exception boundary
        stderr: object = exc.stderr  # pyright: ignore[reportAny] - subprocess exception boundary
        if isinstance(stdout, str) and stdout:
            sys.stderr.write(stdout.rstrip() + "\n")
        if isinstance(stderr, str) and stderr:
            sys.stderr.write(stderr.rstrip() + "\n")
        sys.stderr.write(f"standards-rollout: {exc}\n")
        return 2
    except (OSError, RolloutError) as exc:
        sys.stderr.write(f"standards-rollout: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
