from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_patching_system_under_test import NoPatchingSystemUnderTest


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


TEST_PATH = "python/bulbul/tests/unit/test_billing.py"


def _check(source: str, path: str = TEST_PATH) -> list[Diagnostic]:
    return NoPatchingSystemUnderTest().check(Path(path), textwrap.dedent(source))


# Shape 1: patch a sibling of the symbol the test imports and runs.
_SIBLING = """
from unittest.mock import patch

from app.billing import apply_discount, compute_invoice


@patch("app.billing.apply_discount")
def test_compute_invoice(mock_discount):
    assert compute_invoice(order) == 10
"""

# Shape 2: build the unit, cut a method out of it, drive what is left.
_HOLLOW_OBJECT = """
from unittest import mock

from app.billing import Invoice


def test_total():
    invoice = Invoice(lines)
    with mock.patch.object(invoice, "line_total"):
        assert invoice.total() == 5
"""


# --------------------------------------------------------------------------- #
# Path gating and parse failures.                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("source", [_SIBLING, _HOLLOW_OBJECT], ids=["sibling", "hollow-object"])
@pytest.mark.parametrize("path", ["test_x.py", "x_test.py", "a/tests/test_y.py", "a/tests/helpers.py"])
def test_fires_in_test_paths(source: str, path: str):
    assert len(_check(source, path)) == 1


@pytest.mark.parametrize("source", [_SIBLING, _HOLLOW_OBJECT], ids=["sibling", "hollow-object"])
@pytest.mark.parametrize("path", ["src/billing.py", "app/testing/thing.py"])
def test_skips_non_test_paths(source: str, path: str):
    assert _check(source, path) == []


def test_syntax_error_returns_no_diagnostics():
    assert _check("from unittest.mock import patch\ndef test_x(:\n    pass\n") == []


@pytest.mark.parametrize("source", ["", "  \n\n ", "# comment\n"], ids=["empty", "blank", "comment"])
def test_empty_source_is_clean(source: str):
    assert _check(source) == []


# --------------------------------------------------------------------------- #
# Positives.                                                                   #
# --------------------------------------------------------------------------- #


def test_flags_patched_sibling_of_the_symbol_under_test():
    assert len(_check(_SIBLING)) == 1


def test_flags_method_cut_out_of_the_object_under_test():
    assert len(_check(_HOLLOW_OBJECT)) == 1


def test_flags_class_level_patch_with_the_instance_built_in_the_same_test():
    # celery/t/unit/backends/test_gcs.py:105 — every GCSBackend method test
    # mocks two or three sibling methods of the backend it then constructs.
    src = """
    from unittest.mock import patch

    from celery.backends.gcs import GCSBackend


    @patch.object(GCSBackend, "_get_blob")
    def test_get_key(mock_get_blob):
        backend = GCSBackend(app=None)
        backend.get(b"testkey1")
        mock_get_blob.assert_called_once_with("testkey1")
    """
    assert len(_check(src)) == 1


def test_flags_private_sibling_method_of_the_object_under_test():
    src = """
    from unittest import mock

    from django.db.backends.oracle.creation import DatabaseCreation


    def test_create_test_db():
        creation = DatabaseCreation(connection)
        with mock.patch.object(creation, "_test_user_create"):
            creation._create_test_db(verbosity=0)
    """
    assert len(_check(src)) == 1


def test_flags_a_helper_that_is_not_named_test():
    # django/tests/auth_tests/test_hashers.py:462 patches two hashers siblings
    # inside a `@contextmanager` helper on the TestCase, not inside a `test_*`.
    src = """
    from contextlib import contextmanager
    from unittest import mock

    from django.contrib.auth.hashers import check_password, identify_hasher


    @contextmanager
    def assert_identify_called():
        with mock.patch("django.contrib.auth.hashers.identify_hasher"):
            check_password("letmein", encoded)
            yield
    """
    assert len(_check(src)) == 1


def test_message_names_the_patched_target():
    [diag] = _check(_HOLLOW_OBJECT)
    assert "`Invoice.line_total`" in diag.message


def test_message_names_the_dotted_target_for_a_sibling_patch():
    [diag] = _check(_SIBLING)
    assert "`app.billing.apply_discount`" in diag.message


def test_message_is_reported_verbatim():
    [diag] = _check(_SIBLING)
    assert diag.message == (
        "this patches `app.billing.apply_discount`, which belongs to the unit this test then "
        "exercises, so the real code path never runs and the assertions only describe the mock. "
        "Patch at the boundary the unit talks to instead, or exercise the real method."
    )


def test_reports_line_and_column_of_the_patch_call():
    [diag] = _check(_SIBLING)
    assert (diag.line, diag.col) == (7, 2)
    assert diag.code == "SARJ061"


def test_reports_the_position_of_a_patch_nested_in_a_class_and_a_with_block():
    # Both coordinates are far from 1, so neither a hardcoded line nor a
    # hardcoded column survives this.
    src = """
    from unittest import mock

    from app.billing import Invoice


    class TestInvoice:
        def test_total(self):
            invoice = Invoice(lines)
            with mock.patch.object(invoice, "line_total"):
                assert invoice.total() == 5
    """
    [diag] = _check(src)
    assert (diag.line, diag.col) == (10, 14)


def test_multiple_hits_in_one_file_are_sorted_by_position():
    src = """
    from unittest.mock import patch

    from app.billing import apply_discount, compute_invoice, round_cents


    @patch("app.billing.round_cents")
    @patch("app.billing.apply_discount")
    def test_one(a, b):
        assert compute_invoice(order) == 10


    @patch("app.billing.apply_discount")
    def test_two(a):
        assert compute_invoice(order) == 11
    """
    diags = _check(src)
    assert len(diags) == 3
    assert [d.line for d in diags] == sorted(d.line for d in diags)


# --------------------------------------------------------------------------- #
# Reaching `unittest.mock`. The name is only trusted when an import backs it.  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("imports", "call"),
    [
        ("from unittest.mock import patch", 'patch("app.billing.apply_discount")'),
        ("from unittest.mock import patch as mpatch", 'mpatch("app.billing.apply_discount")'),
        ("from unittest import mock", 'mock.patch("app.billing.apply_discount")'),
        ("from unittest import mock as m", 'm.patch("app.billing.apply_discount")'),
        ("import unittest.mock", 'unittest.mock.patch("app.billing.apply_discount")'),
        ("import unittest.mock as um", 'um.patch("app.billing.apply_discount")'),
    ],
    ids=["from-patch", "aliased-patch", "from-mock", "aliased-mock", "dotted", "aliased-dotted"],
)
def test_every_mock_import_spelling_is_recognised(imports: str, call: str):
    src = f"""
    {imports}

    from app.billing import apply_discount, compute_invoice


    def test_compute_invoice():
        with {call}:
            assert compute_invoice(order) == 10
    """
    assert len(_check(src)) == 1


def test_a_patch_no_mock_import_backs_is_ignored():
    src = """
    from myproject.testing import patch

    from app.billing import apply_discount, compute_invoice


    @patch("app.billing.apply_discount")
    def test_compute_invoice(mock_discount):
        assert compute_invoice(order) == 10
    """
    assert _check(src) == []


def test_a_project_local_patch_shadowing_the_import_is_ignored():
    # The file reaches `unittest.mock`, but the bare `patch` name is the
    # project's own helper — only import-backed names are trusted.
    src = """
    from unittest import mock

    from myproject.testing import patch

    from app.billing import apply_discount, compute_invoice


    @patch("app.billing.apply_discount")
    def test_compute_invoice(mock_discount):
        assert compute_invoice(order) == 10
    """
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: "patch where it's used". The target string names the SUT module,   #
# but the attribute is a dependency the SUT merely imported. 112 corpus hits.  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "target",
    [
        "app.billing.requests",
        "app.billing.build_report",
        "app.billing.sessionmaker",
        "app.billing.add_span_attributes",
    ],
    ids=["third-party", "not-imported-here", "sqlalchemy", "telemetry-helper"],
)
def test_attribute_the_test_file_does_not_import_is_exempt(target: str):
    src = f"""
    from unittest.mock import patch

    from app.billing import compute_invoice


    @patch("{target}")
    def test_compute_invoice(mock_dep):
        assert compute_invoice(order) == 10
    """
    assert _check(src) == []


def test_the_same_attribute_imported_here_does_fire():
    src = """
    from unittest.mock import patch

    from app.billing import build_report, compute_invoice


    @patch("app.billing.build_report")
    def test_compute_invoice(mock_report):
        assert compute_invoice(order) == 10
    """
    assert len(_check(src)) == 1


def test_a_module_this_file_never_imports_from_is_exempt():
    src = """
    from unittest.mock import patch

    from app.billing import compute_invoice


    @patch("app.pricing.apply_discount")
    def test_compute_invoice(mock_discount):
        assert compute_invoice(order) == 10
    """
    assert _check(src) == []


def test_a_relative_import_cannot_prove_the_module_and_is_exempt():
    # `from .helpers import ...` binds `node.module == "helpers"`, which would
    # match the target string `helpers.compute` if the relative-import guard were
    # dropped — but `.helpers` is not the top-level `helpers` package.
    src = """
    from unittest.mock import patch

    from .helpers import compute, render


    @patch("helpers.compute")
    def test_render(mock_compute):
        assert render(1) == 10
    """
    assert _check(src) == []


def test_the_same_shape_with_an_absolute_import_does_fire():
    src = """
    from unittest.mock import patch

    from helpers import compute, render


    @patch("helpers.compute")
    def test_render(mock_compute):
        assert render(1) == 10
    """
    assert len(_check(src)) == 1


def test_module_whose_other_imports_are_never_called_is_exempt():
    # Nothing this file imported from `app.billing` is exercised, so the module
    # is a dependency of the test, not the unit under test.
    src = """
    from unittest.mock import patch

    from app.billing import apply_discount, compute_invoice


    @patch("app.billing.apply_discount")
    def test_compute_invoice(mock_discount):
        assert mock_discount is not None
    """
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: the proof that <mod> is the unit under test must live in the same  #
# function as the patch. Pooling it file-wide let one test license another's   #
# unrelated patch — the largest FP class at scale (196 of 1,968 corpus hits).  #
# --------------------------------------------------------------------------- #


def test_a_sibling_tests_call_does_not_license_the_patch():
    # litellm test_health_check_allowed_fails_integration.py:661 — the patch
    # exercises `app.pricing`, and the only call into `app.billing` is in a
    # different test entirely.
    src = """
    from unittest.mock import patch

    from app.billing import apply_discount, compute_invoice
    from app.pricing import quote


    def test_compute_invoice():
        assert compute_invoice(order) == 10


    @patch("app.billing.apply_discount")
    def test_quote(mock_discount):
        assert quote(order) == 3
    """
    assert _check(src) == []


def test_the_same_call_inside_the_patching_function_does_fire():
    src = """
    from unittest.mock import patch

    from app.billing import apply_discount, compute_invoice
    from app.pricing import quote


    @patch("app.billing.apply_discount")
    def test_quote(mock_discount):
        assert compute_invoice(order) == 10
        assert quote(order) == 3
    """
    assert len(_check(src)) == 1


def test_the_unit_reached_through_a_module_alias_is_evidence():
    # airflow/airflow-core/tests/unit/security/test_kerberos.py:306 — `run` is a
    # member of the patched module but the test never imports it by name, so the
    # only proof it enters the module is the `kerberos.` receiver.
    src = """
    from unittest import mock

    from airflow.security import kerberos
    from airflow.security.kerberos import detect_conf_var, renew_from_kt


    @mock.patch("airflow.security.kerberos.renew_from_kt")
    def test_run(mock_renew):
        kerberos.run(principal="test-principal", keytab="/tmp/keytab")
        assert mock_renew.mock_calls == [mock.call("test-principal", "/tmp/keytab")]
    """
    assert len(_check(src)) == 1


def test_an_aliased_import_resolves_to_the_module_it_names():
    src = """
    from unittest import mock

    import mlflow.utils.databricks_utils as databricks_utils
    from mlflow.utils.databricks_utils import get_workspace_id, get_workspace_url


    def test_deployment_job_url():
        with mock.patch("mlflow.utils.databricks_utils.get_workspace_id", return_value=456):
            assert databricks_utils.build_deployment_job_url(job_id=123)
    """
    assert len(_check(src)) == 1


def test_an_alias_for_a_different_module_is_not_evidence():
    src = """
    from unittest import mock

    from airflow.security import krb5
    from airflow.security.kerberos import detect_conf_var, renew_from_kt


    @mock.patch("airflow.security.kerberos.renew_from_kt")
    def test_run(mock_renew):
        krb5.run(principal="test-principal", keytab="/tmp/keytab")
        assert mock_renew.mock_calls
    """
    assert _check(src) == []


def test_patching_the_only_symbol_imported_is_exempt():
    # `apply_discount` is the sole import: there is no sibling being exercised,
    # so this is a test of the patcher's own plumbing, not of a unit.
    src = """
    from unittest.mock import patch

    from app.billing import apply_discount


    @patch("app.billing.apply_discount")
    def test_apply_discount(mock_discount):
        assert apply_discount(order) is mock_discount.return_value
    """
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: only plain function-shaped names are the unit's own logic.         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("attr", "imported"),
    [
        ("Invoice", "Invoice"),
        ("_CollectViaDtmfTask", "_CollectViaDtmfTask"),
        ("MAX_RETRIES", "MAX_RETRIES"),
        ("__init__", "Invoice"),
        ("__call__", "Invoice"),
    ],
    ids=["class", "private-class", "constant", "dunder-init", "dunder-call"],
)
def test_class_constant_and_dunder_targets_are_exempt(attr: str, imported: str):
    src = f"""
    from unittest.mock import patch

    from app.billing import compute_invoice, {imported}


    @patch("app.billing.{attr}")
    def test_compute_invoice(mock_dep):
        assert compute_invoice(order) == 10
    """
    assert _check(src) == []


@pytest.mark.parametrize(
    "attr",
    ["apply_discount", "_apply_discount", "discount"],
    ids=["snake", "private-snake", "single-word"],
)
def test_plain_function_names_do_fire(attr: str):
    src = f"""
    from unittest.mock import patch

    from app.billing import compute_invoice, {attr}


    @patch("app.billing.{attr}")
    def test_compute_invoice(mock_dep):
        assert compute_invoice(order) == 10
    """
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "attr",
    ["stripe_client", "session", "db_pool", "http_session", "broker", "redis", "logger", "result_cache"],
    ids=["client", "session", "pool", "http", "broker", "redis", "logger", "cache"],
)
def test_boundary_shaped_names_are_exempt(attr: str):
    src = f"""
    from unittest.mock import patch

    from app.billing import compute_invoice, {attr}


    @patch("app.billing.{attr}")
    def test_compute_invoice(mock_dep):
        assert compute_invoice(order) == 10
    """
    assert _check(src) == []


def test_a_name_merely_containing_a_boundary_word_still_fires():
    # `session_total` is a computation, not a handle: the boundary words only
    # match as the trailing segment.
    src = """
    from unittest.mock import patch

    from app.billing import compute_invoice, session_total


    @patch("app.billing.session_total")
    def test_compute_invoice(mock_total):
        assert compute_invoice(order) == 10
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: a snake_case name the file only ever drives through its attributes  #
# is a module singleton, and swapping one is the DI seam. 76 corpus hits.       #
# --------------------------------------------------------------------------- #


def test_a_module_singleton_driven_through_its_attributes_is_exempt():
    # `global_mcp_server_manager: MCPServerManager = MCPServerManager()` is
    # patched 83 times across two litellm suites, always as an object.
    src = """
    from unittest.mock import patch

    from app.billing import compute_invoice, invoice_registry


    def test_compute_invoice():
        with patch("app.billing.invoice_registry") as mock_registry:
            assert compute_invoice(order) == 10
        mock_registry.expand.assert_called_once()


    def test_registry_starts_empty():
        assert invoice_registry.entries == []
    """
    assert _check(src) == []


def test_a_name_the_file_also_calls_bare_is_not_a_singleton():
    # `build_report.cache_clear()` makes it an attribute receiver too, so the
    # veto has to turn on the *absence* of a bare call, not the receiver alone.
    src = """
    from unittest.mock import patch

    from app.billing import build_report, compute_invoice


    def test_compute_invoice():
        with patch("app.billing.build_report") as mock_report:
            assert compute_invoice(order) == 10
        mock_report.assert_called_once()


    def test_build_report_directly():
        build_report.cache_clear()
        assert build_report(order) == 1
    """
    assert len(_check(src)) == 1


def test_a_name_that_is_never_a_receiver_is_not_a_singleton():
    src = """
    from unittest.mock import patch

    from app.billing import build_report, compute_invoice


    def test_compute_invoice():
        with patch("app.billing.build_report") as mock_report:
            assert compute_invoice(order) == 10
        mock_report.assert_called_once()
    """
    assert len(_check(src)) == 1


def test_dunder_method_of_the_object_under_test_is_exempt():
    src = """
    from unittest import mock

    from app.billing import Invoice


    def test_total():
        invoice = Invoice(lines)
        with mock.patch.object(invoice, "__len__"):
            assert invoice.total() == 5
    """
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: a concrete replacement is a hand-written substitute, not a mock.   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        'patch("app.billing.apply_discount", fake_discount)',
        'patch("app.billing.apply_discount", new=fake_discount)',
        'patch("app.billing.apply_discount", new_callable=FakeDiscount)',
        'patch("app.billing.apply_discount", wraps=apply_discount)',
        'patch("app.billing.apply_discount", **patch_kwargs)',
        'patch("app.billing.apply_discount", *patch_args)',
    ],
    ids=["positional-new", "new", "new-callable", "wraps", "kwargs", "starargs"],
)
def test_a_concrete_replacement_is_exempt(call: str):
    src = f"""
    from unittest.mock import patch

    from app.billing import apply_discount, compute_invoice


    def test_compute_invoice():
        with {call}:
            assert compute_invoice(order) == 10
    """
    assert _check(src) == []


@pytest.mark.parametrize(
    "call",
    [
        'patch("app.billing.apply_discount")',
        'patch("app.billing.apply_discount", return_value=10)',
        'patch("app.billing.apply_discount", autospec=True)',
        'patch("app.billing.apply_discount", side_effect=[10, 20])',
        'patch("app.billing.apply_discount", side_effect=canned_answers)',
    ],
    ids=["bare", "return-value", "autospec", "side-effect-list", "side-effect-name"],
)
def test_an_auto_generated_mock_does_fire(call: str):
    src = f"""
    from unittest.mock import patch

    from app.billing import apply_discount, compute_invoice


    def test_compute_invoice():
        with {call}:
            assert compute_invoice(order) == 10
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: a mock that raises is a tripwire or a fault injector, never a       #
# stand-in for the real answer, and the caller's path does run. 30 corpus hits. #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "side_effect",
    [
        "ValueError",
        'RuntimeError("boom")',
        'AssertionError("Should not be called")',
        'Exception("connection failed")',
        "SystemExit",
        "asyncio.TimeoutError",
        "ExpectedException()",
    ],
    ids=["class", "instance", "tripwire", "bare-exception", "exit", "dotted", "test-local"],
)
def test_a_side_effect_that_raises_is_exempt(side_effect: str):
    # django/tests/logging_tests/tests.py:570 proves `emit` short-circuits when
    # ADMINS is empty; prefect test_send_entrypoint_logs.py:115 is literally
    # named `test_silently_swallows_exceptions`.
    src = f"""
    from unittest.mock import patch

    from app.billing import apply_discount, compute_invoice


    def test_compute_invoice():
        with patch("app.billing.apply_discount", side_effect={side_effect}):
            assert compute_invoice(order) == 10
    """
    assert _check(src) == []


def test_a_raising_side_effect_on_the_object_under_test_is_also_exempt():
    # airflow test_manager.py:1302 — `patch.object(manager,
    # "persist_parsing_result", side_effect=RuntimeError("boom"))`.
    src = """
    from unittest import mock

    from app.billing import Invoice


    def test_total():
        invoice = Invoice(lines)
        with mock.patch.object(invoice, "line_total", side_effect=RuntimeError("boom")):
            assert invoice.total() == 5
    """
    assert _check(src) == []


def test_a_side_effect_delegating_to_the_real_symbol_is_a_spy():
    # django/tests/queries/test_iterator.py:29 — `side_effect=cursor_iter`
    # alongside `patch(".....compiler.cursor_iter")` keeps the real behaviour
    # and only counts calls.
    src = """
    from unittest import mock

    from django.db.models.sql.compiler import cursor_iter, execute_sql


    def test_default_iterator_chunk_size():
        with mock.patch(
            "django.db.models.sql.compiler.cursor_iter", side_effect=cursor_iter
        ) as cursor_iter_mock:
            execute_sql(qs)
        assert cursor_iter_mock.call_count == 1
    """
    assert _check(src) == []


def test_a_side_effect_delegating_to_the_patched_method_is_a_spy():
    # django/tests/auth_tests/test_hashers.py:221.
    src = """
    from unittest import mock

    from django.contrib.auth.hashers import get_hasher


    def test_bcrypt_harden_runtime():
        hasher = get_hasher("bcrypt")
        with mock.patch.object(hasher, "encode", side_effect=hasher.encode):
            hasher.harden_runtime("wrong_password", encoded)
    """
    assert _check(src) == []


def test_a_side_effect_naming_a_different_object_still_fires():
    src = """
    from unittest import mock

    from django.contrib.auth.hashers import get_hasher


    def test_bcrypt_harden_runtime():
        hasher = get_hasher("bcrypt")
        with mock.patch.object(hasher, "encode", side_effect=other.encode):
            hasher.harden_runtime("wrong_password", encoded)
    """
    assert len(_check(src)) == 1


def test_patch_object_with_a_positional_replacement_is_exempt():
    src = """
    from unittest import mock

    from app.billing import Invoice


    def test_total():
        invoice = Invoice(lines)
        with mock.patch.object(invoice, "line_total", fake_line_total):
            assert invoice.total() == 5
    """
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: monkeypatch always installs an author-written substitute.          #
# 464 call sites across bulbul and noura-be; flagging them would bury the      #
# signal, and a hand-rolled fake is what this rule steers toward anyway.       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "call",
    [
        'monkeypatch.setattr("app.billing.apply_discount", fake_discount)',
        'monkeypatch.setattr(Invoice, "line_total", fake_line_total)',
        'monkeypatch.setattr(invoice, "line_total", fake_line_total)',
    ],
    ids=["string-target", "class-target", "instance-target"],
)
def test_monkeypatch_setattr_is_exempt(call: str):
    src = f"""
    from unittest import mock

    from app.billing import Invoice, apply_discount, compute_invoice


    def test_total(monkeypatch):
        invoice = Invoice(lines)
        {call}
        assert invoice.total() == compute_invoice(order)
    """
    assert _check(src) == []


def test_the_same_shape_through_mock_patch_object_does_fire():
    src = """
    from unittest import mock

    from app.billing import Invoice, apply_discount, compute_invoice


    def test_total(monkeypatch):
        invoice = Invoice(lines)
        with mock.patch.object(invoice, "line_total"):
            assert invoice.total() == compute_invoice(order)
    """
    assert len(_check(src)) == 1


# --------------------------------------------------------------------------- #
# FP guard: the patched object must be a production type, not a test stub or  #
# a stdlib object the test happens to hold.                                    #
# --------------------------------------------------------------------------- #


def test_stdlib_object_is_exempt():
    # django/tests/user_commands/tests.py:454 — a StringIO buffer, patched
    # while `management.call_command(...)` is the actual unit under test.
    src = """
    from io import StringIO
    from unittest import mock


    def test_outputwrapper_flush():
        out = StringIO()
        with mock.patch.object(out, "flush"):
            call_command("outputwrapper", stdout=out)
        assert out.getvalue()
    """
    assert _check(src) == []


def test_the_same_shape_on_a_project_type_does_fire():
    src = """
    from unittest import mock

    from app.io import OutputBuffer


    def test_outputwrapper_flush():
        out = OutputBuffer()
        with mock.patch.object(out, "flush"):
            call_command("outputwrapper", stdout=out)
        assert out.getvalue()
    """
    assert len(_check(src)) == 1


def test_class_defined_in_the_test_file_is_exempt():
    # django/tests/test_utils/tests.py:2460 — `DoNothingDecorator` is a stub
    # subclass declared right above the test that patches it.
    src = """
    from unittest import mock


    class CustomStorage:
        def save(self, name):
            return name


    def test_validate_before_get_available_name():
        s = CustomStorage()
        with mock.patch.object(s, "get_available_name"):
            s.save("bad/name")
    """
    assert _check(src) == []


def test_the_same_class_imported_from_production_does_fire():
    src = """
    from unittest import mock

    from app.storage import CustomStorage


    def test_validate_before_get_available_name():
        s = CustomStorage()
        with mock.patch.object(s, "get_available_name"):
            s.save("bad/name")
    """
    assert len(_check(src)) == 1


def test_factory_defined_in_the_test_file_is_exempt():
    # django/tests/backends/postgresql/tests.py:478 — `no_pool_connection()` is
    # a helper the suite wrote for itself.
    src = """
    from unittest import mock


    def no_pool_connection():
        return connection


    def test_connect_no_is_usable_checks():
        new_connection = no_pool_connection()
        with mock.patch.object(new_connection, "is_usable"):
            new_connection.connect()
    """
    assert _check(src) == []


def test_an_object_from_an_unresolvable_name_is_exempt():
    # Nothing local built `new_connection` and nothing imported it, so there is
    # no evidence about what it is.
    src = """
    from unittest import mock


    def test_connect_no_is_usable_checks(new_connection):
        with mock.patch.object(new_connection, "is_usable"):
            new_connection.connect()
    """
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# FP guard: the object must be driven through its own surface. A double the    #
# test merely hands to something else IS the collaborator.                     #
# --------------------------------------------------------------------------- #


def test_object_handed_to_a_module_level_function_is_exempt():
    # django/tests/auth_tests/test_hashers.py:474 — the hasher is patched and
    # then passed to `check_password`, which is the real unit under test.
    src = """
    from unittest import mock

    from django.contrib.auth.hashers import get_hasher


    def test_check_password():
        hasher = get_hasher("default")
        with mock.patch.object(hasher, "verify"):
            assert check_password("letmein", encoded)
    """
    assert _check(src) == []


def test_driving_the_same_object_afterwards_does_fire():
    src = """
    from unittest import mock

    from django.contrib.auth.hashers import get_hasher


    def test_check_password():
        hasher = get_hasher("default")
        with mock.patch.object(hasher, "verify"):
            assert hasher.harden_runtime("letmein", encoded)
    """
    assert len(_check(src)) == 1


def test_calling_only_the_patched_attribute_is_exempt():
    src = """
    from unittest import mock

    from app.billing import Invoice


    def test_total():
        invoice = Invoice(lines)
        with mock.patch.object(invoice, "total") as mock_total:
            invoice.total()
        mock_total.assert_called_once()
    """
    assert _check(src) == []


def test_a_class_patched_but_never_instantiated_is_exempt():
    src = """
    from unittest import mock

    from celery.backends.gcs import GCSBackend


    def test_get_key():
        with mock.patch.object(GCSBackend, "_get_blob"):
            assert other_backend.get(b"k") is None
    """
    assert _check(src) == []


def test_exercise_in_a_different_test_does_not_leak():
    # `_Scope` is per function: the construction in `test_two` must not make
    # `test_one`'s patch look like a self-patch.
    src = """
    from unittest import mock

    from app.billing import Invoice


    def test_one():
        with mock.patch.object(Invoice, "line_total"):
            assert other.total() == 5


    def test_two():
        invoice = Invoice(lines)
        assert invoice.total() == 5
    """
    assert _check(src) == []


def test_patch_object_without_an_attribute_argument_is_ignored():
    # `_PATCH_OBJECT_MIN_ARGS`: one argument is not enough to judge anything, and
    # reaching for `args[1]` regardless would raise IndexError.
    src = """
    from unittest import mock

    from app.billing import Invoice


    def test_total():
        invoice = Invoice(lines)
        with mock.patch.object(invoice):
            assert invoice.total() == 5
    """
    assert _check(src) == []


def test_patch_object_without_a_string_attribute_is_ignored():
    src = """
    from unittest import mock

    from app.billing import Invoice


    def test_total():
        invoice = Invoice(lines)
        with mock.patch.object(invoice, attr_name):
            assert invoice.total() == 5
    """
    assert _check(src) == []


@pytest.mark.parametrize(
    "call",
    ["patch(target)", "patch()", 'patch.object(get_invoice(), "line_total")'],
    ids=["computed-target", "no-args", "non-name-target"],
)
def test_targets_the_rule_cannot_read_are_ignored(call: str):
    src = f"""
    from unittest.mock import patch

    from app.billing import Invoice, apply_discount, compute_invoice


    def test_total():
        invoice = Invoice(lines)
        with {call}:
            assert invoice.total() == compute_invoice(order)
    """
    assert _check(src) == []
