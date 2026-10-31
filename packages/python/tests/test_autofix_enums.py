from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


_RULE = "prefer-str-enum"
_SOURCE = (
    "from typing import Literal\ntype Mode = Literal['text', 'image', 'reserved']\n"
    "def outer() -> str:\n    def _render(kind: str) -> str:\n"
    "        match kind:\n            case 'text':\n                return 'Text'\n"
    "            case 'image':\n                return 'Image'\n"
    "            case _:\n                raise ValueError('unsupported kind')\n"
    "    return _render('text')\n"
)
_FIXED = _SOURCE.replace("_render(kind: str)", "_render(kind: Mode)")


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_private_dispatch_reuses_existing_literal_alias_with_reachable_fallback(ending: str) -> None:
    source = _SOURCE.replace("\n", ending)
    expected = _FIXED.replace("\n", ending)
    path = Path("app/service.py")
    assert len(REGISTRY[_RULE]().check(path, source)) == 1
    assert fix_source(path, source, rule_ids=[_RULE]) == expected
    assert not REGISTRY[_RULE]().check(path, expected)
    assert fix_source(path, expected, rule_ids=[_RULE]) == expected
    assert fix_source(path, source, rule_ids=[]) == source
    compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
        expected, str(path), "exec", dont_inherit=True
    )


@pytest.mark.parametrize(
    "source",
    [
        _SOURCE.replace("type Mode = Literal['text', 'image', 'reserved']\n", ""),
        _SOURCE.replace("type Mode = Literal['text', 'image', 'reserved']", "type Mode = Literal['text', 'image']"),
        _SOURCE.replace("type Mode = Literal['text', 'image', 'reserved']", "type Mode = Literal['text']"),
        _SOURCE.replace(
            "type Mode = Literal['text', 'image', 'reserved']", "type Mode[T] = Literal['text', 'image', 'reserved']"
        ),
        _SOURCE.replace(
            "type Mode = Literal['text', 'image', 'reserved']",
            "type Mode = Literal['text', 'image', 'reserved']\ntype Other = Literal['text', 'image', 'reserved']",
        ),
        _SOURCE + "Mode = str\n",
        _SOURCE + "escaped = Mode\n",
        _SOURCE.replace("def outer()", "def outer[T]()"),
        _SOURCE.replace("def outer()", "def outer(Mode: str)"),
        _SOURCE.replace("    def _render", "    Mode = str\n    def _render"),
        _SOURCE.replace("kind: str", "kind: str = 'text'"),
        _SOURCE.replace("kind: str", "kind: 'str'"),
        _SOURCE.replace("        match kind:", "        # preserve domain explanation\n        match kind:"),
        _SOURCE.replace(
            "type Mode = Literal['text', 'image', 'reserved']",
            "type Mode = Literal['text', 'image', 'reserved']  # public domain",
        ),
        _SOURCE.replace("                return 'Text'", "                return kind.upper()"),
        _SOURCE.replace("case 'text':", "case 'text' if True:"),
        _SOURCE.replace("    return _render('text')", "    return _render"),
        _SOURCE.replace("    return _render('text')", "    return _render('other')"),
        _SOURCE.replace("    return _render('text')", "    return _render('reserved')"),
        _SOURCE.replace("    return _render('text')", "    value = 'text'\n    return _render(value)"),
        _SOURCE.replace("    return _render('text')", "    return _render(*('text',))"),
        _SOURCE.replace("    return _render('text')", "    return _render('text', kind='image')"),
        "from inspect import stack\n" + _SOURCE,
        _SOURCE.replace("    return _render('text')", "    locals()\n    return _render('text')"),
        _SOURCE.replace("from typing import Literal", "from custom import Literal"),
        "str = object\n" + _SOURCE,
    ],
)
def test_unproven_string_domain_ownership_remains_manual(source: str) -> None:
    assert fix_source(Path("app/service.py"), source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize("annotation", ["str", "ﬆr", "ｓｔｒ"])
def test_native_identifier_spelling_and_existing_alias_are_preserved(annotation: str) -> None:
    source = _SOURCE.replace("Mode", "模式").replace("kind: str", f"kind: {annotation}")
    expected = source.replace(f"kind: {annotation}", "kind: 模式")
    fixed = fix_source(Path("app/service.py"), source, rule_ids=[_RULE])
    assert fixed == expected
    compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
        fixed, "app/service.py", "exec", dont_inherit=True
    )


def test_keyword_calls_and_unreferenced_helpers_keep_the_same_domain() -> None:
    for source in (
        _SOURCE.replace("_render('text')", "_render(kind='image')"),
        _SOURCE.replace("    return _render('text')", "    return 'unused'"),
    ):
        assert fix_source(Path("app/service.py"), source, rule_ids=[_RULE]) == source.replace("kind: str", "kind: Mode")


def test_private_dispatch_preserves_all_runtime_branches_and_rejection(tmp_path: Path) -> None:
    fixed = fix_source(Path("app/service.py"), _SOURCE, rule_ids=[_RULE])
    before_branches = [ast.dump(node) for node in ast.walk(ast.parse(_SOURCE)) if isinstance(node, ast.Match)]
    after_branches = [ast.dump(node) for node in ast.walk(ast.parse(fixed)) if isinstance(node, ast.Match)]
    assert after_branches == before_branches
    for index, source in enumerate((_SOURCE, fixed)):
        for kind, expected in (("text", "Text"), ("image", "Image")):
            path = tmp_path / f"runtime_{index}_{kind}.py"
            candidate = source.replace("_render('text')", f"_render({kind!r})")
            path.write_text(candidate + f"\nassert outer() == {expected!r}\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
            assert result.returncode == 0, result.stderr
        path = tmp_path / f"runtime_{index}_fallback.py"
        candidate = source.replace("_render('text')", "_render('reserved')")
        path.write_text(
            candidate
            + "\ntry:\n    outer()\nexcept ValueError as error:\n    assert str(error) == 'unsupported kind'\nelse:\n    raise AssertionError('fallback changed')\n",
            encoding="utf-8",
        )
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


def test_literal_domain_callers_typecheck_before_and_after(tmp_path: Path) -> None:
    source = _SOURCE.replace("def outer() -> str:", "def outer() -> tuple[str, str]:").replace(
        "    return _render('text')",
        "    return _render('text'), _render(kind='image')",
    )
    fixed = fix_source(Path("app/service.py"), source, rule_ids=[_RULE])
    assert fixed == source.replace("kind: str", "kind: Mode")
    (tmp_path / "before.py").write_text(source, encoding="utf-8")
    (tmp_path / "after.py").write_text(fixed, encoding="utf-8")
    exact = _SOURCE.replace("Literal['text', 'image', 'reserved']", "Literal['text', 'image']")
    assert fix_source(Path("app/service.py"), exact, rule_ids=[_RULE]) == exact
    (tmp_path / "exact_refusal.py").write_text(exact, encoding="utf-8")
    config = tmp_path / "pyrightconfig.json"
    config.write_text(
        json.dumps(
            {
                "typeCheckingMode": "strict",
                "pythonVersion": "3.15",
                "include": ["before.py", "after.py", "exact_refusal.py"],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["basedpyright", "--project", str(config), "--outputjson"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_rejecting_caller_can_export_the_private_annotation_in_its_traceback(tmp_path: Path) -> None:
    source = _SOURCE.replace("_render('text')", "_render('reserved')")
    assert len(REGISTRY[_RULE]().check(Path("app/service.py"), source)) == 1
    assert fix_source(Path("app/service.py"), source, rule_ids=[_RULE]) == source
    oracle = (
        "try:\n    outer()\nexcept ValueError as error:\n"
        "    trace = error.__traceback__\n"
        "    while trace is not None:\n"
        "        if '_render' in trace.tb_frame.f_locals:\n"
        "            assert trace.tb_frame.f_locals['_render'].__annotations__['kind'] is str\n"
        "            break\n"
        "        trace = trace.tb_next\n"
        "    else:\n        raise AssertionError('private frame missing')\n"
    )
    path = tmp_path / "traceback.py"
    path.write_text(source + "\n" + oracle, encoding="utf-8")
    result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
