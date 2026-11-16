from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import ExampleFinding, verify_examples

from sarj_iac_lint.rules.no_unused_module_outputs import NoUnusedModuleOutputs


if TYPE_CHECKING:
    from pathlib import Path


def test_documented_examples() -> None:
    spec = NoUnusedModuleOutputs.native_spec()
    assert spec is not None

    def analyze(root: Path, _focus: Path) -> list[ExampleFinding]:
        sources = {
            PurePosixPath(path.relative_to(root).as_posix()): path.read_text(encoding="utf-8")
            for path in root.rglob("*.tf")
        }
        return [
            ExampleFinding(d.path, d.line, d.col, d.code, d.message)
            for d in NoUnusedModuleOutputs.check_project(root, sources)
        ]

    assert verify_examples(spec.examples, analyze, expected_code="SARJ223") == 2


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("crlf", [False, True])
def test_required_diagnostic_cannot_be_suppressed_or_baselined(tmp_path: Path, *, selected: bool, crlf: bool) -> None:
    code = NoUnusedModuleOutputs.code if selected else "SARJ999"
    source = f'# sarj-noqa: {code} — migration\noutput "unused" {{ value = true }}\n'
    source = source.replace("\n", "\r\n") if crlf else source
    findings = NoUnusedModuleOutputs.check_project(
        tmp_path,
        {
            PurePosixPath("main.tf"): 'module "child" { source = "./child" }\n',
            PurePosixPath("child/outputs.tf"): source,
        },
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.code == "SARJ223"
    assert finding.line == 2
    assert not finding.suppressible
    assert not finding.baselineable
    assert finding.severity.value == "error"
    assert "external_outputs" in finding.message


def test_exact_external_contract_is_retained_and_stale_contract_fails(tmp_path: Path) -> None:
    sources = {
        PurePosixPath("main.tf"): 'module "child" { source = "./child" }',
        PurePosixPath("child/outputs.tf"): 'output "external" { value = true }',
    }
    assert NoUnusedModuleOutputs.check_project(tmp_path, sources, external_outputs=(("child", "external"),)) == []
    with pytest.raises(ValueError, match="does not name an existing output"):
        NoUnusedModuleOutputs.check_project(tmp_path, sources, external_outputs=(("child", "missing"),))


def test_file_local_api_cannot_prove_non_use(tmp_path: Path) -> None:
    assert NoUnusedModuleOutputs().check(tmp_path / "outputs.tf", 'output "contract" { value = true }') == []
