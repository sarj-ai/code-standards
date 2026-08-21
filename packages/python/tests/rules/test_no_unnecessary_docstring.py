from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import deduplicate_diagnostics
from sarj_python_lint.rule_base import Rule, Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet
from sarj_python_lint.rules.no_long_comment import NoLongComment
from sarj_python_lint.rules.no_unnecessary_docstring import NoUnnecessaryDocstring
from sarj_python_lint.rules.redundant_class_docstring import RedundantClassDocstring
from sarj_python_lint.rules.redundant_docstring import RedundantDocstring
from sarj_python_lint.rules.redundant_module_docstring import RedundantModuleDocstring
from sarj_python_lint.rules.restated_test_docstring import RestatedTestDocstring


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/service.py") -> list[Diagnostic]:
    return NoUnnecessaryDocstring().check(Path(path), source)


_PUBLIC_EXAMPLES = NoUnnecessaryDocstring.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def test_flags_module_class_sync_and_async_function_docstrings() -> None:
    source = '''"""Service entry points."""

class Service:
    """Coordinates the request lifecycle."""

    def run(self) -> None:
        """Commit the prepared request."""
        return None

async def stop() -> None:
    """Drain pending work before shutdown."""
    return None
'''

    findings = _check(source)

    assert [(finding.line, finding.code, finding.severity) for finding in findings] == [
        (1, "SARJ420", Severity.ERROR),
        (4, "SARJ420", Severity.ERROR),
        (7, "SARJ420", Severity.ERROR),
        (11, "SARJ420", Severity.ERROR),
    ]
    assert {finding.message for finding in findings} == {
        "No docstring consumer detected — delete it; make author-controlled names, types, and structure explain the code."
    }


@pytest.mark.parametrize(
    "source",
    [
        'def explain() -> None:\n    """>>> 1 + 1\n    2\n    """\n    return None\n',
        'from pydantic import BaseModel\n\nclass Payload(BaseModel):\n    """Published in JSON Schema."""\n    value: str\n',
        'from pydantic import BaseModel\n\nclass Payload(BaseModel):\n    value: str\n\nclass Event(Payload):\n    """Published by inherited Pydantic schema generation."""\n    kind: str\n',
        'from enum import StrEnum\n\nclass Status(StrEnum):\n    """May be published by a schema consumer in another module."""\n    READY = "ready"\n',
        'import pydantic\n\n@pydantic.computed_field\ndef total(self) -> int:\n    """Published in JSON Schema."""\n    return 1\n',
        'import strawberry\n\n@strawberry.type\nclass Payload:\n    """Published in GraphQL schema."""\n    value: str\n',
        'from agents import function_tool\n\n@function_tool\ndef lookup() -> str:\n    """Description sent to the model."""\n    return "x"\n',
        'from livekit.agents import function_tool\n\n@function_tool()\ndef lookup() -> str:\n    """Description sent to the model."""\n    return "x"\n',
        'from livekit.agents.llm import function_tool as tool\n\n@tool()\ndef lookup() -> str:\n    """Description sent to the model."""\n    return "x"\n',
        'import livekit.agents.llm as llm\n\n@llm.function_tool()\ndef lookup() -> str:\n    """Description sent to the model."""\n    return "x"\n',
        'import livekit.agents.llm\n\n@livekit.agents.llm.function_tool()\ndef lookup() -> str:\n    """Description sent to the model."""\n    return "x"\n',
        'from livekit.agents.llm import function_tool\n\ndef lookup() -> str:\n    """Description sent to the model."""\n    return "x"\n\ntool = function_tool(lookup)\n',
        'from fastapi import APIRouter\n\ndef mount(router: APIRouter) -> None:\n    @router.get("/health")\n    def health() -> str:\n        """Published in OpenAPI."""\n        return "ok"\n',
        'import fastapi as api\n\ndef mount() -> None:\n    router = api.APIRouter()\n\n    @router.post("/items")\n    def create() -> str:\n        """Published in OpenAPI."""\n        return "ok"\n',
        'from fastapi import APIRouter\n\ndef mount() -> None:\n    Router = APIRouter\n    router = Router()\n\n    @router.get("/items")\n    def read() -> str:\n        """Published in OpenAPI."""\n        return "ok"\n',
        'from agents import function_tool\n\n@function_tool\ndef consumed() -> str:\n    """Published tool description."""\n    return "ok"\n\nfunction_tool = custom_tool\n',
        'from pydantic import BaseModel\n\ndef build() -> None:\n    class Base(BaseModel):\n        value: str\n\n    class Child(Base):\n        """Published by inherited Pydantic schema generation."""\n        other: str\n',
        'import pytest\n\n@pytest.fixture\ndef account() -> object:\n    """Description shown by pytest --fixtures."""\n    return object()\n',
        'import pytest_asyncio as pa\n\n@pa.fixture\nasync def account() -> object:\n    """Description shown by pytest --fixtures."""\n    return object()\n',
        'import typer\n\napp = typer.Typer()\n\n@app.command()\ndef serve() -> None:\n    """Description shown in CLI help."""\n    return None\n',
        'from typer import Typer as Cli\n\nFactory = Cli\napp = Factory()\n\n@app.callback()\ndef main() -> None:\n    """Description shown in CLI help."""\n    return None\n',
        'import click\n\n@click.command()\ndef serve() -> None:\n    """Description shown in CLI help."""\n    return None\n',
        'from click import command as cli_command\n\n@cli_command()\ndef serve() -> None:\n    """Description shown in CLI help."""\n    return None\n',
        'import click\n\n@click.group()\ndef cli() -> None:\n    """Description shown in CLI help."""\n    return None\n',
        'import click\n\n@click.group()\ndef cli() -> None:\n    return None\n\n@cli.command()\ndef serve() -> None:\n    """Description shown in CLI help."""\n    return None\n',
        'import click\n\ncli = click.Group()\n\n@cli.command()\ndef serve() -> None:\n    """Description shown in CLI help."""\n    return None\n',
        'import typer\n\ndef register(app: typer.Typer) -> None:\n    @app.command()\n    def serve() -> None:\n        """Description shown in CLI help."""\n        return None\n',
        'import typer\n\napp = typer.Typer()\n\n@app.command(**options)\ndef serve() -> None:\n    """May be consumed through dynamic options."""\n    return None\n',
        'import click\n\n@click.command(**options)\ndef serve() -> None:\n    """May be consumed through dynamic options."""\n    return None\n',
        '@property\ndef value(self) -> str:\n    """Published as the property descriptor doc."""\n    return self._value\n',
    ],
)
def test_doctest_schema_and_framework_consumers_are_exempt(source: str) -> None:
    assert _check(source) == []


def test_livekit_raw_schema_does_not_exempt_an_unused_docstring() -> None:
    source = '''from livekit.agents.llm import function_tool

@function_tool(raw_schema={"name": "lookup", "parameters": {}})
def lookup() -> str:
    """Not used by the raw tool schema."""
    return "x"
'''

    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    "source",
    [
        'class Router:\n    def get(self, path: str): ...\n\nrouter = Router()\n\n@router.get("/health")\ndef health() -> str:\n    """Human-only notes."""\n    return "ok"\n',
        'from fastapi import APIRouter\n\nrouter = APIRouter()\n\n@router.get("/health", description="Published explicitly")\ndef health() -> str:\n    """Human-only notes."""\n    return "ok"\n',
        'from fastapi import APIRouter\n\nrouter = APIRouter()\nrouter = custom_router\n\n@router.get("/health")\ndef health() -> str:\n    """Human-only notes."""\n    return "ok"\n',
    ],
)
def test_unproven_or_overridden_fastapi_routes_do_not_exempt_docstrings(source: str) -> None:
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    "source",
    [
        'class Typer:\n    pass\n\napp = Typer()\n\n@app.command()\ndef serve() -> None:\n    """Human-only notes."""\n    return None\n',
        'from .typer import Typer\n\napp = Typer()\n\n@app.command()\ndef serve() -> None:\n    """Human-only notes."""\n    return None\n',
        'import typer\n\napp = typer.Typer()\n\n@app.command(help="Published explicitly")\ndef serve() -> None:\n    """Human-only notes."""\n    return None\n',
        'import typer\n\napp = typer.Typer()\napp = custom_app\n\n@app.command()\ndef serve() -> None:\n    """Human-only notes."""\n    return None\n',
        'import click\n\n@click.command(help="Published explicitly")\ndef serve() -> None:\n    """Human-only notes."""\n    return None\n',
        'from .click import command\n\n@command()\ndef serve() -> None:\n    """Human-only notes."""\n    return None\n',
        'import click\nclick = custom_click\n\n@click.command()\ndef serve() -> None:\n    """Human-only notes."""\n    return None\n',
        'class Cli:\n    def command(self): ...\n\ncli = Cli()\n\n@cli.command()\ndef serve() -> None:\n    """Human-only notes."""\n    return None\n',
        'import click\n\n@click.group()\ndef cli() -> None:\n    return None\n\n@cli.command(help="Published explicitly")\ndef serve() -> None:\n    """Human-only notes."""\n    return None\n',
    ],
)
def test_unproven_or_overridden_cli_decorators_do_not_exempt_docstrings(source: str) -> None:
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    "source",
    [
        '"""CLI help."""\n\nparser = Parser(description=__doc__)\n',
        '"""CLI help."""\n\ndef main() -> None:\n    parser = Parser(description=__doc__)\n',
        'def operation() -> None:\n    """Plugin description."""\n    return None\n\nregister(operation.__doc__)\n',
        'class Plugin:\n    """Plugin description."""\n    value = 1\n\nhelp(Plugin)\n',
        'import inspect\n\ndef operation() -> None:\n    """Plugin description."""\n    return None\n\ninspect.getdoc(operation)\n',
        'class Plugin:\n    """Plugin description."""\n    value = 1\n\ndef publish() -> None:\n    help(Plugin)\n',
    ],
)
def test_explicit_runtime_reads_are_exempt(source: str) -> None:
    assert _check(source) == []


def test_a_runtime_read_exempts_only_the_named_owner() -> None:
    source = '''def consumed() -> None:
    """Plugin description."""
    return None

def human_only() -> None:
    """Implementation notes."""
    return None

publish(consumed.__doc__)
'''

    findings = _check(source)

    assert [(finding.line, finding.code) for finding in findings] == [(6, "SARJ420")]


def test_runtime_reads_use_qualified_owner_identity() -> None:
    source = '''class Alpha:
    def run(self) -> None:
        """Human-only notes."""
        return None

class Beta:
    def run(self) -> None:
        """Published plugin help."""
        return None

publish(Beta.run.__doc__)
'''
    assert [(finding.line, finding.code) for finding in _check(source)] == [(3, "SARJ420")]


def test_simple_alias_to_runtime_consumer_is_followed() -> None:
    source = '''def operation() -> None:
    """Published plugin help."""
    return None

callback = operation
publish(callback.__doc__)
'''
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        '@get\ndef operation() -> None:\n    """Human-only notes."""\n    return None\n',
        'from .agents import function_tool\n\n@function_tool\ndef operation() -> None:\n    """Human-only notes."""\n    return None\n',
        'from .pydantic import BaseModel\n\nclass Payload(BaseModel):\n    """Human-only notes."""\n    value: str\n',
        'from agents import function_tool\n\n@function_tool(use_docstring_info=False)\ndef operation() -> None:\n    """Human-only notes."""\n    return None\n',
        'import pydantic\n\n@pydantic.computed_field(description="Published explicitly")\ndef operation() -> int:\n    """Human-only notes."""\n    return 1\n',
        'class BaseModel:\n    pass\n\nclass Payload(BaseModel):\n    """Human-only notes."""\n    value: str\n',
        'def getdoc(value: object) -> str:\n    return "x"\n\ndef operation() -> None:\n    """Human-only notes."""\n    return None\n\npublish(getdoc(operation))\n',
        'from inspect import getdoc\n\ndef getdoc(value: object) -> str:\n    return "local"\n\ndef operation() -> None:\n    """Human-only notes."""\n    return None\n\npublish(getdoc(operation))\n',
        'from pydantic import BaseModel\n\nclass BaseModel:\n    pass\n\nclass Payload(BaseModel):\n    """Human-only notes."""\n    value: str\n',
    ],
)
def test_unproven_framework_and_consumer_names_do_not_exempt(source: str) -> None:
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_cross_module_pydantic_inheritance_is_exempt(tmp_path: Path) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    base_path = package / "base.py"
    base_source = "from pydantic import BaseModel\n\nclass Record(BaseModel):\n    value: str\n"
    base_path.write_text(base_source, encoding="utf-8")
    response_path = package / "response.py"
    response_source = (
        'from app.base import Record\n\nclass SaveResponse(Record):\n    """Published in OpenAPI."""\n    saved: bool\n'
    )
    response_path.write_text(response_source, encoding="utf-8")
    rule = NoUnnecessaryDocstring()
    rule.prepare(
        ProjectIndexSet.build([base_path, response_path], {base_path: base_source, response_path: response_source})
    )

    assert rule.check(response_path, response_source) == []


def test_syntax_required_class_and_function_docstrings_are_exempt_but_a_module_is_not() -> None:
    source = '''"""Human-only module prose."""

class Marker:
    """The only class statement."""

def marker() -> None:
    """The only function statement."""
'''

    findings = _check(source)

    assert [(finding.line, finding.code) for finding in findings] == [(1, "SARJ420")]


@pytest.mark.parametrize(
    "source",
    [
        'def kept() -> None:\n    """External documentation source."""  # sarj-noqa: SARJ420 — published by custom docs\n    return None\n',
        'def kept() -> None:\n    """External documentation\n    source.\n    """  # sarj-noqa: SARJ420 — published by custom docs\n    return None\n',
        '"""External package documentation."""  # sarj-noqa: SARJ420 — published by custom docs\n\nVALUE = 1\n',
    ],
)
def test_exact_sarj_noqa_on_the_docstring_is_an_escape_hatch(source: str) -> None:
    assert _check(source) == []


def test_an_unrelated_suppression_does_not_hide_the_warning() -> None:
    source = 'def kept() -> None:\n    """External documentation."""  # sarj-noqa: SARJ050 — separate rule\n    return None\n'

    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_suppression_requires_a_reason_and_cannot_live_inside_docstring_text() -> None:
    bare = 'def kept() -> None:\n    """External documentation."""  # sarj-noqa: SARJ420\n    return None\n'
    embedded = 'def kept() -> None:\n    """Notes.\n    # sarj-noqa: SARJ420 — not a source comment\n    """\n    return None\n'

    assert [finding.code for finding in _check(bare)] == ["SARJ420"]
    assert [finding.code for finding in _check(embedded)] == ["SARJ420"]


@pytest.mark.parametrize(
    "source",
    [
        '# Generated by protoc\n"""Generated module."""\nVALUE = 1\n',
        'def broken(:\n    """Not parseable."""\n',
    ],
)
def test_generated_and_malformed_sources_are_ignored(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    ("path", "source", "specific_rule", "specific_code"),
    [
        ("package/element.py", '"""Element module."""\n\nVALUE = 1\n', RedundantModuleDocstring(), "SARJ099"),
        (
            "app/service.py",
            'class RetryPolicy:\n    """The retry policy."""\n    attempts = 3\n',
            RedundantClassDocstring(),
            "SARJ085",
        ),
        (
            "app/service.py",
            'def update_message(message_id: str):\n    """Update the message."""\n    return None\n',
            RedundantDocstring(),
            "SARJ050",
        ),
        (
            "tests/test_retry.py",
            'def test_retries_failed_request():\n    """Retries failed request."""\n    assert retry()\n',
            RestatedTestDocstring(),
            "SARJ088",
        ),
    ],
)
def test_specific_existing_docstring_diagnostic_wins_precedence(
    path: str,
    source: str,
    specific_rule: Rule,
    specific_code: str,
) -> None:
    raw = [*_check(source, path), *specific_rule.check(Path(path), source)]

    findings = deduplicate_diagnostics(raw, source=source)

    assert [finding.code for finding in findings] == [specific_code]


def test_long_comment_diagnostic_wins_over_default_deny_warning() -> None:
    source = '"""One fact. Two facts. Three facts. Four facts. Five facts. Six facts. Seven facts. Eight facts."""\n'
    raw = [*_check(source), *NoLongComment().check(Path("app/service.py"), source)]

    findings = deduplicate_diagnostics(raw, source=source)

    assert [finding.code for finding in findings] == ["SARJ091"]
