from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import JsonValue, RootModel
import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting import external
from sarj_standards.libs.linting.process import ProcessCapabilities, ProcessRequest, RequestExecutor, ToolResolution
from tests.process_fakes import FakeProcessExecutor


if TYPE_CHECKING:
    from collections.abc import Sequence


class Request(RootModel[dict[str, JsonValue]]):
    pass


@pytest.mark.parametrize("staged", [False, True])
def test_native_adapter_uses_selected_source_paths(tmp_path: Path, staged: bool) -> None:
    app = tmp_path / "app"
    app.mkdir()
    requests: list[dict[str, JsonValue]] = []

    def run(request: ProcessRequest) -> external.ProcessOutput:
        assert request.cwd == tmp_path
        assert request.argv[:2] == (
            "node",
            str(Path(external.__file__).resolve().parents[2] / "configs/react-doctor-runner.mjs"),
        )
        assert request.input_bytes is not None
        requests.append(Request.model_validate_json(request.input_bytes).root)
        return external.ProcessOutput(0, '{"complete":true,"diagnostics":[]}', "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- Inspect the actual execution boundary.
        tmp_path,
        projects=(app,),
        root=tmp_path,
        runner=RequestExecutor(run, ProcessCapabilities(ToolResolution.PROVIDED)),
        file_count=1,
        staged=staged,
        paths=("app/view.tsx",),
    )
    assert report.completion is Completion.COMPLETE
    assert requests[0]["paths"] == [str(app / "view.tsx")]
    assert requests[0]["fullScan"] is False


def test_metadata_selection_expands_native_source_scope(tmp_path: Path) -> None:
    requests: list[dict[str, JsonValue]] = []

    def run(request: ProcessRequest) -> external.ProcessOutput:
        assert request.cwd == tmp_path
        assert request.input_bytes is not None
        requests.append(Request.model_validate_json(request.input_bytes).root)
        return external.ProcessOutput(0, '{"complete":true,"diagnostics":[]}', "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- Verify metadata routes through full source selection.
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=RequestExecutor(run, ProcessCapabilities(ToolResolution.PROVIDED)),
        file_count=1,
        staged=False,
        paths=("package.json",),
    )
    assert report.completion is Completion.COMPLETE
    assert requests[0]["fullScan"] is False
    assert requests[0]["metadataPaths"] == [str(tmp_path / "package.json")]


@pytest.mark.parametrize("output", ["", "{}", '{"complete":false,"diagnostics":[]}', "invalid JSON"])
def test_adapter_cannot_report_clean_without_completion(tmp_path: Path, output: str) -> None:
    def run(argv: Sequence[str], *, cwd: Path) -> external.ProcessOutput:
        assert argv[0] == "node"
        assert cwd == tmp_path
        return external.ProcessOutput(0, output, "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- Verify malformed tool output stays failed.
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=FakeProcessExecutor(run),
        file_count=1,
        staged=False,
    )
    assert report.completion is Completion.FAILED
    assert report.issues


def test_adapter_preserves_native_warning_severity(tmp_path: Path) -> None:
    source = tmp_path / "view.tsx"
    source.write_text("export const View = () => <div />;\n")
    payload = json.dumps(
        {
            "complete": True,
            "diagnostics": [
                {
                    "plugin": "react-doctor",
                    "rule": "example",
                    "filePath": str(source),
                    "severity": "warning",
                    "message": "Explicit warning",
                    "line": 1,
                    "column": 1,
                }
            ],
        }
    )
    diagnostic = external.parse_react_doctor(payload, root=tmp_path)[0]
    assert diagnostic.severity.value == "warning"
    assert diagnostic.rule_id == "react-doctor/example"


def test_native_adapter_uses_yarns_virtual_dependency_loader(tmp_path: Path) -> None:
    (tmp_path / ".pnp.cjs").write_text("// PnP installation marker\n")
    requests: list[ProcessRequest] = []

    def run(request: ProcessRequest) -> external.ProcessOutput:
        requests.append(request)
        return external.ProcessOutput(0, '{"complete":true,"diagnostics":[]}', "")

    report = external._invoke_react_doctor(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- Inspect the package-manager execution boundary.
        tmp_path,
        projects=(tmp_path,),
        root=tmp_path,
        runner=RequestExecutor(run, ProcessCapabilities(ToolResolution.PROVIDED)),
        file_count=1,
        staged=False,
    )
    assert report.completion is Completion.COMPLETE
    assert requests[0].argv[:2] == ("yarn", "node")
    assert requests[0].input_bytes is not None
