from pathlib import Path, PurePosixPath
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.over_mocked_test import OverMockedTest
from sarj_python_lint.rules.prefer_injected_dependency_over_monkeypatch import (
    PreferInjectedDependencyOverMonkeypatch,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


TEST_PATH = "python/service/tests/test_service.py"


def _check(source: str, path: str | PurePosixPath = TEST_PATH) -> list[Diagnostic]:
    return PreferInjectedDependencyOverMonkeypatch().check(Path(path), textwrap.dedent(source))


_PUBLIC_EXAMPLES = PreferInjectedDependencyOverMonkeypatch.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, focus.path)) == example.expected_count


@pytest.mark.parametrize(
    "call",
    [
        "monkeypatch.setattr(service, 'client', fake)",
        "monkeypatch.setattr('app.service.client', fake)",
        "monkeypatch.delattr(service, 'client')",
        "monkeypatch.delattr('app.service.client')",
    ],
)
def test_reports_every_attribute_mutation_form(call: str) -> None:
    diagnostics = _check(f"""
        def test_service(monkeypatch):
            {call}
    """)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ445"
    assert diagnostics[0].line == 3
    assert diagnostics[0].col == 5


def test_reports_each_call_in_source_order() -> None:
    diagnostics = _check("""
        def test_service(monkeypatch):
            monkeypatch.setattr(service, "client", fake)
            monkeypatch.delattr(service, "legacy_client")
    """)
    assert [(diagnostic.line, diagnostic.col) for diagnostic in diagnostics] == [(3, 5), (4, 5)]


@pytest.mark.parametrize(
    ("imports", "call", "label"),
    [
        ("from unittest.mock import patch", "patch('app.service.client', fake)", "`patch`"),
        ("from unittest.mock import patch as replace", "replace('app.service.client', fake)", "`patch`"),
        ("import unittest.mock", "unittest.mock.patch('app.service.client', fake)", "`patch`"),
        ("from unittest import mock", "mock.patch('app.service.client', fake)", "`patch`"),
        ("from unittest.mock import patch", "patch.object(service, 'client', fake)", "`patch.object`"),
        ("", "mocker.patch('app.service.client', fake)", "`mocker.patch`"),
        ("", "mocker.patch.object(service, 'client', fake)", "`mocker.patch.object`"),
    ],
)
def test_reports_patch_apis(imports: str, call: str, label: str) -> None:
    diagnostics = _check(f"""
        {imports}

        def test_service(mocker):
            {call}
    """)
    assert len(diagnostics) == 1
    assert label in diagnostics[0].message


def test_reports_patch_decorator() -> None:
    diagnostics = _check("""
        from unittest.mock import patch

        @patch("app.service.client")
        def test_service(client):
            assert client is not None
    """)
    assert len(diagnostics) == 1


def test_ignores_unrelated_patch_objects() -> None:
    assert (
        _check("""
        patch = CustomPatcher()

        def test_service():
            patch("app.service.client", fake)
    """)
        == []
    )


def test_recognizes_aliased_pytest_annotation() -> None:
    diagnostics = _check("""
        import pytest as pt

        def install_boundary(mp: pt.MonkeyPatch):
            mp.setattr(runtime, "client", fake)
    """)
    assert len(diagnostics) == 1


def test_recognizes_imported_monkeypatch_annotation() -> None:
    diagnostics = _check("""
        from pytest import MonkeyPatch as MP

        def install_boundary(mp: MP):
            mp.setattr(runtime, "client", fake)
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize("annotation", ['"pytest.MonkeyPatch"', '"MonkeyPatch"'])
def test_recognizes_string_annotations(annotation: str) -> None:
    diagnostics = _check(f"""
        import pytest
        from pytest import MonkeyPatch

        def install_boundary(mp: {annotation}):
            mp.setattr(runtime, "client", fake)
    """)
    assert len(diagnostics) == 1


def test_recognizes_direct_handle_alias() -> None:
    diagnostics = _check("""
        def test_service(monkeypatch):
            mp = monkeypatch
            mp.setattr(service, "client", fake)
    """)
    assert len(diagnostics) == 1


def test_rebound_handle_alias_is_ignored() -> None:
    assert (
        _check("""
        def test_service(monkeypatch):
            mp = monkeypatch
            mp = CustomPatcher()
            mp.setattr(service, "client", fake)
    """)
        == []
    )


def test_alias_created_after_fixture_parameter_rebinding_is_ignored() -> None:
    assert (
        _check("""
        def test_service(monkeypatch):
            monkeypatch = CustomPatcher()
            mp = monkeypatch
            mp.setattr(service, "client", fake)
    """)
        == []
    )


def test_recognizes_context_handle_alias() -> None:
    diagnostics = _check("""
        def test_service(monkeypatch):
            with monkeypatch.context() as scoped:
                scoped.setattr(service, "client", fake)
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "call",
    [
        'monkeypatch.setenv("REGION", "test")',
        'monkeypatch.delenv("REGION", raising=False)',
        "monkeypatch.chdir(tmp_path)",
        "monkeypatch.syspath_prepend(str(tmp_path))",
        'monkeypatch.setitem(sys.modules, "optional", fake)',
        'monkeypatch.delitem(config, "legacy", raising=False)',
        "monkeypatch.context()",
    ],
)
def test_allows_reversible_process_state_operations(call: str) -> None:
    assert (
        _check(f"""
        def test_service(monkeypatch):
            {call}
    """)
        == []
    )


def test_unrelated_local_named_monkeypatch_is_ignored() -> None:
    assert (
        _check("""
        def test_service():
            monkeypatch = CustomPatcher()
            monkeypatch.setattr(service, "client", fake)
    """)
        == []
    )


def test_rebound_fixture_parameter_is_ignored() -> None:
    assert (
        _check("""
        def test_service(monkeypatch):
            monkeypatch = CustomPatcher()
            monkeypatch.setattr(service, "client", fake)
    """)
        == []
    )


def test_reports_call_before_fixture_parameter_is_rebound() -> None:
    diagnostics = _check("""
        def test_service(monkeypatch):
            monkeypatch.setattr(service, "client", fake)
            monkeypatch = CustomPatcher()
            monkeypatch.setattr(service, "fallback", fake)
    """)
    assert [(diagnostic.line, diagnostic.col) for diagnostic in diagnostics] == [(3, 5)]


def test_recognizes_union_annotation() -> None:
    diagnostics = _check("""
        import pytest

        def install_boundary(mp: pytest.MonkeyPatch | None):
            assert mp is not None
            mp.setattr(runtime, "client", fake)
    """)
    assert len(diagnostics) == 1


def test_nested_scope_owns_its_own_fixture_handle() -> None:
    diagnostics = _check("""
        import pytest

        def helper(monkeypatch: pytest.MonkeyPatch):
            def nested(monkeypatch: pytest.MonkeyPatch):
                monkeypatch.setattr(service, "nested", fake)
            monkeypatch.setattr(service, "outer", fake)
    """)
    assert [(diagnostic.line, diagnostic.col) for diagnostic in diagnostics] == [(6, 9), (7, 5)]


@pytest.mark.parametrize("path", ["src/service.py", "app/testing_helpers.py"])
def test_skips_non_test_paths(path: str) -> None:
    assert (
        _check(
            """
        def install(monkeypatch):
            monkeypatch.setattr(service, "client", fake)
    """,
            path,
        )
        == []
    )


@pytest.mark.parametrize(
    ("path", "header"),
    [
        ("tests/generated/test_client.py", ""),
        (TEST_PATH, "# This file is generated. Do not edit.\n"),
    ],
)
def test_skips_generated_tests(path: str, header: str) -> None:
    source = f"{header}def test_service(monkeypatch):\n    monkeypatch.setattr(service, 'client', fake)\n"
    assert _check(source, path) == []


def test_syntax_error_is_ignored() -> None:
    assert _check("def test_service(:\n") == []


def test_message_teaches_injection_and_boundary_suppression() -> None:
    [diagnostic] = _check("""
        def test_service(monkeypatch):
            monkeypatch.setattr(service, "client", fake)
    """)
    assert "Inject the dependency or configuration" in diagnostic.message
    assert "global lookup or interception is the behavior under test" in diagnostic.message
    assert "suppress SARJ445 locally" in diagnostic.message


def test_complements_over_mocked_test_without_changing_its_threshold() -> None:
    source = textwrap.dedent("""
        def test_checkout(monkeypatch):
            monkeypatch.setattr(inventory, "reserve", reserve)
            monkeypatch.setattr(payments, "charge", charge)
            monkeypatch.setattr(shipping, "quote", quote)
            monkeypatch.setattr(tax, "calculate", calculate)
            monkeypatch.setattr(email, "send_receipt", send_receipt)
            monkeypatch.setattr(risk, "approve", approve)
    """)
    path = Path(TEST_PATH)

    attribute_diagnostics = PreferInjectedDependencyOverMonkeypatch().check(path, source)
    breadth_diagnostics = OverMockedTest().check(path, source)

    assert len(attribute_diagnostics) == 6
    assert [diagnostic.code for diagnostic in breadth_diagnostics] == ["SARJ062"]


def test_exact_local_suppression_is_honored_by_analysis(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_service.py"
    target.parent.mkdir()
    target.write_text(
        "def test_service(monkeypatch):\n"
        "    monkeypatch.setattr(runtime, 'client', fake)  # sarj-noqa: SARJ445 -- runtime owns this global\n",
        encoding="utf-8",
    )
    assert analyze([PreferInjectedDependencyOverMonkeypatch.id], [target]) == []


@pytest.mark.parametrize("handle", ["monkeypatch", "mocker"])
def test_untyped_helper_parameters_are_not_assumed_to_be_fixtures(handle: str) -> None:
    operation = "setattr" if handle == "monkeypatch" else "patch"
    assert _check(f"def helper({handle}):\n    {handle}.{operation}('target', fake)\n") == []


@pytest.mark.parametrize("handle", ["monkeypatch", "mocker"])
def test_parametrized_values_are_not_fixture_handles(handle: str) -> None:
    operation = "setattr" if handle == "monkeypatch" else "patch"
    assert (
        _check(f"""
        import pytest as pt

        @pt.mark.parametrize("{handle}", [CustomPatcher()])
        def test_service({handle}):
            {handle}.{operation}("target", fake)
    """)
        == []
    )


@pytest.mark.parametrize("decorator", ["fixture", "fixture()"])
def test_fixture_functions_supply_handle_provenance(decorator: str) -> None:
    diagnostics = _check(f"""
        from pytest import fixture

        @{decorator}
        def installed_client(monkeypatch, mocker):
            monkeypatch.setattr(service, "client", fake)
            mocker.patch("app.service.client", fake)
    """)
    assert len(diagnostics) == 2


def test_recognizes_typed_mock_helper_and_single_assignment_alias() -> None:
    diagnostics = _check("""
        from pytest_mock import MockerFixture as MF

        def helper(handle: "MF"):
            alias = handle
            alias.patch.object(service, "client", fake)
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize("binding", ["mocker = CustomPatcher()", "from other import mocker", "def mocker(): pass"])
def test_rebound_mocker_fixture_is_ignored(binding: str) -> None:
    assert (
        _check(f"""
        def test_service(mocker):
            {binding}
            mocker.patch("app.service.client", fake)
    """)
        == []
    )


def test_reports_mocker_before_rebinding_but_not_after() -> None:
    diagnostics = _check("""
        def test_service(mocker):
            mocker.patch("app.service.client", fake)
            mocker = CustomPatcher()
            mocker.patch("app.service.client", fake)
    """)
    assert [diagnostic.line for diagnostic in diagnostics] == [3]


@pytest.mark.parametrize(
    ("signature", "binding"),
    [
        ("patch", "pass"),
        ("", "patch = CustomPatcher()"),
        ("", "from other import patch"),
        ("", "def patch(*args): pass"),
    ],
)
def test_local_bindings_shadow_imported_patch(signature: str, binding: str) -> None:
    assert (
        _check(f"""
        from unittest.mock import patch

        def test_service({signature}):
            {binding}
            patch("app.service.client", fake)
    """)
        == []
    )


def test_shadowing_in_one_function_does_not_hide_other_patch_calls_or_decorators() -> None:
    diagnostics = _check("""
        from unittest.mock import patch

        @patch("app.service.client")
        def test_custom(patch):
            patch("app.service.client", fake)

        def test_imported():
            patch("app.service.client", fake)
    """)
    assert [diagnostic.line for diagnostic in diagnostics] == [4, 9]


def test_outer_parameter_shadows_import_in_nested_function() -> None:
    assert (
        _check("""
        from unittest.mock import patch

        def helper(patch):
            def nested():
                patch("app.service.client", fake)
    """)
        == []
    )


@pytest.mark.parametrize("annotation", ['"MonkeyPatch"', '"pytest.MonkeyPatch"', '"bad syntax!"'])
def test_unresolved_string_annotations_are_not_assumed_to_be_pytest(annotation: str) -> None:
    assert (
        _check(f"""
        def helper(handle: {annotation}):
            handle.setattr(service, "client", fake)
    """)
        == []
    )


def test_class_parametrization_excludes_fixture_inference() -> None:
    assert (
        _check("""
        import pytest

        @pytest.mark.parametrize(argnames=["monkeypatch", "mocker"], argvalues=[])
        class TestCustomPatcher:
            def test_custom(self, monkeypatch, mocker):
                monkeypatch.setattr(service, "client", fake)
                mocker.patch("app.service.client", fake)
    """)
        == []
    )


def test_nested_test_name_does_not_establish_fixture_provenance() -> None:
    assert (
        _check("""
        def helper():
            def test_custom(monkeypatch, mocker):
                monkeypatch.setattr(service, "client", fake)
                mocker.patch("app.service.client", fake)
    """)
        == []
    )


def test_async_fixture_alias_establishes_provenance() -> None:
    diagnostics = _check("""
        import pytest_asyncio as pa

        @pa.fixture
        async def installed_client(monkeypatch):
            monkeypatch.setattr(service, "client", fake)
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "expression",
    [
        '[patch("target") for patch in custom_patchers]',
        '(lambda patch: patch("target"))(custom_patcher)',
        '(lambda *patch: patch("target"))(custom_patcher)',
    ],
)
def test_nested_expression_bindings_shadow_patch_import(expression: str) -> None:
    assert (
        _check(f"""
        from unittest.mock import patch

        def test_custom():
            result = {expression}
    """)
        == []
    )


def test_comprehension_bindings_do_not_inherit_fixture_handles() -> None:
    assert (
        _check("""
        def test_custom(monkeypatch, mocker):
            one = [monkeypatch.setattr(service, "client", fake) for monkeypatch in custom_patchers]
            two = [mocker.patch("target") for mocker in custom_patchers]
    """)
        == []
    )


@pytest.mark.parametrize(
    "setup",
    [
        "    patcher = pytest.MonkeyPatch()\n    patcher.setattr(service, 'clock', fake)",
        "    with pytest.MonkeyPatch.context() as patcher:\n        patcher.delattr(service, 'clock')",
        "    with pytest.MonkeyPatch().context() as patcher:\n        patcher.setattr(service, 'clock', fake)",
        "    patcher = pytest.MonkeyPatch()\n    alias = patcher\n    alias.setattr(service, 'clock', fake)",
    ],
)
def test_explicit_monkeypatch_handles(setup: str) -> None:
    source = f"import pytest\ndef test_service():\n{setup}\n"
    assert len(_check(source)) == 1
    assert _check(source.replace("import pytest", "import custom as pytest")) == []


@pytest.mark.parametrize(
    "body",
    [
        "    patcher = pytest.MonkeyPatch()\n    patcher.setenv('MODE', 'test')",
        "    patcher = pytest.MonkeyPatch()\n    patcher = custom\n    patcher.setattr(service, 'clock', fake)",
        "    if enabled:\n        patcher = pytest.MonkeyPatch()\n    patcher.setattr(service, 'clock', fake)",
        "    patcher.setattr(service, 'clock', fake)\n    patcher = pytest.MonkeyPatch()",
    ],
)
def test_constructed_handle_exclusions(body: str) -> None:
    assert _check(f"import pytest\ndef test_service():\n{body}\n") == []


def test_monkeypatch_constructor_import_alias_and_shadowing() -> None:
    source = "from pytest import MonkeyPatch as MP\ndef test_service():\n    patcher = MP()\n    patcher.setattr(service, 'clock', fake)\n"
    assert len(_check(source)) == 1
    assert _check(source.replace("test_service()", "test_service(MP)")) == []


def test_context_on_constructed_monkeypatch_handle(tmp_path: Path) -> None:
    source = "import pytest\ndef test_service():\n    patcher = pytest.MonkeyPatch()\n    with patcher.context() as scoped:\n        scoped.setattr(service, 'clock', fake)\n"
    assert len(_check(source)) == 1
    assert (
        _check(source.replace("    with patcher.context()", "    patcher = custom\n    with patcher.context()")) == []
    )
    target = tmp_path / "test_service.py"
    target.write_text(
        source.replace(
            "scoped.setattr(service, 'clock', fake)",
            "scoped.setattr(service, 'clock', fake)  # sarj-noqa: SARJ445 -- global interception is under test",
        )
    )
    assert analyze([PreferInjectedDependencyOverMonkeypatch.id], [target]) == []
