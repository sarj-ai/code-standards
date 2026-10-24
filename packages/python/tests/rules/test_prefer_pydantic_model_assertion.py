from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.prefer_pydantic_model_assertion import PreferPydanticModelAssertion


_MODEL = "from pydantic import BaseModel\nfrom typing import Annotated\nclass User(BaseModel):\n    id: int\n    name: str\n    active: bool\n"
_ORIGINS = (
    ("parameter", "", "result: User", ""),
    ("optional", "", "result: User | None", "assert result is not None\n"),
    ("quoted", "", "result: 'User'", ""),
    ("annotated", "", "result: Annotated[User, 'record']", ""),
    ("alias", "type Result = User\n", "result: Result", ""),
    ("constructed", "", "", "result = User(id=1, name='Alice', active=True)\n"),
    ("validated", "", "raw", "result = User.model_validate(raw)\n"),
    ("local-annotation", "", "raw", "result: User = raw\n"),
    ("function-return", "def load() -> User: ...\n", "", "result = load()\n"),
    (
        "method-return",
        "class Service:\n    def load(self) -> User: ...\n",
        "service: Service",
        "result = service.load()\n",
    ),
)
_ASSERTIONS = (
    ("equality", "assert result.id == 1\nassert result.name == 'Alice'\n", 1),
    ("boolean", "assert result.active is True\nassert result.name == 'Alice'\n", 1),
    ("single", "assert result.id == 1\n", 0),
    ("message", "assert result.id == 1, 'identifier contract'\nassert result.name == 'Alice'\n", 0),
    ("effectful-expected", "assert result.id == identifier()\nassert result.name == 'Alice'\n", 0),
)


@pytest.fixture
def rule() -> PreferPydanticModelAssertion:
    return PreferPydanticModelAssertion()


def test_documented_examples() -> None:
    verify_native_rule(PreferPydanticModelAssertion, analyze)


@pytest.mark.parametrize(("origin", "prefix", "parameters", "setup"), _ORIGINS, ids=[case[0] for case in _ORIGINS])
@pytest.mark.parametrize(("comparison", "body", "expected"), _ASSERTIONS, ids=[case[0] for case in _ASSERTIONS])
def test_model_assertion_contracts(
    *,
    rule: PreferPydanticModelAssertion,
    origin: str,
    prefix: str,
    parameters: str,
    setup: str,
    comparison: str,
    body: str,
    expected: int,
) -> None:
    source = (
        _MODEL
        + prefix
        + f"def test_{origin.replace('-', '_')}_{comparison.replace('-', '_')}({parameters}):\n"
        + "".join("    " + line + "\n" for line in (setup + body).splitlines())
    )
    findings = rule.check(Path("tests/test_user.py"), source)
    assert len(findings) == expected


@pytest.mark.parametrize(
    "body",
    [
        "assert result.id == 1\nassert other.name == 'Alice'",
        "assert result.id == 1\nassert result.id == 2",
        "assert result.id > 0\nassert result.name == 'Alice'",
        "assert result.id == 1\nresult = other\nassert result.name == 'Alice'",
        "assert result.user.id == 1\nassert result.user.name == 'Alice'",
        "assert result.model_dump(include={'id', 'name'}) == {'id': 1, 'name': 'Alice'}",
        "assert result == User(id=1, name='Alice', active=True)",
    ],
)
def test_preserves_distinct_test_contracts(rule: PreferPydanticModelAssertion, body: str) -> None:
    source = (
        _MODEL + "def test_user(result: User, other):\n" + "".join("    " + line + "\n" for line in body.splitlines())
    )
    assert rule.check(Path("tests/test_user.py"), source) == []


def test_non_model_attributes_remain_valid(rule: PreferPydanticModelAssertion) -> None:
    source = (
        _MODEL.replace("(BaseModel)", "")
        + "def test_user(result: User):\n    assert result.id == 1\n    assert result.name == 'Alice'\n"
    )
    assert rule.check(Path("tests/test_user.py"), source) == []


def test_plain_property_keeps_its_behavior_assertion(rule: PreferPydanticModelAssertion) -> None:
    source = (
        "from pydantic import BaseModel\n"
        "class Status(BaseModel):\n    enabled: bool\n    ready: bool\n"
        "    @property\n    def unavailable(self) -> bool:\n        return self.enabled and not self.ready\n"
        "def load() -> Status | None: ...\n"
        "def test_status(blocked: bool):\n"
        "    status = load()\n"
        "    assert status is not None\n"
        "    assert status.enabled is True\n"
        "    assert status.unavailable is blocked\n"
    )
    assert rule.check(Path("tests/test_status.py"), source) == []


@pytest.mark.parametrize(
    "header",
    [
        "@pytest.fixture\ndef test_factory(result: User):",
        "@custom\ndef test_user(result: User):",
        "class TestUser(Base):\n    def test_user(self, result: User):",
    ],
)
def test_non_collected_contracts_keep_field_assertions(rule: PreferPydanticModelAssertion, header: str) -> None:
    indent = "        " if header.startswith("class") else "    "
    source = (
        "import pytest\n"
        + _MODEL
        + header
        + "\n"
        + indent
        + "assert result.id == 1\n"
        + indent
        + "assert result.name == 'Alice'\n"
    )
    assert rule.check(Path("tests/test_user.py"), source) == []


def test_final_model_still_has_comparable_data_fields(rule: PreferPydanticModelAssertion) -> None:
    source = (
        "from typing import final\n"
        + _MODEL.replace("class User(", "@final\nclass User(")
        + "def test_user(result: User):\n    assert result.id == 1\n    assert result.name == 'Alice'\n"
    )
    assert len(rule.check(Path("tests/test_user.py"), source)) == 1


@pytest.mark.parametrize(
    ("prefix", "declaration", "attribute"),
    [
        ("from typing import ClassVar\n", "kind: ClassVar[str] = 'user'", "kind"),
        ("from typing import ClassVar as Metadata\n", "kind: 'Metadata[str]' = 'user'", "kind"),
        (
            "from typing import ClassVar as Metadata\ndef helper():\n    from typing import Callable as Metadata\n",
            "kind: Metadata[str] = 'user'",
            "kind",
        ),
        ("import typing_extensions as te\n", "kind: te.ClassVar[str] = 'user'", "kind"),
        ("from typing import Final\n", "kind: Final[str] = 'user'", "kind"),
        ("from typing import ClassVar\ntype Metadata = ClassVar[str]\n", "kind: Metadata = 'user'", "kind"),
        ("from pydantic import PrivateAttr\n", "_cache: str = PrivateAttr(default='user')", "_cache"),
        ("", "_cache: str", "_cache"),
        ("", "model_config: dict = {}", "model_config"),
    ],
)
def test_metadata_keeps_its_own_assertion(
    rule: PreferPydanticModelAssertion, prefix: str, declaration: str, attribute: str
) -> None:
    source = (
        prefix
        + _MODEL
        + "    "
        + declaration
        + "\n"
        + "def test_user(result: User, expected):\n"
        + "    assert result.id == 1\n"
        + f"    assert result.{attribute} == expected\n"
    )
    assert rule.check(Path("tests/test_user.py"), source) == []


@pytest.mark.parametrize(("attribute", "value", "expected"), [("kind", "user", 0), ("name", "Alice", 1)])
def test_imported_model_uses_its_own_annotation_imports(
    rule: PreferPydanticModelAssertion, tmp_path: Path, attribute: str, value: str, expected: int
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="metadata-probe"\nversion="0.0.0"\n')
    model = tmp_path / "models.py"
    model.write_text("from typing import ClassVar as Metadata\n" + _MODEL + "    kind: Metadata[str] = 'user'\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    test = tests / "test_user.py"
    test.write_text(
        "from models import User\n"
        "def test_user(result: User):\n"
        "    assert result.id == 1\n"
        f"    assert result.{attribute} == {value!r}\n"
    )
    assert len(analyze([rule.id], [model, test])) == expected


def test_cyclic_metadata_aliases_do_not_hide_ordinary_fields(rule: PreferPydanticModelAssertion) -> None:
    source = (
        "type First = Second\ntype Second = First\n"
        + _MODEL
        + "    metadata: First\n"
        + "def test_user(result: User):\n    assert result.id == 1\n    assert result.name == 'Alice'\n"
    )
    assert len(rule.check(Path("tests/test_user.py"), source)) == 1


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [("Annotated[int, ClassVar[str]]", 1), ("Annotated[ClassVar[int], 'metadata']", 0)],
)
def test_only_the_annotated_type_defines_class_metadata(
    rule: PreferPydanticModelAssertion, annotation: str, expected: int
) -> None:
    source = (
        "from pydantic import BaseModel\nfrom typing import Annotated, ClassVar\n"
        f"class User(BaseModel):\n    id: {annotation} = 1\n    name: str\n"
        "def test_user(result: User):\n    assert result.id == 1\n    assert result.name == 'Alice'\n"
    )
    assert len(rule.check(Path("tests/test_user.py"), source)) == expected


@pytest.mark.parametrize(("override", "expected"), [("", 1), ("    id: ClassVar[int] = 1\n", 0)])
def test_inherited_fields_keep_subclass_metadata_overrides(
    rule: PreferPydanticModelAssertion, override: str, expected: int
) -> None:
    source = (
        "from pydantic import BaseModel\nfrom typing import ClassVar\n"
        "class Parent(BaseModel):\n    id: int\n"
        f"class User(Parent):\n{override}    name: str\n"
        "def test_user(result: User):\n    assert result.id == 1\n    assert result.name == 'Alice'\n"
    )
    assert len(rule.check(Path("tests/test_user.py"), source)) == expected


@pytest.mark.parametrize(
    "wrapper",
    [
        "if enabled:\n{body}",
        "try:\n    pass\nexcept ValueError:\n{body}",
        "try:\n    pass\nexcept* ValueError:\n{body}",
        "with resource:\n{body}",
        "match value:\n    case 1:\n{deep_body}",
    ],
)
def test_nested_blocks_keep_one_model_assertion_run(rule: PreferPydanticModelAssertion, wrapper: str) -> None:
    assertions = "assert result.id == 1\nassert result.name == 'Alice'"
    body = wrapper.format(
        body="\n".join("    " + line for line in assertions.splitlines()),
        deep_body="\n".join("        " + line for line in assertions.splitlines()),
    )
    source = _MODEL + "def test_user(result: User):\n" + "\n".join("    " + line for line in body.splitlines())
    assert len(rule.check(Path("tests/test_user.py"), source)) == 1
