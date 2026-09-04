from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.require_pydantic_for_external_json import (
    RequirePydanticForExternalJson,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "protocol.py"):
    return RequirePydanticForExternalJson().check(Path(path), dedent(source))


_PUBLIC_EXAMPLES = RequirePydanticForExternalJson.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(RequirePydanticForExternalJson().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        "import json, os\ndef parse():\n raw=json.loads(os.environ['REPORT'])\n return raw.get('id')",
        "import json, os\ndef parse():\n raw=json.loads(os.environ['REPORT'])\n return raw['id']",
        "import json as j, os\ndef parse():\n raw=j.loads(os.environ['REPORT'])\n return raw.get('id')",
        "from json import loads as decode\nfrom os import environ\ndef parse():\n raw=decode(environ['REPORT'])\n return raw['id']",
        "import orjson, os\ndef parse():\n raw=orjson.loads(os.environ['REPORT'])\n return raw['id']",
        "import ujson as codec, os\ndef parse():\n raw=codec.loads(os.environ['REPORT'])\n return raw.get('id')",
        "import json, os\ndef parse():\n raw=json.loads(os.environ['REPORT'])\n alias=raw\n return alias['id']",
        "import json, os\ndef parse():\n raw: object=json.loads(os.environ['REPORT'])\n return raw['id']",
        "import json, os\ndef parse():\n raw=cast(dict[str, object], json.loads(os.environ['REPORT']))\n return raw['id']",
        "import json, subprocess\ndef parse():\n done=subprocess.run(['tool'], capture_output=True, text=True)\n raw=json.loads(done.stdout)\n return raw['ok']",
        "import json, os\ndef parse():\n raw=json.loads(os.environ['REPORT'])\n return raw['ok']",
        "import httpx\ndef parse():\n raw=httpx.get('https://example.test').json()\n return raw.get('id')",
        "import httpx\ndef parse(response: httpx.Response):\n raw=response.json()\n return raw['id']",
        "import json, os\ndef parse():\n raw=json.loads(os.environ['REPORT'])\n assert isinstance(raw, dict)\n return raw['id']",
        "import json, os\ndef parse():\n raw=json.loads(os.environ['REPORT'])\n value=raw['id']\n Report.model_validate(raw)\n return value",
    ],
)
def test_flags_external_json_fixed_field_access(source: str) -> None:
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.WARNING


def test_flags_original_react_doctor_helper_chain_once() -> None:
    diagnostics = _check("""
        import json

        def _loads(payload: str) -> object:
            if not payload.strip():
                raise ValueError
            return json.loads(payload)

        def _table(value: object, label: str) -> dict[str, object]:
            if not isinstance(value, dict):
                raise TypeError(label)
            return {str(key): item for key, item in value.items()}

        import os

        def parse_react_doctor():
            report = _table(_loads(os.environ["REPORT"]), "React Doctor report")
            if report.get("schemaVersion") != 3:
                raise ValueError
            if report.get("ok") is not True:
                raise ValueError
            return report.get("projects")
    """)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 18


def test_flags_structural_record_helper_call() -> None:
    diagnostics = _check("""
        import json
        def field(table: object, key: str):
            return table.get(key)
        import os
        def parse():
            raw = json.loads(os.environ["REPORT"])
            return field(raw, "id")
    """)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 8


@pytest.mark.parametrize(
    "source",
    [
        "def parse(payload):\n return Report.model_validate_json(payload)",
        "def parse(payload):\n return TypeAdapter(Report).validate_json(payload)",
        "import json\ndef parse(payload):\n return Report.model_validate(json.loads(payload))",
        "import json\ndef parse(payload):\n return TypeAdapter(Report).validate_python(json.loads(payload))",
        "from json import loads\nfrom pydantic import parse_obj_as\ndef parse(payload):\n return parse_obj_as(Report, loads(payload))",
        "import json\ndef parse(payload):\n raw=json.loads(payload)\n report=Report.model_validate(raw)\n return report.id",
        "import json\ndef parse(payload):\n raw=json.loads(payload)\n return Report.parse_obj(raw)",
        "import json\ndef parse(payload):\n raw=json.loads('{\"id\": 1}')\n return raw['id']",
        "import json\nfrom pathlib import Path\ndef parse(path):\n raw=json.loads(Path(path).read_text())\n return raw['id']",
        "import json\ndef parse(handle):\n raw=json.load(handle)\n return raw['id']",
        "import json\ndef parse(payload):\n raw=json.loads(payload)\n return raw.get(key)",
        "import json\ndef parse(payload):\n raw=json.loads(payload)\n return raw",
        "def parse(table):\n return table.get('id')",
        "import json\ndef parse(payload):\n raw=json.loads(payload)",
        "import httpx, json\ndef send(request: httpx.Request):\n body=json.loads(request.content)\n return body.get('tools')",
    ],
)
def test_accepts_non_record_or_validated_json_use(source: str) -> None:
    assert _check(source) == []


def test_accepts_parameter_proven_local_at_every_module_callsite() -> None:
    assert (
        _check("""
        import json
        from pathlib import Path

        def merge_document(text: str):
            document = json.loads(text)
            return document.get("dependencies")

        def load(path: Path):
            return merge_document(path.read_text())
    """)
        == []
    )


@pytest.mark.parametrize("path", ["test_protocol.py", "tests/protocol.py", "testing/protocol.py", "docs/protocol.py"])
def test_excludes_non_production_paths(path: str) -> None:
    assert _check("import json\ndef parse(payload):\n return json.loads(payload)['id']", path) == []


def test_excludes_generated_and_malformed_files() -> None:
    assert _check("# @generated\nimport json\ndef parse(payload):\n return json.loads(payload)['id']") == []
    assert _check("import json\ndef parse(payload):\n if (") == []


def test_does_not_follow_rebound_decoder_import() -> None:
    assert (
        _check("""
        from json import loads
        loads = custom_decoder
        def parse(payload):
            raw = loads(payload)
            return raw['id']
    """)
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        """
        import httpx
        def request() -> httpx.Response: ...
        def load():
            response = request()
            return response.json()["id"]
        """,
        """
        import httpx
        class Client:
            async def _request(self) -> httpx.Response: ...
            async def load(self):
                response = await self._request()
                return response.json().get("id")
        """,
        """
        import httpx
        async def load(client: httpx.AsyncClient):
            response = await client.get("https://example.test")
            return response.json()["id"]
        """,
        """
        import httpx
        class DAO:
            def __init__(self, client: httpx.AsyncClient) -> None:
                self.client = client
            async def load(self):
                response = await self.client.get("/items")
                return response.json()["id"]
        """,
    ],
)
def test_flags_json_from_typed_http_response_helpers(source: str) -> None:
    diagnostics = _check(source)
    assert len(diagnostics) == 1


def test_arbitrary_local_json_method_is_not_treated_as_http() -> None:
    assert (
        _check("""
        class Document:
            def json(self) -> dict[str, object]: ...
        def load(document: Document):
            return document.json()["id"]
    """)
        == []
    )


def test_ambiguous_same_named_helper_is_not_treated_as_http() -> None:
    assert (
        _check("""
        import httpx
        class Remote:
            def request(self) -> httpx.Response: ...
        class Local:
            def request(self) -> object: ...
        def load(client: Local):
            response = client.request()
            return response.json()["id"]
    """)
        == []
    )


def test_unrelated_receiver_method_is_not_treated_as_typed_http_helper() -> None:
    assert (
        _check("""
        import httpx
        class Remote:
            def request(self) -> httpx.Response: ...
        class Local: ...
        def load(client: Local):
            response = client.request()
            return response.json()["id"]
    """)
        == []
    )


def test_unrelated_owner_attribute_is_not_treated_as_typed_http_client() -> None:
    assert (
        _check("""
        import httpx
        class Remote:
            def __init__(self, client: httpx.AsyncClient) -> None:
                self.client = client
        class Local:
            async def load(self):
                response = await self.client.get("/items")
                return response.json()["id"]
    """)
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        "import json\ndef parse(payload):\n raw=json.loads(payload)\n return raw['id']",
        "import json\ndef bundled(): return '{\"id\": 1}'\ndef parse():\n raw=json.loads(bundled())\n return raw['id']",
        "import json\ndef parse(template):\n raw=json.loads(template.text)\n return raw['id']",
        "import json\ndef parse(value={'id': 1}):\n raw=json.loads(json.dumps(value))\n return raw['id']",
    ],
    ids=["unknown-parameter", "local-factory", "arbitrary-text", "internal-round-trip"],
)
def test_unproven_external_sources_are_ignored(source: str) -> None:
    assert _check(source) == []


def test_jsonschema_validation_before_access_is_accepted() -> None:
    assert (
        _check("""
        import json
        import jsonschema
        import os
        raw = None
        def parse():
            raw = json.loads(os.environ["REPORT"])
            jsonschema.validate(raw, SCHEMA)
            return raw["id"]
        """)
        == []
    )


def test_keyword_jsonschema_validation_before_access_is_accepted() -> None:
    assert (
        _check("""
        import httpx
        import jsonschema
        def parse():
            raw = httpx.get("https://example.test").json()
            jsonschema.validate(instance=raw, schema=SCHEMA)
            return raw["id"]
        """)
        == []
    )


def test_jsonschema_validation_through_a_simple_alias_is_accepted() -> None:
    assert (
        _check("""
        import httpx
        import jsonschema
        def parse():
            raw = httpx.get("https://example.test").json()
            alias = raw
            jsonschema.validate(alias, SCHEMA)
            return raw["id"]
        """)
        == []
    )


def test_jsonschema_validation_propagates_to_a_later_annotated_alias() -> None:
    assert (
        _check("""
        import httpx
        import jsonschema
        def parse():
            raw = httpx.get("https://example.test").json()
            jsonschema.validate(raw, SCHEMA)
            alias: object = raw
            return alias["id"]
        """)
        == []
    )


@pytest.mark.parametrize("guard", ["if False", "if enabled"], ids=["dead", "conditional"])
def test_non_guaranteed_validation_does_not_suppress(guard: str) -> None:
    diagnostics = _check(f"""
        import httpx
        import jsonschema
        def parse():
            raw = httpx.get("https://example.test").json()
            {guard}:
                jsonschema.validate(raw, SCHEMA)
            return raw["id"]
    """)
    assert len(diagnostics) == 1


def test_unrelated_model_validate_method_does_not_suppress_raw_access() -> None:
    diagnostics = _check("""
        import httpx
        def parse():
            raw = httpx.get("https://example.test").json()
            audit.model_validate(raw)
            return raw["id"]
    """)
    assert len(diagnostics) == 1


def test_marshmallow_load_result_is_accepted() -> None:
    assert (
        _check("""
        import httpx
        from marshmallow import Schema
        def parse():
            raw = httpx.get("https://example.test").json()
            report = Schema().load(raw)
            return report["id"]
        """)
        == []
    )


def test_arbitrary_capitalized_unpack_does_not_masquerade_as_validation() -> None:
    diagnostics = _check("""
        import httpx
        def parse():
            raw = httpx.get("https://example.test").json()
            record = Record(**raw)
            return record["id"]
    """)
    assert len(diagnostics) == 1


def test_manual_field_constructor_access_still_requires_boundary_validation() -> None:
    diagnostics = _check("""
        import httpx
        def parse():
            raw = httpx.get("https://example.test").json()
            return Report(id=raw["id"])
    """)
    assert len(diagnostics) == 1


def test_module_helper_rebinding_does_not_reuse_the_helper_summary() -> None:
    assert (
        _check("""
        import httpx
        def consume(record):
            return record["id"]
        def parse():
            consume = print
            consume(httpx.get("https://example.test").json())
        """)
        == []
    )


def test_exact_suppression_is_honored() -> None:
    assert (
        _check("""
        import httpx
        def parse():
            raw = httpx.get("https://example.test").json()
            return raw["id"]  # sarj-noqa: SARJ411
        """)
        == []
    )


def test_unrelated_suppression_does_not_hide_the_warning() -> None:
    diagnostics = _check("""
        import httpx
        def parse():
            raw = httpx.get("https://example.test").json()
            return raw["id"]  # sarj-noqa: SARJ412
    """)
    assert len(diagnostics) == 1


def test_message_covers_already_decoded_json() -> None:
    diagnostic = _check("""
        import httpx
        def parse():
            return httpx.get("https://example.test").json()["id"]
    """)[0]
    assert "model_validate" in diagnostic.message
    documentation = RequirePydanticForExternalJson.documentation
    assert documentation is not None
    assert "validate_python" in documentation.remediation


def test_direct_subprocess_output_is_proven_external() -> None:
    diagnostics = _check("""
        import json
        import subprocess
        def parse():
            raw = json.loads(subprocess.check_output(["tool"]))
            return raw["id"]
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "expression",
    [
        'subprocess.check_output(["tool"]).decode()',
        'subprocess.run(["tool"], capture_output=True, text=True).stdout',
    ],
    ids=["decoded-check-output", "direct-run-stdout"],
)
def test_direct_subprocess_text_forms_are_proven_external(expression: str) -> None:
    diagnostics = _check(f"""
        import json
        import subprocess
        def parse():
            raw = json.loads({expression})
            return raw["id"]
    """)
    assert len(diagnostics) == 1


def test_assigned_subprocess_stdout_decode_is_proven_external() -> None:
    diagnostics = _check("""
        import json
        import subprocess
        def parse():
            done = subprocess.run(["tool"], capture_output=True)
            raw = json.loads(done.stdout.decode())
            return raw["id"]
    """)
    assert len(diagnostics) == 1


def test_popen_stdout_handle_is_not_assumed_to_be_json_text() -> None:
    assert (
        _check("""
        import json
        import subprocess
        def parse():
            process = subprocess.Popen(["tool"], stdout=subprocess.PIPE)
            raw = json.loads(process.stdout)
            return raw["id"]
        """)
        == []
    )


def test_simple_http_response_alias_is_followed() -> None:
    diagnostics = _check("""
        import httpx
        def parse():
            response = httpx.get("https://example.test")
            alias = response
            return alias.json()["id"]
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\ndef parse():\n response=httpx.get('https://example.test')\n response=Local()\n return response.json()['id']",
        "import httpx\ndef parse():\n response=httpx.get('https://example.test')\n alias=response\n alias=Local()\n return alias.json()['id']",
        "import httpx\ndef parse(response: httpx.Response):\n response=Local()\n return response.json()['id']",
        "import httpx\ndef parse(client: httpx.Client):\n client=Local()\n response=client.get('/')\n return response.json()['id']",
    ],
    ids=["response", "alias", "typed-response", "typed-client"],
)
def test_reassigned_http_names_do_not_retain_external_provenance(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\ndef request() -> httpx.Response: ...\nrequest=lambda: Local()\ndef parse():\n return request().json()['id']",
        "import json, os\ndef decode(value): return json.loads(value)\ndecode=lambda value: {}\ndef parse():\n return decode(os.environ['REPORT'])['id']",
        "import httpx\ndef consume(record): return record['id']\nconsume=print\ndef parse():\n consume(httpx.get('https://example.test').json())",
    ],
    ids=["response-helper", "decoder-helper", "consumer-helper"],
)
def test_module_level_helper_rebinding_invalidates_summaries(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\ndef request() -> httpx.Response: ...\ndef parse(request):\n response=request()\n return response.json()['id']",
        "import json, os\ndef decode(value): return json.loads(value)\ndef parse(decode):\n return decode(os.environ['REPORT'])['id']",
        "import httpx\ndef request() -> httpx.Response: ...\ndef parse():\n def request(): return Local()\n return request().json()['id']",
    ],
    ids=["response-parameter", "decoder-parameter", "nested-helper"],
)
def test_function_local_helper_shadowing_invalidates_module_summaries(source: str) -> None:
    assert _check(source) == []


def test_class_body_rebinding_invalidates_response_method_summary() -> None:
    assert (
        _check("""
        import httpx
        class Client:
            def request(self) -> httpx.Response: ...
            request = lambda self: Local()
            def parse(self):
                return self.request().json()["id"]
        """)
        == []
    )


@pytest.mark.parametrize(
    "expression",
    ["FakeSchema().load(raw)", "audit.model_validate(raw)"],
    ids=["fake-schema", "method-name-lookalike"],
)
def test_unproven_validator_names_do_not_hide_external_origins(expression: str) -> None:
    diagnostics = _check(f"""
        import httpx
        def parse():
            raw = httpx.get("https://example.test").json()
            result = {expression}
            return result["id"]
    """)
    assert len(diagnostics) == 1


def test_local_marshmallow_schema_subclass_is_recognized() -> None:
    assert (
        _check("""
        import httpx
        from marshmallow import Schema
        class ReportSchema(Schema): ...
        def parse():
            raw = httpx.get("https://example.test").json()
            report = ReportSchema().load(raw)
            return report["id"]
        """)
        == []
    )


@pytest.mark.parametrize(
    "setup",
    [
        "def parse(validator: Validator):",
        "def parse():\n    validator = jsonschema.Draft202012Validator(SCHEMA)",
    ],
    ids=["protocol", "draft-instance"],
)
def test_jsonschema_validator_instance_dominates_access(setup: str) -> None:
    assert (
        _check(f"""
        import httpx
        import jsonschema
        from jsonschema.protocols import Validator
        {setup}
            raw = httpx.get("https://example.test").json()
            validator.validate(raw)
            return raw["id"]
        """)
        == []
    )


def test_same_line_validation_dominates_later_access() -> None:
    assert (
        _check("""
        import httpx, jsonschema
        def parse():
            raw = httpx.get("https://example.test").json(); jsonschema.validate(raw, {}); return raw["id"]
        """)
        == []
    )


def test_same_line_validation_does_not_hide_earlier_access() -> None:
    diagnostics = _check("""
        import httpx, jsonschema
        def parse():
            raw = httpx.get("https://example.test").json(); value = raw["id"]; jsonschema.validate(raw, {}); return value
    """)
    assert len(diagnostics) == 1


def test_validation_through_alias_covers_existing_and_later_aliases() -> None:
    assert (
        _check("""
        import httpx, jsonschema
        def parse():
            raw = httpx.get("https://example.test").json()
            alias = raw
            jsonschema.validate(alias, {})
            later = raw
            return raw["id"], alias["id"], later["id"]
        """)
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\nfrom jsonschema.protocols import Validator\ndef parse(validator: Validator):\n validator=Fake()\n raw=httpx.get('https://example.test').json()\n validator.validate(raw)\n return raw['id']",
        "import httpx, jsonschema\ndef parse():\n validator=jsonschema.Draft202012Validator({})\n validator=Fake()\n raw=httpx.get('https://example.test').json()\n validator.validate(raw)\n return raw['id']",
    ],
    ids=["reassigned-protocol", "reassigned-draft-instance"],
)
def test_reassigned_jsonschema_validator_does_not_hide_access(source: str) -> None:
    diagnostics = _check(source)
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "rebind",
    ["ReportSchema = Fake", "from fake import ReportSchema"],
    ids=["assignment", "import"],
)
def test_rebound_marshmallow_schema_does_not_hide_access(rebind: str) -> None:
    diagnostics = _check(f"""
        import httpx
        from marshmallow import Schema
        class ReportSchema(Schema): ...
        {rebind}
        def parse():
            raw = httpx.get("https://example.test").json()
            report = ReportSchema().load(raw)
            return report["id"]
    """)
    assert len(diagnostics) == 1


def test_function_local_marshmallow_shadow_does_not_hide_access() -> None:
    diagnostics = _check("""
        import httpx
        from marshmallow import Schema
        class ReportSchema(Schema): ...
        def parse():
            ReportSchema = Fake
            raw = httpx.get("https://example.test").json()
            report = ReportSchema().load(raw)
            return report["id"]
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\nfrom pydantic import TypeAdapter\nADAPTER=TypeAdapter(dict[str,str])\ndef parse():\n raw=httpx.get('https://example.test').json()\n report=ADAPTER.validate_python(raw)\n return report['id']",
        "import httpx\nfrom pydantic import TypeAdapter\ndef parse():\n adapter=TypeAdapter(dict[str,str])\n raw=httpx.get('https://example.test').json()\n report=adapter.validate_python(raw)\n return report['id']",
        "import httpx\nfrom pydantic import TypeAdapter\nADAPTER=TypeAdapter(dict[str,str])\ndef parse():\n adapter=ADAPTER\n raw=httpx.get('https://example.test').json()\n report=adapter.validate_python(raw)\n return report['id']",
        "import httpx\nfrom pydantic import TypeAdapter\nADAPTER: TypeAdapter[dict[str,str]]=TypeAdapter(dict[str,str])\ndef parse():\n raw=httpx.get('https://example.test').json()\n report=ADAPTER.validate_python(raw)\n return report['id']",
    ],
    ids=["module", "function", "module-alias", "annotated-module"],
)
def test_bound_type_adapter_validates_result(source: str) -> None:
    assert _check(source) == []


def test_model_validate_result_is_not_treated_as_raw_json() -> None:
    assert (
        _check("""
        import httpx
        from pydantic import BaseModel
        class Report(BaseModel):
            data: dict[str, str]
        def parse():
            raw = httpx.get("https://example.test").json()
            report = Report.model_validate(raw)
            return report.data["id"]
        """)
        == []
    )


def test_model_validate_lookalike_does_not_hide_external_origin() -> None:
    diagnostics = _check("""
        import httpx
        class Audit:
            @classmethod
            def model_validate(cls, value): return value
        def parse():
            raw = httpx.get("https://example.test").json()
            report = Audit.model_validate(raw)
            return report["id"]
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\nfrom pydantic import BaseModel\nclass Report(BaseModel):\n @classmethod\n def model_validate(cls,value): return value\ndef parse():\n raw=httpx.get('https://example.test').json()\n report=Report.model_validate(raw)\n return report['id']",
        "import httpx\nfrom pydantic import BaseModel\ndef replace(cls): return Audit\n@replace\nclass Report(BaseModel): ...\ndef parse():\n raw=httpx.get('https://example.test').json()\n report=Report.model_validate(raw)\n return report['id']",
    ],
    ids=["method-override", "class-decorator"],
)
def test_unproven_pydantic_class_transform_does_not_hide_origin(source: str) -> None:
    diagnostics = _check(source)
    assert len(diagnostics) == 1


def test_pydantic_model_alias_validates_result() -> None:
    assert (
        _check("""
        import httpx
        from pydantic import BaseModel
        class Report(BaseModel):
            data: dict[str, str]
        ReportAlias = Report
        def parse():
            raw = httpx.get("https://example.test").json()
            report = ReportAlias.model_validate(raw)
            return report.data["id"]
        """)
        == []
    )


@pytest.mark.parametrize(
    "binding",
    [
        "VALIDATOR=jsonschema.Draft202012Validator({})",
        "VALIDATOR: jsonschema.protocols.Validator=jsonschema.Draft202012Validator({})",
    ],
    ids=["assignment", "annotated-assignment"],
)
def test_module_jsonschema_validator_dominates_access(binding: str) -> None:
    assert (
        _check(f"""
        import httpx, jsonschema
        {binding}
        def parse():
            raw = httpx.get("https://example.test").json()
            VALIDATOR.validate(raw)
            return raw["id"]
        """)
        == []
    )


def test_aliased_jsonschema_constructor_dominates_access() -> None:
    assert (
        _check("""
        import httpx
        from jsonschema import Draft202012Validator as V
        VALIDATOR = V({})
        def unrelated():
            VALIDATOR = object()
        def parse():
            raw = httpx.get("https://example.test").json()
            VALIDATOR.validate(raw)
            return raw["id"]
        """)
        == []
    )


def test_parameter_shadowing_invalidates_module_validator() -> None:
    diagnostics = _check("""
        import httpx, jsonschema
        VALIDATOR = jsonschema.Draft202012Validator({})
        def parse(VALIDATOR):
            raw = httpx.get("https://example.test").json()
            VALIDATOR.validate(raw)
            return raw["id"]
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "source",
    [
        "import httpx,jsonschema\nVALIDATOR=jsonschema.Draft202012Validator({})\ndef unrelated(value=(VALIDATOR := Fake())): ...\ndef parse():\n raw=httpx.get('https://example.test').json()\n VALIDATOR.validate(raw)\n return raw['id']",
        "import httpx,jsonschema\nVALIDATOR=jsonschema.Draft202012Validator({})\n@((VALIDATOR := FakeDecorator()))\ndef unrelated(): ...\ndef parse():\n raw=httpx.get('https://example.test').json()\n VALIDATOR.validate(raw)\n return raw['id']",
    ],
    ids=["default-walrus", "decorator-walrus"],
)
def test_definition_header_rebinding_invalidates_module_validator(source: str) -> None:
    diagnostics = _check(source)
    assert len(diagnostics) == 1


def test_overridden_marshmallow_load_does_not_hide_origin() -> None:
    diagnostics = _check("""
        import httpx
        from marshmallow import Schema
        class ReportSchema(Schema):
            def load(self, value): return value
        def parse():
            raw = httpx.get("https://example.test").json()
            report = ReportSchema().load(raw)
            return report["id"]
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize("scope", ["module", "function"])
def test_bound_marshmallow_schema_validates_result(scope: str) -> None:
    if scope == "module":
        source = "from marshmallow import Schema\nimport httpx\nSCHEMA=Schema()\ndef parse():\n raw=httpx.get('https://example.test').json()\n report=SCHEMA.load(raw)\n return report['id']"
    else:
        source = "from marshmallow import Schema\nimport httpx\ndef parse():\n schema=Schema()\n raw=httpx.get('https://example.test').json()\n report=schema.load(raw)\n return report['id']"
    assert _check(source) == []


@pytest.mark.parametrize("method", ["items", "keys", "values"])
def test_open_record_iteration_is_out_of_scope(method: str) -> None:
    assert (
        _check(f"""
        import httpx
        def parse():
            raw = httpx.get("https://example.test").json()
            return raw.{method}()
        """)
        == []
    )


def test_rule_metadata_preserves_the_stable_selector() -> None:
    rule = RequirePydanticForExternalJson()
    assert rule.id == "require-pydantic-for-external-json"
    assert rule.code == "SARJ411"
    assert rule.documentation is not None
    assert rule.documentation.aliases == ()
