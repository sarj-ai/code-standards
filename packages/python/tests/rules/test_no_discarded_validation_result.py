from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rules.no_discarded_validation_result import NoDiscardedValidationResult


_VALIDATOR = "def checked_count(raw: str) -> int:\n    if not raw:\n        raise ValueError('empty count')\n    return int(raw)\n"
_CLASS_CELL_VALIDATOR = "def __class__(invalid: bool = True) -> int:\n    if invalid:\n        raise ValueError('global helper must not run')\n    return 1\n"
_CASES = (
    EvaluationCase(
        "discarded-replacement", Language.PYTHON, _VALIDATOR + "checked_count('2')\n", ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "validation-before-write",
        Language.PYTHON,
        _VALIDATOR + "def save(raw):\n    checked_count(raw)\n    persist(raw)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested-scope",
        Language.PYTHON,
        "def save(raw):\n"
        + "\n".join("    " + line for line in _VALIDATOR.splitlines())
        + "\n    checked_count(raw)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "async-result",
        Language.PYTHON,
        _VALIDATOR.replace("def checked_count", "async def checked_count")
        + "async def save(raw):\n    await checked_count(raw)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "quoted-annotation",
        Language.PYTHON,
        _VALIDATOR.replace("-> int", "-> 'int'") + "checked_count('2')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "stable-local-callable-alias",
        Language.PYTHON,
        _VALIDATOR + "convert = checked_count\nconvert('2')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "captured-local-callable-alias",
        Language.PYTHON,
        _VALIDATOR + "def save(raw):\n    convert = checked_count\n    convert(raw)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "bounded-callable-alias-chain",
        Language.PYTHON,
        _VALIDATOR + "convert = checked_count\nvalidate = convert\nvalidate('2')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "rebound-callable-alias",
        Language.PYTHON,
        _VALIDATOR + "convert = checked_count\nconvert = command\nconvert('2')\n",
    ),
    EvaluationCase(
        "aliased-command-keeps-its-void-contract",
        Language.PYTHON,
        "def require_count(raw: str) -> None:\n    if not raw:\n        raise ValueError('empty count')\nconvert = require_count\nconvert('2')\n",
    ),
    EvaluationCase(
        "cyclic-callable-aliases",
        Language.PYTHON,
        "convert = validate\nvalidate = convert\nconvert('2')\n",
    ),
    EvaluationCase(
        "conditional-callable-alias-is-uncertain",
        Language.PYTHON,
        _VALIDATOR + "if enabled:\n    convert = checked_count\nconvert('2')\n",
    ),
    EvaluationCase(
        "global-write-invalidates-a-callable-alias",
        Language.PYTHON,
        _VALIDATOR
        + "convert = checked_count\ndef reset():\n    global convert\n    convert = command\nreset()\nconvert('2')\n",
    ),
    EvaluationCase("assigned-result", Language.PYTHON, _VALIDATOR + "count = checked_count('2')\n"),
    EvaluationCase("returned-result", Language.PYTHON, _VALIDATOR + "def save(raw):\n    return checked_count(raw)\n"),
    EvaluationCase("passed-result", Language.PYTHON, _VALIDATOR + "persist(checked_count('2'))\n"),
    EvaluationCase("branch-condition", Language.PYTHON, _VALIDATOR + "if checked_count('2'):\n    persist()\n"),
    EvaluationCase(
        "explicit-command",
        Language.PYTHON,
        "def require_count(raw: str) -> None:\n    if not raw:\n        raise ValueError('empty count')\nrequire_count('2')\n",
    ),
    EvaluationCase("unknown-contract", Language.PYTHON, _VALIDATOR.replace(" -> int", "") + "checked_count('2')\n"),
    EvaluationCase(
        "optional-result", Language.PYTHON, _VALIDATOR.replace("-> int", "-> int | None") + "checked_count('2')\n"
    ),
    EvaluationCase("never-result", Language.PYTHON, _VALIDATOR.replace("-> int", "-> Never") + "checked_count('2')\n"),
    EvaluationCase("any-result", Language.PYTHON, _VALIDATOR.replace("-> int", "-> Any") + "checked_count('2')\n"),
    EvaluationCase("decorated-contract", Language.PYTHON, "@external_contract\n" + _VALIDATOR + "checked_count('2')\n"),
    EvaluationCase(
        "shadowed-parameter", Language.PYTHON, _VALIDATOR + "def save(checked_count):\n    checked_count('2')\n"
    ),
    EvaluationCase("rebound-function", Language.PYTHON, _VALIDATOR + "checked_count = command\nchecked_count('2')\n"),
    EvaluationCase("unresolved-call", Language.PYTHON, "from external import checked_count\nchecked_count('2')\n"),
    EvaluationCase("unknown-method", Language.PYTHON, "def save(parser):\n    parser.checked_count('2')\n"),
    EvaluationCase(
        "class-namespace-is-not-a-method-closure",
        Language.PYTHON,
        "def checked_count(raw: str) -> None:\n    pass\nclass Parser:\n"
        + "\n".join("    " + line for line in _VALIDATOR.splitlines())
        + "\n    def save(self):\n        checked_count('2')\n",
    ),
    EvaluationCase(
        "module-helper-is-not-hidden-by-a-class-member",
        Language.PYTHON,
        _VALIDATOR
        + "class Parser:\n    def checked_count(self, raw: str) -> None:\n        pass\n    def save(self, raw: str) -> None:\n        checked_count(raw)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "captured-helper-is-not-hidden-by-a-class-member",
        Language.PYTHON,
        "def factory(raw):\n"
        + "\n".join("    " + line for line in _VALIDATOR.splitlines())
        + "\n    class Parser:\n        checked_count = None\n        def save(self):\n            checked_count(raw)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-body-keeps-its-own-namespace",
        Language.PYTHON,
        _VALIDATOR + "class Parser:\n    def checked_count(raw: str) -> None:\n        pass\n    checked_count('')\n",
    ),
    EvaluationCase(
        "eager-class-lookup-can-fall-back-before-a-local-write",
        Language.PYTHON,
        "import pytest\n"
        + _VALIDATOR
        + "class TestCounts:\n    with pytest.raises(ValueError):\n        checked_count('')\n    pytest = None\n",
    ),
    EvaluationCase(
        "prepared-class-namespace-controls-the-callee",
        Language.PYTHON,
        _VALIDATOR
        + "def require_count(raw: str) -> None:\n    pass\nclass Meta(type):\n    @classmethod\n    def __prepare__(cls, name, bases):\n        return {'checked_count': require_count}\nclass Parser(metaclass=Meta):\n    checked_count('')\n",
    ),
    EvaluationCase(
        "global-directive-selects-the-module-helper",
        Language.PYTHON,
        _VALIDATOR
        + "def factory():\n    def checked_count(raw: str) -> None:\n        pass\n    def save(raw):\n        global checked_count\n        checked_count(raw)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "global-command-is-not-a-captured-converter",
        Language.PYTHON,
        "def checked_count(raw: str) -> None:\n    pass\ndef factory():\n"
        + "\n".join("    " + line for line in _VALIDATOR.splitlines())
        + "\n    def save(raw):\n        global checked_count\n        checked_count(raw)\n",
    ),
    EvaluationCase(
        "readonly-nonlocal-helper",
        Language.PYTHON,
        "def factory():\n"
        + "\n".join("    " + line for line in _VALIDATOR.splitlines())
        + "\n    def save(raw):\n        nonlocal checked_count\n        checked_count(raw)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nonlocal-write-invalidates-the-helper",
        Language.PYTHON,
        "def factory():\n"
        + "\n".join("    " + line for line in _VALIDATOR.splitlines())
        + "\n    def require_count(raw: str) -> None:\n        pass\n    def save(raw):\n        nonlocal checked_count\n        checked_count = require_count\n        checked_count(raw)\n",
    ),
    EvaluationCase(
        "global-write-invalidates-the-helper",
        Language.PYTHON,
        _VALIDATOR
        + "def require_count(raw: str) -> None:\n    pass\ndef reset():\n    global checked_count\n    checked_count = require_count\nreset()\nchecked_count('')\n",
    ),
    EvaluationCase(
        "compiler-class-cell-is-not-the-global-function",
        Language.PYTHON,
        _CLASS_CELL_VALIDATOR + "class Parser:\n    def save(self):\n        __class__()\nParser().save()\n",
    ),
    EvaluationCase(
        "ordinary-global-function-named-class-cell",
        Language.PYTHON,
        _CLASS_CELL_VALIDATOR + "__class__(False)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "implicit-class-cell-is-not-an-enclosing-helper",
        Language.PYTHON,
        "def factory():\n"
        + "\n".join("    " + line for line in _CLASS_CELL_VALIDATOR.splitlines())
        + "\n    class Parser:\n        def save(self):\n            __class__()\n    return Parser\nfactory()().save()\n",
    ),
    EvaluationCase(
        "ordinary-enclosing-function-named-class-cell",
        Language.PYTHON,
        "def factory():\n"
        + "\n".join("    " + line for line in _CLASS_CELL_VALIDATOR.splitlines())
        + "\n    def save():\n        __class__(False)\n    return save\nfactory()()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "decorated-caller-keeps-its-function-scope",
        Language.PYTHON,
        "from functools import cache\n" + _VALIDATOR + "@cache\ndef save(raw: str) -> None:\n    checked_count(raw)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "invalid-global-declaration-order",
        Language.PYTHON,
        _VALIDATOR + "def save(raw):\n    checked_count(raw)\n    global checked_count\n",
    ),
    EvaluationCase(
        "plain-conversion",
        Language.PYTHON,
        "def checked_count(raw: str) -> int:\n    return int(raw)\nchecked_count('2')\n",
    ),
    EvaluationCase(
        "explicit-write-contract",
        Language.PYTHON,
        _VALIDATOR.replace("    return int(raw)", "    persist(raw)\n    return int(raw)") + "checked_count('2')\n",
    ),
    EvaluationCase(
        "shared-mutation",
        Language.PYTHON,
        _VALIDATOR.replace("    return int(raw)", "    state.value = raw\n    return int(raw)")
        + "checked_count('2')\n",
    ),
    EvaluationCase(
        "generator-contract",
        Language.PYTHON,
        _VALIDATOR.replace("    return int(raw)", "    yield int(raw)") + "checked_count('2')\n",
    ),
    EvaluationCase(
        "nested-return-is-not-owner-return",
        Language.PYTHON,
        "def checked_count(raw: str) -> int:\n    def nested():\n        raise ValueError('nested')\n        return 1\nchecked_count('2')\n",
    ),
    EvaluationCase(
        "unawaited-coroutine",
        Language.PYTHON,
        _VALIDATOR.replace("def checked_count", "async def checked_count") + "checked_count('2')\n",
    ),
    EvaluationCase(
        "exception-assertion",
        Language.PYTHON,
        "import pytest as testing\n"
        + _VALIDATOR
        + "def test_empty():\n    with testing.raises(ValueError):\n        checked_count('')\n",
    ),
    EvaluationCase(
        "unittest-owned-assertion-method",
        Language.PYTHON,
        "import unittest\n"
        + _VALIDATOR
        + "class TestCounts(unittest.TestCase):\n    def test_empty(self):\n        with self.assertRaises(ValueError):\n            checked_count('')\n",
    ),
    EvaluationCase(
        "unittest-constructed-assertion-receiver",
        Language.PYTHON,
        "from unittest import TestCase\n"
        + _VALIDATOR
        + "with TestCase().assertRaisesRegex(ValueError, 'empty'):\n    checked_count('')\n",
    ),
    EvaluationCase(
        "unittest-bound-assertion-receiver",
        Language.PYTHON,
        "from unittest import TestCase\n"
        + _VALIDATOR
        + "case = TestCase()\nwith case.assertRaises(ValueError):\n    checked_count('')\n",
    ),
    EvaluationCase(
        "unknown-assertion-receiver-keeps-the-converter-diagnostic",
        Language.PYTHON,
        _VALIDATOR + "def save(case):\n    with case.assertRaises(ValueError):\n        checked_count('2')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overridden-unittest-assertion-is-not-assumed",
        Language.PYTHON,
        "from unittest import TestCase\n"
        + _VALIDATOR
        + "class Writer(TestCase):\n    assertRaises = command\n    def save(self):\n        with self.assertRaises(ValueError):\n            checked_count('2')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unittest-instance-assertion-write-is-not-assumed",
        Language.PYTHON,
        "from unittest import TestCase\n"
        + _VALIDATOR
        + "case = TestCase()\ncase.assertRaises = command\nwith case.assertRaises(ValueError):\n    checked_count('2')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unittest-setup-assertion-write-is-not-assumed",
        Language.PYTHON,
        "from unittest import TestCase\n"
        + _VALIDATOR
        + "class Writer(TestCase):\n    def setUp(self):\n        self.assertRaises = command\n    def save(self):\n        with self.assertRaises(ValueError):\n            checked_count('2')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unittest-class-assertion-write-is-not-assumed",
        Language.PYTHON,
        "from unittest import TestCase\n"
        + _VALIDATOR
        + "class Writer(TestCase):\n    def save(self):\n        with self.assertRaises(ValueError):\n            checked_count('2')\nWriter.assertRaises = command\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-unittest-instance-field-keeps-the-assertion",
        Language.PYTHON,
        "from unittest import TestCase\n"
        + _VALIDATOR
        + "case = TestCase()\ncase.flag = True\nwith case.assertRaises(ValueError):\n    checked_count('')\n",
    ),
    EvaluationCase(
        "method-exception-owner-skips-class-namespace",
        Language.PYTHON,
        "import pytest\n"
        + _VALIDATOR
        + "class TestCounts:\n    pytest = None\n    def test_empty(self):\n        with pytest.raises(ValueError):\n            checked_count('')\n",
    ),
    EvaluationCase(
        "local-exception-owner-is-resolved",
        Language.PYTHON,
        _VALIDATOR
        + "def test_empty():\n    from pytest import raises as expect\n    with expect(ValueError):\n        checked_count('')\n",
    ),
    EvaluationCase(
        "replaced-exception-owner-is-not-an-assertion",
        Language.PYTHON,
        "import pytest\n"
        + _VALIDATOR
        + "pytest.raises = command\nwith pytest.raises(ValueError):\n    checked_count('2')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "exception-assertion-encloses-class-body",
        Language.PYTHON,
        "import pytest\n"
        + _VALIDATOR
        + "with pytest.raises(ValueError):\n    class Invalid:\n        checked_count('')\n",
    ),
    EvaluationCase(
        "exception-assertion-does-not-enclose-deferred-method-body",
        Language.PYTHON,
        "import pytest\n"
        + _VALIDATOR
        + "with pytest.raises(ValueError):\n    class Parser:\n        def save(self):\n            checked_count('2')\n    raise ValueError('configuration')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "shadowed-exception-helper",
        Language.PYTHON,
        "import pytest\n"
        + _VALIDATOR
        + "def save(pytest):\n    with pytest.raises(ValueError):\n        checked_count('2')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "dynamic-namespace", Language.PYTHON, _VALIDATOR + "globals()['checked_count'] = command\nchecked_count('2')\n"
    ),
    EvaluationCase("malformed-source", Language.PYTHON, "def checked_count(:\n"),
)


@pytest.mark.parametrize("case", _CASES, ids=[case.case_id for case in _CASES])
def test_labeled_validation_cases(case: EvaluationCase) -> None:
    findings = NoDiscardedValidationResult().check(Path("app/counts.py"), case.source)
    assert len(findings) == int(case.expected is ExpectedOutcome.MATCH)


def test_documented_examples() -> None:
    verify_native_rule(NoDiscardedValidationResult, analyze)


@pytest.mark.parametrize(
    "imports",
    ["from counts import checked_count", "from counts import checked_count as validate", "import counts as values"],
)
def test_imported_validator_result_is_observed_without_importing_application_code(tmp_path: Path, imports: str) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    (tmp_path / "counts.py").write_text("raise RuntimeError('do not execute application modules')\n" + _VALIDATOR)
    call = (
        "validate"
        if " as validate" in imports
        else "values.checked_count"
        if "import counts" in imports
        else "checked_count"
    )
    target = tmp_path / "store.py"
    target.write_text(f"{imports}\ndef save(raw):\n    {call}(raw)\n    persist(raw)\n")
    [finding] = analyze([NoDiscardedValidationResult.id], [target])
    assert (finding.code, finding.line, finding.col, finding.severity.value) == ("SARJ519", 3, 5, "error")


def test_reexported_validator_and_relative_import(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("from .counts import checked_count\n")
    (package / "counts.py").write_text(_VALIDATOR)
    target = package / "store.py"
    target.write_text("from . import checked_count\nchecked_count('2')\n")
    assert len(analyze([NoDiscardedValidationResult.id], [target])) == 1


@pytest.mark.parametrize(
    "caller",
    [
        "import counts as values\nclass Parser:\n    values = None\n    def save(self):\n        values.checked_count('2')\n",
        "def save():\n    from counts import checked_count\n    checked_count('2')\n",
    ],
    ids=["method-global-import", "function-local-import"],
)
def test_runtime_import_binding_selects_the_provider(tmp_path: Path, caller: str) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    (tmp_path / "counts.py").write_text(_VALIDATOR)
    target = tmp_path / "store.py"
    target.write_text(caller)
    assert len(analyze([NoDiscardedValidationResult.id], [target])) == 1


@pytest.mark.parametrize(
    "replacement",
    [
        "checked_count = command\n",
        "from external import checked_count\n",
        "def checked_count(raw) -> None:\n    pass\n",
        "def reset():\n    global checked_count\n    checked_count = command\nreset()\n",
    ],
)
def test_rebound_imported_contract_is_not_guessed(tmp_path: Path, replacement: str) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    (tmp_path / "counts.py").write_text(_VALIDATOR + replacement)
    target = tmp_path / "store.py"
    target.write_text("from counts import checked_count\nchecked_count('2')\n")
    assert analyze([NoDiscardedValidationResult.id], [target]) == []


def test_reexport_reassignment_is_not_a_stable_contract(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    (tmp_path / "counts.py").write_text(_VALIDATOR)
    (tmp_path / "exports.py").write_text(
        "from counts import checked_count\n"
        "def require_count(raw: str) -> None:\n    pass\n"
        "def reset():\n    global checked_count\n    checked_count = require_count\n"
        "reset()\n"
    )
    target = tmp_path / "store.py"
    target.write_text("from exports import checked_count\nchecked_count('2')\n")
    assert analyze([NoDiscardedValidationResult.id], [target]) == []


@pytest.mark.parametrize(
    ("imports", "operation", "expected"),
    [
        ("import counts as first\nimport counts as second\n", "second.checked_count = require_count\n", 0),
        ("import counts as first\nimport counts as second\n", "configure(second)\n", 0),
        ("import counts as first\nimport other as second\n", "second.checked_count = require_count\n", 1),
    ],
    ids=["same-provider-write", "same-provider-escape", "unrelated-provider-write"],
)
def test_module_aliases_share_provider_identity(tmp_path: Path, imports: str, operation: str, expected: int) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    (tmp_path / "counts.py").write_text(_VALIDATOR)
    (tmp_path / "other.py").write_text(_VALIDATOR)
    target = tmp_path / "store.py"
    target.write_text(
        imports
        + "def require_count(raw: str) -> None:\n    pass\n"
        + "def configure(namespace):\n    namespace.checked_count = require_count\n"
        + operation
        + "first.checked_count('2')\n"
    )
    assert len(analyze([NoDiscardedValidationResult.id], [target])) == expected


def test_relative_and_absolute_aliases_share_provider_identity(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "counts.py").write_text(_VALIDATOR)
    target = package / "store.py"
    target.write_text(
        "from . import counts as first\nimport app.counts as second\n"
        "def require_count(raw: str) -> None:\n    pass\n"
        "second.checked_count = require_count\nfirst.checked_count('2')\n"
    )
    assert analyze([NoDiscardedValidationResult.id], [target]) == []


def test_self_module_alias_can_replace_a_local_definition(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    target = tmp_path / "store.py"
    target.write_text(
        _VALIDATOR
        + "import store as module\n"
        + "def require_count(raw: str) -> None:\n    pass\n"
        + "module.checked_count = require_count\nchecked_count('2')\n"
    )
    assert analyze([NoDiscardedValidationResult.id], [target]) == []


def test_reexport_provider_namespace_write_is_not_ignored(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    (tmp_path / "counts.py").write_text(_VALIDATOR)
    (tmp_path / "exports.py").write_text(
        "import counts as namespace\n"
        "def require_count(raw: str) -> None:\n    pass\n"
        "namespace.checked_count = require_count\nfrom counts import checked_count\n"
    )
    target = tmp_path / "store.py"
    target.write_text("from exports import checked_count\nchecked_count('2')\n")
    assert analyze([NoDiscardedValidationResult.id], [target]) == []


def test_exact_suppression_and_generated_sources() -> None:
    rule = NoDiscardedValidationResult()
    source = _VALIDATOR + "checked_count('2')  # sarj-noqa: SARJ519 — exercise the exception-only compatibility API\n"
    assert rule.check(Path("app/counts.py"), source) == []
    assert rule.check(Path("generated/counts.py"), _CASES[0].source) == []


@pytest.mark.parametrize(
    ("case_id", "expected_exit"),
    [("discarded-replacement", 1), ("passed-result", 0), ("explicit-command", 0)],
)
def test_blocking_cli_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case_id: str, expected_exit: int
) -> None:
    target = tmp_path / "counts.py"
    target.write_text(next(case.source for case in _CASES if case.case_id == case_id))
    assert main(["check", "--rule", NoDiscardedValidationResult.id, str(target)]) == expected_exit
    output = capsys.readouterr().out
    assert ("SARJ519" in output) == bool(expected_exit)
    assert "warning:" not in output


@pytest.mark.parametrize(
    ("imports", "patching"),
    [
        (
            "from unittest.mock import patch\n",
            "with patch('counts.checked_count', return_value=None):\n    counts.checked_count('2')\n",
        ),
        (
            "from unittest import mock\n",
            "@mock.patch('counts.checked_count', return_value=None)\ndef test_command(replacement):\n    counts.checked_count('2')\n",
        ),
        (
            "from unittest.mock import patch as replace\n",
            "with replace.multiple('counts', checked_count=command):\n    counts.checked_count('2')\n",
        ),
        (
            "from unittest.mock import patch\n",
            "with patch.dict('sys.modules', counts=replacement):\n    counts.checked_count('2')\n",
        ),
    ],
    ids=["patch-context", "patch-decorator", "patch-multiple", "patch-module-table"],
)
def test_mock_patch_invalidates_static_provider_contract(tmp_path: Path, imports: str, patching: str) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    (tmp_path / "counts.py").write_text(_VALIDATOR)
    target = tmp_path / "store.py"
    target.write_text(f"import counts\n{imports}{patching}")
    assert analyze([NoDiscardedValidationResult.id], [target]) == []


def test_a_local_patch_name_does_not_disable_validator_checks(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    (tmp_path / "counts.py").write_text(_VALIDATOR)
    target = tmp_path / "store.py"
    target.write_text("import counts\ndef patch(raw):\n    return raw\npatch('unrelated')\ncounts.checked_count('2')\n")
    assert len(analyze([NoDiscardedValidationResult.id], [target])) == 1


def test_provider_mock_patching_invalidates_reexport_contract(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    (tmp_path / "counts.py").write_text(
        f"from unittest.mock import patch\n{_VALIDATOR}patch('counts.checked_count', return_value=None).start()\n"
    )
    (tmp_path / "public.py").write_text("from counts import checked_count\n")
    target = tmp_path / "store.py"
    target.write_text("from public import checked_count\nchecked_count('2')\n")
    assert analyze([NoDiscardedValidationResult.id], [target]) == []


@pytest.mark.parametrize(
    ("declarations", "annotation"),
    [
        ("type NoValue = None\n", "NoValue"),
        ("from typing import TypeAlias\nNoValue: TypeAlias = None\n", "NoValue"),
        ("from typing import Optional as Maybe\n", "Maybe[int]"),
        ("from typing import Any as Payload\n", "Payload"),
        ("", "object"),
    ],
    ids=["pep695-none-alias", "pep613-none-alias", "optional-import-alias", "any-import-alias", "object-contract"],
)
def test_return_contract_can_include_none(declarations: str, annotation: str) -> None:
    source = (
        f"{declarations}def record(raw: str) -> None:\n    pass\n"
        f"def require(raw: str) -> {annotation}:\n"
        "    if not raw:\n        raise ValueError('empty')\n"
        "    return record(raw)\nrequire('2')\n"
    )
    assert NoDiscardedValidationResult().check(Path("app/counts.py"), source) == []


@pytest.mark.parametrize(
    ("declarations", "annotation", "result"),
    [
        ("", "list[int | None]", "[int(raw), None]"),
        ("from typing import Any\n", "list[Any]", "[int(raw)]"),
        ("from typing import Annotated\n", "Annotated[int, None]", "int(raw)"),
        ("type Checked = int\n", "Checked", "int(raw)"),
        ("class Optional:\n    pass\n", "Optional", "Optional()"),
    ],
    ids=[
        "nullable-container-elements",
        "opaque-container-elements",
        "annotation-metadata",
        "value-alias",
        "local-optional-class",
    ],
)
def test_non_none_return_value_is_distinct_from_nested_annotation_metadata(
    declarations: str, annotation: str, result: str
) -> None:
    source = (
        f"{declarations}def checked(raw: str) -> {annotation}:\n"
        "    if not raw:\n        raise ValueError('empty')\n"
        f"    return {result}\nchecked('2')\n"
    )
    assert len(NoDiscardedValidationResult().check(Path("app/counts.py"), source)) == 1


def test_imported_none_return_alias_is_resolved_from_source(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="sample"\nversion="0.0.0"\n')
    (tmp_path / "contracts.py").write_text("type NoValue = None\n")
    target = tmp_path / "store.py"
    target.write_text(
        "from contracts import NoValue\ndef record(raw: str) -> None:\n    pass\n"
        "def require(raw: str) -> NoValue:\n    if not raw:\n        raise ValueError('empty')\n"
        "    return record(raw)\nrequire('2')\n"
    )
    assert analyze([NoDiscardedValidationResult.id], [target]) == []


@pytest.mark.parametrize(
    ("declarations", "annotation"),
    [
        ("type Checked[T] = T\n", "Checked[int]"),
        ("type First = Second\ntype Second = First\n", "First"),
        ("from typing import Protocol\nclass Result(Protocol):\n    pass\n", "Result"),
        ("from typing import Annotated, Optional\n", "Annotated[Optional[int], 'checked']"),
        ("from typing import Union\n", "Union[int, None]"),
    ],
    ids=["generic-alias", "cyclic-alias", "empty-protocol", "annotated-nullable", "union-nullable"],
)
def test_opaque_and_nullable_annotation_boundaries(declarations: str, annotation: str) -> None:
    source = declarations + _VALIDATOR.replace("-> int", f"-> {annotation}") + "checked_count('2')\n"
    assert NoDiscardedValidationResult().check(Path("app/counts.py"), source) == []


def test_return_annotation_uses_definition_scope_instead_of_function_locals() -> None:
    source = _VALIDATOR.replace("checked_count(raw: str)", "checked_count(raw: str, int=command)")
    source += "checked_count('2')\n"
    assert len(NoDiscardedValidationResult().check(Path("app/counts.py"), source)) == 1


def test_return_annotation_type_parameter_shadows_builtin() -> None:
    source = _VALIDATOR.replace("def checked_count(", "def checked_count[int](") + "checked_count('2')\n"
    assert NoDiscardedValidationResult().check(Path("app/counts.py"), source) == []


def test_nested_definition_uses_enclosing_type_alias() -> None:
    source = (
        "def save(raw):\n    type Checked = int\n"
        "    def checked_count(raw: str) -> Checked:\n"
        "        if not raw:\n            raise ValueError('empty')\n"
        "        return int(raw)\n    checked_count(raw)\n"
    )
    assert len(NoDiscardedValidationResult().check(Path("app/counts.py"), source)) == 1
