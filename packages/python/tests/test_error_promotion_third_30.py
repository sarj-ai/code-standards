from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_rule_contracts import RuleId


_FULL_RULES = (
    "async-mock-call-without-await-assertion",
    "no-unused-copy-result",
    "no-test-method-grafting",
    "no-swallowed-asyncio-cancellation",
    "no-redundant-module-alias-exports",
)


@pytest.mark.parametrize("rule_id", _FULL_RULES)
def test_error_policy_blocks_and_allows_exact_exception(rule_id: RuleId, tmp_path: Path) -> None:
    rule = REGISTRY[rule_id]
    assert rule.documentation is not None
    assert rule.documentation.default_level is Severity.ERROR
    example = next(item for item in rule.public_examples() if item.expected_count)
    for item in example.files:
        path = tmp_path / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.source)
    focus = tmp_path / example.focus_path
    findings = analyze([rule_id], [focus])
    assert len(findings) == example.expected_count
    assert all(item.severity is Severity.ERROR for item in findings)
    assert analyze([rule_id], [focus]) == findings
    assert len({(item.line, item.col, item.code) for item in findings}) == len(findings)
    assert main(["check", "--rule", rule_id, str(focus)]) == 1
    baseline = tmp_path / "baseline.json"
    assert main(["check", "--rule", rule_id, "--update-baseline", str(baseline), str(focus)]) == 0
    assert rule.code in baseline.read_text()
    lines = focus.read_text().splitlines()
    for line in {item.line for item in findings}:
        lines[line - 1] += f"  # sarj-noqa: {rule.code} -- intentional compatibility contract"
    focus.write_text("\n".join(lines) + "\n")
    assert analyze([rule_id], [focus]) == []


@pytest.mark.parametrize(
    ("rule_id", "source", "expected"),
    [
        pytest.param(
            "no-swallowed-asyncio-cancellation",
            "import asyncio\nasync def worker(task):\n    try:\n        await task\n"
            "    except asyncio.CancelledError:\n        return None\n",
            Severity.WARNING,
            id="child-cancellation-is-not-caller-cancellation",
        ),
        pytest.param(
            "no-swallowed-asyncio-cancellation",
            "import asyncio\nasyncio.sleep = replacement\nasync def worker():\n    try:\n"
            "        await asyncio.sleep(10)\n    except asyncio.CancelledError:\n        return None\n",
            Severity.WARNING,
            id="mutated-sleep-is-not-canonical",
        ),
        pytest.param(
            "redundant-docstring",
            'def update_message(message_id: str):\n    """Update the message."""\n    return None\n',
            Severity.ERROR,
            id="ordered-name-restatement",
        ),
        pytest.param(
            "redundant-docstring",
            'def copy(left, right):\n    """right → left"""\n    left[:] = right\n',
            Severity.WARNING,
            id="direction-is-behavior",
        ),
        pytest.param(
            "redundant-docstring",
            'def copy_left_to_right(left, right):\n    """Copy right to left."""\n    left[:] = right\n',
            Severity.WARNING,
            id="word-order-is-behavior",
        ),
        pytest.param(
            "prefer-pydantic-json-value",
            "type _Json = str | int | float | bool | None | list[_Json] | dict[str, _Json]\n"
            "def _accept(value: _Json) -> None:\n    pass\n",
            Severity.ERROR,
            id="private-static-json-alias",
        ),
        pytest.param(
            "prefer-pydantic-json-value",
            "type PublicJson = str | int | float | bool | None | list[PublicJson] | dict[str, PublicJson]\n",
            Severity.WARNING,
            id="public-alias-contract",
        ),
        pytest.param(
            "prefer-pydantic-json-value",
            "from pydantic import TypeAdapter\n"
            "type _Json = str | int | float | bool | None | list[_Json] | dict[str, _Json]\n"
            "adapter = TypeAdapter(_Json)\n",
            Severity.WARNING,
            id="runtime-coercion-contract",
        ),
        pytest.param(
            "prefer-pydantic-json-value",
            "from pydantic import BaseModel\n"
            "type _Json = str | int | float | bool | None | list[_Json] | dict[str, _Json]\n"
            "class Payload(BaseModel):\n    value: _Json\n",
            Severity.WARNING,
            id="model-annotation-is-runtime-schema",
        ),
        pytest.param(
            "prefer-pydantic-json-value",
            "from pydantic import validate_call\n"
            "type _Json = str | int | float | bool | None | list[_Json] | dict[str, _Json]\n"
            "@validate_call\ndef _accept(value: _Json) -> None:\n    pass\n",
            Severity.WARNING,
            id="decorated-annotation-is-runtime-schema",
        ),
        pytest.param(
            "no-restated-closed-domain-description",
            "from typing import Literal\nfrom pydantic import BaseModel, Field\n"
            "class Payload(BaseModel):\n"
            "    mode: Literal['a', 'b'] = Field(description=\"Must be one of 'a', 'b'.\")\n",
            Severity.ERROR,
            id="inert-literal-domain",
        ),
        pytest.param(
            "no-restated-closed-domain-description",
            "from typing import Literal\nfrom pydantic import BaseModel, Field\n"
            "class Payload(BaseModel):\n"
            "    mode: Literal['a', 'b'] = Field(description=\"Must be one of 'a', 'b'.\", "
            "json_schema_extra=lambda schema: schema.pop('enum', None))\n",
            Severity.WARNING,
            id="callback-removes-enum",
        ),
        pytest.param(
            "no-restated-closed-domain-description",
            "from typing import Literal\nfrom pydantic import BaseModel, Field\n"
            "class Payload(BaseModel):\n"
            "    mode: Literal['a', 'b'] = Field(description=\"Must be one of 'a', 'b'.\", "
            "json_schema_extra={'enum': None})\n",
            Severity.WARNING,
            id="literal-schema-extra-overrides-enum",
        ),
    ],
)
def test_bounded_promotion_preserves_compatibility(
    rule_id: RuleId, source: str, expected: Severity, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'example'\nversion = '0.0.0'\ndependencies = ['pydantic>=2.5']\n"
    )
    path = tmp_path / "app.py"
    path.write_text(source)
    findings = analyze([rule_id], [path])
    assert len(findings) == 1
    assert findings[0].severity is expected
    assert analyze([rule_id], [path]) == findings
    assert main(["check", "--rule", rule_id, str(path)]) == (1 if expected is Severity.ERROR else 0)
    baseline = tmp_path / "baseline.json"
    assert main(["check", "--rule", rule_id, "--update-baseline", str(baseline), str(path)]) == 0
    assert (REGISTRY[rule_id].code in baseline.read_text()) is (expected is Severity.ERROR)


@pytest.mark.parametrize("requirement", ["pydantic>=2", "pydantic==2.4", "pydantic==2.4.1"])
def test_json_value_requires_a_supported_declared_floor(requirement: str, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f"[project]\nname = 'example'\nversion = '0.0.0'\ndependencies = ['{requirement}']\n"
    )
    path = tmp_path / "app.py"
    path.write_text(
        "type _Json = str | int | float | bool | None | list[_Json] | dict[str, _Json]\n"
        "def _accept(value: _Json) -> None:\n    pass\n"
    )
    findings = analyze(["prefer-pydantic-json-value"], [path])
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize(
    "mutation",
    [
        "setattr(asyncio, 'sleep', replacement)",
        "change(asyncio)",
        "asyncio.CancelledError = ValueError",
        "setattr(asyncio.sleep, '__code__', replacement.__code__)",
    ],
)
def test_visible_asyncio_provider_mutation_keeps_warning(mutation: str, tmp_path: Path) -> None:
    path = tmp_path / "worker.py"
    path.write_text(
        f"import asyncio\n{mutation}\nasync def worker():\n    try:\n        await asyncio.sleep(10)\n"
        "    except asyncio.CancelledError:\n        return None\n"
    )
    findings = analyze(["no-swallowed-asyncio-cancellation"], [path])
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize(
    "mutation",
    [
        "pydantic.Field = altered",
        "setattr(pydantic, 'Field', altered)",
        "change(pydantic)",
        "if condition:\n    from custom import Field",
    ],
)
def test_visible_schema_provider_mutation_keeps_warning(mutation: str, tmp_path: Path) -> None:
    path = tmp_path / "schema.py"
    path.write_text(
        "import pydantic\nfrom pydantic import BaseModel, Field\nfrom typing import Literal\n"
        f"{mutation}\nclass Payload(BaseModel):\n"
        "    mode: Literal['a', 'b'] = Field(description=\"Must be one of 'a', 'b'.\")\n"
    )
    findings = analyze(["no-restated-closed-domain-description"], [path])
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize("suppression_line", [0, 3])
def test_multiline_docstring_has_a_real_local_exception(suppression_line: int, tmp_path: Path) -> None:
    lines = ["def update_message():", '    """', "    Update the message.", '    """', "    return None"]
    lines[suppression_line] += "  # sarj-noqa: SARJ050 -- required public documentation"
    path = tmp_path / "service.py"
    path.write_text("\n".join(lines) + "\n")
    assert analyze(["redundant-docstring"], [path]) == []


@pytest.mark.parametrize(
    ("imports", "constructor"),
    [
        pytest.param(
            "import unittest.mock as mock\nsetattr(mock, 'AsyncMock', mock.Mock)\n",
            "mock.AsyncMock",
            id="setter-replaces-async-constructor",
        ),
        pytest.param(
            "import unittest.mock as mock\nmock.AsyncMock = mock.Mock\nfrom unittest.mock import AsyncMock\n",
            "AsyncMock",
            id="cross-alias-replaces-async-constructor",
        ),
    ],
)
def test_mutated_async_mock_provider_cannot_block(imports: str, constructor: str, tmp_path: Path) -> None:
    path = tmp_path / "test_worker.py"
    path.write_text(
        f"{imports}async def test_worker():\n    collaborator = {constructor}()\n    collaborator.assert_called_once()\n"
    )
    findings = analyze(["async-mock-call-without-await-assertion"], [path])
    assert all(item.severity is Severity.WARNING for item in findings)


@pytest.mark.parametrize("annotation", ["typing.Literal", "Literal"])
def test_mutated_literal_provider_cannot_block(annotation: str, tmp_path: Path) -> None:
    path = tmp_path / "schema.py"
    path.write_text(
        "import typing\nfrom pydantic import BaseModel, Field\n"
        "typing.Literal = altered\nfrom typing import Literal\nclass Payload(BaseModel):\n"
        f"    mode: {annotation}['a', 'b'] = Field(description=\"Must be one of 'a', 'b'.\")\n"
    )
    findings = analyze(["no-restated-closed-domain-description"], [path])
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


@pytest.mark.parametrize("escape", [False, True])
def test_v1_provider_alias_escape_retains_warning(*, escape: bool, tmp_path: Path) -> None:
    path = tmp_path / "schema.py"
    effect = "change(ModelAlias)\n" if escape else ""
    path.write_text(
        "from pydantic.v1 import BaseModel, Field\n"
        "from pydantic.v1 import BaseModel as ModelAlias\nfrom typing import Literal\n"
        f"{effect}class Payload(BaseModel):\n"
        "    mode: Literal['a', 'b'] = Field(description=\"Must be one of 'a', 'b'.\")\n"
    )
    findings = analyze(["no-restated-closed-domain-description"], [path])
    assert len(findings) == 1
    assert findings[0].severity is (Severity.WARNING if escape else Severity.ERROR)
