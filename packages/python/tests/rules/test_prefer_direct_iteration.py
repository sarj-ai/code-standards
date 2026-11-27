from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules import DEFAULT_REGISTRY
from sarj_python_lint.rules.prefer_direct_iteration import PreferDirectIteration


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "app/iteration.py") -> list[Diagnostic]:
    return PreferDirectIteration().check(Path(path), source)


def test_documented_examples() -> None:
    verify_native_rule(PreferDirectIteration, analyze)


def test_warning_without_autofix_is_enabled_by_default() -> None:
    rule = DEFAULT_REGISTRY["prefer-direct-iteration"]
    assert rule is PreferDirectIteration
    assert rule.documentation is not None
    assert rule.documentation.default_level is Severity.WARNING
    assert rule.documentation.autofix is AutofixPolicy.NONE


@pytest.mark.parametrize(
    "body",
    ["consume(files[i])", "consume(files[i], files[i])", "consume(transform(files[i]).name)"],
    ids=["one-read", "multiple-reads", "nested-expression"],
)
def test_reports_index_only_reads(body: str) -> None:
    [finding] = _check(f"def run(files):\n    for i in range(len(files)):\n        {body}\n")
    assert (finding.line, finding.col, finding.code, finding.severity) == (2, 5, "SARJ606", Severity.WARNING)
    assert "`for item in files`" in finding.message
    assert not finding.fixes


def test_attribute_operand() -> None:
    [finding] = _check("for i in range(len(self.files)):\n    consume(self.files[i])\n")
    assert "`self.files[i]`" in finding.message
    assert "`for item in self.files`" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        "for item in files:\n    consume(item)\n",
        "for i in range(len(files)):\n    files[i] = transform(files[i])\n",
        "for i in range(len(files)):\n    consume(files[i + 1])\n",
        "for i in range(len(files)):\n    consume(files[i], other[i])\n",
        "for i in range(len(files)):\n    print(i)\n    consume(files[i])\n",
        "for _round in range(len(files)):\n    update(files)\n",
        "for i in range(len(files)):\n    consume(files[i])\n    files.pop()\n",
        "for i in range(len(files)):\n    del files[i]\n",
        "for i in range(1, len(files)):\n    consume(files[i])\n",
        "for i in range(len(files) - 1):\n    consume(files[i])\n",
        "for i in range(len(files)):\n    consume(files[i])\nelse:\n    print(i)\n",
        "def run(len, files):\n    for i in range(len(files)):\n        consume(files[i])\n",
        "range = custom_range\nfor i in range(len(files)):\n    consume(files[i])\n",
        "for i in range(len(files)):\n    files = load()\n    consume(files[i])\n",
        "for i in range(len(files)):\n    i = 0\n    consume(files[i])\n",
        "for i in range(len(self.files)):\n    self.files = load()\n    consume(self.files[i])\n",
        "for i in range(len(files)):\n    consume(files[i:])\n",
        "for i in range(len(load())):\n    consume(load()[i])\n",
        "async for i in range(len(files)):\n    consume(files[i])\n",
        "for i in range(len(files)):\n    def later():\n        consume(files[i])\n",
        "for i in range(len(files)):\n    save(files[i] for _ in other)\n",
        "for :\n",
    ],
    ids=[
        "direct",
        "store",
        "arithmetic",
        "other-sequence",
        "index-read",
        "rounds",
        "mutation",
        "delete",
        "two-args",
        "short-range",
        "else-read",
        "shadowed-len",
        "shadowed-range",
        "sequence-rebound",
        "index-rebound",
        "attribute-rebound",
        "slice",
        "call-operand",
        "async",
        "nested-scope",
        "nested-generator",
        "malformed",
    ],
)
def test_keeps_indices_with_other_meaning(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("method", ["append", "extend", "insert", "pop", "remove", "clear", "sort", "reverse"])
def test_excludes_known_sequence_mutators(method: str) -> None:
    assert _check(f"for i in range(len(files)):\n    consume(files[i])\n    files.{method}(value)\n") == []


@pytest.mark.parametrize("path", ["app/iteration.pyi", "generated/iteration.py", "vendor/iteration.py"])
def test_excludes_stubs_and_generated_paths(path: str) -> None:
    assert _check("for i in range(len(files)):\n    consume(files[i])\n", path) == []


def test_generated_banner_and_exact_suppression() -> None:
    source = "for i in range(len(files)):\n    consume(files[i])\n"
    assert _check("# This file is generated; do not edit.\n" + source) == []
    assert _check(source.replace(":\n", ":  # sarj-noqa: SARJ606 -- index semantics are required here.\n", 1)) == []
    assert len(_check(source.replace(":\n", ":  # sarj-noqa: SARJ999 -- unrelated rule.\n", 1))) == 1
