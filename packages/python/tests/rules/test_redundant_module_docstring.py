from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.redundant_module_docstring import RedundantModuleDocstring


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "package/element.py") -> list[Diagnostic]:
    return RedundantModuleDocstring().check(Path(path), source)


_PUBLIC_EXAMPLES = RedundantModuleDocstring.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(RedundantModuleDocstring().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    ("path", "docstring"),
    [
        ("browser/element.py", "Element class for element operations."),
        ("input/mouse.py", "Mouse class for mouse operations."),
        ("pydantic/warnings.py", "Pydantic-specific warnings."),
        ("pydantic/errors.py", "Pydantic-specific errors."),
        ("pydantic/validate_call_decorator.py", "Decorator for validating function calls."),
        ("browser/actor/page.py", "Page class for page-level operations."),
        ("browser/actor/utils.py", "Utility functions for actor operations."),
        ("_pytest/cacheprovider.py", "Implementation of the cache provider."),
        ("celery/utils/log.py", "Logging utilities."),
        ("scrapy/utils/signal.py", "Helper functions for working with signals."),
        ("scrapy/utils/template.py", "Helper functions for working with templates."),
        ("prefect/client/utilities.py", "Utilities for working with clients."),
    ],
)
def test_flags_corpus_path_restatements(path: str, docstring: str) -> None:
    findings = _check(f'"""{docstring}"""\n\nVALUE = 1\n', path)

    assert len(findings) == 1
    assert findings[0].code == "SARJ099"
    assert findings[0].severity is Severity.WARNING
    assert (findings[0].line, findings[0].col) == (1, 1)
    assert "file path" in findings[0].message


@pytest.mark.parametrize(
    "docstring",
    [
        "Canonical diagnostics preserve facts across JSON, SARIF, and native tools.",
        "Versioned analysis reports for IDEs, CI annotations, and programmatic consumers.",
        "Diagnostics share one tool-neutral invariant across serializers.",
        "Element operations preserve insertion order.",
        "Mouse operations are unavailable in headless sessions.",
    ],
)
def test_novel_behavior_architecture_and_consumer_tokens_keep_docstring(docstring: str) -> None:
    assert _check(f'"""{docstring}"""\n\nVALUE = 1\n', "analysis/diagnostics.py") == []


@pytest.mark.parametrize(
    "docstring",
    [
        "Cache provider backed by Redis.",
        "Cache provider with TTL semantics.",
        "Legacy cache provider retained for compatibility.",
        "Logging utilities redact credentials.",
    ],
)
def test_filename_matching_keeps_novel_contracts(docstring: str) -> None:
    path = "celery/utils/log.py" if docstring.startswith("Logging") else "_pytest/cacheprovider.py"
    assert _check(f'"""{docstring}"""\n\nVALUE = 1\n', path) == []


@pytest.mark.parametrize(
    ("path", "docstring"),
    [
        ("scrapy/utils/signal.py", "Signal utilities that work offline."),
        ("scrapy/utils/signal.py", "Utilities for workers receiving signals."),
    ],
)
def test_work_vocabulary_outside_structural_phrase_keeps_docstring(path: str, docstring: str) -> None:
    assert _check(f'"""{docstring}"""\n\nVALUE = 1\n', path) == []


@pytest.mark.parametrize(
    "path",
    [
        "package/__init__.py",
        "package/__main__.py",
        "tests/element.py",
        "package/test_element.py",
        "package/element_test.py",
        "package/element.pyi",
    ],
)
def test_excluded_module_kinds_are_ignored(path: str) -> None:
    assert _check('"""Element module."""\n\nVALUE = 1\n', path) == []


def test_docstring_only_module_is_ignored() -> None:
    assert _check('"""Element module."""\n') == []


@pytest.mark.parametrize(
    "source",
    [
        '"""Element module.\n\nDetails live here."""\n\nVALUE = 1\n',
        '"""Element module. It provides element operations."""\n\nVALUE = 1\n',
        '"""Element module.\n\nNotes:\n    Element operations."""\n\nVALUE = 1\n',
    ],
)
def test_multiline_sections_and_multiple_sentences_are_ignored(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "docstring",
    [
        "Element operations for HTTP 429 responses.",
        "Element operations since Python 3.11.",
        "Element operations required by an upstream regression.",
        "Element operations. See https://example.com/elements.",
        "Element operations measured in milliseconds.",
    ],
)
def test_protected_and_value_markers_keep_docstring(docstring: str) -> None:
    assert _check(f'"""{docstring}"""\n\nVALUE = 1\n') == []


def test_generated_and_malformed_sources_are_ignored() -> None:
    generated = '# Code generated by schema compiler. DO NOT EDIT.\n"""Element module."""\nVALUE = 1\n'

    assert _check(generated) == []
    assert _check('"""Element module."""\nVALUE = (\n') == []


def test_only_the_first_statement_can_be_the_module_docstring() -> None:
    source = 'VALUE = 1\n"""Element module."""\n'

    assert _check(source) == []


def test_class_docstrings_are_out_of_scope() -> None:
    source = 'class Element:\n    """Element class for element operations."""\n\n    value = 1\n'

    assert _check(source) == []


def test_cli_reports_warning_without_failing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "element.py"
    target.write_text('"""Element class for element operations."""\n\nVALUE = 1\n', encoding="utf-8")

    assert main(["check", "--rule", "redundant-module-docstring", str(target)]) == 0
    assert "SARJ099 warning:" in capsys.readouterr().out


def test_exact_suppression_is_honored(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "element.py"
    target.write_text(
        '"""Element class for element operations."""  # sarj-noqa: SARJ099 — public docs\n\nVALUE = 1\n',
        encoding="utf-8",
    )

    assert main(["check", "--rule", "redundant-module-docstring", str(target)]) == 0
    assert not capsys.readouterr().out
