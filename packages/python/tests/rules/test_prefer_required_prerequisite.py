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
_SDK_REGISTRY = (
    "from collections.abc import Mapping\n"
    "from enum import StrEnum\n"
    "from openai import AsyncOpenAI\n"
    "class Provider(StrEnum):\n    FIRST = 'first'\n    SECOND = 'second'\n"
    "class Sender:\n"
    "    def __init__(self, *, endpoints: Mapping[Provider, AsyncOpenAI]):\n"
    "        self._endpoints = dict(endpoints)\n"
    "    async def send(self, provider: Provider):\n"
    "        selected = self._endpoints.get(provider)\n"
    "        if selected is None:\n"
    "            message = 'endpoint required'\n"
    "            raise RuntimeError(message)\n"
    "        return await selected.audio.speech.create(model='model', input='hello', voice='voice')\n"
)
_SDK_FIELD = (
    "from openai import AsyncOpenAI\n"
    "class Sender:\n"
    "    def __init__(self, *, endpoint: AsyncOpenAI | None):\n"
    "        self._endpoint = endpoint\n"
    "    async def send(self):\n"
    "        if self._endpoint is None:\n"
    "            raise RuntimeError('endpoint required')\n"
    "        return await self._endpoint.audio.speech.create(model='model', input='hello', voice='voice')\n"
)


@pytest.mark.parametrize("source", [_SDK_REGISTRY, _SDK_FIELD], ids=["partial-registry", "nullable-field"])
def test_required_sdk_dependency_is_encoded_at_construction(tmp_path: Path, source: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    path = tmp_path / "sender.py"
    path.write_text(source)
    findings = analyze(["prefer-required-prerequisite"], [path])
    assert [(finding.code, finding.severity) for finding in findings] == [("SARJ584", Severity.ERROR)]


@pytest.mark.parametrize(
    "source",
    [
        _SDK_REGISTRY.replace("Mapping[Provider, AsyncOpenAI]", "dict[Provider, AsyncOpenAI]"),
        _SDK_REGISTRY.replace(
            "from enum import StrEnum", "from typing import Literal\nfrom enum import StrEnum"
        ).replace("Mapping[Provider, AsyncOpenAI]", "Mapping[Literal['first', 'second'], AsyncOpenAI]"),
        _SDK_REGISTRY.replace(
            "raise RuntimeError(message)", "raise TaskFailureError(message, retriable=False, expected=True)"
        ),
        _SDK_FIELD.replace("from openai import AsyncOpenAI", "from openai import AsyncOpenAI as API").replace(
            "endpoint: AsyncOpenAI | None", "endpoint: API | None"
        ),
        _SDK_FIELD.replace(
            "from openai import AsyncOpenAI", "from openai import AsyncOpenAI\nfrom typing import Optional"
        ).replace("endpoint: AsyncOpenAI | None", "endpoint: Optional[AsyncOpenAI]"),
        _SDK_FIELD.replace("from openai import AsyncOpenAI", "from httpx2 import AsyncClient as AsyncOpenAI"),
        _SDK_FIELD.replace(
            "raise RuntimeError('endpoint required')", "raise RuntimeError('endpoint required') from None"
        ),
        _SDK_REGISTRY.replace("raise RuntimeError(message)", "raise TaskFailureError(message) from cause"),
    ],
    ids=["dict", "literal-provider", "task-failure", "sdk-alias", "optional", "httpx2", "no-cause", "explicit-cause"],
)
def test_sdk_contract_variants(tmp_path: Path, source: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    path = tmp_path / "variant.py"
    path.write_text(source)
    findings = analyze(["prefer-required-prerequisite"], [path])
    assert [(finding.code, finding.severity) for finding in findings] == [("SARJ584", Severity.ERROR)]


@pytest.mark.parametrize(
    "source",
    [
        _SDK_FIELD.replace("AsyncOpenAI | None", "AsyncOpenAI"),
        _SDK_FIELD.replace("raise RuntimeError('endpoint required')", "return None"),
        _SDK_FIELD.replace("raise RuntimeError('endpoint required')", "return await fallback()"),
        _SDK_FIELD.replace("self._endpoint is None", "not self._endpoint"),
        _SDK_FIELD.replace("    async def send", "    @validate_input\n    async def send"),
        _SDK_FIELD.replace(
            "        self._endpoint = endpoint",
            "        if endpoint is None:\n            raise ValueError('required')\n        self._endpoint = endpoint",
        ),
        _SDK_FIELD.replace("from openai import AsyncOpenAI", "class AsyncOpenAI: pass"),
        _SDK_FIELD.replace("from openai import AsyncOpenAI", "from other_library import AsyncOpenAI"),
        _SDK_FIELD.replace("AsyncOpenAI | None", "AsyncOpenAI | str | None"),
        _SDK_FIELD.replace(
            "    async def send",
            "    def configure(self, endpoint):\n        self._endpoint = endpoint\n    async def send",
        ),
        _SDK_REGISTRY.replace("Mapping[Provider, AsyncOpenAI]", "Mapping[str, AsyncOpenAI]"),
        _SDK_REGISTRY.replace("from enum import StrEnum", "class StrEnum: pass"),
        _SDK_REGISTRY.replace(
            "selected = self._endpoints.get(provider)", "selected = self._endpoints.get(provider, default_endpoint)"
        ),
        _SDK_REGISTRY.replace(
            "selected = self._endpoints.get(provider)",
            "self._endpoints.update(load_more())\n        selected = self._endpoints.get(provider)",
        ),
        _SDK_REGISTRY.replace(
            "selected = self._endpoints.get(provider)",
            "register(self._endpoints)\n        selected = self._endpoints.get(provider)",
        ),
        _SDK_REGISTRY.replace(
            "selected = self._endpoints.get(provider)",
            "selected = self._endpoints.get(provider)\n        selected = fallback()",
        ),
        _SDK_REGISTRY.replace(
            "raise RuntimeError(message)", "record_failure()\n            raise RuntimeError(message)"
        ),
        _SDK_REGISTRY.replace("selected is None", "selected is None and needs_audio"),
        _SDK_REGISTRY.replace(
            "return await selected.audio.speech.create(model='model', input='hello', voice='voice')", "return selected"
        ),
    ],
    ids=[
        "required",
        "absence-return",
        "fallback",
        "truthiness",
        "decorated",
        "validated-constructor",
        "shadowed-sdk",
        "unrelated-sdk",
        "mixed-union",
        "reconfigured",
        "open-keys",
        "false-enum",
        "lookup-default",
        "mutated",
        "escaped",
        "rebound",
        "logging",
        "complex-predicate",
        "narrowing",
    ],
)
def test_sdk_boundary_near_misses(tmp_path: Path, source: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    path = tmp_path / "boundary.py"
    path.write_text(source)
    assert not analyze(["prefer-required-prerequisite"], [path])


def test_sdk_dependency_error_suppression(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    path = tmp_path / "suppressed.py"
    path.write_text(
        _SDK_FIELD.replace(
            "endpoint: AsyncOpenAI | None):",
            "endpoint: AsyncOpenAI | None):  # sarj-noqa: SARJ584 -- intentional compatibility boundary",
        )
    )
    assert not analyze(["prefer-required-prerequisite"], [path])


def test_imported_finite_provider_registry(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    providers = tmp_path / "providers.py"
    providers.write_text(
        "from enum import StrEnum\nclass Provider(StrEnum):\n    FIRST = 'first'\n    SECOND = 'second'\n"
    )
    path = tmp_path / "sender.py"
    source = _SDK_REGISTRY.replace("from enum import StrEnum\n", "").replace(
        "class Provider(StrEnum):\n    FIRST = 'first'\n    SECOND = 'second'\n", "from providers import Provider\n"
    )
    path.write_text(source)
    findings = analyze(["prefer-required-prerequisite"], [path, providers])
    assert [(finding.path, finding.code, finding.severity) for finding in findings] == [
        (path, "SARJ584", Severity.ERROR)
    ]


def test_blocking_sdk_contract_owns_default_advice(tmp_path: Path) -> None:
    path = tmp_path / "sender.py"
    source = _SDK_FIELD.replace("endpoint: AsyncOpenAI | None", "endpoint: AsyncOpenAI | None = None")
    path.write_text(source)
    selectors = ["prefer-required-prerequisite", "prefer-required-constructor-parameters"]
    assert [finding.code for finding in analyze(selectors, [path])] == ["SARJ584"]
    path.write_text(
        source.replace(
            "endpoint: AsyncOpenAI | None = None):",
            "endpoint: AsyncOpenAI | None = None):  # sarj-noqa: SARJ584 -- compatibility boundary",
        )
    )
    assert [finding.code for finding in analyze(selectors, [path])] == ["SARJ468"]


def test_sdk_dependency_is_a_blocking_cli_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "sender.py"
    path.write_text(_SDK_FIELD)
    assert main(["check", "--rule", "prefer-required-prerequisite", str(path)]) == 1
    assert "SARJ584 SDK dependency" in capsys.readouterr().out


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
