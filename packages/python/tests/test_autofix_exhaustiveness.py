from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys
from typing import TypeIs

import pytest
from sarj_rule_contracts import fix_file

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.json_boundary import is_object_mapping, parse_json
from sarj_python_lint.rules import REGISTRY


_RULE = "prefer-match-assert-never"
_IGNORE = "# type: ignore[arg-type]"
_SOURCE = (
    "from enum import StrEnum\nfrom typing import assert_never\n"
    "class Status(StrEnum):\n    READY = 'ready'\n    DONE = 'done'\n"
    "def label(status: Status) -> str:\n"
    "    if status is Status.READY:\n        return 'Ready'\n"
    "    if status is Status.DONE:\n        return 'Done'\n"
    f"    assert_never(status)  {_IGNORE}\n"
)


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize("ignore", [_IGNORE, "# pyright: ignore[reportArgumentType]"])
def test_already_exhaustive_dispatch_removes_only_its_argument_ignore(ending: str, ignore: str) -> None:
    source = _SOURCE.replace(_IGNORE, ignore).replace("\n", ending)
    expected = source.replace(ignore, "")
    path = Path("app/dispatch.py")
    assert len(REGISTRY[_RULE]().check(path, source)) == 1
    assert fix_source(path, source, rule_ids=[_RULE]) == expected
    assert not REGISTRY[_RULE]().check(path, expected)
    assert fix_source(path, expected, rule_ids=[_RULE]) == expected
    assert fix_source(path, source, rule_ids=[]) == source
    assert ast.dump(ast.parse(source), include_attributes=True) == ast.dump(
        ast.parse(expected), include_attributes=True
    )
    assert source.splitlines()[0:-1] == expected.splitlines()[0:-1]
    assert compile(source, str(path), "exec", dont_inherit=True) == compile(
        expected, str(path), "exec", dont_inherit=True
    )


@pytest.mark.parametrize(
    "source",
    [
        _SOURCE.replace("    DONE = 'done'", "    DONE = 'ready'"),
        _SOURCE.replace("    DONE = 'done'", "    DONE = 'done'\n    OTHER = 'other'"),
        _SOURCE.replace("Status.DONE:", "Status.READY:"),
        _SOURCE.replace("if status is Status.DONE:", "if True and status is Status.DONE:"),
        _SOURCE.replace("        return 'Done'", "        pass"),
        _SOURCE.replace("        return 'Done'", "        return compute_label()"),
        _SOURCE.replace("def label(status: Status)", "def label(status: Status = Status.READY)"),
        _SOURCE.replace("status: Status", "status: 'Status'"),
        _SOURCE.replace("def label(", "@decorate\ndef label("),
        _SOURCE.replace("class Status(", "@decorate\nclass Status("),
        _SOURCE.replace("class Status(StrEnum)", "class Status(StrEnum, Other)"),
        _SOURCE.replace("def label(", "def label[T]("),
        _SOURCE.replace("    if status is Status.READY:", "    status = Status.READY\n    if status is Status.READY:"),
        _SOURCE.replace("Status.DONE", "Status.ready").replace("    DONE = 'done'", "    ready = 'done'"),
        _SOURCE.replace("    DONE = 'done'", "    DONE = auto()"),
        _SOURCE.replace("    DONE = 'done'", "    DONE: str = 'done'"),
        _SOURCE.replace("from enum import StrEnum", "from other import StrEnum"),
        _SOURCE.replace("StrEnum", "Enum"),
        _SOURCE + "Status = Other\n",
        _SOURCE + "Status.READY = 'other'\n",
        _SOURCE + "setattr(Status, 'OTHER', 'other')\n",
        _SOURCE.replace("from typing import assert_never", "from other import assert_never"),
        _SOURCE + "assert_never = other\n",
        _SOURCE.replace("assert_never(status)", "assert_never(status, extra=True)"),
        _SOURCE.replace("assert_never(status)", "assert_never(*(status,))"),
        _SOURCE.replace(_IGNORE, "# type: ignore"),
        _SOURCE.replace(_IGNORE, "# type: ignore[arg-type, call-arg]"),
        _SOURCE.replace(_IGNORE, "# type: ignore[arg-type]  # reviewed exception"),
        _SOURCE.replace(_IGNORE, "# type: ignore[arg-type] -- reviewed exception"),
        _SOURCE.replace(_IGNORE, "# pyright: ignore[reportArgumentType, reportCallIssue]"),
        _SOURCE.replace("assert_never(status)", "assert_never(\n        status\n    )"),
        _SOURCE.replace("    assert_never(status)", "    return assert_never(status)"),
        _SOURCE.replace(_IGNORE, _IGNORE + " # sarj-noqa: SARJ032 -- compatibility contract retained"),
    ],
)
def test_unproven_exhaustiveness_or_broader_suppression_stays_manual(source: str) -> None:
    assert fix_source(Path("app/dispatch.py"), source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize(
    "source",
    [
        _SOURCE.replace("    if status is Status.DONE:", "    elif status is Status.DONE:"),
        _SOURCE.replace("assert_never", "不可达").replace(
            "from typing import 不可达", "from typing import assert_never as 不可达"
        ),
        _SOURCE.replace("from enum import StrEnum", "import enum").replace(
            "class Status(StrEnum)", "class Status(enum.StrEnum)"
        ),
        _SOURCE.replace("from typing import assert_never", "import typing").replace(
            "    assert_never(", "    typing.assert_never("
        ),
    ],
)
def test_existing_import_aliases_and_complete_elif_chains_are_preserved(source: str) -> None:
    assert len(REGISTRY[_RULE]().check(Path("app/dispatch.py"), source)) == 1
    expected = source.replace(_IGNORE, "")
    assert fix_source(Path("app/dispatch.py"), source, rule_ids=[_RULE]) == expected
    assert ast.dump(ast.parse(source)) == ast.dump(ast.parse(expected))


def test_exhaustive_ignore_removal_preserves_each_runtime_result_and_failure(tmp_path: Path) -> None:
    fixed = fix_source(Path("app/dispatch.py"), _SOURCE, rule_ids=[_RULE])
    assert fixed != _SOURCE
    oracle = (
        "assert label(Status.READY) == 'Ready'\nassert label(Status.DONE) == 'Done'\n"
        "try:\n    label('other')\nexcept AssertionError as error:\n    print(type(error).__name__, str(error))\n"
        "else:\n    raise AssertionError('runtime assertion disappeared')\n"
    )
    outputs: list[str] = []
    for name, source in (("before.py", _SOURCE), ("after.py", fixed)):
        script = tmp_path / name
        script.write_text(source + oracle, encoding="utf-8")
        completed = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=False)
        assert completed.returncode == 0, completed.stderr
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1]


def test_exhaustive_ignore_file_fix_preserves_bom_and_line_endings(tmp_path: Path) -> None:
    source = _SOURCE.replace("\n", "\r\n")
    path = tmp_path / "dispatch.py"
    path.write_bytes(source.encode("utf-8-sig"))
    assert fix_file(path, lambda text: fix_source(path, text, rule_ids=[_RULE]))
    assert path.read_bytes() == source.replace(_IGNORE, "").encode("utf-8-sig")
    assert not fix_file(path, lambda text: fix_source(path, text, rule_ids=[_RULE]))


def test_exhaustive_ignore_removal_typechecks_without_new_errors(tmp_path: Path) -> None:
    fixed = fix_source(Path("app/dispatch.py"), _SOURCE, rule_ids=[_RULE])
    assert fixed != _SOURCE
    (tmp_path / "before.py").write_text(_SOURCE, encoding="utf-8")
    (tmp_path / "after.py").write_text(fixed, encoding="utf-8")
    config = tmp_path / "pyrightconfig.json"
    config.write_text(
        json.dumps({"typeCheckingMode": "strict", "pythonVersion": "3.15", "include": ["before.py", "after.py"]}),
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["basedpyright", "--project", str(config), "--outputjson"], capture_output=True, text=True, check=False
    )
    assert completed.returncode in {0, 1}, completed.stdout + completed.stderr
    report = parse_json(completed.stdout)
    assert is_object_mapping(report)
    diagnostics = report["generalDiagnostics"]
    assert _is_object_list(diagnostics)
    for item in diagnostics:
        assert is_object_mapping(item)
        filename = item["file"]
        assert isinstance(filename, str)
        assert Path(filename).name == "before.py", completed.stdout + completed.stderr
        assert item.get("rule") == "reportUnnecessaryTypeIgnoreComment", completed.stdout + completed.stderr


def _is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)
