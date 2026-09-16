from __future__ import annotations

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


@pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch"])
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


@pytest.mark.parametrize(
    "name",
    [
        "bootstrap-ci.yml",
        "python-ci.yml",
        "sql-ci.yml",
        "iac-ci.yml",
        "typescript-ci.yml",
        "tsconfig-ci.yml",
        "standards-ci.yml",
        "docs.yml",
        "security.yml",
    ],
)
def test_routing_failure_cannot_silently_skip_required_jobs(name: str) -> None:
    jobs = [job for job in workflow(name).jobs.values() if job.needs == "changes"]
    assert jobs
    for job in jobs:
        assert job.condition.startswith("always()")
        assert job.condition == "always()" or "needs.changes.result != 'success'" in job.condition
        guard = job.steps[1]
        assert guard.condition == "needs.changes.result != 'success'"
        assert guard.run == "exit 1"


def test_required_standards_gate_requires_both_lanes_and_routing() -> None:
    gate = workflow("standards-ci.yml").jobs["test"]
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
    typescript = workflow("typescript-ci.yml").jobs["test"]
    assert typescript.condition == "always()"
    for step in typescript.steps[2:]:
        assert "needs.changes.outputs.typescript != 'false'" in step.condition
    assert workflow("standards-ci.yml").jobs["portability-smoke"].name == "standards portability (ubuntu-latest)"
    assert workflow("security.yml").jobs["npm-audit"].name == "npm-audit (apps/docs)"


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
