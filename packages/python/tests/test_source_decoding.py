from __future__ import annotations

import ast
import codecs
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint._source import read_python_source
from sarj_python_lint.ratchet import measure
from sarj_python_lint.rules._first_party import FirstPartyFacts
from sarj_python_lint.rules._local_source import LocalSourceFacts
from sarj_python_lint.rules._nominal_project import NominalProjectFacts


if TYPE_CHECKING:
    from pathlib import Path


_UNICODE_TEST = "from unittest.mock import Mock\ndef test_café():\n    naïve = Mock()\n    naïve.send()\n"


@pytest.mark.parametrize(
    "raw",
    [
        _UNICODE_TEST.encode("utf-8"),
        codecs.BOM_UTF8 + _UNICODE_TEST.encode("utf-8"),
        ("# coding: latin-1\n" + _UNICODE_TEST).encode("latin-1"),
        ("#!/usr/bin/env python\n# coding: latin-1\n" + _UNICODE_TEST).encode("latin-1"),
        ("# coding: latin-1\n" + _UNICODE_TEST).replace("\n", "\r\n").encode("latin-1"),
        ("# coding: cp1252\n" + _UNICODE_TEST).encode("cp1252"),
    ],
    ids=("utf8", "bom", "latin1", "second-line-cookie", "crlf", "cp1252"),
)
def test_valid_source_encodings_preserve_cli_api_findings(tmp_path: Path, raw: bytes) -> None:
    target = tmp_path / "test_service.py"
    target.write_bytes(raw)
    native = ast.parse(raw)
    calls = [
        node
        for node in ast.walk(native)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Mock"
    ]

    findings = analyze(["mock-without-spec"], [target])

    assert [(finding.code, finding.line, finding.col) for finding in findings] == [
        ("SARJ040", calls[0].lineno, calls[0].col_offset + 1)
    ]
    assert main(["check", "--rule", "mock-without-spec", str(target)]) == 1
    assert ast.dump(ast.parse(read_python_source(target))) == ast.dump(native)


@pytest.mark.parametrize(
    "raw",
    [
        b"# coding: unknown-codec\nvalue = 1\n",
        codecs.BOM_UTF8 + b"# coding: latin-1\nvalue = 1\n",
        b"value = '\xff'\n",
        b"# header\n# header\n# coding: latin-1\nvalue = '\xff'\n",
    ],
    ids=("unknown-cookie", "bom-conflict", "bad-utf8", "late-cookie"),
)
def test_invalid_encodings_fail_cli_and_api(tmp_path: Path, raw: bytes, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "test_service.py"
    target.write_bytes(raw)
    with pytest.raises(SyntaxError):
        ast.parse(raw)
    with pytest.raises((SyntaxError, UnicodeError)):
        analyze(["mock-without-spec"], [target])

    assert main(["check", "--rule", "mock-without-spec", str(target)]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "error:" in output.err
    assert "Traceback" not in output.err


def test_cookie_decoding_reaches_bounded_project_readers_and_ratchet(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\nversion="1.0.0"\ndependencies=[]\n')
    package = tmp_path / "src"
    package.mkdir()
    model = package / "models.py"
    model.write_bytes(
        "# coding: latin-1\nclass Café:\n    name: str\nvalue = 1 # sarj-noqa: SARJ002 -- compatibility boundary\n".encode(
            "latin-1"
        )
    )
    consumer = package / "service.py"
    consumer.write_text("from models import Café\n", encoding="utf-8")
    ast.parse(model.read_bytes())

    local = LocalSourceFacts().read_module(model)
    nominal = NominalProjectFacts().sources(consumer, FirstPartyFacts())
    observed = measure(tmp_path, ["src"])

    assert local is not None
    assert "models" in nominal
    nominal_tree = nominal["models"].tree
    assert nominal_tree is not None
    assert ast.dump(local.tree) == ast.dump(nominal_tree)
    assert observed.codes["sarj-noqa:SARJ002"] == 1


def test_malformed_unselected_project_sources_keep_module_isolation(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\nversion="1.0.0"\ndependencies=[]\n')
    package = tmp_path / "src"
    package.mkdir()
    malformed = package / "unselected.py"
    malformed.write_bytes(b"# coding: unknown-codec\nvalue = 1\n")
    consumer = package / "service.py"
    consumer.write_text("value = 1\n")

    assert LocalSourceFacts().read_module(malformed) is None
    assert "unselected" not in NominalProjectFacts().sources(consumer, FirstPartyFacts())
    assert measure(tmp_path, ["src"]).codes == {}
    assert analyze(["no-input-model-mutation"], [consumer]) == []
