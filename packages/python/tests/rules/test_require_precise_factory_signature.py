from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity, is_suppressed
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.require_precise_factory_signature import RequirePreciseFactorySignature


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_PREFIX = "from collections.abc import Callable\nclass Result: pass\n"
_CASES = (
    EvaluationCase(
        "fixed-keyword",
        Language.PYTHON,
        _PREFIX + "def build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "async",
        Language.PYTHON,
        _PREFIX + "async def build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "default-constructor",
        Language.PYTHON,
        _PREFIX + "def build(factory: Callable[..., Result] = Result):\n    return factory(size=4)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "typing-alias",
        Language.PYTHON,
        "from typing import Callable as Factory\nclass Result: pass\ndef build(factory: Factory[..., Result]):\n    return factory(size=4)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "qualified",
        Language.PYTHON,
        "import collections.abc as contracts\nclass Result: pass\ndef build(factory: contracts.Callable[..., Result]):\n    return factory(size=4)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "multiple-calls",
        Language.PYTHON,
        _PREFIX + "def build(factory: Callable[..., Result]):\n    factory(size=4)\n    return factory(size=5)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "callable-walrus-in-function-default",
        Language.PYTHON,
        _PREFIX
        + "class Marker:\n    @classmethod\n    def __class_getitem__(cls, item):\n        return object\ndef configure(unused=(Callable := Marker)):\n    pass\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "callable-namespace-walrus-in-function-default",
        Language.PYTHON,
        "import typing as contracts\nclass Result: pass\nclass Marker:\n    Callable = list\ndef configure(unused=(contracts := Marker)):\n    pass\ndef build(factory: contracts.Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "unrelated-default-walrus",
        Language.PYTHON,
        _PREFIX
        + "def configure(unused=(record := None)):\n    pass\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "exact", Language.PYTHON, _PREFIX + "def build(factory: Callable[[int], Result]):\n    return factory(4)\n"
    ),
    EvaluationCase(
        "constructor-type", Language.PYTHON, _PREFIX + "def build(factory: type[Result]):\n    return factory(size=4)\n"
    ),
    EvaluationCase(
        "positional-only",
        Language.PYTHON,
        _PREFIX + "def build(factory: Callable[..., Result]):\n    return factory(4)\n",
    ),
    EvaluationCase(
        "no-arguments", Language.PYTHON, _PREFIX + "def build(factory: Callable[..., Result]):\n    return factory()\n"
    ),
    EvaluationCase(
        "unpacking",
        Language.PYTHON,
        _PREFIX + "def build(factory: Callable[..., Result], options):\n    return factory(size=4, **options)\n",
    ),
    EvaluationCase(
        "starred",
        Language.PYTHON,
        _PREFIX + "def build(factory: Callable[..., Result], args):\n    return factory(*args, size=4)\n",
    ),
    EvaluationCase(
        "mixed-dynamic",
        Language.PYTHON,
        _PREFIX
        + "def build(factory: Callable[..., Result], options):\n    factory(size=4)\n    return factory(**options)\n",
    ),
    EvaluationCase(
        "forwarded",
        Language.PYTHON,
        _PREFIX + "def build(factory: Callable[..., Result]):\n    register(factory)\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "returned", Language.PYTHON, _PREFIX + "def build(factory: Callable[..., Result]):\n    return factory\n"
    ),
    EvaluationCase(
        "nested-capture",
        Language.PYTHON,
        _PREFIX
        + "def build(factory: Callable[..., Result]):\n    def inner():\n        return factory(size=4)\n    return inner\n",
    ),
    EvaluationCase(
        "nested-shadow",
        Language.PYTHON,
        _PREFIX
        + "def build(factory: Callable[..., Result]):\n    def inner(factory):\n        return factory(size=4)\n    return inner\n",
    ),
    EvaluationCase(
        "rebound",
        Language.PYTHON,
        _PREFIX + "def build(factory: Callable[..., Result]):\n    factory = Result\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "exception-binding",
        Language.PYTHON,
        _PREFIX
        + "def build(factory: Callable[..., Result]):\n    try:\n        pass\n    except Exception as factory:\n        return factory(size=4)\n",
    ),
    EvaluationCase(
        "pattern-binding",
        Language.PYTHON,
        _PREFIX
        + "def build(factory: Callable[..., Result], other):\n    match other:\n        case factory:\n            return factory(size=4)\n",
    ),
    EvaluationCase(
        "unknown-result",
        Language.PYTHON,
        "from collections.abc import Callable\ndef build(factory: Callable[..., External]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "builtin-result",
        Language.PYTHON,
        "from collections.abc import Callable\ndef build(factory: Callable[..., str]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "rebound-class",
        Language.PYTHON,
        _PREFIX + "Result = external\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "deleted-class",
        Language.PYTHON,
        _PREFIX + "del Result\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "duplicate-class",
        Language.PYTHON,
        _PREFIX + "class Result: pass\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "shadowed-callable",
        Language.PYTHON,
        _PREFIX + "Callable = custom\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "pattern-captured-callable",
        Language.PYTHON,
        _PREFIX
        + "match source:\n    case Callable:\n        pass\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "pattern-captured-typing-namespace",
        Language.PYTHON,
        "import typing\nclass Result: pass\nmatch source:\n    case typing:\n        pass\ndef build(factory: typing.Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "exception-captured-callable",
        Language.PYTHON,
        _PREFIX
        + "try:\n    action()\nexcept Exception as Callable:\n    pass\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "star-captured-callable",
        Language.PYTHON,
        _PREFIX
        + "match source:\n    case [*Callable]:\n        pass\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "mapping-captured-callable",
        Language.PYTHON,
        _PREFIX
        + "match source:\n    case {**Callable}:\n        pass\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "wildcard",
        Language.PYTHON,
        _PREFIX + "from custom import *\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "decorated",
        Language.PYTHON,
        _PREFIX + "@adapter\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "string-annotation",
        Language.PYTHON,
        _PREFIX + 'def build(factory: "Callable[..., Result]"):\n    return factory(size=4)\n',
    ),
    EvaluationCase(
        "paramspec",
        Language.PYTHON,
        _PREFIX + "def build[P](factory: Callable[P, Result]):\n    return factory(size=4)\n",
    ),
    EvaluationCase(
        "late-class",
        Language.PYTHON,
        "from collections.abc import Callable\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\nclass Result: pass\n",
    ),
    EvaluationCase("malformed", Language.PYTHON, "def build(:\n"),
)


def _check(source: str, path: Path = Path("app/service.py")) -> list[Diagnostic]:
    return RequirePreciseFactorySignature().check(path, source)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1
    assert all(item.severity is Severity.WARNING for item in findings)


@pytest.mark.parametrize("path", ["tests/test_factory.py", "app/fakes/service.py", "app/generated/client.py"])
def test_excluded_paths(path: str) -> None:
    assert _check(_CASES[0].source, Path(path)) == []


def test_exact_suppression() -> None:
    source = _CASES[0].source.replace("):\n", "):  # sarj-noqa: SARJ473 -- intentionally dynamic plugin contract.\n")
    findings = _check(source)
    assert len(findings) == 1
    assert is_suppressed(source.splitlines(), findings[0].line, findings[0].code)


@pytest.mark.parametrize("mutation", ["", "Result = external\n", "del Result\n"])
def test_imported_owned_result(tmp_path: Path, mutation: str) -> None:
    root = tmp_path / "project"
    package = root / "app"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    (package / "__init__.py").write_text("")
    definition = package / "result.py"
    service = package / "service.py"
    definition.write_text(f"class Result: pass\n{mutation}")
    service.write_text(
        "from collections.abc import Callable\nfrom app.result import Result\ndef build(factory: Callable[..., Result]):\n    return factory(size=4)\n"
    )
    sources = {path: path.read_text() for path in (definition, service)}
    rule = RequirePreciseFactorySignature()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert bool(rule.check(service, sources[service])) is (not mutation)


@pytest.mark.parametrize(
    ("import_source", "result_annotation", "capture"),
    [
        ("from app.result import Result", "Result", "match source:\n    case Result:\n        pass\n"),
        ("from app.result import Result", "Result", "try:\n    action()\nexcept Exception as Result:\n    pass\n"),
        ("import app.result as models", "models.Result", "match source:\n    case models:\n        pass\n"),
        ("import app.result as models", "models.Result", "try:\n    action()\nexcept Exception as models:\n    pass\n"),
        ("from app.result import Result", "Result", "def configure(unused=(Result := object)):\n    pass\n"),
        (
            "import app.result as models",
            "models.Result",
            "class Marker:\n    Result = str\ndef configure(unused=(models := Marker)):\n    pass\n",
        ),
    ],
)
def test_imported_owned_result_capture(
    tmp_path: Path, import_source: str, result_annotation: str, capture: str
) -> None:
    root = tmp_path / "project"
    package = root / "app"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    (package / "__init__.py").write_text("")
    definition = package / "result.py"
    service = package / "service.py"
    definition.write_text("class Result: pass\n")
    service.write_text(
        f"from collections.abc import Callable\n{import_source}\n{capture}def build(factory: Callable[..., {result_annotation}]):\n    return factory(size=4)\n"
    )
    sources = {path: path.read_text() for path in (definition, service)}
    rule = RequirePreciseFactorySignature()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert rule.check(service, sources[service]) == []


def test_cli_and_interactions_are_stable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "service.py"
    path.write_text(_CASES[0].source)
    rules = [RequirePreciseFactorySignature.id, "require-public-dependency-contract", "no-nullable-dependency-fallback"]
    assert analyze(rules, [path]) == analyze(list(reversed(rules)), [path])
    assert [finding.code for finding in analyze(rules, [path])] == ["SARJ473"]
    assert main(["check", "--rule", RequirePreciseFactorySignature.id, str(path)]) == 0
    assert "SARJ473" in capsys.readouterr().out
