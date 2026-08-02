"""Cross-file comment and generated-artifact policy tests."""

from pathlib import Path

import pytest

from sarj_lint_configs import textlint


def _codes(path: Path, *, root: Path | None = None) -> list[str]:
    return [finding.code for finding in textlint.check_paths([str(path)], root=root)]


def test_flags_commented_out_yaml(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("# timeout-minutes: 30\nname: CI\n")
    assert _codes(path) == ["SARJ301"]


def test_ignores_documented_config_examples_and_docker_prose(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("# Default:\n# timeout = 30\ntimeout = 10\n")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("# Copy workspace files\nCOPY . /app\n")
    assert _codes(config) == []
    assert _codes(dockerfile) == []


def test_protects_config_rationale_and_tool_directives(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# yamllint disable rule:line-length\n"
        "# Keep one worker because upstream rejects parallel uploads\n"
        "concurrency: 1\n"
    )
    assert _codes(path) == []


def test_collapses_a_commented_out_config_block(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("# timeout-minutes: 30\n# retries: 2\nname: CI\n")
    assert _codes(path) == ["SARJ301"]


def test_collapses_repeated_config_narration(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Set deploy image\nimage: app\n"
        "# Run deploy command\ncommand: deploy\n"
    )
    assert _codes(path) == ["SARJ300"]


def test_rationale_comments_count_against_wall_ratio(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Keep the timeout because upstream can stall\ntimeout: 30\n"
        "# Set deploy image\nimage: app\n"
        "# Run deploy command\ncommand: deploy\n"
        "# Keep one worker because uploads race\nconcurrency: 1\n"
    )
    assert _codes(path) == []


def test_groups_narration_across_multiline_sibling_entries(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build job\n"
        "build_job:\n  image: node\n  script:\n    - npm ci\n    - npm build\n"
        "# Set test job\n"
        "test_job:\n  image: node\n  script:\n    - npm test\n"
        "# Set deploy job\n"
        "deploy_job:\n  image: node\n  script:\n    - npm deploy\n"
        "# Set publish job\n"
        "publish_job:\n  image: node\n  script:\n    - npm publish\n"
    )
    assert _codes(path) == ["SARJ300"]


def test_flags_jsonc_block_comment_and_toml_section(tmp_path: Path) -> None:
    jsonc = tmp_path / "settings.jsonc"
    jsonc.write_text('/* "debug": true */\n{}\n')
    toml = tmp_path / "settings.toml"
    toml.write_text("# [debug]\n# enabled = true\n")
    assert _codes(jsonc) == ["SARJ301"]
    assert _codes(toml) == ["SARJ301"]


def test_manifest_can_exclude_documented_template_config(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text('[text]\nexclude = ["templates/**"]\n')
    templates = tmp_path / "templates"
    templates.mkdir()
    config = templates / "values.yaml"
    config.write_text("# timeout: 30\n# retries: 2\n")
    assert _codes(config, root=tmp_path) == []


def test_flags_named_ai_execution_artifact(tmp_path: Path) -> None:
    path = tmp_path / "FIX-BRIEF-V3.md"
    path.write_text("# Fix brief\n")
    assert _codes(path, root=tmp_path) == ["SARJ302"]


@pytest.mark.parametrize(
    "relative",
    [
        "_backups/old.bak.md",
        "CLONE_NOTES.md",
        "AUTHENTICITY-FIXES-PROMPT.md",
        "audits/fable-loop-findings.md",
    ],
)
def test_flags_additional_ai_artifact_shapes(tmp_path: Path, relative: str) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Temporary work\n")
    assert _codes(path, root=tmp_path) == ["SARJ302"]


def test_flags_change_diary_inside_readme(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_text("# App\n\n## Fixes + learnings\n\n## Verification passes\n")
    assert _codes(path, root=tmp_path) == ["SARJ302"]


def test_allows_durable_docs_and_single_verification_section(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    path = docs / "operations.md"
    path.write_text("# Operations\n\n## Verification\nRun `make verify`.\n")
    assert _codes(path, root=tmp_path) == []


def test_changelog_issue_heading_is_durable(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\n## Issues fixed\n\n- Corrected retry behavior.\n")
    assert _codes(path, root=tmp_path) == []


@pytest.mark.parametrize(
    "filename",
    ["Dockerfile.nginx", "workflow.yaml.tftpl", "settings.ini", ".env.example", "Justfile"],
)
def test_extended_text_file_routing(filename: str) -> None:
    assert textlint.is_text_path(Path(filename))


def test_manifest_can_allow_a_durable_research_report(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text('[artifacts]\ndurable = ["evidence/**"]\n')
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    report = evidence / "research-report.md"
    report.write_text("# Reproducible benchmark evidence\n")
    assert _codes(report, root=tmp_path) == []


@pytest.mark.parametrize(
    ("filename", "heading"),
    [("FIX-BRIEF.md", "# Fix brief\n"), ("END-TO-END-PLAN.md", "# End-to-end plan\n")],
    ids=["fix-brief", "end-to-end-plan"],
)
def test_durable_directory_does_not_hide_execution_artifacts(tmp_path: Path, filename: str, heading: str) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    artifact = docs / filename
    artifact.write_text(heading)
    assert _codes(artifact, root=tmp_path) == ["SARJ302"]


def test_flags_strong_change_diary_heading_without_a_second_heading(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# App\n\n## What changed this session\n")
    assert _codes(readme, root=tmp_path) == ["SARJ302"]
