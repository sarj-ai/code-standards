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


@pytest.mark.parametrize(
    ("filename", "comment"),
    [
        ("config.toml", "# timeout = 30\n"),
        ("config.jsonc", "// timeout: 30\n"),
        ("Makefile", "# RELEASE = true\n"),
        ("Dockerfile", "# RUN make build\n"),
    ],
    ids=["toml", "jsonc", "make", "docker"],
)
def test_flags_commented_out_syntax_in_each_supported_config_format(
    tmp_path: Path, filename: str, comment: str
) -> None:
    path = tmp_path / filename
    path.write_text(comment)
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


def test_ignores_comments_inside_yaml_block_scalars(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("script: |\n  # timeout-minutes: 30\n  # retries: 2\nname: CI\n")
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


def test_config_wall_requires_four_attached_comments(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n# Run build command\nrun: make build\n# Set deploy image\nimage: app\n"
    )
    assert _codes(path) == []


def test_config_wall_requires_three_weak_comments(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Application lifecycle owner\nimage: app\n"
        "# Deployment entry point\ncommand: deploy\n"
    )
    assert _codes(path) == []


def test_config_wall_requires_75_percent_weak_comments(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Set deploy image\nimage: app\n"
        "# Deployment entry point\ncommand: deploy\n"
        "# Release lifecycle owner\ntarget: production\n"
    )
    assert _codes(path) == []


def test_config_wall_flags_three_weak_comments_out_of_four(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Set deploy image\nimage: app\n"
        "# Deployment entry point\ncommand: deploy\n"
    )
    findings = textlint.check_paths([str(path)])
    assert [finding.code for finding in findings] == ["SARJ300"]
    assert "3 narrated entries" in findings[0].message


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


def test_config_wall_requires_comments_attached_to_entries(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\n\nname: build\n"
        "# Run build command\n\nrun: make build\n"
        "# Set deploy image\n\nimage: app\n"
        "# Run deploy command\n\ncommand: deploy\n"
    )
    assert _codes(path) == []


def test_config_wall_does_not_combine_different_indentation_levels(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "  # Set deploy image\n  image: app\n"
        "  # Run deploy command\n  command: deploy\n"
    )
    assert _codes(path) == []


@pytest.mark.parametrize(
    "protected_comment",
    [
        "# yamllint disable rule:line-length",
        "# See RFC 9110 for retry semantics",
        "# Keep one worker because uploads are serialized",
        "# Invariant: the deployment name is immutable",
        "# The timeout is 30 sec",
        "# Compatibility with legacy runners",
        "# Upstream rejects parallel uploads",
    ],
    ids=["directive", "reference", "rationale", "invariant", "unit", "compatibility", "upstream"],
)
def test_config_wall_protects_high_signal_comments(tmp_path: Path, protected_comment: str) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "# Set build name\nname: build\n"
        "# Run build command\nrun: make build\n"
        "# Application lifecycle owner\nimage: app\n"
        f"{protected_comment}\ncommand: deploy\n"
    )
    assert _codes(path) == []


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


def test_manifest_exclusion_applies_to_artifact_findings(tmp_path: Path) -> None:
    manifest = tmp_path / ".sarj-standards.toml"
    manifest.write_text('[text]\nexclude = ["docs/backups/**"]\n', encoding="utf-8")
    artifact = tmp_path / "docs" / "backups" / "README.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Archived operational reference\n", encoding="utf-8")

    assert _codes(artifact, root=tmp_path) == []


def test_manifest_is_read_once_per_textlint_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = tmp_path / ".sarj-standards.toml"
    manifest.write_text('[artifacts]\ndurable = ["docs/**"]\n[text]\nexclude = ["templates/**"]\n')
    config = tmp_path / "values.yaml"
    config.write_text("enabled: true\n")
    real_read_text = Path.read_text
    manifest_reads = 0

    def recording_read_text(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal manifest_reads
        if path == manifest:
            manifest_reads += 1
        return real_read_text(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", recording_read_text)

    assert textlint.check_paths([str(config)], root=tmp_path) == []
    assert manifest_reads == 1


@pytest.mark.parametrize(
    "filename",
    ["FIX-BRIEF-V3.md", "diagnosis-handoff.md", "project-status.md", "qa-fixlist.md"],
    ids=["brief", "handoff", "status", "qa"],
)
def test_flags_named_ai_execution_artifacts(tmp_path: Path, filename: str) -> None:
    path = tmp_path / filename
    path.write_text("# Temporary execution record\n")
    assert _codes(path, root=tmp_path) == ["SARJ302"]


def test_new_artifact_rule_warns_without_blocking_its_first_release(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "FIX-BRIEF.md"
    path.write_text("# Temporary execution record\n")

    assert textlint.run([str(path)]) == 0
    assert "SARJ302 warning:" in capsys.readouterr().out


def test_established_text_rules_remain_blocking(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("# timeout = 30\n")

    assert textlint.run([str(path)]) == 1


def test_flags_change_diary_inside_readme(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_text("# App\n\n## Fixes + learnings\n\n## Verification passes\n")
    assert _codes(path, root=tmp_path) == ["SARJ302"]


@pytest.mark.parametrize(
    "heading",
    ["Verification pass", "Verification passes", "QA pass", "Implementation status", "Session summary"],
    ids=["verification", "verification-plural", "qa", "implementation-status", "session-status"],
)
def test_flags_repeated_execution_log_headings(tmp_path: Path, heading: str) -> None:
    path = tmp_path / "notes.md"
    path.write_text(f"# Work\n\n## {heading}\n\n## {heading}\n")
    assert _codes(path, root=tmp_path) == ["SARJ302"]


def test_allows_durable_docs_and_single_verification_section(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    path = docs / "operations.md"
    path.write_text("# Operations\n\n## Verification\nRun `make verify`.\n")
    assert _codes(path, root=tmp_path) == []


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "AGENTS.md",
        "CLAUDE.md",
        ".github/policy.md",
        "architecture/system.md",
        "adr/001-decision.md",
    ],
    ids=[
        "readme",
        "changelog",
        "contributing",
        "security",
        "agents",
        "claude",
        "github",
        "architecture",
        "adr",
    ],
)
def test_allows_durable_markdown_locations(tmp_path: Path, relative: str) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Current design\n")
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


def test_markdown_fences_do_not_create_artifact_headings(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# CLI\n\n```markdown\n## Fixes + learnings\n## Verification passes\n```\n",
        encoding="utf-8",
    )

    assert _codes(readme, root=tmp_path) == []


def test_matching_sarj_suppression_is_code_specific(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("# sarj-noqa: SARJ301\n# timeout = 30\n", encoding="utf-8")
    assert _codes(config) == []

    config.write_text("# sarj-noqa: SARJ999\n# timeout = 30\n", encoding="utf-8")
    assert _codes(config) == ["SARJ301"]


def test_custom_durable_paths_extend_builtin_locations(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text('[artifacts]\ndurable = ["evidence/**"]\n', encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    report = docs / "architecture-report.md"
    report.write_text("# Maintained architecture\n", encoding="utf-8")

    assert _codes(report, root=tmp_path) == []


def test_flags_large_dated_audit_inside_docs(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    audit = docs / "pagerduty-audit-2026-08.md"
    audit.write_text(
        "# PagerDuty audit — 2026-08-04\n\n"
        "## Inventory\n\n| Object | Count |\n| --- | --- |\n| Services | 4 |\n\n"
        "## Findings\n\n**1. Stale rotation.** Remove it.\n\n"
        "## What was actually changed\n\nThe rotation was replaced.\n\n"
        "## Recommended order of work\n\n1. Remove the stale rotation.\n\n"
        "## Post-change verification\n\nThe API returned the expected state.\n\n"
        + "Evidence captured during the audit.\n"
        * 180
    )
    assert _codes(audit, root=tmp_path) == ["SARJ302"]


def test_large_architecture_reference_is_not_an_execution_artifact(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    architecture = docs / "ARCHITECTURE.md"
    architecture.write_text(
        "# Architecture\n\n## Components\n\nThe API accepts requests and publishes domain events.\n\n"
        + "### Service contract\n\nEach consumer processes one versioned event schema.\n\n" * 80
    )
    assert _codes(architecture, root=tmp_path) == []


def test_large_document_needs_multiple_artifact_signals(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    operations = docs / "operations-2026-08.md"
    operations.write_text("# Operations\n\n## Inventory\n\n" + "Current service fact.\n" * 210)
    assert _codes(operations, root=tmp_path) == []


def test_large_design_findings_and_actions_need_artifact_provenance(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    design = docs / "database-design.md"
    design.write_text(
        "# Database design\n\n## Findings\n\n1. Writes need stable keys.\n2. Reads need an index.\n\n"
        "## Action Items\n\nAdd the index during implementation.\n\n"
        + "The maintained design explains a durable constraint.\n"
        * 200
    )
    assert _codes(design, root=tmp_path) == []


@pytest.mark.parametrize(
    "filename",
    ["BUGS-FOUND.md", "bugs_found.md", "bugs-found-fe.md"],
)
def test_flags_bug_hunt_artifacts_even_in_durable_locations(tmp_path: Path, filename: str) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    report = docs / filename
    report.write_text("# Bugs found during the testing initiative\n")
    assert _codes(report, root=tmp_path) == ["SARJ302"]


@pytest.mark.parametrize(
    "filename",
    ["bugs-foundation.md", "ladybugs-found.md", "debugs-foundation.md"],
)
def test_bug_hunt_name_requires_complete_filename_tokens(tmp_path: Path, filename: str) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    document = docs / filename
    document.write_text("# Maintained reference\n")
    assert _codes(document, root=tmp_path) == []
