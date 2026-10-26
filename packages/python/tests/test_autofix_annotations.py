from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


_RULE = "no-any-mapping-types"
_PREFIX = (
    "from collections.abc import Mapping\nfrom typing import Any\ndef identity(value: Any) -> Any:\n    return value\n"
)
_BEFORE = (
    _PREFIX
    + "def outer() -> int:\n    def _accept(payload: Mapping[str, Any]) -> int:\n        return 1\n    return _accept({'key': 1})\n"
)
_AFTER = _BEFORE.replace("Mapping[str, Any]", "Mapping[str, object]")


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_private_opaque_mapping_preserves_exact_output_and_converges(ending: str) -> None:
    path = Path("app/service.py")
    before = _BEFORE.replace("\n", ending)
    after = _AFTER.replace("\n", ending)
    assert len(REGISTRY[_RULE]().check(path, before)) == 1
    assert fix_source(path, before, rule_ids=[_RULE]) == after
    assert not REGISTRY[_RULE]().check(path, after)
    assert fix_source(path, after, rule_ids=[_RULE]) == after
    assert fix_source(path, before, rule_ids=[]) == before
    compile(after, str(path), "exec", dont_inherit=True)


@pytest.mark.parametrize(
    "source",
    [
        _BEFORE.replace("Mapping[str, Any]", "dict[str, Any]"),
        _BEFORE.replace("from collections.abc import Mapping", "from collections.abc import MutableMapping as Mapping"),
        _BEFORE.replace("Mapping[str, Any]", "Mapping[str, list[Any]]"),
        _BEFORE.replace("Mapping[str, Any]", "'Mapping[str, Any]'"),
        _BEFORE.replace("        return 1", "        return len(payload)"),
        _BEFORE.replace("        return 1", "        payload = {}\n        return 1"),
        _BEFORE.replace(
            "        return 1", "        def observe() -> object:\n            return payload\n        return 1"
        ),
        _BEFORE.replace("payload: Mapping[str, Any]", "payload: Mapping[str, Any] = {}"),
        _BEFORE.replace("def outer()", "def outer[T]()"),
        _BEFORE.replace("    return _accept({'key': 1})", "    return _accept"),
        _BEFORE.replace("    return _accept({'key': 1})", "    return _accept(*({'key': 1},))"),
        _BEFORE.replace("    return _accept({'key': 1})", "    return _accept({'key': 1}, payload={})"),
        _BEFORE.replace("        return 1", "        # preserve the signature explanation\n        return 1"),
        "object = str\n" + _BEFORE,
        "import builtins\n" + _BEFORE,
        "import sys\n"
        + _BEFORE.replace(
            "    return _accept({'key': 1})", "    sys.setprofile(identity)\n    return _accept({'key': 1})"
        ),
        _BEFORE.replace("    return _accept({'key': 1})", "    locals()\n    return _accept({'key': 1})"),
        _BEFORE.replace("def identity(value: Any) -> Any:\n    return value\n", ""),
        _PREFIX + "def accept(payload: Mapping[str, Any]) -> int:\n    return 1\naccept({'key': 1})\n",
        _PREFIX + "class Service:\n    def _accept(self, payload: Mapping[str, Any]) -> int:\n        return 1\n",
    ],
)
def test_unproven_mapping_contracts_remain_manual(source: str) -> None:
    assert fix_source(Path("app/service.py"), source, rule_ids=[_RULE]) == source


def test_private_mapping_retains_namespace_aliases_and_unicode_offsets() -> None:
    source = (
        "from collections.abc import Mapping as Records\nimport typing as types\n"
        "def identity(value: types.Any) -> types.Any:\n    return value\n"
        "def outer() -> int:\n    def _accept(数据: Records[str, types.Any]) -> int:\n"
        "        return 1\n    return _accept({'key': 1})\n"
    )
    fixed = fix_source(Path("app/service.py"), source, rule_ids=[_RULE])
    assert fixed == source.replace("Records[str, types.Any]", "Records[str, object]")
    compile(fixed, "app/service.py", "exec", dont_inherit=True)


def test_unreferenced_private_mapping_still_has_no_contract_consumers() -> None:
    source = _BEFORE.replace("    return _accept({'key': 1})", "    return 1")
    assert fix_source(Path("app/service.py"), source, rule_ids=[_RULE]) == source.replace(
        "Mapping[str, Any]", "Mapping[str, object]"
    )


def test_private_mapping_preserves_runtime_body_and_values(tmp_path: Path) -> None:
    fixed = fix_source(Path("app/service.py"), _BEFORE, rule_ids=[_RULE])
    before_ast = ast.parse(_BEFORE)
    after_ast = ast.parse(fixed)
    before_returns = [ast.dump(node) for node in ast.walk(before_ast) if isinstance(node, ast.Return)]
    after_returns = [ast.dump(node) for node in ast.walk(after_ast) if isinstance(node, ast.Return)]
    assert before_returns == after_returns
    for index, source in enumerate((_BEFORE, fixed)):
        path = tmp_path / f"runtime_{index}.py"
        path.write_text(source + "\nassert outer() == 1\nassert identity('opaque') == 'opaque'\n", encoding="utf-8")
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


def test_covariant_mapping_callers_typecheck_before_and_after(tmp_path: Path) -> None:
    source = _PREFIX.replace("from typing import Any", "from typing import Any, TypedDict") + (
        "class Row(TypedDict):\n    key: int\n"
        "def outer() -> tuple[int, int, int]:\n"
        "    def _accept(payload: Mapping[str, Any]) -> int:\n        return 1\n"
        "    numeric: Mapping[str, int] = {'key': 1}\n"
        "    record: Row = {'key': 2}\n"
        "    opaque: Mapping[str, object] = {'key': None}\n"
        "    return _accept(numeric), _accept(record), _accept(opaque)\n"
    )
    fixed = fix_source(Path("app/service.py"), source, rule_ids=[_RULE])
    assert fixed == source.replace("Mapping[str, Any]", "Mapping[str, object]")
    (tmp_path / "before.py").write_text(source, encoding="utf-8")
    (tmp_path / "after.py").write_text(fixed, encoding="utf-8")
    config = tmp_path / "pyrightconfig.json"
    config.write_text(
        json.dumps({"typeCheckingMode": "strict", "pythonVersion": "3.15", "include": ["before.py", "after.py"]}),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["basedpyright", "--project", str(config), "--outputjson"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
