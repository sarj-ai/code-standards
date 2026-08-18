from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

import sarj_standards
from sarj_standards import api
from sarj_standards.libs.adoption.lifecycle import Command
from sarj_standards.libs.adoption.manifest import Manifest
from sarj_standards.libs.rules import RuleEngine, RuleId, RuleSelector


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sarj_standards.libs.linting.policy import Policy
    from sarj_standards.libs.linting.runner import GroupedPaths


def test_every_declared_public_api_resolves() -> None:
    assert api.__all__
    assert all(hasattr(api, name) for name in api.__all__)
    assert len(api.__all__) == len(set(api.__all__))


def test_package_root_exposes_the_small_consumer_facade() -> None:
    assert sarj_standards.Standards is api.Standards
    assert sarj_standards.Result is api.Result


def test_package_import_does_not_eagerly_load_release_automation() -> None:
    script = "import sys; import sarj_standards; assert 'sarj_standards.libs.release' not in sys.modules"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("source", "rule_id", "expected"),
    [
        (
            "sarj-python-lint",
            "no-global-mutable",
            RuleSelector(RuleEngine.PYTHON, RuleId("no-global-mutable")),
        ),
        (
            "eslint",
            "@sarj/no-alert",
            RuleSelector(RuleEngine.ESLINT, RuleId("no-alert")),
        ),
        ("unregistered-tool", "no-alert", None),
        ("eslint", "@upstream/no-alert", None),
    ],
)
def test_diagnostic_identity_normalizes_only_known_custom_rule_selectors(
    source: str,
    rule_id: str,
    expected: RuleSelector | None,
) -> None:
    diagnostic = api.Diagnostic(
        "TEST001",
        "finding",
        api.Severity.ERROR,
        source,
        api.Location("src/example.py"),
        rule_id=rule_id,
    )

    selector = api._selector_for_diagnostic(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        diagnostic
    )
    assert selector == expected


def test_canonical_analysis_routes_the_repository_only_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "service.py"
    source.write_text("value = 1\n", encoding="utf-8")
    routed: list[GroupedPaths] = []
    original_group_paths = api.group_paths  # pyright: ignore[reportPrivateLocalImportUsage]

    def route_once(paths: Sequence[str], *, policy: Policy | None = None) -> GroupedPaths:
        grouped = original_group_paths(paths, policy=policy)
        routed.append(grouped)
        return grouped

    def native(_paths: Sequence[str], **kwargs: object) -> api.AnalysisReport:
        assert kwargs["grouped"] is routed[0]
        return api.AnalysisReport(tmp_path, api.Completion.COMPLETE, api.Conclusion.PASSED, ())

    def external(_paths: Sequence[str], **kwargs: object) -> tuple[api.ToolReport, ...]:
        assert kwargs["grouped"] is routed[0]
        return ()

    monkeypatch.setattr(api, "group_paths", route_once)
    monkeypatch.setattr(api, "analyze_paths", native)
    monkeypatch.setattr(api, "analyze_external", external)

    report = api.Standards(tmp_path).analyze(["service.py"], external=True)

    assert report.conclusion is api.Conclusion.PASSED
    assert len(routed) == 1


def test_analysis_rejects_a_bare_rule_selector_string(tmp_path: Path) -> None:
    report = api.Standards(tmp_path).analyze(rules="python:no-rule")

    assert report.conclusion is api.Conclusion.INCONCLUSIVE
    assert report.issues[0].kind == "invalid-input"
    assert "sequence of canonical selectors" in report.issues[0].message


def test_public_api_is_the_deliberately_small_stable_facade() -> None:
    expected = {
        "AnalysisReport",
        "Change",
        "Diagnostic",
        "Finding",
        "Result",
        "Standards",
        "Status",
        "to_json",
        "to_sarif",
        "__version__",
    }
    assert expected <= set(api.__all__)
    assert {"RUFF_STRICT", "plan_upgrade", "initialize", "sync_configs"}.isdisjoint(api.__all__)


def test_standards_facade_returns_typed_doctor_result(tmp_path: Path) -> None:
    result = api.Standards(tmp_path).doctor()

    assert not result.ok
    assert result.status is api.Status.DRIFT
    assert result.findings[0].id == "doctor.manifest.absent"


def test_standards_facade_fix_uses_the_adopted_nested_typescript_destination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    web = tmp_path / "apps" / "web"
    web.mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        '{"name":"workspace","private":true,"packageManager":"pnpm@11.0.0"}\n',
        encoding="utf-8",
    )
    (tmp_path / "pnpm-workspace.yaml").write_text('packages:\n  - "apps/*"\n', encoding="utf-8")
    (web / "package.json").write_text('{"name":"web","private":true}\n', encoding="utf-8")
    (tmp_path / ".sarj-standards.toml").write_text(
        Manifest(
            version=api.__version__,
            configs=("eslint",),
            python_dest=".",
            typescript_dest="apps/web",
        ).render(),
        encoding="utf-8",
    )
    planned: list[Command] = []

    def capture(commands: Sequence[Command]) -> int:
        planned.extend(commands)
        return 0

    monkeypatch.setattr("sarj_standards.libs.adoption.lifecycle.execute", capture)

    result = api.Standards(tmp_path).fix()

    assert result.status is api.Status.OK
    assert [command.cwd for command in planned] == [web]


def test_standards_facade_rejects_selected_paths_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")

    result = api.Standards(tmp_path).check([str(outside)])

    assert result.status is api.Status.INVALID
    assert result.exit_code == 2
    assert result.findings[0].id == "check.input.invalid"


def test_standards_facade_rejects_selected_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    link = tmp_path / "linked.py"
    link.symlink_to(source)

    result = api.Standards(tmp_path).check(["linked.py"])

    assert result.status is api.Status.INVALID
    assert "symlink" in result.findings[0].message


def test_standards_facade_enforces_selected_application_dependency_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adopted = Manifest(
        version=api.__version__,
        configs=("markdownlint",),
        python_dest=".",
        typescript_dest=".",
        profile="application",
    )
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render(), encoding="utf-8")
    package = tmp_path / "package.json"
    package.write_text('{"dependencies":{"moment":"1"}}\n', encoding="utf-8")

    def clean_check(_paths: Sequence[str], **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr(api, "check", clean_check)

    result = api.Standards(tmp_path).check(["package.json"])

    assert result.status is api.Status.DRIFT
    assert [finding.id for finding in result.findings] == ["LIB102"]


def test_standards_facade_runs_eslint_for_selected_typescript(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "component.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    command = Command("ESLint", ("true",), tmp_path)

    def clean_check(_paths: Sequence[str], **_kwargs: object) -> int:
        return 0

    def selected(_root: Path, _paths: Sequence[str]) -> list[Command]:
        return [command]

    def execute(commands: Sequence[Command]) -> int:
        return 1 if list(commands) == [command] else 0

    monkeypatch.setattr(api, "check", clean_check)
    monkeypatch.setattr(api, "selected_eslint_commands", selected)
    monkeypatch.setattr(api, "execute", execute)

    result = api.Standards(tmp_path).check(["component.ts"])

    assert result.status is api.Status.DRIFT


def test_standards_facade_init_dry_run_never_writes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )

    result = api.Standards(tmp_path).setup(dry_run=True)

    assert result.status is api.Status.CHANGED
    assert result.changes
    assert any(change.path == tmp_path / ".ruff-strict.toml" for change in result.changes)
    assert not (tmp_path / ".sarj-standards.toml").exists()


def test_standards_facade_init_exposes_project_roots_and_truthful_no_install_preview(tmp_path: Path) -> None:
    python_root = tmp_path / "python"
    python_root.mkdir()
    (python_root / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )

    result = api.Standards(tmp_path).setup(
        configs=("ruff",),
        python_root="python",
        install=False,
        dry_run=True,
    )

    assert result.status is api.Status.CHANGED
    assert any(change.path == python_root / ".ruff-strict.toml" for change in result.changes)
    assert all(change.action != "run" for change in result.changes)
    assert not (python_root / ".ruff-strict.toml").exists()


def test_standards_facade_init_dry_run_reports_invalid_plan(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n', encoding="utf-8"
    )
    (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
    (tmp_path / ".pre-commit-config.yml").write_text("repos: []\n", encoding="utf-8")

    result = api.Standards(tmp_path).setup(dry_run=True, install=False)

    assert result.status is api.Status.INVALID
    assert result.exit_code == 2
    assert result.findings[0].id == "setup.plan.invalid"
    assert "multiple pre-commit configurations" in result.findings[0].message


def test_standards_facade_update_targets_latest_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "upgraded", "")

    def which(_name: str) -> str:
        return "/usr/bin/uvx"

    monkeypatch.setattr("sarj_standards.api.shutil.which", which)
    monkeypatch.setattr("sarj_standards.api.subprocess.run", run)

    result = api.Standards(tmp_path).update(install=False)

    assert result.status is api.Status.CHANGED
    assert commands == [
        [
            "/usr/bin/uvx",
            "--no-config",
            "--isolated",
            "--python",
            "3.14",
            "--refresh",
            "--from",
            "sarj-standards",
            "sarj-standards",
            "--root",
            str(tmp_path),
            "update",
            "--offline",
            "--no-install",
        ]
    ]


def test_standards_facade_update_exposes_exact_offline_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "upgraded", "")

    def which(_name: str) -> str:
        return "/usr/bin/uvx"

    monkeypatch.setattr("sarj_standards.api.shutil.which", which)
    monkeypatch.setattr("sarj_standards.api.subprocess.run", run)

    result = api.Standards(tmp_path).update(version="5.14.1", offline=True, install=False)

    assert result.status is api.Status.CHANGED
    assert "sarj-standards==5.14.1" in commands[0]
    assert "--refresh" not in commands[0]
    assert commands[0][-4:] == ["--offline", "--to", "5.14.1", "--no-install"]


def test_standards_facade_update_rejects_noncanonical_exact_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def which(_name: str) -> str:
        return "/usr/bin/uvx"

    monkeypatch.setattr("sarj_standards.api.shutil.which", which)

    result = api.Standards(tmp_path).update(version="latest")

    assert result.status is api.Status.INVALID
    assert result.findings[0].id == "update.version.invalid"


@pytest.mark.parametrize(
    ("check_only", "expected_status", "expected_finding"),
    [
        (True, api.Status.DRIFT, "update.latest.available"),
        (False, api.Status.FAILED, "update.latest.failed"),
    ],
)
def test_latest_update_exit_one_is_truthful_and_has_no_parent_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    check_only: bool,
    expected_status: api.Status,
    expected_finding: str,
) -> None:
    calls: list[dict[str, object]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(command, 1, "", "postflight drift")

    def which(_name: str) -> str:
        return "/usr/bin/uvx"

    monkeypatch.setattr("sarj_standards.api.shutil.which", which)
    monkeypatch.setattr("sarj_standards.api.subprocess.run", run)

    result = api.Standards(tmp_path).update(install=False, check_only=check_only)

    assert result.status is expected_status
    assert result.findings[0].id == expected_finding
    assert "timeout" not in calls[0]


def test_standards_facade_init_rejects_invalid_existing_manifest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "fixture"\nversion = "0.0.0"\n', encoding="utf-8")
    manifest = tmp_path / ".sarj-standards.toml"
    manifest.write_text("bad = [\n", encoding="utf-8")

    result = api.Standards(tmp_path).setup(install=False, dry_run=True)

    assert result.status is api.Status.INVALID
    assert result.findings[0].id == "setup.input.invalid"
    assert manifest.read_text(encoding="utf-8") == "bad = [\n"


@pytest.mark.parametrize("configs", [("bogus",), (), "ruff"], ids=("unknown", "empty", "string"))
def test_standards_facade_init_rejects_invalid_configs(tmp_path: Path, configs: object) -> None:
    result = api.Standards(tmp_path).setup(configs=configs, install=False)  # type: ignore[arg-type]

    assert result.status is api.Status.INVALID
    assert result.findings[0].id == "setup.input.invalid"


def test_standards_facade_init_rejects_invalid_runtime_profile(tmp_path: Path) -> None:
    result = api.Standards(tmp_path).setup(profile="bogus", install=False)  # type: ignore[arg-type]

    assert result.status is api.Status.INVALID
    assert result.findings[0].id == "setup.input.invalid"
