from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field
import pytest
import yaml


SCRIPT = Path(__file__).resolve().parents[3] / ".github/scripts/ci-scope.sh"
SCOPES = frozenset(
    {
        "bootstrap",
        "python",
        "sql",
        "iac",
        "typescript",
        "tsconfig",
        "standards",
        "docs",
        "mobile",
        "codeql-python",
        "codeql-javascript-typescript",
        "docs-audit",
    }
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-c", "user.name=CI Test", "-c", "user.email=ci@example.invalid", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "commit", "--allow-empty", "-qm", "initial")
    return tmp_path


def route(root: Path, base: str, head: str, *, event: str = "pull_request") -> frozenset[str]:
    output = root / "scope-output"
    subprocess.run(
        ("bash", str(SCRIPT), event, base, head, str(output)),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return frozenset(line.removesuffix("=true") for line in output.read_text().splitlines() if line.endswith("=true"))


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(
            "packages/python/src/rule.py", {"python", "standards", "docs", "codeql-python"}, id="python-consumers"
        ),
        pytest.param(
            "packages/contracts/src/sarj_rule_contracts/contracts.py",
            {"python", "sql", "iac", "standards", "docs", "codeql-python"},
            id="shared-contract-consumers",
        ),
        pytest.param(
            "packages/typescript/src/rule.ts",
            {"typescript", "standards", "docs", "codeql-javascript-typescript"},
            id="typescript-consumers",
        ),
        pytest.param("packages/sql/src/rule.py", {"sql", "standards", "docs", "codeql-python"}, id="sql-consumers"),
        pytest.param("packages/iac/src/rule.py", {"iac", "standards", "docs", "codeql-python"}, id="iac-consumers"),
        pytest.param(
            "packages/bootstrap/src/cli.py",
            {"bootstrap", "standards", "docs", "codeql-python"},
            id="bootstrap-consumers",
        ),
        pytest.param(
            "packages/tsconfig/strict.json",
            {"tsconfig", "standards", "docs"},
            id="tsconfig-consumers",
        ),
        pytest.param("apps/docs/src/content/guide.mdx", {"docs"}, id="documentation-prose"),
        pytest.param(
            "apps/docs/package-lock.json",
            {"docs", "standards", "docs-audit"},
            id="docs-lock-audit",
        ),
        pytest.param(
            "packages/standards/src/sarj_standards/api.py",
            {"standards", "docs", "mobile", "codeql-python"},
            id="runner-mobile-dependency",
        ),
        pytest.param("packages/standards/tests/test_api.py", {"standards", "codeql-python"}, id="runner-test-only"),
        pytest.param("packages/standards/src/sarj_standards/configs/ruff.strict.toml", SCOPES, id="shared-config"),
        pytest.param(".github/scripts/ci-scope.sh", SCOPES, id="routing-change"),
        pytest.param(".sarj-standards.toml", {"standards", "docs"}, id="bundle-manifest"),
        pytest.param("packages/standards/uv.lock", {"standards", "docs", "mobile"}, id="runner-dependencies"),
        pytest.param(
            "packages/standards/src/sarj_standards/configs/eslint.strict.mjs",
            {"typescript", "standards", "docs", "codeql-javascript-typescript"},
            id="eslint-consumer-config",
        ),
        pytest.param("new-package/source.py", SCOPES, id="unknown-owner"),
        pytest.param(
            "packages/python/src/name with\na newline.py",
            {"python", "standards", "docs", "codeql-python"},
            id="nul-delimited-filename",
        ),
    ],
)
def test_pr_selects_owners_and_consumers(repository: Path, path: str, expected: set[str]) -> None:
    base = git(repository, "rev-parse", "HEAD")
    source = repository / path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("fixture\n")
    git(repository, "add", "--", path)
    git(repository, "commit", "-qm", "change")
    assert route(repository, base, git(repository, "rev-parse", "HEAD")) == expected


def test_cross_package_rename_checks_old_and_new_owners(repository: Path) -> None:
    source = repository / "packages/python/fixture.py"
    source.parent.mkdir(parents=True)
    source.write_text("unchanged contents\n")
    git(repository, "add", "packages")
    git(repository, "commit", "-qm", "source")
    base = git(repository, "rev-parse", "HEAD")
    destination = repository / "packages/sql/fixture.py"
    destination.parent.mkdir()
    git(repository, "mv", str(source), str(destination))
    git(repository, "commit", "-qm", "move")
    assert route(repository, base, git(repository, "rev-parse", "HEAD")) == {
        "python",
        "sql",
        "standards",
        "docs",
        "codeql-python",
    }


@pytest.mark.parametrize(
    ("source_path", "owner", "local_linter", "security"),
    [
        ("packages/typescript/src/rules/new-rule.ts", "typescript", None, "codeql-javascript-typescript"),
        ("packages/python/src/new_rule.py", "python", "sarj-python-lint", "codeql-python"),
        ("packages/sql/src/new_rule.py", "sql", "sarj-sql-lint", "codeql-python"),
        ("packages/iac/src/new_rule.py", "iac", "sarj-iac-lint", "codeql-python"),
        (
            "packages/standards/src/sarj_standards/libs/linting/textlint.py",
            "standards",
            None,
            "codeql-python",
        ),
    ],
    ids=["typescript", "python", "sql", "iac", "text"],
)
def test_rule_with_generated_catalog_and_version_bump_skips_unrelated_jobs(
    repository: Path, source_path: str, owner: str, local_linter: str | None, security: str
) -> None:
    project = repository / "packages/standards/pyproject.toml"
    project.parent.mkdir(parents=True)
    project.write_text('[project]\nname = "code-standards"\nversion = "1.0.0"\n')
    lock = project.with_name("uv.lock")
    lock.write_text('[[package]]\nname = "code-standards"\nversion = "1.0.0"\nsource = { editable = "." }\n')
    if local_linter is not None:
        project.write_text(project.read_text() + f'dependencies = ["{local_linter}==1.0.0"]\n')
        lock.write_text(
            lock.read_text()
            + f'[[package]]\nname = "{local_linter}"\nversion = "1.0.0"\nsource = {{ editable = "../{owner}" }}\n'
        )
    git(repository, "add", "packages")
    git(repository, "commit", "-qm", "initial package")
    base = git(repository, "rev-parse", "HEAD")
    for path in (project, lock):
        path.write_text(path.read_text().replace("1.0.0", "1.1.0"))
    for relative in (
        source_path,
        "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json",
        "packages/standards/src/sarj_standards/configs/rule-inventory.v1.json",
        "packages/standards/src/sarj_standards/configs/cli-reference.v1.json",
        "apps/docs/src/generated/formatted-code.v1.json",
    ):
        source = repository / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("fixture\n")
    git(repository, "add", "packages", "apps")
    git(repository, "commit", "-qm", "new rule and release metadata")
    assert route(repository, base, git(repository, "rev-parse", "HEAD")) == {
        owner,
        "standards",
        "docs",
        security,
    }


@pytest.mark.parametrize(
    ("filename", "before", "after"),
    [
        (
            "pyproject.toml",
            '[project]\nversion = "1"\ndependencies = ["semgrep==1"]\n',
            '[project]\nversion = "2"\ndependencies = ["semgrep==2"]\n',
        ),
        (
            "uv.lock",
            '[[package]]\nname = "semgrep"\nversion = "1"\n',
            '[[package]]\nname = "semgrep"\nversion = "2"\n',
        ),
        ("pyproject.toml", '[project]\nversion = "1"\n', "invalid toml"),
        ("pyproject.toml", '[project]\nversion = "1"\n', None),
        (
            "uv.lock",
            (
                '[[package]]\nname = "sarj-python-lint"\nversion = "1"\nsource = { editable = "../python" }\n'
                'dependencies = [{ name = "old-dependency" }]\n'
            ),
            (
                '[[package]]\nname = "sarj-python-lint"\nversion = "2"\nsource = { editable = "../python" }\n'
                'dependencies = [{ name = "new-dependency" }]\n'
            ),
        ),
        (
            "uv.lock",
            '[[package]]\nname = "sarj-python-lint"\nversion = "1"\nsource = { registry = "https://pypi.org/simple" }\n',
            '[[package]]\nname = "sarj-python-lint"\nversion = "2"\nsource = { registry = "https://pypi.org/simple" }\n',
        ),
    ],
    ids=["direct-dependency", "transitive-dependency", "malformed", "deleted", "local-dependency", "registry-linter"],
)
def test_dependency_changes_or_comparison_errors_keep_mobile(
    repository: Path, filename: str, before: str, after: str | None
) -> None:
    source = repository / "packages/standards" / filename
    source.parent.mkdir(parents=True)
    root_package = '[[package]]\nname = "code-standards"\nversion = "1"\nsource = { editable = "." }\n'
    prefix = root_package if filename == "uv.lock" else ""
    source.write_text(prefix + before)
    git(repository, "add", "packages")
    git(repository, "commit", "-qm", "initial dependencies")
    base = git(repository, "rev-parse", "HEAD")
    if after is None:
        source.unlink()
    else:
        source.write_text(prefix + after)
    git(repository, "add", "packages")
    git(repository, "commit", "-qm", "changed dependencies")
    assert "mobile" in route(repository, base, git(repository, "rev-parse", "HEAD"))


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_non_pr_events_keep_complete_validation(repository: Path, event: str) -> None:
    assert route(repository, "", "", event=event) == SCOPES


@pytest.mark.parametrize("base", ["", "--help", "0" * 40])
def test_invalid_diff_fails_without_publishing_skip_outputs(repository: Path, base: str) -> None:
    output = repository / "scope-output"
    result = subprocess.run(
        ("bash", str(SCRIPT), "pull_request", base, git(repository, "rev-parse", "HEAD"), str(output)),
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert not output.exists()


def test_deleting_the_last_package_file_still_selects_its_checks(repository: Path) -> None:
    source = repository / "packages/iac/last.py"
    source.parent.mkdir(parents=True)
    source.write_text("fixture\n")
    git(repository, "add", "packages")
    git(repository, "commit", "-qm", "source")
    base = git(repository, "rev-parse", "HEAD")
    git(repository, "rm", str(source))
    git(repository, "commit", "-qm", "delete")
    assert route(repository, base, git(repository, "rev-parse", "HEAD")) == {
        "iac",
        "standards",
        "docs",
        "codeql-python",
    }


def test_base_only_changes_do_not_trigger_unrelated_pr_checks(repository: Path) -> None:
    base = git(repository, "rev-parse", "HEAD")
    source = repository / "packages/python/rule.py"
    source.parent.mkdir(parents=True)
    source.write_text("fixture\n")
    git(repository, "add", "packages")
    git(repository, "commit", "-qm", "PR change")
    head = git(repository, "rev-parse", "HEAD")
    git(repository, "checkout", "--detach", base)
    workflow = repository / ".github/workflows/unrelated.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("fixture\n")
    git(repository, "add", ".github")
    git(repository, "commit", "-qm", "base advanced")
    assert route(repository, git(repository, "rev-parse", "HEAD"), head) == {
        "python",
        "standards",
        "docs",
        "codeql-python",
    }


class WorkflowStep(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    name: str = ""
    condition: str = Field(default="", alias="if")
    run: str = ""


class WorkflowJob(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    needs: str | list[str] | None = None
    name: str = ""
    condition: str = Field(default="", alias="if")
    steps: list[WorkflowStep] = Field(default_factory=list)


class Workflow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    jobs: dict[str, WorkflowJob]


def workflow(name: str) -> Workflow:
    path = SCRIPT.parents[1] / "workflows" / name
    document: object = yaml.safe_load(path.read_text())  # pyright: ignore[reportAny] -- Pydantic validates the YAML boundary.
    return Workflow.model_validate(document)


def test_routing_failure_cannot_silently_skip_required_jobs() -> None:
    jobs = [job for job in workflow("ci.yml").jobs.values() if job.needs == "changes"]
    assert jobs
    for job in jobs:
        assert job.condition.startswith("always()")
        assert (
            job.condition.startswith("always() && github.event_name")
            or job.condition == "always()"
            or "needs.changes.result != 'success'" in job.condition
        )
        guard = job.steps[1]
        assert guard.condition == "needs.changes.result != 'success'"
        assert guard.run == "exit 1"


def test_required_standards_gate_requires_both_lanes_and_routing() -> None:
    gate = workflow("ci.yml").jobs["standards"]
    assert gate.needs == ["changes", "static-analysis", "package-tests"]
    assert gate.condition.startswith("always()")
    assert "needs.changes.result != 'success'" in gate.condition
    [guard] = [step for step in gate.steps if step.run]
    assert set(guard.condition.split(" || ")) == {
        "needs.changes.result != 'success'",
        "needs.static-analysis.result != 'success'",
        "needs.package-tests.result != 'success'",
    }
    assert guard.run == "exit 1"


def test_required_matrix_checks_keep_their_names_when_unaffected() -> None:
    typescript = workflow("ci.yml").jobs["typescript"]
    assert typescript.condition == "always() && github.event_name != 'schedule'"
    for step in typescript.steps[2:]:
        assert "needs.changes.outputs.typescript != 'false'" in step.condition
    assert workflow("ci.yml").jobs["portability-smoke"].name == "standards portability (ubuntu-latest)"
    assert workflow("ci.yml").jobs["npm-audit"].name == "npm-audit (apps/docs)"


def test_private_reference_fetch_excludes_existing_main_history(repository: Path) -> None:
    ancestor = git(repository, "rev-parse", "HEAD")
    git(repository, "commit", "--allow-empty", "-qm", "main advanced")
    base = git(repository, "rev-parse", "HEAD")
    git(repository, "checkout", "--detach", ancestor)
    git(repository, "commit", "--allow-empty", "-qm", "PR change")
    head = git(repository, "rev-parse", "HEAD")
    workspace = repository / "workspace"
    workspace.mkdir()
    candidate = workspace / "candidate"
    git(repository, "clone", "--no-local", repository.as_uri(), str(candidate))
    [step] = [
        step for step in workflow("private-refs.yml").jobs["scan"].steps if step.name == "Fetch comparison commit"
    ]
    command = step.run.replace("https://github.com/${{ github.repository }}.git", repository.as_uri())
    subprocess.run(
        ("bash", "-c", command.replace("$BASE_SHA", base)),
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert git(candidate, "rev-list", f"{base}..{head}") == head
    assert git(candidate, "rev-parse", "--is-shallow-repository") == "false"


def test_scheduled_ci_selects_only_security(repository: Path) -> None:
    assert route(repository, "", "", event="schedule") == {
        "codeql-python",
        "codeql-javascript-typescript",
        "docs-audit",
    }


def test_ci_detects_changes_once_and_never_deploys_on_schedule() -> None:
    workflows = SCRIPT.parents[1] / "workflows"
    assert sum(path.read_text().count("run: bash .github/scripts/ci-scope.sh") for path in workflows.glob("*.yml")) == 1
    jobs = workflow("ci.yml").jobs
    assert jobs["changes"].name == "Detect affected checks"
    deploy = jobs["docs-deploy"]
    assert deploy.needs == "docs-build"
    assert deploy.condition == (
        "github.ref == 'refs/heads/main' && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')"
    )


@pytest.mark.parametrize(
    ("result", "accepted"), [("success", True), ("skipped", True), ("failure", False), ("cancelled", False)]
)
def test_ci_completion_covers_every_job_and_rejects_failures(result: str, accepted: bool) -> None:
    jobs = workflow("ci.yml").jobs
    terminal = jobs["complete"]
    assert terminal.name == "CI complete"
    assert isinstance(terminal.needs, list)
    assert set(terminal.needs) == set(jobs) - {"complete"}
    assert terminal.condition == "always()"
    [step] = [step for step in terminal.steps if step.run]
    results = {key: {"result": "success"} for key in jobs if key != "complete"}
    for key in results:
        candidate = results | {key: {"result": result}}
        process = subprocess.run(
            ("bash", "-c", step.run),
            env={"PATH": "/usr/bin:/bin", "RESULTS": json.dumps(candidate)},
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert process.returncode == (0 if accepted else 1), (key, process.stderr)
