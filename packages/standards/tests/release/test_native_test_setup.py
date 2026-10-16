from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.linting.devops_tools import MISE_REFS, TOOLS
from sarj_standards.libs.release import native_test_setup


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("failing_tool", ["mise", "uvx"])
def test_integration_installer_failure_preserves_consumer_optouts_and_stops_before_path_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_tool: str
) -> None:
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: Test\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo fixture\n"
    )
    adopted = manifest.Manifest(version=manifest.adopted_version(), configs=(), python_dest=".", typescript_dest=".")
    configuration = tmp_path / manifest.MANIFEST_NAME
    configuration.write_text(adopted.render())
    original = configuration.read_bytes()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for tool in ("mise", "uvx"):
        executable = binaries / tool
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            f"Path({str(tmp_path / (tool + '.json'))!r}).write_text(json.dumps(sys.argv[1:]))\n"
            f"sys.exit({7 if tool == failing_tool else 0})\n"
        )
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries))
    output = tmp_path / "github-path"
    monkeypatch.setenv("GITHUB_PATH", str(output))
    assert native_test_setup.setup(tmp_path) == 7
    command: object = json.loads((tmp_path / "mise.json").read_text())  # pyright: ignore[reportAny] -- JSON command recording boundary.
    required = ("actionlint", "helm", "knip", "kube-linter", "kubeconform", "shellcheck", "shfmt")
    assert command == [
        "--no-config",
        "--no-env",
        "--no-hooks",
        "install",
        *(f"{MISE_REFS[name]}@{TOOLS[name].version}" for name in required),
    ]
    security_install = tmp_path / "uvx.json"
    if failing_tool == "uvx":
        security_command: object = json.loads(security_install.read_text())  # pyright: ignore[reportAny] -- JSON command recording boundary.
        assert security_command == [
            "--no-config",
            "--isolated",
            "--python",
            "3.12",
            "--from",
            "zizmor==1.31.1",
            "zizmor",
            "--version",
        ]
    else:
        assert not security_install.exists()
    assert configuration.read_bytes() == original
    assert not output.exists()
