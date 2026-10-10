from pathlib import Path
import subprocess
import sys
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.redundant_test_constructor_forwarder import RedundantTestConstructorForwarder


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_MODEL = "from pydantic import BaseModel\nclass Record(BaseModel):\n    value: str\n"
_HELPER = "def _record(value: str) -> Record:\n    return Record(value=value)\n"
_BASE = _MODEL + _HELPER + "def test_record():\n    assert _record('item').value == 'item'\n"
_CASES = (
    EvaluationCase("required-field-forwarder", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "constructor-owned-default",
        Language.PYTHON,
        _BASE.replace("    value: str\n", "    value: str\n    active: bool = True\n"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "omitted-required-field",
        Language.PYTHON,
        _BASE.replace("    value: str\n", "    value: str\n    active: bool\n"),
    ),
    EvaluationCase(
        "renamed-parameter",
        Language.PYTHON,
        _BASE.replace("value: str) ->", "text: str) ->").replace("value=value", "value=text"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "documented-forwarder",
        Language.PYTHON,
        _BASE.replace("    return Record", '    """Test record."""\n    return Record'),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("real-default", Language.PYTHON, _BASE.replace("value: str) ->", "value: str = 'item') ->")),
    EvaluationCase(
        "narrower-parameter",
        Language.PYTHON,
        "from typing import Literal\n" + _BASE.replace("value: str) ->", "value: Literal['item']) ->"),
    ),
    EvaluationCase("untyped-parameter", Language.PYTHON, _BASE.replace("value: str) ->", "value) ->")),
    EvaluationCase("transformation", Language.PYTHON, _BASE.replace("value=value", "value=value.strip()")),
    EvaluationCase("scenario-constant", Language.PYTHON, _BASE.replace("value=value", "value='item'")),
    EvaluationCase("decorator-seam", Language.PYTHON, _BASE.replace("def _record", "@fixture\ndef _record")),
    EvaluationCase("escaped-callback", Language.PYTHON, _BASE + "register(_record)\n"),
    EvaluationCase("patch-point", Language.PYTHON, _BASE + "patch('examples.test_record._record')\n"),
    EvaluationCase("unpacked-caller", Language.PYTHON, _BASE + "_record(**fields)\n"),
    EvaluationCase("rebound-name", Language.PYTHON, _BASE + "_record = replacement\n"),
    EvaluationCase("constructor-shadow", Language.PYTHON, _BASE + "Record = replacement\n"),
    EvaluationCase(
        "narrowed-builtin-binding",
        Language.PYTHON,
        _MODEL + "from typing import Literal\nstr = Literal['item']\n" + _HELPER + "_record('item')\n",
    ),
    EvaluationCase(
        "generic-record-type-scope",
        Language.PYTHON,
        "from typing import TypeVar\nT = TypeVar('T', bound=str)\n"
        + _BASE.replace("class Record(", "class Record[T](").replace("value: str", "value: T"),
    ),
    EvaluationCase(
        "custom-constructor",
        Language.PYTHON,
        _BASE.replace(
            "    value: str\n",
            "    value: str\n    def __init__(self, **values):\n        super().__init__(**values)\n",
        ),
    ),
    EvaluationCase(
        "constructor-alias",
        Language.PYTHON,
        _BASE.replace("from pydantic import BaseModel", "from pydantic import BaseModel, Field").replace(
            "    value: str\n", "    value: str = Field(alias='text')\n"
        ),
    ),
    EvaluationCase("public-helper", Language.PYTHON, _BASE.replace("_record", "make_record")),
    EvaluationCase(
        "nested-helper",
        Language.PYTHON,
        _MODEL
        + "def test_record():\n    def _record(value: str) -> Record:\n        return Record(value=value)\n    _record('item')\n",
    ),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase(
        "suppressed",
        Language.PYTHON,
        _BASE.replace(" -> Record:", " -> Record:  # sarj-noqa: SARJ487 -- retain test seam"),
    ),
    EvaluationCase("malformed", Language.PYTHON, "def _record(:\n"),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = RedundantTestConstructorForwarder().check(Path("tests/test_record.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1
    assert all(item.severity is Severity.WARNING for item in findings)


@pytest.mark.parametrize(
    "example",
    RedundantTestConstructorForwarder.public_examples(),
    ids=tuple(example.example_id for example in RedundantTestConstructorForwarder.public_examples()),
)
def test_public_examples(example: RuleExample) -> None:
    assert (
        len(RedundantTestConstructorForwarder().check(Path(example.focus_path), example.focus_file.source))
        == example.expected_count
    )


@pytest.mark.parametrize("path", ["app/records.py", "tests/conftest.py", "vendor/tests/test_records.py"])
def test_non_owned_paths(path: str) -> None:
    assert RedundantTestConstructorForwarder().check(Path(path), _BASE) == []


def test_fresh_process_cli_loads_registry() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sarj_python_lint", "--help"], capture_output=True, text=True, timeout=10, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "sarj-python-lint" in result.stdout


@pytest.mark.parametrize("narrow", [False, True])
def test_imported_first_party_record_and_annotation_alias(tmp_path: Path, *, narrow: bool) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").touch()
    model = package / "models.py"
    test = package / "test_records.py"
    model.write_text(
        "from pydantic import BaseModel\nfrom typing import Literal\nFieldType = str\nclass Record(BaseModel):\n    value: FieldType\n"
    )
    source = dedent("""\
        from app.models import Record, FieldType as Text
        def _record(value: Text) -> Record:
            return Record(value=value)
        def test_record():
            assert _record('item').value == 'item'
        """)
    if narrow:
        source = "from typing import Literal\n" + source.replace("value: Text", "value: Literal['item']")
    test.write_text(source)
    sources = {model: model.read_text(), test: source}
    rule = RedundantTestConstructorForwarder()
    rule.prepare(ProjectIndexSet.build(list(sources), sources))
    assert bool(rule.check(test, source)) is (not narrow)
