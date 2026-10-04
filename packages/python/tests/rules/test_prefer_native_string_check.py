from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_native_string_check import PreferNativeStringCheck


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/receipts.py") -> list[Diagnostic]:
    return PreferNativeStringCheck().check(Path(path), textwrap.dedent(source))


@pytest.mark.parametrize(
    "source",
    [
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(raw)",
        "from pydantic import TypeAdapter as Adapter\nassert Adapter[str](str).validate_python(raw)",
        "import pydantic as pd\nassert pd.TypeAdapter(str).validate_python(raw)",
        "from builtins import str as String\nfrom pydantic import TypeAdapter\nassert TypeAdapter(String).validate_python(raw)",
        "import builtins as b\nimport pydantic\nassert pydantic.TypeAdapter(b.str).validate_python(raw)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(type=str).validate_python(raw)",
        "from pydantic import TypeAdapter\nSTRING = TypeAdapter(str)\nassert STRING.validate_python(raw)",
        "from pydantic import TypeAdapter\nSTRING: TypeAdapter[str] = TypeAdapter(str)\ndef read(raw):\n    assert STRING.validate_python(raw)",
    ],
)
def test_reports_plain_string_python_validation(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_json(raw)",
        "from pydantic import TypeAdapter\nTypeAdapter(str).json_schema()",
        "from pydantic import TypeAdapter\nTypeAdapter(str).dump_python(raw)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_strings(raw)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(list[str]).validate_python(raw)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str | None).validate_python(raw)",
        "from pydantic import TypeAdapter, StringConstraints\nfrom typing import Annotated\nassert TypeAdapter(Annotated[str, StringConstraints(min_length=1)]).validate_python(raw)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(Record).validate_python(raw)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(int).validate_python(raw)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str, config=config).validate_python(raw)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(raw, strict=True)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(raw, context=context)",
        "from pydantic import TypeAdapter\nstr = CustomString\nassert TypeAdapter(str).validate_python(raw)",
        "from pydantic import TypeAdapter\ndef read(str, raw):\n    assert TypeAdapter(str).validate_python(raw)",
        "from custom import TypeAdapter\nassert TypeAdapter(str).validate_python(raw)",
        "from pydantic import TypeAdapter\nTypeAdapter = custom\nassert TypeAdapter(str).validate_python(raw)",
        "from pydantic import TypeAdapter\nSTRING = TypeAdapter(str)\nSTRING = custom\nassert STRING.validate_python(raw)",
        "from pydantic import TypeAdapter\nSTRING = TypeAdapter(str)\ndef read(STRING, raw):\n    assert STRING.validate_python(raw)",
        "from pydantic import TypeAdapter\nif enabled:\n    STRING = TypeAdapter(str)\nassert STRING.validate_python(raw)",
        "from pydantic import TypeAdapter\ndef read(raw):\n    STRING = TypeAdapter(str)\n    assert STRING.validate_python(raw)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(raw)  # sarj-noqa: SARJ480 — intentional ValidationError contract",
        '# TypeAdapter(str).validate_python(raw)\nexample = "TypeAdapter(str).validate_python(raw)"',
        "this is not valid python (",
        "from pydantic import TypeAdapter\nvalue = TypeAdapter(str).validate_python(raw)",
        "from pydantic import TypeAdapter\nwith pytest.raises(ValidationError):\n    TypeAdapter(str).validate_python(raw)",
        "from pydantic import TypeAdapter\nassert lambda: TypeAdapter(str).validate_python(raw)",
    ],
)
def test_preserves_parsing_constraints_and_uncertain_bindings(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("path", ["app/generated/receipts.py", "vendor/receipts.py"])
def test_generated_and_vendor_sources_are_excluded(path: str) -> None:
    assert _check("from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(raw)", path) == []


@pytest.mark.parametrize(
    "example",
    PreferNativeStringCheck.public_examples(),
    ids=tuple(example.example_id for example in PreferNativeStringCheck.public_examples()),
)
def test_public_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_path))) == example.expected_count


def test_findings_are_stable_and_located_at_validation_call() -> None:
    source = "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(a)\nassert TypeAdapter(str).validate_python(b)"
    findings = _check(source)
    assert findings == _check(source)
    assert [(finding.line, finding.col, finding.code) for finding in findings] == [(2, 8, "SARJ480"), (3, 8, "SARJ480")]
