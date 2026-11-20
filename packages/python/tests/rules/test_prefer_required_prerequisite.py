from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_required_prerequisite import PreferRequiredPrerequisite


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_SIMPLE = (
    "def execute(service: Service | None = None):\n"
    "    if service is None:\n        raise ValueError('service required')\n"
    "    service.run()\n"
)
_LINKED_SHAPE = (
    "async def say_for_scenario(session: Session, call_settings: Settings,\n"
    "                           scenario_config: Config | None, call_config: GlobalSettings,\n"
    "                           global_prompt_service: Service | None = None) -> None:\n"
    "    userdata = session.userdata\n"
    "    pending_generated_audio = userdata.pending_generated_audio\n"
    "    userdata.pending_generated_audio = None\n"
    "    if intro_will_be_skipped(userdata, call_settings, scenario_config):\n"
    "        userdata.language_switch_enter = False\n"
    "        if pending_generated_audio is not None:\n"
    "            pending_generated_audio.cancel()\n"
    "        return\n"
    "    if not scenario_config:\n"
    "        msg = f'No scenario configuration: {call_settings.scenario.id}'\n"
    "        raise ValueError(msg)\n"
    "    if not global_prompt_service:\n"
    "        msg = 'service required for execution'\n"
    "        raise ValueError(msg)\n"
    "    language = scenario_config.get_language_settings(call_settings.language)\n"
    "    await speak(global_prompt_service, language, call_config)\n"
)
_CASES = (
    EvaluationCase(
        "unreachable-after-return",
        Language.PYTHON,
        _SIMPLE.replace("    if service", "    return\n    if service"),
    ),
    EvaluationCase(
        "unreachable-after-raise",
        Language.PYTHON,
        _SIMPLE.replace("    if service", "    raise RuntimeError('disabled')\n    if service"),
    ),
    EvaluationCase(
        "class-suite-callback",
        Language.PYTHON,
        _SIMPLE + "\nclass Handlers:\n    execute = register_callback(execute)\n",
    ),
    EvaluationCase(
        "class-suite-direct-call",
        Language.PYTHON,
        _SIMPLE + "\nclass Handlers:\n    result = execute(service)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "reassigned-callback",
        Language.PYTHON,
        _SIMPLE + "execute = register_callback(execute)\n",
    ),
    EvaluationCase(
        "replaced-function-definition",
        Language.PYTHON,
        _SIMPLE + "\ndef execute(service: Service):\n    service.run()\n",
    ),
    EvaluationCase(
        "absence-already-accepted",
        Language.PYTHON,
        "def execute(service: Service | None):\n"
        "    if service is None:\n        return\n"
        "    if not service:\n        raise ValueError('present service is not ready')\n"
        "    service.run()\n",
    ),
    EvaluationCase(
        "absence-already-rejected-elsewhere",
        Language.PYTHON,
        "def execute(service: Service | None):\n"
        "    if service is None:\n        raise RuntimeError('no service')\n"
        "    if not service:\n        raise ValueError('present service is not ready')\n"
        "    service.run()\n",
    ),
    EvaluationCase("none-prerequisite", Language.PYTHON, _SIMPLE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "nullable-without-default",
        Language.PYTHON,
        _SIMPLE.replace(" = None", ""),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "reverse-none",
        Language.PYTHON,
        _SIMPLE.replace("service is None", "None is service"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "truthiness",
        Language.PYTHON,
        _SIMPLE.replace("service is None", "not service"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "message-assignment",
        Language.PYTHON,
        _SIMPLE.replace(
            "        raise ValueError('service required')", "        msg = 'required'\n        raise ValueError(msg)"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nominal-falsy-state",
        Language.PYTHON,
        "class Service:\n    def __bool__(self): return False\n" + _SIMPLE.replace("service is None", "not service"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "quoted-optional",
        Language.PYTHON,
        "from typing import Optional as Maybe\n" + _SIMPLE.replace("Service | None", "'Maybe[Service]'"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "annotated-union",
        Language.PYTHON,
        "import typing as t\n" + _SIMPLE.replace("Service | None", "t.Annotated[t.Union[Service, None], 'metadata']"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "stable-local-alias",
        Language.PYTHON,
        "type MaybeService = Service | None\n" + _SIMPLE.replace("Service | None", "MaybeService"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "independent-comprehension-binding",
        Language.PYTHON,
        _SIMPLE.replace("    if service", "    values = [service for service in sources]\n    if service"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested-exception-name-is-independent",
        Language.PYTHON,
        _SIMPLE.replace(
            "    if service",
            "    def helper():\n        ValueError = RuntimeError\n        return ValueError\n    if service",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("concrete-dependency", Language.PYTHON, _SIMPLE.replace("Service | None = None", "Service")),
    EvaluationCase(
        "meaningful-absence",
        Language.PYTHON,
        _SIMPLE.replace("raise ValueError('service required')", "return"),
    ),
    EvaluationCase(
        "narrowing-adapter",
        Language.PYTHON,
        _SIMPLE.replace("service.run()", "return service"),
    ),
    EvaluationCase(
        "decorated-boundary",
        Language.PYTHON,
        "@validate_input\n" + _SIMPLE,
    ),
    EvaluationCase(
        "known-callback-registration",
        Language.PYTHON,
        _SIMPLE + "register_callback(execute)\n",
    ),
    EvaluationCase(
        "constructor",
        Language.PYTHON,
        "class Owner:\n    def __init__(self, service: Service | None):\n"
        "        if service is None:\n            raise ValueError('required')\n        self.service = service\n",
    ),
    EvaluationCase(
        "method-contract",
        Language.PYTHON,
        "class Owner:\n    def execute(self, service: Service | None):\n"
        "        if service is None:\n            raise ValueError('required')\n        service.run()\n",
    ),
    EvaluationCase(
        "rebound-fallback",
        Language.PYTHON,
        _SIMPLE.replace("    if service", "    service = service or discover_service()\n    if service"),
    ),
    EvaluationCase(
        "conditional-rebinding",
        Language.PYTHON,
        _SIMPLE.replace("    if service", "    if enabled:\n        service = discover_service()\n    if service"),
    ),
    EvaluationCase(
        "exception-parameter",
        Language.PYTHON,
        _SIMPLE.replace(" = None)", ", ValueError: ErrorFactory)"),
    ),
    EvaluationCase(
        "later-local-exception-binding",
        Language.PYTHON,
        _SIMPLE + "    ValueError = RuntimeError\n",
    ),
    EvaluationCase(
        "comprehension-walrus-exception-binding",
        Language.PYTHON,
        _SIMPLE + "    [(ValueError := RuntimeError) for item in ()]\n",
    ),
    EvaluationCase(
        "module-error-rebindings",
        Language.PYTHON,
        "ValueError = RuntimeError\nValueError = CustomError\n" + _SIMPLE,
    ),
    EvaluationCase(
        "complex-rejection",
        Language.PYTHON,
        _SIMPLE.replace("        raise", "        if allow_skip:\n            return\n        raise"),
    ),
    EvaluationCase(
        "compound-condition",
        Language.PYTHON,
        _SIMPLE.replace("service is None", "enabled and service is None"),
    ),
    EvaluationCase(
        "different-error-protocol",
        Language.PYTHON,
        _SIMPLE.replace("raise ValueError(", "raise MissingServiceError("),
    ),
    EvaluationCase(
        "non-none-sentinel-default",
        Language.PYTHON,
        _SIMPLE.replace("Service | None = None", "Service | Unset | None = UNSET"),
    ),
    EvaluationCase(
        "nullable-element",
        Language.PYTHON,
        _SIMPLE.replace("Service | None", "list[Service | None]"),
    ),
    EvaluationCase(
        "raw-object-boundary",
        Language.PYTHON,
        _SIMPLE.replace("Service | None", "object | None"),
    ),
    EvaluationCase(
        "primitive-value-validation",
        Language.PYTHON,
        _SIMPLE.replace("Service | None", "str | None"),
    ),
    EvaluationCase(
        "container-value-validation",
        Language.PYTHON,
        _SIMPLE.replace("Service | None", "list[Service] | None").replace("service is None", "not service"),
    ),
    EvaluationCase(
        "metadata-is-not-nullability",
        Language.PYTHON,
        "from typing import Annotated\n" + _SIMPLE.replace("Service | None", "Annotated[Service, None]"),
    ),
    EvaluationCase(
        "unsupported-alias",
        Language.PYTHON,
        "from external import MaybeService\n" + _SIMPLE.replace("Service | None", "MaybeService"),
    ),
    EvaluationCase(
        "cyclic-local-alias",
        Language.PYTHON,
        "type A = B\ntype B = A\n" + _SIMPLE.replace("Service | None", "A"),
    ),
    EvaluationCase(
        "nested-capture",
        Language.PYTHON,
        "def outer(service: Service | None):\n"
        "    def inner():\n        if service is None:\n            raise ValueError('required')\n"
        "        service.run()\n    return inner\n",
    ),
    EvaluationCase(
        "already-modeled-overloads",
        Language.PYTHON,
        "from typing import Literal, overload as signature\n"
        "@signature\ndef execute(*, skip: Literal[True], service: Service | None = None) -> None: ...\n"
        "@signature\ndef execute(*, skip: Literal[False], service: Service) -> None: ...\n"
        "def execute(*, skip: bool, service: Service | None = None) -> None:\n"
        "    if skip:\n        return\n"
        "    if service is None:\n        raise ValueError('required')\n    service.run()\n",
    ),
)


def _check(source: str, path: Path = Path("app/service.py")) -> list[Diagnostic]:
    return PreferRequiredPrerequisite().check(path, source)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_contracts(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(finding.severity is Severity.WARNING for finding in findings)


def test_linked_async_shape_preserves_conditional_review() -> None:
    findings = _check(_LINKED_SHAPE)
    assert [finding.line for finding in findings] == [12, 15]
    assert all("on this path" in finding.message for finding in findings)
    assert all("other falsy objects" in finding.message for finding in findings)
    assert all(finding.severity is Severity.WARNING for finding in findings)


def test_known_presence_is_specific_to_the_parameter() -> None:
    source = _LINKED_SHAPE.replace(
        "    userdata = session.userdata",
        "    if scenario_config is None:\n        return\n    userdata = session.userdata",
    )
    findings = _check(source)
    assert len(findings) == 1
    assert "global_prompt_service" in findings[0].message


def test_unmarked_conversion_boundary_remains_a_disclosed_review_false_positive() -> None:
    source = (
        "def materialize(request: Request | None) -> Job:\n"
        "    if request is None:\n        raise ValueError('missing request')\n"
        "    return Job(request)\n"
    )
    assert len(_check(source)) == 1
    marked = source.replace(
        "if request is None:", "if request is None:  # sarj-noqa: SARJ584 -- preserve nullable decoder boundary"
    )
    assert _check(marked) == []


def test_work_budget_and_source_boundaries() -> None:
    aliases = "type A0 = Service | None\n" + "".join(
        f"type A{index} = A{index - 1} | A{index - 1}\n" for index in range(1, 8)
    )
    assert _check(aliases + _SIMPLE.replace("Service | None", "A7")) == []
    assert _check(_SIMPLE, Path("tests/test_service.py")) == []
    assert _check(_SIMPLE, Path("app/service.pyi")) == []
    assert _check("# Generated by tool\n" + _SIMPLE) == []
    assert _check("def incomplete(") == []


def test_warning_cli_exact_suppressions_and_blocking_precedence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "service.py"
    target.write_text(_LINKED_SHAPE)
    rules = ["check", "--rule", PreferRequiredPrerequisite.id]
    assert main([*rules, str(target)]) == 0
    assert capsys.readouterr().out.count("SARJ584 warning:") == 2

    marked = _LINKED_SHAPE.replace(
        "if not scenario_config:",
        "if not scenario_config:  # sarj-noqa: SARJ584 -- preserve conditional intro compatibility",
    )
    target.write_text(marked)
    findings = analyze([PreferRequiredPrerequisite.id], [target])
    assert len(findings) == 1
    assert "global_prompt_service" in findings[0].message
    target.write_text(marked.replace("sarj-noqa: SARJ584", "sarj-noqa: SARJ469"))
    assert len(analyze([PreferRequiredPrerequisite.id], [target])) == 2

    target.write_text(_SIMPLE + "\n# ----------------\nvalue = 2\n")
    assert main([*rules, "--rule", "no-comment-cruft", str(target)]) == 1
    output = capsys.readouterr().out
    assert "SARJ584 warning:" in output
    assert "SARJ016" in output


def test_documented_examples() -> None:
    verify_native_rule(PreferRequiredPrerequisite, analyze)
