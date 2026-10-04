from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.no_test_method_grafting import NoTestMethodGrafting


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


TEST_PATH = Path("tests/test_dispatch.py")
_CLASSES = """
from unittest.mock import AsyncMock, Mock
from collections.abc import Callable
import pytest

class Dispatcher:
    scenario: str
    callback: Callable[[str], None]

    def apply(self, target: str) -> None:
        raise ValueError(target)

    async def resolve(self, target: str) -> str:
        return target

    @property
    def profile(self) -> str:
        return "profile"

class Recorder:
    def apply(self, target: str) -> None:
        pass

    async def resolve(self, target: str) -> str:
        return target

class ChildDispatcher(Dispatcher):
    pass
"""


def _check(source: str, path: Path = TEST_PATH) -> list[Diagnostic]:
    source = textwrap.dedent(_CLASSES) + "\n" + textwrap.dedent(source)
    rule = NoTestMethodGrafting()
    rule.prepare(ProjectIndexSet.single(path, source))
    return rule.check(path, source)


_EXAMPLES = NoTestMethodGrafting.public_examples()


@pytest.mark.parametrize("example", _EXAMPLES, ids=tuple(example.example_id for example in _EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    rule = NoTestMethodGrafting()
    rule.prepare(ProjectIndexSet.single(Path(focus.path), focus.source))
    assert len(rule.check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    recorder = Recorder()\n    dispatcher.apply = recorder.apply\n",
            id="bound-method",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    dispatcher.apply = lambda target: None\n",
            id="lambda",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    def record(target: str) -> None:\n        pass\n    dispatcher.apply = record\n",
            id="local-function",
        ),
        pytest.param(
            "async def test_dispatch():\n    dispatcher = Dispatcher()\n    async def resolve(target: str) -> str:\n        return target\n    dispatcher.resolve = resolve\n",
            id="local-async-function",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = ChildDispatcher()\n    dispatcher.apply = lambda target: None\n",
            id="inherited-method",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    recorder = Recorder()\n    setattr(dispatcher, 'apply', recorder.apply)\n",
            id="builtin-setattr",
        ),
        pytest.param(
            "def test_dispatch(dispatcher: Dispatcher):\n    dispatcher.apply = lambda target: None\n",
            id="annotated-parameter",
        ),
        pytest.param(
            "@pytest.fixture\ndef dispatcher() -> Dispatcher:\n    return Dispatcher()\n\ndef test_dispatch(dispatcher):\n    dispatcher.apply = lambda target: None\n",
            id="typed-fixture",
        ),
        pytest.param(
            "@pytest.fixture\ndef dispatcher():\n    return Dispatcher()\n\ndef test_dispatch(dispatcher):\n    dispatcher.apply = lambda target: None\n",
            id="constructor-fixture",
        ),
        pytest.param(
            "def make_dispatcher():\n    return Dispatcher()\n\ndef test_dispatch():\n    dispatcher = make_dispatcher()\n    dispatcher.apply = lambda target: None\n",
            id="one-helper-hop",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Mock(spec=Dispatcher)\n    recorder = Recorder()\n    dispatcher.apply = recorder.apply\n",
            id="specced-mock-receiver",
        ),
    ],
)
def test_reports_proven_method_replacements(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ478"
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    dispatcher.scenario = 'scenario'\n",
            id="data-field",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    recorder = Recorder()\n    dispatcher.callback = recorder.apply\n",
            id="callable-field",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    dispatcher.profile = lambda: 'profile'\n",
            id="property",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    dispatcher.unknown = lambda target: None\n",
            id="undeclared-member",
        ),
        pytest.param(
            "class RecordingDispatcher(Dispatcher):\n    def apply(self, target: str) -> None:\n        pass\n\ndef test_dispatch():\n    dispatcher = RecordingDispatcher()\n    dispatcher.apply('target')\n",
            id="declared-fake-override",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Mock(spec=Dispatcher)\n    dispatcher.resolve = AsyncMock(spec=Dispatcher.resolve)\n",
            id="mock-child-configuration",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Mock()\n    dispatcher.apply = lambda target: None\n",
            id="unknown-mock-contract",
        ),
        pytest.param(
            "def test_dispatch(dispatcher):\n    dispatcher.apply = lambda target: None\n", id="untyped-fixture"
        ),
        pytest.param(
            "def test_dispatch(dispatcher: Dispatcher | Recorder):\n    dispatcher.apply = lambda target: None\n",
            id="union-receiver",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    dispatcher = unknown()\n    dispatcher.apply = lambda target: None\n",
            id="receiver-rebound",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    recorder = Recorder()\n    recorder = unknown()\n    dispatcher.apply = recorder.apply\n",
            id="replacement-rebound",
        ),
        pytest.param(
            "def test_dispatch(flag):\n    if flag:\n        dispatcher = Dispatcher()\n    else:\n        dispatcher = unknown()\n    dispatcher.apply = lambda target: None\n",
            id="ambiguous-branch",
        ),
        pytest.param(
            "def test_dispatch(Dispatcher):\n    dispatcher = Dispatcher()\n    dispatcher.apply = lambda target: None\n",
            id="shadowed-class",
        ),
        pytest.param(
            "def test_dispatch(setattr):\n    dispatcher = Dispatcher()\n    setattr(dispatcher, 'apply', lambda target: None)\n",
            id="shadowed-setattr",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    dispatcher.apply = unknown_callable\n",
            id="unresolved-replacement",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    def inner(dispatcher):\n        dispatcher.apply = lambda target: None\n",
            id="nested-scope-shadow",
        ),
    ],
)
def test_preserves_fields_fakes_and_ambiguous_contracts(source: str) -> None:
    assert _check(source) == []


def test_reports_target_position() -> None:
    source = (
        textwrap.dedent(_CLASSES)
        + "\ndef test_dispatch():\n    dispatcher = Dispatcher()\n    dispatcher.apply = lambda target: None\n"
    )
    rule = NoTestMethodGrafting()
    rule.prepare(ProjectIndexSet.single(TEST_PATH, source))
    [finding] = rule.check(TEST_PATH, source)
    assert (finding.line, finding.col) == (len(source.splitlines()), 5)


def test_resolves_imported_method_without_importing_its_module(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-package"\nversion = "0.1.0"\n')
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    service_path = package / "service.py"
    service_source = "raise RuntimeError('must never import')\nclass Service:\n    def apply(self, target: str) -> None:\n        pass\n"
    service_path.write_text(service_source)
    tests = tmp_path / "tests"
    tests.mkdir()
    test_path = tests / "test_service.py"
    test_source = "from app.service import Service as Handler\ndef test_service():\n    service = Handler()\n    service.apply = lambda target: None\n"
    test_path.write_text(test_source)
    rule = NoTestMethodGrafting()
    rule.prepare(
        ProjectIndexSet.build([test_path, service_path], {test_path: test_source, service_path: service_source})
    )
    [finding] = rule.check(test_path, test_source)
    assert (finding.code, finding.line, finding.col) == ("SARJ478", 4, 5)


@pytest.mark.parametrize(
    "path", [Path("service.py"), Path("tests/generated/test_dispatch.py")], ids=["production", "generated"]
)
def test_excludes_unmaintained_test_sources(path: Path) -> None:
    assert (
        _check(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    dispatcher.apply = lambda target: None\n", path
        )
        == []
    )


def test_malformed_source_is_ignored() -> None:
    assert _check("def test_dispatch(:\n") == []


def test_exact_suppression_is_respected() -> None:
    assert (
        _check(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    dispatcher.apply = lambda target: None  # sarj-noqa: SARJ478 — rebinding itself is the tested contract\n"
        )
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def test_dispatch():\n    Dispatcher = unknown\n    dispatcher = Dispatcher()\n    dispatcher.apply = lambda target: None\n",
            id="rebound-class",
        ),
        pytest.param(
            "def test_dispatch(flag):\n    if flag:\n        Dispatcher = unknown\n    dispatcher = Dispatcher()\n    dispatcher.apply = lambda target: None\n",
            id="conditionally-rebound-class",
        ),
        pytest.param(
            "def make_dispatcher():\n    return Dispatcher()\n\ndef test_dispatch():\n    make_dispatcher = unknown\n    dispatcher = make_dispatcher()\n    dispatcher.apply = lambda target: None\n",
            id="rebound-factory",
        ),
        pytest.param(
            "def test_dispatch():\n    class Dispatcher:\n        apply: object\n    dispatcher = Dispatcher()\n    dispatcher.apply = lambda target: None\n",
            id="local-class-hides-global-method",
        ),
        pytest.param(
            "@replace\nclass DynamicDispatcher:\n    def apply(self, target):\n        pass\n\ndef test_dispatch():\n    dispatcher = DynamicDispatcher()\n    dispatcher.apply = lambda target: None\n",
            id="decorated-constructor",
        ),
        pytest.param(
            "class DynamicDispatcher:\n    def __new__(cls):\n        return unknown()\n    def apply(self, target):\n        pass\n\ndef test_dispatch():\n    dispatcher = DynamicDispatcher()\n    dispatcher.apply = lambda target: None\n",
            id="custom-constructor-result",
        ),
        pytest.param(
            "class DynamicDispatcher:\n    def apply(self, target):\n        pass\n    def __getattribute__(self, name):\n        return unknown()\n\ndef test_dispatch():\n    dispatcher = DynamicDispatcher()\n    dispatcher.apply = lambda target: None\n",
            id="dynamic-member-access",
        ),
    ],
)
def test_abstains_when_constructor_or_member_provenance_is_invalidated(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    ("second_argument", "expected_count"),
    [
        pytest.param("Dispatcher()", 1, id="consistent-helper-contract"),
        pytest.param("unknown()", 0, id="inconsistent-helper-contract"),
    ],
)
def test_helper_parameter_requires_consistent_callers(second_argument: str, expected_count: int) -> None:
    source = (
        "def configure(dispatcher):\n    dispatcher.apply = lambda target: None\n\n"
        "def test_first():\n    configure(Dispatcher())\n\n"
        f"def test_second():\n    configure({second_argument})\n"
    )
    assert len(_check(source)) == expected_count


def test_resolves_relative_method_import(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-package"\nversion = "0.1.0"\n')
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    tests = package / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    service_path = package / "service.py"
    service_source = "class Service:\n    def apply(self, target: str) -> None:\n        pass\n"
    service_path.write_text(service_source)
    test_path = tests / "test_relative.py"
    test_source = "from ..service import Service\ndef test_service():\n    service = Service()\n    service.apply = lambda target: None\n"
    test_path.write_text(test_source)
    rule = NoTestMethodGrafting()
    rule.prepare(
        ProjectIndexSet.build([test_path, service_path], {test_path: test_source, service_path: service_source})
    )
    [finding] = rule.check(test_path, test_source)
    assert (finding.code, finding.line) == ("SARJ478", 4)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    original = dispatcher.apply\n    def wrapper(original):\n        return original('target')\n    dispatcher.apply = wrapper\n",
            id="wrapper-parameter-shadows-original",
        ),
        pytest.param(
            "def test_dispatch():\n    dispatcher = Dispatcher()\n    original = dispatcher.apply\n    def wrapper(target):\n        return original(target)\n    original = unknown\n    dispatcher.apply = wrapper\n",
            id="captured-original-rebound-after-definition",
        ),
    ],
)
def test_wrapper_exemption_requires_unchanged_unshadowed_original(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize("import_name", ["mock", "mock as doubles"], ids=["module-symbol", "module-symbol-alias"])
def test_resolves_unittest_mock_module_symbol(import_name: str) -> None:
    module = "doubles" if " as " in import_name else "mock"
    source = (
        f"from unittest import {import_name}\n\n"
        f"def test_dispatch():\n    dispatcher = {module}.Mock(spec=Dispatcher)\n"
        "    dispatcher.apply = lambda target: None\n"
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("local_binding", "expected_count"),
    [
        pytest.param("from unittest import mock as doubles", 1, id="identical-module-alias"),
        pytest.param("from unrelated import doubles", 0, id="conflicting-module-alias"),
        pytest.param("doubles = unknown", 0, id="shadowed-module-alias"),
    ],
)
def test_local_mock_module_bindings_preserve_only_proven_imports(local_binding: str, expected_count: int) -> None:
    source = (
        "from unittest import mock as doubles\n\n"
        f"def test_dispatch():\n    {local_binding}\n"
        "    dispatcher = doubles.Mock(spec=Dispatcher)\n"
        "    dispatcher.apply = lambda target: None\n"
    )
    assert len(_check(source)) == expected_count


@pytest.mark.parametrize(
    "capture",
    [
        pytest.param(
            "try:\n        operation()\n    except Exception as dispatcher:\n        pass", id="exception-name"
        ),
        pytest.param("match candidate:\n        case dispatcher:\n            pass", id="pattern-as-name"),
        pytest.param("match candidate:\n        case [*dispatcher]:\n            pass", id="pattern-star-name"),
        pytest.param(
            "match candidate:\n        case {'detail': detail, **dispatcher}:\n            pass",
            id="pattern-mapping-rest",
        ),
    ],
)
def test_capture_bindings_invalidate_previous_method_contract(capture: str) -> None:
    source = (
        "def test_dispatch():\n    dispatcher = Dispatcher()\n"
        f"    {capture}\n    dispatcher.apply = lambda target: None\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    ("constructor", "expected_count"),
    [
        pytest.param("create_autospec(Dispatcher, instance=True, spec_set=True)", 1, id="strict-instance-autospec"),
        pytest.param("create_autospec(spec_set=True, instance=True, spec=Dispatcher)", 1, id="autospec-keyword-order"),
        pytest.param("Mock(spec=CallbackDispatcher, spec_set=Dispatcher)", 1, id="spec-set-proves-method"),
        pytest.param("Mock(spec_set=Dispatcher, spec=CallbackDispatcher)", 1, id="spec-set-proves-method-first"),
        pytest.param("Mock(spec=Dispatcher, spec_set=CallbackDispatcher)", 0, id="spec-set-proves-callback-field"),
        pytest.param(
            "Mock(spec_set=CallbackDispatcher, spec=Dispatcher)", 0, id="spec-set-proves-callback-field-first"
        ),
        pytest.param("Mock(spec=Dispatcher, spec_set=None)", 1, id="none-does-not-override-spec"),
    ],
)
def test_resolves_effective_mock_contract_for_each_factory(constructor: str, expected_count: int) -> None:
    source = (
        "from unittest.mock import create_autospec\n"
        "class CallbackDispatcher:\n    apply: Callable[[str], None] | None = None\n\n"
        f"def test_dispatch():\n    dispatcher = {constructor}\n"
        "    dispatcher.apply = lambda target: None\n"
    )
    assert len(_check(source)) == expected_count


@pytest.mark.parametrize(
    "class_source",
    [
        pytest.param(
            "class Meta(type):\n    def __new__(mcls, name, bases, namespace):\n        namespace['apply'] = None\n        return super().__new__(mcls, name, bases, namespace)\n\nclass DynamicDispatcher(metaclass=Meta):\n    def apply(self, target):\n        pass\n",
            id="metaclass-replaces-declared-method",
        ),
        pytest.param(
            "class Extensible:\n    def __init_subclass__(cls, *, replace=False):\n        if replace:\n            cls.apply = None\n\nclass DynamicDispatcher(Extensible, replace=True):\n    def apply(self, target):\n        pass\n",
            id="class-keyword-replaces-declared-method",
        ),
    ],
)
def test_abstains_for_custom_class_creation(class_source: str) -> None:
    source = (
        f"{class_source}\ndef test_dispatch():\n    dispatcher = DynamicDispatcher()\n"
        "    dispatcher.apply = lambda target: None\n"
    )
    assert _check(source) == []


def test_wrapper_delegating_to_exact_original_method_is_allowed() -> None:
    source = """
    def test_dispatch():
        dispatcher = Dispatcher()
        original = dispatcher.apply
        targets = []
        def record(target: str) -> None:
            targets.append(target)
            original(target)
        dispatcher.apply = record
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "original",
    [
        pytest.param("dispatcher.resolve", id="different-original-member"),
        pytest.param("other.apply", id="different-original-receiver"),
    ],
)
def test_wrapper_using_other_method_still_replaces_target_behavior(original: str) -> None:
    source = (
        "def test_dispatch():\n    dispatcher = Dispatcher()\n    other = Dispatcher()\n"
        f"    original = {original}\n"
        "    def record(target: str) -> None:\n        original(target)\n"
        "    dispatcher.apply = record\n"
    )
    [finding] = _check(source)
    assert finding.code == "SARJ478"


def test_saved_original_restored_to_exact_member_in_finally_is_allowed() -> None:
    source = """
    def test_dispatch():
        dispatcher = Dispatcher()
        original = dispatcher.apply
        try:
            dispatcher.apply = lambda target: None
            run(dispatcher)
        finally:
            dispatcher.apply = original
    """
    assert _check(source) == []
