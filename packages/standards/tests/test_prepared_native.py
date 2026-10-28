from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_standards.api import Standards
import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption.manifest import Manifest, PreparedTarget, adopted_version
from sarj_standards.libs.diagnostics import Completion, TrustMode
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.devops_tools import TOOLS, checked_tool
from sarj_standards.libs.linting.external import run_process, run_process_input
from sarj_standards.libs.linting.prepared_devops import analyze_prepared


if TYPE_CHECKING:
    from pydantic import JsonValue


_CASES = (
    (
        "systemd",
        "systemd-analyze",
        "--version",
        "etc/systemd/system/example.service",
        "[Unit]\nDefaultDependencies=no\n[Service]\nType=oneshot\nExecStart=/usr/local/bin/example\n",
        "[Service]\nUnknownSetting=yes\n",
    ),
    (
        "nginx",
        "nginx",
        "-v",
        "nginx.conf",
        "pid logs/nginx.pid;\nerror_log stderr;\nevents {}\n",
        "unknown_directive on;\n",
    ),
    ("kamailio", "kamailio", "-V", "kamailio.cfg", "#!KAMAILIO\nrequest_route { exit; }\n", "unknown_setting = 1\n"),
    (
        "prometheus-config",
        "promtool",
        "--version",
        "prometheus.yaml",
        "global: {scrape_interval: 15s}\nscrape_configs: []\n",
        "unknown_setting: true\n",
    ),
    (
        "prometheus-rules",
        "promtool",
        "--version",
        "rules.yaml",
        "groups:\n- name: example\n  rules:\n  - record: example:up\n    expr: sum(up)\n",
        "groups:\n- name: example\n  rules:\n  - record: example:up\n    expr: up ==\n",
    ),
)


def _receipt(root: Path, kind: str, entry: str, content: str, version: str) -> Path:
    source = root / "source.conf"
    source.write_text(content)
    prepared = root / "prepared"
    prepared.mkdir(exist_ok=True)
    path = prepared / entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    artifacts = {entry: sha256(path.read_bytes()).hexdigest()}
    executables: list[str] = []
    if kind == "systemd":
        binary = prepared / "usr/local/bin/example"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("#!/bin/sh\nexit 0\n")
        artifacts["usr/local/bin/example"] = sha256(binary.read_bytes()).hexdigest()
        executables.append("usr/local/bin/example")
    target = {
        "id": "example",
        "source": source.name,
        "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "kind": kind,
        "native_version": version,
        "manifests": [entry],
        "artifacts": artifacts,
        "executables": executables,
    }
    if kind == "compose":
        (prepared / "overlay.yaml").write_text("services:\n  app:\n    image: ${IMAGE:?image is required}\n")
        (prepared / "bound.env").write_text("IMAGE=alpine:3.22\n")
        target["manifests"] = [entry, "overlay.yaml"]
        target["environment_file"] = "bound.env"
        artifacts.update(
            {name: sha256((prepared / name).read_bytes()).hexdigest() for name in ("overlay.yaml", "bound.env")}
        )
    receipt = prepared / "receipt.json"
    receipt.write_text(json.dumps({"version": 1, "targets": [target]}))
    return receipt


@pytest.mark.parametrize(
    ("kind", "program", "flag", "entry", "valid", "invalid"), _CASES, ids=[case[0] for case in _CASES]
)
def test_matching_native_validator_accepts_valid_and_rejects_invalid_prepared_config(
    tmp_path: Path, *, kind: str, program: str, flag: str, entry: str, valid: str, invalid: str
) -> None:
    output = run_process((program, flag), cwd=tmp_path)
    assert output.returncode == 0
    version = (output.stderr if kind == "nginx" else output.stdout).splitlines()[0]
    declared = (PreparedTarget("example", "source.conf"),)
    receipt = _receipt(tmp_path, kind, entry, valid, version)
    (report,) = analyze_prepared((receipt,), root=tmp_path, declared=declared, trust_repository_code=True)
    assert report.completion is Completion.COMPLETE, report.issues
    assert not report.diagnostics
    assert not report.issues
    broken = invalid if kind == "prometheus-rules" else valid + invalid
    receipt = _receipt(tmp_path, kind, entry, broken, version)
    (invalid_report,) = analyze_prepared((receipt,), root=tmp_path, declared=declared, trust_repository_code=True)
    assert invalid_report.completion is Completion.FAILED
    assert invalid_report.issues


def test_native_validation_requires_explicit_trust_and_attested_runtime(tmp_path: Path) -> None:
    entry = "etc/systemd/system/example.service"
    receipt = _receipt(tmp_path, "systemd", entry, _CASES[0][4], "wrong-version")
    declared = (PreparedTarget("example", "source.conf"),)
    (untrusted,) = analyze_prepared((receipt,), root=tmp_path, declared=declared)
    assert untrusted.completion is Completion.FAILED
    assert "trusted repository code" in untrusted.issues[0].message
    (wrong_runtime,) = analyze_prepared((receipt,), root=tmp_path, declared=declared, trust_repository_code=True)
    assert wrong_runtime.completion is Completion.FAILED
    assert "exact version" in wrong_runtime.issues[0].message


def test_mutated_rendered_config_cannot_reuse_a_valid_receipt(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path, "systemd", "example.service", _CASES[0][4], "unused")
    (receipt.parent / "example.service").write_text("mutated\n")
    (report,) = analyze_prepared(
        (receipt,), root=tmp_path, declared=(PreparedTarget("example", "source.conf"),), trust_repository_code=True
    )
    assert report.completion is Completion.FAILED
    assert "hash does not match" in report.issues[0].message


@pytest.mark.parametrize("extra", ["", "    depends_on: [missing]\n"], ids=("valid-project", "undefined-service"))
def test_prepared_compose_uses_bound_environment_and_full_native_consistency(tmp_path: Path, extra: str) -> None:
    content = "services:\n  app:\n    environment: {MODE: base}\n" + extra
    receipt = _receipt(tmp_path, "compose", "base.yaml", content, TOOLS["docker"].version)
    (report,) = analyze_prepared(
        (receipt,), root=tmp_path, declared=(PreparedTarget("example", "source.conf"),), trust_repository_code=True
    )
    assert report.completion is (Completion.FAILED if extra else Completion.COMPLETE), report.issues
    assert bool(report.issues) == bool(extra)


def test_prepared_compose_cannot_use_mutated_environment_inputs(tmp_path: Path) -> None:
    receipt = _receipt(
        tmp_path, "compose", "base.yaml", "services:\n  app:\n    environment: {MODE: base}\n", TOOLS["docker"].version
    )
    (receipt.parent / "bound.env").write_text("IMAGE=changed\n")
    (report,) = analyze_prepared(
        (receipt,), root=tmp_path, declared=(PreparedTarget("example", "source.conf"),), trust_repository_code=True
    )
    assert report.completion is Completion.FAILED
    assert "hash does not match" in report.issues[0].message


def test_terraform_template_is_rendered_before_systemd_validation_and_binds_its_inputs(tmp_path: Path) -> None:
    fixtures = Path(__file__).parent / "fixtures/prepared-native"
    for name in ("example.service.tftpl", "variables.tfvars"):
        (tmp_path / name).write_bytes((fixtures / name).read_bytes())
    (tmp_path / "variables.tf").write_text('variable "description" { type = string }\n')
    terraform = checked_tool("terraform", root=tmp_path)
    assert terraform.executable is not None
    rendered = run_process_input(
        (str(terraform.executable), "console", "-no-color", "-var-file=variables.tfvars"),
        cwd=tmp_path,
        source='jsonencode(templatefile("example.service.tftpl", {description = var.description}))\n',
    )
    assert rendered.returncode == 0
    encoded = parse_json(rendered.stdout)
    assert isinstance(encoded, str)
    content = parse_json(encoded)
    assert isinstance(content, str)
    version = run_process(("systemd-analyze", "--version"), cwd=tmp_path).stdout.splitlines()[0]
    receipt = _receipt(tmp_path, "systemd", "etc/systemd/system/example.service", content, version)
    payload = parse_json(receipt.read_text())
    assert isinstance(payload, dict)
    targets = payload["targets"]
    assert isinstance(targets, list)
    target = targets[0]
    assert isinstance(target, dict)
    target["source"] = "example.service.tftpl"
    inputs: dict[str, JsonValue] = {
        name: sha256((tmp_path / name).read_bytes()).hexdigest()
        for name in ("example.service.tftpl", "variables.tfvars", "variables.tf")
    }
    target["source_inputs"] = inputs
    target["source_sha256"] = inputs["example.service.tftpl"]
    receipt.write_text(json.dumps(payload))
    declared = (PreparedTarget("example", "example.service.tftpl"),)
    (report,) = analyze_prepared((receipt,), root=tmp_path, declared=declared, trust_repository_code=True)
    assert report.completion is Completion.COMPLETE, report.issues
    assert not report.issues
    (tmp_path / "variables.tfvars").write_text('description = "Changed"\n')
    (stale,) = analyze_prepared((receipt,), root=tmp_path, declared=declared, trust_repository_code=True)
    assert stale.completion is Completion.FAILED
    assert "hash does not match" in stale.issues[0].message


@pytest.mark.parametrize("trust", [TrustMode.SAFE, TrustMode.TRUSTED])
def test_public_api_and_cli_preserve_native_prepared_trust(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], trust: TrustMode
) -> None:
    version = run_process(("systemd-analyze", "--version"), cwd=tmp_path).stdout.splitlines()[0]
    receipt = _receipt(tmp_path, "systemd", _CASES[0][3], _CASES[0][4], version)
    (tmp_path / ".sarj-standards.toml").write_text(
        Manifest(adopted_version(), (), ".", ".", prepared_targets=(PreparedTarget("example", "source.conf"),)).render()
    )
    report = Standards(tmp_path).analyze(prepared_devops=(receipt,), prepared_only=True, trust=trust)
    arguments = [
        "--root",
        str(tmp_path),
        "analyze",
        "--format",
        "json",
        "--prepared-only",
        "--prepared-devops",
        str(receipt),
    ]
    if trust is TrustMode.TRUSTED:
        arguments.append("--trust-repository-code")
    status = cli.main(arguments)
    output = capsys.readouterr()
    assert not output.err
    assert status == report.exit_code == (0 if trust is TrustMode.TRUSTED else 2)
    assert parse_json(output.out) == report.as_dict()
