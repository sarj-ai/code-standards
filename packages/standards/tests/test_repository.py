from __future__ import annotations

import io
import os
from pathlib import Path
import re
import subprocess

import pytest

import sarj_standards.cli.main as cli
from sarj_standards.libs.repository import comment_corpus, hooks, ledger, repository, rule_maintenance


def _policy(**changes: object) -> repository.RepositoryPolicy:
    values: dict[str, object] = {
        "distinctive": ("secret-repo",),
        "contextual": ("quartzscope",),
        "private_excludes": (),
        "forbidden_paths": (),
        "filename_rules": (),
        "rule_families": (),
        "config_references": (),
        "version_references": (),
        "canonical_config_dir": "configs",
        "versions": {},
        "known_manifests": (),
        "known_locks": (),
    }
    values.update(changes)
    return repository.RepositoryPolicy(**values)  # pyright: ignore[reportArgumentType]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()  # ruff: ignore[banned-api] — Git subprocesses need the inherited environment minus hook-local variables.
    local_names = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for name in local_names:
        environment.pop(name, None)
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def _git_repo(root: Path, files: dict[str, str]) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "add", ".")


def _commit(root: Path, message: str) -> None:
    _git(root, "commit", "-qm", message)


def test_load_policy_reads_repository_configuration(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        """
[repository]
canonical_config_dir = "configs"
[repository.private_refs]
distinctive = ["private"]
contextual = ["quartzscope"]
exclude = ["lock"]
[[repository.filename_rules]]
glob = "*.py"
pattern = '^[a-z_]+\\.py$'
label = "snake case"
[[repository.rule_families]]
name = "python"
source = "src"
tests = "tests"
registry = "registry.py"
extension = "py"
test_pattern = "test_{name}.py"
registry_pattern = "rules.{name} import"
[repository.versions]
python = ["pyproject.toml"]
[repository.version_coverage]
manifests = ["pyproject.toml"]
locks = ["uv.lock"]
""",
        encoding="utf-8",
    )

    policy = repository.load_policy(tmp_path)

    assert policy.distinctive == ("private",)
    assert policy.rule_families[0].test_pattern == "test_{name}.py"
    assert policy.known_locks == ("uv.lock",)


def test_load_policy_reads_private_patterns_from_untracked_file(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text("[repository.private_refs]\nexclude = ['lock']\n")
    (tmp_path / ".sarj-private-refs.toml").write_text(
        "[private_refs]\ndistinctive = ['confidential-project']\ncontextual = ['workspace']\n"
    )

    policy = repository.load_policy(tmp_path)

    assert policy.distinctive == ("confidential-project",)
    assert policy.contextual == ("workspace",)
    assert policy.private_excludes == ("lock",)


def test_load_policy_rejects_a_malformed_rule_instead_of_disabling_it(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        "[repository]\n[[repository.filename_rules]]\nglob = '*.py'\npattern = '.*'\n"
    )

    with pytest.raises(ValueError, match="filename rule requires: label"):
        repository.load_policy(tmp_path)


def test_load_policy_rejects_unknown_repository_fields(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text("[repository]\nfilename_rule = []\n")

    with pytest.raises(ValueError, match="unknown repository field"):
        repository.load_policy(tmp_path)


def test_load_policy_rejects_unknown_nested_fields(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        "[repository]\n[[repository.filename_rules]]\nglob = '*.py'\npattern = '.*'\nlabel = 'python'\nlabels = []\n"
    )

    with pytest.raises(ValueError, match="unknown filename rule field"):
        repository.load_policy(tmp_path)


def test_load_policy_wraps_invalid_regexes(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        "[repository]\n[[repository.filename_rules]]\nglob = '*.py'\npattern = '['\nlabel = 'python'\n"
    )

    with pytest.raises(ValueError, match="invalid filename rule regex"):
        repository.load_policy(tmp_path)


def test_private_reference_check_without_secret_fails_closed(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"conflicted.py": "<<<<<<< branch\n"})

    with pytest.raises(ValueError, match="policy is unavailable"):
        repository.check_private_refs(
            tmp_path,
            _policy(distinctive=(), contextual=()),
            commits=None,
        )


def test_default_repository_check_delegates_private_refs_to_trusted_ci(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"clean.py": "value = 1\n"})
    (tmp_path / ".sarj-standards.toml").write_text("[repository]\n")

    assert repository.check(tmp_path) == []


def test_explicit_private_check_fails_without_a_private_policy(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"clean.py": "value = 1\n"})
    (tmp_path / ".sarj-standards.toml").write_text("[repository]\n")

    with pytest.raises(ValueError, match="policy is unavailable"):
        repository.check(tmp_path, selected=frozenset({"private-refs"}))


def test_private_names_are_literals_not_regular_expressions(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"clean.py": "name = 'secretXrepo'\n", "leak.py": "name = 'secret.repo'\n"})

    findings = repository.check_private_refs(
        tmp_path,
        _policy(distinctive=("secret.repo",), contextual=()),
        commits=None,
    )

    assert [finding.where for finding in findings] == ["leak.py"]


def test_private_name_variants_are_explicit_literals(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"space.py": "name = 'client alpha zone'\n", "dash.py": "name = 'client-alpha-zone'\n"})

    findings = repository.check_private_refs(
        tmp_path,
        _policy(distinctive=("client alpha zone", "client-alpha-zone"), contextual=()),
        commits=None,
    )

    assert [finding.where for finding in findings] == ["dash.py", "space.py"]


def test_private_policy_rejects_regex_fields(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text("[repository.private_refs]\ndistinctive_regex = ['client.*']\n")

    with pytest.raises(ValueError, match="unknown private_refs field"):
        repository.load_policy(tmp_path)


def test_private_scan_reads_a_symlink_target_as_data(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"link": "placeholder"})
    (tmp_path / "link").unlink()
    (tmp_path / "link").symlink_to("/confidential-project")

    findings = repository.check_private_refs(
        tmp_path,
        _policy(distinctive=("confidential-project",), contextual=()),
        commits=None,
    )

    assert [finding.where for finding in findings] == ["link"]


def test_trusted_policy_scans_a_separate_candidate_checkout(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    candidate = tmp_path / "candidate"
    trusted.mkdir()
    candidate.mkdir()
    (trusted / ".sarj-standards.toml").write_text("[repository.private_refs]\n")
    secret = tmp_path / "private.toml"
    secret.write_text("[private_refs]\ndistinctive = ['confidential-project']\n")
    _git_repo(candidate, {"leak.py": "name = 'confidential-project'\n"})

    findings = repository.check(
        candidate,
        selected=frozenset({"private-refs"}),
        policy_root=trusted,
        private_refs_path=secret,
    )

    assert [finding.where for finding in findings] == ["leak.py"]


def test_trusted_policy_cannot_run_candidate_path_checks(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    candidate = tmp_path / "candidate"
    trusted.mkdir()
    candidate.mkdir()

    with pytest.raises(ValueError, match="restricted to the private-refs check"):
        repository.check(candidate, policy_root=trusted)


def test_private_reference_check_scans_tracked_files(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"clean.py": "value = 1\n", "leak.py": "# secret-repo/api\n"})

    findings = repository.check_private_refs(tmp_path, _policy(), commits=None)

    assert [(finding.where, finding.message) for finding in findings] == [
        ("leak.py", "private repository or client reference")
    ]


def test_private_reference_check_scans_tracked_paths(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"secret-repo.txt": "public content\n"})

    findings = repository.check_private_refs(tmp_path, _policy(), commits=None)

    assert [(finding.where, finding.message) for finding in findings] == [
        ("secret-repo.txt", "private repository or client reference")
    ]


def test_private_reference_check_scans_intermediate_commit_blobs(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"value.txt": "public\n"})
    _commit(tmp_path, "base")
    (tmp_path / "value.txt").write_text("secret-repo/api\n")
    _git(tmp_path, "add", "value.txt")
    _commit(tmp_path, "transient")
    transient = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    (tmp_path / "value.txt").write_text("public again\n")
    _git(tmp_path, "add", "value.txt")
    _commit(tmp_path, "clean")

    findings = repository.check_private_refs(tmp_path, _policy(), commits="HEAD~2..HEAD")

    assert [(finding.where, finding.message) for finding in findings] == [
        (f"{transient}:value.txt", "private repository or client reference")
    ]


def test_private_reference_check_scans_intermediate_paths_and_symlink_targets(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"value.txt": "public\n"})
    _commit(tmp_path, "base")
    (tmp_path / "secret-repo-link").symlink_to("quartzscope/private")
    _git(tmp_path, "add", "secret-repo-link")
    _commit(tmp_path, "transient")
    transient = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    (tmp_path / "secret-repo-link").unlink()
    _git(tmp_path, "add", "-u")
    _commit(tmp_path, "clean")

    findings = repository.check_private_refs(tmp_path, _policy(), commits="HEAD~2..HEAD")

    assert (f"{transient}:secret-repo-link", "private repository or client reference") in {
        (finding.where, finding.message) for finding in findings
    }


def test_private_reference_check_scans_merge_resolution_blobs(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"left.txt": "base\n", "right.txt": "base\n", "value.txt": "public\n"})
    _commit(tmp_path, "base")
    base = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    _git(tmp_path, "checkout", "-qb", "left")
    (tmp_path / "left.txt").write_text("left\n")
    _git(tmp_path, "add", "left.txt")
    _commit(tmp_path, "left")
    _git(tmp_path, "checkout", "-qb", "right", base)
    (tmp_path / "right.txt").write_text("right\n")
    _git(tmp_path, "add", "right.txt")
    _commit(tmp_path, "right")
    _git(tmp_path, "merge", "--no-ff", "--no-commit", "left")
    (tmp_path / "value.txt").write_text("secret-repo/api\n")
    _git(tmp_path, "add", "value.txt")
    _commit(tmp_path, "merge resolution")
    merge = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    (tmp_path / "value.txt").write_text("public again\n")
    _git(tmp_path, "add", "value.txt")
    _commit(tmp_path, "clean")

    findings = repository.check_private_refs(tmp_path, _policy(), commits=f"{base}..HEAD")

    assert (f"{merge}:value.txt", "private repository or client reference") in {
        (finding.where, finding.message) for finding in findings
    }


def test_private_reference_check_scans_unmaterialized_gitlink_paths(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"value.txt": "public\n"})
    _commit(tmp_path, "base")
    revision = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    _git(tmp_path, "update-index", "--add", "--cacheinfo", f"160000,{revision},secret-repo-module")

    findings = repository.check_private_refs(tmp_path, _policy(), commits=None)

    assert [(finding.where, finding.message) for finding in findings] == [
        ("secret-repo-module", "private repository or client reference")
    ]


def test_private_reference_check_scans_commit_messages(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"clean.py": "value = 1\n"})
    _commit(tmp_path, "secret-repo change")

    findings = repository.check_private_refs(tmp_path, _policy(), commits="HEAD")

    assert findings[0].where == _git(tmp_path, "rev-parse", "HEAD").stdout.strip()


def test_private_reference_check_ignores_generated_github_merge_subject(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"left.txt": "base\n", "right.txt": "base\n"})
    _commit(tmp_path, "base")
    base = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    initial_branch = _git(tmp_path, "branch", "--show-current").stdout.strip()
    _git(tmp_path, "checkout", "-qb", "feature")
    (tmp_path / "left.txt").write_text("feature\n")
    _git(tmp_path, "add", "left.txt")
    _commit(tmp_path, "feature")
    _git(tmp_path, "checkout", "-q", initial_branch)
    (tmp_path / "right.txt").write_text("main\n")
    _git(tmp_path, "add", "right.txt")
    _commit(tmp_path, "main")
    _git(tmp_path, "merge", "--no-ff", "-m", "Merge pull request #276 from sarj-ai/agent/safe", "feature")

    findings = repository.check_private_refs(
        tmp_path,
        _policy(contextual=("agent",)),
        commits=f"{base}..HEAD",
    )

    assert findings == []


def test_private_reference_check_scans_generated_github_merge_body(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"left.txt": "base\n", "right.txt": "base\n"})
    _commit(tmp_path, "base")
    base = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    initial_branch = _git(tmp_path, "branch", "--show-current").stdout.strip()
    _git(tmp_path, "checkout", "-qb", "feature")
    (tmp_path / "left.txt").write_text("feature\n")
    _git(tmp_path, "add", "left.txt")
    _commit(tmp_path, "feature")
    _git(tmp_path, "checkout", "-q", initial_branch)
    (tmp_path / "right.txt").write_text("main\n")
    _git(tmp_path, "add", "right.txt")
    _commit(tmp_path, "main")
    _git(
        tmp_path,
        "merge",
        "--no-ff",
        "-m",
        "Merge pull request #276 from sarj-ai/agent/safe",
        "-m",
        "secret-repo change",
        "feature",
    )

    findings = repository.check_private_refs(tmp_path, _policy(), commits=f"{base}..HEAD")

    assert findings[0].where == _git(tmp_path, "rev-parse", "HEAD").stdout.strip()


def test_private_reference_cli_can_redact_findings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _git_repo(tmp_path, {"secret-repo.txt": "public\n"})
    (tmp_path / ".sarj-standards.toml").write_text("[repository.private_refs]\ndistinctive = ['secret-repo']\n")

    status = cli.main(["--root", str(tmp_path), "maintain", "check", "--only", "private-refs", "--quiet"])

    assert status == 1
    assert capsys.readouterr().out == "repository policy failed\n"


def test_git_fixtures_ignore_a_hooks_repository_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    inner = tmp_path / "inner"
    outer.mkdir()
    inner.mkdir()
    _git_repo(outer, {"outer.py": "value = 1\n"})
    _commit(outer, "outer")
    outer_head = _git(outer, "rev-parse", "HEAD").stdout

    monkeypatch.setenv("GIT_DIR", str(outer / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outer))
    monkeypatch.setenv("GIT_INDEX_FILE", str(outer / ".git" / "index"))
    _git_repo(inner, {"inner.py": "value = 2\n"})
    _commit(inner, "inner")

    assert _git(outer, "rev-parse", "HEAD").stdout == outer_head
    assert _git(inner, "show", "--format=%s", "--no-patch", "HEAD").stdout.strip() == "inner"


def test_repository_checks_ignore_a_hooks_repository_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outer = tmp_path / "outer"
    inner = tmp_path / "inner"
    outer.mkdir()
    inner.mkdir()
    _git_repo(outer, {"outer.py": "value = 1\n"})
    _commit(outer, "outer")
    _git_repo(inner, {"leak.py": "# secret-repo/api\n"})

    monkeypatch.setenv("GIT_DIR", str(outer / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outer))
    monkeypatch.setenv("GIT_INDEX_FILE", str(outer / ".git" / "index"))

    findings = repository.check_private_refs(inner, _policy(), commits=None)

    assert [(finding.where, finding.message) for finding in findings] == [
        ("leak.py", "private repository or client reference")
    ]


def test_ci_history_requires_full_checkout_for_test_jobs(tmp_path: Path) -> None:
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  tests:\n    steps:\n      - uses: actions/checkout@v4\n      - run: pytest\n",
        encoding="utf-8",
    )

    findings = repository.check_ci_history(tmp_path)

    assert findings[0].where == ".github/workflows/ci.yml:tests"


def test_file_conventions_pair_rules_tests_and_registry(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"src/example.py": "pass\n", "registry.py": ""})
    (tmp_path / "configs").mkdir()
    family = repository.RuleFamily(
        "python", "src", "tests", "registry.py", "py", "test_{name}.py", "rules.{name} import"
    )

    findings = repository.check_file_conventions(tmp_path, _policy(rule_families=(family,)))

    assert {finding.message for finding in findings} >= {
        "missing tests/test_example.py",
        "rule is absent from its registry",
    }


def test_file_conventions_reject_forbidden_paths(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"scripts/check.sh": "#!/bin/sh\n"})
    (tmp_path / "configs").mkdir()

    findings = repository.check_file_conventions(tmp_path, _policy(forbidden_paths=("scripts/*",)))

    assert findings[0].where == "scripts/check.sh"


def test_file_conventions_allow_audit_records(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"docs/audits/finding.md": "# Finding\n"})
    (tmp_path / "configs").mkdir()

    findings = repository.check_file_conventions(tmp_path, _policy())

    assert not findings


@pytest.mark.parametrize("document", ["CODE_OF_CONDUCT.md", "CONTRIBUTING.md"])
def test_file_conventions_allow_essential_community_documents(tmp_path: Path, document: str) -> None:
    _git_repo(tmp_path, {document: "# Project policy\n"})
    (tmp_path / "configs").mkdir()

    findings = repository.check_file_conventions(tmp_path, _policy())

    assert not findings


def test_file_conventions_reject_config_outside_canonical_dir(tmp_path: Path) -> None:
    _git_repo(
        tmp_path, {"package/pyproject.toml": 'extend = "local.toml"\n', "package/local.toml": "line-length = 100\n"}
    )
    (tmp_path / "configs").mkdir()
    reference = repository.ConfigReference("package/pyproject.toml", re.compile(r'^extend = "([^"]+)"$', re.MULTILINE))

    findings = repository.check_file_conventions(tmp_path, _policy(config_references=(reference,)))

    assert findings[0].message == "extended config is outside configs"


def test_file_conventions_allow_exact_managed_root_configs(tmp_path: Path) -> None:
    config = "line-length = 100\n"
    _git_repo(
        tmp_path,
        {
            "configs/ruff.strict.toml": config,
            ".ruff-strict.toml": config,
            "packages/python/pyproject.toml": 'extend = "../../.ruff-strict.toml"\n',
        },
    )
    reference = repository.ConfigReference(
        "packages/*/pyproject.toml", re.compile(r'^extend = "([^"]+)"$', re.MULTILINE)
    )

    findings = repository.check_file_conventions(tmp_path, _policy(config_references=(reference,)))

    assert not findings


def test_file_conventions_reject_drifted_managed_root_config(tmp_path: Path) -> None:
    _git_repo(
        tmp_path,
        {
            "configs/ruff.strict.toml": "line-length = 100\n",
            ".ruff-strict.toml": "line-length = 80\n",
            "packages/python/pyproject.toml": 'extend = "../../.ruff-strict.toml"\n',
        },
    )
    reference = repository.ConfigReference(
        "packages/*/pyproject.toml", re.compile(r'^extend = "([^"]+)"$', re.MULTILINE)
    )

    findings = repository.check_file_conventions(tmp_path, _policy(config_references=(reference,)))

    assert [(finding.where, finding.message) for finding in findings] == [
        (
            ".ruff-strict.toml",
            "generated config drifted from configs/ruff.strict.toml; run `sarj-standards setup`",
        )
    ]


def test_file_conventions_reject_extra_exact_config_copy(tmp_path: Path) -> None:
    config = "line-length = 100\n"
    _git_repo(
        tmp_path,
        {
            "configs/ruff.strict.toml": config,
            ".ruff-strict.toml": config,
            "package/copied.toml": config,
        },
    )

    findings = repository.check_file_conventions(tmp_path, _policy())

    assert [(finding.where, finding.message) for finding in findings] == [
        ("package/copied.toml", "duplicates configs/ruff.strict.toml; remove the unmanaged copy")
    ]


def test_version_references_detect_lock_drift(tmp_path: Path) -> None:
    _git_repo(
        tmp_path,
        {
            "pyproject.toml": '[project]\nversion = "2.0.0"\n',
            "uv.lock": '[[package]]\nname = "demo"\nversion = "1.0.0"\n',
        },
    )
    reference = repository.VersionReference("uv.lock", "uv-lock", "demo", "demo")
    policy = _policy(versions={"demo": ("pyproject.toml",)}, version_references=(reference,), known_locks=("uv.lock",))

    findings = repository.check_versions(tmp_path, policy)

    assert findings[0].message == "demo is 1.0.0, expected 2.0.0"


def test_comment_corpus_defaults_to_an_aggregate_summary(tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text('"""One. Two."""\n# Explain why.\n', encoding="utf-8")
    output = io.StringIO()

    assert comment_corpus.emit_summary([tmp_path], output) == 0
    assert output.getvalue().startswith("repository\t0-1\t2\t3+\n")
    assert "repository-1\t1\t1\t0\n" in output.getvalue()
    assert tmp_path.name not in output.getvalue()
    assert "One. Two." not in output.getvalue()


def test_comment_corpus_writes_text_to_a_private_new_file(tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text("# Sensitive explanation.\n", encoding="utf-8")
    destination = tmp_path / "corpus.jsonl"

    assert comment_corpus.write_records([tmp_path], destination) == 0
    assert '"text": "Sensitive explanation."' in destination.read_text(encoding="utf-8")
    assert destination.stat().st_mode & 0o777 == 0o600

    with pytest.raises(FileExistsError):
        comment_corpus.write_records([tmp_path], destination)


def test_comment_corpus_skips_symlinked_files(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("# Sensitive explanation.\n", encoding="utf-8")
    (tmp_path / "linked.py").symlink_to(outside)
    output = io.StringIO()

    comment_corpus.emit_summary([tmp_path], output)

    assert output.getvalue() == "repository\t0-1\t2\t3+\n"


def test_comment_corpus_rejects_a_file_swapped_to_a_symlink(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("# Initial comment.\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("# Sensitive explanation.\n", encoding="utf-8")
    original_open = os.open

    def swap_before_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == "example.py":
            source.unlink()
            source.symlink_to(outside)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("sarj_standards.libs.repository.comment_corpus.os.open", swap_before_open)

    assert list(comment_corpus.records([tmp_path])) == []


def test_comment_corpus_removes_partial_output_after_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class ExtractionError(Exception):
        pass

    destination = tmp_path / "corpus.jsonl"
    failure = ExtractionError()

    def fail(_roots: object) -> object:
        raise failure

    monkeypatch.setattr(comment_corpus, "records", fail)

    with pytest.raises(ExtractionError):
        comment_corpus.write_records([tmp_path], destination)

    assert not destination.exists()
    assert list(tmp_path.glob(".corpus.jsonl.*.tmp")) == []


def test_comment_corpus_does_not_remove_a_colliding_staging_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "corpus.jsonl"
    staging = tmp_path / ".corpus.jsonl.collision.tmp"
    staging.mkdir()
    marker = staging / "owned-by-another-process"
    marker.write_text("keep", encoding="utf-8")

    def collision_token(_length: int) -> str:
        return "collision"

    monkeypatch.setattr("sarj_standards.libs.repository.comment_corpus.secrets.token_hex", collision_token)

    with pytest.raises(FileExistsError):
        comment_corpus.write_records([tmp_path], destination)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert not destination.exists()


def test_comment_corpus_rejects_a_staging_file_swap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text("# Initial comment.\n", encoding="utf-8")
    destination = tmp_path / "corpus.jsonl"
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text('{"text": "attacker controlled"}\n', encoding="utf-8")
    original_link = os.link

    def swap_before_link(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        assert src_dir_fd is not None
        os.unlink(source, dir_fd=src_dir_fd)
        os.symlink(replacement, source, dir_fd=src_dir_fd)
        original_link(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr("sarj_standards.libs.repository.comment_corpus.os.link", swap_before_link)

    with pytest.raises(RuntimeError, match="staging file changed"):
        comment_corpus.write_records([tmp_path], destination)

    assert replacement.read_text(encoding="utf-8") == '{"text": "attacker controlled"}\n'
    assert destination.is_symlink()
    assert destination.resolve() == replacement
    staging_directories = list(tmp_path.glob(".corpus.jsonl.*.tmp"))
    assert len(staging_directories) == 1
    assert (staging_directories[0] / "records").is_symlink()


def test_comment_corpus_does_not_delete_a_destination_replaced_after_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "example.py").write_text("# Initial comment.\n", encoding="utf-8")
    destination = tmp_path / "corpus.jsonl"
    original_fsync = os.fsync
    calls = 0

    def replace_before_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            destination.unlink()
            destination.write_text("owned by another process", encoding="utf-8")
            error = OSError("directory fsync failed")
            raise error
        original_fsync(descriptor)

    monkeypatch.setattr("sarj_standards.libs.repository.comment_corpus.os.fsync", replace_before_directory_fsync)

    with pytest.raises(OSError, match="directory fsync failed"):
        comment_corpus.write_records([tmp_path], destination)

    assert destination.read_text(encoding="utf-8") == "owned by another process"
    assert list(tmp_path.glob(".corpus.jsonl.*.tmp")) == []


def test_comment_corpus_does_not_use_or_remove_a_swapped_staging_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "corpus.jsonl"
    staging = tmp_path / ".corpus.jsonl.swap.tmp"
    moved = tmp_path / "original-staging"
    original_open = os.open

    def swap_before_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == staging.name:
            staging.rename(moved)
            staging.mkdir()
        return original_open(path, flags, mode, dir_fd=dir_fd)

    def swap_token(_length: int) -> str:
        return "swap"

    monkeypatch.setattr("sarj_standards.libs.repository.comment_corpus.secrets.token_hex", swap_token)
    monkeypatch.setattr("sarj_standards.libs.repository.comment_corpus.os.open", swap_before_open)

    with pytest.raises(RuntimeError, match="staging directory changed"):
        comment_corpus.write_records([tmp_path], destination)

    assert staging.is_dir()
    assert moved.is_dir()
    assert list(staging.iterdir()) == []
    assert list(moved.iterdir()) == []
    assert not destination.exists()


def test_comment_corpus_rejects_a_nonsticky_shared_output_directory(tmp_path: Path) -> None:
    output_directory = tmp_path / "shared"
    output_directory.mkdir(mode=0o777)
    output_directory.chmod(0o777)

    with pytest.raises(PermissionError, match="group/world writable"):
        comment_corpus.write_records([tmp_path], output_directory / "corpus.jsonl")


def test_comment_corpus_does_not_open_parent_when_token_generation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class TokenError(Exception):
        pass

    opened: list[object] = []
    failure = TokenError()
    original_open = os.open

    def fail_token(_length: int) -> str:
        raise failure

    def record_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        opened.append((path, flags, mode, dir_fd))
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("sarj_standards.libs.repository.comment_corpus.secrets.token_hex", fail_token)
    monkeypatch.setattr("sarj_standards.libs.repository.comment_corpus.os.open", record_open)

    with pytest.raises(TokenError):
        comment_corpus.write_records([tmp_path], tmp_path / "corpus.jsonl")

    assert opened == []


def test_comment_corpus_closes_records_descriptor_when_fstat_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "corpus.jsonl"
    original_fstat = os.fstat
    calls = 0
    records_descriptor = -1

    def fail_records_fstat(descriptor: int) -> os.stat_result:
        nonlocal calls, records_descriptor
        calls += 1
        if calls == 3:
            records_descriptor = descriptor
            error = OSError("records fstat failed")
            raise error
        return original_fstat(descriptor)

    monkeypatch.setattr("sarj_standards.libs.repository.comment_corpus.os.fstat", fail_records_fstat)

    with pytest.raises(OSError, match="records fstat failed"):
        comment_corpus.write_records([tmp_path], destination)

    with pytest.raises(OSError, match="Bad file descriptor"):
        original_fstat(records_descriptor)
    assert not destination.exists()
    assert list(tmp_path.glob(".corpus.jsonl.*.tmp")) == []


def test_hook_install_resolves_environment_binaries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def which(name: str, *, path: str | None = None) -> str:
        assert path is not None
        return f"/bin/{name}"

    def run(argv: list[str], **_kwargs: object) -> None:
        calls.append(argv)

    def git(_root: Path, *_args: str) -> str:
        return ".git/hooks/pre-commit\n"

    monkeypatch.setattr("sarj_standards.libs.repository.hooks.shutil.which", which)
    monkeypatch.setattr("sarj_standards.libs.repository.hooks.subprocess.run", run)
    monkeypatch.setattr("sarj_standards.libs.repository.hooks._git", git)
    hook = tmp_path / ".git/hooks/pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "lefthook.yml").write_text("pre-commit: {}\n", encoding="utf-8")

    hooks.install(tmp_path)

    assert calls[0] == ["/bin/lefthook", "install", "-f"]
    assert 'LEFTHOOK_BIN="/bin/lefthook"' in hook.read_text(encoding="utf-8")


def test_live_rule_inventory_is_machine_readable() -> None:
    root = Path(__file__).parents[3]

    inventory = rule_maintenance.inventory(root)

    assert inventory
    assert {item["family"] for item in inventory} == {"python", "sql", "iac", "text", "typescript"}


def test_live_rule_inventory_does_not_depend_on_consumer_repository_layout(tmp_path: Path) -> None:
    inventory = rule_maintenance.inventory(tmp_path)

    typescript = [item for item in inventory if item["family"] == "typescript"]
    assert typescript
    assert {item["id"] for item in typescript} == set(ledger.load().rules[ledger.ESLINT])
