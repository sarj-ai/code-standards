from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules.prefer_pydantic_model_assertion import PreferPydanticModelAssertion


_PREFIX = """from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str

"""
_SOURCE = (
    _PREFIX
    + """def test_user() -> None:
    result = User(id=1, name="Alice")
    assert result.id == 1
    assert result.name == "Alice"
"""
)
_ASSERTIONS = '    assert result.id == 1\n    assert result.name == "Alice"\n'
_DUMP = _SOURCE.replace(
    _ASSERTIONS,
    '    assert result.model_dump(include={"id", "name"}) == {"id": 1, "name": "Alice"}\n',
)
_MODEL = _SOURCE.replace(_ASSERTIONS, '    assert result == User(id=1, name="Alice")\n')
_SNAPSHOT = (
    _PREFIX
    + """def test_user() -> None:
    result = User(id=1, name="Alice")
    projection = result.model_dump(include={"id", "name"})
    if type(projection) is dict and projection == {"id": result.id, "name": result.name}:
        assert result.id == 1
        assert result.name == "Alice"
"""
)
_SNAPSHOT_FIXED = _SNAPSHOT.replace(
    '        assert result.id == 1\n        assert result.name == "Alice"\n',
    '        assert projection == {"id": 1, "name": "Alice"}\n',
)
_PLUGIN = """import pytest

@pytest.fixture(autouse=True)
def customize_model(request, monkeypatch):
    model = request.node.module.User
"""
_DUMP_PLUGIN = (
    _PLUGIN
    + """    def dump(self, **kwargs):
        raise RuntimeError("serialization-contract")
    monkeypatch.setattr(model, "model_dump", dump)
"""
)
_VALIDATION_PLUGIN = (
    _PLUGIN
    + """    original = model.__init__
    calls = 0
    def initialize(self, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("validation-contract")
        original(self, **kwargs)
    monkeypatch.setattr(model, "__init__", initialize)
"""
)
_DESCRIPTOR_PLUGIN = (
    _PLUGIN
    + """    def dump(self, **kwargs):
        return {"id": 1, "name": "Alice"}
    monkeypatch.setattr(model, "model_dump", dump)
    original = model.__getattribute__
    reads = 0
    def attribute(self, name):
        nonlocal reads
        if name == "id":
            reads += 1
            if reads > 1:
                raise RuntimeError("descriptor-read-contract")
        return original(self, name)
    monkeypatch.setattr(model, "__getattribute__", attribute)
"""
)


@dataclass(frozen=True, slots=True, kw_only=True)
class _Boundary:
    name: str
    before: str
    rejected_rewrite: str
    plugin: str
    before_exit: int
    after_exit: int
    marker: str


_CASES = (
    _Boundary(
        name="new-serialization-call",
        before=_SOURCE,
        rejected_rewrite=_DUMP,
        plugin=_DUMP_PLUGIN,
        before_exit=0,
        after_exit=1,
        marker="serialization-contract",
    ),
    _Boundary(
        name="extra-model-validation",
        before=_SOURCE,
        rejected_rewrite=_MODEL,
        plugin=_VALIDATION_PLUGIN,
        before_exit=0,
        after_exit=1,
        marker="validation-contract",
    ),
    _Boundary(
        name="reused-projection-does-not-close-descriptor-reads",
        before=_SNAPSHOT,
        rejected_rewrite=_SNAPSHOT_FIXED,
        plugin=_DESCRIPTOR_PLUGIN,
        before_exit=1,
        after_exit=0,
        marker="descriptor-read-contract",
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.name for case in _CASES))
def test_autofix_model_assertion_keeps_each_reported_contract_for_review(case: _Boundary) -> None:
    path = Path("tests/test_user.py")
    assert len(PreferPydanticModelAssertion().check(path, case.before)) == 1
    # The complete authored test source is the oracle: a warning alone cannot
    # authorize adding validation/serialization or removing descriptor reads.
    assert fix_source(path, case.before, rule_ids=["prefer-pydantic-model-assertion"]) == case.before


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.name for case in _CASES))
def test_autofix_model_assertion_rejected_rewrites_change_real_pytest_behavior(tmp_path: Path, case: _Boundary) -> None:
    statuses: list[int] = []
    outputs: list[str] = []
    for name, source in (("before", case.before), ("after", case.rejected_rewrite)):
        project = tmp_path / name
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nname="model-contract-boundary"\nversion="0.0.0"\n')
        (project / "test_user.py").write_text(source)
        (project / "conftest.py").write_text(case.plugin)
        # Exercise the real pinned Pydantic model and ordinary pytest autouse
        # hook; replacing the library with a fake would not prove this boundary.
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "test_user.py"],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        statuses.append(result.returncode)
        outputs.append(result.stdout + result.stderr)
    assert statuses == [case.before_exit, case.after_exit], outputs
    failing_output = outputs[0] if case.before_exit else outputs[1]
    assert case.marker in failing_output
