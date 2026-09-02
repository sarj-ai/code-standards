from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.docstring_args_restate_signature import DocstringArgsRestateSignature


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return DocstringArgsRestateSignature().check(Path("<t>.py"), dedent(source))


RESTATING_BLOCKS = [
    ("count_widgets(tenant_id: UUID) -> int", "tenant_id: Tenant ID"),
    ("load_manifest(manifest_id: UUID) -> Row", "manifest_id: Manifest ID"),
    ("parse_locator(locator: str) -> Locator", "locator: Locator to parse"),
    ("delete(*keys: str) -> int", "keys: Keys to delete"),
    ("repair_payload(payload: Payload) -> Payload", "payload: The payload to repair"),
]

_PUBLIC_EXAMPLES = DocstringArgsRestateSignature.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(DocstringArgsRestateSignature().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(("signature", "entry"), RESTATING_BLOCKS)
def test_flags_a_block_whose_every_entry_restates(signature: str, entry: str):
    diags = _check(f'''
        def {signature}:
            """Do the thing, and record why it happened.

            Args:
                {entry}
            """
            return None
        ''')
    assert len(diags) == 1
    assert diags[0].code == "SARJ086"


def test_the_owning_class_name_counts_as_signature():
    # A reader types `JwtService.verify_access_token(token)`, so "JWT" is not a
    # word the docstring supplies.
    diags = _check('''
        class JwtService:
            def verify_access_token(self, token: str) -> Payload:
                """Verify an access token and reject a refresh one.

                Args:
                    token: JWT access token to verify
                """
                return None
        ''')
    assert len(diags) == 1


def test_the_function_name_counts_as_signature():
    diags = _check('''
        def verify_access_token(token: str) -> Payload:
            """Reject refresh tokens before decoding.

            Args:
                token: Access token to verify
            """
            return decode(token)
        ''')
    assert len(diags) == 1


@pytest.mark.parametrize(
    "header",
    ["Args", "Arguments", "Parameters", "Params", "Keyword Args", "Keyword Arguments"],
)
def test_every_google_section_spelling_is_read(header: str):
    diags = _check(f'''
        def count_widgets(tenant_id: str) -> int:
            """Count widgets, excluding retired ones.

            {header}:
                tenant_id: Tenant ID
            """
            return 0
        ''')
    assert len(diags) == 1


def test_a_wrapped_description_is_folded_into_its_entry():
    assert (
        _check('''
        def count_widgets(tenant_id: str) -> int:
            """Count widgets, excluding retired ones.

            Args:
                tenant_id: Tenant ID, and the tenant it is
                    scoped to.
            """
            return 0
        ''')
        == []
    )


def test_one_informative_entry_protects_the_whole_block():
    # Splitting a parameter table is worse than leaving it whole.
    assert (
        _check('''
        def count_widgets(tenant_id: str, window: str) -> int:
            """Count widgets, excluding retired ones.

            Args:
                tenant_id: Tenant ID
                window: Rolling window, defaulting to the calendar month
            """
            return 0
        ''')
        == []
    )


def test_unknown_documented_parameter_is_left_to_signature_consistency_tools():
    assert (
        _check('''
        def load(user_id: str) -> None:
            """Load the user.

            Args:
                tenant_id: Tenant ID
            """
        ''')
        == []
    )


def test_docstring_only_or_mismatched_type_is_informative():
    untyped = '''
        def render(widget) -> None:
            """Render the widget.

            Args:
                widget (Widget): Widget
            """
    '''
    mismatched = '''
        def render(widget: str) -> None:
            """Render the widget.

            Args:
                widget (Widget): Widget
            """
    '''

    assert _check(untyped) == []
    assert _check(mismatched) == []


def test_sibling_parameter_words_do_not_prove_redundancy():
    assert (
        _check('''
        def copy(source_path: Path, destination_path: Path) -> None:
            """Copy a file.

            Args:
                source_path: Destination path
                destination_path: Source path
            """
        ''')
        == []
    )


@pytest.mark.parametrize("description", ["Existing path", "Supported path", "Optional path", "Required path"])
def test_semantic_qualifier_is_preserved(description: str):
    assert (
        _check(f'''
        def load(path: Path) -> None:
            """Load a resource.

            Args:
                path: {description}
            """
        ''')
        == []
    )


def test_an_entry_with_no_description_is_left_alone():
    # A machine-emitted `name (type):` stub.
    assert (
        _check('''
        def count_widgets(tenant_id: str) -> int:
            """Count Widgets

            Args:
                tenant_id (str):
            """
            return 0
        ''')
        == []
    )


def test_a_docstring_with_no_args_block_is_ignored():
    assert (
        _check('''
        def count_widgets(tenant_id: str) -> int:
            """Count widgets, excluding retired ones."""
            return 0
        ''')
        == []
    )


def test_an_empty_args_block_is_ignored():
    assert (
        _check('''
        def count_widgets(tenant_id: str) -> int:
            """Count widgets.

            Args:
            """
            return 0
        ''')
        == []
    )


@pytest.mark.parametrize(
    "entry",
    [
        "tenant_id: Tenant ID, see https://example.com/ids",
        "tenant_id: Tenant ID (RFC 4122)",
        "tenant_id: Tenant ID, cached for 30 seconds",
        "tenant_id: Tenant ID — never the account ID",
        "tenant_id: Tenant ID, because the shard key derives from it",
        "tenant_id: Tenant ID; the upstream rejects a blank one",
    ],
)
def test_entries_carrying_value_keep_the_block(entry: str):
    assert (
        _check(f'''
        def count_widgets(tenant_id: str) -> int:
            """Count widgets.

            Args:
                {entry}
            """
            return 0
        ''')
        == []
    )


def test_a_protected_signal_keeps_an_otherwise_restating_block():
    assert (
        _check('''
        def store_secret(secret: str) -> None:
            """Persist the credential in the selected vault.

            Args:
                secret: Secret
            """
            return None
        ''')
        == []
    )


def test_a_unit_keeps_an_otherwise_restating_block():
    assert (
        _check('''
        def set_timeout_ms(timeout_ms: int) -> None:
            """Configure the request deadline.

            Args:
                timeout_ms: Timeout in ms
            """
            return None
        ''')
        == []
    )


@pytest.mark.parametrize(
    "decorator",
    ["@function_tool", "@click.command()", "@typer.command()", "@router.post('/x')"],
)
def test_prompt_and_cli_decorators_are_exempt(decorator: str):
    # For an agent tool the Args block is part of the schema shipped to the
    # model; for click/typer it is the argument help text.
    assert (
        _check(f'''
        {decorator}
        def count_widgets(tenant_id: str) -> int:
            """Count widgets.

            Args:
                tenant_id: Tenant ID
            """
            return 0
        ''')
        == []
    )


def test_import_aliased_runtime_tool_decorator_is_exempt():
    assert (
        _check('''
        from agents import function_tool as exposed

        @exposed
        def count_widgets(tenant_id: str) -> int:
            """Count widgets.

            Args:
                tenant_id: Tenant ID
            """
            return 0
        ''')
        == []
    )


def test_overload_docstring_is_left_to_upstream_rule():
    assert (
        _check('''
        from typing import overload as signature

        @signature
        def load(tenant_id: str) -> int:
            """Load widgets.

            Args:
                tenant_id: Tenant ID
            """
            ...
        ''')
        == []
    )


def test_varargs_and_kwargs_resolve_to_signature_parameters():
    diagnostics = _check('''
        def merge(*items: Item, **options: Option) -> None:
            """Merge items.

            Args:
                *items: Items to merge
                **options: Merge options
            """
    ''')

    assert len(diagnostics) == 1


def test_numpy_style_parameter_blocks_are_not_parsed():
    assert (
        _check('''
        def count_widgets(tenant_id: str) -> int:
            """Count widgets.

            Parameters
            ----------
            tenant_id
                Tenant ID
            """
            return 0
        ''')
        == []
    )


def test_generated_file_is_skipped():
    assert (
        _check('''
        # Code generated by openapi-generator. DO NOT EDIT.
        def count_widgets(tenant_id: str) -> int:
            """Count widgets.

            Args:
                tenant_id: Tenant ID
            """
            return 0
        ''')
        == []
    )


def test_an_abstract_stub_keeps_compiling_after_the_fix():
    # The docstring is the whole body, but the remedy removes only the section,
    # so the suite survives — unlike SARJ050's whole-docstring deletion.
    diags = _check('''
        class Cache:
            @abc.abstractmethod
            async def delete(self, *keys: str) -> int:
                """Delete one or more keys, returning how many existed.

                Args:
                    keys: Keys to delete
                """
        ''')
    assert len(diags) == 1


def test_diagnostic_names_callable_and_is_advisory():
    [diagnostic] = _check('''
        def count_widgets(tenant_id: UUID) -> int:
            """Count widgets.

            Args:
                tenant_id: Tenant ID
            """
            return 0
    ''')

    assert "`count_widgets`" in diagnostic.message
    assert diagnostic.severity is Severity.WARNING


def test_unparseable_source_returns_nothing():
    assert _check("def (:\n") == []
