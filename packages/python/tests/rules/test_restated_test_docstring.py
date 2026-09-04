from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.restated_test_docstring import RestatedTestDocstring


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


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

_PUBLIC_EXAMPLES = RestatedTestDocstring.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(RestatedTestDocstring().check(Path(focus.path), focus.source)) == example.expected_count


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
    assert diags[0].severity is Severity.WARNING


def test_default_pytest_test_prefix_without_underscore_is_checked() -> None:
    diags = _check('''
        def testConnection():
            """Test connection."""
            assert connection()
        ''')
    assert len(diags) == 1


def test_module_control_flow_does_not_hide_a_collected_test() -> None:
    diags = _check('''
        if ENABLED:
            def test_connection():
                """Test connection."""
                assert connection()
        ''')
    assert len(diags) == 1


def test_a_word_the_body_already_carries_is_not_novel() -> None:
    diags = _check('''
        def test_lookup():
            """Test that a missing beneficiary is None."""
            missing = store.get_beneficiary(beneficiary_id)
            assert missing is None
        ''')
    assert len(diags) == 1


def test_identifiers_inside_a_nested_helper_do_not_prove_a_restatement() -> None:
    diags = _check('''
        def test_widget():
            """Widget maps lease."""

            def unused_helper():
                return maps(lease)

            assert widget()
        ''')
    assert diags == []


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
    diags = _check('''
        def test_rejects_it():
            """A stale cursor is silently discarded."""
            assert reject("a stale cursor is silently discarded") is None
        ''')
    assert diags == []


def test_a_docstring_with_a_google_section_is_left_whole() -> None:
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


def test_a_test_named_method_on_a_helper_class_is_left_alone() -> None:
    diags = _check('''
        class ConnectionHelper:
            def test_connection(self):
                """Test connection."""
                return connection()
        ''')
    assert diags == []


def test_a_decorated_test_function_is_left_alone() -> None:
    diags = _check('''
        @pytest.fixture
        def test_user():
            """Test user."""
            return user()
        ''')
    assert diags == []


@pytest.mark.parametrize(
    "decorator_import",
    [
        "import pytest\n\n@pytest.mark.parametrize('value', [1])",
        "import pytest as pt\n\n@pt.mark.asyncio",
        "from pytest import mark as m\n\n@m.security",
    ],
)
def test_import_proven_pytest_marks_do_not_hide_a_restatement(decorator_import: str) -> None:
    source = f'{decorator_import}\ndef test_widget(value=1):\n    """Test widget value."""\n    assert widget(value)\n'
    diags = _check(source)
    assert len(diags) == 1


def test_an_unknown_decorator_preserves_the_docstring() -> None:
    diags = _check('''
        @published_test
        def test_widget():
            """Test widget."""
            assert widget()
        ''')
    assert diags == []


def test_a_decorated_test_method_is_left_alone() -> None:
    diags = _check('''
        class TestWidget:
            @property
            def test_state(self):
                """Test state."""
                return state()
        ''')
    assert diags == []


def test_a_pytest_marked_test_class_is_checked() -> None:
    diags = _check('''
        import pytest

        @pytest.mark.usefixtures("database")
        class TestWidget:
            """Tests widget."""

            def test_widget(self):
                assert widget()
        ''')
    assert len(diags) == 1


@pytest.mark.parametrize(
    ("import_line", "binding", "decorator"),
    [
        ("import pytest", "pytest", "pytest.mark.publish_docstring"),
        ("from pytest import mark", "mark", "mark.publish_docstring"),
    ],
)
def test_a_preceding_class_binding_can_shadow_a_pytest_mark_import(
    import_line: str,
    binding: str,
    decorator: str,
) -> None:
    diags = _check(f'''
        {import_line}

        class TestWidget:
            {binding} = publishing_framework

            @{decorator}
            def test_widget(self):
                """Test widget."""
                assert widget()
        ''')
    assert diags == []


def test_a_later_class_binding_does_not_shadow_a_pytest_mark() -> None:
    diags = _check('''
        import pytest

        class TestWidget:
            @pytest.mark.security
            def test_widget(self):
                """Test widget."""
                assert widget()

            pytest = publishing_framework
        ''')
    assert len(diags) == 1


def test_a_later_class_binding_does_not_shadow_a_conditionally_defined_method() -> None:
    diags = _check('''
        import pytest

        class TestWidget:
            if ENABLED:
                @pytest.mark.security
                def test_widget(self):
                    """Test widget."""
                    assert widget()

            pytest = publishing_framework
        ''')
    assert len(diags) == 1


def test_a_later_binding_in_the_same_class_branch_does_not_shadow_the_decorator() -> None:
    diags = _check('''
        import pytest

        class TestWidget:
            if ENABLED:
                @pytest.mark.security
                def test_widget(self):
                    """Test widget."""
                    assert widget()
                pytest = publishing_framework
        ''')
    assert len(diags) == 1


def test_a_binding_in_a_sibling_class_branch_does_not_shadow_the_decorator() -> None:
    diags = _check('''
        import pytest

        class TestWidget:
            if ENABLED:
                @pytest.mark.security
                def test_widget(self):
                    """Test widget."""
                    assert widget()
            else:
                pytest = publishing_framework
        ''')
    assert len(diags) == 1


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
    diags = _check('''
        class TestParser:
            """Test cases for the diamond dependency manifest."""

            def test_diamond_dependency(self, manifest):
                assert parse(manifest)
        ''')
    assert len(diags) == 1


def test_separate_method_names_cannot_jointly_prove_a_class_restatement() -> None:
    diags = _check('''
        class TestParser:
            """Tests token lease."""

            def test_token(self):
                assert token()

            def test_lease(self):
                assert lease()
        ''')
    assert diags == []


def test_a_test_class_naming_something_new_is_left_alone() -> None:
    diags = _check('''
        class TestSessionExpiry:
            """A lease that outlives its holder resurrects on refresh."""

            def test_expires(self):
                assert expired()
        ''')
    assert diags == []


def test_a_test_class_with_a_base_is_left_alone() -> None:
    diags = _check('''
        class TestSessionExpiry(BaseSuite):
            """Tests for session expiry."""

            def test_expires(self):
                assert expired()
        ''')
    assert diags == []


def test_methods_of_an_inherited_test_class_are_left_alone() -> None:
    diags = _check('''
        class TestWidget(unittest.TestCase):
            def test_renders(self):
                """Test that widget renders."""
                self.assertTrue(render(widget))
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


def test_a_test_class_with_a_constructor_is_left_alone() -> None:
    diags = _check('''
        class TestVector:
            """Test vector."""

            def __init__(self):
                self.vector = vector()
        ''')
    assert diags == []


def test_a_test_class_with_a_literal_collection_opt_out_is_left_alone() -> None:
    diags = _check('''
        class TestHelper:
            """Tests helper."""
            __test__ = False

            def test_helper(self):
                """Test helper."""
                assert helper()
        ''')
    assert diags == []


def test_a_test_class_with_an_ambiguous_collection_opt_out_is_left_alone() -> None:
    diags = _check('''
        class TestHelper:
            """Tests helper."""
            __test__ = SHOULD_COLLECT

            def test_helper(self):
                assert helper()
        ''')
    assert diags == []


def test_a_post_definition_class_collection_opt_out_is_honored() -> None:
    diags = _check('''
        class TestHelper:
            """Tests helper."""

            def test_helper(self):
                """Test helper."""
                assert helper()

        TestHelper.__test__ = False
        ''')
    assert diags == []


def test_a_post_definition_function_collection_opt_out_is_honored() -> None:
    diags = _check('''
        def test_helper():
            """Test helper."""
            assert helper()

        test_helper.__test__ = False
        ''')
    assert diags == []


def test_an_explicit_true_collection_marker_remains_eligible() -> None:
    diags = _check('''
        def test_helper():
            """Test helper."""
            assert helper()

        test_helper.__test__ = True
        ''')
    assert len(diags) == 1


def test_a_test_class_nested_in_a_non_test_class_is_left_alone() -> None:
    diags = _check('''
        class Container:
            class TestVector:
                """Test vector."""

                def test_vector(self):
                    assert vector()
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


@pytest.mark.parametrize(
    "reader",
    [
        "test_connection.__doc__",
        "help(test_connection)",
        "inspect.getdoc(test_connection)",
        'getattr(test_connection, "__doc__")',
    ],
)
def test_an_in_file_docstring_consumer_preserves_the_test_docstring(reader: str) -> None:
    diags = _check(f'''
        def test_connection():
            """Test connection."""
            assert connection()

        DOCUMENTATION = {reader}
        ''')
    assert diags == []


def test_an_in_file_docstring_consumer_preserves_the_test_class_docstring() -> None:
    diags = _check('''
        class TestConnection:
            """Test connection."""

            def test_connection(self):
                assert connection()

        DOCUMENTATION = TestConnection.__doc__
        ''')
    assert diags == []


@pytest.mark.parametrize(
    "reader",
    ["published_test.__doc__", "inspect.getdoc(published_test)", "help(published_test)"],
)
def test_a_stable_alias_to_a_runtime_consumed_test_preserves_the_docstring(reader: str) -> None:
    diags = _check(f'''
        def test_widget():
            """Test widget."""
            assert widget()

        published_test = test_widget
        DESCRIPTION = {reader}
        ''')
    assert diags == []


def test_a_stable_alias_chain_to_a_runtime_consumer_preserves_the_docstring() -> None:
    diags = _check('''
        def test_widget():
            """Test widget."""
            assert widget()

        published_test = test_widget
        documented_test = published_test
        DESCRIPTION = documented_test.__doc__
        ''')
    assert diags == []


def test_a_rebound_alias_does_not_hide_the_test_docstring() -> None:
    diags = _check('''
        def test_widget():
            """Test widget."""
            assert widget()

        published_test = test_widget
        published_test = another_test
        DESCRIPTION = published_test.__doc__
        ''')
    assert len(diags) == 1


def test_an_alias_to_an_older_binding_does_not_hide_a_later_test_definition() -> None:
    diags = _check('''
        def helper():
            return None

        test_widget = helper
        published = test_widget

        def test_widget():
            """Test widget."""
            assert widget()

        help(published)
        ''')
    assert len(diags) == 1


def test_a_stable_alias_to_a_runtime_consumed_test_class_preserves_the_docstring() -> None:
    diags = _check('''
        class TestWidget:
            """Tests widget."""

            def test_widget(self):
                assert widget()

        PublishedTest = TestWidget
        DESCRIPTION = PublishedTest.__doc__
        ''')
    assert diags == []


@pytest.mark.parametrize(
    "reader",
    ["test_widget.__doc__", "inspect.getdoc(test_widget)", "help(test_widget)"],
)
def test_a_runtime_consumer_inside_a_helper_preserves_the_test_docstring(reader: str) -> None:
    diags = _check(f'''
        def test_widget():
            """Test widget."""
            assert widget()

        def published_description():
            return {reader}
        ''')
    assert diags == []


def test_a_runtime_consumer_inside_a_class_method_preserves_the_test_docstring() -> None:
    diags = _check('''
        def test_widget():
            """Test widget."""
            assert widget()

        class Report:
            def description(self):
                return test_widget.__doc__
        ''')
    assert diags == []


def test_a_nested_reader_resolves_a_stable_module_alias() -> None:
    diags = _check('''
        def test_widget():
            """Test widget."""
            assert widget()

        published_test = test_widget

        def description():
            return published_test.__doc__
        ''')
    assert diags == []


def test_a_class_method_reader_resolves_a_stable_module_alias_chain() -> None:
    diags = _check('''
        def test_widget():
            """Test widget."""
            assert widget()

        published_test = test_widget
        documented_test = published_test

        class Report:
            def description(self):
                return inspect.getdoc(documented_test)
        ''')
    assert diags == []


def test_a_nested_parameter_does_not_consume_a_same_named_module_test_docstring() -> None:
    diags = _check('''
        def test_widget():
            """Test widget."""
            assert widget()

        def description(test_widget):
            return test_widget.__doc__
        ''')
    assert len(diags) == 1


def test_a_nested_local_definition_does_not_consume_a_module_test_docstring() -> None:
    diags = _check('''
        def test_widget():
            """Test widget."""
            assert widget()

        def description():
            def test_widget():
                return None
            return test_widget.__doc__
        ''')
    assert len(diags) == 1


def test_an_unrelated_attribute_does_not_consume_a_same_named_module_test_docstring() -> None:
    diags = _check('''
        def test_widget():
            """Test widget."""
            assert widget()

        def description(report):
            return report.test_widget.__doc__
        ''')
    assert len(diags) == 1


def test_exact_suppression_on_the_docstring_line_is_honored() -> None:
    diags = _check('''
        def test_connection():
            """Test connection."""  # sarj-noqa: SARJ088 — published by the test report
            assert connection()
        ''')
    assert diags == []


def test_exact_suppression_on_a_multiline_docstring_closing_line_is_honored() -> None:
    diags = _check('''
        def test_connection():
            """Test
            connection.
            """  # sarj-noqa: SARJ088 — published by the test report
            assert connection()
        ''')
    assert diags == []


def test_unrelated_suppression_does_not_hide_the_finding() -> None:
    diags = _check('''
        def test_connection():
            """Test connection."""  # sarj-noqa: SARJ050 — separate policy
            assert connection()
        ''')
    assert len(diags) == 1
