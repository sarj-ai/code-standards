from __future__ import annotations

from pathlib import Path

import pytest

from sarj_standards.libs.linting import library_policy


def test_catalog_has_stable_unique_ids_and_adapter_messages() -> None:
    entries = library_policy.catalog()

    assert len(entries) == 41
    assert len({entry.id for entry in entries}) == len(entries)
    assert library_policy.python_banned_api()["argparse"].startswith("LIB001:")
    assert {entry.name for entry in library_policy.typescript_restricted_imports()} >= {"axios", "express", "tslint"}


def test_scan_reads_python_manifest_families_and_normalizes_names(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["Requests[socks]>=2", "pandas"]
[project.optional-dependencies]
api = ["Flask>=3"]
[dependency-groups]
test = ["nose"]
[tool.poetry.dependencies]
python = ">=3.14"
aioredis = "*"
[tool.poetry.group.docs.dependencies]
pathlib2 = "*"
[tool.pdm.dev-dependencies]
lint = ["importlib_metadata"]
[tool.uv]
dev-dependencies = ["backports.cached-property"]
""",
        encoding="utf-8",
    )

    findings = library_policy.scan(tmp_path)

    assert {finding.id for finding in findings} == {
        "LIB003",
        "LIB004",
        "LIB006",
        "LIB011",
        "LIB013",
        "LIB018",
        "LIB020",
        "LIB021",
    }


def test_scan_requirements_supports_includes_urls_editables_and_ignores_constraints(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements"
    requirements.mkdir()
    (tmp_path / "requirements.in").write_text(
        "-r requirements/dev.in\n-c constraints.txt\nrequests @ https://example.test/a.whl\npandas>=2 # data frames\n",
        encoding="utf-8",
    )
    (requirements / "dev.in").write_text("-e git+https://example.test/project#egg=UJSON\n", encoding="utf-8")
    (tmp_path / "constraints.txt").write_text("pandas==1\n", encoding="utf-8")

    findings = library_policy.scan(tmp_path)

    assert {finding.id for finding in findings} == {"LIB003", "LIB004", "LIB005"}
    ujson = next(finding for finding in findings if finding.id == "LIB005")
    assert (ujson.path, ujson.line, ujson.column) == (Path("requirements/dev.in"), 1, 41)


def test_scan_ignores_generated_requirements_exports(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "# This file was auto-generated from environment.yml\npandas==2\n", encoding="utf-8"
    )

    assert library_policy.scan(tmp_path) == ()


def test_scan_accepts_pep735_includes_and_ignores_requirement_fixtures_and_unnamed_urls(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[dependency-groups]\ndev = [{ include-group = "test" }, "requests"]\ntest = ["pytest"]\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("https://example.test/archive.zip\n", encoding="utf-8")
    fixture = tmp_path / "tests" / "templates"
    fixture.mkdir(parents=True)
    (fixture / "requirements.txt").write_text("{% if enabled %}\npandas\n{% endif %}\n", encoding="utf-8")

    findings = library_policy.scan(tmp_path)

    assert [finding.id for finding in findings] == ["LIB004"]


def test_scan_package_json_fields_aliases_and_workspaces(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '\ufeff{"dependencies":{"http":"npm:Axios@^1","zod":"^4"},"devDependencies":{"jest":"1"},"optionalDependencies":{"node-sass":"1"},"peerDependencies":{"express":"5"}}',
        encoding="utf-8",
    )
    workspace = tmp_path / "packages" / "web"
    workspace.mkdir(parents=True)
    (workspace / "package.json").write_text('{"dependencies":{"lodash-es":"1"}}', encoding="utf-8")
    ignored = tmp_path / "node_modules" / "old"
    ignored.mkdir(parents=True)
    (ignored / "package.json").write_text('{"dependencies":{"moment":"1"}}', encoding="utf-8")
    cached = tmp_path / ".uv-cache" / "sdists-v9" / "old"
    cached.mkdir(parents=True)
    (cached / "pyproject.toml").write_text('[project]\ndependencies=["pandas"]\n', encoding="utf-8")

    assert {finding.id for finding in library_policy.scan(tmp_path)} == {
        "LIB101",
        "LIB103",
        "LIB107",
        "LIB108",
        "LIB118",
    }


def test_scan_allows_selected_mapping_ids(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("pandas\nrequests\n", encoding="utf-8")

    findings = library_policy.scan(tmp_path, allowed_ids={"LIB003"})

    assert [finding.id for finding in findings] == ["LIB004"]


def test_scan_paths_checks_only_selected_manifests(tmp_path: Path) -> None:
    selected = tmp_path / "requirements.txt"
    selected.write_text("requests\n", encoding="utf-8")
    unrelated = tmp_path / "nested" / "package.json"
    unrelated.parent.mkdir()
    unrelated.write_text('{"dependencies":{"axios":"1"}}', encoding="utf-8")

    assert [finding.id for finding in library_policy.scan_paths(tmp_path, [str(selected)])] == ["LIB004"]
    assert [finding.id for finding in library_policy.scan_paths(tmp_path, [str(unrelated)])] == ["LIB101"]


def test_scan_paths_ignores_selected_source_files(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies":{"axios":"1"}}', encoding="utf-8")
    source = tmp_path / "src" / "component.ts"
    source.parent.mkdir()
    source.write_text("export const value = 1;\n", encoding="utf-8")

    assert library_policy.scan_paths(tmp_path, [str(source)]) == ()


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("pyproject.toml", "[project\ndependencies=[]"),
        ("package.json", '{"dependencies": []}'),
        ("requirements.txt", "not a valid !!! requirement"),
    ],
)
def test_scan_fails_closed_on_malformed_applicable_manifests(tmp_path: Path, name: str, content: str) -> None:
    (tmp_path / name).write_text(content, encoding="utf-8")

    with pytest.raises(library_policy.ManifestPolicyError):
        library_policy.scan(tmp_path)


def test_findings_have_actionable_rendered_locations(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("safe==1\npandas==2\n", encoding="utf-8")

    finding = library_policy.scan(tmp_path)[0]

    assert finding.path == Path("requirements.txt")
    assert finding.line == 2
    assert finding.column == 1
    assert finding.render().startswith("requirements.txt:2:1 LIB003")
