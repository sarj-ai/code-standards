from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption.manifest import Manifest
from sarj_standards.libs.diagnostics import Completion, TrustMode, baseline
from sarj_standards.libs.linting.external import analyze_external


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("config_name", ["pyproject.toml", "ruff.toml", ".ruff.toml"])
def test_adopted_project_and_root_helper_keep_their_relative_ruff_policy(tmp_path: Path, config_name: str) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    (tmp_path / ".sarj-standards.toml").write_text(
        Manifest(version="1.2.3", configs=("ruff",), python_dest="backend", typescript_dest=".").render(),
        encoding="utf-8",
    )
    prefix = "tool.ruff." if config_name == "pyproject.toml" else ""
    header = "[tool.ruff]\n" if prefix else ""
    (backend / config_name).write_text(
        header
        + "preview = true\n"
        + f"[{prefix}lint]\n"
        + 'select = ["unused-async", "undefined-name", "typing-only-standard-library-import"]\n'
        + f"[{prefix}lint.per-file-ignores]\n"
        + '"tests/**" = ["unused-async"]\n'
        + '"app/**" = ["typing-only-standard-library-import"]\n'
        + '"tools/**" = ["unused-async"]\n',
        encoding="utf-8",
    )
    sources = {
        "backend/tests/test_client.py": "async def contract() -> None:\n    return None\n",
        "backend/app/model.py": (
            "from __future__ import annotations\nfrom datetime import date\n\ndef render(value: date) -> str:\n    return str(value)\n"
        ),
        "backend/broken.py": "missing_name\n",
        "backend/worker.py": "async def worker() -> None:\n    return None\n",
        "tools/helper.py": "async def contract() -> None:\n    return None\n",
    }
    paths: list[str] = []
    for relative, source in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        paths.append(str(path))

    reports = analyze_external(paths, root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"ruff"}))

    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert sorted((finding.location.path, finding.code) for report in reports for finding in report.diagnostics) == [
        ("backend/broken.py", "F821"),
        ("backend/worker.py", "RUF029"),
    ]


@pytest.mark.parametrize("relative", ["backend/app.py", "tools/helper.py"])
def test_adopted_project_routing_keeps_required_source_policy(tmp_path: Path, relative: str) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    (tmp_path / ".sarj-standards.toml").write_text(
        Manifest(version="1.2.3", configs=("ruff",), python_dest="backend", typescript_dest=".").render(),
        encoding="utf-8",
    )
    (backend / "pyproject.toml").write_text("[tool.ruff.lint]\nselect = []\n", encoding="utf-8")
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("from typing import cast\nvalue = cast(int, 1)\n", encoding="utf-8")

    reports = analyze_external([str(path)], root=tmp_path, trust=TrustMode.SAFE, capabilities=frozenset({"ruff"}))

    assert len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE
    assert len(reports[0].diagnostics) == 1
    finding = reports[0].diagnostics[0]
    assert finding.code == "TID251"
    assert finding.location.path == relative
    assert not baseline.is_baselineable(finding)
