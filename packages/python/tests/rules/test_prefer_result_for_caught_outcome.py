from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_custom_control_flow_exception import NoCustomControlFlowException
from sarj_python_lint.rules.prefer_result_for_caught_outcome import PreferResultForCaughtOutcome


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sarj_python_lint.rule_base import Diagnostic


_RULE = PreferResultForCaughtOutcome.id
_ERRORS = """class Declined(RuntimeError):
    pass

class Unavailable(RuntimeError):
    pass
"""
_PRODUCER = (
    _ERRORS
    + """
def decide():
    if should_skip():
        raise Declined("skip")
    raise Unavailable
"""
)
_CALLER = """from .service import Declined, Unavailable, decide as evaluate

def read():
    try:
        evaluate()
    except Unavailable:
        raise
    except Declined:
        return "skipped"
"""


def _check(root: Path, service: str, files: Mapping[str, str], *, overlap: bool = False) -> list[Diagnostic]:
    (root / ".git").mkdir()
    app = root / "app"
    app.mkdir()
    (app / "__init__.py").touch()
    producer = app / "service.py"
    producer.write_text(service, encoding="utf-8")
    for name, source in files.items():
        (app / name).write_text(source, encoding="utf-8")
    rules = [NoCustomControlFlowException.id, _RULE] if overlap else [_RULE]
    return analyze(rules, [producer])


def test_documented_examples() -> None:
    verify_native_rule(PreferResultForCaughtOutcome, analyze)


def test_catches_one_exception_and_reraises_the_other(tmp_path: Path) -> None:
    [finding] = _check(tmp_path, _PRODUCER, {"consumer.py": _CALLER})

    assert finding.line == 9
    assert finding.severity is Severity.WARNING
    assert "Declined" in finding.message
    assert "app.consumer.read" in finding.message


def test_all_awaited_calls_convert_each_named_exception(tmp_path: Path) -> None:
    producer = _PRODUCER.replace("def decide", "async def decide").replace(
        'raise Declined("skip")', 'raise Declined("skip") from cause'
    )
    caller = """from . import service

async def send():
    try:
        await service.decide()
    except (service.Declined, service.Unavailable):
        return "unavailable"
"""
    other = (
        _CALLER.replace("def read", "async def read")
        .replace("evaluate()", "await evaluate()")
        .replace("        raise", '        return "unavailable"')
    )

    findings = _check(tmp_path, producer, {"consumer.py": caller, "other.py": other})

    assert {item.line for item in findings} == {9, 10}
    assert all("app.consumer.send, app.other.read" in item.message for item in findings)


def test_only_a_direct_callee_can_supply_the_outcome(tmp_path: Path) -> None:
    producer = (
        _ERRORS
        + """
def _deep():
    raise Declined

def decide():
    _deep()
    raise Declined("outer")
"""
    )
    [finding] = _check(tmp_path, producer, {"consumer.py": _CALLER})
    assert finding.line == 12


def test_works_with_a_plain_method_and_a_same_class_receiver(tmp_path: Path) -> None:
    producer = (
        _ERRORS
        + """
class Worker:
    def _read(worker):
        raise Declined

    def run(worker):
        try:
            worker._read()
        except Declined:
            return "skipped"
"""
    )
    [finding] = _check(tmp_path, producer, {})
    assert "app.service.Worker.run" in finding.message


def test_requires_an_exact_handler_for_each_exception(tmp_path: Path) -> None:
    producer = _PRODUCER.replace("Unavailable(RuntimeError)", "Unavailable(Declined)")
    caller = _CALLER.replace("    except Unavailable:\n        raise\n", "")
    [finding] = _check(tmp_path, producer, {"consumer.py": caller})
    assert finding.line == 9


def test_resolves_imported_exception_ancestry(tmp_path: Path) -> None:
    producer = (
        "from .errors import BoundaryError\nclass Declined(BoundaryError): pass\ndef decide():\n    raise Declined\n"
    )
    errors = "class BoundaryError(OSError):\n    def __str__(self):\n        return f'{self.__dict__}'\n"
    caller = (
        "from .service import Declined, decide\n"
        "def read():\n    try:\n        decide()\n    except Declined:\n        return 'skipped'\n"
    )
    [finding] = _check(tmp_path, producer, {"consumer.py": caller, "errors.py": errors})
    assert finding.line == 4


@pytest.mark.parametrize(
    "extra",
    [
        "def propagate():\n    evaluate()\n",
        "registry = [evaluate]\n",
        "register(evaluate)\n",
        "callback = lambda: evaluate()\n",
        "def deferred():\n    yield (evaluate() for row in rows)\n",
        "def other():\n    try:\n        pass\n    finally:\n        evaluate()\n",
        "def other():\n    try:\n        pass\n    except Declined:\n        evaluate()\n",
        "def other():\n    try:\n        pass\n    except Declined:\n        pass\n    else:\n        evaluate()\n",
        "try:\n    try:\n        evaluate()\n    finally:\n        clean()\nexcept Declined:\n    pass\n",
    ],
)
def test_abstains_when_an_additional_use_does_not_convert(tmp_path: Path, extra: str) -> None:
    assert _check(tmp_path, _PRODUCER, {"consumer.py": _CALLER + extra}) == []


@pytest.mark.parametrize(
    "handler",
    [
        "    except Exception:\n        return 'unexpected'\n",
        "    except Exception:\n        pass\n    except Declined:\n        return 'skipped'\n",
        "    except Declined as error:\n        raise HTTPException(410) from error\n",
        "    except Declined:\n        if serious():\n            raise\n        return 'skipped'\n",
        "    except OtherDeclined:\n        return 'unrelated'\n",
    ],
)
def test_excludes_broad_shadowing_and_translating_handlers(tmp_path: Path, handler: str) -> None:
    caller = (
        "from .service import Declined, decide\n"
        "from .other import Declined as OtherDeclined\n"
        "def read():\n    try:\n        decide()\n" + handler
    )
    assert _check(tmp_path, _PRODUCER, {"consumer.py": caller, "other.py": _ERRORS}) == []


@pytest.mark.parametrize(
    "producer",
    [
        "def decide():\n    raise ValueError('builtin')\n",
        "from vendor import Declined\ndef decide():\n    raise Declined\n",
        "class Declined:\n    pass\ndef decide():\n    raise Declined\n",
        _ERRORS + "def decide():\n    raise Declined\ndecide = replacement\n",
        _ERRORS + "async def decide():\n    raise Declined\n",
        _ERRORS + "def decide():\n    yield 1\n    raise Declined\n",
        _ERRORS + "def decide():\n    with manager():\n        raise Declined\n",
        _ERRORS + "def decide():\n    try:\n        raise Declined\n    except Declined:\n        return None\n",
        _ERRORS + "from typing import NoReturn\ndef decide() -> 'NoReturn':\n    raise Declined\n",
        _ERRORS
        + "from typing import Never as End\ntype Terminal = End\ndef decide() -> Terminal:\n    raise Declined\n",
        _ERRORS + "from contextlib import contextmanager\n@contextmanager\ndef decide():\n    raise Declined\n",
        _ERRORS
        + "from pydantic import field_validator\n@field_validator('field')\ndef decide():\n    raise Declined\n",
        _ERRORS + "class Adapter(Port):\n    def decide(self):\n        raise Declined\n",
        _ERRORS + "class Adapter:\n    def __init__(self):\n        raise Declined\n",
    ],
)
def test_excludes_unproven_or_external_contracts(tmp_path: Path, producer: str) -> None:
    assert _check(tmp_path, producer, {"consumer.py": _CALLER}) == []


def test_package_reexport_blocks_the_proof(tmp_path: Path) -> None:
    assert (
        _check(tmp_path, _PRODUCER, {"consumer.py": _CALLER, "__init__.py": "from .consumer import evaluate\n"}) == []
    )


def test_ambiguous_import_blocks_an_apparent_match(tmp_path: Path) -> None:
    other = "from .service import decide as process\nfrom .other import decide as process\nprocess()\n"
    assert _check(tmp_path, _PRODUCER, {"consumer.py": _CALLER, "other.py": other}) == []


def test_ignores_tests_that_catch_or_propagate(tmp_path: Path) -> None:
    uncaught = "from .service import decide\ndecide()\n"
    [finding] = _check(tmp_path, _PRODUCER, {"consumer.py": _CALLER, "test_service.py": uncaught})
    assert finding.line == 9


def test_requires_a_non_test_caller(tmp_path: Path) -> None:
    assert _check(tmp_path, _PRODUCER, {"test_service.py": _CALLER}) == []


def test_exact_code_suppression_at_the_raise(tmp_path: Path) -> None:
    producer = _PRODUCER.replace(
        'raise Declined("skip")', 'raise Declined("skip")  # sarj-noqa: SARJ604 -- external failure contract'
    )
    assert _check(tmp_path, producer, {"consumer.py": _CALLER}) == []


def test_yields_to_the_marker_owner(tmp_path: Path) -> None:
    producer = _PRODUCER.replace("Declined(RuntimeError)", "Declined(Exception)")
    findings = _check(tmp_path, producer, {"consumer.py": _CALLER}, overlap=True)
    assert [(item.line, item.code) for item in findings] == [(1, NoCustomControlFlowException.code)]
