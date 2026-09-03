from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_self_type_annotation import PreferSelfTypeAnnotation


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return PreferSelfTypeAnnotation().check(Path("example.py"), textwrap.dedent(source))


_PUBLIC_EXAMPLES = PreferSelfTypeAnnotation.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferSelfTypeAnnotation().check(Path(focus.path), focus.source)) == example.expected_count


def test_flags_string_literal_class_return_type() -> None:
    source = """
    class Builder:
        def set_name(self, name: str) -> "Builder":
            self.name = name
            return self
    """
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ078"
    assert diags[0].severity is Severity.WARNING
    assert "consider `Self`" in diags[0].message


def test_flags_explicit_class_name_return_type() -> None:
    source = """
    class Builder:
        def set_name(self, name: str) -> Builder:
            self.name = name
            return self
    """
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ078"


def test_flags_classmethod_constructor_annotated_with_enclosing_class() -> None:
    source = """
    class Builder:
        @classmethod
        def create(cls) -> "Builder":
            return cls()
    """
    diags = _check(source)
    assert len(diags) == 1
    assert "returns an instance of its class" in diags[0].message


@pytest.mark.parametrize(
    ("import_line", "decorator"),
    [
        ("from builtins import classmethod as class_method", "class_method"),
        ("import builtins", "builtins.classmethod"),
    ],
)
def test_flags_proven_classmethod_alias(import_line: str, decorator: str) -> None:
    source = f"""
    {import_line}

    class Builder:
        @{decorator}
        def create(builder_type) -> "Builder":
            return builder_type()
    """
    assert len(_check(source)) == 1


def test_flags_renamed_instance_receiver() -> None:
    source = """
    class Builder:
        def configure(this) -> "Builder":
            return this
    """
    assert len(_check(source)) == 1


def test_accepts_self_return_type_annotation() -> None:
    source = """
    from typing import Self

    class Builder:
        def set_name(self, name: str) -> Self:
            self.name = name
            return self
    """
    assert _check(source) == []


def test_does_not_flag_method_returning_other_class() -> None:
    source = """
    class Builder:
        def build(self) -> Config:
            return Config()
    """
    diags = _check(source)
    assert len(diags) == 0


def test_does_not_flag_mixed_return_shapes() -> None:
    source = """
class Builder:
    def configure(self, clone: bool) -> "Builder":
        if clone:
            return Builder()
        return self
"""
    assert _check(source) == []


def test_ignores_method_with_implicit_none_fallthrough() -> None:
    source = """
class Builder:
    def configure(self, enabled: bool) -> "Builder":
        if enabled:
            return self
"""
    assert _check(source) == []


def test_flags_method_when_both_branches_return_self() -> None:
    source = """
class Builder:
    def configure(self, enabled: bool) -> "Builder":
        if enabled:
            return self
        else:
            return self
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("import_line", "base"),
    [("", "type"), ("from abc import ABCMeta", "ABCMeta"), ("import abc", "abc.ABCMeta")],
)
def test_ignores_metaclass_methods(import_line: str, base: str) -> None:
    source = f"""\
{import_line}
class ModelMeta({base}):
    def configure(self) -> "ModelMeta":
        return self
"""
    assert _check(source) == []


def test_does_not_suppress_shadowed_type_base() -> None:
    source = """
class type:
    pass

class Builder(type):
    def configure(self) -> "Builder":
        return self
"""
    assert len(_check(source)) == 1


def test_ignores_generic_return_that_can_change_specialization() -> None:
    source = """
class Box:
    def replace(self, value) -> "Box[str]":
        self.value = value
        return self
"""
    assert _check(source) == []


def test_flags_pydantic_classmethod_constructor() -> None:
    source = """
from pydantic import BaseModel

class Model(BaseModel):
    @classmethod
    def from_payload(cls, payload: object) -> "Model":
        return cls.model_validate(payload)
"""
    assert len(_check(source)) == 1


def test_does_not_assume_model_constructor_on_unproven_class() -> None:
    source = """
class Model:
    @classmethod
    def from_payload(cls, payload: object) -> "Model":
        return cls.model_validate(payload)
"""
    assert _check(source) == []


def test_flags_pydantic_after_model_validator() -> None:
    source = """
from pydantic import BaseModel, model_validator

class Model(BaseModel):
    @model_validator(mode="after")
    def validate_model(self) -> "Model":
        return self
"""
    assert len(_check(source)) == 1


def test_defers_standard_self_returning_dunders_to_ruff() -> None:
    source = """
class Resource:
    def __enter__(self) -> "Resource":
        return self
"""
    assert _check(source) == []


def test_does_not_treat_nested_local_function_as_method() -> None:
    source = """
class Builder:
    def configure(self) -> None:
        def helper() -> "Builder":
            return self
"""
    assert _check(source) == []


def test_ignores_direct_base_annotation_contract() -> None:
    source = """
class ConcreteBuilder(AbstractBuilder):
    def configure(self) -> "AbstractBuilder":
        return self
"""

    assert _check(source) == []


def test_ignores_init_return_annotation() -> None:
    source = """
class Builder:
    def __init__(self) -> "Builder":
        return self
"""
    assert _check(source) == []


def test_ignores_staticmethod_named_self() -> None:
    source = """
class Builder:
    @staticmethod
    def identity(self: "Builder") -> "Builder":
        return self
"""
    assert _check(source) == []


def test_ignores_shadowed_classmethod_decorator() -> None:
    source = """
def classmethod(function):
    return function

class Builder:
    @classmethod
    def create(cls) -> "Builder":
        return cls()
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    ("import_line", "decorator"),
    [
        ("from typing import final", "final"),
        ("from typing_extensions import final as sealed", "sealed"),
        ("import typing", "typing.final"),
    ],
)
def test_ignores_proven_final_class(import_line: str, decorator: str) -> None:
    source = f"""
{import_line}

@{decorator}
class Builder:
    def configure(self) -> "Builder":
        return self
"""
    assert _check(source) == []


def test_shadowed_final_does_not_suppress() -> None:
    source = """
def final(cls):
    return cls

@final
class Builder:
    def configure(self) -> "Builder":
        return self
"""
    assert len(_check(source)) == 1


def test_ignores_generator_returning_receiver() -> None:
    source = """
class Builder:
    def values(self) -> "Builder":
        yield 1
        return self
"""
    assert _check(source) == []


def test_ignores_rebound_receiver() -> None:
    source = """
class Builder:
    def configure(self) -> "Builder":
        self = Builder()
        return self
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "binding",
    [
        "def self():\n            pass",
        "class self:\n            pass",
        "import email as self",
        "from email import message as self",
        "try:\n            pass\n        except Exception as self:\n            pass",
        "match value:\n            case self:\n                pass",
    ],
)
def test_ignores_receiver_rebound_by_non_name_binding(binding: str) -> None:
    source = f"""
class Builder:
    def configure(self, value) -> "Builder":
        {binding}
        return self
"""
    assert _check(source) == []


def test_ignores_unknown_behavior_changing_decorator() -> None:
    source = """
class Builder:
    @framework_callback
    def configure(self) -> "Builder":
        return self
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    ("import_line", "mutation", "decorator"),
    [
        ("import builtins", "builtins.classmethod = identity", "builtins.classmethod"),
        ("import builtins as runtime", "runtime.classmethod = identity", "runtime.classmethod"),
        ("import builtins", "builtins.property = identity", "builtins.property"),
    ],
)
def test_ignores_mutated_qualified_builtin_decorator(
    import_line: str,
    mutation: str,
    decorator: str,
) -> None:
    source = f"""
{import_line}
{mutation}

class Builder:
    @{decorator}
    def configure(self) -> "Builder":
        return self
"""
    assert _check(source) == []


@pytest.mark.parametrize("decorator", ["classmethod()", "property()", "override()"])
def test_ignores_called_non_factory_decorator(decorator: str) -> None:
    source = f"""
from typing import override

class Builder:
    @{decorator}
    def configure(self) -> "Builder":
        return self
"""
    assert _check(source) == []


def test_ignores_proven_iterator_method_owned_by_ruff() -> None:
    source = """
from collections.abc import Iterator

class Values(Iterator[int]):
    def __iter__(self) -> "Values":
        return self
"""
    assert _check(source) == []


def test_ignores_aliased_metaclass_and_its_subclass() -> None:
    source = """
from builtins import type as Type

class Meta(Type):
    def configure(self) -> "Meta":
        return self

class DerivedMeta(Meta):
    def configure(self) -> "DerivedMeta":
        return self
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "declarations",
    [
        "TypeAlias = type",
        "import abc\nTypeAlias = abc.ABCMeta",
        "TypeAlias = type\nSecondAlias = TypeAlias",
    ],
)
def test_ignores_assignment_alias_of_metaclass_base(declarations: str) -> None:
    base = "SecondAlias" if "SecondAlias" in declarations else "TypeAlias"
    source = f"""
{declarations}

class Factory({base}):
    def configure(self) -> "Factory":
        return self
"""
    assert _check(source) == []


def test_does_not_trust_rebound_metaclass_alias() -> None:
    source = """
TypeAlias = type
TypeAlias = object

class Factory(TypeAlias):
    def configure(self) -> "Factory":
        return self
"""
    assert len(_check(source)) == 1


def test_honors_exact_suppression() -> None:
    source = """
class Builder:
    def configure(self) -> "Builder":  # sarj-noqa: SARJ078
        return self
"""
    assert _check(source) == []


def test_ignores_metaclass_with_new_signature_and_derived_metaclass() -> None:
    source = """
class FrameworkMeta(ExternalMeta):
    def __new__(cls, name, bases, namespace):
        return super().__new__(cls, name, bases, namespace)

    def configure(self) -> "FrameworkMeta":
        return self

class DerivedMeta(FrameworkMeta):
    def configure(self) -> "DerivedMeta":
        return self
"""
    assert _check(source) == []


def test_ignores_framework_metaclass_with_unresolved_base() -> None:
    source = """
class FrameworkMeta(ExternalMeta):
    def configure(self) -> "FrameworkMeta":
        return self
"""
    assert _check(source) == []


def test_ignores_malformed_source() -> None:
    assert _check("class Builder(") == []


def test_cli_reports_nonblocking_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "builder.py"
    target.write_text('class Builder:\n    def configure(self) -> "Builder":\n        return self\n', encoding="utf-8")

    assert main(["check", "--rule", "prefer-self-type-annotation", str(target)]) == 0
    assert "SARJ078 warning:" in capsys.readouterr().out


def test_ignores_generated_client() -> None:
    source = """
# @generated - do not edit
class Client:
    def configure(self) -> "Client":
        return self
"""
    assert PreferSelfTypeAnnotation().check(Path("generated/client.py"), textwrap.dedent(source)) == []
