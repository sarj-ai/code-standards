from pathlib import Path

import pytest
from sarj_rule_contracts import RuleId
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_dynamic_builtins import NoDynamicBuiltins


def _lines(source: str) -> list[int]:
    return [finding.line for finding in NoDynamicBuiltins().check(Path("service/reader.py"), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoDynamicBuiltins, analyze)


@pytest.mark.parametrize("name", ["locals", "globals", "compile", "__import__", "delattr", "getattr"])
def test_rejects_bare_builtin_calls_and_references(name: str) -> None:
    assert _lines(f"{name}(value)\ncallback = {name}\n") == [1, 2]


@pytest.mark.parametrize("name", ["exec", "breakpoint"])
def test_rejects_executor_and_debugger_reference_escape(name: str) -> None:
    assert _lines(f"callback = {name}\ncallback(value)\n") == [1]


@pytest.mark.parametrize(
    "name", ["eval", "exec", "breakpoint", "locals", "globals", "compile", "__import__", "getattr", "delattr"]
)
def test_rejects_builtins_module_aliases(name: str) -> None:
    assert _lines(f"import builtins as native\nnamespace = native\nnamespace.{name}(value)\n") == [3]


@pytest.mark.parametrize(
    "source",
    [
        "getattr(value, name)\n",
        "getattr(value, 'name', None)\n",
        "getattr(value, '__private')\n",
        "getattr(value, 'not-an-identifier')\n",
        "getattr(value, 'class')\n",
        "getattr(value, 'name', default=None)\n",
        "getattr(*values, 'name')\n",
        "getattr.__call__(value, name)\n",
        "def reader(callback=getattr):\n    return callback\n",
        "from builtins import exec as run\nrun(payload)\n",
        "from builtins import eval as run\n",
    ],
)
def test_rejects_patterns_without_a_native_owner(source: str) -> None:
    assert len(_lines(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "getattr(value, 'name')\n",
        "getattr(value, '__class__')\n",
        "getattr(value, 'ſ')\n",
        "exec(payload)\n",
        "breakpoint()\n",
        "eval(payload)\n",
        "callback = eval\n",
        "import builtins as native\nnative.getattr(value, name)\n",
        "from builtins import getattr as lookup\nlookup(value, name)\n",
        "from builtins import breakpoint as pause\npause()\n",
    ],
)
def test_keeps_native_owners(source: str) -> None:
    assert _lines(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("delattr(value, 'field')\n", id="statement"),
        pytest.param("if active:\n    delattr(value, 'field')\n", id="nested-statement"),
        pytest.param("(delattr(value, 'field'))\n", id="parenthesized-statement"),
        pytest.param("delattr(\n    value,\n    'field',\n)\n", id="multiline-statement"),
        pytest.param("delattr(value, '__class__')\n", id="unmangled-dunder"),
        pytest.param("delattr(value, 'ſ')\n", id="native-normalization-guard"),
        pytest.param("delattr(\n    value,  # retain context\n    'field',\n)\n", id="native-comment-guard"),
    ],
)
def test_constant_attribute_deletion_retains_native_ownership(source: str) -> None:
    assert _lines(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("def read(value):\n    return delattr(value, 'field')\n", id="return-value"),
        pytest.param("result = delattr(value, 'field')\n", id="assigned-result"),
        pytest.param("use(delattr(value, 'field'))\n", id="nested-call"),
        pytest.param("read = lambda value: delattr(value, 'field')\n", id="lambda-value"),
        pytest.param("if delattr(value, 'field'):\n    run()\n", id="condition"),
        pytest.param("async def read(value):\n    await delattr(value, 'field')\n", id="awaited-value"),
        pytest.param("delattr(value, name)\n", id="dynamic-name"),
        pytest.param("delattr(value, 'not-an-identifier')\n", id="invalid-identifier"),
        pytest.param("delattr(value, 'class')\n", id="keyword-name"),
        pytest.param("delattr(value, '__private')\n", id="private-mangling"),
        pytest.param("delattr(value, '__debug__')\n", id="reserved-debug-name"),
        pytest.param("delattr(*values, 'field')\n", id="starred-receiver"),
        pytest.param("delattr(value, name='field')\n", id="keyword-argument"),
        pytest.param("delattr(value, 'field', extra)\n", id="additional-argument"),
        pytest.param("callback = delattr\ncallback(value, 'field')\n", id="escaped-reference"),
    ],
)
def test_nonstatement_attribute_deletion_and_unproven_calls_keep_custom_coverage(source: str) -> None:
    assert len(_lines(source)) == 1


def test_shadowed_attribute_deletion_remains_unrelated_to_the_builtin_policy() -> None:
    source = "def delattr(value, name):\n    return name\ndelattr(value, 'field')\n"
    assert _lines(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "def getattr(value, name):\n    return value\ngetattr(value, name)\n",
        "def reader(getattr):\n    return getattr(value, name)\n",
        "from application import getattr\ngetattr(value, name)\n",
        "class Reader:\n    def getattr(self, name):\n        return name\nReader().getattr(name)\n",
        "read = lambda getattr: getattr(value, name)\n",
        "values = [getattr(value, name) for getattr in readers]\n",
        "def outer():\n    def getattr(value, name):\n        return value\n    def inner():\n        return getattr(value, name)\n    return inner()\n",
        "def reader[getattr](value: getattr):\n    return value\n",
        "type Reader[getattr] = list[getattr]\n",
        "text = 'getattr(value, name); globals()'\n# locals()\n",
        "from application import *\ngetattr(value, name)\n",
        "getattr(\n",
    ],
)
def test_preserves_shadowed_names_strings_and_malformed_source(source: str) -> None:
    assert _lines(source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def reader(getattr):\n    return getattr(value, name)\ngetattr(value, name)\n", [3]),
        (
            "class Reader:\n    def getattr(self, name):\n        return name\n    def read(self, value, name):\n        return getattr(value, name)\n",
            [5],
        ),
        ("values = [value for getattr in getattr(source, name)]\n", [1]),
        ("def reader(getattr=getattr):\n    return getattr\n", [1]),
    ],
)
def test_respects_python_scope_boundaries(source: str, expected: list[int]) -> None:
    assert _lines(source) == expected


def test_defaults_to_error_severity() -> None:
    findings = NoDynamicBuiltins().check(Path("tests/test_reader.py"), "globals()\n")
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert NoDynamicBuiltins.documentation is not None
    assert NoDynamicBuiltins.documentation.default_level is Severity.ERROR


@pytest.mark.parametrize(
    ("rule_id", "code", "source"),
    [
        (RuleId("no-dynamic-builtins"), "SARJ557", "value = locals()"),
        (RuleId("no-hasattr"), "SARJ499", "value = hasattr(settings, 'name')"),
        (RuleId("no-sys-path-mutation"), "SARJ558", "import sys; sys.path.append('/opt/application')"),
        (RuleId("no-shared-mutable-default"), "SARJ559", "def read(values: object = []): return values"),
    ],
)
def test_analyzer_requires_the_matching_local_suppression(
    tmp_path: Path, rule_id: RuleId, code: str, source: str
) -> None:
    path = tmp_path / "service.py"
    (tmp_path / ".git").mkdir()
    path.write_text(source + "\n", encoding="utf-8")
    assert [finding.code for finding in analyze([rule_id], [path], root=tmp_path)] == [code]
    path.write_text(
        source + "  # sarj-noqa: SARJ000 -- A different rule must not suppress this runtime policy.\n",
        encoding="utf-8",
    )
    assert [finding.code for finding in analyze([rule_id], [path], root=tmp_path)] == [code]
    path.write_text(
        source + f"  # sarj-noqa: {code} -- This fixture exercises an explicitly reviewed runtime boundary.\n",
        encoding="utf-8",
    )
    assert analyze([rule_id], [path], root=tmp_path) == []
