from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import deduplicate_diagnostics
from sarj_python_lint.rule_base import Rule, Severity
from sarj_python_lint.rules._project_index import ProjectIndexSet
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


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_deep_annotation_preserves_docstring_owner_examples(example: RuleExample) -> None:
    annotation = " | ".join(["str"] * 3001 + ["None"])
    source = f"{example.focus_file.source}\nclass AnnotationCarrier:\n    payload: {annotation}\n"
    assert len(_check(source, str(example.focus_path))) == example.expected_count


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
    ("source", "line"),
    [
        ('""\nvalue = 1\n', 1),
        ('class Service:\n    ""\n    value = 1\n', 2),
        ('def run():\n    ""\n    return 1\n', 2),
        ('async def run():\n    ""\n    return 1\n', 2),
        ('def outer():\n    def inner():\n        ""\n        return 1\n    return inner\n', 3),
        ('class Service:\n    async def run(self):\n        ""\n        return 1\n', 3),
    ],
    ids=["module", "class", "function", "async-function", "nested-function", "nested-async-method"],
)
def test_empty_docstrings_remain_eligible(source: str, line: int) -> None:
    assert [(finding.line, finding.code) for finding in _check(source)] == [(line, "SARJ420")]


def test_flags_test_module_incident_narration_with_ticket_and_cross_file_reference() -> None:
    source = (
        '"""Fair-share behavior after INC-2048; core picker semantics are pinned by '
        'test_dispatch_order.py."""\n\n'
        "def test_small_account_is_served() -> None:\n"
        "    assert dispatch_order() == ['small', 'large']\n"
    )

    findings = _check(source, "tests/test_dispatch_fair_share.py")

    assert [(finding.line, finding.code, finding.severity) for finding in findings] == [(1, "SARJ420", Severity.ERROR)]


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


def test_class_only_prose_is_an_error_but_function_stubs_remain_exempt() -> None:
    source = '''"""Human-only module prose."""

class Marker:
    """The only class statement."""

def marker() -> None:
    """The only function statement."""
'''

    findings = _check(source)

    assert [(finding.line, finding.code) for finding in findings] == [(1, "SARJ420"), (4, "SARJ420")]


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
    "docstring",
    [
        '"""Text quoting # sarj-noqa: SARJ420 -- explanation."""',
        '"""Text.\n    # sarj-noqa: SARJ420 -- explanation."""',
        '"""Text quoting # sarj-noqa: SARJ420 -- explanation."""  # sarj-noqa: SARJ420',
    ],
)
def test_closing_line_suppression_text_requires_a_real_explained_comment(docstring: str) -> None:
    source = f"class Example:\n    {docstring}\n    value = 1\n"
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_literal_suppression_text_does_not_mask_a_real_explained_source_comment() -> None:
    source = (
        "class Example:\n"
        '    """Text quoting # sarj-noqa: SARJ420 -- example."""  # sarj-noqa: SARJ420 -- published docs\n'
        "    value = 1\n"
    )
    assert _check(source) == []


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
    specific = [finding for finding in raw if finding.code == specific_code]
    expected = (
        [specific_code]
        if any(finding.severity is Severity.ERROR for finding in specific)
        else ["SARJ420", specific_code]
    )

    assert [finding.code for finding in findings] == expected


@pytest.mark.parametrize(
    "wrapper", ["if enabled:", "try:", "for item in values:", "with scope():", "match value:\n    case 1:"]
)
def test_control_flow_docstring_owners_are_indexed(wrapper: str) -> None:
    depth = 8 if wrapper.startswith("match") else 4
    body = 'def run():\n    """Run the selected implementation."""\n    return 1\n'
    source = wrapper + "\n" + textwrap.indent(body, " " * depth)
    if wrapper == "try:":
        source += "except Exception:\n    pass\n"
    assert len(_check(source)) == 1


def test_control_flow_owner_consumption_is_preserved() -> None:
    source = 'if enabled:\n    def run():\n        """Runtime help text."""\n        return 1\nhelp(run)\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "decorator",
    [
        "functools.lru_cache",
        "functools.lru_cache()",
        "functools.lru_cache(maxsize=1)",
        "functools.lru_cache(None, typed=True)",
        "functools.lru_cache(1, True)",
        "functools.lru_cache(-1)",
    ],
)
def test_canonical_lru_cache_copies_the_decorated_docstring(decorator: str) -> None:
    source = (
        "import functools\n\n"
        f"@{decorator}\n"
        'def result() -> str:\n    """Copied onto the cache wrapper."""\n    return "value"\n'
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    ("imports", "decorator"),
    [
        ("import functools as ft", "ft.lru_cache(maxsize=1)"),
        ("from functools import lru_cache as cache", "cache(maxsize=1)"),
    ],
)
def test_lru_cache_import_aliases_keep_canonical_identity(imports: str, decorator: str) -> None:
    source = f'{imports}\n\n@{decorator}\ndef result():\n    """Copied cache metadata."""\n    return 1\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "from local import functools\n",
        "import functools\nfunctools = replacement\n",
        "import functools\nfunctools.lru_cache = replacement\n",
        "import functools\nnamespace = functools.__dict__\n",
    ],
)
def test_unproven_lru_cache_does_not_claim_metadata_consumption(prefix: str) -> None:
    source = prefix + '@functools.lru_cache(maxsize=1)\ndef result():\n    """Human-only prose."""\n    return 1\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize("options", ["maxsize=unknown", "**options", "unknown=True", "1, maxsize=2"])
def test_unknown_or_invalid_lru_cache_options_do_not_prove_copying(options: str) -> None:
    source = (
        f"import functools\n\n@functools.lru_cache({options})\ndef result():\n"
        '    """Human-only prose."""\n    return 1\n'
    )
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    ("arguments", "copied"),
    [
        ("target", True),
        ('target, ("__name__", "__doc__")', True),
        ('target, assigned=["__doc__"]', True),
        ('wrapped=target, assigned=("__doc__",)', True),
        ("target, assigned=()", False),
        ('target, assigned=("__name__",)', False),
        ('target, ("__name__",)', False),
        ("target, assigned=assigned", False),
        ("target, **options", False),
    ],
)
def test_direct_wraps_requires_proven_doc_assignment(arguments: str, copied: bool) -> None:
    source = (
        'from functools import wraps\n\ndef target():\n    """Copied input metadata."""\n    return 1\n\n'
        f"@wraps({arguments})\ndef wrapper():\n    return target()\n"
    )
    assert [(finding.line, finding.code) for finding in _check(source)] == ([] if copied else [(4, "SARJ420")])


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "import functools\nfunctools.wraps = replacement\n",
        "import functools\nnamespace = functools.__dict__\n",
        "import functools\nchange(functools)\n",
        "import functools\nchange(functools.wraps)\n",
        "import functools\nfunctools.wraps.__defaults__ = ((), ())\n",
    ],
)
def test_direct_wraps_requires_an_unmutated_canonical_binding(prefix: str) -> None:
    source = (
        f'{prefix}def target():\n    """Input prose."""\n    return 1\n\n'
        "@functools.wraps(target)\ndef wrapper():\n    return target()\n"
    )
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_unrelated_scope_shadow_does_not_erase_a_direct_copy() -> None:
    source = '''from functools import wraps

def unrelated(wraps):
    return wraps

def target():
    """Copied metadata."""
    return 1

@wraps(target)
def wrapper():
    return target()
'''
    assert _check(source) == []


def test_enclosing_parameter_shadow_cannot_prove_direct_wraps() -> None:
    source = '''from functools import wraps

def target():
    """Input prose."""
    return 1

def build(wraps):
    @wraps(target)
    def wrapper():
        return target()
    return wrapper
'''
    assert [(finding.line, finding.code) for finding in _check(source)] == [(4, "SARJ420")]


_METADATA_FACTORY = '''import functools

def copy_metadata(method):
    """Factory prose has no consumer."""
    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        """Wrapper implementation prose is overwritten."""
        return method(*args, **kwargs)
    return wrapper
'''
_METADATA_OWNER = '''def result():
    """Copied input description."""
    return 1
'''


def _project_metadata_findings(
    tmp_path: Path,
    factory: str,
    prefix: str = "from app.decorators import copy_metadata",
    decorator: str = "copy_metadata",
) -> list[Diagnostic]:
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    factory_path = package / "decorators.py"
    owner_path = package / "service.py"
    owner = prefix + f"\n\n@{decorator}\n" + _METADATA_OWNER
    factory_path.write_text(factory, encoding="utf-8")
    owner_path.write_text(owner, encoding="utf-8")
    rule = NoUnnecessaryDocstring()
    rule.prepare(ProjectIndexSet.build([factory_path, owner_path], {factory_path: factory, owner_path: owner}))
    return rule.check(owner_path, owner)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_source_proven_imported_factory_copies_only_input_metadata(tmp_path: Path, asynchronous: bool) -> None:
    factory = _METADATA_FACTORY
    if asynchronous:
        factory = factory.replace("def wrapper", "async def wrapper").replace("return method(", "return await method(")
    assert _project_metadata_findings(tmp_path, factory) == []
    assert [(finding.line, finding.code) for finding in _check(factory)] == [(4, "SARJ420"), (7, "SARJ420")]


def test_same_module_factory_is_resolved_from_the_current_tree() -> None:
    source = _METADATA_FACTORY + "\n@copy_metadata\n" + _METADATA_OWNER
    assert [(finding.line, finding.code) for finding in _check(source)] == [(4, "SARJ420"), (7, "SARJ420")]


@pytest.mark.parametrize(
    "mutation",
    [
        "    method = replacement\n",
        "    method, other = replacement, None\n",
        "    wrapper = replacement\n",
        "    if enabled:\n        return replacement\n",
    ],
)
def test_factory_parameter_wrapper_rebinding_or_alternate_return_is_opaque(tmp_path: Path, mutation: str) -> None:
    factory = _METADATA_FACTORY.replace("    return wrapper\n", f"{mutation}    return wrapper\n")
    assert [finding.code for finding in _project_metadata_findings(tmp_path, factory)] == ["SARJ420"]


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(("@functools.wraps(method)", "@functools.wraps(method, assigned=())"), id="assigned-excludes-doc"),
        pytest.param(
            ("@functools.wraps(method)", "@functools.wraps(method, assigned=assigned)"), id="assigned-unknown"
        ),
        pytest.param(("@functools.wraps(method)", "@unknown\n    @functools.wraps(method)"), id="unknown-outer"),
        pytest.param(("@functools.wraps(method)", "@functools.wraps(method)\n    @unknown"), id="unknown-inner"),
        pytest.param(("@functools.wraps(method)", "@other.wraps(method)"), id="noncanonical-wraps"),
        pytest.param(("import functools", "import functools\nfunctools.wraps = replacement"), id="mutated-wraps"),
        pytest.param(("def copy_metadata(method):", "@unknown\ndef copy_metadata(method):"), id="decorated-factory"),
    ],
)
def test_unproven_factory_metadata_flow_keeps_default_deny(tmp_path: Path, change: tuple[str, str]) -> None:
    factory = _METADATA_FACTORY.replace(*change)
    assert [finding.code for finding in _project_metadata_findings(tmp_path, factory)] == ["SARJ420"]


def test_assignment_aliases_of_source_decorators_remain_opaque(tmp_path: Path) -> None:
    prefix = "from .decorators import copy_metadata as copied\ncopy_metadata = copied"
    # An assignment alias is deliberately opaque; canonical import aliases are supported.
    assert [finding.code for finding in _project_metadata_findings(tmp_path, _METADATA_FACTORY, prefix)] == ["SARJ420"]


def test_current_source_cannot_borrow_a_stale_index_decorator_binding(tmp_path: Path) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    factory_path = package / "decorators.py"
    owner_path = package / "service.py"
    indexed = "from app.decorators import copy_metadata\n\n@copy_metadata\n" + _METADATA_OWNER
    current = indexed.replace("@copy_metadata", "copy_metadata = replacement\n\n@copy_metadata")
    factory_path.write_text(_METADATA_FACTORY, encoding="utf-8")
    owner_path.write_text(current, encoding="utf-8")
    rule = NoUnnecessaryDocstring()
    rule.prepare(
        ProjectIndexSet.build([factory_path, owner_path], {factory_path: _METADATA_FACTORY, owner_path: indexed})
    )
    assert [finding.code for finding in rule.check(owner_path, current)] == ["SARJ420"]


@pytest.mark.parametrize(
    "prefix", ["from app.decorators import copy_metadata as copied", "from .decorators import copy_metadata as copied"]
)
def test_import_aliases_of_source_decorators_are_resolved(tmp_path: Path, prefix: str) -> None:
    assert _project_metadata_findings(tmp_path, _METADATA_FACTORY, prefix, "copied") == []


@pytest.mark.parametrize(
    "decorator", ["dataclasses.dataclass", "dataclasses.dataclass()", "dataclasses.dataclass(frozen=True, slots=True)"]
)
def test_dataclass_incidental_metadata_does_not_exempt_class_prose(decorator: str) -> None:
    source = f'import dataclasses\n\n@{decorator}\nclass Record:\n    """Read before fallback signature generation."""\n    value: int\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    ("prefix", "decorator"),
    [
        ("import dataclasses as ds", "ds.dataclass(frozen=True, slots=True)"),
        ("from dataclasses import dataclass as model", "model"),
    ],
)
def test_dataclass_aliases_do_not_exempt_class_prose(prefix: str, decorator: str) -> None:
    source = f'{prefix}\n\n@{decorator}\nclass Record:\n    """Read as dataclass metadata."""\n    value: int\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "from local import dataclasses\n",
        "import dataclasses\ndataclasses = replacement\n",
        "import dataclasses\ndataclasses.dataclass = replacement\n",
        "import dataclasses\nnamespace = dataclasses.__dict__\n",
    ],
)
def test_unproven_dataclass_does_not_exempt_class_prose(prefix: str) -> None:
    source = (
        prefix
        + '@dataclasses.dataclass(frozen=True, slots=True)\nclass Record:\n    """Human-only prose."""\n    value: int\n'
    )
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    "decorator",
    [
        "typing.dataclass_transform()",
        "dataclasses.dataclass(**options)",
        "dataclasses.dataclass(frozen=unknown)",
        "dataclasses.dataclass(unknown=True)",
    ],
)
def test_transform_and_unknown_dataclass_options_are_not_doc_consumers(decorator: str) -> None:
    source = f'import dataclasses\nimport typing\n\n@{decorator}\nclass Record:\n    """Human-only prose."""\n    value: int\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_unrelated_namespace_mutation_preserves_cache_consumer_only() -> None:
    source = 'import dataclasses\nimport functools\nimport other\nother.__dict__["dataclass"] = replacement\n@dataclasses.dataclass\nclass Record:\n    """Read as dataclass metadata."""\n    value: int\n@functools.lru_cache(maxsize=1)\ndef result():\n    """Copied cache metadata."""\n    return 1'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize("decorator", ["classmethod", "staticmethod", "builtins.classmethod", "builtins.staticmethod"])
def test_builtin_descriptors_copy_the_method_docstring(decorator: str) -> None:
    source = f'import builtins\n\nclass Service:\n    @{decorator}\n    def run(cls):\n        """Copied onto the method descriptor."""\n        return 1\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "decorator", ["classmethod()", "staticmethod()", "other", "typing.override", "abc.abstractmethod"]
)
def test_nonconsumer_or_invalid_method_decorators_do_not_exempt_prose(decorator: str) -> None:
    source = f'import abc\nimport typing\n\nclass Service:\n    @{decorator}\n    def run(cls):\n        """Human-only method prose."""\n        return 1\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    "prefix",
    [
        "classmethod = replacement",
        "from local import classmethod",
        "import builtins\nbuiltins.classmethod = replacement",
    ],
)
def test_shadowed_or_mutated_builtin_descriptor_is_opaque(prefix: str) -> None:
    source = f'{prefix}\nclass Service:\n    @classmethod\n    def run(cls):\n        """Human-only method prose."""\n        return 1\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize("consumer", ["classmethod", "staticmethod", "functools.lru_cache", "dataclasses.dataclass"])
def test_direct_functional_metadata_consumers_exempt_only_the_input(consumer: str) -> None:
    source = "\n".join(
        [
            "import functools",
            "import dataclasses",
            "class Record:",
            '    """Consumed input metadata."""',
            "    value: int",
            "def operation():",
            '    """Consumed function metadata."""',
            "    return 1",
            f"consumed = {consumer}(Record)"
            if consumer == "dataclasses.dataclass"
            else f"consumed = {consumer}(operation)",
        ]
    )
    expected_lines = [4, 7] if consumer == "dataclasses.dataclass" else [4]
    assert [(finding.line, finding.code) for finding in _check(source)] == [
        (line, "SARJ420") for line in expected_lines
    ]


def test_nested_functional_consumer_preserves_lexical_owner_identity() -> None:
    source = 'def operation():\n    """Human-only outer prose."""\n    return 1\n\ndef build():\n    def operation():\n        """Copied nested metadata."""\n        return 2\n    return staticmethod(operation)\n'
    assert [(finding.line, finding.code) for finding in _check(source)] == [(2, "SARJ420")]


def test_functional_consumer_parameter_shadow_does_not_exempt_a_module_owner() -> None:
    source = 'def operation():\n    """Human-only module prose."""\n    return 1\n\ndef build(operation):\n    return staticmethod(operation)\n'
    assert [(finding.line, finding.code) for finding in _check(source)] == [(2, "SARJ420")]


def test_rebound_direct_wraps_input_does_not_exempt_its_original_owner() -> None:
    source = 'from functools import wraps\ndef target():\n    """Original prose is no longer referenced."""\n    return 1\ntarget = replacement\n@wraps(target)\ndef wrapper():\n    return 1\n'
    assert [(finding.line, finding.code) for finding in _check(source)] == [(3, "SARJ420")]


@pytest.mark.parametrize("descriptor", ["classmethod", "staticmethod"])
def test_canonical_descriptor_import_aliases(descriptor: str) -> None:
    source = f'from builtins import {descriptor} as copied\nclass Service:\n    @copied\n    def run(cls):\n        """Copied descriptor metadata."""\n        return 1\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "consumer",
    [
        "classmethod()",
        "staticmethod(operation, extra)",
        "functools.lru_cache(operation, typed=unknown)",
        "dataclasses.dataclass(Record, unknown=True)",
    ],
)
def test_invalid_or_unknown_functional_consumers_do_not_exempt_inputs(consumer: str) -> None:
    source = "\n".join(
        [
            "import functools",
            "import dataclasses",
            "class Record:",
            '    """Class prose."""',
            "    value: int",
            "def operation():",
            '    """Function prose."""',
            "    return 1",
            f"copied = {consumer}",
        ]
    )
    assert [(finding.line, finding.code) for finding in _check(source)] == [(4, "SARJ420"), (7, "SARJ420")]


def test_descriptor_global_rebinding_is_not_an_unshadowed_builtin() -> None:
    source = 'def replace():\n    global classmethod\n    classmethod = replacement\nreplace()\nclass Service:\n    @classmethod\n    def run(cls):\n        """Human-only prose."""\n        return 1\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_dataclass_functional_form_requires_a_class_owner() -> None:
    source = 'from dataclasses import dataclass\ndef operation():\n    """A function cannot be processed as a dataclass."""\n    return 1\ndecorated = dataclass(operation)\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_direct_wraps_preserves_nested_owner_identity() -> None:
    source = 'from functools import wraps\ndef target():\n    """Outer prose stays eligible."""\n    return 1\ndef build():\n    def target():\n        """Copied nested metadata."""\n        return 2\n    @wraps(target)\n    def wrapper():\n        return target()\n    return wrapper\n'
    assert [(finding.line, finding.code) for finding in _check(source)] == [(3, "SARJ420")]


@pytest.mark.parametrize(
    ("prefix", "decorator"),
    [("import functools", "functools.cache"), ("from functools import cache as memoize", "memoize")],
)
def test_canonical_unbounded_cache_copies_docstrings(prefix: str, decorator: str) -> None:
    source = f'{prefix}\n@{decorator}\ndef result():\n    """Copied onto an unbounded cache."""\n    return 1\n'
    assert _check(source) == []


def test_unbounded_cache_functional_form_copies_only_its_input() -> None:
    source = 'from functools import cache\ndef operation():\n    """Copied input metadata."""\n    return 1\ncopied = cache(operation)\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "expression", ["functools.cache()", "functools.cache(maxsize=1)", "functools.cache(**options)"]
)
def test_unbounded_cache_invalid_decorator_forms_do_not_exempt_prose(expression: str) -> None:
    source = f'import functools\n@{expression}\ndef result():\n    """Human-only prose."""\n    return 1\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_mutated_unbounded_cache_cannot_prove_metadata_copying() -> None:
    source = 'import functools\nfunctools.cache = replacement\n@functools.cache\ndef result():\n    """Human-only prose."""\n    return 1\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    "prefix",
    [
        "from app.decorators import copy_metadata\ncopy_metadata.__code__ = replacement.__code__",
        "import app.decorators as decorators\ndecorators.copy_metadata = replacement\ncopy_metadata = decorators.copy_metadata",
    ],
)
def test_imported_factory_mutation_does_not_borrow_its_original_body(tmp_path: Path, prefix: str) -> None:
    assert [finding.code for finding in _project_metadata_findings(tmp_path, _METADATA_FACTORY, prefix)] == ["SARJ420"]


def test_factory_module_mutation_invalidates_the_original_function_body(tmp_path: Path) -> None:
    factory = _METADATA_FACTORY + "\ncopy_metadata.__code__ = replacement.__code__\n"
    assert [finding.code for finding in _project_metadata_findings(tmp_path, factory)] == ["SARJ420"]


@pytest.mark.parametrize(
    ("decorators", "expected"),
    [("@unknown\n@functools.lru_cache(maxsize=1)", []), ("@functools.lru_cache(maxsize=1)\n@unknown", ["SARJ420"])],
)
def test_unknown_function_decorator_order_cannot_borrow_the_original_doc(decorators: str, expected: list[str]) -> None:
    source = f'import functools\n{decorators}\ndef operation():\n    """Original input metadata."""\n    return 1\n'
    assert [finding.code for finding in _check(source)] == expected


@pytest.mark.parametrize(
    ("decorators", "expected"),
    [("@unknown\n@dataclasses.dataclass", ["SARJ420"]), ("@dataclasses.dataclass\n@unknown", ["SARJ420"])],
)
def test_unknown_class_decorator_order_cannot_borrow_the_original_doc(decorators: str, expected: list[str]) -> None:
    source = f'import dataclasses\n{decorators}\nclass Record:\n    """Original class metadata."""\n    value: int\n'
    assert [finding.code for finding in _check(source)] == expected


@pytest.mark.parametrize(
    "decorators", ["@functools.lru_cache(maxsize=1)\n@checked", "@checked\n@functools.lru_cache(maxsize=1)"]
)
def test_source_proven_transparent_modifier_aliases_preserve_function_metadata(decorators: str) -> None:
    source = f'from typing import override as checked\nimport functools\n{decorators}\ndef operation():\n    """Read by the cache consumer."""\n    return 1\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "prefix",
    [
        "from typing import override as checked\nchecked = replacement",
        "import typing\ntyping.override = replacement\nfrom typing import override as checked",
    ],
)
def test_mutated_or_shadowed_transparent_modifier_cannot_reach_an_outer_consumer(prefix: str) -> None:
    source = f'{prefix}\nimport functools\n@functools.lru_cache(maxsize=1)\n@checked\ndef operation():\n    """Original prose is not proven to survive."""\n    return 1\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_canonical_abstractmethod_can_reach_an_outer_classmethod_consumer() -> None:
    source = 'import abc as hooks\nclass Service:\n    @classmethod\n    @hooks.abstractmethod\n    def run(cls):\n        """Copied by the outer descriptor."""\n        return 1\n'
    assert _check(source) == []


@pytest.mark.parametrize("consumer", ["staticmethod", "functools.cache", "functools.lru_cache"])
def test_functional_consumers_do_not_read_a_doc_replaced_by_an_unknown_decorator(consumer: str) -> None:
    source = f'import functools\n@unknown\ndef operation():\n    """Original prose is not proven to survive."""\n    return 1\ncopied = {consumer}(operation)\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_functional_dataclass_does_not_read_original_unknown_replacement_prose() -> None:
    source = 'from dataclasses import dataclass\n@unknown\nclass Record:\n    """Original class prose."""\n    value: int\ncopied = dataclass(Record)\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_direct_wraps_does_not_read_original_unknown_replacement_prose() -> None:
    source = 'from functools import wraps\n@unknown\ndef operation():\n    """Original function prose."""\n    return 1\n@wraps(operation)\ndef wrapper():\n    return 1\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    ("replacement", "expected"),
    [
        pytest.param('method.__doc__ = "Replacement metadata"', ["SARJ420"], id="doc-replaced-before-copy"),
        pytest.param('setattr(method, "__doc__", "Replacement metadata")', ["SARJ420"], id="doc-replaced-by-setattr"),
        pytest.param('method.__name__ = "renamed"', [], id="name-replaced-doc-preserved"),
    ],
)
def test_factory_cannot_borrow_input_prose_overwritten_before_wraps(
    tmp_path: Path, replacement: str, expected: list[str]
) -> None:
    factory = _METADATA_FACTORY.replace(
        "    @functools.wraps(method)", f"    {replacement}\n    @functools.wraps(method)"
    )
    assert [finding.code for finding in _project_metadata_findings(tmp_path, factory)] == expected


def test_factory_doc_replacement_after_wraps_does_not_erase_the_earlier_copy(tmp_path: Path) -> None:
    factory = _METADATA_FACTORY.replace(
        "    return wrapper\n", '    method.__doc__ = "Later metadata"\n    return wrapper\n'
    )
    assert _project_metadata_findings(tmp_path, factory) == []


@pytest.mark.parametrize(
    "statement", ["mutate(method)", "state.current = method", "alias = method", "bound_setattr = method.__setattr__"]
)
def test_factory_opaque_input_escape_before_copy_is_not_proven(tmp_path: Path, statement: str) -> None:
    factory = _METADATA_FACTORY.replace(
        "    @functools.wraps(method)", f"    {statement}\n    @functools.wraps(method)"
    )
    assert [finding.code for finding in _project_metadata_findings(tmp_path, factory)] == ["SARJ420"]


def test_factory_wrapper_body_can_later_replace_an_already_copied_doc(tmp_path: Path) -> None:
    factory = _METADATA_FACTORY.replace(
        "        return method(*args, **kwargs)",
        '        method.__doc__ = "Later metadata"\n        return method(*args, **kwargs)',
    )
    assert _project_metadata_findings(tmp_path, factory) == []


@pytest.mark.parametrize("decorators", ["@dataclasses.dataclass\n@checked", "@checked\n@dataclasses.dataclass"])
def test_transparent_modifiers_do_not_exempt_dataclass_prose(decorators: str) -> None:
    source = f'from typing import override as checked\nimport dataclasses\n{decorators}\nclass Record:\n    """Read by class metadata generation."""\n    value: int\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    "prefix",
    [
        "from typing import override as checked\nchecked = replacement",
        "import typing\ntyping.override = replacement\nfrom typing import override as checked",
    ],
)
def test_unproven_modifier_does_not_pass_original_class_prose_to_dataclass(prefix: str) -> None:
    source = f'{prefix}\nimport dataclasses\n@dataclasses.dataclass\n@checked\nclass Record:\n    """Original prose is not proven to survive."""\n    value: int\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    "exposure",
    [
        pytest.param(
            'from functools import __dict__ as namespace\nnamespace["lru_cache"] = replacement',
            id="imported-module-dict",
        ),
        pytest.param(
            'from functools import __getattribute__ as attribute\nattribute("__dict__")["lru_cache"] = replacement',
            id="imported-bound-getattribute",
        ),
        pytest.param(
            'from functools import __setattr__ as set_attribute\nset_attribute("lru_cache", replacement)',
            id="imported-bound-setattr",
        ),
        pytest.param(
            'from functools import __delattr__ as del_attribute\ndel_attribute("lru_cache")',
            id="imported-bound-delattr",
        ),
        pytest.param('namespace = vars(functools)\nnamespace["lru_cache"] = replacement', id="canonical-vars"),
        pytest.param(
            'from builtins import vars as mapping_of\nnamespace = mapping_of(functools)\nnamespace["lru_cache"] = replacement',
            id="aliased-canonical-vars",
        ),
    ],
)
def test_writable_module_namespace_imports_and_vars_cannot_prove_cache_metadata(exposure: str) -> None:
    source = f'import functools\n{exposure}\n@functools.lru_cache(maxsize=1)\ndef operation():\n    """Original prose is not proven to be copied."""\n    return 1\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    ("module", "consumer", "owner"),
    [
        pytest.param(
            "dataclasses",
            "dataclass",
            'class Record:\n    """Original class prose."""\n    value: int\n',
            id="dataclass-module-dict",
        ),
        pytest.param(
            "builtins",
            "classmethod",
            'def operation():\n    """Original callable prose."""\n    return 1\n',
            id="builtin-module-dict",
        ),
    ],
)
def test_other_canonical_consumers_require_unexposed_module_dict(module: str, consumer: str, owner: str) -> None:
    source = f'from {module} import __dict__ as namespace\nimport {module}\nnamespace["{consumer}"] = replacement\n@{module}.{consumer}\n{owner}'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


def test_imported_typing_namespace_is_not_a_transparent_modifier_proof() -> None:
    source = 'from typing import __dict__ as namespace\nfrom typing import override as checked\nimport functools\nnamespace["override"] = replacement\n@functools.lru_cache(maxsize=1)\n@checked\ndef operation():\n    """Original prose is not proven to survive."""\n    return 1\n'
    assert [finding.code for finding in _check(source)] == ["SARJ420"]


@pytest.mark.parametrize(
    "prefix",
    [
        "from functools import __name__ as module_name",
        "from functools import __doc__ as module_doc",
        'import other\nnamespace = vars(other)\nnamespace["lru_cache"] = replacement',
    ],
)
def test_readonly_metadata_imports_or_unrelated_namespace_keep_cache_proof(prefix: str) -> None:
    source = f'{prefix}\nimport functools\n@functools.lru_cache(maxsize=1)\ndef operation():\n    """Copied canonical metadata."""\n    return 1\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(("def copy_metadata(method):", "async def copy_metadata(method):"), id="async-outer-not-executed"),
        pytest.param(
            ("    @functools.wraps(method)", "    yield None\n    @functools.wraps(method)"), id="yield-before-copy"
        ),
        pytest.param(("    return wrapper\n", "    yield from ()\n    return wrapper\n"), id="yield-from-after-copy"),
        pytest.param(
            ("    @functools.wraps(method)", "    if False:\n        yield None\n    @functools.wraps(method)"),
            id="unreachable-yield-still-lazy",
        ),
    ],
)
def test_lazy_outer_factory_does_not_execute_the_metadata_copy(tmp_path: Path, change: tuple[str, str]) -> None:
    factory = _METADATA_FACTORY.replace(*change)
    assert [finding.code for finding in _project_metadata_findings(tmp_path, factory)] == ["SARJ420"]


def test_generator_nested_wrapper_does_not_delay_its_wraps_decorator(tmp_path: Path) -> None:
    factory = _METADATA_FACTORY.replace(
        "        return method(*args, **kwargs)", "        yield method(*args, **kwargs)"
    )
    assert _project_metadata_findings(tmp_path, factory) == []


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(
            ("def wrapper(*args, **kwargs):", "def wrapper(value=mutate(method), *args, **kwargs):"),
            id="evaluated-default-escape",
        ),
        pytest.param(
            ("def wrapper(*args, **kwargs):", "def wrapper(*args: mutate(method), **kwargs):"),
            id="parameter-annotation-escape",
        ),
        pytest.param(
            ("def wrapper(*args, **kwargs):", "def wrapper(*args, **kwargs) -> mutate(method):"),
            id="return-annotation-escape",
        ),
        pytest.param(
            ("@functools.wraps(method)", "@functools.wraps(method, updated=mutate(method))"),
            id="decorator-option-escape",
        ),
    ],
)
def test_wrapper_header_cannot_escape_input_before_metadata_copy(tmp_path: Path, change: tuple[str, str]) -> None:
    factory = _METADATA_FACTORY.replace(*change)
    assert [finding.code for finding in _project_metadata_findings(tmp_path, factory)] == ["SARJ420"]


def test_wrapper_default_can_read_immutable_input_name_before_copy(tmp_path: Path) -> None:
    factory = _METADATA_FACTORY.replace(
        "def wrapper(*args, **kwargs):", "def wrapper(value=method.__name__, *args, **kwargs):"
    )
    assert _project_metadata_findings(tmp_path, factory) == []


@pytest.mark.parametrize(
    ("option", "expected"),
    [
        pytest.param("", [], id="default-update-fields"),
        pytest.param(", updated=()", [], id="empty-updates"),
        pytest.param(', updated=("__dict__",)', [], id="literal-update-fields"),
        pytest.param(", updated=functools.WRAPPER_UPDATES", [], id="canonical-update-fields"),
        pytest.param(", updated=fields", ["SARJ420"], id="unknown-update-fields"),
        pytest.param(", updated=mutate(target)", ["SARJ420"], id="updated-expression-can-replace-doc"),
    ],
)
def test_direct_wraps_update_options_require_known_evaluation(option: str, expected: list[str]) -> None:
    source = f'import functools\ndef target():\n    """Original input metadata."""\n    return 1\n@functools.wraps(target{option})\ndef wrapper():\n    return 1\n'
    assert [finding.code for finding in _check(source)] == expected


@pytest.mark.parametrize(
    ("reference", "header", "expected"),
    [
        pytest.param("target", "value=mutate(target)", ["SARJ420"], id="direct-default-escape"),
        pytest.param("target", "value=mutate(alias)", ["SARJ420"], id="default-through-stable-alias"),
        pytest.param("target", "target=mutate(target)", ["SARJ420"], id="default-evaluated-outside-parameter-scope"),
        pytest.param("target", "value=target.__name__", [], id="readonly-name-default"),
    ],
)
def test_direct_wraps_header_must_preserve_original_input_doc(reference: str, header: str, expected: list[str]) -> None:
    source = f'import functools\ndef target():\n    """Original input metadata."""\n    return 1\nalias = target\n@functools.wraps({reference})\ndef wrapper({header}):\n    return 1\n'
    assert [finding.code for finding in _check(source)] == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(classmethod=classmethod(original)):\n"
            "    return classmethod\n",
            [],
            id="default:classmethod:classmethod:positional",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(*, classmethod=classmethod(original)):\n"
            "    return classmethod\n",
            [],
            id="default:classmethod:classmethod:keyword",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(original=classmethod(original)):\n"
            "    return original\n",
            [],
            id="default:classmethod:original:positional",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(*, original=classmethod(original)):\n"
            "    return original\n",
            [],
            id="default:classmethod:original:keyword",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = lambda classmethod: classmethod(original)\n",
            ["SARJ420"],
            id="lambda-provider:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = lambda original: classmethod(original)\n",
            ["SARJ420"],
            id="lambda-owner:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [classmethod(original) for classmethod in candidates]\n",
            ["SARJ420"],
            id="comprehension-provider:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [classmethod(original) for original in candidates]\n",
            ["SARJ420"],
            id="comprehension-owner:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [classmethod for classmethod in [classmethod(original)]]\n",
            [],
            id="first-iter-provider:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [original for original in [classmethod(original)]]\n",
            [],
            id="first-iter-owner:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = (original for original in [classmethod(original)])\n",
            [],
            id="generator-first-iter:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(classmethod):\n"
            "    return classmethod(original)\n",
            ["SARJ420"],
            id="body-provider:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(original):\n"
            "    return classmethod(original)\n",
            ["SARJ420"],
            id="body-owner:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper[classmethod](value: classmethod(original)):\n"
            "    return value\n",
            ["SARJ420"],
            id="annotation-provider:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper[classmethod]():\n"
            "    return classmethod(original)\n",
            ["SARJ420"],
            id="type-parameter-provider:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "class Base:\n"
            "    def __init_subclass__(cls, **kwargs):\n"
            "        pass\n"
            "class Wrapper(Base, copied=classmethod(original)):\n"
            "    classmethod = None\n",
            [],
            id="class-keyword-provider:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "class Base:\n"
            "    def __init_subclass__(cls, **kwargs):\n"
            "        pass\n"
            "class Wrapper(Base, copied=classmethod(original)):\n"
            "    original = None\n",
            [],
            id="class-keyword-owner:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def select_base(metadata):\n"
            "    return object\n"
            "class Wrapper(select_base(classmethod(original))):\n"
            "    classmethod = None\n",
            [],
            id="class-base-provider:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def select_base(metadata):\n"
            "    return object\n"
            "class Wrapper(select_base(classmethod(original))):\n"
            "    original = None\n",
            [],
            id="class-base-owner:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(staticmethod=staticmethod(original)):\n"
            "    return staticmethod\n",
            [],
            id="default:staticmethod:staticmethod:positional",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(*, staticmethod=staticmethod(original)):\n"
            "    return staticmethod\n",
            [],
            id="default:staticmethod:staticmethod:keyword",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(original=staticmethod(original)):\n"
            "    return original\n",
            [],
            id="default:staticmethod:original:positional",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(*, original=staticmethod(original)):\n"
            "    return original\n",
            [],
            id="default:staticmethod:original:keyword",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = lambda staticmethod: staticmethod(original)\n",
            ["SARJ420"],
            id="lambda-provider:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = lambda original: staticmethod(original)\n",
            ["SARJ420"],
            id="lambda-owner:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [staticmethod(original) for staticmethod in candidates]\n",
            ["SARJ420"],
            id="comprehension-provider:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [staticmethod(original) for original in candidates]\n",
            ["SARJ420"],
            id="comprehension-owner:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [staticmethod for staticmethod in [staticmethod(original)]]\n",
            [],
            id="first-iter-provider:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [original for original in [staticmethod(original)]]\n",
            [],
            id="first-iter-owner:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = (original for original in [staticmethod(original)])\n",
            [],
            id="generator-first-iter:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(staticmethod):\n"
            "    return staticmethod(original)\n",
            ["SARJ420"],
            id="body-provider:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(original):\n"
            "    return staticmethod(original)\n",
            ["SARJ420"],
            id="body-owner:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper[staticmethod](value: staticmethod(original)):\n"
            "    return value\n",
            ["SARJ420"],
            id="annotation-provider:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper[staticmethod]():\n"
            "    return staticmethod(original)\n",
            ["SARJ420"],
            id="type-parameter-provider:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "class Base:\n"
            "    def __init_subclass__(cls, **kwargs):\n"
            "        pass\n"
            "class Wrapper(Base, copied=staticmethod(original)):\n"
            "    staticmethod = None\n",
            [],
            id="class-keyword-provider:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "class Base:\n"
            "    def __init_subclass__(cls, **kwargs):\n"
            "        pass\n"
            "class Wrapper(Base, copied=staticmethod(original)):\n"
            "    original = None\n",
            [],
            id="class-keyword-owner:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def select_base(metadata):\n"
            "    return object\n"
            "class Wrapper(select_base(staticmethod(original))):\n"
            "    staticmethod = None\n",
            [],
            id="class-base-provider:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def select_base(metadata):\n"
            "    return object\n"
            "class Wrapper(select_base(staticmethod(original))):\n"
            "    original = None\n",
            [],
            id="class-base-owner:staticmethod",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(ft=ft.lru_cache(original)):\n"
            "    return ft\n",
            [],
            id="imported-default-provider",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(original=ft.lru_cache(original)):\n"
            "    return original\n",
            [],
            id="imported-default-owner",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(*, ft=ft.lru_cache(original)):\n"
            "    return ft\n",
            [],
            id="imported-kw-default-provider",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = lambda ft: ft.lru_cache(original)\n",
            ["SARJ420"],
            id="imported-lambda-provider",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = lambda original: ft.lru_cache(original)\n",
            ["SARJ420"],
            id="imported-lambda-owner",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [ft.lru_cache(original) for ft in candidates]\n",
            ["SARJ420"],
            id="imported-comprehension-provider",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [ft.lru_cache(original) for original in candidates]\n",
            ["SARJ420"],
            id="imported-comprehension-owner",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [ft for ft in [ft.lru_cache(original)]]\n",
            [],
            id="imported-first-iter-provider",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = [original for original in [ft.lru_cache(original)]]\n",
            [],
            id="imported-first-iter-owner",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "class Base:\n"
            "    def __init_subclass__(cls, **kwargs):\n"
            "        pass\n"
            "class Wrapper(Base, copied=ft.lru_cache(original)):\n"
            "    ft = None\n",
            [],
            id="imported-class-keyword-provider",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def select_base(metadata):\n"
            "    return object\n"
            "class Wrapper(select_base(ft.lru_cache(original))):\n"
            "    original = None\n",
            [],
            id="imported-class-base-owner",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(value=lambda original: original):\n"
            "    return ft.lru_cache(original)\n",
            [],
            id="imported-nested-default-parameter",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def outer(ft):\n"
            "    def wrapper(value=ft.lru_cache(original)):\n"
            "        return value\n"
            "    return wrapper\n",
            ["SARJ420"],
            id="imported-outer-provider-shadow",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def outer(original):\n"
            "    def wrapper(value=ft.lru_cache(original)):\n"
            "        return value\n"
            "    return wrapper\n",
            ["SARJ420"],
            id="imported-outer-owner-shadow",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(value=lambda original: original):\n"
            "    return staticmethod(original)\n",
            [],
            id="nested-default-owner-parameter",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(value=lambda staticmethod: staticmethod):\n"
            "    return staticmethod(original)\n",
            [],
            id="nested-default-provider-parameter",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = lambda classmethod=classmethod(original): classmethod\n",
            [],
            id="lambda-default-provider",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "copied = lambda original=classmethod(original): original\n",
            [],
            id="lambda-default-owner",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper[classmethod](value=classmethod(original)):\n"
            "    return value\n",
            [],
            id="default-type-parameter-provider",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "class Wrapper[ft](ft.lru_cache(original)):\n"
            "    pass\n",
            ["SARJ420"],
            id="class-base-type-parameter-provider",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return value\n"
            "def wrapper(rebound=(classmethod := opaque), copied=classmethod(original)):\n"
            "    return copied\n",
            ["SARJ420"],
            id="default-walrus-rebound-builtin",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def wrapper(rebound=(ft := replacement), copied=ft.lru_cache(original)):\n"
            "    return copied\n",
            ["SARJ420"],
            id="default-walrus-rebound-import",
        ),
    ],
)
def test_metadata_consumers_follow_expression_lexical_frames(source: str, expected: list[str]) -> None:
    assert [finding.code for finding in _check(source)] == expected


@pytest.mark.parametrize(
    ("imports", "decorator"),
    [
        pytest.param("import functools as ft\nimport functools as ft", "ft.cache", id="same-module-alias"),
        pytest.param(
            "from functools import cache as cached\nfrom functools import cache as cached",
            "cached",
            id="same-callable-alias",
        ),
    ],
)
def test_identical_canonical_reimports_preserve_metadata_copy(imports: str, decorator: str) -> None:
    source = f'{imports}\n@{decorator}\ndef original():\n    """Copied metadata."""\n    return 1\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    classmethod = opaque\n"
            "    def method(self):\n"
            "        return classmethod(original)\n",
            [],
            id="class-method-body:classmethod:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    classmethod = opaque\n"
            "    copied = lambda: classmethod(original)\n",
            [],
            id="class-lambda-body:classmethod:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    classmethod = opaque\n"
            "    copied = [classmethod(original) for item in [0]]\n",
            [],
            id="class-comprehension-body:classmethod:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    classmethod = opaque\n"
            "    def method(self, copied=classmethod(original)):\n"
            "        return copied\n",
            ["SARJ420"],
            id="class-method-default:classmethod:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C[classmethod]:\n"
            "    def method(self):\n"
            "        return classmethod(original)\n",
            ["SARJ420"],
            id="class-type-parameter-method:classmethod:classmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    original = opaque\n"
            "    def method(self):\n"
            "        return classmethod(original)\n",
            [],
            id="class-method-body:classmethod:original",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    original = opaque\n"
            "    copied = lambda: classmethod(original)\n",
            [],
            id="class-lambda-body:classmethod:original",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    original = opaque\n"
            "    copied = [classmethod(original) for item in [0]]\n",
            [],
            id="class-comprehension-body:classmethod:original",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    original = opaque\n"
            "    def method(self, copied=classmethod(original)):\n"
            "        return copied\n",
            ["SARJ420"],
            id="class-method-default:classmethod:original",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C[original]:\n"
            "    def method(self):\n"
            "        return classmethod(original)\n",
            ["SARJ420"],
            id="class-type-parameter-method:classmethod:original",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    staticmethod = opaque\n"
            "    def method(self):\n"
            "        return staticmethod(original)\n",
            [],
            id="class-method-body:staticmethod:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    staticmethod = opaque\n"
            "    copied = lambda: staticmethod(original)\n",
            [],
            id="class-lambda-body:staticmethod:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    staticmethod = opaque\n"
            "    copied = [staticmethod(original) for item in [0]]\n",
            [],
            id="class-comprehension-body:staticmethod:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    staticmethod = opaque\n"
            "    def method(self, copied=staticmethod(original)):\n"
            "        return copied\n",
            ["SARJ420"],
            id="class-method-default:staticmethod:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C[staticmethod]:\n"
            "    def method(self):\n"
            "        return staticmethod(original)\n",
            ["SARJ420"],
            id="class-type-parameter-method:staticmethod:staticmethod",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    original = opaque\n"
            "    def method(self):\n"
            "        return staticmethod(original)\n",
            [],
            id="class-method-body:staticmethod:original",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    original = opaque\n"
            "    copied = lambda: staticmethod(original)\n",
            [],
            id="class-lambda-body:staticmethod:original",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    original = opaque\n"
            "    copied = [staticmethod(original) for item in [0]]\n",
            [],
            id="class-comprehension-body:staticmethod:original",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    original = opaque\n"
            "    def method(self, copied=staticmethod(original)):\n"
            "        return copied\n",
            ["SARJ420"],
            id="class-method-default:staticmethod:original",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C[original]:\n"
            "    def method(self):\n"
            "        return staticmethod(original)\n",
            ["SARJ420"],
            id="class-type-parameter-method:staticmethod:original",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    ft = opaque\n"
            "    def method(self):\n"
            "        return ft.lru_cache(original)\n",
            [],
            id="class-imported-method-body",
        ),
        pytest.param(
            "import functools as ft\n"
            "\n"
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class C:\n"
            "    ft = opaque\n"
            "    def method(self, copied=ft.lru_cache(original)):\n"
            "        return copied\n",
            ["SARJ420"],
            id="class-imported-method-default",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class Outer:\n"
            "    original = opaque\n"
            "    class Inner:\n"
            "        copied = staticmethod(original)\n",
            [],
            id="nested-class-body",
        ),
        pytest.param(
            "def original():\n"
            '    """Consumed metadata."""\n'
            "    return 1\n"
            "\n"
            "def opaque(value):\n"
            "    return None\n"
            "\n"
            "class Outer:\n"
            "    class Inner:\n"
            "        original = opaque\n"
            "        copied = staticmethod(original)\n",
            ["SARJ420"],
            id="nested-class-own-shadow",
        ),
    ],
)
def test_metadata_lookup_respects_class_namespace_boundaries(source: str, expected: list[str]) -> None:
    assert [finding.code for finding in _check(source)] == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            'def original():\n    """Consumed metadata."""\n    return 1\n\n'
            "def wrapper[original](copied=staticmethod(original)):\n    return copied\n",
            [],
            id="function-type-parameter-owner-default",
        ),
        pytest.param(
            'def original():\n    """Unconsumed metadata."""\n    return 1\n\n'
            "def wrapper[classmethod]():\n    return classmethod(original)\n",
            ["SARJ420"],
            id="function-type-parameter-provider-body",
        ),
        pytest.param(
            'def original():\n    """Unconsumed metadata."""\n    return 1\n\n'
            "def wrapper[original]():\n    return staticmethod(original)\n",
            ["SARJ420"],
            id="function-type-parameter-owner-body",
        ),
    ],
)
def test_metadata_lookup_respects_function_type_parameter_boundaries(source: str, expected: list[str]) -> None:
    assert [finding.code for finding in _check(source)] == expected


@pytest.mark.parametrize(
    ("copy", "expected_line"),
    [
        pytest.param(
            "    def method(self):\n        return staticmethod(original)\n",
            7,
            id="method-body-consumes-module-owner",
        ),
        pytest.param(
            "    copied = lambda: staticmethod(original)\n",
            7,
            id="lambda-body-consumes-module-owner",
        ),
        pytest.param(
            "    def method(self, copied=staticmethod(original)):\n        return copied\n",
            2,
            id="method-default-consumes-class-owner",
        ),
        pytest.param(
            "    copied = staticmethod(original)\n",
            2,
            id="class-body-consumes-class-owner",
        ),
    ],
)
def test_metadata_copy_does_not_confuse_same_named_module_and_class_owners(copy: str, expected_line: int) -> None:
    source = (
        'def original():\n    """Module metadata."""\n    return 1\n\n'
        'class C:\n    def original():\n        """Class metadata."""\n        return 2\n'
        f"{copy}"
    )
    assert [(finding.line, finding.code) for finding in _check(source)] == [(expected_line, "SARJ420")]


@pytest.mark.parametrize(
    ("source", "expected_diagnostics"),
    [
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    copied = staticmethod(original)\n    def original():\n        """Class metadata."""\n        return 2\n',
            [(8, "SARJ420")],
            id="staticmethod-class-copy-before-owner-binding",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    def original():\n        """Class metadata."""\n        return 2\n    copied = staticmethod(original)\n',
            [(2, "SARJ420")],
            id="staticmethod-class-copy-after-owner-binding",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    copied = classmethod(original)\n    def original():\n        """Class metadata."""\n        return 2\n',
            [(8, "SARJ420")],
            id="classmethod-class-copy-before-owner-binding",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    def original():\n        """Class metadata."""\n        return 2\n    copied = classmethod(original)\n',
            [(2, "SARJ420")],
            id="classmethod-class-copy-after-owner-binding",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    def method(self, copied=staticmethod(original)):\n        return copied\n    def original():\n        """Class metadata."""\n        return 2\n',
            [(9, "SARJ420")],
            id="method-default-before-class-owner-binding",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef opaque(value):\n    return None\n\nclass C:\n    copied = staticmethod(original)\n    staticmethod = opaque\n',
            [],
            id="class-provider-binding-after-copy",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef opaque(value):\n    return None\n\nclass C:\n    staticmethod = opaque\n    copied = staticmethod(original)\n',
            [(2, "SARJ420")],
            id="class-provider-binding-before-copy",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef build():\n    copied = staticmethod(original)\n    original = None\n    return copied\n',
            [(2, "SARJ420")],
            id="function-later-owner-assignment-stays-local",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef build():\n    copied = staticmethod(original)\n    staticmethod = None\n    return copied\n',
            [(2, "SARJ420")],
            id="function-later-provider-assignment-stays-local",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef build():\n    def original():\n        """Enclosing metadata."""\n        return 2\n    class C:\n        copied = staticmethod(original)\n    return C\nC = build()\n',
            [(2, "SARJ420")],
            id="class-free-name-uses-earlier-enclosing-definition",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef build():\n    def original():\n        """Enclosing metadata."""\n        return 2\n    class C:\n        copied = staticmethod(original)\n        def original():\n            """Class metadata."""\n            return 3\n    return C\nC = build()\n',
            [(7, "SARJ420"), (12, "SARJ420")],
            id="class-local-later-binding-falls-back-global-not-enclosing",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    def original():\n        """First class metadata."""\n        return 2\n    copied = staticmethod(original)\n    def original():\n        """Second class metadata."""\n        return 3\n',
            [(2, "SARJ420"), (11, "SARJ420")],
            id="class-owner-redefined-after-copy",
        ),
    ],
)
def test_metadata_class_body_lookup_uses_executed_bindings(
    source: str, expected_diagnostics: list[tuple[int, str]]
) -> None:
    findings = NoUnnecessaryDocstring().check(Path("app/service.py"), source)
    assert [(finding.line, finding.code) for finding in findings] == expected_diagnostics


@pytest.mark.parametrize(
    ("source", "expected_diagnostics"),
    [
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C[original]:\n    copied = staticmethod(original)\n    def original():\n        """Class metadata."""\n        return 2\n',
            [(8, "SARJ420")],
            id="generic-owner-future-local-module",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef build():\n    def original():\n        """Enclosing metadata."""\n        return 2\n    class C[original]:\n        copied = staticmethod(original)\n        def original():\n            """Class metadata."""\n            return 3\n    return C, original\nC, enclosing_original = build()\n',
            [(7, "SARJ420"), (12, "SARJ420")],
            id="generic-owner-future-local-enclosing",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C[original]:\n    copied = staticmethod(original)\n',
            [(2, "SARJ420")],
            id="generic-owner-without-future-local",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef opaque(value):\n    return None\n\nclass C[staticmethod]:\n    copied = staticmethod(original)\n    staticmethod = opaque\n',
            [],
            id="generic-provider-future-local",
        ),
        pytest.param(
            'class Outer:\n    class C:\n        def original():\n            """Discarded metadata."""\n            return 1\n    class C:\n        original = lambda: 2\n    copied = staticmethod(C.original)\n',
            [(4, "SARJ420")],
            id="latest-nested-class-lambda",
        ),
        pytest.param(
            'class Outer:\n    class C:\n        def original():\n            """Discarded metadata."""\n            return 1\n    class C:\n        def original():\n            """Copied metadata."""\n            return 2\n    copied = staticmethod(C.original)\n',
            [(4, "SARJ420")],
            id="latest-nested-class-function",
        ),
        pytest.param(
            'class Outer:\n    class C:\n        class D:\n            def original():\n                """Discarded metadata."""\n                return 1\n    class C:\n        class D:\n            original = lambda: 2\n    copied = staticmethod(C.D.original)\n',
            [(5, "SARJ420")],
            id="chained-tail-latest-lambda",
        ),
        pytest.param(
            'class Outer:\n    class C:\n        class D:\n            def original():\n                """Discarded metadata."""\n                return 1\n    class C:\n        class D:\n            def original():\n                """Copied metadata."""\n                return 2\n    copied = staticmethod(C.D.original)\n',
            [(5, "SARJ420")],
            id="chained-tail-latest-function",
        ),
        pytest.param(
            'class Outer:\n    class C:\n        def original():\n            """Discarded metadata."""\n            return 1\n    class C:\n        original = lambda: 2\nalias = Outer.C.original\ncopied = staticmethod(alias)\n',
            [(4, "SARJ420")],
            id="module-alias-latest-lambda",
        ),
        pytest.param(
            'class Outer:\n    class C:\n        def original():\n            """Discarded metadata."""\n            return 1\n    class C:\n        def original():\n            """Copied metadata."""\n            return 2\nalias = Outer.C.original\ncopied = staticmethod(alias)\n',
            [(4, "SARJ420")],
            id="module-alias-latest-function",
        ),
        pytest.param(
            'def replace(cls):\n    class Replacement:\n        original = lambda: 2\n    return Replacement\n\nclass Outer:\n    @replace\n    class C:\n        def original():\n            """Discarded metadata."""\n            return 1\n    copied = staticmethod(C.original)\n',
            [(10, "SARJ420")],
            id="opaque-class-decorator-tail",
        ),
        pytest.param(
            'class Outer:\n    class C:\n        def original():\n            """Discarded metadata."""\n            return 1\n        if True:\n            original = lambda: 2\n    copied = staticmethod(C.original)\n',
            [(4, "SARJ420")],
            id="conditional-member-replacement",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Discarded metadata."""\n        return 1\n    def original():\n        """Copied metadata."""\n        return 2\ncopied = staticmethod(C.original)\n',
            [(3, "SARJ420")],
            id="repeated-member-latest-function",
        ),
    ],
)
def test_metadata_generic_class_and_dotted_tail_owner_identity(
    source: str, expected_diagnostics: list[tuple[int, str]]
) -> None:
    findings = NoUnnecessaryDocstring().check(Path("app/service.py"), source)
    assert [(finding.line, finding.code) for finding in findings] == expected_diagnostics


@pytest.mark.parametrize(
    ("source", "expected_diagnostics"),
    [
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C[original]:\n    def original():\n        """Class metadata."""\n        return 2\n    def run(self):\n        return staticmethod(original)\n',
            [(2, "SARJ420"), (7, "SARJ420")],
            id="method-body-typevar-prior-class-binding",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C[original]:\n    def original():\n        """Class metadata."""\n        return 2\n    make = lambda: staticmethod(original)\n',
            [(2, "SARJ420"), (7, "SARJ420")],
            id="lambda-body-typevar-prior-class-binding",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C[original]:\n    def original():\n        """Class metadata."""\n        return 2\n    def run(self, copied=staticmethod(original)):\n        return copied\n',
            [(2, "SARJ420")],
            id="method-default-prior-class-binding",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C[original]:\n    def run(self):\n        return staticmethod(original)\n',
            [(2, "SARJ420")],
            id="method-body-typevar-no-class-binding",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef wrapper(value: staticmethod(original)):\n    def original():\n        """Inner metadata."""\n        return 2\n    return value\n',
            [(7, "SARJ420")],
            id="plain-function-annotation-versus-inner-body-declaration",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef wrapper[original](value: staticmethod(original)):\n    def original():\n        """Inner metadata."""\n        return 2\n    return value\n',
            [(2, "SARJ420"), (7, "SARJ420")],
            id="generic-function-annotation-versus-inner-body-declaration",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    def method(value: staticmethod(original)):\n        return value\n    def original():\n        """Class metadata."""\n        return 2\n',
            [(2, "SARJ420")],
            id="method-deferred-annotation-before-class-owner-declaration",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef wrapper[T: staticmethod(original)]():\n    def original():\n        """Inner metadata."""\n        return 2\n    return 1\n',
            [(7, "SARJ420")],
            id="generic-function-bound-versus-inner-body-declaration",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Original metadata."""\n        return 1\nC.original = lambda: 2\ncopied = staticmethod(C.original)\n',
            [(3, "SARJ420")],
            id="direct-after-attribute-mutation",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Original metadata."""\n        return 1\nC.original = lambda: 2\nalias = C.original\ncopied = staticmethod(alias)\n',
            [(3, "SARJ420")],
            id="alias-after-attribute-mutation",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Original metadata."""\n        return 1\nalias = C.original\nC.original = lambda: 2\ncopied = staticmethod(alias)\n',
            [],
            id="alias-before-attribute-mutation",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Original metadata."""\n        return 1\nalias = C.original\nC.original = lambda: 2\nsecond = alias\ncopied = staticmethod(second)\n',
            [],
            id="alias-chain-before-attribute-mutation",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Original metadata."""\n        return 1\nC.original = lambda: 2\nalias = C.original\nsecond = alias\ncopied = staticmethod(second)\n',
            [(3, "SARJ420")],
            id="alias-chain-after-attribute-mutation",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Original metadata."""\n        return 1\nalias = C.original\ndef mutate():\n    C.original = lambda: 2\ncopied = staticmethod(alias)\n',
            [(3, "SARJ420")],
            id="captured-alias-with-nested-attribute-mutation",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Original metadata."""\n        return 1\nalias = C.original\nif changed:\n    C.original = lambda: 2\ncopied = staticmethod(alias)\n',
            [(3, "SARJ420")],
            id="captured-alias-with-conditional-attribute-mutation",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Original metadata."""\n        return 1\nalias = C.original\nalias = lambda: 2\ncopied = staticmethod(alias)\n',
            [(3, "SARJ420")],
            id="captured-alias-reassigned",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Original metadata."""\n        return 1\nalias = C\nC.original = lambda: 2\ncopied = staticmethod(alias.original)\n',
            [(3, "SARJ420")],
            id="class-alias-does-not-freeze-member",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Original metadata."""\n        return 1\nalias = C.original\nsecond = alias\ncopied = staticmethod(second)\n',
            [],
            id="unmutated-module-alias-chain",
        ),
    ],
)
def test_metadata_frame_authority_and_alias_capture(source: str, expected_diagnostics: list[tuple[int, str]]) -> None:
    findings = NoUnnecessaryDocstring().check(Path("app/service.py"), source)
    assert [(finding.line, finding.code) for finding in findings] == expected_diagnostics


@pytest.mark.parametrize(
    ("source", "expected_diagnostics"),
    [
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C[original: staticmethod(original)]:\n    def original():\n        """Class metadata."""\n        return 2\n',
            [(2, "SARJ420"), (7, "SARJ420")],
            id="class-own-typeparameter-bound-versus-body-declaration",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass Outer:\n    class Inner[T: staticmethod(original)]:\n        pass\n    def original():\n        """Outer metadata."""\n        return 2\n',
            [(2, "SARJ420")],
            id="nested-class-bound-before-later-outer-owner",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    type Alias = staticmethod(original)\n    def original():\n        """Class metadata."""\n        return 2\n',
            [(2, "SARJ420")],
            id="class-typealias-value-before-later-owner",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    type Alias[original] = staticmethod(original)\n    def original():\n        """Class metadata."""\n        return 2\n',
            [(2, "SARJ420")],
            id="generic-class-typealias-parameter-versus-class-owner",
        ),
        pytest.param(
            'def original():\n    """Original metadata."""\n    return 1\nfirst = second = original\ncopied = staticmethod(first)\n',
            [],
            id="multi-name-direct-function-owner",
        ),
        pytest.param(
            'class C:\n    def original():\n        """Original metadata."""\n        return 1\nfirst = second = C.original\nC.original = lambda: 2\ncopied = staticmethod(second)\n',
            [],
            id="multi-name-member-capture-before-later-mutation",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    field: staticmethod(original)\n    def original():\n        """Class metadata."""\n        return 2\n',
            [(2, "SARJ420")],
            id="class-variable-annotation-before-later-class-owner",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef run():\n    field: staticmethod(original)\n    return "body-ran"\n',
            [(2, "SARJ420")],
            id="function-local-variable-annotation-not-evaluated",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    def method[original](value: staticmethod(original)):\n        return value\n    def original():\n        """Class metadata."""\n        return 2\n',
            [(2, "SARJ420")],
            id="generic-method-annotation-with-later-class-owner",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    def method[original](value: staticmethod(original)):\n        return value\n',
            [(2, "SARJ420")],
            id="generic-method-annotation-without-class-owner",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\ndef run():\n    field: object = staticmethod(original)\n    return field\n',
            [],
            id="function-local-annotated-assignment-value-executes",
        ),
        pytest.param(
            'def original():\n    """Module metadata."""\n    return 1\n\nclass C:\n    def original():\n        """Class metadata."""\n        return 2\n    def outer(self):\n        def nested(value: staticmethod(original)):\n            return value\n        return nested\n',
            [(7, "SARJ420")],
            id="nested-function-annotation-does-not-see-ordinary-class-owner",
        ),
    ],
)
def test_metadata_intrinsic_annotation_frames_and_alias_assignments(
    source: str, expected_diagnostics: list[tuple[int, str]]
) -> None:
    findings = NoUnnecessaryDocstring().check(Path("app/service.py"), source)
    assert [(finding.line, finding.code) for finding in findings] == expected_diagnostics
