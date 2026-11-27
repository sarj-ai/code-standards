from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules import DEFAULT_REGISTRY
from sarj_python_lint.rules.prefer_itertools_batched import PreferItertoolsBatched


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "app/batches.py") -> list[Diagnostic]:
    return PreferItertoolsBatched().check(Path(path), source)


def test_documented_examples() -> None:
    verify_native_rule(PreferItertoolsBatched, analyze)


def test_warning_without_autofix_is_enabled_by_default() -> None:
    rule = DEFAULT_REGISTRY["prefer-itertools-batched"]
    assert rule is PreferItertoolsBatched
    assert rule.documentation is not None
    assert rule.documentation.default_level is Severity.WARNING
    assert rule.documentation.autofix is AutofixPolicy.NONE


@pytest.mark.parametrize(
    "source",
    [
        "for offset in range(0, len(files), SIZE):\n    run(files[offset : offset + SIZE])\n",
        "for number, offset in enumerate(range(0, len(files), SIZE), start=1):\n    run(number, files[offset : offset + SIZE])\n",
        "batches = [files[offset : offset + SIZE] for offset in range(0, len(files), SIZE)]\n",
        "batches = {files[offset : offset + SIZE] for offset in range(0, len(files), SIZE)}\n",
        "batches = (files[offset : offset + SIZE] for offset in range(0, len(files), SIZE))\n",
        "for offset in range(0, len(files), SIZE):\n    run(files[offset : SIZE + offset])\n",
        "for offset in range(0, len(self.files), SIZE):\n    run(self.files[offset : offset + SIZE])\n",
        "for offset in range(0, len(files), SIZE):\n    batch = files[offset : offset + SIZE]\n    run(tuple(str(path) for path in batch))\n",
    ],
    ids=["loop", "enumerate", "list", "set", "generator", "reversed-add", "attribute", "unrelated-generator"],
)
def test_reports_manual_chunking(source: str) -> None:
    [finding] = _check(source)
    assert finding.code == "SARJ605"
    assert finding.severity is Severity.WARNING
    assert "itertools.batched(" in finding.message
    assert "strict=False" in finding.message
    assert not finding.fixes


def test_location_and_mismatched_width() -> None:
    [finding] = _check(
        "def run(files):\n    for offset in range(0, len(files), SIZE):\n        consume(files[offset : offset + 128])\n"
    )
    assert (finding.line, finding.col, finding.code, finding.severity) == (2, 5, "SARJ605", Severity.WARNING)
    assert "slice width `128` differs from the step `SIZE`" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        "for batch in batched(files, SIZE, strict=False):\n    run(batch)\n",
        "for offset in range(0, len(files), SIZE):\n    run(offset, files[offset : offset + SIZE])\n",
        "for offset in range(0, len(files), SIZE):\n    run(other[offset : offset + SIZE])\n",
        "for offset in range(1, len(files), SIZE):\n    run(files[offset : offset + SIZE])\n",
        "for offset in range(0, len(files)):\n    run(files[offset : offset + SIZE])\n",
        "for offset in range(0, len(files), SIZE):\n    run(files[offset : offset + SIZE : 2])\n",
        "for offset in range(0, len(files), SIZE):\n    files = load()\n    run(files[offset : offset + SIZE])\n",
        "for offset in range(0, len(files), SIZE):\n    offset = 0\n    run(files[offset : offset + SIZE])\n",
        "for offset in range(0, len(load()), SIZE):\n    run(load()[offset : offset + SIZE])\n",
        "async for offset in range(0, len(files), SIZE):\n    run(files[offset : offset + SIZE])\n",
        "batches = [files[offset : offset + SIZE] for offset in range(0, len(files), SIZE) if offset]\n",
        "batches = [files[offset : offset + SIZE] for offset in range(0, len(files), SIZE) for extra in other]\n",
        "for offset in range(0, len(files), SIZE):\n    def later():\n        return files[offset : offset + SIZE]\n",
        "def run(range, files):\n    for offset in range(0, len(files), SIZE):\n        consume(files[offset : offset + SIZE])\n",
        "for offset in range(0, len(files), 0):\n    run(files[offset : offset + SIZE])\n",
        "for offset in range(0, len(files), -1):\n    run(files[offset : offset + SIZE])\n",
        "for offset in range(0, len(self.files), SIZE):\n    self.files = load()\n    run(self.files[offset : offset + SIZE])\n",
        "for offset in range(0, len(files), SIZE):\n    run(files[offset : offset + SIZE])\nelse:\n    run(offset)\n",
        "for offset in range(0, len(files), SIZE):\n    run(files[offset : offset + offset])\n",
        "for offset in range(0, len(files), SIZE):\n    save(files[offset : offset + SIZE] for _ in other)\n",
        "for :\n",
    ],
    ids=[
        "batched",
        "offset-use",
        "different-sequence",
        "nonzero",
        "two-args",
        "slice-step",
        "sequence-rebound",
        "offset-rebound",
        "call-operand",
        "async",
        "filter",
        "multiple-generators",
        "nested-scope",
        "shadowed-range",
        "zero-step",
        "negative-step",
        "attribute-rebound",
        "else-use",
        "offset-width",
        "nested-generator",
        "malformed",
    ],
)
def test_keeps_unsupported_and_observable_indices(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("path", ["app/batches.pyi", "generated/batches.py", "vendor/batches.py"])
def test_excludes_stubs_and_generated_paths(path: str) -> None:
    assert _check("for offset in range(0, len(files), SIZE):\n    run(files[offset : offset + SIZE])\n", path) == []


def test_generated_banner_and_exact_suppression() -> None:
    source = "for offset in range(0, len(files), SIZE):\n    run(files[offset : offset + SIZE])\n"
    assert _check("# This file is generated; do not edit.\n" + source) == []
    assert _check(source.replace(":\n", ":  # sarj-noqa: SARJ605 -- tuple batches are incompatible here.\n", 1)) == []
    assert len(_check(source.replace(":\n", ":  # sarj-noqa: SARJ999 -- unrelated rule.\n", 1))) == 1


@pytest.mark.parametrize("minimum", ["3.10", "3.11", "3.12", "3.13"])
def test_declared_python_api_support(tmp_path: Path, minimum: str) -> None:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nrequires-python = ">={minimum}"\n')
    findings = _check(
        "for offset in range(0, len(files), SIZE):\n    run(files[offset : offset + SIZE])\n",
        str(tmp_path / "batches.py"),
    )
    if minimum in {"3.10", "3.11"}:
        assert findings == []
    else:
        [finding] = findings
        assert ("strict=False" in finding.message) is (minimum == "3.13")


def test_class_field_does_not_shadow_builtins_in_other_scopes() -> None:
    source = "class Record:\n    range: object = None\n\ndef run(files):\n    for offset in range(0, len(files), SIZE):\n        consume(files[offset : offset + SIZE])\n"
    assert len(_check(source)) == 1


def test_class_body_loop_respects_its_class_bindings() -> None:
    source = "class Record:\n    range = custom_range\n    for offset in range(0, len(files), SIZE):\n        consume(files[offset : offset + SIZE])\n"
    assert _check(source) == []
