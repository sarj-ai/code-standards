from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import ValidationError
import pytest
from sarj_rule_contracts import RuleSelection, RuleSelector

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.api import Standards
from sarj_standards.libs.adoption import configs, doctor, lifecycle, manifest, scaffold
from sarj_standards.libs.adoption.service import plan_init
from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode
from sarj_standards.libs.linting import external, security_tools
from sarj_standards.libs.linting.external import ProcessOutput, analyze_external
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _mapping(value: object) -> dict[object, object]:
    assert is_object_mapping(value)
    return value


def _checkov(
    path: Path, *, code: str = "CKV_GCP_41", resource: str = "google_project_iam_member.app"
) -> dict[str, object]:
    return {
        "check_type": "kubernetes" if code.startswith("CKV_K8S") else "terraform",
        "results": {
            "failed_checks": [
                {
                    "check_id": code,
                    "check_name": "Reviewed upstream security finding",
                    "check_result": {"result": "FAILED"},
                    "file_path": f"/{path.name}",
                    "file_abs_path": str(path),
                    "file_line_range": [1, 1],
                    "resource": resource,
                    "code_block": [[1, "sensitive source must not enter diagnostics"]],
                }
            ],
            "passed_checks": [],
            "skipped_checks": [],
            "parsing_errors": [],
        },
        "summary": {"checkov_version": "3.3.20", "parsing_errors": 0},
    }


def _zizmor(path: Path) -> dict[str, object]:
    return {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "zizmor", "version": "1.30.1"}},
                "invocations": [{"executionSuccessful": True}],
                "results": [
                    {
                        "ruleId": "zizmor/template-injection",
                        "level": "error",
                        "message": {"text": "Template injection"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": path.as_uri()},
                                    "region": {"startLine": 1, "startColumn": 1},
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_pinned_commands_are_isolated_and_checks_are_offline() -> None:
    for tool, version in security_tools.VERSIONS.items():
        argv = security_tools.command(tool)
        assert "--no-config" in argv
        assert "--isolated" in argv
        assert "--offline" in argv
        assert argv[argv.index("--python") + 1] == "3.12"
        assert argv[argv.index("--from") + 1] == f"{tool}=={version}"
        assert "--offline" not in security_tools.command(tool, offline=False)


def test_checkov_normalizes_upstream_id_without_source_snippets(tmp_path: Path) -> None:
    path = tmp_path / "main.tf"
    path.write_text('resource "google_project_iam_member" "app" {}\n', encoding="utf-8")
    findings = security_tools.parse_checkov(json.dumps(_checkov(path)), root=tmp_path)
    assert len(findings) == 1
    item = findings[0]
    assert (item.code, item.rule_id, item.source, item.severity, item.location.path) == (
        "CKV_GCP_41",
        "CKV_GCP_41",
        "checkov",
        Severity.WARNING,
        "main.tf",
    )
    assert "sensitive source" not in json.dumps(item.as_dict())


def test_zizmor_preserves_upstream_identity_and_decodes_local_uri(tmp_path: Path) -> None:
    path = tmp_path / "workflow space.yml"
    path.write_text("on: push\n", encoding="utf-8")
    item = security_tools.parse_zizmor(json.dumps(_zizmor(path)), root=tmp_path)[0]
    assert (item.source, item.code, item.severity, item.location.path) == (
        "zizmor",
        "template-injection",
        Severity.WARNING,
        path.name,
    )


@pytest.mark.parametrize("failure", ["parsing-errors", "version", "outside", "unsupported-check", "line", "unknown"])
def test_checkov_rejects_incomplete_or_invalid_reports(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "main.tf"
    path.write_text("resource {}\n", encoding="utf-8")
    report = _checkov(path)
    results = report["results"]
    assert is_object_mapping(results)
    findings = results["failed_checks"]
    assert is_object_list(findings)
    finding = _mapping(findings[0])
    match failure:
        case "parsing-errors":
            results["parsing_errors"] = ["main.tf"]
        case "version":
            report["summary"] = {"checkov_version": "unexpected", "parsing_errors": 0}
        case "outside":
            finding["file_abs_path"] = str(tmp_path.parent / "outside.tf")
        case "unsupported-check":
            finding["check_id"] = "CKV_GCP_999"
        case "line":
            finding["file_line_range"] = [0, 1]
        case _:
            finding["check_result"] = {"result": "UNKNOWN"}
    with pytest.raises((ValueError, ValidationError)):
        security_tools.parse_checkov(json.dumps(report), root=tmp_path)


@pytest.mark.parametrize("payload", ["", "{}", "[]", '{"check_type":"terraform"}', "invalid"])
def test_checkov_malformed_or_empty_payload_never_passes(tmp_path: Path, payload: str) -> None:
    with pytest.raises((ValueError, ValidationError)):
        security_tools.parse_checkov(payload, root=tmp_path)


def _empty_checkov_summary() -> dict[str, object]:
    return {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "parsing_errors": 0,
        "resource_count": 0,
        "checkov_version": "3.3.20",
    }


def test_checkov_version_attested_zero_summary_is_a_complete_empty_scan(tmp_path: Path) -> None:
    assert security_tools.parse_checkov(json.dumps(_empty_checkov_summary()), root=tmp_path) == ()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("passed", 1),
        ("failed", 1),
        ("skipped", 1),
        ("parsing_errors", 1),
        ("resource_count", 1),
        ("passed", False),
        ("passed", "0"),
        ("checkov_version", "wrong"),
        ("failed_checks", []),
    ],
)
def test_checkov_bare_summary_never_hides_findings_errors_or_unattested_data(
    tmp_path: Path, key: str, value: object
) -> None:
    summary = _empty_checkov_summary()
    summary[key] = value
    with pytest.raises((ValueError, ValidationError)):
        security_tools.parse_checkov(json.dumps(summary), root=tmp_path)


def test_checkov_bare_summary_requires_all_scan_counters(tmp_path: Path) -> None:
    summary = {key: value for key, value in _empty_checkov_summary().items() if key != "resource_count"}
    with pytest.raises((ValueError, ValidationError)):
        security_tools.parse_checkov(json.dumps(summary), root=tmp_path)


@pytest.mark.parametrize("failure", ["version", "incomplete", "remote-uri", "outside", "line", "unknown-audit"])
def test_zizmor_rejects_incomplete_or_invalid_reports(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("on: push\n", encoding="utf-8")
    report = _zizmor(path)
    runs = report["runs"]
    assert is_object_list(runs)
    run = _mapping(runs[0])
    match failure:
        case "version":
            _mapping(_mapping(run["tool"])["driver"])["version"] = "unexpected"
        case "incomplete":
            invocations = run["invocations"]
            assert is_object_list(invocations)
            _mapping(invocations[0])["executionSuccessful"] = False
        case "unknown-audit":
            results = run["results"]
            assert is_object_list(results)
            _mapping(results[0])["ruleId"] = "zizmor/future-audit"
        case _:
            results = run["results"]
            assert is_object_list(results)
            locations = _mapping(results[0])["locations"]
            assert is_object_list(locations)
            physical = _mapping(_mapping(locations[0])["physicalLocation"])
            match failure:
                case "remote-uri":
                    _mapping(physical["artifactLocation"])["uri"] = "https://example.invalid/workflow.yml"
                case "outside":
                    _mapping(physical["artifactLocation"])["uri"] = (tmp_path.parent / "outside.yml").as_uri()
                case _:
                    _mapping(physical["region"])["startLine"] = True
    with pytest.raises((ValueError, ValidationError)):
        security_tools.parse_zizmor(json.dumps(report), root=tmp_path)


@pytest.mark.parametrize("image", ['"${IMAGE}"', '"{{ IMAGE }}"'])
def test_image_template_defer_is_informational_and_resource_scoped(tmp_path: Path, image: str) -> None:
    path = tmp_path / "pod.yml"
    path.write_text(
        f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: app\nspec:\n  containers:\n    - image: {image}\n",
        encoding="utf-8",
    )
    report = _checkov(path, code="CKV_K8S_43", resource="Pod.default.app")
    item = security_tools.parse_checkov(json.dumps(report), root=tmp_path)[0]
    assert item.severity is Severity.INFO
    assert "rendered artifact" in item.notes[0]
    other = _checkov(path, code="CKV_K8S_43", resource="Pod.default.other")
    assert security_tools.parse_checkov(json.dumps(other), root=tmp_path)[0].severity is Severity.WARNING
    resources = _checkov(path, code="CKV_K8S_10", resource="Pod.default.app")
    assert security_tools.parse_checkov(json.dumps(resources), root=tmp_path)[0].severity is Severity.WARNING


def test_mixed_static_and_template_images_do_not_hide_static_digest_findings(tmp_path: Path) -> None:
    path = tmp_path / "pod.yml"
    path.write_text(
        'apiVersion: v1\nkind: Pod\nmetadata:\n  name: app\nspec:\n  containers:\n    - image: "${IMAGE}"\n    - image: app:latest\n',
        encoding="utf-8",
    )
    report = _checkov(path, code="CKV_K8S_43", resource="Pod.default.app")
    assert security_tools.parse_checkov(json.dumps(report), root=tmp_path)[0].severity is Severity.WARNING


@pytest.mark.parametrize("suffix", [".tf", ".tf.json"])
def test_terraform_kubernetes_digest_findings_never_use_yaml_template_classification(
    tmp_path: Path, suffix: str
) -> None:
    path = tmp_path / f"pod{suffix}"
    source = (
        'resource "kubernetes_deployment" "app" { image = "${var.image}" }\n'
        if suffix == ".tf"
        else '{"resource":{"kubernetes_deployment":{"app":{"image":"${var.image}"}}}}\n'
    )
    path.write_text(source, encoding="utf-8")
    report = _checkov(path, code="CKV_K8S_43", resource="kubernetes_deployment.app")
    report["check_type"] = "terraform"
    findings = security_tools.parse_checkov(json.dumps(report), root=tmp_path)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].notes == ()


def test_security_routing_uses_actual_selected_source_and_offline_managed_config(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("on: push\n", encoding="utf-8")
    terraform = tmp_path / "main.tf"
    terraform.write_text("resource {}\n", encoding="utf-8")
    config = tmp_path / "settings.yml"
    config.write_text("setting: true\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        calls.append(tuple(argv))
        assert cwd == tmp_path
        assert "--offline" in argv
        assert "--no-config" in argv
        if "zizmor" in argv:
            assert "--strict-collection" in argv
            assert "--no-exit-codes" in argv
            assert "--no-ignores" in argv
            return ProcessOutput(0, json.dumps(_zizmor(workflow)), "")
        assert argv[argv.index("--framework") + 1] == "terraform"
        assert "--skip-download" in argv
        return ProcessOutput(1, json.dumps(_checkov(terraform)), "")

    reports = analyze_external(
        [str(tmp_path)], root=tmp_path, trust=TrustMode.SAFE, runner=run, capabilities=frozenset({"zizmor", "checkov"})
    )
    assert [report.name for report in reports] == ["zizmor", "checkov"]
    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert [report.version for report in reports] == ["1.30.1", "3.3.20"]
    assert all(str(config) not in argv for argv in calls)


@pytest.mark.parametrize(("code", "payload"), [(0, "{}"), (1, "{}"), (2, "{}")])
def test_process_and_protocol_failures_are_execution_issues(tmp_path: Path, code: int, payload: str) -> None:
    path = tmp_path / "main.tf"
    path.write_text("resource {}\n", encoding="utf-8")

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert "checkov" in argv
        assert cwd == tmp_path
        return ProcessOutput(code, payload, "")

    report = analyze_external(
        [str(path)], root=tmp_path, trust=TrustMode.SAFE, runner=run, capabilities=frozenset({"checkov"})
    )[0]
    assert report.completion is Completion.FAILED
    assert report.issues


def test_zizmor_exit_one_is_audit_failure_even_with_findings(tmp_path: Path) -> None:
    path = tmp_path / "action.yml"
    path.write_text("name: fixture\n", encoding="utf-8")

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert "zizmor" in argv
        assert cwd == tmp_path
        return ProcessOutput(1, json.dumps(_zizmor(path)), "")

    report = analyze_external(
        [str(path)], root=tmp_path, trust=TrustMode.SAFE, runner=run, capabilities=frozenset({"zizmor"})
    )[0]
    assert report.completion is Completion.FAILED


def test_security_process_preserves_environment_allowlist_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "synthetic")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic")
    monkeypatch.setenv("UV_INDEX_PASSWORD", "synthetic")
    safe_keys = ("UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "UV_TOOL_DIR")
    for key in safe_keys:
        monkeypatch.setenv(key, str(tmp_path / key))

    def bounded(
        argv: Sequence[str], *, cwd: Path, environment: dict[str, str], timeout_seconds: float
    ) -> ProcessOutput:
        assert argv == ("checkov",)
        assert cwd == tmp_path
        assert "AWS_ACCESS_KEY_ID" not in environment
        assert "GITHUB_TOKEN" not in environment
        assert "UV_INDEX_PASSWORD" not in environment
        for key in safe_keys:
            assert environment[key] == str(tmp_path / key)
        assert timeout_seconds == 300
        return ProcessOutput(0, "{}", "")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the production process boundary; injected runners bypass the environment and timeout controls being tested.
        external, "_run_process", bounded
    )
    external._security_runner(external.run_process, ("checkov",), cwd=tmp_path, name="checkov")  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]


def test_upstream_selectors_and_exclusions_use_canonical_ids(tmp_path: Path) -> None:
    assert str(RuleSelector.parse("checkov:CKV_GCP_41")) == "checkov:CKV_GCP_41"
    assert manifest.validate_excluded_rule("checkov:CKV_GCP_41") == "checkov:CKV_GCP_41"
    assert manifest.validate_excluded_rule("zizmor:template-injection") == "zizmor:template-injection"
    standards = Standards(tmp_path)
    valid = standards.analyze([], rules=["checkov:CKV_GCP_41", "zizmor:template-injection"])
    assert valid.completion is Completion.COMPLETE
    invalid = standards.analyze([], rules=["checkov:CKV_GCP_999"])
    assert invalid.completion is Completion.FAILED
    assert any(
        "unknown or invalid rule selector" in issue.message for report in invalid.tools for issue in report.issues
    )
    with pytest.raises(ValueError, match="unknown Standards rule exclusion"):
        manifest.validate_excluded_rule("checkov:CKV_GCP_999")


@pytest.mark.parametrize("tool", security_tools.TOOLS)
def test_public_analysis_retains_only_the_selected_upstream_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    if tool == "checkov":
        path = tmp_path / "main.tf"
        path.write_text('resource "google_project_iam_member" "app" {}\n', encoding="utf-8")
        payload = _checkov(path)
        results = _mapping(payload["results"])
        findings = results["failed_checks"]
        assert is_object_list(findings)
        findings.append({**_mapping(findings[0]), "check_id": "CKV_GCP_95"})
        rule = "CKV_GCP_41"
    else:
        path = tmp_path / ".github" / "workflows" / "ci.yml"
        path.parent.mkdir(parents=True)
        path.write_text("on: push\n", encoding="utf-8")
        payload = _zizmor(path)
        runs = payload["runs"]
        assert is_object_list(runs)
        findings = _mapping(runs[0])["results"]
        assert is_object_list(findings)
        findings.append({**_mapping(findings[0]), "ruleId": "zizmor/dangerous-triggers"})
        rule = "template-injection"
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    executable = binary_directory / "uvx"
    expected = ["--check", rule] if tool == "checkov" else ["--persona", "auditor"]
    executable.write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        f"expected = {expected!r}\n"
        "assert sys.argv[sys.argv.index(expected[0]) + 1] == expected[1]\n"
        f"print({json.dumps(payload)!r})\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary_directory), prepend=":")
    report = Standards(tmp_path).analyze([str(path)], external=True, rules=[f"{tool}:{rule}"])
    assert report.completion is Completion.COMPLETE
    assert [item.code for item in report.diagnostics] == [rule]
    assert [item.source for item in report.diagnostics] == [tool]


def test_security_adoption_detects_sources_and_prepares_tools_separately(tmp_path: Path) -> None:
    action = tmp_path / "action.yml"
    action.write_text("name: fixture\n", encoding="utf-8")
    terraform = tmp_path / "main.tf"
    terraform.write_text("resource {}\n", encoding="utf-8")
    detected = scaffold.detect(tmp_path)
    assert detected.actions
    assert detected.infrastructure
    selected = manifest.default_configs(
        has_python=False, has_typescript=False, has_actions=detected.actions, has_infrastructure=detected.infrastructure
    )
    assert {"zizmor", "checkov"}.issubset(selected)
    commands = lifecycle.install_commands(tmp_path, detected, hook_manager="none")
    assert len(commands) == 2
    assert all("--offline" not in command.argv for command in commands)
    disabled = scaffold.configured_ecosystems(detected, ())
    assert lifecycle.install_commands(tmp_path, disabled, hook_manager="none") == []


@pytest.mark.parametrize("tool", security_tools.TOOLS)
@pytest.mark.parametrize("state", ["current", "missing", "drift"])
def test_doctor_recognizes_and_verifies_adopted_security_configs(tmp_path: Path, tool: str, state: str) -> None:
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=(tool,),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    source, target = configs.CONFIG_NAMES[tool]
    if state == "current":
        (tmp_path / target).write_bytes((CONFIGS_DIR / source).read_bytes())
    elif state == "drift":
        (tmp_path / target).write_text("different: true\n", encoding="utf-8")
    findings = doctor.diagnose_adoption_health(tmp_path)
    assert not any(finding.id == "doctor.config.unknown" for finding in findings)
    assert any(finding.id == f"doctor.config.{state}" and finding.where == target for finding in findings)


def test_ci_prepares_pinned_tools_before_offline_analysis(tmp_path: Path) -> None:
    ecosystems = scaffold.Ecosystems(python=False, typescript=False, actions=True, infrastructure=True)
    workflow = scaffold.github_ci_workflow(tmp_path, ecosystems=ecosystems)
    for tool in security_tools.TOOLS:
        assert f"--from {tool}=={security_tools.VERSIONS[tool]} {tool} --version" in workflow
        assert workflow.index(f"Prepare pinned {tool}") < workflow.index("Run standards")


def test_old_manifest_does_not_implicitly_enable_new_security_capabilities(tmp_path: Path) -> None:
    (tmp_path / manifest.MANIFEST_NAME).write_text(
        'schema = 4\nbundle = "8.12.1"\n[capabilities]\ndisable = []\n',
        encoding="utf-8",
    )
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert "zizmor" not in adopted.enabled_capabilities
    assert "checkov" not in adopted.enabled_capabilities


def test_terraform_json_is_routed_to_checkov(tmp_path: Path) -> None:
    path = tmp_path / "main.tf.json"
    path.write_text('{"resource":{}}\n', encoding="utf-8")

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert str(path) in argv
        assert cwd == tmp_path
        return ProcessOutput(1, json.dumps(_checkov(path)), "")

    reports = analyze_external(
        [str(path)], root=tmp_path, trust=TrustMode.SAFE, runner=run, capabilities=frozenset({"checkov"})
    )
    assert len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE


@pytest.mark.parametrize(
    "source",
    [
        "  apiVersion: v1\n  kind: Pod\n  metadata: {name: app}\n",
        '"apiVersion": v1\n"kind": Pod\nmetadata: {name: app}\n',
        "apiVersion: v1\nkind: List\nitems:\n  - apiVersion: v1\n    kind: Pod\n    metadata: {name: app}\n",
    ],
)
def test_kubernetes_discovery_parses_valid_yaml_ownership(tmp_path: Path, source: str) -> None:
    path = tmp_path / "manifest.yml"
    path.write_text(source, encoding="utf-8")
    assert security_tools.select_inputs([str(path)], root=tmp_path).kubernetes == (str(path),)


def test_nested_metadata_does_not_own_generic_yaml(tmp_path: Path) -> None:
    path = tmp_path / "dataset.yml"
    path.write_text("fields:\n  apiVersion: text\n  kind: text\n", encoding="utf-8")
    assert security_tools.select_inputs([str(path)], root=tmp_path).kubernetes == ()


@pytest.mark.parametrize(
    "source",
    [
        "{apiVersion: v1, kind: Pod, metadata: {name: app}}\n",
        '{"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "app"}}\n',
        "{apiVersion: v1,\n kind: Pod, metadata: {name: app}}\n",
    ],
)
def test_kubernetes_discovery_does_not_depend_on_block_key_spelling(tmp_path: Path, source: str) -> None:
    path = tmp_path / "manifest.yml"
    path.write_text(source, encoding="utf-8")
    assert security_tools.select_inputs([str(path)], root=tmp_path).kubernetes == (str(path),)


@pytest.mark.parametrize(
    "source",
    [
        "fields: {apiVersion: text, kind: text}\n",
        'description: \'{"apiVersion": "v1", "kind": "Pod"}\'\n',
        "description: |\n  {apiVersion: v1, kind: Pod}\n",
    ],
)
def test_nested_or_quoted_flow_keys_do_not_own_generic_yaml(tmp_path: Path, source: str) -> None:
    path = tmp_path / "dataset.yml"
    path.write_text(source, encoding="utf-8")
    assert security_tools.select_inputs([str(path)], root=tmp_path).kubernetes == ()


def test_discovery_ignores_large_unrelated_dataset_but_limits_owned_sources(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.yml"
    dataset.write_text("rows:\n" + "  - value\n" * 250_000, encoding="utf-8")
    assert not scaffold.detect(tmp_path).infrastructure
    # Explicit adoption of an unrelated capability must also complete discovery.
    assert plan_init(tmp_path, configs=("yamllint",), hook_manager="none").scaffold.configs == ("yamllint",)
    dataset.write_text("apiVersion: v1\nkind: Pod\n" + "# padding\n" * 250_000, encoding="utf-8")
    with pytest.raises(ValueError, match="2 MiB size limit"):
        security_tools.select_inputs([str(dataset)], root=tmp_path)


@pytest.mark.parametrize(
    "capabilities", [frozenset({"zizmor"}), frozenset({"checkov"})], ids=["zizmor-only", "gcp-only"]
)
def test_unrelated_security_selection_does_not_read_kubernetes_yaml(
    tmp_path: Path, capabilities: frozenset[str]
) -> None:
    path = tmp_path / "pod.yml"
    path.write_bytes(b"apiVersion: v1\nkind: Pod\n\xff")
    inputs = security_tools.select_inputs(
        [str(path)], root=tmp_path, capabilities=capabilities, checkov_rule_ids=frozenset({"CKV_GCP_95"})
    )
    assert inputs.kubernetes == ()


@pytest.mark.parametrize(
    ("kind", "prefix", "container_key", "companion", "severity"),
    [
        ("Pod", "spec:\n", "containers", "app@sha256:abc", Severity.INFO),
        ("PodTemplate", "template:\n  spec:\n", "containers", "app@sha256:abc", Severity.INFO),
        ("Deployment", "spec:\n  template:\n    spec:\n", "containers", "app@sha256:abc", Severity.INFO),
        (
            "CronJob",
            "spec:\n  jobTemplate:\n    spec:\n      template:\n        spec:\n",
            "containers",
            "app@sha256:abc",
            Severity.INFO,
        ),
        ("Pod", "spec:\n", "initContainers", "app:latest", Severity.WARNING),
    ],
)
def test_digest_deferral_uses_only_upstream_container_paths(
    tmp_path: Path, *, kind: str, prefix: str, container_key: str, companion: str, severity: Severity
) -> None:
    path = tmp_path / "pod.yml"
    indentation = " " * (len(prefix.splitlines()[-1]) - len(prefix.splitlines()[-1].lstrip()) + 2)
    source = (
        f"apiVersion: v1\nkind: {kind}\nmetadata:\n  name: app\n  annotations:\n    image: logo.svg\n{prefix}"
        f'{indentation}containers:\n{indentation}  - image: "${{IMAGE}}"\n'
    )
    if container_key != "containers":
        source += f"{indentation}{container_key}:\n"
    source += f"{indentation}  - image: {companion}\n"
    path.write_text(source, encoding="utf-8")
    report = _checkov(path, code="CKV_K8S_43", resource=f"{kind}.default.app")
    assert security_tools.parse_checkov(json.dumps(report), root=tmp_path)[0].severity is severity


def test_list_digest_deferral_is_scoped_to_the_upstream_resource(tmp_path: Path) -> None:
    path = tmp_path / "pods.yml"
    path.write_text(
        "apiVersion: v1\nkind: List\nitems:\n  - apiVersion: v1\n    kind: Pod\n"
        '    metadata: {name: app}\n    spec:\n      containers:\n        - image: "${IMAGE}"\n'
        "  - apiVersion: v1\n    kind: Pod\n    metadata: {name: other}\n"
        "    spec:\n      containers:\n        - image: app:latest\n",
        encoding="utf-8",
    )
    for resource, severity in (("Pod.default.app", Severity.INFO), ("Pod.default.other", Severity.WARNING)):
        report = _checkov(path, code="CKV_K8S_43", resource=resource)
        assert security_tools.parse_checkov(json.dumps(report), root=tmp_path)[0].severity is severity


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("payload", ["valid", "broken"])
def test_explicit_zizmor_audit_enables_auditor_persona_without_relaxing_protocol(
    tmp_path: Path, selected: bool, payload: str
) -> None:
    path = tmp_path / "action.yml"
    path.write_text("name: fixture\n", encoding="utf-8")

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        assert ("--persona" in argv) is selected
        if selected:
            assert argv[argv.index("--persona") + 1] == "auditor"
        return ProcessOutput(0, json.dumps(_zizmor(path)) if payload == "valid" else "{}", "")

    report = analyze_external(
        [str(path)],
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=run,
        capabilities=frozenset({"zizmor"}),
        security_selection=RuleSelection(frozenset({RuleSelector.parse("zizmor:concurrency-limits")}))
        if selected
        else None,
    )[0]
    assert report.completion is (Completion.COMPLETE if payload == "valid" else Completion.FAILED)


@pytest.mark.parametrize("audit", sorted(security_tools.ZIZMOR_ONLINE_ONLY))
def test_online_only_zizmor_selectors_fail_with_offline_diagnostic(tmp_path: Path, audit: str) -> None:
    selector = f"zizmor:{audit}"
    assert manifest.validate_excluded_rule(selector) == selector
    report = Standards(tmp_path).analyze([], rules=[selector])
    assert report.completion is Completion.FAILED
    assert any("cannot run in offline analysis" in issue.message for tool in report.tools for issue in tool.issues)


@pytest.mark.parametrize("code", ["CKV_GCP_95", "CKV_K8S_43"])
def test_explicit_checkov_selection_limits_checks_and_preserves_terraform_provider_coverage(
    tmp_path: Path, code: str
) -> None:
    terraform = tmp_path / "main.tf"
    terraform.write_text('locals { region = "local" }\n', encoding="utf-8")
    pod = tmp_path / "pod.yml"
    pod.write_text("apiVersion: v1\nkind: Pod\nspec:\n  containers: [\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        calls.append(tuple(argv))
        assert argv[argv.index("--check") + 1] == code
        assert argv[argv.index("--framework") + 1] == "terraform"
        return ProcessOutput(0, json.dumps(_empty_checkov_summary()), "")

    paths = [str(terraform), str(pod)] if code == "CKV_GCP_95" else [str(terraform)]
    reports = analyze_external(
        paths,
        root=tmp_path,
        trust=TrustMode.SAFE,
        runner=run,
        capabilities=frozenset({"checkov"}),
        security_selection=RuleSelection(frozenset({RuleSelector.parse(f"checkov:{code}")})),
    )
    assert len(calls) == 1
    assert all(str(pod) not in argv for argv in calls)
    assert len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE
