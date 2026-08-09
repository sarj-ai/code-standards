from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

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
    assert "use `Self` (from `typing`) instead" in diags[0].message


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


@pytest.mark.parametrize("base", ["type", "ABCMeta", "abc.ABCMeta"])
def test_ignores_metaclass_methods(base: str) -> None:
    source = f"""\
class ModelMeta({base}):
    def configure(self) -> "ModelMeta":
        return self
"""
    assert _check(source) == []


def test_flags_pydantic_classmethod_constructor() -> None:
    source = """
class Model:
    @classmethod
    def from_payload(cls, payload: object) -> "Model":
        return cls.model_validate(payload)
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


def test_flags_direct_base_annotation_when_method_returns_self() -> None:
    source = """
class ConcreteBuilder(AbstractBuilder):
    def configure(self) -> "AbstractBuilder":
        return self
"""

    assert len(_check(source)) == 1


def test_ignores_generated_client() -> None:
    source = """
# @generated - do not edit
class Client:
    def configure(self) -> "Client":
        return self
"""
    assert PreferSelfTypeAnnotation().check(Path("generated/client.py"), textwrap.dedent(source)) == []
