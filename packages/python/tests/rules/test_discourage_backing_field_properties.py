from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.discourage_backing_field_properties import DiscourageBackingFieldProperties


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


PROBLEM = RuleProblem(
    key="backing-field-properties",
    summary="A property forwards an ordinary constructor input through an extra accessor.",
    harm="Duplicated storage names and accessor methods add boilerplate to dependency injection and state access.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=(
        (
            "class Service:\n    def __init__(self, store):\n        self._store = store\n"
            "    @property\n    def store(self):\n        return self._store\n"
        ),
    ),
    good_examples=("class Service:\n    def __init__(self, store: Store):\n        self.store: Store = store\n",),
    exclusions=(
        "Inherited or decorated classes, slots, attribute hooks, descriptors, and accessors with additional behavior.",
    ),
)


def _service(
    *,
    getter: str = "return self._store",
    decorator: str = "property",
    header: str = "class Service:",
    before: str = "",
    members: str = "",
) -> str:
    body = getter.replace("\n", "\n        ")
    return (
        f"{before}{header}\n"
        "    def __init__(self, store):\n        self._store = store\n"
        f"    @{decorator}\n    def store(self):\n        {body}\n{members}"
    )


CASES = (
    EvaluationCase("getter", Language.PYTHON, _service(), ExpectedOutcome.MATCH),
    EvaluationCase(
        "docstring", Language.PYTHON, _service(getter='"The store."\nreturn self._store'), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "builtin-alias",
        Language.PYTHON,
        _service(before="from builtins import property as field\n", decorator="field"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "qualified-builtin",
        Language.PYTHON,
        _service(before="import builtins as b\n", decorator="b.property"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("object-base", Language.PYTHON, _service(header="class Service(object):"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "unrelated-nested-import",
        Language.PYTHON,
        _service(members="    def debug(self):\n        import json\n        return json.dumps({})\n"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("renamed-receiver", Language.PYTHON, _service().replace("self", "instance"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "different-storage-name", Language.PYTHON, _service().replace("_store", "_dependency"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "annotated-storage",
        Language.PYTHON,
        _service().replace("self._store =", "self._store: Store ="),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested-class",
        Language.PYTHON,
        "def build():\n" + "\n".join("    " + line for line in _service().splitlines()) + "\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "test-fake", Language.PYTHON, _service(), ExpectedOutcome.MATCH, path=PurePosixPath("tests/test_service.py")
    ),
    EvaluationCase("computed", Language.PYTHON, _service(getter="return len(self._store)")),
    EvaluationCase("internal-counter", Language.PYTHON, _service().replace("self._store = store", "self._store = 0")),
    EvaluationCase("internal-metric", Language.PYTHON, _service().replace("self._store = store", "self._store = None")),
    EvaluationCase(
        "constructed-dependency",
        Language.PYTHON,
        _service().replace("self._store = store", "self._store = build(store)"),
    ),
    EvaluationCase("nested-attribute", Language.PYTHON, _service(getter="return self._store.connection")),
    EvaluationCase(
        "validation", Language.PYTHON, _service(getter="assert self._store is not None\nreturn self._store")
    ),
    EvaluationCase("public-field", Language.PYTHON, _service().replace("_store", "other_store")),
    EvaluationCase("dunder-field", Language.PYTHON, _service().replace("_store", "__dict__")),
    EvaluationCase(
        "missing-constructor",
        Language.PYTHON,
        "class Service:\n    @property\n    def store(self):\n        return self._store\n",
    ),
    EvaluationCase(
        "nested-assignment",
        Language.PYTHON,
        _service().replace("self._store = store", "if store:\n            self._store = store"),
    ),
    EvaluationCase("async-getter", Language.PYTHON, _service().replace("def store", "async def store")),
    EvaluationCase(
        "extra-parameter", Language.PYTHON, _service().replace("def store(self)", "def store(self, fallback=None)")
    ),
    EvaluationCase("variadic-getter", Language.PYTHON, _service().replace("def store(self)", "def store(self, *args)")),
    EvaluationCase(
        "cached-property",
        Language.PYTHON,
        _service(before="from functools import cached_property\n", decorator="cached_property"),
    ),
    EvaluationCase("decorated-getter", Language.PYTHON, _service(decorator="property\n    @validate")),
    EvaluationCase("abstract-getter", Language.PYTHON, _service(decorator="property\n    @abstractmethod")),
    EvaluationCase("inherited-contract", Language.PYTHON, _service(header="class Service(Contract):")),
    EvaluationCase(
        "local-contract",
        Language.PYTHON,
        _service(
            before="class Contract:\n    @property\n    def store(self):\n        raise NotImplementedError\n",
            header="class Service(Contract):",
        ),
    ),
    EvaluationCase("framework-base", Language.PYTHON, _service(header="class Service(BaseModel):")),
    EvaluationCase("class-decorator", Language.PYTHON, _service(header="@dataclass\nclass Service:")),
    EvaluationCase("metaclass", Language.PYTHON, _service(header="class Service(metaclass=ModelMeta):")),
    EvaluationCase("slots", Language.PYTHON, _service(members="    __slots__ = ('_store',)\n")),
    EvaluationCase(
        "attribute-hook",
        Language.PYTHON,
        _service(members="    def __setattr__(self, name, value):\n        validate(value)\n"),
    ),
    EvaluationCase("descriptor-field", Language.PYTHON, _service(members="    _store = Descriptor()\n")),
    EvaluationCase("custom-property", Language.PYTHON, _service(before="property = instrumented_property\n")),
    EvaluationCase("class-shadow", Language.PYTHON, _service(members="    property = instrumented_property\n")),
    EvaluationCase(
        "class-import-shadow", Language.PYTHON, _service(header="class Service:\n    from custom import property")
    ),
    EvaluationCase(
        "module-mutation",
        Language.PYTHON,
        _service(before="import builtins\nbuiltins.property = custom_property\n", decorator="builtins.property"),
    ),
    EvaluationCase("wildcard-import", Language.PYTHON, _service(before="from custom import *\n")),
    EvaluationCase(
        "accessor-behavior",
        Language.PYTHON,
        _service(members="    @store.setter\n    def store(self, value):\n        self._store = validate(value)\n"),
    ),
    EvaluationCase("generated-path", Language.PYTHON, _service(), path=PurePosixPath("generated/client.py")),
    EvaluationCase("generated-header", Language.PYTHON, _service(before="# This file is generated; do not edit.\n")),
    EvaluationCase("vendor-path", Language.PYTHON, _service(), path=PurePosixPath("vendor/service.py")),
    EvaluationCase("malformed", Language.PYTHON, "class Service(:\n"),
)


@pytest.mark.parametrize("case", CASES, ids=[case.case_id for case in CASES])
def test_labeled_cases(case: EvaluationCase) -> None:
    diagnostics = DiscourageBackingFieldProperties().check(Path(case.path), case.source)

    assert len(diagnostics) == int(case.expected is ExpectedOutcome.MATCH)
    assert all(item.code == "SARJ478" and item.severity is Severity.WARNING for item in diagnostics)


@pytest.mark.parametrize(
    "example",
    DiscourageBackingFieldProperties.public_examples(),
    ids=[example.example_id for example in DiscourageBackingFieldProperties.public_examples()],
)
def test_documentation_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(DiscourageBackingFieldProperties().check(Path(focus.path), focus.source)) == example.expected_count


def test_warning_cli_suppression_and_repeatability(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "service.py"
    source = _service()
    target.write_text(source)
    command = ["check", "--rule", DiscourageBackingFieldProperties.id, str(target)]

    assert main(command) == 0
    assert "SARJ478 warning:" in capsys.readouterr().out
    assert target.read_text() == source
    findings = analyze([DiscourageBackingFieldProperties.id], [target])
    assert [(item.line, item.col) for item in findings] == [(5, 5)]
    assert findings == analyze([DiscourageBackingFieldProperties.id], [target])

    target.write_text(
        source.replace(
            "def store(self):", "def store(self):  # sarj-noqa: SARJ478 — preserve the public read-only binding"
        )
    )
    assert analyze([DiscourageBackingFieldProperties.id], [target]) == []

    target.write_text(source.replace("def store(self):", "def store(self):  # sarj-noqa: SARJ468 — unrelated rule"))
    assert len(analyze([DiscourageBackingFieldProperties.id], [target])) == 1
