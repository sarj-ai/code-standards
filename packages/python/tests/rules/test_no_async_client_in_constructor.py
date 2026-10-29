from pathlib import Path
from textwrap import indent

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.no_async_client_in_constructor import NoAsyncClientInConstructor


def _service(body: str, imports: str = "import httpx") -> str:
    return f"{imports}\nclass Service:\n    def __init__(self):\n{indent(body, '        ')}\n"


CASES = (
    EvaluationCase("direct", Language.PYTHON, _service("self.client = httpx.AsyncClient()"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _service("self.client = hx.AsyncClient()", "import httpx as hx"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "symbol-alias",
        Language.PYTHON,
        _service("self.client = Client()", "from httpx import AsyncClient as Client"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "private-module",
        Language.PYTHON,
        _service("self.client = Client()", "from httpx._client import AsyncClient as Client"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "qualified-import",
        Language.PYTHON,
        _service("self.client = clients.AsyncClient()", "from httpx import _client as clients"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "assignment-alias",
        Language.PYTHON,
        _service("self.client = Client()", "from httpx import AsyncClient\nClient = AsyncClient"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "local-annotated-alias",
        Language.PYTHON,
        _service("Client: object = httpx.AsyncClient\nself.client = Client()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "local-import",
        Language.PYTHON,
        _service("from httpx import AsyncClient as Client\nself.client = Client()", ""),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "conditional-construction",
        Language.PYTHON,
        _service("if active:\n    self.client = httpx.AsyncClient()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "context-manager-body",
        Language.PYTHON,
        _service("with scope():\n    self.client = httpx.AsyncClient()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "list-comprehension",
        Language.PYTHON,
        _service("self.clients = [httpx.AsyncClient() for item in items]"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "set-comprehension",
        Language.PYTHON,
        _service("self.clients = {httpx.AsyncClient() for item in items}"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "dict-comprehension",
        Language.PYTHON,
        _service("self.clients = {item: httpx.AsyncClient() for item in items}"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "first-generator-iterable",
        Language.PYTHON,
        _service("self.items = (item for item in values(httpx.AsyncClient()))"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "eager-nested-default",
        Language.PYTHON,
        _service("def helper(client=httpx.AsyncClient()):\n    return client"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "eager-nested-decorator",
        Language.PYTHON,
        _service("@decorate(httpx.AsyncClient())\ndef helper():\n    pass"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "immediate-lambda",
        Language.PYTHON,
        _service("self.client = (lambda: httpx.AsyncClient())()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "called-lambda-alias",
        Language.PYTHON,
        _service("factory = lambda: httpx.AsyncClient()\nself.client = factory()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-factory",
        Language.PYTHON,
        _service(
            "self.client = make_client(endpoint)",
            "import httpx\ndef make_client(endpoint):\n    return httpx.AsyncClient(base_url=endpoint)",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "factory-alias",
        Language.PYTHON,
        _service(
            "self.client = factory()",
            "from httpx import AsyncClient\ndef make_client():\n    return AsyncClient()\nfactory = make_client",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "called-local-factory",
        Language.PYTHON,
        _service("def make_client():\n    return httpx.AsyncClient()\nself.client = make_client()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "local-factory-captured-parameter",
        Language.PYTHON,
        "import httpx\nclass Service:\n    def __init__(self, httpx):\n        def make_client():\n            return httpx.AsyncClient()\n        self.client = make_client()\n",
    ),
    EvaluationCase(
        "local-factory-rebound",
        Language.PYTHON,
        _service(
            "def make_client():\n    return httpx.AsyncClient()\nmake_client = other\nself.client = make_client()"
        ),
    ),
    EvaluationCase(
        "local-factory-parameter-shadow",
        Language.PYTHON,
        _service("def make_client(httpx):\n    return httpx.AsyncClient()\nself.client = make_client(other)"),
    ),
    EvaluationCase(
        "conditional-local-factory",
        Language.PYTHON,
        _service("if False:\n    def make_client():\n        return httpx.AsyncClient()\nself.client = make_client()"),
    ),
    EvaluationCase(
        "local-factory-before-definition",
        Language.PYTHON,
        _service("self.client = make_client()\ndef make_client():\n    return httpx.AsyncClient()"),
    ),
    EvaluationCase(
        "module-alias-mutation",
        Language.PYTHON,
        _service("self.client = httpx.AsyncClient()", "import httpx\nalias = httpx\nalias.AsyncClient = other"),
    ),
    EvaluationCase(
        "module-alias-conservative-abstention",
        Language.PYTHON,
        _service("self.client = httpx.AsyncClient()", "import httpx\nalias = httpx"),
    ),
    EvaluationCase(
        "module-argument-escape",
        Language.PYTHON,
        _service("self.client = httpx.AsyncClient()", "import httpx\nconfigure(httpx)"),
    ),
    EvaluationCase(
        "constructor-alias-mutation",
        Language.PYTHON,
        _service(
            "self.client = httpx.AsyncClient()", "import httpx\nClient = httpx.AsyncClient\nClient.__new__ = other"
        ),
    ),
    EvaluationCase(
        "constructor-alias-argument-escape",
        Language.PYTHON,
        _service("self.client = Client()", "from httpx import AsyncClient as Client\nconfigure(Client)"),
    ),
    EvaluationCase(
        "constructor-alias-return-escape",
        Language.PYTHON,
        _service("self.client = Client()", "from httpx import AsyncClient as Client\ndef expose():\n    return Client"),
    ),
    EvaluationCase(
        "constructor-alias-stable-chain",
        Language.PYTHON,
        _service(
            "self.client = FinalClient()", "from httpx import AsyncClient\nClient = AsyncClient\nFinalClient = Client"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "shadowed-module-escape-is-unrelated",
        Language.PYTHON,
        _service("self.client = httpx.AsyncClient()", "import httpx\ndef configure(httpx):\n    return httpx"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-local-shadow",
        Language.PYTHON,
        _service("self.client = httpx.AsyncClient()", "import httpx\ndef unrelated(httpx):\n    return httpx"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-namespace-is-not-method-scope",
        Language.PYTHON,
        "import httpx\nclass Service:\n    httpx = unrelated\n    def __init__(self):\n        self.client = httpx.AsyncClient()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "wrong-suppression",
        Language.PYTHON,
        _service("self.client = httpx.AsyncClient()  # sarj-noqa: SARJ463 -- different rule"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "injected",
        Language.PYTHON,
        "import httpx\nclass Service:\n    def __init__(self, client: httpx.AsyncClient):\n        self.client = client\n",
    ),
    EvaluationCase(
        "composition-owner",
        Language.PYTHON,
        "import httpx\nfrom contextlib import asynccontextmanager\n@asynccontextmanager\nasync def service_scope(endpoint):\n    async with httpx.AsyncClient(base_url=endpoint) as client:\n        yield Service(client)\n",
    ),
    EvaluationCase(
        "unrelated-class", Language.PYTHON, _service("self.client = AsyncClient()", "class AsyncClient:\n    pass")
    ),
    EvaluationCase(
        "other-library", Language.PYTHON, _service("self.client = AsyncClient()", "from vendor import AsyncClient")
    ),
    EvaluationCase("sync-client", Language.PYTHON, _service("self.client = httpx.Client()")),
    EvaluationCase(
        "parameter-shadow",
        Language.PYTHON,
        "import httpx\nclass Service:\n    def __init__(self, httpx):\n        self.client = httpx.AsyncClient()\n",
    ),
    EvaluationCase(
        "symbol-shadow",
        Language.PYTHON,
        "from httpx import AsyncClient\nclass Service:\n    def __init__(self, AsyncClient):\n        self.client = AsyncClient()\n",
    ),
    EvaluationCase(
        "alias-rebound", Language.PYTHON, _service("Client = httpx.AsyncClient\nClient = other\nself.client = Client()")
    ),
    EvaluationCase("alias-cycle", Language.PYTHON, _service("Client = Other\nOther = Client\nself.client = Client()")),
    EvaluationCase(
        "namespace-mutated",
        Language.PYTHON,
        _service("self.client = httpx.AsyncClient()", "import httpx\nhttpx.AsyncClient = other"),
    ),
    EvaluationCase(
        "wildcard", Language.PYTHON, _service("self.client = httpx.AsyncClient()", "import httpx\nfrom custom import *")
    ),
    EvaluationCase(
        "module-init-function", Language.PYTHON, "import httpx\ndef __init__():\n    return httpx.AsyncClient()\n"
    ),
    EvaluationCase(
        "constructor-parameter-default",
        Language.PYTHON,
        "import httpx\nclass Service:\n    def __init__(self, client=httpx.AsyncClient()):\n        self.client = client\n",
    ),
    EvaluationCase(
        "nested-deferred-function",
        Language.PYTHON,
        _service("def later():\n    return httpx.AsyncClient()\nself.factory = later"),
    ),
    EvaluationCase("nested-deferred-lambda", Language.PYTHON, _service("self.factory = lambda: httpx.AsyncClient()")),
    EvaluationCase(
        "deferred-generator", Language.PYTHON, _service("self.clients = (httpx.AsyncClient() for item in items)")
    ),
    EvaluationCase(
        "comprehension-shadow", Language.PYTHON, _service("self.clients = [httpx.AsyncClient() for httpx in vendors]")
    ),
    EvaluationCase(
        "factory-parameter-shadow",
        Language.PYTHON,
        _service(
            "self.client = make_client(other)", "import httpx\ndef make_client(httpx):\n    return httpx.AsyncClient()"
        ),
    ),
    EvaluationCase(
        "factory-return-existing",
        Language.PYTHON,
        _service(
            "self.client = make_client()",
            "import httpx\nclient = httpx.AsyncClient()\ndef make_client():\n    return client",
        ),
    ),
    EvaluationCase(
        "factory-rebound",
        Language.PYTHON,
        _service(
            "self.client = make_client()",
            "import httpx\ndef make_client():\n    return httpx.AsyncClient()\nmake_client = other",
        ),
    ),
    EvaluationCase(
        "decorated-factory",
        Language.PYTHON,
        _service(
            "self.client = make_client()", "import httpx\n@adapt\ndef make_client():\n    return httpx.AsyncClient()"
        ),
    ),
    EvaluationCase(
        "async-factory",
        Language.PYTHON,
        _service(
            "self.client = make_client()", "import httpx\nasync def make_client():\n    return httpx.AsyncClient()"
        ),
    ),
    EvaluationCase(
        "generator-factory",
        Language.PYTHON,
        _service("self.client = make_client()", "import httpx\ndef make_client():\n    yield httpx.AsyncClient()"),
    ),
    EvaluationCase(
        "opaque-factory",
        Language.PYTHON,
        _service("self.client = make_client()", "from dependencies import make_client"),
    ),
    EvaluationCase(
        "overridable-method-factory",
        Language.PYTHON,
        "import httpx\nclass Service:\n    def __init__(self):\n        self.client = self.make_client()\n    def make_client(self):\n        return httpx.AsyncClient()\n",
    ),
    EvaluationCase(
        "suppressed",
        Language.PYTHON,
        _service("self.client = httpx.AsyncClient()  # sarj-noqa: SARJ549 -- independently owned adapter lifecycle"),
    ),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _service("self.client = httpx.AsyncClient()")),
    EvaluationCase(
        "lambda-parameter-shadow", Language.PYTHON, _service("self.client = (lambda httpx: httpx.AsyncClient())(other)")
    ),
    EvaluationCase(
        "lambda-captured-parameter",
        Language.PYTHON,
        "import httpx\nclass Service:\n    def __init__(self, httpx):\n        self.client = (lambda: httpx.AsyncClient())()\n",
    ),
    EvaluationCase(
        "lambda-captured-local",
        Language.PYTHON,
        _service("httpx = other\nself.client = (lambda: httpx.AsyncClient())()"),
    ),
    EvaluationCase(
        "lambda-global-write",
        Language.PYTHON,
        _service(
            "self.client = (lambda: httpx.AsyncClient())()",
            "import httpx\ndef replace():\n    global httpx\n    httpx = other",
        ),
    ),
    EvaluationCase("lambda-return-existing", Language.PYTHON, _service("self.client = (lambda: existing)()")),
    EvaluationCase(
        "module-class-body", Language.PYTHON, "import httpx\nclass Owner:\n    client = httpx.AsyncClient()\n"
    ),
    EvaluationCase(
        "plain-nested-class-body",
        Language.PYTHON,
        _service("class Inner:\n    client = httpx.AsyncClient()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "eager-lambda-default",
        Language.PYTHON,
        _service("self.factory = lambda client=httpx.AsyncClient(): client"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested-class-unknown-base", Language.PYTHON, _service("class Inner(Base):\n    client = httpx.AsyncClient()")
    ),
    EvaluationCase(
        "prepared-class-namespace",
        Language.PYTHON,
        _service(
            "class Inner(metaclass=Meta):\n    client = httpx.AsyncClient()",
            "import httpx\nclass Meta(type):\n    @classmethod\n    def __prepare__(mcls, name, bases):\n        return {'httpx': vendor}",
        ),
    ),
    EvaluationCase(
        "metaclass-method-keeps-module-globals",
        Language.PYTHON,
        "import httpx\nclass Meta(type):\n    @classmethod\n    def __prepare__(mcls, name, bases):\n        return {'httpx': vendor}\nclass Service(metaclass=Meta):\n    def __init__(self):\n        self.client = httpx.AsyncClient()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "factory-hidden-yield",
        Language.PYTHON,
        _service(
            "self.client = make_client()",
            "import httpx\ndef make_client():\n    return httpx.AsyncClient(timeout=(yield 1))",
        ),
    ),
    EvaluationCase(
        "lambda-hidden-yield",
        Language.PYTHON,
        _service("self.client = (lambda: httpx.AsyncClient(timeout=(yield 1)))()"),
    ),
    EvaluationCase(
        "generator-constructor", Language.PYTHON, _service("self.client = httpx.AsyncClient(timeout=(yield 1))")
    ),
    EvaluationCase(
        "nested-generator-does-not-defer-constructor",
        Language.PYTHON,
        _service("def later():\n    yield 1\nself.client = httpx.AsyncClient()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested-generator-lambda-does-not-defer-outer-lambda",
        Language.PYTHON,
        _service("self.client = (lambda: httpx.AsyncClient(event_hooks={'response': [lambda: (yield 1)]}))()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "duplicate-module-import",
        Language.PYTHON,
        _service("self.client = httpx.AsyncClient()", "import httpx\nimport httpx"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "duplicate-symbol-import",
        Language.PYTHON,
        _service(
            "self.client = Client()", "from httpx import AsyncClient as Client\nfrom httpx import AsyncClient as Client"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "conflicting-symbol-import",
        Language.PYTHON,
        _service("self.client = Client()", "from httpx import AsyncClient as Client\nfrom vendor import Client"),
    ),
    EvaluationCase(
        "factory-nested-lambda-default-yield",
        Language.PYTHON,
        _service(
            "self.client = make_client()",
            "import httpx\ndef make_client():\n    return httpx.AsyncClient(timeout=(lambda item=(yield 1): item))",
        ),
    ),
    EvaluationCase(
        "factory-generator-first-iterable-yield",
        Language.PYTHON,
        _service(
            "self.client = make_client()",
            "import httpx\ndef make_client():\n    return httpx.AsyncClient(timeout=(item for item in (yield 1)))",
        ),
    ),
    EvaluationCase(
        "local-annotation-is-not-executed",
        Language.PYTHON,
        _service("self.reference = httpx.__name__\nlocal: httpx.AsyncClient()"),
    ),
    EvaluationCase(
        "attribute-annotation-is-not-executed",
        Language.PYTHON,
        _service("self.reference = httpx.__name__\nself.client: httpx.AsyncClient()"),
    ),
    EvaluationCase(
        "annotated-value-is-executed",
        Language.PYTHON,
        _service("self.client: object = httpx.AsyncClient()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "constructor-parameter-annotation",
        Language.PYTHON,
        "import httpx\nclass Service:\n    def __init__(self, value: httpx.AsyncClient()):\n        self.reference = httpx.__name__\n        self.value = value\n",
    ),
    EvaluationCase(
        "constructor-return-annotation",
        Language.PYTHON,
        "import httpx\nclass Service:\n    def __init__(self) -> httpx.AsyncClient():\n        self.reference = httpx.__name__\n",
    ),
    EvaluationCase(
        "nested-function-annotation",
        Language.PYTHON,
        _service("self.reference = httpx.__name__\ndef later(client: httpx.AsyncClient()):\n    return client"),
    ),
    EvaluationCase(
        "nested-class-annotation",
        Language.PYTHON,
        _service("self.reference = httpx.__name__\nclass Inner:\n    client: httpx.AsyncClient()"),
    ),
    EvaluationCase(
        "lazy-type-alias",
        Language.PYTHON,
        _service("self.reference = httpx.__name__\ntype Alias = httpx.AsyncClient()"),
    ),
    EvaluationCase(
        "lazy-type-alias-bound",
        Language.PYTHON,
        _service("self.reference = httpx.__name__\ntype Alias[T: httpx.AsyncClient()] = T"),
    ),
    EvaluationCase(
        "lazy-function-type-parameter",
        Language.PYTHON,
        _service("self.reference = httpx.__name__\ndef later[T: httpx.AsyncClient()]():\n    pass"),
    ),
    EvaluationCase(
        "annotation-with-inert-value",
        Language.PYTHON,
        _service("self.reference = httpx.__name__\nlocal: httpx.AsyncClient() = object()"),
    ),
    EvaluationCase(
        "annotation-and-real-value",
        Language.PYTHON,
        _service("self.reference = httpx.__name__\nself.client: httpx.AsyncClient() = httpx.AsyncClient()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("malformed", Language.PYTHON, "class Service: def __init__("),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = NoAsyncClientInConstructor().check(Path("app/service.py"), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)


def test_distinct_allocations_have_distinct_diagnostics() -> None:
    source = _service("self.first = httpx.AsyncClient()\nself.second = httpx.AsyncClient()")
    findings = NoAsyncClientInConstructor().check(Path("app/service.py"), source)
    assert [finding.line for finding in findings] == [4, 5]
    assert len({(finding.line, finding.col) for finding in findings}) == 2
    assert all(finding.code == "SARJ549" and finding.severity is Severity.ERROR for finding in findings)


def test_error_policy_has_no_unsafe_autofix() -> None:
    documentation = NoAsyncClientInConstructor.documentation
    assert documentation is not None
    assert documentation.default_level is Severity.ERROR
    assert documentation.autofix is AutofixPolicy.NONE


def test_constructor_fallback_advisories_do_not_duplicate_the_client_call(tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    path.write_text(
        _service("self.client = client or httpx.AsyncClient()").replace(
            "def __init__(self):", "def __init__(self, client=None):"
        )
    )
    findings = analyze(
        [NoAsyncClientInConstructor.id, "no-hidden-constructor-fallback", "no-nullable-dependency-fallback"], [path]
    )
    assert [(finding.code, finding.line) for finding in findings] == [("SARJ549", 4)]


def test_documented_examples() -> None:
    verify_native_rule(NoAsyncClientInConstructor, analyze)
