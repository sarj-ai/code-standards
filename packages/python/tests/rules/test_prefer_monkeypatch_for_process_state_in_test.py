from pathlib import Path, PurePosixPath
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.prefer_injected_dependency_over_monkeypatch import (
    PreferInjectedDependencyOverMonkeypatch,
)
from sarj_python_lint.rules.prefer_monkeypatch_for_process_state_in_test import (
    PreferMonkeypatchForProcessStateInTest,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


TEST_PATH = "python/service/tests/test_process_state.py"


def _check(source: str, path: str | PurePosixPath = TEST_PATH) -> list[Diagnostic]:
    return PreferMonkeypatchForProcessStateInTest().check(Path(path), textwrap.dedent(source))


_PUBLIC_EXAMPLES = PreferMonkeypatchForProcessStateInTest.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, focus.path)) == example.expected_count


@pytest.mark.parametrize(
    ("statement", "message_part"),
    [
        ("os.chdir(tmp_path)", "monkeypatch.chdir"),
        ("sys.path.insert(0, str(tmp_path))", "monkeypatch.syspath_prepend"),
        ('sys.modules["optional"] = fake', "monkeypatch.setitem"),
        ('del sys.modules["optional"]', "monkeypatch.delitem"),
        ('sys.modules.pop("optional", None)', "monkeypatch.delitem"),
    ],
)
def test_reports_supported_direct_process_state_mutations(statement: str, message_part: str) -> None:
    diagnostics = _check(f"""
        import os
        import sys

        def helper():
            {statement}
    """)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ446"
    assert diagnostics[0].severity.value == "warning"
    assert message_part in diagnostics[0].message


def test_reports_multiple_mutations_in_source_order() -> None:
    diagnostics = _check("""
        import os
        import sys

        def test_loader():
            os.chdir(tmp_path)
            sys.modules["optional"] = fake
    """)
    assert [(diagnostic.line, diagnostic.col) for diagnostic in diagnostics] == [(6, 5), (7, 5)]


@pytest.mark.parametrize(
    "source",
    [
        "import os as operating_system\n\ndef helper():\n    operating_system.chdir(target)",
        "from os import chdir as change_directory\n\ndef helper():\n    change_directory(target)",
        "import sys as runtime\n\ndef helper():\n    runtime.modules['optional'] = fake",
        "from sys import modules as registry\n\ndef helper():\n    registry['optional'] = fake",
        "from sys import path as import_path\n\ndef helper():\n    import_path.insert(0, target)",
        "def helper():\n    import sys as runtime\n    runtime.modules['optional'] = fake",
    ],
)
def test_resolves_import_aliases(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "import os\n\nos.chdir(target)",
        "import sys\n\nsys.path.insert(0, target)",
        "import sys\n\nsys.modules['optional'] = fake",
        "import sys\n\nclass Bootstrap:\n    sys.modules['optional'] = fake",
    ],
)
def test_allows_module_and_class_bootstrap(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "statement",
    [
        'os.environ["REGION"] = "test"',
        'os.environ.update({"REGION": "test"})',
        "sys.path.append(target)",
        "sys.path.insert(1, target)",
        "sys.argv.append('--debug')",
        "warnings.simplefilter('error')",
        "locale.setlocale(locale.LC_ALL, 'C')",
    ],
)
def test_leaves_other_process_state_to_its_owner(statement: str) -> None:
    assert (
        _check(f"""
        import locale
        import os
        import sys
        import warnings

        def helper():
            {statement}
    """)
        == []
    )


@pytest.mark.parametrize(
    "statement",
    [
        "monkeypatch.chdir(target)",
        "monkeypatch.syspath_prepend(target)",
        'monkeypatch.setitem(sys.modules, "optional", fake)',
        'monkeypatch.delitem(sys.modules, "optional", raising=False)',
    ],
)
def test_allows_pytest_restoring_helpers(statement: str) -> None:
    assert (
        _check(f"""
        import sys

        def helper(monkeypatch):
            {statement}
    """)
        == []
    )


def test_allows_consumed_modules_pop_result() -> None:
    assert (
        _check("""
        import sys

        def helper():
            previous = sys.modules.pop("optional", None)
            return previous
    """)
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        "import os\n\ndef helper(os):\n    os.chdir(target)",
        "import sys\n\ndef helper(sys):\n    sys.modules['optional'] = fake",
        "import os\n\ndef helper():\n    os = CustomOS()\n    os.chdir(target)",
        "import sys\n\ndef helper():\n    sys = registry\n    sys.modules['optional'] = fake",
    ],
)
def test_ignores_shadowed_or_rebound_imports(source: str) -> None:
    assert _check(source) == []


def test_reports_use_before_later_rebinding() -> None:
    diagnostics = _check("""
        import sys

        def helper():
            sys.modules["optional"] = fake
            sys = registry
    """)
    assert len(diagnostics) == 1


def test_nested_helper_is_analyzed_once() -> None:
    diagnostics = _check("""
        import sys

        def test_loader():
            def install():
                sys.modules["optional"] = fake
            install()
    """)
    assert len(diagnostics) == 1
    assert diagnostics[0].line == 6


def test_allows_matching_try_finally_registry_restoration() -> None:
    assert (
        _check("""
        import sys

        def helper():
            try:
                sys.modules["optional"] = fake
                exercise()
            finally:
                del sys.modules["optional"]
    """)
        == []
    )


def test_allows_matching_try_finally_path_restoration() -> None:
    assert (
        _check("""
        import sys

        def helper():
            try:
                sys.path.insert(0, plugin_path)
                exercise()
            finally:
                sys.path.remove(plugin_path)
    """)
        == []
    )


def test_different_finally_key_does_not_hide_registry_leak() -> None:
    diagnostics = _check("""
        import sys

        def helper():
            try:
                sys.modules["optional"] = fake
            finally:
                del sys.modules["other"]
    """)
    assert len(diagnostics) == 2


def test_exact_suppression_is_honored_by_runner(tmp_path: Path) -> None:
    source = textwrap.dedent("""
        import sys

        def helper():
            sys.modules["optional"] = fake  # sarj-noqa: SARJ446 -- loader contract owns this process-global registry entry.
    """)
    file = tmp_path / "tests" / "test_loader.py"
    file.parent.mkdir()
    file.write_text(source)
    assert analyze([PreferMonkeypatchForProcessStateInTest.id], [file]) == []


def test_recommended_helpers_do_not_conflict_with_sarj445() -> None:
    source = textwrap.dedent("""
        import sys

        def test_loader(monkeypatch):
            monkeypatch.chdir(target)
            monkeypatch.syspath_prepend(plugin_path)
            monkeypatch.setitem(sys.modules, "optional", fake)
            monkeypatch.delitem(sys.modules, "legacy", raising=False)
    """)
    assert _check(source) == []
    assert PreferInjectedDependencyOverMonkeypatch().check(Path(TEST_PATH), source) == []


def test_non_test_generated_and_malformed_files_are_ignored() -> None:
    source = "import sys\n\ndef helper():\n    sys.modules['optional'] = fake\n"
    assert _check(source, "python/service/runtime.py") == []
    assert _check(f"# Generated file; do not edit\n{source}") == []
    assert _check("def broken(") == []
