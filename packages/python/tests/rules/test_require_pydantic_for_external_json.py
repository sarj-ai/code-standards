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
        "import json\ndef parse(payload):\n raw=json.loads(payload)\n return raw.get('id')",
        "import json\ndef parse(payload):\n raw=json.loads(payload)\n return raw['id']",
        "import json as j\ndef parse(payload):\n raw=j.loads(payload)\n return raw.get('id')",
        "from json import loads as decode\ndef parse(payload):\n raw=decode(payload)\n return raw['id']",
        "import orjson\ndef parse(payload):\n raw=orjson.loads(payload)\n return raw['id']",
        "import ujson as codec\ndef parse(payload):\n raw=codec.loads(payload)\n return raw.get('id')",
        "import json\ndef parse(payload):\n raw=json.loads(payload)\n alias=raw\n return alias['id']",
        "import json\ndef parse(payload):\n raw: object=json.loads(payload)\n return raw['id']",
        "import json\ndef parse(payload):\n raw=cast(dict[str, object], json.loads(payload))\n return raw['id']",
        "import json\ndef parse(done):\n raw=json.loads(done.stdout)\n return raw['ok']",
        "import json, os\ndef parse():\n raw=json.loads(os.environ['REPORT'])\n return raw['ok']",
        "import json\nasync def parse(payload):\n raw=json.loads(payload)\n return raw.get('id')",
        "import json\ndef parse(payload):\n raw=json.loads(payload)\n assert isinstance(raw, dict)\n return raw['id']",
        "import json\ndef parse(payload):\n raw=json.loads(payload)\n value=raw['id']\n Report.model_validate(raw)\n return value",
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

        def parse_react_doctor(payload: str):
            report = _table(_loads(payload), "React Doctor report")
            if report.get("schemaVersion") != 3:
                raise ValueError
            if report.get("ok") is not True:
                raise ValueError
            return report.get("projects")
    """)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 15


def test_flags_structural_record_helper_call() -> None:
    diagnostics = _check("""
        import json
        def field(table: object, key: str):
            return table.get(key)
        def parse(payload: str):
            raw = json.loads(payload)
            return field(raw, "id")
    """)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 7


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
