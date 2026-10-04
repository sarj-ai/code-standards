from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import lifecycle
from sarj_standards.libs.adoption.manifest import Manifest
from sarj_standards.libs.diagnostics import Completion, TrustMode
from sarj_standards.libs.linting.external import ProcessOutput
from sarj_standards.libs.linting.formatting import analyze_formatting
from sarj_standards.libs.linting.policy import Policy


if TYPE_CHECKING:
    from collections.abc import Sequence


def _project(root: Path) -> None:
    (root / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    (root / ".oxfmtrc.json").write_text('{"printWidth":80,"sortImports":false}\n', encoding="utf-8")


@pytest.mark.parametrize("output", ["", "name with spaces.ts"])
def test_clean_and_dirty_protocol_preserves_exact_filenames(tmp_path: Path, output: str) -> None:
    _project(tmp_path)
    (tmp_path / "name with spaces.ts").write_text("export const value=1;", encoding="utf-8")
    captured: list[Sequence[str]] = []

    def execute(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        captured.append(argv)
        assert cwd == tmp_path
        return ProcessOutput(1 if output else 0, output, "")

    report = analyze_formatting(["name with spaces.ts"], root=tmp_path, trust=TrustMode.TRUSTED, runner=execute)

    assert report.completion is Completion.COMPLETE
    assert "--list-different" in captured[0]
    assert "--check" not in captured[0]
    assert "--write" not in captured[0]
    assert [item.location.path for item in report.diagnostics] == (["name with spaces.ts"] if output else [])
    assert all(item.code == "OXFMT001" and item.source == "oxfmt" for item in report.diagnostics)


def test_full_formatter_discovery_respects_generated_and_manifest_exclusions(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / "index.html").write_text("<div><span>text</span></div>", encoding="utf-8")
    (tmp_path / "exclude.css").write_text("a{color:red}", encoding="utf-8")
    (tmp_path / "client.generated.ts").write_text("export const value=1;", encoding="utf-8")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "client.ts").write_text("export const value=1;", encoding="utf-8")
    policy = Policy.from_manifest(
        tmp_path,
        Manifest(
            version="1.0.0", configs=("oxlint",), python_dest=".", typescript_dest=".", excluded_paths=("exclude.css",)
        ),
    )
    captured: list[Sequence[str]] = []

    def execute(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        captured.append(argv)
        assert cwd == tmp_path
        return ProcessOutput(1, "index.html", "")

    report = analyze_formatting(["."], root=tmp_path, policy=policy, trust=TrustMode.TRUSTED, runner=execute)

    assert report.completion is Completion.COMPLETE
    assert [item.location.path for item in report.diagnostics] == ["index.html"]
    assert "exclude.css" not in captured[0]
    assert "client.generated.ts" not in captured[0]
    assert "generated/client.ts" not in captured[0]


@pytest.mark.parametrize(
    ("filename", "source"), [("index.html", "<div><span>text</span></div>"), ("config.toml", "value=1")]
)
def test_pinned_formatter_checks_non_javascript_languages(tmp_path: Path, filename: str, source: str) -> None:
    _project(tmp_path)
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    if not (modules / ".bin" / "oxfmt").is_file():
        pytest.skip("the pinned Oxfmt package is not installed")
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / filename).write_text(source, encoding="utf-8")

    report = analyze_formatting([filename], root=tmp_path, trust=TrustMode.TRUSTED)

    assert report.completion is Completion.COMPLETE
    assert [item.location.path for item in report.diagnostics] == [filename]
    assert (tmp_path / filename).read_text(encoding="utf-8") == source


@pytest.mark.parametrize(
    ("status", "stdout", "stderr"),
    [
        (1, "", "invalid formatter configuration"),
        (1, "", ""),
        (0, "Checking formatting...", ""),
        (1, "unselected.ts", ""),
        (1, "source.ts\nsource.ts", ""),
        (2, "", "parse failure"),
        (2, "", "No files found matching the given patterns."),
        (0, "source.ts", "No files found matching the given patterns."),
        (0, "", "No files found matching the given patterns.\nconfiguration failure"),
    ],
)
def test_formatter_protocol_failures_never_become_clean_reports(
    tmp_path: Path,
    status: int,
    stdout: str,
    stderr: str,
) -> None:
    _project(tmp_path)
    (tmp_path / "source.ts").write_text("export const value=1;", encoding="utf-8")

    def execute(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert "--list-different" in argv
        assert cwd == tmp_path
        return ProcessOutput(status, stdout, stderr)

    report = analyze_formatting(["source.ts"], root=tmp_path, trust=TrustMode.TRUSTED, runner=execute)

    assert report.completion is Completion.FAILED
    assert report.issues


def test_missing_local_formatter_does_not_trigger_package_download(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / "source.ts").write_text("export const value=1;", encoding="utf-8")

    report = analyze_formatting(["source.ts"], root=tmp_path, trust=TrustMode.TRUSTED)

    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "missing-dependency"


@pytest.mark.parametrize("filename", [".oxfmtrc.json", "oxfmt.config.mts"])
def test_all_formatter_configs_require_repository_trust(tmp_path: Path, filename: str) -> None:
    _project(tmp_path)
    (tmp_path / ".oxfmtrc.json").unlink()
    (tmp_path / filename).write_text("{}" if filename.endswith(".json") else "export default {};", encoding="utf-8")
    (tmp_path / "source.ts").write_text("export const value=1;", encoding="utf-8")

    def forbidden(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert "--list-different" in argv
        pytest.fail(f"untrusted formatter executed in {cwd}")

    report = analyze_formatting(["source.ts"], root=tmp_path, trust=TrustMode.SAFE, runner=forbidden)

    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "trust-required"


def test_oxfmt_real_tool_reports_dirty_files_and_retains_generated_ignores(tmp_path: Path) -> None:
    _project(tmp_path)
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    if not (modules / ".bin" / "oxfmt").is_file():
        pytest.skip("the pinned Oxfmt package is not installed")
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / ".oxfmtrc.json").write_text(
        json.dumps({"printWidth": 80, "sortPackageJson": False, "ignorePatterns": ["*.generated.ts"]}), encoding="utf-8"
    )
    dirty = tmp_path / "dirty.ts"
    dirty.write_text("export const value=1;", encoding="utf-8")
    ignored = tmp_path / "client.generated.ts"
    ignored.write_text("export const generated=1;", encoding="utf-8")

    report = analyze_formatting([str(dirty), str(ignored)], root=tmp_path, trust=TrustMode.TRUSTED)

    assert report.completion is Completion.COMPLETE
    assert [item.location.path for item in report.diagnostics] == ["dirty.ts"]
    assert dirty.read_text(encoding="utf-8") == "export const value=1;"
    assert ignored.read_text(encoding="utf-8") == "export const generated=1;"


@pytest.mark.parametrize("ignore_owner", ["config", ".prettierignore"])
def test_ignored_only_yaml_selection_completes_without_formatting(tmp_path: Path, ignore_owner: str) -> None:
    _project(tmp_path)
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    if not (modules / ".bin" / "oxfmt").is_file():
        pytest.skip("the pinned Oxfmt package is not installed")
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    if ignore_owner == "config":
        (tmp_path / ".oxfmtrc.json").write_text('{"ignorePatterns":["workflow.yml"]}\n', encoding="utf-8")
    else:
        (tmp_path / ignore_owner).write_text("workflow.yml\n", encoding="utf-8")
    source = "name:    deliberately-unformatted\n"
    (tmp_path / "workflow.yml").write_text(source, encoding="utf-8")

    report = analyze_formatting(["workflow.yml"], root=tmp_path, trust=TrustMode.TRUSTED)

    assert report.completion is Completion.COMPLETE, report.issues
    assert report.diagnostics == ()
    assert report.issues == ()
    assert lifecycle.execute(lifecycle.selected_formatter_commands(tmp_path, ["workflow.yml"])) == 0
    assert (tmp_path / "workflow.yml").read_text(encoding="utf-8") == source


@pytest.mark.parametrize("failure", ["configuration", "yaml"])
def test_real_formatter_failures_remain_failures_with_no_match_support(tmp_path: Path, failure: str) -> None:
    _project(tmp_path)
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    if not (modules / ".bin" / "oxfmt").is_file():
        pytest.skip("the pinned Oxfmt package is not installed")
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    source = "value: [unterminated\n" if failure == "yaml" else "name: example\n"
    (tmp_path / "workflow.yml").write_text(source, encoding="utf-8")
    if failure == "configuration":
        (tmp_path / ".oxfmtrc.json").write_text("{", encoding="utf-8")

    report = analyze_formatting(["workflow.yml"], root=tmp_path, trust=TrustMode.TRUSTED)

    assert report.completion is Completion.FAILED
    assert report.issues
    assert (tmp_path / "workflow.yml").read_text(encoding="utf-8") == source


def test_nested_formatter_policy_checks_repository_files_without_parent_paths(tmp_path: Path) -> None:
    project = tmp_path / "frontend"
    project.mkdir()
    _project(project)
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    if not (modules / ".bin" / "oxfmt").is_file():
        pytest.skip("the pinned Oxfmt package is not installed")
    (project / "node_modules").symlink_to(modules, target_is_directory=True)
    (tmp_path / ".sarj-standards.toml").write_text(
        Manifest(version="1.0.0", configs=("oxlint",), python_dest=".", typescript_dest="frontend").render(),
        encoding="utf-8",
    )
    (project / ".oxfmtrc.json").write_text(
        json.dumps({"singleQuote": True, "ignorePatterns": ["ignored.ts"]}), encoding="utf-8"
    )
    sources = {
        "root file.ts": 'export const name="root";',
        "frontend/source.ts": 'export const name="frontend";',
        "frontend/clean.ts": "export const name = 'clean';\n",
        "frontend/ignored.ts": "export const ignored=1;",
    }
    for name, source in sources.items():
        (tmp_path / name).write_text(source, encoding="utf-8")

    report = analyze_formatting(tuple(sources), root=tmp_path, trust=TrustMode.TRUSTED)

    assert report.completion is Completion.COMPLETE
    assert report.issues == ()
    assert report.file_count == 4
    assert [item.location.path for item in report.diagnostics] == ["frontend/source.ts", "root file.ts"]
    assert {name: (tmp_path / name).read_text(encoding="utf-8") for name in sources} == sources

    assert lifecycle.execute(lifecycle.selected_formatter_commands(tmp_path, sources)) == 0
    assert (tmp_path / "root file.ts").read_text(encoding="utf-8") == "export const name = 'root';\n"
    assert (project / "source.ts").read_text(encoding="utf-8") == "export const name = 'frontend';\n"
    assert (project / "ignored.ts").read_text(encoding="utf-8") == sources["frontend/ignored.ts"]
    clean = analyze_formatting(tuple(sources), root=tmp_path, trust=TrustMode.TRUSTED)
    assert clean.completion is Completion.COMPLETE
    assert clean.diagnostics == ()


@pytest.mark.parametrize("ignore_source", ["root", "nested", "info-exclude"])
@pytest.mark.parametrize("selection", [["."], ["source.json", ".outputs/ignored.json", ".outputs/force-added.json"]])
def test_formatter_keeps_tracked_files_but_excludes_untracked_git_ignores(
    tmp_path: Path, selection: list[str], ignore_source: str
) -> None:
    _project(tmp_path)
    modules = Path(__file__).resolve().parents[3] / "node_modules"
    if not (modules / ".bin" / "oxfmt").is_file():
        pytest.skip("the pinned Oxfmt package is not installed")
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True, capture_output=True, shell=False)
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    cache = tmp_path / ".outputs"
    cache.mkdir()
    if ignore_source == "root":
        (tmp_path / ".gitignore").write_text(".outputs/*.json\nnode_modules/\n", encoding="utf-8")
    elif ignore_source == "nested":
        (cache / ".gitignore").write_text("*.json\n", encoding="utf-8")
    else:
        (tmp_path / ".git/info/exclude").write_text(".outputs/*.json\n", encoding="utf-8")
    source = '{"value":1}'
    for path in (tmp_path / "source.json", cache / "ignored.json", cache / "force-added.json"):
        path.write_text(source, encoding="utf-8")
    subprocess.run(
        ("git", "add", "--force", ".outputs/force-added.json"),
        cwd=tmp_path,
        check=True,
        capture_output=True,
        shell=False,
    )

    report = analyze_formatting(selection, root=tmp_path, trust=TrustMode.TRUSTED)

    assert report.completion is Completion.COMPLETE, report.issues
    findings = {item.location.path for item in report.diagnostics}
    assert "source.json" in findings
    assert ".outputs/force-added.json" in findings
    assert ".outputs/ignored.json" not in findings
    commands = lifecycle.selected_formatter_commands(
        tmp_path, ["source.json", ".outputs/ignored.json", ".outputs/force-added.json"]
    )
    assert lifecycle.execute(commands) == 0
    assert (cache / "ignored.json").read_text(encoding="utf-8") == source
    assert (cache / "force-added.json").read_text(encoding="utf-8") != source
    assert (tmp_path / "source.json").read_text(encoding="utf-8") != source


def test_formatter_does_not_apply_personal_global_git_ignores(tmp_path: Path) -> None:
    _project(tmp_path)
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True, capture_output=True, shell=False)
    global_ignores = tmp_path / "personal.ignore"
    global_ignores.write_text("source.json\n", encoding="utf-8")
    subprocess.run(
        ("git", "config", "core.excludesFile", str(global_ignores)),
        cwd=tmp_path,
        check=True,
        capture_output=True,
        shell=False,
    )
    (tmp_path / "source.json").write_text('{"value":1}', encoding="utf-8")
    captured: list[Sequence[str]] = []

    def execute(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        captured.append(argv)
        return ProcessOutput(1, "source.json", "")

    report = analyze_formatting(["source.json"], root=tmp_path, trust=TrustMode.TRUSTED, runner=execute)

    assert report.completion is Completion.COMPLETE
    assert [item.location.path for item in report.diagnostics] == ["source.json"]
    assert captured


def test_formatter_git_selection_failure_cannot_report_clean(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "source.json").write_text('{"value":1}', encoding="utf-8")

    report = analyze_formatting(["source.json"], root=tmp_path, trust=TrustMode.TRUSTED)

    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "configuration-failure"
    assert "Git could not determine" in report.issues[0].message
