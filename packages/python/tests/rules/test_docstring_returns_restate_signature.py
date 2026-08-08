from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.docstring_returns_restate_signature import (
    DocstringReturnsRestateSignature,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "<t>.py") -> list[Diagnostic]:
    return DocstringReturnsRestateSignature().check(Path(path), dedent(source))


RESTATING_BLOCKS = [
    ("validate(self) -> None", "None"),
    ("get_line_length(line: list[Segment]) -> int", "int: The length of the line."),
    ("convert_to_aliases(self) -> list[str]", "The list of aliases."),
    ("read_block_documents(self, limit: int) -> list[BlockDocument]", "A list of block documents"),
    ("expand_grouped_metadata(annotations: Iterable[Any]) -> Iterable[Any]", "An iterable of expanded annotations."),
    ("_get_document_format(mime_type: str) -> str", "The document format"),
]

_PUBLIC_EXAMPLES = DocstringReturnsRestateSignature.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(DocstringReturnsRestateSignature().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(("signature", "block"), RESTATING_BLOCKS)
def test_flags_a_returns_block_that_restates_the_signature(signature: str, block: str):
    diags = _check(f'''
        def {signature}:
            """Do the thing, and record why it happened.

            Returns:
                {block}
            """
            return None
        ''')
    assert len(diags) == 1
    assert diags[0].code == "SARJ087"


@pytest.mark.parametrize("header", ["Returns", "Return", "Yields", "Yield"])
def test_every_return_section_spelling_is_read(header: str):
    diags = _check(f'''
        def get_line_length(line: list[Segment]) -> int:
            """Do the thing, and record why it happened.

            {header}:
                The length of the line.
            """
            return 0
        ''')
    assert len(diags) == 1


def test_the_owning_class_name_counts_as_signature():
    # A reader types `TokenStore.load(key)`, so "token" is not a word the
    # docstring supplies.
    diags = _check('''
        class TokenStore:
            def load(self, key: str) -> Row:
                """Fetch the row, waiting out a cold replica.

                Returns:
                    The token row for the key.
                """
                return None
        ''')
    assert len(diags) == 1


def test_a_block_naming_something_the_signature_does_not_is_left_alone():
    diags = _check('''
        def get_line_length(line: list[Segment]) -> int:
            """Measure a rendered line.

            Returns:
                The width in terminal cells, which is not the character count.
            """
            return 0
        ''')
    assert not diags


@pytest.mark.parametrize(
    ("signature", "block"),
    [
        ("rebind_storage(self, storage: Storage) -> Storage", "A new storage."),
        ("get_same_storage(self, storage: Storage) -> Storage", "The same storage."),
        ("copy_storage(self, storage: Storage) -> Storage", "A copy of storage."),
        ("return_itself(self) -> Self", "Itself."),
    ],
)
def test_identity_semantics_are_not_a_restatement(signature: str, block: str):
    # A return annotation cannot say whether the result is fresh or identical.
    diags = _check(f'''
        def {signature}:
            """Point the policy somewhere else without disturbing the caller.

            Returns:
                {block}
            """
            return None
        ''')
    assert not diags


def test_a_whole_docstring_restatement_belongs_to_sarj050():
    # One deletion must not read as two findings: when the SUMMARY restates the
    # signature too, `redundant-docstring` already reports the whole docstring.
    diags = _check('''
        def get_line_length(line: list[Segment]) -> int:
            """Get the line length.

            Returns:
                The length of the line.
            """
            return 0
        ''')
    assert not diags


def test_a_protected_block_is_left_alone():
    # `secret` is a security-reasoning signal AND a word of the signature, so
    # the block restates and the protected class is the only thing sparing it.
    diags = _check('''
        def get_secret(self, name: str) -> str:
            """Fetch the value, failing closed when the vault is unreachable.

            Returns:
                The secret.
            """
            return ""
        ''')
    assert not diags


@pytest.mark.parametrize(
    ("signature", "block"),
    [
        ("get_proj_249_ticket(self) -> Ticket", "The PROJ-249 ticket."),
        ("get_https_example_com(self) -> str", "https://example.com"),
        ("get_widget_because_cache(self) -> Widget", "The widget because cache."),
    ],
)
def test_references_and_causal_context_keep_the_block(signature: str, block: str):
    diags = _check(f'''
        def {signature}:
            """Fetch the configured value.

            Returns:
                {block}
            """
            return None
        ''')
    assert not diags


def test_a_prefix_is_not_a_signature_word():
    diags = _check('''
        def get_policy(self) -> Policy:
            """Load the configured policy.

            Returns:
                The policyholder.
            """
            return None
        ''')
    assert not diags


def test_a_block_carrying_a_unit_is_left_alone():
    # Every word is in the signature, so only `VALUE_MARKER_RE` keeps this one:
    # a bare unit carries no digit and so is not `is_protected`.
    diags = _check('''
        def get_timeout_ms(self) -> int:
            """Read the configured deadline.

            Returns:
                The timeout in ms.
            """
            return 0
        ''')
    assert not diags


def test_a_block_documenting_a_raise_is_left_alone():
    diags = _check('''
        def get_line_length(line: list[Segment]) -> int:
            """Measure a rendered line.

            Returns:
                The length of the line.
                Raises: ValueError
            """
            return 0
        ''')
    assert not diags


def test_a_schema_producing_decorator_exempts_the_docstring():
    # The docstring reaches an OpenAPI document, so deleting a section of it
    # changes an artefact rather than tidying a file.
    diags = _check('''
        @router.get("/widgets")
        def list_widgets(tenant_id: UUID) -> list[Widget]:
            """Serve the widget index, newest first.

            Returns:
                The list of widgets.
            """
            return []
        ''')
    assert not diags


def test_a_function_with_no_return_section_is_left_alone():
    diags = _check('''
        def get_line_length(line: list[Segment]) -> int:
            """Measure a rendered line."""
            return 0
        ''')
    assert not diags


def test_an_empty_return_section_is_left_alone():
    # `Returns:` with nothing under it is ruff's D414, not this rule's finding;
    # `restates` reports False for a text with no content words at all.
    diags = _check('''
        def get_line_length(line: list[Segment]) -> int:
            """Measure a rendered line.

            Returns:
            """
            return 0
        ''')
    assert not diags


def test_generated_files_are_exempt():
    diags = _check(
        '''
        # Code generated by the widget compiler. DO NOT EDIT.
        def get_line_length(line: list[Segment]) -> int:
            """Measure a rendered line.

            Returns:
                The length of the line.
            """
            return 0
        ''',
        path="widgets_pb2.py",
    )
    assert not diags


def test_the_finding_points_at_the_docstring():
    diags = _check('''
        def get_line_length(line: list[Segment]) -> int:
            """Measure a rendered line.

            Returns:
                The length of the line.
            """
            return 0
        ''')
    assert len(diags) == 1
    assert diags[0].line == 3


def test_a_method_and_a_nested_function_are_both_walked():
    diags = _check('''
        class Ruler:
            def measure(self, line: list[Segment]) -> int:
                """Measure a rendered line.

                Returns:
                    The measured line.
                """

                def inner(width: int) -> int:
                    """Round a width up to the next terminal cell.

                    Returns:
                        The width.
                    """
                    return width

                return inner(0)
        ''')
    assert len(diags) == 2


def test_a_syntax_error_yields_no_findings():
    assert not _check("def broken(:\n")
