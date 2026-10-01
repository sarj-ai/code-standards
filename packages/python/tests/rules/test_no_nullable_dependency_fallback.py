from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity, is_suppressed
from sarj_python_lint.rules.no_nullable_dependency_fallback import NoNullableDependencyFallback


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_CASES = (
    EvaluationCase(
        "inline-factory",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    return (DefaultFactory if factory is None else factory)()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "reverse-conditional",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    return (factory if factory is not None else DefaultFactory)()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "boolean-factory",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    return (factory or DefaultFactory)()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "normalized-factory",
        Language.PYTHON,
        "def run(*, factory: Factory | None = None):\n    factory = factory or DefaultFactory\n    return factory()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "guarded-factory",
        Language.PYTHON,
        "async def run(factory: Factory | None = None):\n    if factory is None:\n        factory = DefaultFactory\n    return await factory()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("concrete-factory", Language.PYTHON, "def run(factory: Factory):\n    return factory()\n"),
    EvaluationCase(
        "concrete-default", Language.PYTHON, "def run(factory: Factory = DefaultFactory):\n    return factory()\n"
    ),
    EvaluationCase(
        "absent-domain-task",
        Language.PYTHON,
        "async def run(task: Task | None = None):\n    if task is None:\n        return\n    await task\n",
    ),
    EvaluationCase(
        "nullable-task-result", Language.PYTHON, "async def run(task: Task[str | None]):\n    return await task\n"
    ),
    EvaluationCase(
        "prebuilt-task",
        Language.PYTHON,
        "async def run(task: Task | None = None):\n    task = task or start_recording()\n    return await task\n",
    ),
    EvaluationCase(
        "absent-callback",
        Language.PYTHON,
        "def run(callback: Callback | None = None):\n    if callback is not None:\n        callback()\n",
    ),
    EvaluationCase(
        "required-nullable-state",
        Language.PYTHON,
        "def run(callback: Callback | None):\n    if callback is not None:\n        callback()\n",
    ),
    EvaluationCase(
        "nested-shadow",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    def nested(factory):\n        return (factory or DefaultFactory)()\n    return factory\n",
    ),
    EvaluationCase(
        "rebound-local",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    factory = actual_factory\n    return (factory or DefaultFactory)()\n",
    ),
    EvaluationCase(
        "loop-shadow",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    for factory in factories:\n        (factory or DefaultFactory)()\n",
    ),
    EvaluationCase(
        "comprehension-shadow",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    return [(factory or DefaultFactory)() for factory in factories]\n",
    ),
    EvaluationCase(
        "conditional-rebinding",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    if condition:\n        factory = actual_factory\n        return (factory or DefaultFactory)()\n",
    ),
    EvaluationCase(
        "definition-rebinding",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    def factory():\n        pass\n    return (factory or DefaultFactory)()\n",
    ),
    EvaluationCase(
        "unpacked-rebinding",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    factory, other = actual_factories\n    return (factory or DefaultFactory)()\n",
    ),
    EvaluationCase(
        "optional-path",
        Language.PYTHON,
        "def run(root: Path | None = None):\n    return (Path.cwd() if root is None else root).resolve()\n",
    ),
    EvaluationCase(
        "optional-string",
        Language.PYTHON,
        "def run(contents: str | None = None):\n    text = contents or ''\n    return text.replace('x', 'y')\n",
    ),
    EvaluationCase(
        "optional-list",
        Language.PYTHON,
        "def run(buffer: list | None = None):\n    if buffer is None:\n        buffer = []\n    buffer.append('value')\n    return buffer\n",
    ),
    EvaluationCase(
        "optional-mapping",
        Language.PYTHON,
        "def run(options: dict | None = None):\n    values = options or {}\n    return values.get('key')\n",
    ),
    EvaluationCase(
        "decorated-api",
        Language.PYTHON,
        "@route\ndef run(factory: Factory | None = None):\n    return (factory or DefaultFactory)()\n",
    ),
    EvaluationCase(
        "constructor-owner",
        Language.PYTHON,
        "class Service:\n    def __init__(self, factory: Factory | None = None):\n        self.instance = (factory or DefaultFactory)()\n",
    ),
    EvaluationCase(
        "string-and-comment",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    # (factory or DefaultFactory)()\n    return '(factory or DefaultFactory)()'\n",
    ),
    EvaluationCase(
        "unrelated-guard",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    if factory is None:\n        value = fallback\n    return factory()\n",
    ),
)


def _check(source: str, path: Path = Path("app/service.py")) -> list[Diagnostic]:
    return NoNullableDependencyFallback().check(path, source)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1
    assert all(finding.severity is Severity.WARNING for finding in findings)


def test_settings_fallback_and_shadowing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    service = tmp_path / "service.py"
    prefix = "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    token: str = 'test'\nsettings = Settings()\n"
    source = f"{prefix}def run(token: str | None = None):\n    return settings.token if token is None else token\n"
    service.write_text(source)
    assert len(_check(source, service)) == 1
    getter = (
        f"{prefix}def run(token: str | None = None):\n    return settings.token_value() if token is None else token\n"
    )
    service.write_text(getter)
    assert len(_check(getter, service)) == 1
    shadowed = (
        f"{prefix}def run(settings, token: str | None = None):\n    return settings.token if token is None else token\n"
    )
    service.write_text(shadowed)
    assert _check(shadowed, service) == []


def test_source_boundaries_and_exact_suppression() -> None:
    source = "def run(factory: Factory | None = None):\n    return (factory or DefaultFactory)()\n"
    assert _check(source, Path("tests/test_service.py")) == []
    assert _check(f"# Generated by tool\n{source}") == []
    assert _check("def broken(") == []
    finding = _check(source)[0]
    assert (finding.line, finding.col) == (1, 9)
    marked = source.replace("= None):", "= None):  # sarj-noqa: SARJ469 -- deliberate library compatibility")
    assert is_suppressed(marked.splitlines(), finding.line, finding.code)
    assert not is_suppressed(marked.splitlines(), finding.line, "SARJ095")


def test_duplicate_uses_emit_one_parameter_warning() -> None:
    source = "def run(factory: Factory | None = None):\n    (factory or DefaultFactory)()\n    return (factory or DefaultFactory)()\n"
    assert len(_check(source)) == 1


def test_combined_runner_constructor_ownership_and_suppression(tmp_path: Path) -> None:
    source = "def run(factory: Factory | None = None):\n    return (factory or DefaultFactory)()\n"
    constructor = "class Service:\n    def __init__(self, factory: Factory | None = None):\n        self.instance = (factory or DefaultFactory)()\n"
    path = tmp_path / "service.py"
    path.write_text(source + constructor)
    rules = [
        "no-nullable-dependency-fallback",
        "no-hidden-constructor-fallback",
        "discourage-nullable-constructor-parameters",
    ]
    findings = analyze(rules, [path])
    assert [finding.code for finding in findings] == ["SARJ469", "SARJ468"]
    path.write_text(source.replace("= None):", "= None):  # sarj-noqa: SARJ469 -- library compatibility") + constructor)
    assert [finding.code for finding in analyze(rules, [path])] == ["SARJ468"]
    assert [finding.code for finding in analyze(rules, [path])] == ["SARJ468"]
