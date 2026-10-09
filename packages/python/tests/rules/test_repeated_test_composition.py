from pathlib import Path, PurePosixPath

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.repeated_test_composition import RepeatedTestComposition


_SERVICE = """
from typing import Protocol
class Port(Protocol):
    def run(self): ...
class Service:
    def __init__(self, first: Port, second: Port):
        self.first = first
        self.second = second
    def run(self):
        return self.first.run(), self.second.run()
"""


def _tests(call: str = "Service(first, second)", count: int = 3) -> str:
    return "\n".join(
        f"def test_case_{number}(first, second):\n    result = {call}\n    assert result.run()\n"
        for number in range(count)
    )


_CASES = (
    EvaluationCase("two-collaborators", Language.PYTHON, _SERVICE + _tests(), ExpectedOutcome.MATCH),
    EvaluationCase("below-threshold", Language.PYTHON, _SERVICE + _tests(count=2)),
    EvaluationCase("dynamic-arguments", Language.PYTHON, _SERVICE + _tests("Service(**options)")),
    EvaluationCase("untyped-constructor", Language.PYTHON, _SERVICE.replace(": Port", "") + _tests()),
    EvaluationCase("scalar-methods", Language.PYTHON, _SERVICE.replace(": Port", ": str") + _tests()),
    EvaluationCase("not-invoked", Language.PYTHON, _SERVICE.replace("self.second.run()", "self.second") + _tests()),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _SERVICE + _tests()),
    EvaluationCase("malformed", Language.PYTHON, "def test_broken(:"),
    EvaluationCase("data-class", Language.PYTHON, _SERVICE.replace("class Port(Protocol)", "class Port") + _tests()),
    EvaluationCase("helpers", Language.PYTHON, _SERVICE + _tests().replace("test_case_", "make_case_")),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_composition_cases(case: EvaluationCase) -> None:
    findings = RepeatedTestComposition().check(Path("tests/test_service.py"), case.source)
    assert bool(findings) is (case.expected == ExpectedOutcome.MATCH)


def test_every_construction_has_a_distinct_stable_location() -> None:
    findings = RepeatedTestComposition().check(Path("tests/test_service.py"), _SERVICE + _tests())
    assert len(findings) == 3
    assert len({(item.line, item.col) for item in findings}) == 3
    assert {item.code for item in findings} == {"SARJ457"}


@pytest.mark.parametrize("wrapper", ["fixture", "validation", "multiple", "nested", "unittest"])
def test_excludes_non_composition_contexts(wrapper: str) -> None:
    tests = _tests()
    match wrapper:
        case "fixture":
            tests = tests.replace("def test_", "@pytest.fixture\ndef test_")
        case "validation":
            tests = tests.replace("    result =", "    with pytest.raises(ValueError):\n        result =")
        case "multiple":
            tests = tests.replace(
                "    assert result.run()", "    other = Service(first, second)\n    assert result.run() != other.run()"
            )
        case "nested":
            tests = "def helper():\n" + "\n".join("    " + line for line in tests.splitlines())
        case _:
            tests = "from unittest import TestCase\nclass Tests(TestCase):\n" + "\n".join(
                "    " + line for line in tests.splitlines()
            )
    assert RepeatedTestComposition().check(Path("tests/test_service.py"), "import pytest\n" + _SERVICE + tests) == []


def test_unambiguous_local_aliases_are_normalized() -> None:
    tests = _tests("Constructor(left, second)").replace(
        "    result =", "    Constructor = Service\n    left = first\n    result ="
    )
    assert len(RepeatedTestComposition().check(Path("tests/test_service.py"), _SERVICE + tests)) == 3


def test_different_collaborator_bindings_do_not_match() -> None:
    source = _SERVICE + _tests().replace("result = Service(first, second)", "result = Service(second, first)", 1)
    assert RepeatedTestComposition().check(Path("tests/test_service.py"), source) == []


def test_httpx_context_clients_allow_distinct_app_instances() -> None:
    source = "from httpx import AsyncClient as Client, ASGITransport as Transport\n"
    source += "\n".join(
        f"async def test_case_{number}():\n"
        f"    async with Client(transport=Transport(app=make_app_{number}()), base_url='http://test') as client:\n"
        "        assert await client.get('/')\n"
        for number in range(3)
    )
    assert len(RepeatedTestComposition().check(Path("tests/test_service.py"), source)) == 3
    assert (
        RepeatedTestComposition().check(
            Path("tests/test_service.py"), source.replace("base_url='http://test'", "base_url='http://other'", 1)
        )
        == []
    )


def test_documentation_examples() -> None:
    for example in RepeatedTestComposition.public_examples():
        assert example.focus_path == PurePosixPath("tests/test_client.py")
        assert (
            len(RepeatedTestComposition().check(Path(str(example.focus_path)), example.focus_file.source))
            == example.expected_count
        )


def test_six_dependencies_can_share_two_collaborators() -> None:
    service = _SERVICE.replace("second: Port):", "second: Port, *, a: int, b: str, c: bool, d: float):")
    tests = _tests("Service(first, second, a=1, b='x', c=True, d=1.0)")
    assert len(RepeatedTestComposition().check(Path("tests/test_service.py"), service + tests)) == 3


def test_first_party_fake_construction_matches_aliases_and_inline_calls() -> None:
    source = _SERVICE + "\nclass FakePort(Port):\n    def run(self): return True\n"
    tests = _tests("Service(FakePort(), FakePort())")
    tests = tests.replace(
        "    result = Service(FakePort(), FakePort())",
        "    runner = FakePort()\n    result = Service(FakePort(), runner)",
        1,
    )
    assert len(RepeatedTestComposition().check(Path("tests/test_service.py"), source + tests)) == 3


@pytest.mark.parametrize(
    "setup",
    [
        "from elsewhere import Service",
        "def Service(*args): return args",
        "class Service: pass",
        "Service = first",
    ],
)
def test_local_constructor_shadowing_is_excluded(setup: str) -> None:
    source = _SERVICE + _tests().replace("    result =", f"    {setup}\n    result =")
    assert RepeatedTestComposition().check(Path("tests/test_service.py"), source) == []


def test_regular_pytest_marks_allow_composition_analysis() -> None:
    tests = _tests().replace("def test_", "@pytest.mark.asyncio\ndef test_")
    assert (
        len(RepeatedTestComposition().check(Path("tests/test_service.py"), "import pytest\n" + _SERVICE + tests)) == 3
    )


def test_class_parametrization_is_not_fixture_composition() -> None:
    tests = "@pytest.mark.parametrize('first,second', [(1,2)])\nclass TestCases:\n"
    tests += "\n".join("    " + line for line in _tests().splitlines())
    assert RepeatedTestComposition().check(Path("tests/test_service.py"), "import pytest\n" + _SERVICE + tests) == []


def test_cross_module_resolution_works_without_classes_in_the_test_file(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'sample'\nversion = '0.1.0'\n")
    service = tmp_path / "service.py"
    service.write_text(_SERVICE)
    tests = tmp_path / "tests"
    tests.mkdir()
    path = tests / "test_service.py"
    source = "from service import Service as Subject\n" + _tests("Subject(first, second)")
    path.write_text(source)
    rule = RepeatedTestComposition()
    rule.prepare(ProjectIndexSet.build([path], {path: source}))
    assert len(rule.check(path, source)) == 3


@pytest.mark.parametrize(
    "change",
    ["module-shadow", "field-overwrite", "conditional", "fixture-mutation", "constructor-assertion", "fake-mutation"],
)
def test_semantic_near_misses_do_not_report(change: str) -> None:
    source = _SERVICE + _tests()
    match change:
        case "module-shadow":
            source = _SERVICE + "\nService = another_factory\n" + _tests()
        case "field-overwrite":
            source = source.replace("self.first = first", "self.first = first\n        self.first = other")
        case "conditional":
            source = source.replace("    result =", "    if flag:\n        result =")
        case "fixture-mutation":
            source = source.replace("    result =", "    first.configure()\n    result =")
        case "constructor-assertion":
            source = source.replace("result.run()", "result.first")
        case _:
            source = _SERVICE + "\nclass FakePort(Port):\n    def run(self): return True\n"
            source += _tests("Service(FakePort(), runner)").replace(
                "    result =", "    runner = FakePort()\n    runner.configure()\n    result ="
            )
    assert RepeatedTestComposition().check(Path("tests/test_service.py"), source) == []


def test_second_dynamic_client_prevents_fixture_recommendation() -> None:
    source = "from httpx import AsyncClient, ASGITransport\n" + "\n".join(
        f"async def test_case_{number}(app, options):\n"
        "    other = AsyncClient(**options)\n"
        "    async with AsyncClient(transport=ASGITransport(app=app)) as client:\n"
        "        assert await client.get('/')\n"
        "    await other.aclose()\n"
        for number in range(3)
    )
    assert RepeatedTestComposition().check(Path("tests/test_client.py"), source) == []


def test_constructor_subject_reassigned_before_method_call_is_excluded() -> None:
    source = _SERVICE + _tests().replace("    assert result.run()", "    result = other\n    assert result.run()")
    assert RepeatedTestComposition().check(Path("tests/test_service.py"), source) == []


def test_constructed_dependency_import_shadowing_is_excluded() -> None:
    source = _SERVICE + "\nclass FakePort(Port):\n    def run(self): return True\n"
    source += _tests("Service(FakePort(), FakePort())").replace(
        "    result =", "    from elsewhere import FakePort\n    result ="
    )
    assert RepeatedTestComposition().check(Path("tests/test_service.py"), source) == []


@pytest.mark.parametrize("constructed", [False, True])
@pytest.mark.parametrize(
    "mutation", ["alias.configure()", "alias.option = 1", "del alias.option", "alias.options[0] = 1"]
)
@pytest.mark.parametrize("chain", ["alias = first", "intermediate = first\n    alias = intermediate"])
def test_mutations_through_dependency_aliases_are_excluded(constructed: bool, mutation: str, chain: str) -> None:
    setup = ("first = FakePort()\n    " if constructed else "") + chain + "\n    " + mutation + "\n    "
    source = _SERVICE + "\nclass FakePort(Port):\n    def run(self): return True\n"
    source += _tests().replace("    result =", "    " + setup + "result =")
    assert RepeatedTestComposition().check(Path("tests/test_service.py"), source) == []


def test_mutating_an_unrelated_alias_does_not_hide_repetition() -> None:
    source = _SERVICE + _tests().replace("    result =", "    alias = other\n    alias.configure()\n    result =")
    assert len(RepeatedTestComposition().check(Path("tests/test_service.py"), source)) == 3


def test_dependency_mutation_after_construction_remains_outside_setup() -> None:
    source = _SERVICE + _tests().replace(
        "    assert result.run()", "    alias = first\n    alias.configure()\n    assert result.run()"
    )
    assert len(RepeatedTestComposition().check(Path("tests/test_service.py"), source)) == 3


@pytest.mark.parametrize("extra", ["", "    alias = transport\n"])
def test_managed_transport_aliases(extra: str) -> None:
    receiver = "alias" if extra else "transport"
    source = "from httpx import AsyncClient, ASGITransport\n" + "\n".join(
        f"async def test_case_{number}(app):\n"
        "    Client = AsyncClient\n    Transport = ASGITransport\n"
        "    transport = Transport(app=app)\n"
        + extra
        + f"    async with Client(transport={receiver}, base_url='http://test') as client:\n"
        "        assert await client.get('/')\n"
        for number in range(3)
    )
    assert len(RepeatedTestComposition().check(Path("tests/test_client.py"), source)) == 3
    for mutation in ("transport.option = True", "transport.configure()", "transport = custom"):
        mutated = source.replace("    async with", "    " + mutation + "\n    async with")
        assert RepeatedTestComposition().check(Path("tests/test_client.py"), mutated) == []


def test_shadowed_transport_constructor_is_not_httpx() -> None:
    source = "from httpx import AsyncClient, ASGITransport\n" + "\n".join(
        f"async def test_case_{number}(app, ASGITransport):\n"
        "    transport = ASGITransport(app=app)\n"
        "    async with AsyncClient(transport=transport) as client:\n        assert await client.get('/')\n"
        for number in range(3)
    )
    assert RepeatedTestComposition().check(Path("tests/test_client.py"), source) == []
