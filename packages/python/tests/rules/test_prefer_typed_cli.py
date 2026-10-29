from pathlib import Path

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
