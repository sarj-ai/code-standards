from pathlib import Path
from textwrap import indent

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.no_async_client_in_constructor import NoAsyncClientInConstructor
from sarj_python_lint.rules.no_unscoped_async_client_factory import NoUnscopedAsyncClientFactory


_WRAPPERS = (
    "class Dao:\n    def __init__(self, client):\n        self.client = client\n"
    "class Service:\n    def __init__(self, dao):\n        self.dao = dao\n"
)


def _factory(body: str, imports: str = "import httpx", *, signature: str = "def build(token):") -> str:
    return f"{imports}\n{_WRAPPERS}{signature}\n{indent(body, '    ')}\n"


FACTORY_CASES = (
    EvaluationCase(
        "two-constructors",
        Language.PYTHON,
        _factory("return Service(dao=Dao(httpx.AsyncClient()))"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "assigned-through-two-constructors",
        Language.PYTHON,
        _factory("client = httpx.AsyncClient(headers=token)\ndao = Dao(client)\nreturn Service(dao)"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _factory("return Dao(hx.AsyncClient())", "import httpx as hx"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "symbol-alias",
        Language.PYTHON,
        _factory("return Dao(Http())", "from httpx import AsyncClient as Http"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("sync-client", Language.PYTHON, _factory("return Dao(httpx.Client())"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "one-hop-client-factory",
        Language.PYTHON,
        _factory("return Dao(make_client())", "import httpx\ndef make_client():\n    return httpx.AsyncClient()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "async-factory",
        Language.PYTHON,
        _factory("return Dao(httpx.AsyncClient())", signature="async def build():"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "conditional-creation",
        Language.PYTHON,
        _factory("client = None\nif token:\n    client = httpx.AsyncClient()\nreturn Dao(client)"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "early-return-before-allocation",
        Language.PYTHON,
        _factory("if not token:\n    return None\nclient = httpx.AsyncClient()\nreturn Dao(client)"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "local-method-use",
        Language.PYTHON,
        _factory(
            "client = httpx.AsyncClient()\nclient.headers.update(token)\nif client is None:\n    raise ValueError\nreturn Dao(client)"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-closure-parameter",
        Language.PYTHON,
        _factory("client = httpx.AsyncClient()\ndef hook(client):\n    return client\nreturn Dao(client)"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "staticmethod-factory",
        Language.PYTHON,
        "import httpx\nclass Dao:\n    def __init__(self, client):\n        self.client = client\n"
        "    @staticmethod\n    def create():\n        return Dao(httpx.AsyncClient())\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "classmethod-factory-by-name",
        Language.PYTHON,
        "import httpx\nclass Dao:\n    def __init__(self, client):\n        self.client = client\n"
        "    @classmethod\n    def create(cls):\n        return Dao(httpx.AsyncClient())\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "dataclass-and-named-tuple-wrappers",
        Language.PYTHON,
        "import httpx\nfrom dataclasses import dataclass\nfrom typing import NamedTuple\n"
        "@dataclass(frozen=True)\nclass Dao:\n    client: httpx.AsyncClient\n"
        "class Bundle(NamedTuple):\n    dao: Dao\n"
        "def build():\n    return Bundle(dao=Dao(client=httpx.AsyncClient()))\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "returned-public-field-is-a-known-limitation",
        Language.PYTHON,
        "import httpx\nfrom dataclasses import dataclass\n@dataclass\nclass Runtime:\n    client: httpx.AsyncClient | None\n"
        "def build(enabled):\n    client = None\n    if enabled:\n        client = httpx.AsyncClient()\n    return Runtime(client=client)\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "async-with",
        Language.PYTHON,
        _factory("async with httpx.AsyncClient() as client:\n    return Dao(client)", signature="async def build():"),
    ),
    EvaluationCase(
        "named-async-with",
        Language.PYTHON,
        _factory(
            "client = httpx.AsyncClient()\nasync with client:\n    return Dao(client)", signature="async def build():"
        ),
    ),
    EvaluationCase("sync-with", Language.PYTHON, _factory("with httpx.Client() as client:\n    return Dao(client)")),
    EvaluationCase(
        "exit-stack-context",
        Language.PYTHON,
        _factory(
            "client = await stack.enter_async_context(httpx.AsyncClient())\nreturn Dao(client)",
            signature="async def build(stack):",
        ),
    ),
    EvaluationCase(
        "exit-stack-callback",
        Language.PYTHON,
        _factory(
            "client = httpx.AsyncClient()\nstack.push_async_callback(client.aclose)\nreturn Dao(client)",
            signature="def build(stack):",
        ),
    ),
    EvaluationCase(
        "close-on-failure",
        Language.PYTHON,
        _factory(
            "client = httpx.AsyncClient()\ntry:\n    return Dao(client)\nexcept Exception:\n    await client.aclose()\n    raise",
            signature="async def build():",
        ),
    ),
    EvaluationCase(
        "wrapper-closed-locally",
        Language.PYTHON,
        _factory(
            "service = Service(Dao(httpx.AsyncClient()))\nawait service.dao.client.aclose()\nreturn service",
            signature="async def build():",
        ),
    ),
    EvaluationCase(
        "wrapper-owns-closure",
        Language.PYTHON,
        "import httpx\nclass Dao:\n    def __init__(self, client):\n        self.client = client\n"
        "    async def aclose(self):\n        await self.client.aclose()\n"
        "def build():\n    return Dao(httpx.AsyncClient())\n",
    ),
    EvaluationCase(
        "base-owns-closure",
        Language.PYTHON,
        "import httpx\nclass Closing:\n    def close(self):\n        pass\nclass Dao(Closing):\n    def __init__(self, client):\n        self.client = client\n"
        "def build():\n    return Dao(httpx.Client())\n",
    ),
    EvaluationCase(
        "context-manager-wrapper",
        Language.PYTHON,
        "import httpx\nclass Dao:\n    def __init__(self, client):\n        self.client = client\n"
        "    async def __aexit__(self, *exc):\n        await self.client.aclose()\n"
        "def build():\n    return Dao(httpx.AsyncClient())\n",
    ),
    EvaluationCase(
        "forwarding-wrapper",
        Language.PYTHON,
        "import httpx\nclass Dao:\n    def __init__(self, client):\n        self.client = client\n"
        "    def __getattr__(self, name):\n        return getattr(self.client, name)\n"
        "def build():\n    return Dao(httpx.AsyncClient())\n",
    ),
    EvaluationCase(
        "unresolved-wrapper",
        Language.PYTHON,
        _factory("return Vendor(httpx.AsyncClient())", "import httpx\nfrom vendor import Vendor"),
    ),
    EvaluationCase(
        "unresolved-wrapper-base",
        Language.PYTHON,
        "import httpx\nfrom vendor import Base\nclass Dao(Base):\n    def __init__(self, client):\n        self.client = client\n"
        "def build():\n    return Dao(httpx.AsyncClient())\n",
    ),
    EvaluationCase(
        "metaclass-wrapper",
        Language.PYTHON,
        "import httpx\nclass Dao(metaclass=Meta):\n    def __init__(self, client):\n        self.client = client\n"
        "def build():\n    return Dao(httpx.AsyncClient())\n",
    ),
    EvaluationCase(
        "patched-wrapper",
        Language.PYTHON,
        _factory("return Dao(httpx.AsyncClient())") + "Dao.aclose = close\n",
    ),
    EvaluationCase("bare-return", Language.PYTHON, _factory("return httpx.AsyncClient(base_url=token)")),
    EvaluationCase(
        "annotated-bare-return",
        Language.PYTHON,
        _factory("client = httpx.AsyncClient()\nreturn client", signature="def build() -> httpx.AsyncClient:"),
    ),
    EvaluationCase(
        "bare-return-on-another-path",
        Language.PYTHON,
        _factory("client = httpx.AsyncClient()\nif token:\n    return client\nreturn Dao(client)"),
    ),
    EvaluationCase(
        "lifespan-composition-root",
        Language.PYTHON,
        _factory(
            "client = httpx.AsyncClient()\nservice = Service(Dao(client))\nreturn App(lifespan=partial(lifespan, client), service=service)",
            "import httpx\nfrom functools import partial\nfrom fastapi import FastAPI as App",
        ),
    ),
    EvaluationCase(
        "closure-lifespan",
        Language.PYTHON,
        _factory(
            "client = httpx.AsyncClient()\nasync def lifespan(app):\n    yield\n    await client.aclose()\nreturn Service(Dao(client))"
        ),
    ),
    EvaluationCase(
        "asynccontextmanager",
        Language.PYTHON,
        _factory(
            "async with httpx.AsyncClient() as client:\n    yield Dao(client)",
            "import httpx\nfrom contextlib import asynccontextmanager",
            signature="@asynccontextmanager\nasync def build():",
        ),
    ),
    EvaluationCase("generator", Language.PYTHON, _factory("client = httpx.AsyncClient()\nyield Dao(client)")),
    EvaluationCase(
        "cached-singleton",
        Language.PYTHON,
        _factory(
            "return Dao(httpx.AsyncClient())",
            "import httpx\nimport functools",
            signature="@functools.cache\ndef build():",
        ),
    ),
    EvaluationCase(
        "passed-to-unknown-function",
        Language.PYTHON,
        _factory("client = httpx.AsyncClient()\nregister(client)\nreturn Dao(client)"),
    ),
    EvaluationCase(
        "wrapper-passed-to-unknown-function",
        Language.PYTHON,
        _factory("dao = Dao(httpx.AsyncClient())\nregistry.add(dao)\nreturn Service(dao)"),
    ),
    EvaluationCase(
        "stored-on-receiver",
        Language.PYTHON,
        _factory("self.client = httpx.AsyncClient()\nreturn Dao(self.client)", signature="def build(self):"),
    ),
    EvaluationCase(
        "rebound-to-other-value",
        Language.PYTHON,
        _factory("client = httpx.AsyncClient()\nclient = shared\nreturn Dao(client)"),
    ),
    EvaluationCase("starred-wrapper-argument", Language.PYTHON, _factory("return Dao(*[httpx.AsyncClient()])")),
    EvaluationCase(
        "local-only-use", Language.PYTHON, _factory("client = httpx.AsyncClient()\nDao(client)\nreturn token")
    ),
    EvaluationCase(
        "vendor-client", Language.PYTHON, _factory("return Dao(AsyncClient())", "from vendor import AsyncClient")
    ),
    EvaluationCase(
        "suppressed",
        Language.PYTHON,
        _factory("return Dao(httpx.AsyncClient())  # sarj-noqa: SARJ577 -- process-lifetime client"),
    ),
)


@pytest.mark.parametrize("case", FACTORY_CASES, ids=tuple(case.case_id for case in FACTORY_CASES))
def test_factory_cases(case: EvaluationCase) -> None:
    findings = NoUnscopedAsyncClientFactory().check(Path("app/service.py"), case.source)
    assert [finding.severity for finding in findings] == (
        [Severity.WARNING] if case.expected is ExpectedOutcome.MATCH else []
    )


def test_factory_reports_each_wrapped_client() -> None:
    source = _factory("first = httpx.AsyncClient()\nsecond = httpx.Client()\nreturn Service(Dao(first), Dao(second))")
    findings = NoUnscopedAsyncClientFactory().check(Path("app/service.py"), source)
    assert [(finding.line, finding.col) for finding in findings] == [(9, 13), (10, 14)]


def test_factory_findings_skip_test_helpers() -> None:
    source = _factory("return Dao(httpx.AsyncClient(transport=httpx.MockTransport(handler)))")
    assert NoUnscopedAsyncClientFactory().check(Path("tests/test_service.py"), source) == []


def _write_project(root: Path, files: dict[str, str]) -> list[Path]:
    (root / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    paths: list[Path] = []
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        paths.append(path)
    return paths


@pytest.mark.parametrize(
    ("dao_source", "expected"),
    [
        pytest.param(
            "import abc\nclass Base(abc.ABC):\n    pass\nclass Dao(Base):\n    def __init__(self, client):\n        self.client = client\n",
            [("app/factory.py", 4)],
            id="inert-imported-wrapper",
        ),
        pytest.param(
            "class Dao:\n    def __init__(self, client):\n        self.client = client\n    async def aclose(self):\n        await self.client.aclose()\n",
            [],
            id="imported-wrapper-owns-closure",
        ),
        pytest.param(
            "from app.base import Closing\nclass Dao(Closing):\n    def __init__(self, client):\n        self.client = client\n",
            [],
            id="imported-base-owns-closure",
        ),
    ],
)
def test_wrappers_resolve_across_modules(tmp_path: Path, dao_source: str, expected: list[tuple[str, int]]) -> None:
    paths = _write_project(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/base.py": "class Closing:\n    def close(self):\n        pass\n",
            "app/dao.py": dao_source,
            "app/models/__init__.py": "from app.dao import Dao\n",
            "app/factory.py": "import httpx\nfrom app.models import Dao\ndef build():\n    return Dao(httpx.AsyncClient())\n",
        },
    )
    findings = analyze([NoUnscopedAsyncClientFactory.id], paths)
    assert [(finding.path.relative_to(tmp_path).as_posix(), finding.line) for finding in findings] == expected


def test_constructor_allocations_stay_with_sarj549(tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    path.write_text(
        "import httpx\nclass Service:\n    def __init__(self):\n        self.client = httpx.AsyncClient()\n"
        "def build():\n    return Service(httpx.AsyncClient())\n"
    )
    findings = analyze([NoAsyncClientInConstructor.id, NoUnscopedAsyncClientFactory.id], [path])
    assert [(finding.code, finding.line) for finding in findings] == [("SARJ549", 4), ("SARJ577", 6)]


def test_warning_policy_has_no_unsafe_autofix() -> None:
    documentation = NoUnscopedAsyncClientFactory.documentation
    assert documentation is not None
    assert documentation.default_level is Severity.WARNING
    assert documentation.autofix is AutofixPolicy.NONE


def test_documented_examples() -> None:
    verify_native_rule(NoUnscopedAsyncClientFactory, analyze)
