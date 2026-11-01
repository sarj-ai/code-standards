from pathlib import Path
import re

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, check_source, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_typed_cli import PreferTypedCli


def test_documented_examples() -> None:
    verify_native_rule(PreferTypedCli, analyze)


CASES = (
    ("raw-slice", "import sys\nmain(sys.argv[1:])", 1),
    ("raw-index", "import sys as system\nservice = system.argv[1]", 1),
    ("direct-alias", "from sys import argv as arguments\nmain(arguments)", 1),
    ("program-name", "import sys\nname = sys.argv[0]", 0),
    (
        "literal-program-name-fallback",
        'import sys\nprogram = sys.argv[0] if sys.argv else "tool.py"\n',
        0,
    ),
    (
        "sys-import-alias",
        'import sys as system\nprogram = system.argv[0] if system.argv else "tool.py"\n',
        0,
    ),
    (
        "argv-import-alias",
        'from sys import argv as arguments\nprogram = arguments[0] if arguments else "tool.py"\n',
        0,
    ),
    (
        "real-argv-slice-retained-error",
        "import sys\narguments = sys.argv[1:] if sys.argv else []\n",
        2,
    ),
    (
        "real-argv-index-retained-error",
        'import sys\nargument = sys.argv[1] if sys.argv else "fallback"\n',
        2,
    ),
    (
        "actual-match-plus-metadata",
        'import sys\nmatch sys.argv:\n    case [_, value]: pass\nprogram = sys.argv[0] if sys.argv else "tool.py"\n',
        1,
    ),
    (
        "argparse-plus-metadata",
        'import argparse, sys\nparser = argparse.ArgumentParser()\nprogram = sys.argv[0] if sys.argv else "tool.py"\n',
        1,
    ),
    (
        "nonliteral-fallback-not-proven",
        "import sys\nprogram = sys.argv[0] if sys.argv else fallback()\n",
        1,
    ),
    (
        "nonstring-fallback-not-metadata",
        "import sys\nprogram = sys.argv[0] if sys.argv else None\n",
        1,
    ),
    (
        "false-is-not-int-zero",
        'import sys\nprogram = sys.argv[False] if sys.argv else "tool.py"\n',
        2,
    ),
    (
        "dynamic-index-not-proven",
        'import sys\nprogram = sys.argv[index] if sys.argv else "tool.py"\n',
        2,
    ),
    (
        "whole-argv-retained-error",
        'import sys\nprogram = sys.argv if sys.argv else "tool.py"\n',
        2,
    ),
    (
        "shadowed-sys-preserves-abstention",
        'import sys\ndef name(sys):\n    return sys.argv[0] if sys.argv else "tool.py"\n',
        0,
    ),
    ("assign-argv", "import sys\nsys.argv = ['tool']", 0),
    ("assign-slice", "import sys\nsys.argv[:] = ['tool']", 0),
    ("shadowed-sys", "import sys\ndef f(sys):\n    return sys.argv[1:]", 0),
    ("replaced-argv", "import sys\nsys.argv = replacement\nmain(sys.argv)", 0),
    ("string-only", "text = 'sys.argv[1:]'", 0),
    ("argparse", "import argparse\nparser = argparse.ArgumentParser()", 1),
    ("argparse-alias", "from argparse import ArgumentParser as Parser\nparser = Parser()", 1),
    ("optparse", "import optparse\nparser = optparse.OptionParser()", 1),
    ("getopt", "from getopt import getopt\ngetopt(arguments, 'v')", 1),
    ("click", "import click\n@click.command()\ndef main(): pass", 1),
    ("other-parser", "from app import ArgumentParser\nArgumentParser()", 0),
    ("import-only", "from argparse import ArgumentParser\ndef adapter(parser: ArgumentParser): pass", 0),
    ("typed-run", "import typer\ndef main(service: str, *, count: int = 1): pass\ntyper.run(main)", 0),
    ("untyped-run", "import typer as cli\ndef main(service): pass\ncli.run(main)", 1),
    ("quoted-type", "import typer\ndef main(service: 'str'): pass\ntyper.run(main)", 0),
    ("any-type", "from typing import Any\nimport typer\ndef main(service: Any): pass\ntyper.run(main)", 1),
    ("object-type", "import typer\ndef main(service: object): pass\ntyper.run(main)", 1),
    (
        "annotated-any",
        "from typing import Annotated, Any\nimport typer\ndef main(service: Annotated[Any, typer.Argument()]): pass\ntyper.run(main)",
        1,
    ),
    (
        "annotated-str",
        "from typing import Annotated\nimport typer\ndef main(service: Annotated[str, typer.Argument()]): pass\ntyper.run(main)",
        0,
    ),
    ("local-app", "import typer\napp = typer.Typer()\n@app.command()\ndef main(service): pass", 1),
    (
        "local-app-alias",
        "from typer import Typer\napp = Typer()\ncli = app\n@cli.callback()\ndef main(service): pass",
        1,
    ),
    ("typed-callback", "import typer\napp = typer.Typer()\n@app.callback()\ndef main(context: typer.Context): pass", 0),
    (
        "forwarding",
        "import typer, sys\napp = typer.Typer()\n@app.command()\ndef main(service: str): pass\napp(args=sys.argv[1:])",
        0,
    ),
    ("unrelated-args", "import sys\nother(args=sys.argv[1:])", 1),
    ("other-command", "@app.command()\ndef main(service): pass", 0),
    ("ordinary-function", "def main(service): pass", 0),
    ("dynamic-namespace", "import sys\nexec(source)\nmain(sys.argv)", 0),
    ("wildcard", "from app import *\nimport sys\nmain(sys.argv)", 0),
    ("malformed", "import sys\ndef", 0),
    (
        "local-class-shadows-alias",
        "import typer\ntype Alias = object\ndef outer():\n    class Alias: pass\n    def main(service: Alias): pass\n    typer.run(main)",
        0,
    ),
    (
        "alias-definition-scope",
        "import typer\ntype Alias = object\ndef main[object](service: Alias): pass\ntyper.run(main)",
        1,
    ),
    ("keyword-run", "import typer\ndef main(service): pass\ntyper.run(function=main)", 1),
    ("typed-keyword-run", "import typer\ndef main(service: str): pass\ntyper.run(function=main)", 0),
    ("untyped-varargs", "import typer\ndef main(*arguments): pass\ntyper.run(main)", 1),
    (
        "shadowed-type-alias",
        "import typer\ntype Erased = object\ndef main[Erased](service: Erased): pass\ntyper.run(main)",
        0,
    ),
)

_ISOLATED_TRANSPORT = """\
from pathlib import Path
import sys
from typing import NoReturn

def _fail(message: str) -> NoReturn:
    raise ValueError(message)

def _require(*, condition: bool, message: str) -> None:
    if not condition:
        _fail(message)

def _text(value: object) -> str:
    if not isinstance(value, str):
        _fail("native bridge value must be text")
    return value

def _path(value: object, *, real: bool = True) -> Path:
    rendered = _text(value)
    _require(condition=bool(rendered) and "\\0" not in rendered, message="invalid native bridge path")
    path = Path(rendered)
    _require(
        condition=path.is_absolute() and str(path) == rendered and ".." not in path.parts,
        message="noncanonical native bridge path",
    )
    if real:
        _require(condition=path.resolve() == path, message="native bridge path traverses a link")
    return path

def main(arguments: list[str] | None = None) -> int:
    supplied = sys.argv[1:] if arguments is None else arguments
    _require(
        condition=sys.flags.isolated == 1 and len(supplied) == 1,
        message="native byte bridge requires isolated fixed invocation",
    )
    if supplied[0] == "--node-path":
        return 0
    path = _path(supplied[0])
    return inspect_payload(path)
"""

_TRANSPORT_NEAR_MISSES = (
    ("missing-isolation", "sys.flags.isolated == 1 and len(supplied) == 1", "len(supplied) == 1"),
    ("nonexact-arity", "len(supplied) == 1", "len(supplied) >= 1"),
    ("different-arity", "len(supplied) == 1", "len(supplied) == 2"),
    ("wrong-boolean", "sys.flags.isolated == 1 and", "sys.flags.isolated == 1 or"),
    ("guard-does-not-raise", "raise ValueError(message)", "return None"),
    ("generator-raise", "raise ValueError(message)", "raise (yield ValueError(message))"),
    ("generator-yield-from", "raise ValueError(message)", "raise (yield from ())"),
    ("generator-delegation", "        _fail(message)", "        _fail((yield message))"),
    ("guard-wrong-polarity", "if not condition:", "if condition:"),
    (
        "guard-swallows-raise",
        "    raise ValueError(message)",
        "    try:\n        raise ValueError(message)\n    except ValueError:\n        return None",
    ),
    (
        "pre-guard-read",
        "    _require(\n        condition=sys.flags",
        "    consume(supplied[0])\n    _require(\n        condition=sys.flags",
    ),
    ("raw-alias-escape", "    return inspect_payload(path)", "    alias = supplied\n    return consume(alias)"),
    (
        "raw-closure-escape",
        "    return inspect_payload(path)",
        "    def captured():\n        return supplied\n    return captured()",
    ),
    ("raw-starred-escape", "    return inspect_payload(path)", "    return consume(*supplied)"),
    (
        "raw-mutation",
        "    return inspect_payload(path)",
        "    supplied.append('extra')\n    return inspect_payload(path)",
    ),
    ("raw-rebinding", "    return inspect_payload(path)", "    supplied = other\n    return inspect_payload(path)"),
    ("extra-index", "path = _path(supplied[0])", "path = _path(supplied[1])"),
    ("dynamic-probe", 'if supplied[0] == "--node-path":', 'if supplied[0].startswith("--"):'),
    ("unterminated-probe", "        return 0\n    path =", "        pass\n    path ="),
    ("shadowed-len", "def main(", "len = other\n\ndef main("),
    ("shadowed-string-check", "def _text(", "isinstance = other\n\ndef _text("),
    ("unproven-Path", "from pathlib import Path", "from pathlib import Path\nPath = other"),
    (
        "annotation-only-text",
        '    if not isinstance(value, str):\n        _fail("native bridge value must be text")\n',
        "",
    ),
    ("annotation-only-path", "    return path\n", "    return value\n"),
    ("unrelated-constructor-input", "path = Path(rendered)", "path = Path(other)"),
    ("rebound-helper", "def main(", "_require = other\n\ndef main("),
    ("checked-string-escape", "    path = Path(rendered)", "    consume(rendered)\n    path = Path(rendered)"),
    (
        "checked-string-rebinding",
        "    path = Path(rendered)",
        "    rendered = transform(rendered)\n    path = Path(rendered)",
    ),
    ("untyped-injected-arguments", "arguments: list[str] | None = None", "arguments=None"),
)


@pytest.mark.parametrize(("label", "source", "count"), CASES, ids=[case[0] for case in CASES])
def test_cli_contracts(label: str, source: str, count: int) -> None:
    findings = PreferTypedCli().check(Path("app/cli.py"), source)
    assert len(findings) == count, label
    assert all(finding.severity is Severity.ERROR for finding in findings)


def test_exact_suppression_and_generated_source() -> None:
    source = "import sys\nmain(sys.argv[1:])  # sarj-noqa: SARJ533 -- transparent process launcher forwards arguments\n"
    assert check_source([PreferTypedCli()], Path("app/cli.py"), source) == []
    assert PreferTypedCli().check(Path("generated/cli.py"), CASES[0][1]) == []


def test_location_and_no_automatic_migration() -> None:
    (finding,) = PreferTypedCli().check(Path("app/cli.py"), "import sys\nmain(sys.argv[1:])\n")
    assert (finding.line, finding.col) == (2, 6)
    assert finding.fixes == ()
    documentation = PreferTypedCli.documentation
    assert documentation is not None
    assert documentation.default_level is Severity.ERROR


def test_raw_argv_blocks_the_public_cli(tmp_path: Path) -> None:
    path = tmp_path / "cli.py"
    path.write_text(CASES[0][1])
    assert main(["check", "--rule", PreferTypedCli.id, str(path)]) == 1
    path.write_text("import typer\ndef main(service: str): pass\ntyper.run(main)\n")
    assert main(["check", "--rule", PreferTypedCli.id, str(path)]) == 0


def test_isolated_path_transport_and_renamed_equivalent() -> None:
    assert PreferTypedCli().check(Path("app/worker.py"), _ISOLATED_TRANSPORT) == []
    renamed = (
        _ISOLATED_TRANSPORT.replace("from pathlib import Path", "from pathlib import Path as Location")
        .replace("Path(", "Location(")
        .replace("-> Path:", "-> Location:")
        .replace("import sys", "import sys as process_runtime")
        .replace("sys.", "process_runtime.")
        .replace('"--node-path"', '"inspect-runtime"')
        .replace("_fail", "reject")
        .replace("_require", "ensure")
        .replace("_text", "checked_text")
        .replace("_path", "checked_location")
        .replace("message", "reason")
        .replace("condition", "valid")
        .replace("arguments", "tokens")
        .replace("supplied", "packet")
        .replace("rendered", "checked")
        .replace("real", "resolve_links")
        .replace("main", "transport_entry")
    )
    renamed = re.sub(r"\bpath\b", "location", renamed)
    assert PreferTypedCli().check(Path("tools/ipc/transport.py"), renamed) == []


def test_native_worker_uses_the_source_proven_transport() -> None:
    root = Path(__file__).resolve().parents[4]
    worker = root / "packages/standards/src/sarj_standards/libs/linting/native_byte_process.py"
    assert PreferTypedCli().check(Path("arbitrary/isolated_worker.py"), worker.read_text()) == []


@pytest.mark.parametrize(
    ("label", "before", "after"), _TRANSPORT_NEAR_MISSES, ids=[case[0] for case in _TRANSPORT_NEAR_MISSES]
)
def test_transport_near_misses_remain_errors(label: str, before: str, after: str) -> None:
    assert _ISOLATED_TRANSPORT.count(before) == 1, label
    source = _ISOLATED_TRANSPORT.replace(before, after)
    (finding,) = PreferTypedCli().check(Path("app/worker.py"), source)
    assert finding.code == PreferTypedCli.code, label
    assert finding.severity is Severity.ERROR, label
    assert finding.fixes == (), label


@pytest.mark.parametrize(
    "additional",
    [
        "import argparse\nparser = argparse.ArgumentParser()\n",
        "import typer\ndef untyped(value): pass\ntyper.run(untyped)\n",
    ],
    ids=("ordinary-parser", "untyped-registered-command"),
)
def test_transport_retention_preserves_other_cli_findings(additional: str) -> None:
    (finding,) = PreferTypedCli().check(Path("app/worker.py"), _ISOLATED_TRANSPORT + additional)
    assert finding.code == PreferTypedCli.code
    assert finding.severity is Severity.ERROR
