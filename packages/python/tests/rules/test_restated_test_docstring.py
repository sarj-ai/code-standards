from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.restated_test_docstring import RestatedTestDocstring


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "tests/test_thing.py") -> list[Diagnostic]:
    return RestatedTestDocstring().check(Path(path), dedent(source))


RESTATING = [
    ("test_returns_none_when_missing", "Test that it returns None when missing."),
    ("test_list_collections", "Test that the list_collections is called correctly."),
    ("test_generate_fernet_key_string", "Test generating a Fernet key."),
    ("test_bulk_delete_excludes_system_themes", "Test bulk delete excludes system themes"),
    ("test_config_can_be_set_to_list", "Test that the config can be set to a list."),
    ("test_property_accessors_work_correctly", "Test that property accessors work."),
    ("test_import_chart_invalid", "Test import invalid chart"),
]


@pytest.mark.parametrize(("name", "docstring"), RESTATING)
def test_flags_a_test_docstring_that_restates_the_name(name: str, docstring: str) -> None:
    diags = _check(f'''
        def {name}():
            """{docstring}"""
            conn.list_collections.assert_called_once()
            assert config.property_accessors
        ''')
    assert len(diags) == 1
    assert diags[0].code == "SARJ088"


def test_a_docstring_naming_something_new_is_left_alone() -> None:
    """The restatement test itself: one word the name and body do not carry saves it."""
    diags = _check('''
        def test_keeps_the_lock():
            """The scheduler would spin forever without this."""
            assert acquire()
        ''')
    assert diags == []


def test_the_test_ceremony_vocabulary_is_discounted() -> None:
    diags = _check('''
        def test_widget_renders():
            """Verify that the widget renders correctly."""
            assert render(widget)
        ''')
    assert len(diags) == 1


def test_a_word_the_body_already_carries_is_not_novel() -> None:
    """The body is code the reader has in front of them; a docstring re-spelling it adds nothing."""
    diags = _check('''
        def test_lookup():
            """Test that a missing beneficiary is None."""
            missing = store.get_beneficiary(beneficiary_id)
            assert missing is None
        ''')
    assert len(diags) == 1


@pytest.mark.parametrize("value", ["True", "False"])
def test_boolean_singletons_in_the_body_are_not_novel(value: str) -> None:
    diags = _check(f'''
        def test_enabled():
            """Test that enabled is {value}."""
            assert enabled() is {value}
        ''')
    assert len(diags) == 1


def test_signature_parameters_and_annotations_are_not_novel() -> None:
    diags = _check('''
        def test_serializes_account(account: CustomerAccount) -> SerializedAccount:
            """Test serializes a customer account to a serialized account."""
            return serialize(account)
        ''')
    assert len(diags) == 1


def test_prose_inside_a_string_literal_does_not_count_as_code() -> None:
    """Only IDENTIFIERS widen the known set — a test body is full of English in strings."""
    diags = _check('''
        def test_rejects_it():
            """A stale cursor is silently discarded."""
            assert reject("a stale cursor is silently discarded") is None
        ''')
    assert diags == []


def test_a_docstring_with_a_google_section_is_left_whole() -> None:
    """Sections are SARJ086/087's subject; this rule deletes whole summaries only."""
    diags = _check('''
        def test_it_works():
            """Test that it works.

            Returns:
                None.
            """
            assert works() is None
        ''')
    assert diags == []


def test_a_protected_docstring_is_left_alone() -> None:
    """A causal connective is the shape of a why, whatever words carry it."""
    diags = _check('''
        def test_it_works_because_the_lock_is_held():
            """It works because the lock is held."""
            assert works(lock)
        ''')
    assert diags == []


def test_a_docstring_carrying_a_doctest_is_left_alone() -> None:
    diags = _check('''
        def test_it_works():
            """Test that it works: >>> works()"""
            assert works()
        ''')
    assert diags == []


def test_a_docstring_carrying_a_unit_is_left_alone() -> None:
    diags = _check('''
        def test_timeout():
            """Test that the timeout is 30 seconds."""
            assert timeout() == 30
        ''')
    assert diags == []


def test_a_production_method_named_test_connection_is_left_alone() -> None:
    """`Hook.test_connection` is not a test, and the fix is not "rename the test"."""
    diags = _check(
        '''
        class AzureComputeHook:
            def test_connection(self):
                """Test the Azure Compute connection."""
                return connection()
        ''',
        path="airflow/providers/microsoft/azure/hooks/compute.py",
    )
    assert diags == []


def test_a_helper_in_a_test_file_is_left_alone() -> None:
    diags = _check('''
        def make_client():
            """Make a client."""
            return client()
        ''')
    assert diags == []


def test_a_method_of_a_test_class_counts_as_a_test() -> None:
    diags = _check('''
        class TestThing:
            def testItWorks(self):
                """Test that it works."""
                assert works()
        ''')
    assert len(diags) == 1


def test_an_async_test_counts_as_a_test() -> None:
    diags = _check('''
        async def test_widget_renders():
            """Test that the widget renders."""
            assert await render(widget)
        ''')
    assert len(diags) == 1


def test_generated_files_are_exempt() -> None:
    diags = _check('''
        # Code generated by a tool. DO NOT EDIT.
        def test_it_works():
            """Test that it works."""
            assert works()
        ''')
    assert diags == []


# The class arm: a `Test*` class docstring measured against its own name and
# the signatures of the methods it holds.


def test_flags_a_test_class_docstring_that_restates_the_class_name() -> None:
    diags = _check('''
        class TestSessionExpiry:
            """Tests for session expiry."""

            def test_expires(self):
                assert expired()
        ''')
    assert len(diags) == 1
    assert diags[0].code == "SARJ088"


def test_method_names_count_for_a_test_class() -> None:
    """A `Test*` class names its subject twice: once in its own name, once per method."""
    diags = _check('''
        class TestParser:
            """Test cases for the diamond dependency manifest."""

            def test_diamond_dependency(self, manifest):
                assert parse(manifest)
        ''')
    assert len(diags) == 1


def test_a_test_class_naming_something_new_is_left_alone() -> None:
    diags = _check('''
        class TestSessionExpiry:
            """A lease that outlives its holder resurrects on refresh."""

            def test_expires(self):
                assert expired()
        ''')
    assert diags == []


def test_a_test_class_with_a_base_is_left_alone() -> None:
    """A base class makes the docstring an inherited contract, not a label."""
    diags = _check('''
        class TestSessionExpiry(BaseSuite):
            """Tests for session expiry."""

            def test_expires(self):
                assert expired()
        ''')
    assert diags == []


def test_a_test_class_with_a_metaclass_is_left_alone() -> None:
    diags = _check('''
        class TestSessionExpiry(metaclass=SuiteMeta):
            """Tests for session expiry."""

            def test_expires(self):
                assert expired()
        ''')
    assert diags == []


def test_a_non_test_class_is_left_alone() -> None:
    diags = _check('''
        class SessionExpiry:
            """Session expiry."""

            def check(self):
                assert expired()
        ''')
    assert diags == []


def test_reports_the_docstring_line_not_the_definition() -> None:
    diags = _check('''
        def test_it_works():
            """Test that it works."""
            assert works()
        ''')
    assert (diags[0].line, diags[0].col) == (3, 5)
