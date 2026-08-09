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
