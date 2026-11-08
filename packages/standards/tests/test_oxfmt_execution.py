from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING

from pydantic import BaseModel
import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting import oxfmt
from sarj_standards.libs.linting.process import ProcessCapabilities, ProcessOutput, ToolResolution


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pydantic import JsonValue

    from sarj_standards.libs.linting.process import ProcessRequest


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULES = REPO_ROOT / "packages/typescript/node_modules"
STRICT = REPO_ROOT / "packages/standards/src/sarj_standards/configs/oxfmt.strict.mts"
needs_oxfmt = pytest.mark.skipif(not (MODULES / ".bin/oxfmt").is_file(), reason="the pinned oxfmt is not installed")


class _Executor:
    def __init__(self, respond: Callable[[ProcessRequest], ProcessOutput]) -> None:
        self.respond = respond
        self.capabilities = ProcessCapabilities(ToolResolution.PROVIDED)
        self.requests: list[ProcessRequest] = []

    def run(self, request: ProcessRequest) -> ProcessOutput:
        self.requests.append(request)
        return self.respond(request)


def _listing(returncode: int, stdout: str = "", stderr: str = "") -> _Executor:
    return _Executor(lambda _request: ProcessOutput(returncode, stdout, stderr))


def _install(root: Path) -> None:
    (root / "node_modules").symlink_to(MODULES, target_is_directory=True)


def _written(root: Path, name: str) -> str:
    command = oxfmt.write_command([name], project=root, root=root)
    subprocess.run(command.argv, cwd=command.cwd, check=True, capture_output=True)
    return (root / name).read_text(encoding="utf-8")


def _managed_project(root: Path, options: dict[str, JsonValue]) -> None:
    _install(root)
    shutil.copyfile(STRICT, root / "oxfmt.strict.mts")
    seed = oxfmt.OxfmtSeed("prettier", options)
    (root / "oxfmt.config.mts").write_text(oxfmt.render_config(seed), encoding="utf-8")


@pytest.mark.parametrize(
    ("listed", "expected"),
    [("", []), ("name with spaces.ts\n", ["name with spaces.ts"]), ("src/nested.ts\n", ["src/nested.ts"])],
)
def test_list_different_reports_one_diagnostic_per_listed_file(
    tmp_path: Path, listed: str, expected: list[str]
) -> None:
    executor = _listing(1 if listed else 0, listed)

    report = oxfmt.analyze(["name with spaces.ts", "src"], project=tmp_path, root=tmp_path, runner=executor)

    assert report.completion is Completion.COMPLETE, report.issues
    assert executor.requests[0].argv == (
        "oxfmt",
        "--list-different",
        "--no-error-on-unmatched-pattern",
        "--",
        "name with spaces.ts",
        "src",
    )
    assert [item.location.path for item in report.diagnostics] == expected
    assert all(
        (item.source, item.rule_id, item.fixes, item.location.position) == ("oxfmt", "format", (), None)
        for item in report.diagnostics
    )


def test_paths_are_passed_relative_to_the_owning_project(tmp_path: Path) -> None:
    project = tmp_path / "frontend"
    executor = _listing(1, "src/app.ts\n")

    report = oxfmt.analyze([str(project / "src/app.ts")], project=project, root=tmp_path, runner=executor)

    assert executor.requests[0].cwd == project
    assert executor.requests[0].argv[-1] == "src/app.ts"
    assert [item.location.path for item in report.diagnostics] == ["frontend/src/app.ts"]
    with pytest.raises(ValueError, match="outside the oxfmt project"):
        oxfmt.analyze(["backend/app.ts"], project=project, root=tmp_path, runner=executor)


def test_selection_that_oxfmt_ignores_entirely_is_clean(tmp_path: Path) -> None:
    executor = _listing(
        0, "Finished in 0ms on 0 files using 12 threads.\n", "No files found matching the given patterns.\n"
    )

    report = oxfmt.analyze(["ignored.md"], project=tmp_path, root=tmp_path, runner=executor)

    assert report.completion is Completion.COMPLETE
    assert report.diagnostics == ()


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "kind"),
    [
        (2, "", "  x Unexpected token", "tool-failure"),
        (1, "", "Failed to load configuration file.", "tool-failure"),
        (0, "", "No files found matching the given patterns.\nconfiguration failure", "tool-failure"),
        (1, "", "", "protocol-mismatch"),
        (0, "source.ts\n", "", "protocol-mismatch"),
        (1, "unselected.ts\n", "", "protocol-mismatch"),
        (1, "../outside.ts\n", "", "protocol-mismatch"),
        (1, "source.ts\nsource.ts\n", "", "protocol-mismatch"),
    ],
)
def test_protocol_failures_never_become_clean_reports(
    tmp_path: Path, returncode: int, stdout: str, stderr: str, kind: str
) -> None:
    report = oxfmt.analyze(["source.ts"], project=tmp_path, root=tmp_path, runner=_listing(returncode, stdout, stderr))

    assert report.completion is Completion.FAILED
    assert [issue.kind for issue in report.issues] == [kind]


def test_missing_local_oxfmt_is_a_dependency_failure(tmp_path: Path) -> None:
    report = oxfmt.analyze(["source.ts"], project=tmp_path, root=tmp_path)

    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "missing-dependency"


@needs_oxfmt
def test_managed_policy_scopes_file_types_and_skips_standards_files(tmp_path: Path) -> None:
    _managed_project(tmp_path, {"extensions": ["ts", "mts"], "semi": False, "ignorePatterns": ["vendor.ts"]})
    sources = {
        "dirty.ts": "export const value=1;\n",
        "clean.ts": "export const value = 1\n",
        "vendor.ts": "export const vendor=1;\n",
        "notes.md": "*   item\n",
        "data.json": '{"a":1}',
        "oxlint.strict.mts": "export const managed=1;\n",
    }
    for name, source in sources.items():
        (tmp_path / name).write_text(source, encoding="utf-8")

    report = oxfmt.analyze(list(sources), project=tmp_path, root=tmp_path)

    assert report.completion is Completion.COMPLETE, report.issues
    [diagnostic] = report.diagnostics
    assert diagnostic.location.path == "dirty.ts"
    assert {name: (tmp_path / name).read_text(encoding="utf-8") for name in sources} == sources
    assert _written(tmp_path, "dirty.ts") == "export const value = 1\n"


@needs_oxfmt
def test_write_command_formats_only_selected_files(tmp_path: Path) -> None:
    _managed_project(tmp_path, {})
    (tmp_path / "selected.ts").write_text("export const a=1", encoding="utf-8")
    (tmp_path / "other.ts").write_text("export const b=1", encoding="utf-8")

    command = oxfmt.write_command(["selected.ts"], project=tmp_path, root=tmp_path)

    assert Path(command.argv[0]).name == "oxfmt"
    assert command.argv[1:] == ("--write", "--no-error-on-unmatched-pattern", "--", "selected.ts")
    subprocess.run(command.argv, cwd=command.cwd, check=True, capture_output=True)
    assert (tmp_path / "selected.ts").read_text(encoding="utf-8") == "export const a = 1;\n"
    assert (tmp_path / "other.ts").read_text(encoding="utf-8") == "export const b=1"


def _migration_runner(migrated: Mapping[str, JsonValue], stderr: str = "") -> _Executor:
    def respond(request: ProcessRequest) -> ProcessOutput:
        (request.cwd / ".oxfmtrc.json").write_text(json.dumps(migrated), encoding="utf-8")
        return ProcessOutput(0, "Created `.oxfmtrc.json`.\n", stderr)

    return _Executor(respond)


def test_biome_seed_restores_scope_and_biome_defaults(tmp_path: Path) -> None:
    biome = {
        "files": {"includes": ["**/*.ts", "**/*.tsx", "**/*.json", "**/*.css", "**/*.astro", "!**/generated"]},
        "formatter": {"indentStyle": "space", "lineWidth": 100},
        "javascript": {"formatter": {"quoteStyle": "single"}},
        "overrides": [{"includes": ["legacy/**"], "javascript": {"formatter": {"semicolons": "asNeeded"}}}],
    }
    (tmp_path / "biome.json").write_text(json.dumps(biome), encoding="utf-8")
    migrated: dict[str, JsonValue] = {
        "printWidth": 100,
        "tabWidth": 2,
        "useTabs": False,
        "singleQuote": True,
        "trailingComma": "all",
    }
    executor = _migration_runner(
        {**migrated, "ignorePatterns": ["**/generated"]},
        '\nPlease review:\n  - "overrides" cannot be migrated automatically yet\n',
    )

    with pytest.raises(ValueError, match="Biome override"):
        oxfmt.seed_config(tmp_path, runner=executor)
    assert executor.requests == []


def test_biome_seed_without_includes_keeps_biome_languages_only(tmp_path: Path) -> None:
    (tmp_path / "biome.json").write_text('{"json": {"formatter": {"enabled": false}}}', encoding="utf-8")

    seed = oxfmt.seed_config(tmp_path, runner=_migration_runner({"trailingComma": "all", "singleQuote": False}))

    assert seed.options["extensions"] == ["cjs", "css", "cts", "gql", "graphql", "js", "jsx", "mjs", "mts", "ts", "tsx"]


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({".oxfmtrc.jsonc": "{}"}, "already configures oxfmt"),
        ({"oxfmt.config.mts": "export default {};"}, "handcrafted"),
    ],
)
def test_seed_refuses_ambiguous_formatter_configs(tmp_path: Path, files: dict[str, str], message: str) -> None:
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        oxfmt.seed_config(tmp_path, runner=_listing(0))


def test_seed_keeps_existing_oxfmtrc_and_defaults_repositories_without_a_formatter(tmp_path: Path) -> None:
    executor = _listing(0)
    (tmp_path / "biome.json").write_text('{"formatter": {"enabled": false}}', encoding="utf-8")
    assert oxfmt.seed_config(tmp_path, runner=executor).options == {}
    (tmp_path / ".oxfmtrc.json").write_text('{"$schema": "x", "printWidth": 120}', encoding="utf-8")
    assert oxfmt.seed_config(tmp_path, runner=executor) == oxfmt.OxfmtSeed("oxfmt", {})
    assert executor.requests == []


@needs_oxfmt
def test_prettier_seed_keeps_repository_style_tailwind_sorting_and_ignores(tmp_path: Path) -> None:
    _install(tmp_path)
    prettier = {"semi": False, "printWidth": 100, "plugins": ["prettier-plugin-tailwindcss"]}
    (tmp_path / ".prettierrc.json").write_text(json.dumps(prettier), encoding="utf-8")
    (tmp_path / ".prettierignore").write_text("# generated\npublic/r/\n", encoding="utf-8")

    seed = oxfmt.seed_config(tmp_path)

    assert not (tmp_path / ".oxfmtrc.json").exists()
    assert seed.options == {
        "ignorePatterns": ["public/r/"],
        "extensions": sorted(oxfmt.FORMAT_EXTENSIONS - {"gs", "toml"}),
    }
    shutil.copyfile(STRICT, tmp_path / "oxfmt.strict.mts")
    (tmp_path / "oxfmt.config.mts").write_text(oxfmt.render_config(seed), encoding="utf-8")
    (tmp_path / "view.tsx").write_text('export const v = <div className="p-4 flex" />;\n', encoding="utf-8")
    (tmp_path / "wrangler.toml").write_text("name    =   'x'\n", encoding="utf-8")
    report = oxfmt.analyze(["view.tsx", "wrangler.toml"], project=tmp_path, root=tmp_path)
    assert report.completion is Completion.COMPLETE, report.issues
    assert report.diagnostics == ()
    assert _written(tmp_path, "view.tsx") == 'export const v = <div className="p-4 flex" />;\n'


@needs_oxfmt
def test_biome_seed_with_real_migration_leaves_biome_files_unchanged(tmp_path: Path) -> None:
    _install(tmp_path)
    biome = {
        "files": {"includes": ["**/*.ts", "**/*.jsonc", "**/*.css"]},
        "formatter": {"indentStyle": "space", "lineWidth": 100},
        "javascript": {"formatter": {"quoteStyle": "single"}},
    }
    (tmp_path / "biome.json").write_text(json.dumps(biome), encoding="utf-8")
    sources = {
        "source.ts": "export const name = 'biome';\n",
        "wrangler.jsonc": '{\n  "name": "worker",\n  "vars": {\n    "A": "b"\n  }\n}\n',
        "style.css": 'a[href="x"] {\n  content: "";\n}\n',
        "package.json": '{\n  "version": "1.0.0",\n  "name": "fixture"\n}\n',
        "README.md": "*   Biome never formatted Markdown\n",
    }
    for name, text in sources.items():
        (tmp_path / name).write_text(text, encoding="utf-8")

    seed = oxfmt.seed_config(tmp_path)
    shutil.copyfile(STRICT, tmp_path / "oxfmt.strict.mts")
    (tmp_path / "oxfmt.config.mts").write_text(oxfmt.render_config(seed), encoding="utf-8")
    report = oxfmt.analyze(list(sources), project=tmp_path, root=tmp_path)

    assert seed.source == "biome"
    assert report.completion is Completion.COMPLETE, report.issues
    assert {diagnostic.location.path for diagnostic in report.diagnostics} == {"source.ts", "wrangler.jsonc"}


class _NamingFinding(BaseModel):
    code: str
    message: str


class _NamingReport(BaseModel):
    diagnostics: list[_NamingFinding]


@needs_oxfmt
def test_shared_formatting_preserves_wire_keys_and_native_naming_enforcement(tmp_path: Path) -> None:
    _managed_project(tmp_path, {})
    source = 'export const payload = { "external_wire_key": 1 };\nconsole.log(JSON.stringify(payload));\n'
    target = tmp_path / "wire.mjs"
    target.write_text(source, encoding="utf-8")
    plugin = REPO_ROOT / "packages/typescript/dist/index.js"
    (tmp_path / ".oxlintrc.json").write_text(
        json.dumps(
            {
                "plugins": [],
                "jsPlugins": [{"name": "@sarj", "specifier": str(plugin)}],
                "categories": {"correctness": "off"},
                "rules": {"@sarj/require-camelcase-properties": "error"},
            }
        ),
        encoding="utf-8",
    )

    def naming_findings() -> list[_NamingFinding]:
        result = subprocess.run(
            [str(MODULES / ".bin/oxlint"), "-c", ".oxlintrc.json", "--format", "json", "--", target.name],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode in {0, 1}, result.stderr
        report = _NamingReport.model_validate_json(result.stdout)
        assert all(item.code == "@sarj(require-camelcase-properties)" for item in report.diagnostics), report
        return report.diagnostics

    def emitted_payload() -> str:
        result = subprocess.run(
            ["node", str(target)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    assert naming_findings() == []
    original_payload = emitted_payload()
    formatted = _written(tmp_path, target.name)
    assert naming_findings() == []
    assert '"external_wire_key"' in formatted
    assert emitted_payload() == original_payload == '{"external_wire_key":1}\n'
    assert _written(tmp_path, target.name) == formatted

    target.write_text(formatted + "export const adjacent = { new_unquoted_wire_key: 2 };\n", encoding="utf-8")
    control = _written(tmp_path, target.name)
    findings = naming_findings()
    assert len(findings) == 1, findings
    assert "new_unquoted_wire_key" in findings[0].message
    assert emitted_payload() == original_payload
    assert _written(tmp_path, target.name) == control
