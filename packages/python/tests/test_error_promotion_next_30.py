from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_rule_contracts import RuleId


_PROMOTED_RULES = (
    "no-broad-keyword-capture",
    "no-shallow-container-type-guard",
    "no-input-model-mutation",
    "no-mocked-pydantic-value-object",
    "require-public-dependency-contract",
    "shared-mutable-pydantic-factory",
    "require-pydantic-ordinal-lower-bound",
    "require-pydantic-for-external-json",
    "require-explicit-service-contract",
    "no-fixed-sleep-in-loop",
    "require-injectable-retry-sleep",
    "prefer-pytest-fixture-injection",
    "repeated-unimplemented-test-contract",
    "no-docstring-type-restatement",
    "prefer-module-level-constant",
    "prefer-regex-fullmatch",
)


@pytest.mark.parametrize("rule_id", _PROMOTED_RULES)
def test_promoted_example_blocks_and_supports_exact_local_exception(rule_id: RuleId, tmp_path: Path) -> None:
    rule = REGISTRY[rule_id]
    documentation = rule.documentation
    assert documentation is not None
    assert documentation.default_level is Severity.ERROR
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    example = next(example for example in rule.public_examples() if example.expected_count)
    for file in example.files:
        target = tmp_path / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.source)
    focus = tmp_path / example.focus_path
    findings = analyze([rule_id], [focus])
    assert len(findings) == example.expected_count
    assert all(finding.severity is Severity.ERROR for finding in findings)
    assert len({(finding.path, finding.line, finding.col) for finding in findings}) == len(findings)
    assert analyze([rule_id], [focus]) == findings
    assert main(["check", "--rule", rule_id, str(focus)]) == 1
    baseline = tmp_path / "baseline.json"
    assert main(["check", "--rule", rule_id, "--update-baseline", str(baseline), str(focus)]) == 0
    assert json.loads(baseline.read_text())
    lines = focus.read_text().splitlines()
    suppressed_lines = {1} if rule_id == "no-docstring-type-restatement" else {finding.line for finding in findings}
    for line in suppressed_lines:
        lines[line - 1] += f"  # sarj-noqa: {rule.code} -- required compatibility boundary"
    focus.write_text("\n".join(lines) + "\n")
    assert analyze([rule_id], [focus]) == []
    assert main(["check", "--rule", rule_id, str(focus)]) == 0


def test_regex_hoisting_remains_warning_and_nonblocking(tmp_path: Path) -> None:
    path = tmp_path / "matcher.py"
    path.write_text(
        "import re\ndef find(value: str):\n    pattern = re.compile('word')\n    return pattern.search(value)\n"
    )
    findings = analyze(["prefer-module-level-constant"], [path])
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert main(["check", "--rule", "prefer-module-level-constant", str(path)]) == 0
    baseline = tmp_path / "baseline.json"
    assert main(["check", "--rule", "prefer-module-level-constant", "--update-baseline", str(baseline), str(path)]) == 0
    assert json.loads(baseline.read_text()) == {}


@pytest.mark.parametrize(
    ("rule_id", "source"),
    [
        pytest.param(
            "no-broad-keyword-capture",
            "from typing import Any, override\nfrom pydantic import BaseModel\nclass Record(BaseModel):\n"
            "    value: int\n    @override\n    def __init__(self, **data: Any):\n        super().__init__(**data)\n",
            id="pydantic-open-constructor",
        ),
        pytest.param(
            "no-broad-keyword-capture",
            "from typing import override\nclass Adapter(Base):\n    @override\n"
            "    def forward(self, **data: object):\n        return super().forward(**data)\n",
            id="inherited-open-method",
        ),
        pytest.param(
            "require-pydantic-ordinal-lower-bound",
            "from typing import ClassVar\nfrom pydantic import BaseModel, Field\n"
            "class Record(BaseModel):\n    hook: ClassVar[object] = Descriptor()\n"
            "    page_number: int = Field(default=1, description='1 for the first page')\n",
            id="descriptor-can-set-ordinal-bound",
        ),
        pytest.param(
            "require-pydantic-ordinal-lower-bound",
            "from pydantic import BaseModel, Field\n@configure\nclass Record(BaseModel):\n"
            "    page_number: int = Field(default=1, description='1 for the first page')\n",
            id="decorator-can-set-ordinal-bound",
        ),
        pytest.param(
            "no-nullable-dependency-fallback",
            "def create(factory=None):\n    if factory is None:\n        factory = fresh_factory()\n    return factory()\n",
            id="none-preserves-lazy-per-call-factory",
        ),
        pytest.param(
            "shared-mutable-pydantic-factory",
            "from typing import ClassVar\nfrom pydantic import BaseModel, Field\nSHARED = []\n"
            "class Record(BaseModel):\n    hook: ClassVar[object] = Descriptor()\n"
            "    items: list[int] = Field(default_factory=lambda: SHARED)\n",
            id="descriptor-can-replace-shared-factory",
        ),
        pytest.param(
            "shared-mutable-pydantic-factory",
            "from pydantic import BaseModel, Field\nSHARED = []\n"
            "def fresh(field):\n    field.default_factory = list\n    field._attributes_set['default_factory'] = list\n    return 'fresh'\n"
            "class Record(BaseModel):\n    items: list[int] = Field(default_factory=lambda: SHARED)\n"
            "    marker: int = Field(default=0, description=fresh(items))\n",
            id="field-option-can-replace-shared-factory",
        ),
        pytest.param(
            "prefer-module-level-constant",
            "import sys\ndef capture():\n    return sys._getframe(1).f_locals\n"
            "def lookup(key):\n    allowed = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']\n"
            "    capture()\n    return key in allowed\n",
            id="hoisting-changes-observed-frame-locals",
        ),
    ],
)
def test_compatibility_tiers_stay_warning_and_outside_blocking_baseline(
    rule_id: RuleId, source: str, tmp_path: Path
) -> None:
    path = tmp_path / "boundary.py"
    path.write_text(source)
    findings = analyze([rule_id], [path])
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert main(["check", "--rule", rule_id, str(path)]) == 0
    baseline = tmp_path / "baseline.json"
    assert main(["check", "--rule", rule_id, "--update-baseline", str(baseline), str(path)]) == 0
    assert json.loads(baseline.read_text()) == {}


@pytest.mark.parametrize(
    "access",
    [
        "__builtins__['isinstance'] = checks_contents",
        "providers = __builtins__",
        "globals()['isinstance'] = checks_contents",
    ],
)
def test_mapping_backed_builtin_replacement_does_not_claim_a_shallow_guard(access: str, tmp_path: Path) -> None:
    path = tmp_path / "boundary.py"
    path.write_text(
        "from typing import TypeGuard\n" + access + "\n"
        "def is_record(value: object) -> TypeGuard[dict[str, object]]:\n    return isinstance(value, dict)\n"
    )
    assert analyze(["no-shallow-container-type-guard"], [path]) == []


@pytest.mark.parametrize("marker", ["header", "closing", "inside", "unrelated-code"])
def test_docstring_exception_requires_a_genuine_matching_comment(marker: str, tmp_path: Path) -> None:
    source = (
        'def decode(value: str) -> str:\n    """Decode wire data.\n\n    Args:\n'
        '        value (str): Preserve required compatibility metadata.\n    """\n    return value\n'
    )
    comment = "  # sarj-noqa: SARJ092 -- documentation tooling requires an explicit type"
    lines = source.splitlines()
    line = 0 if marker in {"header", "unrelated-code"} else 5 if marker == "closing" else 4
    lines[line] += comment.replace("SARJ092", "SARJ086") if marker == "unrelated-code" else comment
    path = tmp_path / "boundary.py"
    path.write_text("\n".join(lines) + "\n")
    findings = analyze(["no-docstring-type-restatement"], [path])
    assert len(findings) == (0 if marker in {"header", "closing"} else 1)


@pytest.mark.parametrize("quoted", [False, True], ids=("evaluated-annotation", "quoted-annotation"))
@pytest.mark.parametrize("rule_id", ["require-pydantic-ordinal-lower-bound", "shared-mutable-pydantic-factory"])
def test_annotation_effects_do_not_prove_the_runtime_field_contract(
    rule_id: RuleId, quoted: bool, tmp_path: Path
) -> None:
    if rule_id == "require-pydantic-ordinal-lower-bound":
        field = "page_number: int = Field(default=1, description='1 for the first page')"
        annotation = "constrain(page_number)"
        setup = "def constrain(field):\n    field.metadata.append(Ge(1))\n    return int\n"
    else:
        field = "items: list[int] = Field(default_factory=lambda: SHARED)"
        annotation = "fresh(items)"
        setup = "def fresh(field):\n    field.default_factory = list\n    field._attributes_set['default_factory'] = list\n    return int\n"
    annotation = repr(annotation) if quoted else annotation
    path = tmp_path / "boundary.py"
    path.write_text(
        "from pydantic import BaseModel, Field\nfrom annotated_types import Ge\nSHARED = []\n"
        + setup
        + "class Record(BaseModel):\n    "
        + field
        + f"\n    marker: {annotation} = 0\n"
    )
    findings = analyze([rule_id], [path])
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
