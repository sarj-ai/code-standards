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
        "from pydantic.type_adapter import TypeAdapter as Adapter\nassert Adapter(str).validate_python(raw)",
        "import pydantic.type_adapter as adapters\nassert adapters.TypeAdapter(str).validate_python(raw)",
        "import pydantic.type_adapter\nassert pydantic.type_adapter.TypeAdapter(str).validate_python(raw)",
        "from pydantic import TypeAdapter\ndef read(raw):\n    adapter = TypeAdapter(str)\n    assert adapter.validate_python(raw)",
        "from pydantic import TypeAdapter\nadapter = TypeAdapter(str)\nadapter.json_schema()\nassert adapter.validate_python(raw)",
        "from pydantic import TypeAdapter\nasync def read(raw):\n    adapter: TypeAdapter[str] = TypeAdapter(str)\n    assert adapter.validate_python(raw)",
        "from pydantic import TypeAdapter\nassert [TypeAdapter(str).validate_python(raw) for raw in values]",
        "import pytest\nfrom pydantic import TypeAdapter\nwith pytest.raises(AssertionError):\n    assert TypeAdapter(str).validate_python(raw)",
        "import pytest\nfrom custom import ValidationError\nfrom pydantic import TypeAdapter\nwith pytest.raises(ValidationError):\n    assert TypeAdapter(str).validate_python(raw)",
        "from custom import raises\nfrom pydantic import TypeAdapter, ValidationError\nwith raises(ValidationError):\n    assert TypeAdapter(str).validate_python(raw)",
        "import pytest\nfrom pydantic import TypeAdapter, ValidationError\npytest.raises = custom\nwith pytest.raises(ValidationError):\n    assert TypeAdapter(str).validate_python(raw)",
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
        "from pydantic import TypeAdapter\nassert TypeAdapter(dict[str, object]).validate_python(raw)",
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
        "from pydantic import TypeAdapter\ndef read(raw):\n    if enabled:\n        STRING = TypeAdapter(str)\n    assert STRING.validate_python(raw)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(raw)  # sarj-noqa: SARJ480 — intentional ValidationError contract",
        '# TypeAdapter(str).validate_python(raw)\nexample = "TypeAdapter(str).validate_python(raw)"',
        "this is not valid python (",
        "from pydantic import TypeAdapter\nvalue = TypeAdapter(str).validate_python(raw)",
        "from pydantic import TypeAdapter\nwith pytest.raises(ValidationError):\n    TypeAdapter(str).validate_python(raw)",
        "from pydantic import TypeAdapter\nassert lambda: TypeAdapter(str).validate_python(raw)",
        "from pydantic import TypeAdapter\nassert ready, TypeAdapter(str).validate_python(raw)",
        "from pydantic import TypeAdapter\nassert (TypeAdapter(str).validate_python(raw) for raw in values)",
        "from pydantic import TypeAdapter\nassert all(TypeAdapter(str).validate_python(raw) for raw in values)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python()",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(raw, other)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(raw, object=other)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(object=raw, strict=True)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(object=raw)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(raw, strict=False)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(*values)",
        "from pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(**values)",
        "from pydantic import TypeAdapter\nSTRING = TypeAdapter(str)\nborrow(STRING)\nassert STRING.validate_python(raw)",
        "from pydantic import TypeAdapter\nSTRING = TypeAdapter(str)\nSTRING.validate_python = custom\nassert STRING.validate_python(raw)",
        "from pydantic import TypeAdapter\nadapter = TypeAdapter(str)\nadapter.__init__(int)\nassert adapter.validate_python(raw)",
        "from pydantic import TypeAdapter\nSTRING = TypeAdapter(str)\ndef read(raw):\n    global STRING\n    assert STRING.validate_python(raw)",
        "from pydantic import TypeAdapter\ndef outer():\n    STRING = TypeAdapter(str)\n    def read(raw):\n        nonlocal STRING\n        assert STRING.validate_python(raw)",
        "from pydantic import TypeAdapter\nSTRING = TypeAdapter(str)\n[(STRING := custom) for item in values]\nassert STRING.validate_python(raw)",
        "from pydantic import TypeAdapter\nfrom custom import *\nassert TypeAdapter(str).validate_python(raw)",
        "import pydantic\npydantic.TypeAdapter = custom\nassert pydantic.TypeAdapter(str).validate_python(raw)",
        "import builtins\nfrom pydantic import TypeAdapter\nbuiltins.str = custom\nassert TypeAdapter(builtins.str).validate_python(raw)",
        "import builtins as b\nfrom pydantic import TypeAdapter\nb.str = custom\nassert TypeAdapter(str).validate_python(raw)",
        "import pytest\nfrom pydantic import TypeAdapter, ValidationError\nwith pytest.raises(ValidationError):\n    assert TypeAdapter(str).validate_python(raw)",
        "from pytest import raises as expect\nfrom pydantic import TypeAdapter, ValidationError as Invalid\nwith expect(Invalid, match='string'):\n    assert TypeAdapter(str).validate_python(raw)",
        "import pytest as pt\nimport pydantic as pd\nwith pt.raises(pd.ValidationError):\n    assert pd.TypeAdapter(str).validate_python(raw)",
        "from pytest import raises\nfrom pydantic_core import ValidationError\nfrom pydantic import TypeAdapter\nwith raises(expected_exception=ValidationError):\n    assert TypeAdapter(str).validate_python(raw)",
        "import pytest\nfrom pydantic import TypeAdapter, ValidationError\nwith pytest.raises((ValidationError, ValueError)):\n    assert TypeAdapter(str).validate_python(raw)",
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


def test_multiline_validation_preserves_call_line_suppression() -> None:
    source = """
        from pydantic import TypeAdapter
        assert (
            TypeAdapter(str).validate_python(  # sarj-noqa: SARJ480 — intentional byte decoding
                raw
            )
        )
    """
    assert _check(source) == []
    findings = _check(source.replace("  # sarj-noqa: SARJ480 — intentional byte decoding", ""))
    assert [(finding.line, finding.col) for finding in findings] == [(4, 5)]


@pytest.mark.parametrize(
    ("source", "expected_count"),
    [
        pytest.param(
            "from pydantic import TypeAdapter\ndef first(raw):\n    adapter = TypeAdapter(str)\n    assert adapter.validate_python(raw)\ndef second(raw):\n    adapter = TypeAdapter(str)\n    assert adapter.validate_python(raw)",
            2,
            id="independent-functions-reuse-binding-name",
        ),
        pytest.param(
            "from pydantic import TypeAdapter\ndef first(raw):\n    adapter = TypeAdapter(str)\n    borrow(adapter)\n    assert adapter.validate_python(raw)\ndef second(raw):\n    adapter = TypeAdapter(str)\n    assert adapter.validate_python(raw)",
            1,
            id="one-escaped-binding-does-not-hide-independent-binding",
        ),
        pytest.param(
            "from pydantic import TypeAdapter\ndef first(raw):\n    adapter = TypeAdapter(str)\n    adapter.__setattr__('validate_python', custom)\n    assert adapter.validate_python(raw)\ndef second(raw):\n    adapter = TypeAdapter(str)\n    assert adapter.validate_python(raw)",
            1,
            id="one-mutated-instance-does-not-hide-independent-binding",
        ),
        pytest.param(
            "from pydantic import TypeAdapter\ndef read(raw):\n    from custom import TypeAdapter\n    assert TypeAdapter(str).validate_python(raw)",
            0,
            id="nearest-custom-constructor-import",
        ),
        pytest.param(
            "from custom import TypeAdapter\ndef read(raw):\n    from pydantic import TypeAdapter\n    assert TypeAdapter(str).validate_python(raw)",
            1,
            id="nearest-pydantic-constructor-import",
        ),
        pytest.param(
            "import pydantic as pd\ndef read(raw):\n    import custom as pd\n    assert pd.TypeAdapter(str).validate_python(raw)",
            0,
            id="nearest-custom-module-import",
        ),
        pytest.param(
            "from builtins import str as String\nfrom pydantic import TypeAdapter\ndef read(raw):\n    from custom import String\n    assert TypeAdapter(String).validate_python(raw)",
            0,
            id="nearest-custom-string-import",
        ),
        pytest.param(
            "import builtins as b\nfrom pydantic import TypeAdapter\ndef read(raw):\n    import custom as b\n    assert TypeAdapter(b.str).validate_python(raw)",
            0,
            id="nearest-custom-builtins-module-import",
        ),
        pytest.param(
            "from pydantic import TypeAdapter\nclass Owner:\n    TypeAdapter = custom\n    def read(self, raw):\n        assert TypeAdapter(str).validate_python(raw)",
            1,
            id="method-does-not-close-over-class-namespace",
        ),
        pytest.param(
            "class Owner:\n    from pydantic import TypeAdapter\n    assert TypeAdapter(str).validate_python(raw)",
            1,
            id="immediate-class-body-uses-own-import",
        ),
        pytest.param(
            "from pydantic import TypeAdapter\nclass Outer:\n    TypeAdapter = custom\n    class Inner:\n        assert TypeAdapter(str).validate_python(raw)",
            1,
            id="nested-class-does-not-close-over-outer-class",
        ),
        pytest.param(
            "import pytest\nfrom pydantic import TypeAdapter, ValidationError\nwith pytest.raises(ValidationError):\n    class Owner:\n        assert TypeAdapter(str).validate_python(raw)",
            0,
            id="immediate-class-body-preserves-exception-contract",
        ),
        pytest.param(
            "import pytest\nfrom pydantic import TypeAdapter, ValidationError\nwith pytest.raises(ValidationError):\n    class Owner:\n        def read(self, raw):\n            assert TypeAdapter(str).validate_python(raw)",
            1,
            id="deferred-method-does-not-inherit-enclosing-raises",
        ),
        pytest.param(
            "import pytest\nfrom pydantic import TypeAdapter, ValidationError\nclass Owner:\n    pytest = custom\n    ValidationError = custom\n    def read(self, raw):\n        with pytest.raises(ValidationError):\n            assert TypeAdapter(str).validate_python(raw)",
            0,
            id="method-resolves-real-exception-imports-outside-class",
        ),
        pytest.param(
            "import pytest\nfrom pydantic import TypeAdapter, ValidationError\ndef read(raw):\n    import custom as pytest\n    with pytest.raises(ValidationError):\n        assert TypeAdapter(str).validate_python(raw)",
            1,
            id="custom-local-raises-does-not-suppress-warning",
        ),
        pytest.param(
            "import pydantic as pd\nimport pydantic as other\nother.TypeAdapter = custom\nassert pd.TypeAdapter(str).validate_python(raw)",
            0,
            id="equivalent-module-alias-mutation",
        ),
        pytest.param(
            "from pydantic import TypeAdapter\nimport pydantic\npydantic.TypeAdapter = custom\nassert TypeAdapter(str).validate_python(raw)",
            1,
            id="module-export-replacement-preserves-captured-class",
        ),
        pytest.param(
            "import pydantic\npydantic.TypeAdapter = custom\nfrom pydantic import TypeAdapter\nassert TypeAdapter(str).validate_python(raw)",
            0,
            id="direct-import-after-export-replacement",
        ),
        pytest.param(
            "import pydantic\ndef read(raw):\n    from pydantic import TypeAdapter\n    assert TypeAdapter(str).validate_python(raw)\npydantic.TypeAdapter = custom\nread(raw)",
            0,
            id="deferred-direct-import-after-export-replacement",
        ),
        pytest.param(
            "from pydantic import TypeAdapter\ndef modify(adapter_type):\n    adapter_type.validate_python = custom\nmodify(TypeAdapter)\nassert TypeAdapter(str).validate_python(raw)",
            0,
            id="class-identity-escaped-as-function-argument",
        ),
        pytest.param(
            "from pydantic import TypeAdapter\nAdapter = TypeAdapter\nAdapter.validate_python = custom\nassert TypeAdapter(str).validate_python(raw)",
            0,
            id="class-identity-escaped-through-local-alias",
        ),
        pytest.param(
            "import pydantic\nAlias = pydantic.TypeAdapter\nAlias.validate_python = custom\nassert pydantic.TypeAdapter(str).validate_python(raw)",
            0,
            id="qualified-class-identity-escaped-through-alias",
        ),
        pytest.param(
            "import pydantic\ndef modify(adapter_type):\n    adapter_type.validate_python = custom\nmodify(pydantic.TypeAdapter)\nassert pydantic.TypeAdapter(str).validate_python(raw)",
            0,
            id="qualified-class-identity-escaped-as-function-argument",
        ),
        pytest.param(
            "import pydantic\npydantic.__dict__['TypeAdapter'] = custom\nassert pydantic.TypeAdapter(str).validate_python(raw)",
            0,
            id="module-dictionary-write",
        ),
        pytest.param(
            "import pydantic\npydantic.__dict__.update(TypeAdapter=custom)\nassert pydantic.TypeAdapter(str).validate_python(raw)",
            0,
            id="module-dictionary-update",
        ),
        pytest.param(
            "import pydantic\npydantic.__setattr__('TypeAdapter', custom)\nassert pydantic.TypeAdapter(str).validate_python(raw)",
            0,
            id="explicit-module-dunder-mutator",
        ),
        pytest.param(
            "import pydantic.type_adapter\npydantic.type_adapter.TypeAdapter = custom\nassert pydantic.type_adapter.TypeAdapter(str).validate_python(raw)",
            0,
            id="nested-module-mutation",
        ),
        pytest.param(
            "import pydantic.type_adapter as ta\nimport pydantic.type_adapter\nta.TypeAdapter = custom\nassert pydantic.type_adapter.TypeAdapter(str).validate_python(raw)",
            0,
            id="nested-module-alias-mutation",
        ),
        pytest.param(
            "from pydantic import TypeAdapter\ndef modify():\n    global TypeAdapter\n    TypeAdapter = custom\nmodify()\nassert TypeAdapter(str).validate_python(raw)",
            0,
            id="global-import-rebinding",
        ),
        pytest.param(
            "import builtins as b\nfrom pydantic import TypeAdapter\ndef modify():\n    global b\n    b = custom\nmodify()\nassert TypeAdapter(b.str).validate_python(raw)",
            0,
            id="global-builtins-import-rebinding",
        ),
        pytest.param(
            "import builtins\nfrom pydantic import TypeAdapter\nbuiltins.__dict__.update(str=custom)\nassert TypeAdapter(str).validate_python(raw)",
            0,
            id="builtin-module-dictionary-mutation",
        ),
        pytest.param(
            "import pydantic\nborrow(pydantic)\nassert pydantic.TypeAdapter(str).validate_python(raw)",
            0,
            id="module-escape",
        ),
        pytest.param(
            "import pydantic as pd\nfrom builtins import setattr as mutate\nmutate(pd, 'TypeAdapter', custom)\nassert pd.TypeAdapter(str).validate_python(raw)",
            0,
            id="imported-builtin-mutator",
        ),
        pytest.param(
            "from pydantic import TypeAdapter\nadapter = TypeAdapter(str)\nclass Owner:\n    adapter = custom\n    borrow(adapter)\nassert adapter.validate_python(raw)",
            0,
            id="cached-binding-with-class-shadow-is-conservative",
        ),
    ],
)
def test_scoped_import_identity_and_cached_binding_contracts(source: str, expected_count: int) -> None:
    assert len(_check(source)) == expected_count
