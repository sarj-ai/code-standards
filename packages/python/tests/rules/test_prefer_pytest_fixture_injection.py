from itertools import count
from pathlib import Path, PurePosixPath
import subprocess
import sys
from textwrap import indent
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language, RuleProblem

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.prefer_pytest_fixture_injection import PreferPytestFixtureInjection


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from sarj_python_lint.rule_base import RuleExample


_IMPORTS = "from sample.factory import build_app\nfrom tests.conftest import new_resource\n"
_BODY = "    resource = new_resource()\n    app = build_app(resource=resource)\n    assert app is not None\n"
_BASE = _IMPORTS + "def test_service():\n" + _BODY
_INJECTED = (
    "from sample.factory import build_app\ndef test_service(resource):\n    app = build_app(resource=resource)\n"
)
_HELPER = (
    "from psycopg_pool import ConnectionPool\n"
    "from sample.config import DATABASE_URI\n"
    "def new_resource() -> ConnectionPool:\n"
    "    return ConnectionPool(conninfo=DATABASE_URI, open=False)\n"
)
_FILES = {
    "tests/__init__.py": "",
    "tests/conftest.py": _HELPER,
    "sample/__init__.py": "",
    "sample/config.py": "DATABASE_URI = 'postgresql://localhost/example'\n",
    "sample/factory.py": "def build_app(*, resource):\n    return object()\n",
}
_PROBLEM = RuleProblem(
    key="prefer-pytest-fixture-injection",
    summary="Inject a shared pool fixture instead of manually constructing its resource in a pytest test.",
    harm="Shared dependency setup stays outside pytest fixture discovery, overrides, and dependency graph.",
    languages=frozenset({Language.PYTHON}),
    bad_examples=(_BASE,),
    good_examples=(_INJECTED,),
    exclusions=(
        "Factories with parameters, decorators, asynchronous bodies, or non-pool results.",
        "Construction tests, multiple resource calls, context managers, and ambiguous bindings.",
        "Classes, nested functions, fixture bodies, generated files, and support modules.",
    ),
)


def _case(
    case_id: str,
    source: str,
    expected: ExpectedOutcome = ExpectedOutcome.NO_MATCH,
    path: str = "tests/test_service.py",
) -> EvaluationCase:
    return EvaluationCase(case_id, Language.PYTHON, source, expected, PurePosixPath(path))


_CASES = (
    _case("sync-pool", _BASE, ExpectedOutcome.MATCH),
    _case(
        "inline-resource",
        _IMPORTS + "def test_service():\n    app = build_app(resource=new_resource())\n",
        ExpectedOutcome.MATCH,
    ),
    _case("async-test", _BASE.replace("def test_service", "async def test_service"), ExpectedOutcome.MATCH),
    _case("async-pool", _BASE, ExpectedOutcome.MATCH),
    _case("async-constructor-alias", _BASE, ExpectedOutcome.MATCH),
    _case("generic-pool", _BASE, ExpectedOutcome.MATCH),
    _case("constructor-alias", _BASE, ExpectedOutcome.MATCH),
    _case("constructor-module-alias", _BASE, ExpectedOutcome.MATCH),
    _case("helper-docstring", _BASE, ExpectedOutcome.MATCH),
    _case(
        "test-docstring",
        _BASE.replace("    resource =", '    """Exercise the service."""\n    resource ='),
        ExpectedOutcome.MATCH,
    ),
    _case(
        "import-alias",
        _BASE.replace("import new_resource", "import new_resource as allocate").replace(
            "= new_resource()", "= allocate()"
        ),
        ExpectedOutcome.MATCH,
    ),
    _case("relative-import", _BASE.replace("from tests.conftest", "from .conftest"), ExpectedOutcome.MATCH),
    _case("bare-conftest-import", _BASE.replace("from tests.conftest", "from conftest"), ExpectedOutcome.MATCH),
    _case(
        "positional-consumer",
        _BASE.replace("build_app(resource=resource)", "build_app(resource)"),
        ExpectedOutcome.MATCH,
    ),
    _case(
        "expression-consumer",
        _BASE.replace("app = build_app", "build_app").replace("    assert app is not None\n", ""),
        ExpectedOutcome.MATCH,
    ),
    _case(
        "marked-test",
        "import pytest\n" + _BASE.replace("def test_service", "@pytest.mark.integration\ndef test_service"),
        ExpectedOutcome.MATCH,
    ),
    _case("suffix-test-module", _BASE, ExpectedOutcome.MATCH, "tests/service_test.py"),
    _case(
        "lifespan-after-injection",
        _BASE.replace("def test_service", "async def test_service")
        + "    async with lifespan(app):\n        assert resource.closed is False\n    assert resource.closed\n",
        ExpectedOutcome.MATCH,
    ),
    _case("fixture-injection", _INJECTED),
    _case("fixture-body", "import pytest\n" + _BASE.replace("def test_service", "@pytest.fixture\ndef test_service")),
    _case("helper-body", _BASE.replace("def test_service", "def prepare_service")),
    _case("class-method", _IMPORTS + "class TestService:\n" + indent("def test_service(self):\n" + _BODY, "    ")),
    _case("nested-test", _IMPORTS + "def outer():\n" + indent("def test_service():\n" + _BODY, "    ")),
    _case(
        "unittest-method",
        "import unittest\n"
        + _IMPORTS
        + "class TestService(unittest.TestCase):\n"
        + indent("def test_service(self):\n" + _BODY, "    "),
    ),
    _case("support-module", _BASE, path="tests/support.py"),
    _case("conftest-module", _BASE, path="tests/conftest.py"),
    _case("module-optout", "__test__ = False\n" + _BASE),
    _case("function-optout", _BASE + "test_service.__test__ = False\n"),
    _case("function-optout-alias", _BASE + "collected = test_service\ncollected.__test__ = False\n"),
    _case("test-rebind", _BASE + "test_service = replacement\n"),
    _case("test-delete", _BASE + "del test_service\n"),
    _case("generated-banner", "# @generated\n" + _BASE),
    _case("generated-path", _BASE, path="generated/tests/test_service.py"),
    _case(
        "type-only-import",
        _BASE.replace(
            "from tests.conftest import new_resource",
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from tests.conftest import new_resource",
        ),
    ),
    _case("wildcard-import", _BASE.replace("import new_resource", "import *")),
    _case(
        "module-helper-call",
        _BASE.replace("from tests.conftest import new_resource", "import tests.conftest as shared").replace(
            "= new_resource()", "= shared.new_resource()"
        ),
    ),
    _case("non-conftest-helper", _BASE.replace("from tests.conftest", "from tests.helpers")),
    _case("parameterized-helper", _BASE),
    _case("defaulted-helper", _BASE),
    _case("variadic-helper", _BASE),
    _case("keyword-only-helper", _BASE),
    _case("async-helper", _BASE),
    _case("async-pool-implicit-open", _BASE),
    _case("async-pool-open-true", _BASE),
    _case("async-pool-open-none", _BASE),
    _case("async-pool-dynamic-open", _BASE),
    _case("async-pool-unpacked-keywords", _BASE),
    _case("async-pool-unpacked-positionals", _BASE),
    _case("async-pool-constructor-argument-call", _BASE),
    _case("type-only-constructor", _BASE),
    _case("decorated-helper", _BASE),
    _case("yield-helper", _BASE),
    _case("extra-helper-statement", _BASE),
    _case("data-factory", _BASE),
    _case("foreign-pool-type", _BASE),
    _case("pool-constructor-shadow", _BASE),
    _case("pool-module-shadow", _BASE),
    _case("pool-attribute-rewrite", _BASE),
    _case("source-helper-wildcard", _BASE),
    _case("helper-module-shadow", _BASE),
    _case("helper-duplicate-definition", _BASE),
    _case("helper-parameter-shadow", _BASE.replace("test_service():", "test_service(new_resource):")),
    _case("helper-local-shadow", _BASE + "    new_resource = replacement\n"),
    _case("helper-import-rebind", _BASE + "new_resource = replacement\n"),
    _case("caller-helper-code-rewrite", _BASE + "new_resource.__code__ = replacement.__code__\n"),
    _case("source-helper-code-rewrite", _BASE),
    _case("consumer-parameter-shadow", _BASE.replace("test_service():", "test_service(build_app):")),
    _case("consumer-local-shadow", _BASE + "    build_app = replacement\n"),
    _case("resource-rebind", _BASE.replace("    app =", "    resource = replacement\n    app =")),
    _case("multiple-helper-calls", _BASE + "    other = new_resource()\n"),
    _case("call-with-argument", _BASE.replace("new_resource()", "new_resource('custom')")),
    _case("preceding-patch", _BASE.replace("    resource =", "    patch('sample.factory.open')\n    resource =")),
    _case(
        "preceding-context",
        _IMPORTS + "def test_service():\n    with patch('sample.factory.open'):\n" + indent(_BODY, "    "),
    ),
    _case(
        "construction-observation",
        _IMPORTS + "def test_service():\n    with pytest.raises(ValueError):\n        new_resource()\n",
    ),
    _case(
        "resource-context-manager",
        _IMPORTS + "def test_service():\n    with new_resource() as resource:\n        build_app(resource=resource)\n",
    ),
    _case("no-consumer", _BASE.replace("    app = build_app(resource=resource)\n", "")),
    _case("indirect-consumer", _BASE.replace("resource=resource", "resource=wrap(resource)")),
    _case("nonadjacent-consumer", _BASE.replace("    app =", "    observe()\n    app =")),
    _case("conditional-consumer", _BASE.replace("    app =", "    if enabled:\n        app =")),
    _case("malformed-test", "def test_service(:\n"),
    _case("malformed-helper", _BASE),
    _case("missing-helper", _BASE),
    _case("string-only", "example = 'resource = new_resource()'\n"),
    _case("comment-only", "# resource = new_resource()\n# app = build_app(resource=resource)\n"),
    _case(
        "exact-suppression",
        _BASE.replace("new_resource()", "new_resource()  # sarj-noqa: SARJ476 -- lifecycle setup intentionally manual"),
    ),
)
_SUPPORT = {
    "async-pool": _HELPER.replace("ConnectionPool", "AsyncConnectionPool"),
    "async-constructor-alias": _HELPER.replace("ConnectionPool", "AsyncConnectionPool")
    .replace("import AsyncConnectionPool", "import AsyncConnectionPool as Pool")
    .replace("-> AsyncConnectionPool", "-> Pool")
    .replace("return AsyncConnectionPool(", "return Pool("),
    "async-pool-implicit-open": _HELPER.replace("ConnectionPool", "AsyncConnectionPool").replace(", open=False", ""),
    "async-pool-open-true": _HELPER.replace("ConnectionPool", "AsyncConnectionPool").replace("open=False", "open=True"),
    "async-pool-open-none": _HELPER.replace("ConnectionPool", "AsyncConnectionPool").replace("open=False", "open=None"),
    "async-pool-dynamic-open": _HELPER.replace("ConnectionPool", "AsyncConnectionPool").replace(
        "open=False", "open=OPEN_POOL"
    ),
    "async-pool-unpacked-keywords": _HELPER.replace("ConnectionPool", "AsyncConnectionPool").replace(
        "open=False", "open=False, **POOL_OPTIONS"
    ),
    "async-pool-unpacked-positionals": _HELPER.replace("ConnectionPool", "AsyncConnectionPool").replace(
        "conninfo=DATABASE_URI", "*POOL_ARGUMENTS"
    ),
    "async-pool-constructor-argument-call": _HELPER.replace("ConnectionPool", "AsyncConnectionPool").replace(
        "conninfo=DATABASE_URI", "conninfo=database_uri()"
    ),
    "generic-pool": _HELPER.replace("ConnectionPool(conninfo", "ConnectionPool[object](conninfo"),
    "constructor-alias": _HELPER.replace("import ConnectionPool", "import ConnectionPool as Pool")
    .replace("-> ConnectionPool", "-> Pool")
    .replace("return ConnectionPool(", "return Pool("),
    "constructor-module-alias": _HELPER.replace(
        "from psycopg_pool import ConnectionPool", "import psycopg_pool as pools"
    )
    .replace("-> ConnectionPool", "-> pools.ConnectionPool")
    .replace("return ConnectionPool(", "return pools.ConnectionPool("),
    "helper-docstring": _HELPER.replace("    return", '    """Allocate a shared resource."""\n    return'),
    "parameterized-helper": _HELPER.replace("new_resource()", "new_resource(uri)"),
    "defaulted-helper": _HELPER.replace("new_resource()", "new_resource(uri=DATABASE_URI)"),
    "variadic-helper": _HELPER.replace("new_resource()", "new_resource(*args)"),
    "keyword-only-helper": _HELPER.replace("new_resource()", "new_resource(*, uri=DATABASE_URI)"),
    "async-helper": _HELPER.replace("def new_resource", "async def new_resource"),
    "type-only-constructor": _HELPER.replace(
        "from psycopg_pool import ConnectionPool",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from psycopg_pool import ConnectionPool",
    ),
    "decorated-helper": "import pytest\n" + _HELPER.replace("def new_resource", "@pytest.fixture\ndef new_resource"),
    "yield-helper": _HELPER.replace("return ConnectionPool", "yield ConnectionPool"),
    "extra-helper-statement": _HELPER.replace("    return", "    observe()\n    return"),
    "data-factory": "def new_resource():\n    return {'resource': 'data'}\n",
    "foreign-pool-type": _HELPER.replace("from psycopg_pool", "from another_library"),
    "pool-constructor-shadow": _HELPER.replace("def new_resource", "ConnectionPool = replacement\ndef new_resource"),
    "pool-module-shadow": _HELPER.replace(
        "from psycopg_pool import ConnectionPool", "import psycopg_pool as pools\npools = replacement"
    ).replace("ConnectionPool", "pools.ConnectionPool"),
    "pool-attribute-rewrite": _HELPER.replace("from psycopg_pool import ConnectionPool", "import psycopg_pool as pp")
    .replace("ConnectionPool", "pp.ConnectionPool")
    .replace("def new_resource", "pp.ConnectionPool = replacement\ndef new_resource"),
    "source-helper-wildcard": "from another_library import *\n" + _HELPER,
    "helper-module-shadow": _HELPER + "new_resource = replacement\n",
    "source-helper-code-rewrite": _HELPER + "new_resource.__code__ = replacement.__code__\n",
    "helper-duplicate-definition": _HELPER + "def new_resource():\n    return replacement\n",
    "malformed-helper": "def new_resource(:\n",
}


_PROVENANCE_CASES = (
    (
        _case(
            "rewritten-pytest-marker",
            "import pytest\n"
            + _BASE.replace(
                "def test_service",
                "pytest.mark.integration = pytest.fixture\n@pytest.mark.integration\ndef test_service",
            ),
        ),
        _HELPER,
    ),
    (
        _case(
            "ordinary-pytest-marker",
            "import pytest\n" + _BASE.replace("def test_service", "@pytest.mark.integration\ndef test_service"),
            ExpectedOutcome.MATCH,
        ),
        _HELPER,
    ),
    (
        _case(
            "unrelated-pytest-attribute",
            "import pytest\n"
            + _BASE.replace("def test_service", "pytest.other = True\n@pytest.mark.integration\ndef test_service"),
            ExpectedOutcome.MATCH,
        ),
        _HELPER,
    ),
    (
        _case("global-constructor-writer", _BASE),
        _HELPER + "def configure():\n    global ConnectionPool\n    ConnectionPool = replacement\nconfigure()\n",
    ),
    (
        _case("global-helper-writer", _BASE),
        _HELPER + "def configure():\n    global new_resource\n    new_resource = replacement\nconfigure()\n",
    ),
    (
        _case("constructor-default-walrus", _BASE),
        _HELPER + "def configure(unused=(ConnectionPool := replacement)):\n    pass\n",
    ),
    (
        _case(
            "caller-helper-default-walrus",
            _BASE.replace(
                "def test_service", "def configure(unused=(new_resource := replacement)):\n    pass\ndef test_service"
            ),
        ),
        _HELPER,
    ),
    (
        _case(
            "caller-conditional-wildcard",
            _BASE.replace("def test_service", "if enabled:\n    from sample.custom import *\ndef test_service"),
        ),
        _HELPER,
    ),
    (
        _case("constructor-read-only-global", _BASE, ExpectedOutcome.MATCH),
        _HELPER + "def observe():\n    global ConnectionPool\n    return ConnectionPool\n",
    ),
    (
        _case("unrelated-default-walrus", _BASE, ExpectedOutcome.MATCH),
        _HELPER + "def configure(unused=(other := object())):\n    pass\n",
    ),
)


@pytest.mark.parametrize(
    ("case", "helper"), _PROVENANCE_CASES, ids=tuple(case.case_id for case, _helper in _PROVENANCE_CASES)
)
def test_helper_requires_runtime_binding_provenance(
    case: EvaluationCase, helper: str, project: Callable[[str, Mapping[str, str]], Path]
) -> None:
    path = project(case.path.as_posix(), {**_FILES, "tests/conftest.py": helper, "tests/test_service.py": case.source})
    assert bool(PreferPytestFixtureInjection().check(path, case.source)) is (case.expected is ExpectedOutcome.MATCH)


@pytest.fixture
def project(tmp_path: Path) -> Callable[[str, Mapping[str, str]], Path]:
    sequence = count()

    def materialize(focus: str, files: Mapping[str, str]) -> Path:
        root = tmp_path / f"project-{next(sequence)}"
        root.mkdir()
        (root / ".git").mkdir()
        (root / "pyproject.toml").write_text("[project]\nname = 'sample'\nversion = '0.1.0'\n", encoding="utf-8")
        for relative, source in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return root / focus

    return materialize


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase, project: Callable[[str, Mapping[str, str]], Path]) -> None:
    files = {
        key: source
        for key, source in _FILES.items()
        if not (case.case_id == "missing-helper" and key == "tests/conftest.py")
    }
    if case.case_id != "missing-helper":
        files["tests/conftest.py"] = _SUPPORT.get(case.case_id, _HELPER)
    if case.case_id == "non-conftest-helper":
        files["tests/helpers.py"] = _HELPER
    focus = case.path.as_posix()
    files[focus] = case.source
    path = project(focus, files)
    findings = (
        analyze([PreferPytestFixtureInjection.id], [path])
        if case.case_id == "exact-suppression"
        else PreferPytestFixtureInjection().check(path, case.source)
    )
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(finding.code == "SARJ476" and finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize("example", PreferPytestFixtureInjection.public_examples())
def test_public_examples(example: RuleExample, project: Callable[[str, Mapping[str, str]], Path]) -> None:
    files = {item.path.as_posix(): item.source for item in example.files}
    path = project(example.focus_path.as_posix(), files)
    assert len(PreferPytestFixtureInjection().check(path, example.focus_file.source)) == example.expected_count


def test_metadata_anchor_and_no_autofix(project: Callable[[str, Mapping[str, str]], Path]) -> None:
    documentation = PreferPytestFixtureInjection.documentation
    assert documentation is not None
    assert documentation.default_level is Severity.WARNING
    assert documentation.autofix is AutofixPolicy.NONE
    assert _PROBLEM.autofix is AutofixPolicy.NONE
    path = project("tests/test_service.py", {**_FILES, "tests/test_service.py": _BASE})
    finding = PreferPytestFixtureInjection().check(path, _BASE)[0]
    assert (finding.code, finding.line, finding.col) == ("SARJ476", 4, 16)
    assert "fixture" in finding.message.lower()
    assert "caching" in finding.message
    assert "setup dependencies" in finding.message
    assert "application lifespan" in finding.message


def test_allocation_fixture_caches_without_taking_application_lifecycle(
    project: Callable[[str, Mapping[str, str]], Path],
) -> None:
    source = (
        "from contextlib import contextmanager\nimport pytest\n\n"
        "class Pool:\n"
        "    def __init__(self):\n"
        "        self.closed = True\n        self.opens = 0\n        self.closes = 0\n\n"
        "class Application:\n"
        "    def __init__(self, pool):\n        self.pool = pool\n\n"
        "    @contextmanager\n    def lifespan(self):\n"
        "        self.pool.opens += 1\n        self.pool.closed = False\n"
        "        try:\n            yield\n"
        "        finally:\n            self.pool.closes += 1\n            self.pool.closed = True\n\n"
        "@pytest.fixture\ndef pool():\n    return Pool()\n\n"
        "@pytest.fixture\ndef app(pool):\n    return Application(pool)\n\n"
        "def test_application_owns_lifecycle(app, pool, request):\n"
        "    assert app.pool is pool\n    assert request.getfixturevalue('pool') is pool\n"
        "    assert pool.closed\n    assert (pool.opens, pool.closes) == (0, 0)\n"
        "    with app.lifespan():\n        assert not pool.closed\n"
        "    assert pool.closed\n    assert (pool.opens, pool.closes) == (1, 1)\n"
    )
    path = project("test_fixture_lifecycle.py", {"test_fixture_lifecycle.py": source})
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(path)],
        cwd=path.parent,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_warning_cli_and_exact_suppression(
    project: Callable[[str, Mapping[str, str]], Path], capsys: pytest.CaptureFixture[str]
) -> None:
    path = project("tests/test_service.py", {**_FILES, "tests/test_service.py": _BASE})
    assert main(["check", "--rule", PreferPytestFixtureInjection.id, str(path)]) == 0
    assert "SARJ476 warning:" in capsys.readouterr().out
    path.write_text(
        _BASE.replace("new_resource()", "new_resource()  # sarj-noqa: SARJ476 -- deliberate manual lifecycle"),
        encoding="utf-8",
    )
    assert analyze([PreferPytestFixtureInjection.id], [path]) == []
    path.write_text(
        _BASE.replace("new_resource()", "new_resource()  # sarj-noqa: SARJ474 -- different warning"), encoding="utf-8"
    )
    assert len(analyze([PreferPytestFixtureInjection.id], [path])) == 1


def test_relative_paths_in_rule_and_cli(
    project: Callable[[str, Mapping[str, str]], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = project("tests/test_service.py", {**_FILES, "tests/test_service.py": _BASE})
    monkeypatch.chdir(path.parent.parent)
    relative = Path("tests/test_service.py")
    assert len(PreferPytestFixtureInjection().check(relative, _BASE)) == 1
    assert main(["check", "--rule", PreferPytestFixtureInjection.id, str(relative)]) == 0
    assert "SARJ476 warning:" in capsys.readouterr().out


def test_reused_rule_observes_helper_edits(project: Callable[[str, Mapping[str, str]], Path]) -> None:
    path = project("tests/test_service.py", {**_FILES, "tests/test_service.py": _BASE})
    helper = path.with_name("conftest.py")
    rule = PreferPytestFixtureInjection()
    assert len(rule.check(path, _BASE)) == 1
    helper.write_text(_SUPPORT["data-factory"], encoding="utf-8")
    assert rule.check(path, _BASE) == []
    helper.write_text(_HELPER, encoding="utf-8")
    assert len(rule.check(path, _BASE)) == 1


def test_distinct_projects_do_not_share_helper_results(project: Callable[[str, Mapping[str, str]], Path]) -> None:
    positive = project("tests/test_service.py", {**_FILES, "tests/test_service.py": _BASE})
    negative = project(
        "tests/test_service.py",
        {**_FILES, "tests/conftest.py": _SUPPORT["data-factory"], "tests/test_service.py": _BASE},
    )
    rules = [PreferPytestFixtureInjection.id]
    assert [finding.code for finding in analyze(rules, [positive, negative])] == ["SARJ476"]
    assert [finding.code for finding in analyze(rules, [negative, positive])] == ["SARJ476"]
    assert [finding.code for finding in analyze(rules, [positive])] == ["SARJ476"]


def test_ambiguous_module_roots_stay_quiet(project: Callable[[str, Mapping[str, str]], Path]) -> None:
    files = {**_FILES, "tests/test_service.py": _BASE, "src/tests/__init__.py": "", "src/tests/conftest.py": _HELPER}
    path = project("tests/test_service.py", files)
    assert PreferPytestFixtureInjection().check(path, _BASE) == []


def test_symlinked_helper_stays_quiet(project: Callable[[str, Mapping[str, str]], Path]) -> None:
    files = {**_FILES, "tests/test_service.py": _BASE, "tests/real_support.py": _HELPER}
    path = project("tests/test_service.py", files)
    helper = path.with_name("conftest.py")
    helper.unlink()
    helper.symlink_to("real_support.py")
    assert PreferPytestFixtureInjection().check(path, _BASE) == []


def test_src_layout_provider_outside_test_ancestors_stays_quiet(
    project: Callable[[str, Mapping[str, str]], Path],
) -> None:
    source = _BASE.replace("from tests.conftest", "from sample.conftest")
    files = {
        "tests/test_service.py": source,
        "src/sample/__init__.py": "",
        "src/sample/conftest.py": _HELPER,
        "src/sample/config.py": _FILES["sample/config.py"],
        "src/sample/factory.py": _FILES["sample/factory.py"],
    }
    path = project("tests/test_service.py", files)
    assert PreferPytestFixtureInjection().check(path, source) == []


def test_src_layout_ancestor_conftest_is_visible(project: Callable[[str, Mapping[str, str]], Path]) -> None:
    source = _BASE.replace("from tests.conftest", "from sample.conftest")
    files = {
        "src/sample/test_service.py": source,
        "src/sample/__init__.py": "",
        "src/sample/conftest.py": _HELPER,
        "src/sample/config.py": _FILES["sample/config.py"],
        "src/sample/factory.py": _FILES["sample/factory.py"],
    }
    path = project("src/sample/test_service.py", files)
    assert len(PreferPytestFixtureInjection().check(path, source)) == 1


def test_sibling_conftest_is_not_visible_to_test(project: Callable[[str, Mapping[str, str]], Path]) -> None:
    source = _BASE.replace("from tests.conftest", "from tests.provider.conftest")
    path = project(
        "tests/test_service.py",
        {**_FILES, "tests/test_service.py": source, "tests/provider/conftest.py": _HELPER},
    )
    assert PreferPytestFixtureInjection().check(path, source) == []


def test_relative_parent_import_stays_in_project(project: Callable[[str, Mapping[str, str]], Path]) -> None:
    source = _BASE.replace("from tests.conftest", "from ..conftest")
    path = project("tests/sub/test_service.py", {**_FILES, "tests/sub/test_service.py": source})
    assert len(PreferPytestFixtureInjection().check(path, source)) == 1
    escaped = source.replace("from ..conftest", "from ....conftest")
    assert PreferPytestFixtureInjection().check(path, escaped) == []


def test_package_named_conftest_is_not_a_pytest_support_file(
    project: Callable[[str, Mapping[str, str]], Path],
) -> None:
    files = {key: value for key, value in _FILES.items() if key != "tests/conftest.py"}
    files.update({"tests/conftest/__init__.py": _HELPER, "tests/test_service.py": _BASE})
    path = project("tests/test_service.py", files)
    assert PreferPytestFixtureInjection().check(path, _BASE) == []


@pytest.mark.parametrize(
    "boundary",
    ["oversized-helper", "nested-checkout", "symlink-directory", "module-and-package", "missing-root"],
)
def test_local_source_boundaries_stay_quiet(project: Callable[[str, Mapping[str, str]], Path], boundary: str) -> None:
    nested = boundary in {"nested-checkout", "symlink-directory"}
    source = _BASE.replace("from tests.conftest", "from tests.provider.conftest") if nested else _BASE
    focus = "tests/provider/test_service.py" if nested else "tests/test_service.py"
    files = {**_FILES, focus: source}
    if nested:
        files["tests/provider/conftest.py"] = _HELPER
    path = project(focus, files)
    root = path.parents[2] if nested else path.parent.parent
    helper = path.with_name("conftest.py")
    assert len(PreferPytestFixtureInjection().check(path, source)) == 1

    match boundary:
        case "oversized-helper":
            helper.write_text(_HELPER + "\n#" + "x" * 256_000, encoding="utf-8")
        case "nested-checkout":
            (helper.parent / ".git").mkdir()
        case "symlink-directory":
            outside = project("tests/test_service.py", {**_FILES, "tests/test_service.py": _BASE})
            helper.unlink()
            path.unlink()
            helper.parent.rmdir()
            helper.parent.symlink_to(outside.parent, target_is_directory=True)
        case "module-and-package":
            package = path.parent / "conftest"
            package.mkdir()
            (package / "__init__.py").write_text(_HELPER, encoding="utf-8")
        case _:
            (root / ".git").rmdir()
            (root / "pyproject.toml").unlink()

    assert PreferPytestFixtureInjection().check(path, source) == []


@pytest.mark.parametrize("mutation", ["del pp.ConnectionPool", "pp.__dict__['ConnectionPool'] = replacement"])
def test_mutated_constructor_module_stays_quiet(
    project: Callable[[str, Mapping[str, str]], Path], mutation: str
) -> None:
    helper = _HELPER.replace("from psycopg_pool import ConnectionPool", "import psycopg_pool as pp")
    helper = helper.replace("ConnectionPool", "pp.ConnectionPool")
    helper = helper.replace("def new_resource", f"{mutation}\ndef new_resource")
    path = project("tests/test_service.py", {**_FILES, "tests/conftest.py": helper, "tests/test_service.py": _BASE})
    assert PreferPytestFixtureInjection().check(path, _BASE) == []


def test_nearby_rules_and_repeated_invocations(project: Callable[[str, Mapping[str, str]], Path]) -> None:
    path = project("tests/test_service.py", {**_FILES, "tests/test_service.py": _BASE})
    rules = [
        "repeated-static-call-cases",
        "unused-test-factory-option",
        "no-conftest-test-module-import",
        PreferPytestFixtureInjection.id,
    ]
    first = analyze(rules, [path])
    assert [finding.code for finding in first] == ["SARJ476"]
    assert first == analyze(list(reversed(rules)), [path])
    assert first == analyze(rules, [path])
