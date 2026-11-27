from pathlib import Path

import pytest
from sarj_rule_contracts import RuleId
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_dynamic_builtins import NoDynamicBuiltins


def _lines(source: str) -> list[int]:
    return [finding.line for finding in NoDynamicBuiltins().check(Path("service/reader.py"), source)]


def _hasattr_lines(source: str, path: str = "service/agent.py") -> list[int]:
    return [
        finding.line
        for finding in NoDynamicBuiltins().check(Path(path), source)
        if finding.message
        == "hasattr hides whether this attribute can be missing. Narrow the type with isinstance, a Protocol, "
        "or a typed wrapper instead."
    ]


def test_documented_examples() -> None:
    verify_native_rule(NoDynamicBuiltins, analyze)


@pytest.mark.parametrize("name", ["locals", "globals", "compile", "__import__", "delattr", "getattr"])
def test_rejects_bare_builtin_calls_and_references(name: str) -> None:
    assert _lines(f"{name}(value)\ncallback = {name}\n") == [1, 2]


@pytest.mark.parametrize("name", ["exec", "breakpoint"])
def test_rejects_executor_and_debugger_reference_escape(name: str) -> None:
    assert _lines(f"callback = {name}\ncallback(value)\n") == [1]


@pytest.mark.parametrize(
    "name",
    ["eval", "exec", "breakpoint", "locals", "globals", "compile", "__import__", "getattr", "setattr", "delattr"],
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
        "setattr(value, field, replacement)\n",
        "update = setattr\nupdate(value, 'name', replacement)\n",
        "result = setattr(value, 'name', replacement)\n",
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
        "setattr(value, 'name', replacement)\n",
        "exec(payload)\n",
        "breakpoint()\n",
        "eval(payload)\n",
        "callback = eval\n",
        "import builtins as native\nnative.getattr(value, name)\n",
        "import builtins as native\nnative.setattr(value, field, replacement)\n",
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
        "def writer(setattr):\n    return setattr(value, name, replacement)\n",
        "object.__setattr__(value, 'name', replacement)\n",
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
        (RuleId("no-dynamic-builtins"), "SARJ557", "value = hasattr(settings, 'name')"),
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


def test_reports_each_hasattr_call() -> None:
    source = "def ready(buffer):\n    return hasattr(buffer, 'rate') and hasattr(buffer, 'samples')\n"
    assert _hasattr_lines(source) == [2, 2]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("import os\n\nPG = hasattr(os, 'killpg')\n", id="stdlib-module-probe"),
        pytest.param(
            "import logging\n\nif not hasattr(logging.Logger, 'trace'):\n    pass\n", id="module-attribute-chain"
        ),
        pytest.param(
            "import torch.nn.functional as F\n\nOK = hasattr(F, 'scaled_dot_product_attention')\n", id="aliased-module"
        ),
        pytest.param("def is_dc(cls):\n    return hasattr(cls, '__dataclass_fields__')\n", id="dunder-protocol-probe"),
    ],
)
def test_rejects_runtime_feature_detection(source: str) -> None:
    assert len(_hasattr_lines(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("def hasattr(value, name):\n    return True\n\nhasattr(object(), 'x')\n", id="shadowed-builtin"),
        pytest.param("from compat import hasattr\n\nhasattr(object(), 'x')\n", id="imported-name"),
        pytest.param("value = getattr(settings, 'model', None)\n", id="getattr"),
        pytest.param("checker.hasattr(value, 'x')\n", id="method-named-hasattr"),
        pytest.param("hasattr(\n", id="syntax-error"),
    ],
)
def test_allows_non_builtin_or_other_calls(source: str) -> None:
    assert _hasattr_lines(source) == []


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("tests/test_agent.py", id="test-module"),
        pytest.param("service/conftest.py", id="conftest"),
        pytest.param("tests/fakes/fake_agent.py", id="test-support"),
    ],
)
def test_enforces_test_code(path: str) -> None:
    assert _hasattr_lines("hasattr(value, 'x')\n", path=path) == [1]


@pytest.mark.parametrize(
    "source",
    [
        "callback = hasattr\ncallback(value, name)\n",
        "import builtins as native\nnamespace = native\nnamespace.hasattr(value, name)\n",
        "def checker(hasattr):\n    return hasattr(value, name)\nhasattr(value, name)\n",
    ],
)
def test_rejects_reference_escapes_without_cross_scope_shadowing(source: str) -> None:
    assert len(_hasattr_lines(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "hasattr(value, '__call__')\n",
        "hasattr(*values, '__call__')\n",
        "import builtins\nbuiltins.hasattr(value, name)\n",
        "from builtins import hasattr as probe\nprobe(value, name)\n",
    ],
)
def test_preserves_native_ruff_ownership(source: str) -> None:
    assert _hasattr_lines(source) == []


def test_hasattr_keeps_its_message_under_the_surviving_error_code() -> None:
    findings = NoDynamicBuiltins().check(
        Path("service/agent.py"), "ready = hasattr(buffer, 'rate')\nvalue = getattr(buffer, name)\n"
    )
    assert len(findings) == 2
    assert [finding.line for finding in findings] == [1, 2]
    assert findings[0].code == "SARJ557"
    assert findings[0].severity is Severity.ERROR
    assert findings[0].message == (
        "hasattr hides whether this attribute can be missing. Narrow the type with isinstance, a Protocol, "
        "or a typed wrapper instead."
    )
    assert findings[1].message == (
        "Do not use the builtin getattr. Use explicit typed state, normal imports, or declared attribute access; "
        "a required runtime boundary needs an explained local suppression."
    )


def test_generated_hasattr_probes_remain_allowed() -> None:
    assert _hasattr_lines("# @generated\nhasattr(value, 'x')\n") == []
