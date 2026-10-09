from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_standards.api import Standards
import sarj_standards.cli.main as cli
from sarj_standards.libs.adoption.manifest import Manifest, PreparedTarget, adopted_version, as_table, list_field
from sarj_standards.libs.linting.devops_tools import checked_tool


if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class _PreparedFixture:
    root: Path
    receipt: Path
    target: dict[str, object]


def _prepared_fixture(root: Path) -> _PreparedFixture:
    source = root / "deploy.yaml"
    source.write_text("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: example\n", encoding="utf-8")
    (root / "component.tsx").write_text("export const Component = () => <button />;\n", encoding="utf-8")
    directory = root / "prepared"
    directory.mkdir()
    (directory / "resource.yaml").write_bytes(source.read_bytes())
    (directory / "schema.json").write_text(
        '{"$schema":"http://json-schema.org/draft-04/schema#",'
        '"type":"object","required":["apiVersion","kind","metadata"]}',
        encoding="utf-8",
    )
    target: dict[str, object] = {
        "id": "example",
        "source": "deploy.yaml",
        "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "kind": "kubernetes",
        "kubernetes_version": "1.33.0",
        "manifests": ["resource.yaml"],
        "schema_bindings": {"v1/ConfigMap": "schema.json"},
        "artifacts": {
            name: sha256((directory / name).read_bytes()).hexdigest() for name in ("resource.yaml", "schema.json")
        },
    }
    fixture = _PreparedFixture(root, directory / "receipt.json", target)
    _write_receipt(fixture)
    (root / ".sarj-standards.toml").write_text(
        Manifest(
            adopted_version(), ("eslint",), ".", ".", prepared_targets=(PreparedTarget("example", "deploy.yaml"),)
        ).render(),
        encoding="utf-8",
    )
    return fixture


def _write_receipt(fixture: _PreparedFixture) -> None:
    fixture.receipt.write_text(json.dumps({"version": 1, "targets": [fixture.target]}), encoding="utf-8")


def _paired_analysis(
    fixture: _PreparedFixture,
    capsys: pytest.CaptureFixture[str],
    *,
    paths: Sequence[str] = (),
    receipts: Sequence[Path] = (),
    targets: Sequence[str] = (),
    prepared_only: bool = False,
) -> dict[str, object]:
    documents: list[dict[str, object]] = []
    arguments = ["--root", str(fixture.root), "analyze", "--format", "json"]
    if prepared_only:
        arguments.append("--prepared-only")
    for receipt in receipts:
        arguments.extend(("--prepared-devops", str(receipt)))
    for target in targets:
        arguments.extend(("--prepared-target", target))
    arguments.extend(paths)
    for _ in range(2):
        report = Standards(fixture.root).analyze(
            paths or None, prepared_devops=receipts, prepared_targets=targets, prepared_only=prepared_only
        )
        status = cli.main(arguments)
        output = capsys.readouterr()
        assert not output.err
        payload: object = json.loads(output.out)  # pyright: ignore[reportAny]
        document = as_table(payload)
        assert status == report.exit_code
        assert document == report.as_dict()
        assert document["root"] == "."
        documents.append(document)
    assert documents[0] == documents[1]
    return documents[0]


@pytest.mark.parametrize("mode", ["source-only", "prepared-only", "mixed", "mixed-deferred"])
def test_public_cli_api_prepared_analysis_is_paired_and_repeat_stable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mode: str
) -> None:
    fixture = _prepared_fixture(tmp_path)
    source_only = mode == "source-only"
    prepared_only = mode == "prepared-only"
    mixed_deferred = mode == "mixed-deferred"
    document = _paired_analysis(
        fixture,
        capsys,
        paths={
            "source-only": ("deploy.yaml",),
            "prepared-only": (),
            "mixed": ("deploy.yaml",),
            "mixed-deferred": ("deploy.yaml", "component.tsx"),
        }[mode],
        receipts=() if source_only else (fixture.receipt,),
        prepared_only=prepared_only,
    )
    assert document["exitCode"] == (2 if mixed_deferred else 0)
    assert document["diagnostics"] == []
    assert document["issues"] == []
    tools = tuple(as_table(item) for item in list_field(document, "tools"))
    coverage = tuple(as_table(item) for item in list_field(document, "coverage"))
    prepared = [tool for tool in tools if tool["name"] == "prepared-devops:example"]
    assert len(prepared) == (0 if source_only else 1)
    assert all(tool["completion"] == "complete" and tool["fileCount"] == 1 for tool in prepared)
    if prepared_only:
        assert len(tools) == 1
    else:
        assert any(tool["name"] == "sarj-iac-lint" and tool["fileCount"] == 1 for tool in tools)
    if source_only:
        assert len(coverage) == 1
        assert coverage[0]["source"] == "prepared-devops"
        assert coverage[0]["fileCount"] == 1
        assert coverage[0]["disposition"] == "not-requested"
        assert document["conclusion"] == "passed"
    elif mixed_deferred:
        assert len(coverage) == 1
        assert coverage[0]["source"] == "eslint"
        assert coverage[0]["disposition"] == "failed"
        assert document["completion"] == "partial"
        assert document["conclusion"] == "inconclusive"
    else:
        assert coverage == ()
    if not source_only:
        assert checked_tool("kubeconform", root=tmp_path).version == "0.8.0"
        assert checked_tool("kube-linter", root=tmp_path).version == "0.8.3"


@pytest.mark.parametrize(
    "mutation",
    [
        "malformed-json",
        "boolean-version",
        "stale-source",
        "wrong-source",
        "case-identity",
        "undeclared-target",
        "duplicate-target",
        "duplicate-receipt",
        "prepared-with-source",
    ],
)
def test_public_cli_api_invalid_receipts_and_target_identity_fail_repeat_stably(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mutation: str
) -> None:
    fixture = _prepared_fixture(tmp_path)
    targets: tuple[str, ...] = ()
    receipts = (fixture.receipt,)
    paths: tuple[str, ...] = ()
    match mutation:
        case "malformed-json":
            fixture.receipt.write_text("{", encoding="utf-8")
        case "boolean-version":
            fixture.receipt.write_text(json.dumps({"version": True, "targets": [fixture.target]}), encoding="utf-8")
        case "stale-source":
            (tmp_path / "deploy.yaml").write_text("changed source\n", encoding="utf-8")
        case "wrong-source":
            fixture.target["source"] = "component.tsx"
            _write_receipt(fixture)
        case "case-identity":
            fixture.target["id"] = "Example"
            _write_receipt(fixture)
        case "undeclared-target":
            targets = ("other",)
        case "duplicate-target":
            targets = ("example", "example")
        case "duplicate-receipt":
            receipts = (fixture.receipt, fixture.receipt)
        case _:
            paths = ("deploy.yaml",)
    document = _paired_analysis(fixture, capsys, paths=paths, receipts=receipts, targets=targets, prepared_only=True)
    assert document["exitCode"] == 2
    assert document["completion"] == "failed"
    assert document["conclusion"] == "inconclusive"
    assert document["diagnostics"] == []
    issues = tuple(as_table(item) for item in list_field(document, "issues"))
    assert len(issues) == 1
    assert issues[0]["kind"] == "invalid-input"


@pytest.mark.parametrize("selection", ["declared-default", "all-explicit", "selected-subset"])
def test_prepared_target_selection_never_claims_missing_target_complete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], selection: str
) -> None:
    fixture = _prepared_fixture(tmp_path)
    (tmp_path / "other.yaml").write_bytes((tmp_path / "deploy.yaml").read_bytes())
    (tmp_path / ".sarj-standards.toml").write_text(
        Manifest(
            adopted_version(),
            (),
            ".",
            ".",
            prepared_targets=(PreparedTarget("example", "deploy.yaml"), PreparedTarget("other", "other.yaml")),
        ).render(),
        encoding="utf-8",
    )
    targets = (
        ("example",) if selection == "selected-subset" else ("example", "other") if selection == "all-explicit" else ()
    )
    document = _paired_analysis(fixture, capsys, receipts=(fixture.receipt,), targets=targets, prepared_only=True)
    tools = tuple(as_table(item) for item in list_field(document, "tools"))
    assert not any(tool["name"] == "prepared-devops:other" and tool["completion"] == "complete" for tool in tools)
    if selection == "selected-subset":
        assert document["exitCode"] == 0
        assert len(tools) == 1
        assert tools[0]["name"] == "prepared-devops:example"
        assert tools[0]["completion"] == "complete"
    else:
        assert document["exitCode"] == 2
        assert document["completion"] == "failed"
        issues = tuple(as_table(item) for item in list_field(document, "issues"))
        assert len(issues) == 1
        assert issues[0]["kind"] == "invalid-input"
        assert issues[0]["message"] == "missing prepared targets: other"
