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
        def helper(monkeypatch):
            def nested(monkeypatch):
                monkeypatch.setattr(service, "nested", fake)
            monkeypatch.setattr(service, "outer", fake)
    """)
    assert [(diagnostic.line, diagnostic.col) for diagnostic in diagnostics] == [(4, 9), (5, 5)]


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
