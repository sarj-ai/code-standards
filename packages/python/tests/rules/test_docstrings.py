"""Direct tests for the docstring parser shared by SARJ049/SARJ084."""

import ast

import pytest

from sarj_python_lint.rules._docstrings import (
    PROMPT_DECORATOR_MARKERS,
    VALUE_MARKER_RE,
    arg_entries,
    arg_section,
    decorator_markers,
    identifier_stems,
    restates,
    sections,
    signature_stems,
)


def _func(source: str) -> ast.FunctionDef:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def test_a_docstring_with_no_header_is_all_summary() -> None:
    assert sections("Get a value.\n") == {"summary": "Get a value.\n"}


def test_sections_split_on_headers_alone_on_their_line() -> None:
    found = sections("Do a thing.\n\nArgs:\n    key: The key.\n\nReturns:\n    The value.\n")
    assert found["summary"].strip() == "Do a thing."
    assert "key: The key." in found["Args"]
    assert "The value." in found["Returns"]


def test_a_section_word_with_prose_after_it_is_not_a_header() -> None:
    """A header must be ALONE on its line; otherwise ordinary prose splits the docstring."""
    assert set(sections("Note: this is prose, not a section.\n")) == {"summary"}
    assert set(sections("See the Returns: value for details.\n")) == {"summary"}


@pytest.mark.parametrize("name", ["Args", "Arguments", "Parameters", "Params", "Keyword Args"])
def test_every_spelling_of_the_parameter_section_is_found(name: str) -> None:
    assert arg_section(f"Do a thing.\n\n{name}:\n    key: The key.\n") is not None


def test_a_docstring_without_a_parameter_section_has_none() -> None:
    assert arg_section("Do a thing.\n\nReturns:\n    The value.\n") is None


def test_an_arg_entry_carries_name_type_and_description() -> None:
    assert arg_entries("    key (str): The lookup key.\n") == [("key", "str", "The lookup key.")]


def test_a_wrapped_description_folds_into_its_entry() -> None:
    """Without the fold, an entry whose informative half wrapped reads as a bare restatement."""
    entries = arg_entries("    key (str): The lookup key,\n        namespaced by tenant.\n")
    assert entries == [("key", "str", "The lookup key, namespaced by tenant.")]


def test_an_unindented_line_with_a_colon_is_not_an_entry() -> None:
    assert arg_entries("key: not an entry\n") == []


def test_signature_stems_read_names_annotations_and_the_owning_class() -> None:
    node = _func("def get_widget(self, widget_id: str) -> WidgetRow: ...")
    stems = signature_stems(node, "WidgetStore")
    assert {"get", "widget", "id", "str", "row", "stor"} <= stems


def test_self_and_cls_contribute_nothing_a_reader_did_not_already_have() -> None:
    node = _func("def run(self) -> None: ...")
    assert "self" not in signature_stems(node, None)


def test_a_docstring_restating_only_the_signature_is_recognised() -> None:
    node = _func("def get_widget(self, widget_id: str) -> str: ...")
    stems = signature_stems(node, None)
    assert restates("Get the widget by widget id.", stems)
    assert not restates("Get the widget; raises when the tenant is suspended.", stems)


def test_a_text_with_no_content_words_is_not_a_restatement() -> None:
    """Distinguish empty prose from a restatement of the code."""
    node = _func("def run() -> None: ...")
    assert not restates("The a of it.", signature_stems(node, None))


def test_identifier_stems_fold_the_casings_and_inflections() -> None:
    assert {"widget", "updat"} <= identifier_stems("def updates_widgets(): ...")


@pytest.mark.parametrize(
    "text",
    ["waits 250 ms", "see https://example.com", "encoded as UTF-8", "Raises: KeyError", ">>> f(1)"],
)
def test_the_value_marker_recognises_content_a_signature_cannot_carry(text: str) -> None:
    assert VALUE_MARKER_RE.search(text)


def test_the_value_marker_ignores_a_plain_restatement() -> None:
    assert not VALUE_MARKER_RE.search("Get the widget by id.")


@pytest.mark.parametrize(
    "decorator",
    ["@router.post('/widgets')", "@app.get('/x')", "@click.command()", "@function_tool"],
)
def test_a_consumed_docstring_is_recognised_by_its_decorator(decorator: str) -> None:
    """These docstrings are artefacts -- an OpenAPI description, `--help`, a tool prompt."""
    node = _func(f"{decorator}\ndef handler() -> None: ...")
    assert decorator_markers(node) & PROMPT_DECORATOR_MARKERS


def test_an_ordinary_decorator_does_not_make_a_docstring_an_artefact() -> None:
    node = _func("@functools.cache\ndef handler() -> None: ...")
    assert not decorator_markers(node) & PROMPT_DECORATOR_MARKERS
