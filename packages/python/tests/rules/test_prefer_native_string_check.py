from pathlib import Path, PurePosixPath
import textwrap
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rules.prefer_native_string_check import PreferNativeStringCheck
from sarj_python_lint.rules.require_pydantic_for_external_json import RequirePydanticForExternalJson


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/receipts.py") -> list[Diagnostic]:
    return PreferNativeStringCheck().check(Path(path), textwrap.dedent(source))


_JSON_IMPORTS = "from pydantic import TypeAdapter, JsonValue\nfrom fastapi.encoders import jsonable_encoder\n"
_JSON_CALL = "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'detail': errors, 'body': body}))"
JSON_OUTPUT_CASES = tuple(
    EvaluationCase(
        case_id=case_id,
        language=Language.PYTHON,
        source=_JSON_IMPORTS + source,
        expected=expected,
        path=PurePosixPath("app/responses.py"),
    )
    for case_id, source, expected in (
        ("helper_return", f"def response_content(errors, body):\n    return {_JSON_CALL}", ExpectedOutcome.MATCH),
        ("response_content", f"JSONResponse(content={_JSON_CALL})", ExpectedOutcome.MATCH),
        ("assignment", f"content = {_JSON_CALL}", ExpectedOutcome.MATCH),
        (
            "import_aliases",
            "from pydantic import TypeAdapter as Adapter, JsonValue as JSON\nfrom fastapi.encoders import jsonable_encoder as encode\nAdapter(dict[str, JSON]).validate_python(encode({'body': body}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "module_aliases",
            "import pydantic as pd\nimport fastapi.encoders as enc\npd.TypeAdapter(dict[str, pd.JsonValue]).validate_python(enc.jsonable_encoder({'body': body}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "dotted_modules",
            "import pydantic.type_adapter\nimport fastapi.encoders\npydantic.type_adapter.TypeAdapter(dict[str, JsonValue]).validate_python(fastapi.encoders.jsonable_encoder({'body': body}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "builtin_aliases",
            "from builtins import dict as Dictionary, str as String\nTypeAdapter(Dictionary[String, JsonValue]).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "generic_constructor",
            "TypeAdapter[dict[str, JsonValue]](dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "captured_encoder_export",
            f"import fastapi.encoders as enc\nenc.jsonable_encoder = custom\n{_JSON_CALL}",
            ExpectedOutcome.MATCH,
        ),
        (
            "captured_json_value_export",
            f"import pydantic\npydantic.JsonValue = custom\n{_JSON_CALL}",
            ExpectedOutcome.MATCH,
        ),
        (
            "custom_bytes_encoder",
            "def response_content(exc):\n    return TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'detail': exc.errors(), 'body': exc.body}, custom_encoder={bytes: lambda v: v.decode('utf-8', errors='replace')}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "encoder_options",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body}, exclude_none=True, by_alias=False))",
            ExpectedOutcome.MATCH,
        ),
        (
            "keyword_encoder_input",
            "TypeAdapter(type=dict[str, JsonValue]).validate_python(jsonable_encoder(obj={'body': body}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "empty_mapping",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "nested_integer_key",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': {1: 'value'}}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "cached_module_adapter",
            "ADAPTER = TypeAdapter(dict[str, JsonValue])\nADAPTER.validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "cached_local_adapter",
            "def response(body):\n    adapter = TypeAdapter(dict[str, JsonValue])\n    return adapter.validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.MATCH,
        ),
        ("raw_ingress", "TypeAdapter(dict[str, JsonValue]).validate_python(raw)", ExpectedOutcome.NO_MATCH),
        (
            "unknown_encoded_shape",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder(raw))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "encoded_list",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder([body]))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "dynamic_root_keys",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({key: body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "integer_root_key_contract",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({1: body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "mapping_unpack",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body, **extra}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "model_schema",
            "TypeAdapter(Payload).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "constrained_schema",
            "TypeAdapter(Annotated[dict[str, JsonValue], constraint]).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "other_mapping",
            "TypeAdapter(Mapping[str, JsonValue]).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "other_value_type",
            "TypeAdapter(dict[str, object]).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "adapter_config",
            "TypeAdapter(dict[str, JsonValue], config=config).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "validation_options",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body}), strict=True)",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "validation_json",
            "TypeAdapter(dict[str, JsonValue]).validate_json(jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "cached_encoded_value",
            "encoded = jsonable_encoder({'body': body})\nTypeAdapter(dict[str, JsonValue]).validate_python(encoded)",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "schema_alias",
            "type JSON = dict[str, JsonValue]\nTypeAdapter(JSON).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        ("shadowed_dict", f"def response(dict):\n    return {_JSON_CALL}", ExpectedOutcome.NO_MATCH),
        ("shadowed_str", f"def response(str):\n    return {_JSON_CALL}", ExpectedOutcome.NO_MATCH),
        ("shadowed_json_value", f"def response(JsonValue):\n    return {_JSON_CALL}", ExpectedOutcome.NO_MATCH),
        ("shadowed_encoder", f"def response(jsonable_encoder):\n    return {_JSON_CALL}", ExpectedOutcome.NO_MATCH),
        ("rebound_encoder", f"jsonable_encoder = custom\n{_JSON_CALL}", ExpectedOutcome.NO_MATCH),
        ("encoder_escape", f"borrow(jsonable_encoder)\n{_JSON_CALL}", ExpectedOutcome.NO_MATCH),
        (
            "encoder_alias_mutation",
            f"encode = jsonable_encoder\nencode.__code__ = custom\n{_JSON_CALL}",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "encoder_module_mutation",
            "import fastapi.encoders as enc\nenc.jsonable_encoder = custom\nTypeAdapter(dict[str, JsonValue]).validate_python(enc.jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "encoder_module_dict_mutation",
            "import fastapi.encoders as enc\nenc.__dict__['jsonable_encoder'] = custom\nTypeAdapter(dict[str, JsonValue]).validate_python(enc.jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "json_value_module_mutation",
            "import pydantic\npydantic.JsonValue = custom\nTypeAdapter(dict[str, pydantic.JsonValue]).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        ("wildcard_import", f"from custom import *\n{_JSON_CALL}", ExpectedOutcome.NO_MATCH),
        ("encoder_lookalike", f"from custom import jsonable_encoder\n{_JSON_CALL}", ExpectedOutcome.NO_MATCH),
        ("json_value_lookalike", f"from custom import JsonValue\n{_JSON_CALL}", ExpectedOutcome.NO_MATCH),
        (
            "encoder_import_after_mutation",
            "import fastapi.encoders as enc\nenc.jsonable_encoder = custom\nfrom fastapi.encoders import jsonable_encoder as encode\nTypeAdapter(dict[str, JsonValue]).validate_python(encode({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "json_value_import_after_mutation",
            "import pydantic\npydantic.JsonValue = custom\nfrom pydantic import JsonValue as JSON\nTypeAdapter(dict[str, JSON]).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "dotted_encoder_namespace_mutation",
            "import fastapi.encoders\nimport fastapi.encoders as enc\nenc.jsonable_encoder = custom\nTypeAdapter(dict[str, JsonValue]).validate_python(fastapi.encoders.jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "encoder_module_escape",
            "import fastapi.encoders as enc\nborrow(enc)\nTypeAdapter(dict[str, JsonValue]).validate_python(enc.jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        ("encoder_function_mutation", f"jsonable_encoder.__code__ = custom\n{_JSON_CALL}", ExpectedOutcome.NO_MATCH),
        (
            "encoder_builtin_mutator",
            f"setattr(jsonable_encoder, '__code__', custom)\n{_JSON_CALL}",
            ExpectedOutcome.NO_MATCH,
        ),
        ("function_default", f"def response(content={_JSON_CALL}):\n    return content", ExpectedOutcome.NO_MATCH),
        (
            "class_header_shadow",
            f"class Owner:\n    TypeAdapter = custom\n    JsonValue = custom\n    jsonable_encoder = custom\n    def response(self, content={_JSON_CALL}):\n        return content",
            ExpectedOutcome.NO_MATCH,
        ),
        ("deferred_lambda", f"lambda: {_JSON_CALL}", ExpectedOutcome.NO_MATCH),
        ("comprehension", f"[item for item in {_JSON_CALL}]", ExpectedOutcome.NO_MATCH),
        (
            "starred_encoder_input",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder(*values))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "unpacked_encoder_options",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body}, **options))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "validation_error_context_argument",
            f"import pytest\nfrom pydantic import ValidationError\nwith pytest.raises(ValidationError, match={_JSON_CALL}):\n    pass",
            ExpectedOutcome.MATCH,
        ),
        (
            "validation_error_try_else",
            f"from pydantic import ValidationError\ntry:\n    read()\nexcept ValidationError:\n    recover()\nelse:\n    {_JSON_CALL}",
            ExpectedOutcome.MATCH,
        ),
        (
            "validation_error_try_finally",
            f"from pydantic import ValidationError\ntry:\n    read()\nexcept ValidationError:\n    recover()\nfinally:\n    {_JSON_CALL}",
            ExpectedOutcome.MATCH,
        ),
        (
            "validation_error_deferred_function",
            f"from pydantic import ValidationError\ntry:\n    def response():\n        return {_JSON_CALL}\nexcept ValidationError:\n    recover()",
            ExpectedOutcome.MATCH,
        ),
        ("wrong_suppression", f"{_JSON_CALL}  # sarj-noqa: SARJ479 — other rule", ExpectedOutcome.MATCH),
        ("malformed", "this is not valid Python (", ExpectedOutcome.NO_MATCH),
        (
            "json_type_module_alias",
            "import pydantic.types as types\nTypeAdapter(dict[str, types.JsonValue]).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "normalized_adapter_import",
            "from pydantic import ＴｙｐｅＡｄａｐｔｅｒ as Adapter\nAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "bytes_encoder_alias",
            "from builtins import bytes as Bytes\nTypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body}, custom_encoder={Bytes: decode}))",
            ExpectedOutcome.MATCH,
        ),
        (
            "root_mapping_encoder",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body}, custom_encoder={dict: lambda value: []}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "root_key_encoder",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body}, custom_encoder={str: len}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "opaque_encoder",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body}, custom_encoder=encoders))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "unpacked_custom_encoder",
            "TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body}, custom_encoder={bytes: decode, **extra}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "shadowed_bytes_encoder",
            "def response(bytes):\n    return TypeAdapter(dict[str, JsonValue]).validate_python(jsonable_encoder({'body': body}, custom_encoder={bytes: decode}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "cached_adapter_escape",
            "adapter = TypeAdapter(dict[str, JsonValue])\nborrow(adapter)\nadapter.validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "cached_adapter_mutation",
            "adapter = TypeAdapter(dict[str, JsonValue])\nadapter.__init__(Payload)\nadapter.validate_python(jsonable_encoder({'body': body}))",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "validation_error_test",
            f"import pytest\nfrom pydantic import ValidationError\nwith pytest.raises(ValidationError):\n    {_JSON_CALL}",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "validation_error_handler",
            f"from pydantic import ValidationError\ntry:\n    {_JSON_CALL}\nexcept ValidationError:\n    recover()",
            ExpectedOutcome.NO_MATCH,
        ),
        (
            "reasoned_suppression",
            f"{_JSON_CALL}  # sarj-noqa: SARJ480 — intentional recursive string-key validation",
            ExpectedOutcome.NO_MATCH,
        ),
    )
)


@pytest.mark.parametrize("case", JSON_OUTPUT_CASES, ids=tuple(case.case_id for case in JSON_OUTPUT_CASES))
def test_generic_json_output_validation(case: EvaluationCase) -> None:
    findings = _check(case.source, str(case.path))
    assert len(findings) == int(case.expected is ExpectedOutcome.MATCH)
    assert len({(finding.line, finding.col) for finding in findings}) == len(findings)
    assert all(finding.code == "SARJ480" and finding.severity.value == "warning" for finding in findings)


def test_outgoing_json_warning_preserves_structured_ingress_rule() -> None:
    source = (
        _JSON_IMPORTS
        + "import httpx\ndef read():\n    raw = httpx.get('https://example.test/data').json()\n    return raw['id']\ndef content(errors, body):\n    return "
        + _JSON_CALL
    )
    findings = _check(source) + RequirePydanticForExternalJson().check(Path("app/responses.py"), source)
    assert sorted((finding.code, finding.line) for finding in findings) == [("SARJ411", 6), ("SARJ480", 8)]


@pytest.mark.parametrize("path", ["app/generated/responses.py", "vendor/responses.py"])
def test_generated_json_output_is_excluded(path: str) -> None:
    assert _check(_JSON_IMPORTS + _JSON_CALL, path) == []


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
