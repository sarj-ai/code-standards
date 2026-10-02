from inspect import Parameter, Signature
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_broad_keyword_capture import NoBroadKeywordCapture


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_CASES = (
    EvaluationCase(
        "async-method",
        Language.PYTHON,
        "class Session:\n async def start(self, **_kwargs: object) -> None:\n  self.starts += 1\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unnamed-marker",
        Language.PYTHON,
        "def f(**kwargs: object):\n _ = kwargs\n return None\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "named-marker",
        Language.PYTHON,
        "def f(*args: object, **kwargs: object):\n _unused = args, kwargs\n return None\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "absent-annotation", Language.PYTHON, "def f(**options) -> int:\n return 1\n", ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "any-alias",
        Language.PYTHON,
        "from typing import Any as Value\ndef f(**kwargs: Value):\n return 1\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "qualified-any",
        Language.PYTHON,
        "import typing as t\ndef f(**kwargs: t.Any):\n return 1\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("quoted-object", Language.PYTHON, 'def f(**kwargs: "object"):\n return 1\n', ExpectedOutcome.MATCH),
    EvaluationCase(
        "builtin-alias",
        Language.PYTHON,
        "from builtins import object as Value\ndef f(**kwargs: Value):\n return 1\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "type-alias",
        Language.PYTHON,
        "type Value = object\ndef f(**kwargs: Value):\n return 1\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested-function",
        Language.PYTHON,
        "def outer():\n def f(**kwargs: object):\n  return 1\n return f\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "two-captures", Language.PYTHON, "def f(*args: object, **kwargs: object):\n return 1\n", ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "partial-contract",
        Language.PYTHON,
        "def f(*, room: Room, **options: object):\n return room\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("explicit-unused-parameter", Language.PYTHON, "def f(_room: Room) -> None:\n return None\n"),
    EvaluationCase("required-keyword-name", Language.PYTHON, "def f(*, room: Room) -> None:\n _unused_room = room\n"),
    EvaluationCase(
        "forwarding",
        Language.PYTHON,
        "def f(*args: object, **kwargs: object):\n return target(*args, **kwargs)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "capture",
        Language.PYTHON,
        "def f(**kwargs: object):\n def call():\n  return target(**kwargs)\n return call\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "consumed-mapping", Language.PYTHON, "def f(**kwargs: object):\n return kwargs['room']\n", ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "used-private-binding",
        Language.PYTHON,
        "def f(**kwargs: object):\n _options = kwargs\n return target(**_options)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "paramspec",
        Language.PYTHON,
        "from collections.abc import Callable\ndef f[**P, R](target: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:\n return target(*args, **kwargs)\n",
    ),
    EvaluationCase(
        "unpack",
        Language.PYTHON,
        "from typing import TypedDict, Unpack\nclass Options(TypedDict):\n room: str\ndef f(**kwargs: Unpack[Options]) -> str:\n return kwargs['room']\n",
    ),
    EvaluationCase("precise-variadic-value", Language.PYTHON, "def f(*args: str, **kwargs: int):\n return None\n"),
    EvaluationCase("shadowed-object", Language.PYTHON, "class object: pass\ndef f(**kwargs: object):\n return None\n"),
    EvaluationCase(
        "shadowed-any", Language.PYTHON, "from typing import Any\nAny = custom\ndef f(**kwargs: Any):\n return None\n"
    ),
    EvaluationCase(
        "abstract-method",
        Language.PYTHON,
        "from abc import abstractmethod as contract\nclass Provider:\n @contract\n def f(self, **kwargs: object): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "protocol",
        Language.PYTHON,
        "from typing import Protocol as Contract\nclass Provider(Contract):\n def f(self, **kwargs: object): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "string-and-comment",
        Language.PYTHON,
        '# def f(**kwargs: object): pass\nSOURCE = "def f(**kwargs: object): pass"\n',
    ),
    EvaluationCase("unannotated-legacy", Language.PYTHON, "def f(**options):\n return 1\n", ExpectedOutcome.MATCH),
    EvaluationCase(
        "unsupported-operation",
        Language.PYTHON,
        "def f(**kwargs: object) -> None:\n raise NotImplementedError\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "reject-all-calls",
        Language.PYTHON,
        "def f(**kwargs: object) -> Never:\n raise TypeError('unsupported')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload",
        Language.PYTHON,
        "from typing import overload\n@overload\ndef f(**kwargs: object) -> str: ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "runtime-hook",
        Language.PYTHON,
        "class Resource:\n def __aexit__(self, *args: object) -> None:\n  self.close()\n",
    ),
    EvaluationCase(
        "callable-fake",
        Language.PYTHON,
        "class Factory:\n def __call__(self, **kwargs: object) -> Manager:\n  return self.manager\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "positional-variadic-contract",
        Language.PYTHON,
        "def log_message(self, format: str, *args: object) -> None:\n pass\n",
    ),
    EvaluationCase(
        "dynamic-attribute-api",
        Language.PYTHON,
        "class Placeholder:\n def __getattr__(self, name: str) -> Placeholder:\n  return self\n def __call__(self, **kwargs: object) -> Placeholder:\n  return self\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "enclosing-object-binding",
        Language.PYTHON,
        "def outer(object: type):\n def f(**kwargs: object) -> None:\n  pass\n return f\n",
    ),
    EvaluationCase(
        "enclosing-any-binding",
        Language.PYTHON,
        "from typing import Any\ndef outer():\n Any = str\n def f(**kwargs: Any) -> None:\n  pass\n return f\n",
    ),
    EvaluationCase(
        "class-alias-binding",
        Language.PYTHON,
        "from typing import Any as Value\nclass Owner:\n Value = str\n def f(self, **kwargs: Value) -> None:\n  pass\n",
    ),
    EvaluationCase(
        "forwarded-any",
        Language.PYTHON,
        "from typing import Any\ndef f(**kwargs: Any):\n return target(**kwargs)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "forwarded-unannotated", Language.PYTHON, "def f(**kwargs):\n return target(**kwargs)\n", ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "annotated-object",
        Language.PYTHON,
        "from typing import Annotated\ndef f(**kwargs: Annotated[object, 'metadata']):\n return None\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "union-any",
        Language.PYTHON,
        "from typing import Any, Union\ndef f(**kwargs: Union[str, Any]):\n return None\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "optional-object", Language.PYTHON, "def f(**kwargs: object | None):\n return None\n", ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "runtime-keyword-hook",
        Language.PYTHON,
        "class Resource:\n def __init_subclass__(cls, **kwargs: object) -> None:\n  super().__init_subclass__(**kwargs)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("generic-object-binding", Language.PYTHON, "def f[object](**kwargs: object) -> None:\n pass\n"),
    EvaluationCase(
        "enclosing-generic-binding",
        Language.PYTHON,
        "class Owner[object]:\n def f(self, **kwargs: object) -> None:\n  pass\n",
    ),
    EvaluationCase("precise-union", Language.PYTHON, "def f(**kwargs: str | int):\n return kwargs\n"),
    EvaluationCase(
        "nested-any-is-not-broad-value",
        Language.PYTHON,
        "from typing import Any\ndef f(**kwargs: list[Any]):\n return kwargs\n",
    ),
    EvaluationCase(
        "relative-object-import", Language.PYTHON, "from .types import object\ndef f(**kwargs: object):\n pass\n"
    ),
    EvaluationCase(
        "conditional-object-import",
        Language.PYTHON,
        "for _index in range(1):\n from narrow import object\ndef f(**kwargs: object):\n pass\n",
    ),
    EvaluationCase(
        "relative-wildcard-object", Language.PYTHON, "from .types import *\ndef f(**kwargs: object):\n pass\n"
    ),
    EvaluationCase(
        "wildcard-rebound-any",
        Language.PYTHON,
        "from typing import Any\nfrom narrow import *\ndef f(**kwargs: Any):\n pass\n",
    ),
    EvaluationCase(
        "aliased-typing-guard-object",
        Language.PYTHON,
        "import typing as t\nif t.TYPE_CHECKING:\n from narrow import object\ndef f(**kwargs: object):\n pass\n",
    ),
    EvaluationCase(
        "wildcard-unannotated-still-warns",
        Language.PYTHON,
        "from narrow import *\ndef f(**kwargs):\n pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "outer-positional-capture-shadow", Language.PYTHON, "def outer(*object):\n def f(**kwargs: object):\n  pass\n"
    ),
    EvaluationCase(
        "outer-keyword-capture-shadow",
        Language.PYTHON,
        "from typing import Any\ndef outer(**Any):\n def f(**kwargs: Any):\n  pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "typed-decorator-contract",
        Language.PYTHON,
        "from typing import Protocol\nclass RoomCall(Protocol):\n def __call__(self, *, room: str) -> str: ...\ndef room_only(function: RoomCall) -> RoomCall:\n return function\n@room_only\ndef start(**kwargs: object) -> str:\n return str(kwargs)\n",
    ),
    EvaluationCase(
        "unknown-decorator-factory",
        Language.PYTHON,
        "@factory(option=True)\ndef f(**kwargs: object):\n return kwargs\n",
    ),
    EvaluationCase(
        "wraps-contract-unresolved",
        Language.PYTHON,
        "from functools import wraps\n@wraps(target)\ndef f(**kwargs: object):\n return target(**kwargs)\n",
    ),
    EvaluationCase(
        "builtin-staticmethod",
        Language.PYTHON,
        "class Owner:\n @staticmethod\n def f(**kwargs: object):\n  return kwargs\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "aliased-classmethod",
        Language.PYTHON,
        "from builtins import classmethod as method\nclass Owner:\n @method\n def f(cls, **kwargs: object):\n  return kwargs\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "shadowed-staticmethod",
        Language.PYTHON,
        "def outer(staticmethod):\n @staticmethod\n def f(**kwargs: object):\n  return kwargs\n",
    ),
    EvaluationCase(
        "aliased-abstractmethod",
        Language.PYTHON,
        "from abc import abstractmethod as method\nclass Owner:\n @method\n def f(self, **kwargs: object): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-recognized-overloads",
        Language.PYTHON,
        "from typing import overload as OV\n@OV\ndef f(*, room: str) -> str: ...\n@OV\ndef f(*, count: int) -> int: ...\ndef f(**kwargs: object) -> str | int:\n return str(kwargs)\n",
    ),
    EvaluationCase(
        "overload-qualified-alias",
        Language.PYTHON,
        "import typing as t\n@t.overload\ndef f(*, room: str) -> str: ...\n@t.overload\ndef f(*, count: int) -> int: ...\ndef f(**kwargs: object) -> str | int:\n return str(kwargs)\n",
    ),
    EvaluationCase(
        "overload-typing-extensions-alias",
        Language.PYTHON,
        "from typing_extensions import overload as OV\n@OV\ndef f(*, room: str) -> str: ...\n@OV\ndef f(*, count: int) -> int: ...\ndef f(**kwargs: object) -> str | int:\n return str(kwargs)\n",
    ),
    EvaluationCase(
        "overload-class-method",
        Language.PYTHON,
        "from typing import overload as OV\nclass C:\n @OV\n def f(self, *, room: str) -> str: ...\n @OV\n def f(self, *, count: int) -> int: ...\n def f(self, **kwargs: object) -> str | int:\n  return str(kwargs)\n",
    ),
    EvaluationCase(
        "overload-async-overloads",
        Language.PYTHON,
        "from typing import overload as OV\n@OV\nasync def f(*, room: str) -> str: ...\n@OV\nasync def f(*, count: int) -> int: ...\nasync def f(**kwargs: object) -> str | int:\n return str(kwargs)\n",
    ),
    EvaluationCase(
        "overload-nested-scope",
        Language.PYTHON,
        "from typing import overload as OV\ndef outer():\n @OV\n def f(*, room: str) -> str: ...\n @OV\n def f(*, count: int) -> int: ...\n def f(**kwargs: object) -> str | int:\n  return str(kwargs)\n",
    ),
    EvaluationCase(
        "overload-conditional-same-branch",
        Language.PYTHON,
        "from typing import overload as OV\nif condition:\n @OV\n def f(*, room: str) -> str: ...\n @OV\n def f(*, count: int) -> int: ...\n def f(**kwargs: object) -> str | int:\n  return str(kwargs)\n",
    ),
    EvaluationCase(
        "overload-conditional-overloads-outer-implementation",
        Language.PYTHON,
        "from typing import overload as OV\nif condition:\n @OV\n def f(*, room: str) -> str: ...\n @OV\n def f(*, count: int) -> int: ...\nelse:\n @OV\n def f(*, room: str) -> str: ...\n @OV\n def f(*, count: int) -> int: ...\ndef f(**kwargs: object) -> str | int:\n return str(kwargs)\n",
    ),
    EvaluationCase(
        "overload-single-overload-invalid",
        Language.PYTHON,
        "from typing import overload as OV\n@OV\ndef f(*, room: str) -> str: ...\ndef f(**kwargs: object) -> str | int:\n return str(kwargs)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-unrelated-other-scope",
        Language.PYTHON,
        "from typing import overload as OV\nclass C:\n @OV\n def f(*, room: str) -> str: ...\n @OV\n def f(*, count: int) -> int: ...\ndef f(**kwargs: object) -> str | int:\n return str(kwargs)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-intervening-name-rebinding",
        Language.PYTHON,
        "from typing import overload as OV\n@OV\ndef f(*, room: str) -> str: ...\n@OV\ndef f(*, count: int) -> int: ...\nf = something\ndef f(**kwargs: object) -> str | int:\n return str(kwargs)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-decorator-rebound",
        Language.PYTHON,
        "from typing import overload as OV\nOV = custom\n@OV\ndef f(*, room: str) -> str: ...\n@OV\ndef f(*, count: int) -> int: ...\ndef f(**kwargs: object) -> str | int:\n return str(kwargs)\n",
    ),
    EvaluationCase(
        "overload-decorator-local-shadow",
        Language.PYTHON,
        "from typing import overload as OV\ndef outer(OV):\n @OV\n def f(*, room: str) -> str: ...\n @OV\n def f(*, count: int) -> int: ...\n def f(**kwargs: object) -> str | int:\n  return str(kwargs)\n",
    ),
    EvaluationCase(
        "overload-later-unrelated-implementation",
        Language.PYTHON,
        'from typing import overload as OV\n@OV\ndef f(*, room: str) -> str: ...\n@OV\ndef f(*, count: int) -> int: ...\ndef f(*, room: str = "") -> str:\n return room\ndef f(**kwargs: object) -> str | int:\n return str(kwargs)\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-custom-same-spelling",
        Language.PYTHON,
        "def OV(f):\n return f\n@OV\ndef f(*, room: str) -> str: ...\n@OV\ndef f(*, count: int) -> int: ...\ndef f(**kwargs: object) -> str | int:\n return str(kwargs)\n",
    ),
    EvaluationCase(
        "relative-decorator-binding",
        Language.PYTHON,
        "from .types import staticmethod\n@staticmethod\ndef f(**kwargs: object):\n return kwargs\n",
    ),
    EvaluationCase(
        "wildcard-decorator-binding",
        Language.PYTHON,
        "from alternate import *\n@staticmethod\ndef f(**kwargs):\n return kwargs\n",
    ),
    EvaluationCase(
        "known-override-contract",
        Language.PYTHON,
        "from typing import override as method\nclass Owner(Base):\n @method\n def f(self, **kwargs: object):\n  return kwargs\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "known-final-contract",
        Language.PYTHON,
        "import typing as t\nclass Owner:\n @t.final\n def f(self, **kwargs: object):\n  return kwargs\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "known-extensions-override",
        Language.PYTHON,
        "from typing_extensions import override\nclass Owner(Base):\n @override\n def f(self, **kwargs: object):\n  return kwargs\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module_overload_deleted_valid",
        Language.PYTHON,
        "from typing import overload\n@overload\ndef f(*, value: int) -> int: ...\n@overload\ndef f(*, value: str) -> str: ...\ndel overload\ndef f(**kwargs: object) -> object:\n    return kwargs['value']\nf(value='valid')\n",
    ),
    EvaluationCase(
        "class_overload_later_binding_valid",
        Language.PYTHON,
        "from typing import overload\nclass C:\n    @overload\n    def f(self, *, value: int) -> int: ...\n    @overload\n    def f(self, *, value: str) -> str: ...\n    def overload(self) -> int:\n        return 1\n    def f(self, **kwargs: object) -> object:\n        return kwargs['value']\nC().f(value='valid')\n",
    ),
    EvaluationCase(
        "wildcard-overload-unannotated-implementation",
        Language.PYTHON,
        "from typing import overload\nfrom collections.abc import *\n@overload\ndef f(*, value: int) -> int: ...\n@overload\ndef f(*, value: str) -> str: ...\ndef f(**kwargs) -> object:\n return kwargs['value']\n",
    ),
    EvaluationCase(
        "reexported-overload-decorator",
        Language.PYTHON,
        "from api_types import declare\n@declare\ndef f(*, value: int) -> int: ...\n@declare\ndef f(*, value: str) -> str: ...\ndef f(**kwargs: object) -> object:\n return kwargs['value']\n",
    ),
    EvaluationCase(
        "identity-markers-do-not-imply-overloads",
        Language.PYTHON,
        "from typing import final\n@final\ndef f(*, value: int) -> int: ...\n@final\ndef f(*, value: str) -> str: ...\ndef f(**kwargs: object) -> object:\n return kwargs['value']\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "documented-reexported-overload-decorator",
        Language.PYTHON,
        'from api_types import declare\n@declare\ndef f(*, value: int) -> int:\n "Integer input."\n ...\n@declare\ndef f(*, value: str) -> str:\n "String input."\n ...\ndef f(**kwargs: object) -> object:\n return kwargs["value"]\n',
    ),
    EvaluationCase(
        "docstring-only-reexported-overload-decorator",
        Language.PYTHON,
        'from api_types import declare\n@declare\ndef f(*, value: int) -> int:\n "Integer input."\n@declare\ndef f(*, value: str) -> str:\n "String input."\ndef f(**kwargs: object) -> object:\n return kwargs["value"]\n',
    ),
    EvaluationCase(
        "unknown-decorator-concrete-bodies-remain-uncertain",
        Language.PYTHON,
        'from api_types import decorate\n@decorate\ndef f(*, value: int) -> int:\n return value\n@decorate\ndef f(*, value: str) -> str:\n return value\ndef f(**kwargs: object) -> object:\n return kwargs["value"]\n',
    ),
    EvaluationCase("malformed", Language.PYTHON, "def f(**:\n"),
)


def _check(source: str, path: Path = Path("app/service.py")) -> list[Diagnostic]:
    return NoBroadKeywordCapture().check(path, source)


@pytest.mark.parametrize("case", _CASES, ids=[case.case_id for case in _CASES])
def test_labeled_contract_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(f.code == "SARJ477" and f.severity is Severity.WARNING for f in findings)


@pytest.mark.parametrize("path", ["generated/service.py", "vendor/service.py", "service.pyi"])
def test_ignores_generated_vendor_and_stub_source(path: str) -> None:
    assert _check("def f(**kwargs: object):\n return None\n", Path(path)) == []


def test_exact_suppression_and_repeat_are_stable() -> None:
    source = "def f(**kwargs: object):  # sarj-noqa: SARJ477 — third-party dynamic callback contract\n return None\n"
    assert _check(source) == _check(source) == []


def test_reports_tests_as_well_as_production() -> None:
    assert len(_check("def f(**kwargs: object):\n return None\n", Path("tests/fakes/session.py"))) == 1


def test_unknown_keyword_reproduction() -> None:
    broad = Signature([Parameter("_kwargs", Parameter.VAR_KEYWORD, annotation=object)])
    explicit = Signature([Parameter("room", Parameter.KEYWORD_ONLY, annotation=str)])
    assert broad.bind(misspelled_room="room")
    with pytest.raises(TypeError):
        explicit.bind(misspelled_room="room")


@pytest.mark.parametrize(
    "example",
    NoBroadKeywordCapture.public_examples(),
    ids=[example.example_id for example in NoBroadKeywordCapture.public_examples()],
)
def test_public_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source)) == example.expected_count


def test_broad_overloads_remain_warnings() -> None:
    source = "from typing import overload\n@overload\ndef f(*, room: str) -> str: ...\n@overload\ndef f(**kwargs: object) -> int: ...\ndef f(**kwargs: object) -> str | int:\n return str(kwargs)\n"
    assert len(_check(source)) == 2


@pytest.mark.parametrize(
    "source",
    [
        "def f(\n **kwargs: object,  # sarj-noqa: SARJ477 — required dynamic callback contract\n) -> None:\n pass\n",
        "def f(  # sarj-noqa: SARJ477 — required dynamic callback contract\n **kwargs: object,\n) -> None:\n pass\n",
    ],
)
def test_multiline_local_suppression(source: str) -> None:
    assert _check(source) == []


def test_multiline_diagnostic_points_to_capture() -> None:
    (finding,) = _check("def f(\n **kwargs: object,\n) -> None:\n pass\n")
    assert (finding.line, finding.col) == (2, 4)


def test_deliberate_open_formatting_contract_has_reasoned_exception() -> None:
    source = "def render(template: str, **values: object) -> str:  # sarj-noqa: SARJ477 — template supplies dynamic field names and object formatting\n return template.format(**values)\n"
    assert _check(source) == []
