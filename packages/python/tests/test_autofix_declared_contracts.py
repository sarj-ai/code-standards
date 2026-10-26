from __future__ import annotations

import ast
from importlib import import_module
import json
from pathlib import Path
import subprocess
from types import FunctionType, ModuleType
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import RuleId, apply_edits

from sarj_python_lint._autofix_declared_contracts import DeclaredContractFixes
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from collections.abc import Mapping


_PATH = Path("app/contracts.py")
_PRECISE = (
    "def ready() -> bool:\n"
    "    def _value() -> object:\n"
    "        return 'ready'\n"
    "    if _value():\n"
    "        return True\n"
    "    return False\n"
)
_IMPORT = (
    "import importlib\n"
    "from importlib import import_module as load\n"
    "from types import ModuleType\n"
    "def load_module() -> ModuleType:\n"
    "    if type(importlib) is ModuleType and importlib.__dict__['import_module'] is load:\n"
    "        return importlib.import_module('math')\n"
    "    return load('math')\n"
)
_RULES = ("prefer-precise-object-contract", "prefer-direct-import-module")


def _fixed(source: str, rule_id: RuleId) -> str:
    context = PythonFileContext(_PATH, source)
    fixer = DeclaredContractFixes(context)
    return apply_edits(
        source, [edit for finding in REGISTRY[rule_id]().check_context(context) for edit in fixer.fixes(finding)]
    )


def _function(source: str, name: str, namespace: Mapping[str, object] | None = None) -> FunctionType:
    parsed = ast.parse(source)
    declaration = next(item for item in parsed.body if isinstance(item, ast.FunctionDef) and item.name == name)
    scope = {} if namespace is None else dict(namespace)
    exec(  # ruff: ignore[exec-builtin] -- trusted fixture declarations require real Python lazy annotation behavior.
        compile(ast.Module(body=[declaration], type_ignores=[]), str(_PATH), "exec", dont_inherit=True), scope
    )
    function = scope[name]
    assert isinstance(function, FunctionType)
    return function


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
def test_declared_contract_autofix_exact_native_output_and_convergence(newline: str) -> None:
    source = _PRECISE.replace("\n", newline)
    expected = source.replace("-> object:", "-> str:")
    rule_id = _RULES[0]
    assert len(REGISTRY[rule_id]().check(_PATH, source)) == 1
    assert _fixed(source, RuleId(rule_id)) == expected
    assert not REGISTRY[rule_id]().check(_PATH, expected)
    assert _fixed(expected, RuleId(rule_id)) == expected
    assert fix_source(_PATH, source, rule_ids=[rule_id]) == expected
    assert fix_source(_PATH, source, rule_ids=[]) == source
    compile(expected, str(_PATH), "exec", dont_inherit=True)


@pytest.mark.parametrize("lookup", ["importlib.__dict__['import_module']", "importlib.import_module"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
def test_guarded_import_helpers_are_outside_static_import_scope(lookup: str, newline: str) -> None:
    source = ("# Unicode 😀\n" + _IMPORT.replace("importlib.__dict__['import_module']", lookup)).replace("\n", newline)
    rule_id = _RULES[1]
    assert not REGISTRY[rule_id]().check(_PATH, source)
    assert _fixed(source, RuleId(rule_id)) == source
    assert fix_source(_PATH, source, rule_ids=[rule_id]) == source
    assert fix_source(_PATH, source, rule_ids=[]) == source


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("if _value():", "result = _value()\n    if result:"),
        ("if _value():", "if bool(_value()):"),
        ("if _value():", "if _value() is not None:"),
        ("-> bool:", ":"),
        ("return 'ready'", "return callback()"),
        ("def _value()", "def _value[str]()"),
        ("def ready()", "def ready[object]()"),
        ("def ready()", "def ready[str]()"),
        ("    if _value():", "    alias = _value\n    if _value():"),
        ("    if _value():", "    observe()\n    if _value():"),
    ],
)
def test_precise_return_requires_closed_truthiness_only_uses(before: str, after: str) -> None:
    source = _PRECISE.replace(before, after)
    assert _fixed(source, RuleId(_RULES[0])) == source


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("type(importlib) is ModuleType and ", ""),
        (" is load:", " == load:"),
        (" is ModuleType", " is OtherModule"),
        ("from types import ModuleType", "from custom import ModuleType"),
        ("return importlib.import_module('math')", "return importlib.import_module(module_name)"),
        ("return importlib.import_module('math')", "return importlib.import_module(callback())"),
        ("return importlib.import_module('math')", "return importlib.import_module('math', package=None)"),
        ("def load_module()", "def load_module(importlib)"),
        ("def load_module()", "def load_module[load]()"),
        ("def load_module()", "@decorate\ndef load_module()"),
        ("    return load('math')", "    return other('math')"),
        ("    return load('math')", "    return load('json')"),
        ("import importlib\n", "import importlib\nimportlib.import_module = other\n"),
        ("from types import ModuleType\n", "from types import ModuleType\nobserve()\n"),
    ],
)
def test_function_scoped_import_variants_are_not_static_module_findings(before: str, after: str) -> None:
    source = _IMPORT.replace(before, after)
    assert not REGISTRY[_RULES[1]]().check(_PATH, source)
    assert _fixed(source, RuleId(_RULES[1])) == source
    assert fix_source(_PATH, source, rule_ids=[_RULES[1]]) == source


def test_declared_contract_fixes_preserve_suppression_unicode_and_selection() -> None:
    rule_id = _RULES[0]
    source = "# Unicode 😀\n" + _PRECISE
    expected = _fixed(source, RuleId(rule_id))
    assert expected != source
    assert fix_source(_PATH, source, rule_ids=[rule_id]) == expected
    code = REGISTRY[rule_id].code
    suppressed = source.replace("-> object:", f"-> object:  # sarj-noqa: {code} -- existing contract")
    assert fix_source(_PATH, suppressed, rule_ids=[rule_id]) == suppressed


def test_precise_return_preserves_runtime_and_existing_public_return_annotation() -> None:
    fixed = _fixed(_PRECISE, RuleId(_RULES[0]))
    assert fixed != _PRECISE
    original, updated = _function(_PRECISE, "ready"), _function(fixed, "ready")
    assert original() is updated() is True
    assert original.__annotations__ == updated.__annotations__


def test_guarded_import_exclusion_preserves_canonical_provider_runtime_and_errors() -> None:
    module = import_module("importlib")
    namespace = {"importlib": module, "load": import_module, "ModuleType": ModuleType}
    for name in ("math", "autofix_missing_module_371582934"):
        source = _IMPORT.replace("'math'", repr(name))
        fixed = _fixed(source, RuleId(_RULES[1]))
        assert fixed == source
        assert not REGISTRY[_RULES[1]]().check(_PATH, source)
        original, updated = _function(source, "load_module", namespace), _function(fixed, "load_module", namespace)
        if name == "math":
            assert original() is updated() is import_module("math")
        else:
            with pytest.raises(ModuleNotFoundError):
                original()
            with pytest.raises(ModuleNotFoundError):
                updated()


def test_guarded_import_exclusion_preserves_false_guard_fallback() -> None:
    provider = ModuleType("private_loader")

    def first(name: str) -> str:
        return f"first:{name}"

    def second(name: str) -> str:
        return f"second:{name}"

    provider.__dict__["import_module"] = second
    namespace = {"importlib": provider, "load": first, "ModuleType": ModuleType}
    fixed = _fixed(_IMPORT, RuleId(_RULES[1]))
    assert fixed == _IMPORT
    assert not REGISTRY[_RULES[1]]().check(_PATH, _IMPORT)
    assert (
        _function(_IMPORT, "load_module", namespace)() == _function(fixed, "load_module", namespace)() == "first:math"
    )


def test_declared_contract_before_and_after_typecheck_without_api_changes(tmp_path: Path) -> None:
    original = tmp_path / "before.py"
    updated = tmp_path / "after.py"
    source = _PRECISE + "\nready_result: bool = ready()\n"
    # Analyze the source-owned private helper before adding its public bool consumer.
    fixed = _fixed(_PRECISE, RuleId(_RULES[0])) + "\nready_result: bool = ready()\n"
    original.write_text(source, encoding="utf-8")
    updated.write_text(fixed, encoding="utf-8")
    root = Path(__file__).resolve().parents[3]
    config = tmp_path / "pyrightconfig.json"
    config.write_text(
        json.dumps(
            {
                "extends": str(root / ".basedpyright-strict.json"),
                "pythonVersion": "3.15",
                "include": [str(original), str(updated)],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "basedpyright",
            "--pythonpath",
            str(root / "packages/standards/.venv/bin/python"),
            "--project",
            str(config),
            "--level",
            "error",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
