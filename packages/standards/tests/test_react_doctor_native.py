from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from pydantic import BaseModel, JsonValue, RootModel
import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting import external


class JsonDocument(RootModel[dict[str, JsonValue]]):
    pass


class Finding(BaseModel):
    rule: str
    severity: str


class Report(BaseModel):
    complete: bool
    diagnostics: tuple[Finding, ...]


CONFIGS = Path(external.__file__).resolve().parents[2] / "configs"


def execute(
    root: Path, *argv: str, guarded: bool = False, input_bytes: bytes | None = None, git_index: Path | None = None
) -> external.ProcessOutput:
    request = external.process_request(argv, cwd=root, input_bytes=input_bytes, max_input_bytes=16 * 1024 * 1024)
    if git_index is not None:
        request = replace(request, environment={**request.environment, "GIT_INDEX_FILE": str(git_index)})
    if guarded:
        request = replace(
            request, environment={**request.environment, "NODE_OPTIONS": f"--import={root / 'guard.mjs'}"}
        )
    return external.DEFAULT_EXECUTOR.run(request)


@pytest.fixture(scope="module")
def installation(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("doctor-native")
    (root / "package.json").write_text(
        json.dumps(
            {
                "private": True,
                "dependencies": {
                    "oxlint": "1.91.0",
                    "oxlint-plugin-react-doctor": "0.9.22",
                    "parse5": "8.0.0",
                },
            }
        )
    )
    result = execute(root, "npm", "install", "--ignore-scripts", "--no-audit", "--no-fund")
    assert result.returncode == 0, result.stderr
    packages = JsonDocument.model_validate_json((root / "package-lock.json").read_text()).root["packages"]
    assert isinstance(packages, dict)
    assert not any(path.endswith("node_modules/eslint") for path in packages)
    (root / "guard.mjs").write_text(
        "import {registerHooks} from 'node:module'; registerHooks({resolve(s,c,n){"
        "if(s==='eslint'||s.startsWith('eslint/'))throw new Error('Forbidden ESLint import '+s);return n(s,c)}});"
    )
    # Exercise Linux-style cwd-relative reports on hosts where Oxlint emits absolute paths.
    (root / "relative-native.mjs").write_text(
        "import childProcess from 'node:child_process';"
        "import {syncBuiltinESMExports} from 'node:module';"
        "import {relative,resolve} from 'node:path';"
        "const spawn=childProcess.spawnSync;childProcess.spawnSync=(file,args,options)=>{"
        "const result=spawn(file,args,options);if(args.includes('--format=json')){"
        "const report=JSON.parse(result.stdout);for(const finding of report.diagnostics)"
        "finding.filename=relative(options.cwd,resolve(options.cwd,finding.filename));"
        "result.stdout=JSON.stringify(report);}return result;};syncBuiltinESMExports();"
    )
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text('{"dependencies":{"react":"19.2.8"}}')
    (tmp_path / "src").mkdir()
    (tmp_path / "src/view.tsx").write_text(
        "export const View = ({items}) => items.map((item, index) => <div key={index}>{item.name}</div>);\n"
    )
    (tmp_path / "firestore.rules").write_text(
        "rules_version = '2';\nservice cloud.firestore { match /databases/{database}/documents { "
        "match /{document=**} { allow read, write: if true; } } }\n"
    )
    (tmp_path / "config.json").write_text((CONFIGS / "doctor.config.json").read_text())
    assert execute(tmp_path, "git", "init", "--template=").returncode == 0
    return tmp_path


def scan(
    installation: Path,
    project: Path,
    *,
    paths: tuple[str, ...] = (),
    full: bool = True,
    compiler: bool = False,
    staged: bool = False,
    git_index: Path | None = None,
    relative_native: bool = False,
) -> external.ProcessOutput:
    request: dict[str, JsonValue] = {
        "installRoot": str(installation),
        "config": str(project / "config.json"),
        "repositoryRoot": str(project),
        "fullScan": full,
        "includeCompiler": compiler,
        "staged": staged,
        "paths": [str(project / path) for path in paths],
        "projects": [{"root": str(project), "excluded": []}],
    }
    return execute(
        installation,
        "node",
        *((f"--import={installation / 'relative-native.mjs'}",) if relative_native else ()),
        str(CONFIGS / "react-doctor-runner.mjs"),
        input_bytes=json.dumps(request).encode(),
        guarded=True,
        git_index=git_index,
    )


def test_fresh_install_native_and_security_without_eslint(installation: Path, project: Path) -> None:
    output = scan(installation, project)
    assert output.returncode == 0, output.stderr
    report = Report.model_validate_json(output.stdout)
    assert report.complete is True
    assert {item.rule for item in report.diagnostics} == {"no-array-index-as-key", "firebase-permissive-rules"}
    findings = external.parse_react_doctor(output.stdout, root=project)
    assert {item.rule_id for item in findings} == {
        "react-doctor/no-array-index-as-key",
        "react-doctor/firebase-permissive-rules",
    }


def test_selected_source_scope_keeps_project_security(installation: Path, project: Path) -> None:
    (project / "src/clean.tsx").write_text("export const Clean = () => <div />;\n")
    output = scan(installation, project, full=False, paths=("src/clean.tsx",))
    assert output.returncode == 0, output.stderr
    assert {item.rule for item in Report.model_validate_json(output.stdout).diagnostics} == {
        "firebase-permissive-rules"
    }


def test_ignored_files_overrides_and_inline_suppressions(installation: Path, project: Path) -> None:
    config = JsonDocument.model_validate_json((project / "config.json").read_text()).root
    ignore = config["ignore"]
    assert isinstance(ignore, dict)
    ignore["overrides"] = [{"files": ["firestore.rules"], "rules": ["react-doctor/firebase-permissive-rules"]}]
    (project / "config.json").write_text(json.dumps(config))
    view = project / "src/view.tsx"
    view.write_text(
        "// react-doctor-disable-next-line react-doctor/no-array-index-as-key -- synthetic fixture\n" + view.read_text()
    )
    output = scan(installation, project)
    assert output.returncode == 0, output.stderr
    assert Report.model_validate_json(output.stdout).diagnostics == ()
    ignore["files"] = ["**/*.tsx", "firestore.rules"]
    ignore.pop("overrides")
    view.write_text(view.read_text().split("\n", 1)[1])
    (project / "config.json").write_text(json.dumps(config))
    assert Report.model_validate_json(scan(installation, project).stdout).diagnostics == ()


def test_native_parse_failure_is_not_clean(installation: Path, project: Path) -> None:
    (project / "src/view.tsx").write_text("export const = <\n")
    output = scan(installation, project)
    assert output.returncode != 0
    assert '"complete":true' not in output.stdout


def test_security_selection_preserves_upstream_file_size_bound(installation: Path, project: Path) -> None:
    (project / "src/oversized.ts").write_text("// synthetic bounded-file fixture\n" * 70000)
    output = scan(installation, project, full=False, paths=("firestore.rules",))
    assert output.returncode == 0, output.stderr
    findings = external.parse_react_doctor(output.stdout, root=project)
    assert all(finding.location.path != "src/oversized.ts" for finding in findings)


def test_failed_adapter_is_failed_tool_report(project: Path) -> None:
    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- Test actual tool failure signaling.
        project,
        projects=(project,),
        root=project,
        runner=external.DEFAULT_EXECUTOR,
        file_count=1,
        staged=False,
        full_scan=True,
    )
    assert report.completion is Completion.FAILED
    assert report.issues


def test_incomplete_protocol_is_rejected(project: Path) -> None:
    with pytest.raises(ValueError, match="complete"):
        external.parse_react_doctor('{"complete":false,"diagnostics":[]}', root=project)


def test_tracked_credentials_and_ignored_generated_artifacts(installation: Path, project: Path) -> None:
    # Deliberately invented token-shaped bytes; no service or credential is used.
    value = "sk_live_" + "aB3cD5eF7gH9jK2mN4pQ6rS8tU0vW1xY"
    (project / ".env.production").write_text(f"STRIPE_SECRET_KEY={value}\n")
    (project / ".gitignore").write_text(".env.production\ndist/\n")
    artifact = project / "dist/assets/main.js"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(f'const config={{secret:"{value}"}};' + "const x=1;" * 3000)
    output = scan(installation, project, full=False, paths=("firestore.rules",))
    assert output.returncode == 0, output.stderr
    rules = {item.rule for item in Report.model_validate_json(output.stdout).diagnostics}
    assert "repository-secret-file" not in rules
    assert "artifact-secret-leak" in rules
    assert execute(project, "git", "add", "--force", ".env.production").returncode == 0
    output = scan(installation, project, full=False, paths=("firestore.rules",))
    assert output.returncode == 0, output.stderr
    assert "repository-secret-file" in {item.rule for item in Report.model_validate_json(output.stdout).diagnostics}


def test_native_scan_does_not_move_or_apply_unrelated_oxlint_ledger(installation: Path, project: Path) -> None:
    ledger = project / "oxlint-suppressions.json"
    original = '{"src/view.tsx":{"unrelated/rule":{"count":1}}}\n'
    ledger.write_text(original)
    output = scan(installation, project)
    assert output.returncode == 0, output.stderr
    assert "no-array-index-as-key" in {item.rule for item in Report.model_validate_json(output.stdout).diagnostics}
    assert ledger.read_text() == original


def test_scan_callback_failure_propagates(installation: Path, project: Path) -> None:
    script = project / "failed-scan.mjs"
    module = (CONFIGS / "react-doctor-scan.mjs").as_uri()
    script.write_text(
        f"import {{scanSecurity}} from {json.dumps(module)};\n"
        "const core={classifySecurityScanFile:p=>p==='firestore.rules'?{bucket:'priority',isGeneratedBundleByName:false}:null,"
        "shouldReadSecurityScanContent:()=>true,REACT_DOCTOR_SCAN_RULES:["
        "{id:'failure',key:'react-doctor/failure',rule:{severity:'error',scan(){throw new Error('callback failure')}}}]};\n"
        f"scanSecurity({json.dumps(str(project))},core,{{}});\n"
    )
    output = execute(installation, "node", str(script), guarded=True)
    assert output.returncode != 0
    assert "callback failure" in output.stderr


def test_doctor_only_requests_keep_native_compiler_checks(installation: Path, project: Path) -> None:
    (project / "babel.config.json").write_text('{"plugins":["babel-plugin-react-compiler"]}')
    (project / "src/view.tsx").write_text(
        "import { useState } from 'react';\n"
        "export function Mutate({data}) { data.value = 1; return <div>{data.value}</div>; }\n"
        "export function Impure() { return <div>{Date.now()}</div>; }\n"
        "export function Conditional({enabled}) { if(enabled) { useState(0); } return <div/>; }\n"
        "export function Parent() { const Child = () => <div/>; return <Child/>; }\n"
    )
    output = scan(installation, project, compiler=True)
    assert output.returncode == 0, output.stderr
    assert {"immutability", "purity", "rules-of-hooks", "static-components"} <= {
        item.rule for item in Report.model_validate_json(output.stdout).diagnostics
    }
    diagnostics = external.parse_react_doctor(output.stdout, root=project)
    assert "react/purity" in {item.rule_id for item in diagnostics}


def test_selected_workspace_does_not_scan_untouched_siblings(installation: Path, project: Path) -> None:
    nested = project / "nested"
    nested.mkdir()
    (nested / "package.json").write_text('{"dependencies":{"react":"19.2.8"}}')
    (nested / "firestore.rules").write_text((project / "firestore.rules").read_text())
    request: dict[str, JsonValue] = {
        "installRoot": str(installation),
        "config": str(project / "config.json"),
        "repositoryRoot": str(project),
        "fullScan": False,
        "paths": [str(project / "src/view.tsx")],
        "projects": [{"root": str(project), "excluded": [str(nested)]}, {"root": str(nested), "excluded": []}],
    }
    output = execute(installation, "node", str(CONFIGS / "react-doctor-runner.mjs"), json.dumps(request), guarded=True)
    assert output.returncode == 0, output.stderr
    findings = external.parse_react_doctor(output.stdout, root=project)
    assert findings
    assert all(not finding.location.path.startswith("nested/") for finding in findings)


def test_unresolved_catalog_capabilities_fail_instead_of_disabling_rules(installation: Path, project: Path) -> None:
    (project / "package.json").write_text('{"dependencies":{"react":"catalog:"}}')
    output = scan(installation, project)
    assert output.returncode != 0
    assert "requires a resolved version for react" in output.stderr


def test_catalog_capabilities_use_installed_package_version(installation: Path, project: Path) -> None:
    (project / "package.json").write_text('{"dependencies":{"react":"catalog:"}}')
    installed = project / "node_modules/react"
    installed.mkdir(parents=True)
    (installed / "package.json").write_text('{"name":"react","version":"19.2.8"}')
    output = scan(installation, project)
    assert output.returncode == 0, output.stderr
    assert "no-array-index-as-key" in {item.rule for item in Report.model_validate_json(output.stdout).diagnostics}


def test_compiler_rule_severity_and_library_exemption(installation: Path, project: Path) -> None:
    (project / "babel.config.json").write_text('{"plugins":["babel-plugin-react-compiler"]}')
    (project / "src/view.tsx").write_text(
        "export function Impure() { return <div>{Date.now()}</div>; }\n"
        "export function Parent() { const Child = () => <div/>; return <Child/>; }\n"
    )
    (project / "package.json").write_text(
        '{"name":"published-library","exports":"./src/view.tsx","dependencies":{"react":"19.2.8"}}'
    )
    config = {"warnings": False, "rules": {"react-hooks-js/purity": "warn"}}
    (project / "config.json").write_text(json.dumps(config))
    output = scan(installation, project, compiler=True)
    assert output.returncode == 0, output.stderr
    findings = Report.model_validate_json(output.stdout).diagnostics
    assert "static-components" not in {item.rule for item in findings}
    assert [(item.rule, item.severity) for item in findings if item.rule == "purity"] == [("purity", "warning")]
    config["rules"] = {"react-hooks-js/purity": "off", "react-hooks-js/static-components": "error"}
    (project / "config.json").write_text(json.dumps(config))
    output = scan(installation, project, compiler=True)
    assert output.returncode == 0, output.stderr
    rules = {item.rule for item in Report.model_validate_json(output.stdout).diagnostics}
    assert "purity" not in rules
    assert "static-components" in rules


def test_multiline_jsx_suppression_with_unicode(installation: Path, project: Path) -> None:
    (project / "firestore.rules").unlink()
    (project / "src/view.tsx").write_text(
        "export const View = ({items}) => items.map((item, index) => (\n"
        "  // react-doctor-disable-next-line react-doctor/no-array-index-as-key -- synthetic fixture\n"
        "  <div\n"
        '    title="مرحبا"\n'
        "    key={index}\n"
        "  >{item.name}</div>\n"
        "));\n"
    )
    output = scan(installation, project)
    assert output.returncode == 0, output.stderr
    assert Report.model_validate_json(output.stdout).diagnostics == ()
    view = project / "src/view.tsx"
    view.write_text(view.read_text().replace("  <div\n", "  undefined,\n  <div\n"))
    output = scan(installation, project)
    assert output.returncode == 0, output.stderr
    assert "no-array-index-as-key" in {item.rule for item in Report.model_validate_json(output.stdout).diagnostics}


def test_large_stdin_request_and_bounded_native_batches(installation: Path, project: Path) -> None:
    # A long workspace selection must not hit OS argv limits. The last file is
    # deliberately invalid so losing a batch cannot report a clean scan.
    for index in range(220):
        (project / "src" / f"{'a' * 120}{index}.tsx").write_text("export const Clean = () => <div/>;\n")
    output = scan(installation, project, paths=("src/view.tsx",) * 10000)
    assert output.returncode == 0, output.stderr
    assert "no-array-index-as-key" in {item.rule for item in Report.model_validate_json(output.stdout).diagnostics}


@pytest.mark.parametrize("relative_native", [False, True])
@pytest.mark.parametrize("alternate_index", [False, True])
def test_staged_scan_uses_selected_index_without_touching_worktree(
    installation: Path, project: Path, *, alternate_index: bool, relative_native: bool
) -> None:
    assert execute(project, "git", "add", ".").returncode == 0
    index = project / ".git/index"
    if alternate_index:
        alternate = project / ".git/index.doctor-test"
        alternate.write_bytes(index.read_bytes())
        assert execute(project, "git", "read-tree", "--empty").returncode == 0
        index = alternate
    original_index = index.read_bytes()
    view = project / "src/view.tsx"
    view.write_text("export const Clean = () => <div/>;\n")
    (project / "firestore.rules").write_text("// clean worktree fixture\n")
    original_worktree = view.read_bytes()
    output = scan(installation, project, staged=True, git_index=index, relative_native=relative_native)
    assert output.returncode == 0, output.stderr
    findings = external.parse_react_doctor(output.stdout, root=project)
    assert {item.rule_id for item in findings} >= {
        "react-doctor/no-array-index-as-key",
        "react-doctor/firebase-permissive-rules",
    }
    assert all(not item.location.path.startswith("../") for item in findings)
    assert index.read_bytes() == original_index
    assert view.read_bytes() == original_worktree


@pytest.mark.parametrize("relative_native", [False, True])
@pytest.mark.parametrize(
    ("extension", "source"),
    [
        ("astro", "---\neval(userInput);\n---\n<div/>"),
        ("html", "<html><body>مرحبا<script>eval(userInput);</script></body></html>"),
    ],
)
def test_astro_and_html_execute_native_rules_at_original_positions(
    installation: Path, project: Path, extension: str, source: str, *, relative_native: bool
) -> None:
    (project / "src/view.tsx").unlink()
    (project / f"src/view.{extension}").write_text(source)
    output = scan(installation, project, relative_native=relative_native)
    assert output.returncode == 0, output.stderr
    findings = external.parse_react_doctor(output.stdout, root=project)
    finding = next(item for item in findings if item.rule_id == "react-doctor/no-eval")
    assert finding.location.path == f"src/view.{extension}"
    assert finding.location.position is not None
    assert finding.location.position.byte_offset == len(source[: source.index("eval(")].encode())


def test_html_skips_external_and_inert_scripts(installation: Path, project: Path) -> None:
    (project / "src/view.tsx").unlink()
    (project / "firestore.rules").unlink()
    (project / "src/view.html").write_text(
        '<script src="other.js">eval(input);</script>\n'
        '<script type="application/json">{"value":"eval(input)"}</script>\n'
        "<template><script>eval(input);</script></template>\n"
        "<!-- <script>eval(input);</script> -->\n"
    )
    output = scan(installation, project)
    assert output.returncode == 0, output.stderr
    assert Report.model_validate_json(output.stdout).diagnostics == ()
