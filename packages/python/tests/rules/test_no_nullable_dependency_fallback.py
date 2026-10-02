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
    EvaluationCase(
        "stable-factory-alias",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    selected = factory or DefaultFactory\n    return selected()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "stable-annotated-factory-alias",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    selected: Factory = factory or DefaultFactory\n    return selected()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "data-alias-called-after-rebinding",
        Language.PYTHON,
        "def run(value: int | None = None) -> tuple[int, str]:\n    selected = value or 10\n    observed = selected\n    selected = str\n    return observed, selected(observed)\n",
    ),
    EvaluationCase(
        "data-alias-called-before-rebinding",
        Language.PYTHON,
        "def run(value: int | None = None) -> tuple[int, str]:\n    selected = str\n    text = selected(5)\n    selected = value or 10\n    return selected, text\n",
    ),
    EvaluationCase(
        "callable-parameter-called-before-data-assignment",
        Language.PYTHON,
        "from collections.abc import Callable\ndef run(value: int | None = None, *, selected: Callable[[], str] | int) -> tuple[int, str]:\n    if isinstance(selected, int):\n        return selected, ''\n    text = selected()\n    selected = value or 10\n    return selected, text\n",
    ),
    EvaluationCase(
        "callable-parameter-called-in-data-assignment-rhs",
        Language.PYTHON,
        "from collections.abc import Callable\ndef run(value: int | None = None, *, selected: Callable[[], str] | int) -> int:\n    if isinstance(selected, int):\n        return selected\n    selected = value or len(selected())\n    return selected\n",
    ),
    EvaluationCase(
        "optional-callable-called-before-data-guard",
        Language.PYTHON,
        "from collections.abc import Callable\ndef run(value: Callable[[], str] | int | None = None) -> object:\n    if value is not None and not isinstance(value, int):\n        value()\n    if value is None:\n        value = 10\n    return value\n",
    ),
    EvaluationCase(
        "same-line-stable-factory-alias",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    selected = factory or DefaultFactory; return selected()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "data-alias-rebound-by-definition",
        Language.PYTHON,
        "def run(value: int | None = None):\n    selected = value or 10\n    def selected():\n        return 'replacement'\n    return selected()\n",
    ),
    EvaluationCase(
        "data-alias-rebound-by-import",
        Language.PYTHON,
        "def run(value: int | None = None):\n    selected = value or 10\n    from helpers import replacement as selected\n    return selected()\n",
    ),
    EvaluationCase(
        "data-alias-rebound-by-pattern",
        Language.PYTHON,
        "def run(value: int | None = None):\n    selected = value or 10\n    match source:\n        case {**selected}:\n            pass\n    return selected()\n",
    ),
    EvaluationCase(
        "data-alias-rebound-by-exception",
        Language.PYTHON,
        "def run(value: int | None = None):\n    selected = value or 10\n    try:\n        action()\n    except Error as selected:\n        return selected()\n",
    ),
    EvaluationCase(
        "data-alias-rebound-in-branch",
        Language.PYTHON,
        "def run(value: int | None = None):\n    selected = value or 10\n    if condition:\n        selected = str\n        return selected(5)\n    return selected\n",
    ),
    EvaluationCase(
        "data-alias-rebound-by-comprehension-walrus",
        Language.PYTHON,
        "def run(value: int | None = None):\n    selected = value or 10\n    results = [(selected := str) for item in items]\n    return selected(5), results\n",
    ),
    EvaluationCase(
        "guarded-data-rebound-before-call",
        Language.PYTHON,
        "def run(value: object | None = None) -> str:\n    if value is None:\n        value = 10\n    observed = value\n    value = str\n    return value(observed)\n",
    ),
    EvaluationCase(
        "data-annotated-alias-called-after-rebinding",
        Language.PYTHON,
        "def run(value: int | None = None):\n    selected: object = value or 10\n    selected = str\n    return selected(5)\n",
    ),
    EvaluationCase(
        "nullable-parameter-rebound-by-pattern",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    match source:\n        case {'factory': factory}:\n            return (factory or DefaultFactory)()\n",
    ),
    EvaluationCase(
        "nullable-parameter-replaced-by-concrete-pattern",
        Language.PYTHON,
        "def concrete():\n    return 7\nsource = concrete\ndef run(factory=None):\n    match source:\n        case factory:\n            return (factory or concrete)()\n",
    ),
    EvaluationCase(
        "nullable-parameter-replaced-by-comprehension-walrus",
        Language.PYTHON,
        "def concrete():\n    return 7\ndef run(factory=None):\n    replacements = [(factory := concrete) for item in range(1)]\n    return (factory or concrete)(), replacements\n",
    ),
    EvaluationCase(
        "nullable-parameter-rebound-by-exception",
        Language.PYTHON,
        "def run(factory: Factory | None = None):\n    try:\n        action()\n    except Error as factory:\n        return (factory or DefaultFactory)()\n",
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


@pytest.mark.parametrize(
    "body",
    [
        "class StateError(Exception):\n    token = 'temporary'\ndef run(token=None):\n    try:\n        raise StateError()\n    except StateError as settings:\n        return settings.token if token is None else token\n",
        "class State:\n    token = 'temporary'\ndef run(token=None):\n    match State():\n        case settings:\n            return settings.token if token is None else token\n",
        "class State:\n    token = 'temporary'\ndef run(token=None):\n    global settings\n    settings = State()\n    return settings.token if token is None else token\n",
        "def outer(settings):\n    def run(token=None):\n        return settings.token if token is None else token\n    return run\n",
        "def outer(value):\n    match value:\n        case settings:\n            def run(token=None):\n                return settings.token if token is None else token\n            return run\n",
        "class State:\n    token = 'temporary'\ndef replace():\n    global settings\n    settings = State()\nreplace()\ndef run(token=None):\n    return settings.token if token is None else token\n",
    ],
    ids=(
        "exception-state",
        "pattern-state",
        "global-state",
        "enclosing-parameter",
        "enclosing-pattern",
        "module-global-writer",
    ),
)
def test_settings_runtime_provenance_is_required(tmp_path: Path, body: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    (tmp_path / "settings_provider.py").write_text(
        "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    token: str='ambient'\nsettings = Settings()\n"
    )
    source = f"from settings_provider import settings\n{body}"
    path = tmp_path / "service.py"
    path.write_text(source)
    assert _check(source, path) == []


def test_read_only_global_settings_stays_proven(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\nversion='0.1.0'\n")
    (tmp_path / "settings_provider.py").write_text(
        "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings):\n    token: str='ambient'\nsettings = Settings()\n"
    )
    source = "from settings_provider import settings\ndef observe():\n    global settings\n    return settings.token\ndef run(token=None):\n    return settings.token if token is None else token\n"
    path = tmp_path / "service.py"
    path.write_text(source)
    assert len(_check(source, path)) == 1
