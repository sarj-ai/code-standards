from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest
import yaml

from sarj_standards.cli.main import main
from sarj_standards.libs.adoption import doctor, hooks, launcher, scaffold
from sarj_standards.libs.repository import hooks as repository_hooks


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, env={}, capture_output=True)


def _repository(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    (root / "source.py").write_text("value = 1\n", encoding="utf-8")
    _git(root, "add", "source.py")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
    return root


def _environment(cache: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()  # ruff: ignore[banned-api] -- isolate nested Git hooks from enclosing hook state.
        if not key.startswith("GIT_")
    }
    environment["PRE_COMMIT_HOME"] = str(cache)
    return environment


@dataclass(frozen=True)
class _Probe:
    command: str
    receipt: Path


def _probe(tmp_path: Path, *, status: int) -> _Probe:
    script = tmp_path / "probe.py"
    result = tmp_path / "probe.json"
    script.write_text(
        "import json, subprocess, sys\n"
        "from pathlib import Path\n"
        "names = subprocess.run(['git', 'diff', '--cached', '--name-only', '-z'], "
        "check=True, capture_output=True, env={}).stdout.decode().split('\\0')\n"
        f"Path({str(result)!r}).write_text(json.dumps({{'args': sys.argv[1:], 'paths': [p for p in names if p]}}))\n"
        f"print({'warning fixture: address this finding' if status == 0 else 'error fixture: commit blocked'!r})\n"
        f"raise SystemExit({status})\n",
        encoding="utf-8",
    )
    return _Probe(shlex.join((sys.executable, str(script))), result)


@pytest.mark.parametrize("status", [0, 1])
def test_real_git_precommit_runs_once_and_shows_diagnostics(tmp_path: Path, status: int) -> None:
    repository = _repository(tmp_path / "repository")
    probe = _probe(tmp_path, status=status)
    generated = "repos:\n" + scaffold.precommit_block().replace(launcher.repository_command(), probe.command)
    (repository / ".pre-commit-config.yaml").write_text(generated, encoding="utf-8")
    names = ("typed.pyi", "settings.json", "space name.py", "newline\nname.pyi", "-leading.py")
    for name in names:
        (repository / name).write_text("\n", encoding="utf-8")
    _git(repository, "add", "--", *names)
    environment = _environment(tmp_path / "pre-commit-cache")
    subprocess.run(
        (sys.executable, "-m", "pre_commit", "install", "--hook-type", "pre-commit"),
        cwd=repository,
        check=True,
        env=environment,
        capture_output=True,
    )
    committed = subprocess.run(
        ("git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture change"),
        cwd=repository,
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert committed.returncode == status
    assert (committed.stdout + committed.stderr).count("fixture:") == 1
    assert json.loads(probe.receipt.read_text(encoding="utf-8")) == {
        "args": ["check", "--staged", "--trust-repository-code"],
        "paths": sorted(names),
    }


@pytest.mark.parametrize("state", ["empty", "deleted"])
def test_real_lefthook_runs_without_source_filenames(tmp_path: Path, state: str) -> None:
    repository = _repository(tmp_path / "repository")
    config = repository / "lefthook.yml"
    config.write_text("pre-commit:\n  commands: {}\n", encoding="utf-8")
    probe = _probe(tmp_path, status=0)
    generated = hooks.wire_lefthook_staged_check(repository).contents
    config.write_text(
        generated.replace(launcher.repository_command(), probe.command)
        + "    other:\n      glob: '*.ts'\n      run: echo UNEXPECTED_OTHER_JOB\n",
        encoding="utf-8",
    )
    assert repository_hooks.install(repository) == 0
    installed = repository / ".git" / "hooks" / "pre-commit"
    installed.write_text(
        installed.read_text(encoding="utf-8").replace(launcher.repository_command(), probe.command),
        encoding="utf-8",
    )
    if state == "deleted":
        _git(repository, "rm", "source.py")
    completed = subprocess.run(
        (
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture change",
        ),
        cwd=repository,
        check=False,
        env=_environment(tmp_path / "cache"),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "UNEXPECTED_OTHER_JOB" not in completed.stdout + completed.stderr
    assert json.loads(probe.receipt.read_text(encoding="utf-8")) == {
        "args": ["check", "--staged", "--trust-repository-code"],
        "paths": [] if state == "empty" else ["source.py"],
    }


@pytest.mark.parametrize(
    ("scope", "field", "value"),
    [
        ("hook", "exclude_tags", ["standards"]),
        ("hook", "skip", True),
        ("hook", "only", [{"ref": "main"}]),
        ("hook", "only", False),
        ("hook", "exclude", ["*.py"]),
        ("hook", "files", "git ls-files '*.ts'"),
        ("job", "skip", True),
        ("job", "only", [{"ref": "main"}]),
        ("job", "only", False),
        ("job", "only", []),
        ("job", "glob", "*.ts"),
        ("job", "exclude", ["*.py"]),
        ("job", "root", "src/"),
        ("job", "files", "git ls-files '*.ts'"),
        ("job", "args", "--rule python:SARJ444"),
        ("job", "stage_fixed", True),
        ("group", "skip", True),
        ("group", "only", [{"ref": "main"}]),
        ("group", "only", False),
        ("group", "glob", "*.ts"),
        ("group", "exclude", ["*.py"]),
        ("group", "root", "src/"),
        ("group", "files", "git ls-files '*.ts'"),
    ],
)
def test_conditioned_lefthook_checks_are_not_healthy_or_silently_rewired(
    tmp_path: Path, scope: str, field: str, value: object
) -> None:
    job: dict[str, object] = {
        "name": "standards",
        "run": f"{launcher.repository_command()} check --staged --trust-repository-code",
    }
    pre_commit: dict[str, object] = {"jobs": [job]}
    match scope:
        case "hook":
            pre_commit[field] = value
        case "job":
            job[field] = value
        case _:
            pre_commit["jobs"] = [{field: value, "group": {"jobs": [job]}}]
    config = tmp_path / "lefthook.yml"
    original = yaml.safe_dump({"pre-commit": pre_commit}, sort_keys=False)
    config.write_text(original, encoding="utf-8")
    assert not hooks.lefthook_runs_staged_check(tmp_path)
    with pytest.raises(ValueError, match="unconditional pre-commit job"):
        hooks.wire_lefthook_staged_check(tmp_path)
    assert config.read_text(encoding="utf-8") == original


def test_unconditional_group_and_neutral_options_remain_supported(tmp_path: Path) -> None:
    command = f"{launcher.repository_command()} check --staged --trust-repository-code"
    config = tmp_path / "lefthook.yml"
    config.write_text(
        f"pre-commit:\n  skip: false\n  only: true\n  exclude_tags: [unrelated]\n  jobs:\n    - group:\n        jobs:\n          - run: {command}\n"
        "            only: true\n            root: '.'\n            tags: [metadata]\n",
        encoding="utf-8",
    )
    assert hooks.lefthook_runs_staged_check(tmp_path)
    assert hooks.wire_lefthook_staged_check(tmp_path).contents == config.read_text(encoding="utf-8")


@pytest.mark.parametrize("manager", ["pre-commit", "lefthook"])
def test_duplicate_yaml_keys_cannot_hide_a_disabled_check(tmp_path: Path, manager: str) -> None:
    if manager == "pre-commit":
        config = tmp_path / ".pre-commit-config.yaml"
        config.write_text("repos: []\nrepos:\n" + scaffold.precommit_block(), encoding="utf-8")
        assert not hooks.precommit_runs_staged_check(tmp_path)
    else:
        config = tmp_path / "lefthook.yml"
        command = f"{launcher.repository_command()} check --staged --trust-repository-code"
        config.write_text(
            f"pre-commit: {{}}\npre-commit:\n  commands:\n    standards:\n      run: {command}\n", encoding="utf-8"
        )
        assert not hooks.lefthook_runs_staged_check(tmp_path)


def test_yaml_merge_overrides_preserve_valid_unconditional_jobs(tmp_path: Path) -> None:
    command = hooks.canonical_staged_command(tmp_path)
    config = tmp_path / "lefthook.yml"
    config.write_text(
        "defaults: &defaults\n  skip: true\npre-commit:\n  jobs:\n    - <<: *defaults\n"
        f"      skip: false\n      run: {command}\n",
        encoding="utf-8",
    )
    assert hooks.lefthook_runs_staged_check(tmp_path)
    assert hooks.wire_lefthook_staged_check(tmp_path).contents == config.read_text(encoding="utf-8")


def test_source_checkout_keeps_its_frozen_project_runner(tmp_path: Path) -> None:
    project = tmp_path / "packages" / "standards"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    config = tmp_path / "lefthook.yml"
    legacy = hooks.SOURCE_STAGED_COMMAND.removesuffix(" --trust-repository-code")
    config.write_text(f"pre-commit:\n  commands:\n    standards:\n      run: {legacy}\n", encoding="utf-8")
    assert not hooks.lefthook_runs_staged_check(tmp_path)
    config.write_text(hooks.wire_lefthook_staged_check(tmp_path).contents, encoding="utf-8")
    assert hooks.lefthook_runs_staged_check(tmp_path)
    assert hooks.SOURCE_STAGED_COMMAND in config.read_text(encoding="utf-8")
    assert hooks.wire_lefthook_staged_check(tmp_path).contents == config.read_text(encoding="utf-8")


def test_doctor_rejects_a_precommit_launcher_for_the_wrong_git_stage(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "repository")
    assert main(["--root", str(repository), "setup", "--no-install"]) == 0
    uvx = tmp_path / "uvx"
    uvx.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uvx.chmod(0o755)
    installed = repository / ".git" / "hooks" / "pre-commit"
    installed.write_text(
        f'#!/bin/sh\nexport PATH={shlex.quote(str(tmp_path))}:"$PATH" # sarj-standards: uvx-path\n'
        "# pre_commit\n# hook-type=commit-msg\nexit 0\n",
        encoding="utf-8",
    )
    installed.chmod(0o755)
    findings = doctor.diagnose(repository)
    assert any(finding.id == "doctor.hooks.precommit-install" for finding in findings)
