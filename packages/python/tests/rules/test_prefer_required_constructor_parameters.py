from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import AutofixPolicy, Severity, is_suppressed
from sarj_python_lint.rules.prefer_required_constructor_parameters import PreferRequiredConstructorParameters


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_CASES = (
    EvaluationCase(
        "empty-string-default",
        Language.PYTHON,
        "class Service:\n    def __init__(self, label: str = ''): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nullable-default",
        Language.PYTHON,
        "class Service:\n    def __init__(self, value: str | None = None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unannotated-default",
        Language.PYTHON,
        "class Service:\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "required-nullable-domain-value",
        Language.PYTHON,
        "class Service:\n    def __init__(self, value: str | None): ...\n",
    ),
    EvaluationCase(
        "required-nullable-keyword",
        Language.PYTHON,
        "class Service:\n    def __init__(self, *, value: str | None): ...\n",
    ),
    EvaluationCase(
        "required-nested-nullable-type",
        Language.PYTHON,
        "class Service:\n    def __init__(self, values: list[str | None]): ...\n",
    ),
    EvaluationCase(
        "ordinary-method",
        Language.PYTHON,
        "class Service:\n    def run(self, value: str | None = None): ...\n",
    ),
    EvaluationCase(
        "free-init-lookalike",
        Language.PYTHON,
        "def __init__(value=None): ...\n",
    ),
    EvaluationCase(
        "nested-function-init-lookalike",
        Language.PYTHON,
        "class Service:\n    def run(self):\n        def __init__(value=None): ...\n",
    ),
    EvaluationCase(
        "dunder-new-lookalike",
        Language.PYTHON,
        "class Service:\n    def __new__(cls, value=None): ...\n",
    ),
    EvaluationCase(
        "nested-class",
        Language.PYTHON,
        "def build():\n    class Service:\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "explicit-exception-constructor",
        Language.PYTHON,
        "class ServiceError(Exception):\n    def __init__(self, message='failure'): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "typing-overload",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "typing-overload-import-alias",
        Language.PYTHON,
        "from typing import overload as signature\nclass Service:\n    @signature\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "typing-overload-module-alias",
        Language.PYTHON,
        "import typing as hints\nclass Service:\n    @hints.overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "typing-extensions-overload-alias",
        Language.PYTHON,
        "from typing_extensions import overload as signature\nclass Service:\n    @signature\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "unrelated-overload-name",
        Language.PYTHON,
        "def overload(method): return method\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "shadowed-overload-import",
        Language.PYTHON,
        "from typing import overload\noverload = custom_decorator\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-staticmethod",
        Language.PYTHON,
        "class Service:\n    @staticmethod\n    def __init__(value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-classmethod",
        Language.PYTHON,
        "class Service:\n    @classmethod\n    def __init__(cls, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-descriptor-import-alias",
        Language.PYTHON,
        "from builtins import staticmethod as descriptor\nclass Service:\n    @descriptor\n    def __init__(value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "builtin-descriptor-module-alias",
        Language.PYTHON,
        "import builtins as runtime\nclass Service:\n    @runtime.classmethod\n    def __init__(cls, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "shadowed-builtin-descriptor",
        Language.PYTHON,
        "staticmethod = custom_decorator\nclass Service:\n    @staticmethod\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-qualified-descriptor",
        Language.PYTHON,
        "import decorators\nclass Service:\n    @decorators.staticmethod\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "dataclass-field-default",
        Language.PYTHON,
        "from dataclasses import dataclass\n@dataclass\nclass Value:\n    label: str = ''\n",
    ),
    EvaluationCase(
        "pydantic-field-default",
        Language.PYTHON,
        "from pydantic import BaseModel\nclass Value(BaseModel):\n    label: str = ''\n",
    ),
    EvaluationCase(
        "class-if-constructor",
        Language.PYTHON,
        "class Service:\n    if True:\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-try-constructor",
        Language.PYTHON,
        "class Service:\n    try:\n        def __init__(self, value=None): ...\n    except Exception:\n        pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-with-constructor",
        Language.PYTHON,
        "class Service:\n    with lock:\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-for-constructor",
        Language.PYTHON,
        "class Service:\n    for _ in range(1):\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-while-constructor",
        Language.PYTHON,
        "class Service:\n    while active:\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-match-constructor",
        Language.PYTHON,
        "class Service:\n    match mode:\n        case 1:\n            def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "conditional-free-init-lookalike",
        Language.PYTHON,
        "if True:\n    def __init__(value=None): ...\n",
    ),
    EvaluationCase(
        "conditional-nested-function-lookalike",
        Language.PYTHON,
        "class Service:\n    def run(self):\n        if True:\n            def __init__(value=None): ...\n",
    ),
    EvaluationCase(
        "async-constructor",
        Language.PYTHON,
        "class Service:\n    async def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "abstract-constructor",
        Language.PYTHON,
        "from abc import abstractmethod\nclass Service:\n    @abstractmethod\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "explicit-dataclass-constructor",
        Language.PYTHON,
        "from dataclasses import dataclass\n@dataclass\nclass Service:\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "defaulted-receiver",
        Language.PYTHON,
        "class Service:\n    def __init__(self=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-scoped-overload-import",
        Language.PYTHON,
        "class Service:\n    from typing import overload\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "function-scoped-overload-import",
        Language.PYTHON,
        "def build():\n    from typing import overload\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "conditional-overload-import",
        Language.PYTHON,
        "if True:\n    from typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "unrelated-overload-parameter",
        Language.PYTHON,
        "from typing import overload\ndef run(overload): ...\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "method-parameter-does-not-shadow-decorator",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    @overload\n    def __init__(self, overload=None): ...\n",
    ),
    EvaluationCase(
        "class-shadowed-overload",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    overload = identity\n    @overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "outer-class-is-not-closure",
        Language.PYTHON,
        "from typing import overload\nclass Outer:\n    overload = identity\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "outer-class-import-not-visible",
        Language.PYTHON,
        "class Outer:\n    from typing import overload\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "mutated-overload-namespace",
        Language.PYTHON,
        "import typing\ntyping.overload = lambda method: method\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "deleted-overload-namespace",
        Language.PYTHON,
        "import typing\ndel typing.overload\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-namespace-setattr",
        Language.PYTHON,
        'import typing\nsetattr(typing, "overload", lambda method: method)\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-namespace-vars-mutation",
        Language.PYTHON,
        'import typing\nvars(typing)["overload"] = lambda method: method\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-namespace-alias-mutation",
        Language.PYTHON,
        "import typing\nhints = typing\nhints.overload = lambda method: method\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-scoped-namespace-mutation",
        Language.PYTHON,
        "import typing\ndef run():\n    import custom as typing\n    typing.overload = identity\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "overload-namespace-dictionary-mutation",
        Language.PYTHON,
        'import typing\ntyping.__dict__["overload"] = lambda method: method\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-import-after-namespace-mutation",
        Language.PYTHON,
        "import typing\ntyping.overload = lambda method: method\nfrom typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "captured-overload-before-namespace-mutation",
        Language.PYTHON,
        "from typing import overload\nimport typing\ntyping.overload = lambda method: method\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "namespace-mutation-after-declaration",
        Language.PYTHON,
        "import typing\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\ntyping.overload = lambda method: method\n",
    ),
    EvaluationCase(
        "class-rebinding-after-declaration",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n    overload = identity\n",
    ),
    EvaluationCase(
        "module-rebinding-after-declaration",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\noverload = identity\n",
    ),
    EvaluationCase(
        "overload-symbol-default",
        Language.PYTHON,
        "from typing import overload\nclass Service:\n    @overload\n    def __init__(self, value=overload): ...\n",
    ),
    EvaluationCase(
        "late-global-rebinding-before-factory-call",
        Language.PYTHON,
        "from typing import overload\ndef build():\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n    return Service\noverload = lambda method: method\nService = build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "late-local-binding-is-not-module-import",
        Language.PYTHON,
        "from typing import overload\ndef build():\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n    overload = identity\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-function-member-mutation",
        Language.PYTHON,
        'import typing\ntyping.overload.__setattr__("__code__", (lambda method: method).__code__)\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "same-line-captured-overload",
        Language.PYTHON,
        "import typing\nfrom typing import overload; typing.overload = lambda method: method\nclass Service:\n    @overload\n    def __init__(self, value=None): ...\n",
    ),
    EvaluationCase(
        "late-namespace-replacement-before-factory-call",
        Language.PYTHON,
        "import typing\ndef build():\n    class Service:\n        @typing.overload\n        def __init__(self, value=None): ...\n    return Service\ntyping.overload = lambda method: method\nService = build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "function-import-after-runtime-replacement",
        Language.PYTHON,
        "import typing\ndef build():\n    from typing import overload\n    class Service:\n        @overload\n        def __init__(self, value=None): ...\n    return Service\ntyping.overload = lambda method: method\nService = build()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-module-member-mutation",
        Language.PYTHON,
        'import typing\ntyping.__setattr__("overload", lambda method: method)\nclass Service:\n    @typing.overload\n    def __init__(self, value=None): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "overload-mutated-during-default-evaluation",
        Language.PYTHON,
        'import typing\nclass Service:\n    @typing.overload\n    def __init__(self, value=(setattr(typing.overload, "__code__", (lambda method: method).__code__), "implicit")[1]): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "signature-mutation-uses-declaration-scope",
        Language.PYTHON,
        'import typing\nclass Service:\n    @typing.overload\n    def __init__(self, typing, value=(setattr(typing.overload, "__code__", (lambda method: method).__code__), "implicit")[1]): ...\n',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "deferred-annotations-are-not-default-evaluation",
        Language.PYTHON,
        'from __future__ import annotations\nimport typing\nclass Service:\n    @typing.overload\n    def __init__(self, value: getattr(typing, "Any")=None): ...\n',
    ),
    EvaluationCase("malformed-input", Language.PYTHON, "class Service:\n    def __init__("),
)


def _check(source: str, path: str = "app/service.py") -> list[Diagnostic]:
    return PreferRequiredConstructorParameters().check(Path(path), source)


@pytest.mark.parametrize("case", _CASES, ids=[case.case_id for case in _CASES])
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1
    assert all(finding.code == "SARJ468" and finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize(
    "default",
    [
        "False",
        "0",
        "3",
        "[]",
        "{}",
        "()",
        "SENTINEL",
        "factory()",
        "...",
        "lambda: 0",
        "{**options}",
        "Service.DEFAULT",
    ],
)
def test_any_default_expression_requires_review(default: str) -> None:
    assert len(_check(f"class Service:\n    def __init__(self, value={default}): ...\n")) == 1


def test_positional_defaults_align_to_trailing_parameters() -> None:
    source = "class Service:\n    def __init__(self, required, first=1, /, second=2, *, mandatory, third=None): ...\n"
    findings = _check(source)
    line = source.splitlines()[1]
    assert [(finding.line, finding.col) for finding in findings] == [
        (2, line.index("first") + 1),
        (2, line.index("second") + 1),
        (2, line.index("third") + 1),
    ]


def test_keyword_only_required_none_annotation_differs_from_none_default() -> None:
    source = "class Service:\n    def __init__(self, *, required: str | None, optional: str | None = None): ...\n"
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].col == source.splitlines()[1].index("optional") + 1


def test_variadic_parameters_and_nullable_return_have_no_default() -> None:
    assert _check("class Service:\n    def __init__(self, *args, **kwargs) -> str | None: ...\n") == []


def test_overload_implementation_warns_once() -> None:
    source = (
        "from typing import overload\n"
        "class Service:\n"
        "    @overload\n"
        "    def __init__(self, value: str = ''): ...\n"
        "    @overload\n"
        "    def __init__(self, value: int = 0): ...\n"
        "    def __init__(self, value=None): ...\n"
    )
    assert [finding.line for finding in _check(source)] == [7]


@pytest.mark.parametrize("path", ["tests/test_service.py", "app/service.pyi"])
def test_excluded_sources(path: str) -> None:
    assert _check("class Service:\n    def __init__(self, value=None): ...\n", path) == []


def test_generated_source_is_excluded() -> None:
    assert _check("# Generated by tool\nclass Service:\n    def __init__(self, value=None): ...\n") == []


@pytest.mark.parametrize(
    "path",
    ["app/testability.py", "app/testing/service.py", "app/service_stub.py", "app/service_test_helper.py"],
)
def test_authored_production_paths_are_not_test_exclusions(path: str) -> None:
    assert len(_check("class Service:\n    def __init__(self, value=None): ...\n", path)) == 1


@pytest.mark.parametrize("comment", ["# Generated with AI assistance", "# Generate tokens for authentication"])
def test_attribution_and_runtime_generation_are_not_ownership_banners(comment: str) -> None:
    assert len(_check(f"{comment}\nclass Service:\n    def __init__(self, value=None): ...\n")) == 1


def test_descriptors_still_consume_defaults_during_construction() -> None:
    choices: list[str] = []

    class StaticService:
        @staticmethod
        def __init__(value: str = "static") -> None:
            choices.append(value)

    class ClassService:
        @classmethod
        def __init__(cls, value: str = "class") -> None:
            choices.append(value)

    StaticService()
    ClassService()
    assert choices == ["static", "class"]


def test_exact_suppression_and_manual_fix_policy() -> None:
    source = "class Service:\n    def __init__(self, value=None): ...  # sarj-noqa: SARJ468 -- library compatibility\n"
    finding = _check(source)[0]
    assert is_suppressed(source.splitlines(), finding.line, finding.code)
    assert not is_suppressed(source.splitlines(), finding.line, "SARJ095")
    documentation = PreferRequiredConstructorParameters.documentation
    assert documentation is not None
    assert documentation.autofix is AutofixPolicy.NONE


def test_repeated_checks_are_stable() -> None:
    source = "class Service:\n    def __init__(self, value=None): ...\n"
    rule = PreferRequiredConstructorParameters()
    assert rule.check(Path("app/service.py"), source) == rule.check(Path("app/service.py"), source)
