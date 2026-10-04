from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.no_mocked_pydantic_value_object import NoMockedPydanticValueObject


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


TEST_PATH = Path("tests/test_payload.py")
_MODELS = """
from unittest.mock import AsyncMock, MagicMock, Mock, create_autospec
from pydantic import BaseModel, Field

class Payload(BaseModel):
    attempts: int = Field(ge=1)
    label: str = "label"

    def language(self) -> str:
        return "en"

class ChildPayload(Payload):
    token: str

class Client:
    attempts: int
"""


def _check(source: str, path: Path = TEST_PATH) -> list[Diagnostic]:
    source = textwrap.dedent(_MODELS) + "\n" + textwrap.dedent(source)
    rule = NoMockedPydanticValueObject()
    rule.prepare(ProjectIndexSet.single(path, source))
    return rule.check(path, source)


_EXAMPLES = NoMockedPydanticValueObject.public_examples()


@pytest.mark.parametrize("example", _EXAMPLES, ids=tuple(example.example_id for example in _EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    rule = NoMockedPydanticValueObject()
    rule.prepare(ProjectIndexSet.single(Path(focus.path), focus.source))
    assert len(rule.check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload)\n    payload.attempts = -1\n", id="field-assignment"
        ),
        pytest.param(
            "def test_payload():\n    payload = MagicMock(spec_set=Payload)\n    payload.label = 'label'\n",
            id="spec-set",
        ),
        pytest.param(
            "def test_payload():\n    payload = Mock(Payload)\n    payload.attempts = 2\n", id="positional-spec"
        ),
        pytest.param("def test_payload():\n    payload = Mock(spec=Payload, attempts=2)\n", id="constructor-field"),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=ChildPayload)\n    payload.attempts = 2\n",
            id="inherited-model-field",
        ),
        pytest.param(
            "def test_payload():\n    payload = create_autospec(Payload, instance=True)\n    payload.attempts = 2\n",
            id="autospec-instance",
        ),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload(attempts=2))\n    payload.label = 'label'\n",
            id="concrete-instance-spec",
        ),
        pytest.param(
            "from unittest.mock import Mock as Double\n\ndef test_payload():\n    payload = Double(spec=Payload, attempts=2)\n",
            id="aliased-constructor",
        ),
        pytest.param(
            "import unittest.mock as doubles\n\ndef test_payload():\n    payload = doubles.Mock(spec=Payload, label='label')\n",
            id="aliased-module",
        ),
        pytest.param(
            "def make_payload():\n    payload = Mock(spec=Payload)\n    payload.attempts = 2\n    return payload\n",
            id="support-helper",
        ),
    ],
)
def test_reports_field_only_schema_doubles(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ479"
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("def test_payload():\n    payload = Payload(attempts=2)\n", id="real-model"),
        pytest.param("def test_payload():\n    payload = Mock(spec=Client, attempts=2)\n", id="service-double"),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload)\n    assert pass_through(payload) is payload\n",
            id="identity-placeholder",
        ),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload, wraps=Payload(attempts=2))\n    payload.label = 'label'\n",
            id="wrapped-real-model",
        ),
        pytest.param(
            "def test_payload():\n    factory = create_autospec(Payload)\n    factory.return_value = Payload(attempts=2)\n",
            id="model-class-factory",
        ),
        pytest.param(
            "def test_payload():\n    factory = create_autospec(Payload, instance=False)\n", id="explicit-class-factory"
        ),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload)\n    payload.language.side_effect = ValueError('missing language')\n",
            id="method-fault-injection",
        ),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload)\n    payload.attempts = 2\n    payload.language.return_value = 'ar'\n",
            id="field-plus-method-configuration",
        ),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload)\n    payload.attempts = 2\n    payload.language()\n",
            id="model-method-called",
        ),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload)\n    payload.attempts = 2\n    payload.language.assert_called_once()\n",
            id="model-method-asserted",
        ),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload, **{'language.side_effect': ValueError('failed')})\n",
            id="constructor-method-fault",
        ),
        pytest.param(
            "def test_payload():\n    payload = Mock()\n    payload.attempts = 2\n", id="unspecced-owned-by-sarj040"
        ),
        pytest.param("def test_payload():\n    payload = Mock(spec=unknown, attempts=2)\n", id="unknown-spec"),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload)\n    payload.unknown = 'value'\n",
            id="unproved-field",
        ),
        pytest.param("def test_payload(Mock):\n    payload = Mock(spec=Payload, attempts=2)\n", id="shadowed-mock"),
        pytest.param("def test_payload(Payload):\n    payload = Mock(spec=Payload, attempts=2)\n", id="shadowed-model"),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload)\n    payload = unknown()\n    payload.attempts = 2\n",
            id="rebound-receiver",
        ),
        pytest.param(
            "def test_payload(flag):\n    if flag:\n        payload = Mock(spec=Payload)\n    else:\n        payload = unknown()\n    payload.attempts = 2\n",
            id="ambiguous-control-flow",
        ),
    ],
)
def test_preserves_fault_injection_and_unproved_data_contracts(source: str) -> None:
    assert _check(source) == []


def test_reports_constructor_position_once_for_multiple_fields() -> None:
    source = (
        textwrap.dedent(_MODELS)
        + "\ndef test_payload():\n    payload = Mock(spec=Payload)\n    payload.attempts = 2\n    payload.label = 'label'\n"
    )
    rule = NoMockedPydanticValueObject()
    rule.prepare(ProjectIndexSet.single(TEST_PATH, source))
    [finding] = rule.check(TEST_PATH, source)
    assert (finding.line, finding.col) == (len(source.splitlines()) - 2, 15)


def test_resolves_imported_model_without_importing_its_module(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-package"\nversion = "0.1.0"\n')
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    model_path = package / "models.py"
    model_source = "from pydantic import BaseModel\nraise RuntimeError('must never import')\nclass Payload(BaseModel):\n    attempts: int\n"
    model_path.write_text(model_source)
    tests = tmp_path / "tests"
    tests.mkdir()
    test_path = tests / "test_payload.py"
    test_source = "from unittest.mock import Mock\nfrom app.models import Payload as Data\ndef test_payload():\n    payload = Mock(spec=Data, attempts=2)\n"
    test_path.write_text(test_source)
    rule = NoMockedPydanticValueObject()
    rule.prepare(ProjectIndexSet.build([test_path, model_path], {test_path: test_source, model_path: model_source}))
    [finding] = rule.check(test_path, test_source)
    assert (finding.code, finding.line, finding.col) == ("SARJ479", 4, 15)


@pytest.mark.parametrize(
    "path", [Path("models.py"), Path("tests/generated/test_payload.py")], ids=["production", "generated"]
)
def test_excludes_unmaintained_test_sources(path: Path) -> None:
    assert _check("def test_payload():\n    payload = Mock(spec=Payload, attempts=2)\n", path) == []


def test_malformed_source_is_ignored() -> None:
    assert _check("def test_payload(:\n") == []


def test_exact_suppression_is_respected() -> None:
    assert (
        _check(
            "def test_payload():\n    payload = Mock(spec=Payload, attempts=2)  # sarj-noqa: SARJ479 — invalid field state is the tested contract\n"
        )
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def test_payload():\n    Payload = unknown\n    payload = Mock(spec=Payload, attempts=2)\n",
            id="rebound-model-type",
        ),
        pytest.param(
            "def test_payload(flag):\n    payload = Mock(spec=Payload)\n    if flag:\n        payload = unknown()\n        payload.attempts = 2\n",
            id="branch-field-belongs-to-other-object",
        ),
        pytest.param(
            "def test_payload():\n    payload = Mock(spec=Payload)\n    payload.attempts = 2\n    def inject():\n        payload.language.side_effect = ValueError('missing')\n    inject()\n",
            id="nested-failure-injection",
        ),
        pytest.param(
            "from typing import ClassVar\nclass Options(BaseModel):\n    callback: ClassVar[object] = None\n\ndef test_payload():\n    options = Mock(spec=Options)\n    options.callback = unknown\n",
            id="class-variable-is-not-model-field",
        ),
    ],
)
def test_abstains_for_invalidated_model_data_provenance(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("import_name", ["mock", "mock as doubles"], ids=["module-symbol", "module-symbol-alias"])
def test_resolves_unittest_mock_module_symbol(import_name: str) -> None:
    module = "doubles" if " as " in import_name else "mock"
    source = (
        f"from unittest import {import_name}\n\n"
        f"def test_payload():\n    payload = {module}.Mock(spec=Payload, attempts=2)\n"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("local_binding", "expected_count"),
    [
        pytest.param("from unittest.mock import Mock", 1, id="identical-constructor-import"),
        pytest.param("from unrelated import Mock", 0, id="conflicting-constructor-import"),
        pytest.param("Mock = unknown", 0, id="shadowed-constructor-import"),
    ],
)
def test_local_mock_constructor_bindings_preserve_only_proven_imports(local_binding: str, expected_count: int) -> None:
    source = f"def test_payload():\n    {local_binding}\n    payload = Mock(spec=Payload, attempts=2)\n"
    assert len(_check(source)) == expected_count


@pytest.mark.parametrize(
    "capture",
    [
        pytest.param("try:\n        operation()\n    except Exception as payload:\n        pass", id="exception-name"),
        pytest.param("match candidate:\n        case payload:\n            pass", id="pattern-as-name"),
        pytest.param("match candidate:\n        case [*payload]:\n            pass", id="pattern-star-name"),
        pytest.param(
            "match candidate:\n        case {'detail': detail, **payload}:\n            pass", id="pattern-mapping-rest"
        ),
    ],
)
def test_capture_bindings_invalidate_previous_model_contract(capture: str) -> None:
    source = f"def test_payload():\n    payload = Mock(spec=Payload)\n    {capture}\n    payload.attempts = 2\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    ("constructor", "expected_count"),
    [
        pytest.param(
            "create_autospec(Payload(attempts=2), instance=True, spec_set=True)", 1, id="strict-instance-autospec"
        ),
        pytest.param(
            "create_autospec(spec_set=True, instance=True, spec=Payload(attempts=2))", 1, id="autospec-keyword-order"
        ),
        pytest.param("Mock(spec=Client, spec_set=Payload(attempts=2))", 1, id="spec-set-proves-model"),
        pytest.param("Mock(spec_set=Payload(attempts=2), spec=Client)", 1, id="spec-set-proves-model-first"),
        pytest.param("Mock(spec=Payload, spec_set=Client())", 0, id="spec-set-proves-non-model"),
        pytest.param("Mock(spec_set=Client(), spec=Payload)", 0, id="spec-set-proves-non-model-first"),
        pytest.param("Mock(spec=Payload, spec_set=None)", 1, id="none-does-not-override-spec"),
    ],
)
def test_resolves_effective_mock_model_contract_for_each_factory(constructor: str, expected_count: int) -> None:
    source = f"def test_payload():\n    payload = {constructor}\n    payload.attempts = 2\n"
    assert len(_check(source)) == expected_count


@pytest.mark.parametrize(
    "class_source",
    [
        pytest.param(
            "class ModelMeta(type(BaseModel)):\n    pass\n\nclass DynamicPayload(Payload, metaclass=ModelMeta):\n    pass\n",
            id="custom-model-metaclass",
        ),
        pytest.param("class DynamicPayload(Payload, frozen=True):\n    pass\n", id="configured-class-keyword"),
    ],
)
def test_abstains_for_custom_model_class_creation(class_source: str) -> None:
    source = f"{class_source}\ndef test_payload():\n    payload = Mock(spec=DynamicPayload, attempts=2)\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "import_and_decorator",
    [
        pytest.param("from typing import final\n@final", id="canonical-final"),
        pytest.param("from typing import final as sealed\n@sealed", id="aliased-final"),
    ],
)
def test_final_decorator_preserves_resolved_model_provenance(import_and_decorator: str) -> None:
    source = (
        f"{import_and_decorator}\nclass FinalPayload(Payload):\n    token: str\n\n"
        "def test_payload():\n    payload = Mock(spec=FinalPayload, attempts=2)\n"
    )
    [finding] = _check(source)
    assert finding.code == "SARJ479"


@pytest.mark.parametrize(
    "observation",
    [
        pytest.param("payload.model_dump.side_effect = ValueError('failed')", id="inherited-method-fault"),
        pytest.param("payload.model_dump.return_value = {'attempts': 2}", id="inherited-method-result"),
        pytest.param("payload.model_dump()", id="inherited-method-called"),
        pytest.param("payload.model_dump.assert_called_once()", id="inherited-method-asserted"),
        pytest.param("payload.unknown.side_effect = ValueError('failed')", id="unknown-child-fault"),
        pytest.param("payload.unknown.return_value = 'result'", id="unknown-child-result"),
    ],
)
def test_preserves_inherited_or_unresolved_method_behavior(observation: str) -> None:
    source = f"def test_payload():\n    payload = Mock(spec=Payload, attempts=2)\n    {observation}\n"
    assert _check(source) == []
