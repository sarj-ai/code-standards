from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.trivially_true_assertion import TriviallyTrueAssertion


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/app/tests/test_auth_generic.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return TriviallyTrueAssertion().check(Path(path), textwrap.dedent(source))


# The minimal source that this rule reports: a constructor keyword read straight back out.
_ECHO_TEST = """def test_thing():
    u = User(name="bo")
    assert u.name == "bo"
"""


# Path gating.                                                                 #


@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "a/tests/test_y.py"])
def test_fires_in_test_paths(path: str):
    assert len(_check(_ECHO_TEST, path)) == 1


@pytest.mark.parametrize("path", ["src/service.py", "a/testing/thing.py"])
def test_skips_non_test_paths(path: str):
    assert _check(_ECHO_TEST, path) == []


@pytest.mark.parametrize(
    "path",
    [
        "black/tests/data/cases/fmtonoff5.py",
        "tests/helpers.py",
        "tests/conftest.py",
        "scripts/test_probe.py",
    ],
)
def test_skips_modules_pytest_does_not_collect(path: str):
    assert _check(_ECHO_TEST, path) == []


# The boundary with SARJ057 `no-tautological-expect`.


@pytest.mark.parametrize(
    "condition",
    [
        "True",
        "1",
        "1.5",
        "...",
        "b'x'",
        "[1]",
        "[compute()]",
        "{1, 2}",
        "{'a': 1}",
        "(1, 2)",
        "not False",
        "not ''",
        "not 0",
        "not None",
        "-1",
        "'x'",
        "1 == 1",
    ],
    ids=[
        "true",
        "int",
        "float",
        "ellipsis",
        "bytes",
        "list",
        "list-of-calls",
        "set",
        "dict",
        "tuple",
        "not-false",
        "not-empty-string",
        "not-zero",
        "not-none",
        "signed-int",
        "string",
        "identical-literal-compare",
    ],
)
def test_literal_only_conditions_are_left_to_sarj057(condition: str):
    assert _check(f"def test_thing():\n    assert {condition}\n") == []


def test_a_literal_condition_with_a_message_is_left_to_sarj057():
    # The emulated_hue shape, `assert True, <the thing you meant to check>`: also
    # SARJ057's, which names the assertion-message slot in its message.
    assert _check('def test_thing():\n    assert True, "we got here"\n') == []


def test_a_literal_tautology_does_not_consume_the_one_finding_per_test():
    # The collapse below anchors at the *first* finding, so a ceded literal must
    # not become that anchor — the constructor echo two lines down is the finding.
    src = """
    def test_thing():
        assert True
        u = User(name="bo")
        assert u.name == "bo"
    """
    [diag] = _check(src)
    assert (diag.line, diag.col) == (5, 5)


@pytest.mark.parametrize(
    "condition",
    ["value == value", "'a' in ['a', 'b']"],
    ids=["self-comparison", "literal-membership"],
)
def test_ruff_owned_tautologies_are_not_duplicated(condition: str):
    assert _check(f"def test_thing(value):\n    assert {condition}\n") == []


# Shape 1: reading a constructor keyword straight back out.                     #


def test_flags_keyword_echo():
    assert len(_check(_ECHO_TEST)) == 1


def test_flags_keyword_echo_written_the_other_way_round():
    src = """
    def test_thing():
        payload = EncryptedPayload(jws_signature="sig-456")
        assert "sig-456" == payload.jws_signature
    """
    assert len(_check(src)) == 1


def test_a_test_that_echoes_several_fields_is_reported_once_at_the_first():
    # 45% of the estate-wide finding set used to be repeat lines inside a test
    # that was already flagged; the defect and its repair are one decision.
    src = """
    def test_thing():
        payload = EncryptedPayload(operation_key_id="key-123", jws_signature="sig-456")
        assert payload.operation_key_id == "key-123"
        assert payload.jws_signature == "sig-456"
    """
    [diag] = _check(src)
    assert diag.line == 4


def test_the_same_two_echoes_split_across_two_tests_are_reported_twice():
    src = """
    def test_key_id():
        payload = EncryptedPayload(operation_key_id="key-123")
        assert payload.operation_key_id == "key-123"

    def test_signature():
        payload = EncryptedPayload(jws_signature="sig-456")
        assert payload.jws_signature == "sig-456"
    """
    assert [d.line for d in _check(src)] == [4, 8]


def test_an_honest_assertion_alongside_an_echo_does_not_suppress_the_echo():
    # A stricter collapse — flag only when *every* assertion in the test is
    # trivial — was measured and costs 11 of a first-party repo's 17 findings,
    # because one honest assertion surrounded by echoes is the common real shape.
    src = """
    def test_thing(clock):
        payload = EncryptedPayload(jws_signature="sig-456")
        assert payload.jws_signature == "sig-456"
        assert payload.created_at > clock.start
    """
    assert len(_check(src)) == 1


def test_flags_identity_spelling_of_a_boolean_field():
    # A first-party integration test — `assert result.passed is False` after
    # `VerifyResult(passed=False, ...)`.
    src = """
    def test_thing():
        result = VerifyResult(passed=False)
        assert result.passed is False
    """
    assert len(_check(src)) == 1


def test_flags_a_dotted_constructor():
    src = """
    def test_thing():
        x = models.CalleeInput(phone_number="+1234567890")
        assert x.phone_number == "+1234567890"
    """
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "literal",
    ["[]", "{'trace_id': 'abc'}", "{'app/foo'}", "-1"],
    ids=["empty-list", "dict", "set", "negative-int"],
)
def test_flags_echoed_collection_and_signed_literals(literal: str):
    src = f"""
    def test_thing():
        rec = Registration(payload={literal})
        assert rec.payload == {literal}
    """
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "call",
    [
        "make_settings(ENV='staging')",
        "_worker_options(num_idle_processes=2)",
        "service.get_onboarding_error_details(limit=25)",
        "factory.create_client(language='ar')",
    ],
    ids=["module-helper", "private-helper", "service-method", "factory-method"],
)
def test_a_function_that_maps_its_arguments_is_not_a_constructor(call: str):
    # One first-party test reads an env var back through pydantic-settings; another checks that a service echoes pagination into its response envelope.
    field, value = ("ENV", "'staging'") if "ENV" in call else ("limit", "25")
    src = f"""
    def test_thing(service, factory):
        result = {call}
        assert result.{field} == {value}
    """
    assert _check(src) == []


def test_the_same_shape_with_a_capitalised_callee_fires():
    src = """
    def test_thing():
        result = Settings(ENV="staging")
        assert result.ENV == "staging"
    """
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "cls",
    [
        "CacheBackend",
        "OpenAIClient",
        "AnalyticsService",
        "TaskManager",
        "EventHandler",
        "ApiServer",
        "DatabaseSession",
        "ConnectionPool",
        "QueryEngine",
        "JobRunner",
        "TaskWorker",
        "OrganizationStore",
        "UserRepository",
        "ClientFactory",
        "RequestBuilder",
        "PaymentAdapter",
        "DatabaseConnection",
        "HttpTransport",
        "Receiver",
        "self.Backend",
    ],
)
def test_collaborator_classes_are_exempt(cls: str):
    # celery's cache backends run `expires=` through `prepare_expires`, so
    # t/unit/backends/test_cache.py:126 is a coercion test, not a tautology.
    src = f"""
    def test_thing(self):
        b = {cls}(expires=10)
        assert b.expires == 10
    """
    assert _check(src) == []


def test_a_record_class_with_the_same_field_still_fires():
    src = """
    def test_thing():
        b = RetentionPolicy(expires=10)
        assert b.expires == 10
    """
    assert len(_check(src)) == 1


def test_a_field_another_test_shows_coercing_is_exempt():
    # A first-party settings test — `model="lite"` is rewritten to
    # "flash-lite-3.1", so `test_valid_model_unchanged` is the negative half of
    # a validator test and genuinely can fail.
    src = """
    def test_lite_is_remapped():
        settings = GeminiLLMSettings(model="lite")
        assert settings.model == "flash-lite-3.1"

    def test_valid_model_unchanged():
        settings = GeminiLLMSettings(model="flash")
        assert settings.model == "flash"
    """
    assert _check(src) == []


def test_without_the_coercing_sibling_the_same_assertion_fires():
    src = """
    def test_valid_model_unchanged():
        settings = GeminiLLMSettings(model="flash")
        assert settings.model == "flash"
    """
    assert len(_check(src)) == 1


def test_coercion_evidence_is_scoped_to_the_field():
    src = """
    def test_lite_is_remapped():
        settings = GeminiLLMSettings(model="lite")
        assert settings.model == "flash-lite-3.1"

    def test_provider_kept():
        settings = GeminiLLMSettings(provider="gemini")
        assert settings.provider == "gemini"
    """
    assert len(_check(src)) == 1


def test_coercion_evidence_is_scoped_to_the_class():
    src = """
    def test_lite_is_remapped():
        settings = GeminiLLMSettings(model="lite")
        assert settings.model == "flash-lite-3.1"

    def test_other_model_kept():
        settings = OpenAISettings(model="flash")
        assert settings.model == "flash"
    """
    assert len(_check(src)) == 1


def test_distinct_echoed_literals_do_not_imply_coercion():
    src = """
    def test_first_wire_spelling():
        response = DeleteContainerFileResponse(object="container.file.deleted")
        assert response.object == "container.file.deleted"

    def test_second_wire_spelling():
        response = DeleteContainerFileResponse(object="container_file.deleted")
        assert response.object == "container_file.deleted"
    """
    assert len(_check(src)) == 2


@pytest.mark.parametrize(
    ("given", "asserted"),
    [
        ("value='A@B.com'", "e.value == 'a@b.com'"),
        ("count=0", "e.count is False"),
        ("count=1", "e.count == 1.0"),
        ("name='A B'", "e.slug == 'a-b'"),
        ("name='bo'", "e.title == 'bo'"),
    ],
    ids=["case-coerced", "bool-for-int", "float-for-int", "derived-field", "renamed-field"],
)
def test_a_transformed_value_or_a_renamed_field_is_exempt(given: str, asserted: str):
    src = f"""
    def test_thing():
        e = Email({given})
        assert {asserted}
    """
    assert _check(src) == []


@pytest.mark.parametrize(
    ("given", "asserted"),
    [("value='a@b.com'", "e.value == 'a@b.com'"), ("count=0", "e.count == 0")],
    ids=["identical-string", "identical-int"],
)
def test_a_structurally_identical_literal_fires(given: str, asserted: str):
    src = f"""
    def test_thing():
        e = Email({given})
        assert {asserted}
    """
    assert len(_check(src)) == 1


def test_a_dunder_attribute_is_exempt():
    # celery t/unit/utils/test_local.py:31 — a lazy proxy resolving `__doc__`
    # goes through descriptor machinery, not plain assignment.
    src = """
    def test_doc():
        x = Proxy(__doc__='foo')
        assert x.__doc__ == 'foo'
    """
    assert _check(src) == []


def test_a_plain_attribute_of_the_same_class_fires():
    src = """
    def test_doc():
        x = Proxy(doc='foo')
        assert x.doc == 'foo'
    """
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    ("given", "asserted"),
    [("name=name", "u.name == name"), ("name='bo'", "u.name == expected")],
    ids=["non-literal-keyword", "non-literal-expectation"],
)
def test_a_non_literal_on_either_side_is_exempt(given: str, asserted: str):
    # A `@given(...)` property test hands the constructor a generated value, so
    # this also covers hypothesis.
    src = f"""
    def test_thing(name, expected):
        u = User({given})
        assert {asserted}
    """
    assert _check(src) == []


def test_a_serialisation_round_trip_is_exempt():
    src = """
    def test_thing():
        payload = {"id": 1, "name": "bo"}
        assert User(**payload).model_dump() == payload
    """
    assert _check(src) == []


@pytest.mark.parametrize(
    "operator",
    ["!=", ">", "<="],
    ids=["not-equal", "greater", "less-equal"],
)
def test_a_non_echo_operator_is_exempt(operator: str):
    src = f"""
    def test_thing():
        u = User(count=1)
        assert u.count {operator} 1
    """
    assert _check(src) == []


@pytest.mark.parametrize(
    "meddling",
    [
        "u = User(name='other')",
        "save(u)",
        "u.refresh()",
        "u.name = 'other'",
        "del u",
        "copy = u",
        "print(u.name)",
        "for u in users: pass",
    ],
    ids=[
        "rebound",
        "passed-to-a-function",
        "method-called",
        "attribute-assigned",
        "deleted",
        "aliased",
        "read-outside-an-assert",
        "loop-target",
    ],
)
def test_any_other_mention_of_the_local_is_disqualifying(meddling: str):
    src = f"""
    def test_thing(users):
        u = User(name='bo')
        {meddling}
        assert u.name == 'bo'
    """
    assert _check(src) == []


def test_a_method_called_on_the_local_inside_an_assertion_is_disqualifying():
    # The `assert` wrapper does not make the call safe: `model_dump()` runs arbitrary code on the object before the field below is read.
    src = """
    def test_thing():
        u = User(name='bo')
        assert u.model_dump() == {'name': 'bo'}
        assert u.name == 'bo'
    """
    assert _check(src) == []


def test_an_untouched_local_fires():
    src = """
    def test_thing(users):
        u = User(name='bo')
        assert u.name == 'bo'
    """
    assert len(_check(src)) == 1


def test_a_parameter_shadowing_the_name_is_exempt():
    src = """
    def test_thing(u):
        u = User(name='bo')
        assert u.name == 'bo'
    """
    assert _check(src) == []


def test_a_global_name_is_exempt():
    src = """
    def test_thing():
        global user
        user = User(name='bo')
        assert user.name == 'bo'
    """
    assert _check(src) == []


def test_a_nonlocal_name_is_exempt():
    src = """
    def outer():
        user = None

        def test_thing():
            nonlocal user
            user = User(name='bo')
            assert user.name == 'bo'
    """
    assert _check(src) == []


def test_a_read_from_a_nested_closure_disqualifies_the_outer_local():
    src = """
    def test_thing():
        user = User(name='bo')

        def read_user():
            return user

        assert user.name == 'bo'
    """
    assert _check(src) == []


def test_an_assertion_above_the_construction_is_exempt():
    src = """
    def test_thing(u):
        assert other.name == 'bo'
        other = User(name='bo')
    """
    assert _check(src) == []


def test_a_tuple_unpacking_target_is_exempt():
    src = """
    def test_thing():
        u, v = build_pair(name='bo')
        assert u.name == 'bo'
    """
    assert _check(src) == []


# Shape 2: isinstance against the class that was just called.                   #


def test_flags_isinstance_of_the_class_just_constructed():
    # celery t/unit/worker/test_request.py:1534.
    src = """
    def test_from_message_empty_args(self):
        job = Request(m, app=self.app)
        assert isinstance(job, Request)
    """
    assert len(_check(src)) == 1


def test_flags_isinstance_with_a_dotted_class():
    src = """
    def test_thing():
        job = worker.Request(m)
        assert isinstance(job, worker.Request)
    """
    assert len(_check(src)) == 1


def test_isinstance_that_narrows_for_a_later_assertion_is_exempt():
    # basedpyright strict needs this to prove the reads below are well-typed;
    # deleting it breaks the build.
    src = """
    def test_thing(m):
        job = Request(m)
        assert isinstance(job, Request)
        assert job.name == m.name
    """
    assert _check(src) == []


def test_isinstance_with_only_earlier_assertions_still_fires():
    src = """
    def test_thing(m):
        assert m.ready
        job = Request(m)
        assert isinstance(job, Request)
    """
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    ("construction", "checked"),
    [
        ("Request.from_message(m)", "Request"),
        ("make_request(m)", "Request"),
        ("Request(m)", "BaseRequest"),
        ("Request(m)", "(Request, BaseRequest)"),
    ],
    ids=["factory-classmethod", "factory-function", "different-class", "class-tuple"],
)
def test_isinstance_that_checks_something_real_is_exempt(construction: str, checked: str):
    src = f"""
    def test_thing(m):
        job = {construction}
        assert isinstance(job, {checked})
    """
    assert _check(src) == []


def test_isinstance_of_a_name_the_test_did_not_construct_is_exempt():
    src = """
    def test_thing(job):
        assert isinstance(job, Request)
    """
    assert _check(src) == []


# Edge cases and diagnostic shape.                                             #


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"], ids=["empty", "blank", "comment"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check('def test_x(:\n    u = User(name="bo")\n    assert u.name == "bo"\n') == []


def test_reports_line_column_and_code():
    [diag] = _check(_ECHO_TEST)
    assert (diag.line, diag.col, diag.code) == (3, 5, "SARJ064")


def test_reports_the_position_of_a_finding_nested_in_a_class_and_a_with_block():
    src = """
    class TestPayload:
        def test_fields(self):
            with freeze_time("2026-01-01"):
                payload = EncryptedPayload(jws_signature="sig-456")
                assert payload.jws_signature == "sig-456"
    """
    [diag] = _check(src)
    assert (diag.line, diag.col) == (6, 13)


def test_each_assertion_is_reported_once():
    src = """
    def test_thing():
        u = User(name="bo")
        assert isinstance(u, User)
    """
    assert len(_check(src)) == 1


def test_diagnostics_are_sorted_by_position():
    src = """
    def test_a():
        u = User(name="bo")
        assert u.name == "bo"

    def test_b():
        job = Request(m)
        assert isinstance(job, Request)

    def test_c():
        p = Payload(kind="sms")
        assert "sms" == p.kind
    """
    assert [(d.line, d.col) for d in _check(src)] == [(4, 5), (8, 5), (12, 5)]


# The message, and the conflict with SARJ043 it has to avoid.                  #


_ORDINARY_ADVICE = ". Assert on something the code under test derived, or drop the assertion"

_SARJ043_ADVICE = (
    ". Every assertion this test makes is like it, so dropping them would leave a test that verifies "
    "nothing, which SARJ043 (`zero-assertion-test`) rejects in turn. Assert the behaviour the test name "
    "claims to cover, or delete the test"
)


_KWARG_DIAGNOSIS = (
    "this reads back the literal the test just handed the constructor, so it can only fail if attribute "
    "assignment stops working"
)

_ISINSTANCE_DIAGNOSIS = (
    "the value was produced by calling this very class a line above, so the `isinstance` check pins the "
    "language rather than the code"
)

_SURVIVING_ASSERTION = "    assert clock.now() > 0\n"


@pytest.mark.parametrize(
    ("source", "diagnosis"),
    [
        (
            f'def test_thing(clock):\n    u = User(name="bo")\n    assert u.name == "bo"\n{_SURVIVING_ASSERTION}',
            _KWARG_DIAGNOSIS,
        ),
        (
            f"def test_thing(clock):\n    u = User()\n    assert isinstance(u, User)\n{_SURVIVING_ASSERTION}",
            _ISINSTANCE_DIAGNOSIS,
        ),
    ],
    ids=["keyword-echo", "isinstance"],
)
def test_each_shape_states_its_diagnosis_and_the_ordinary_advice(source: str, diagnosis: str):
    [diag] = _check(source)
    assert diag.message == diagnosis + _ORDINARY_ADVICE


def test_a_test_whose_every_assertion_is_trivial_is_not_told_to_drop_it():
    # SARJ043 (`zero-assertion-test`) flags a test with no assertions, so "drop
    # the assertion" would be an instruction straight into another diagnostic.
    src = """
    def test_thing():
        u = User(name="bo")
        assert u.name == "bo"
    """
    [diag] = _check(src)
    assert diag.message.endswith(_SARJ043_ADVICE)
    assert "drop the assertion" not in diag.message


def test_a_test_that_keeps_a_falsifiable_assertion_is_told_to_drop_the_line():
    src = """
    def test_thing(clock):
        u = User(name="bo")
        assert u.name == "bo"
        assert u.created_at > clock.start
    """
    [diag] = _check(src)
    assert diag.message.endswith(_ORDINARY_ADVICE)
    assert "SARJ043" not in diag.message


def test_fires_inside_a_test_class():
    src = """
    class TestPayload:
        def test_fields(self):
            payload = EncryptedPayload(jws_signature="sig-456")
            assert payload.jws_signature == "sig-456"
    """
    assert len(_check(src)) == 1


def test_fires_inside_a_loop_body():
    # A first-party test site — the loop varies `name`,
    # so asserting the unvaried `phone_number` is still pure echo.
    src = """
    def test_thing(names):
        for name in names:
            callee = CalleeInput(phone_number="+1234567890", name=name)
            assert callee.phone_number == "+1234567890"
            assert callee.name == name
    """
    assert len(_check(src)) == 1
