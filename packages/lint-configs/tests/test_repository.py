from __future__ import annotations

import io
import os
from pathlib import Path
import re
import subprocess
from typing import TYPE_CHECKING

from sarj_lint_configs import comment_corpus, hooks, repository, rule_maintenance


if TYPE_CHECKING:
    import pytest


def _policy(**changes: object) -> repository.RepositoryPolicy:
    values: dict[str, object] = {
        "distinctive": ("secret-repo",),
        "contextual": ("portal",),
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
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "add", ".")


def _commit(root: Path, message: str) -> None:
    _git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        message,
    )


def test_load_policy_reads_repository_configuration(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        """
[repository]
canonical_config_dir = "configs"
[repository.private_refs]
distinctive = ["private"]
contextual = ["portal"]
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


def test_private_reference_check_scans_tracked_files(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"clean.py": "value = 1\n", "leak.py": "# secret-repo/api\n"})

    findings = repository.check_private_refs(tmp_path, _policy(), commits=None)

    assert [(finding.where, finding.message) for finding in findings] == [
        ("leak.py", "private repository or client reference")
    ]


def test_private_reference_check_scans_commit_messages(tmp_path: Path) -> None:
    _git_repo(tmp_path, {"clean.py": "value = 1\n"})
    _commit(tmp_path, "secret-repo change")

    findings = repository.check_private_refs(tmp_path, _policy(), commits="HEAD")

    assert findings[0].where == "HEAD"


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


def test_file_conventions_reject_config_outside_canonical_dir(tmp_path: Path) -> None:
    _git_repo(
        tmp_path, {"package/pyproject.toml": 'extend = "local.toml"\n', "package/local.toml": "line-length = 100\n"}
    )
    (tmp_path / "configs").mkdir()
    reference = repository.ConfigReference("package/pyproject.toml", re.compile(r'^extend = "([^"]+)"$', re.MULTILINE))

    findings = repository.check_file_conventions(tmp_path, _policy(config_references=(reference,)))

    assert findings[0].message == "extended config is outside configs"


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


def test_comment_corpus_emits_json_and_summary(tmp_path: Path) -> None:
    (tmp_path / "example.py").write_text('"""One. Two."""\n# Explain why.\n', encoding="utf-8")
    output = io.StringIO()

    assert comment_corpus.emit([tmp_path], summary=False, output=output) == 0
    assert '"kind": "docstring"' in output.getvalue()

    summary = io.StringIO()
    comment_corpus.emit([tmp_path], summary=True, output=summary)
    assert summary.getvalue().startswith("repository\t0-1\t2\t3+\n")


def test_hook_install_resolves_environment_binaries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def which(name: str, *, path: str | None = None) -> str:
        assert path is not None
        return f"/bin/{name}"

    def run(argv: list[str], **_kwargs: object) -> None:
        calls.append(argv)

    def git(_root: Path, *_args: str) -> str:
        return ".git/hooks/pre-commit\n"

    monkeypatch.setattr("sarj_lint_configs.hooks.shutil.which", which)
    monkeypatch.setattr("sarj_lint_configs.hooks.subprocess.run", run)
    monkeypatch.setattr("sarj_lint_configs.hooks._git", git)
    hook = tmp_path / ".git/hooks/pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "lefthook.yml").write_text("pre-commit: {}\n", encoding="utf-8")

    hooks.install(tmp_path)

    assert calls[0] == ["/bin/lefthook", "install", "-f"]
    assert 'LEFTHOOK_BIN="/bin/sarj-lefthook"' in hook.read_text(encoding="utf-8")


def test_live_rule_inventory_is_machine_readable() -> None:
    root = Path(__file__).parents[3]

    inventory = rule_maintenance.inventory(root)

    assert inventory
    assert {item["family"] for item in inventory} == {"python", "sql", "iac", "text", "typescript"}
