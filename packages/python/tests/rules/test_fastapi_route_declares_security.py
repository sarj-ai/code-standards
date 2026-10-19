from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.fastapi_route_declares_security import FastapiRouteDeclaresSecurity


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_ROUTER = "from fastapi import APIRouter, Depends, Security\nrouter = APIRouter()\n"
_ANNOTATED = "from typing import Annotated\n" + _ROUTER
_CLASS_ROUTER = (
    "from fastapi import APIRouter, Depends, Security\n"
    "class ItemRouter:\n"
    "    def build(self) -> APIRouter:\n"
    "        router = APIRouter()\n"
)

_CASES = (
    EvaluationCase(
        "decorator-depends-only",
        Language.PYTHON,
        _ROUTER + "@router.get('/items', dependencies=[Depends(require_user)])\ndef items(): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "no-dependencies",
        Language.PYTHON,
        _ROUTER + "@router.post('/items')\ndef create(): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "parameter-depends-only",
        Language.PYTHON,
        _ANNOTATED + "@router.get('/items')\ndef items(user: Annotated[User, Depends(require_user)]): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "router-depends-only",
        Language.PYTHON,
        "from fastapi import APIRouter, Depends\nrouter = APIRouter(dependencies=[Depends(require_user)])\n"
        "@router.get('/items')\ndef items(): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "hidden-route-still-serves",
        Language.PYTHON,
        _ROUTER + "@router.patch('/marker', include_in_schema=False)\ndef marker(): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "application-route",
        Language.PYTHON,
        "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/')\ndef welcome(): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "class-router-without-security",
        Language.PYTHON,
        _CLASS_ROUTER + "        @router.get('/items')\n        def items(): ...\n        return router\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "alias-of-depends-list",
        Language.PYTHON,
        _ROUTER
        + "can_read = [Depends(require_user)]\n@router.get('/items', dependencies=can_read)\ndef items(): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "alias-rebound-without-security",
        Language.PYTHON,
        _ROUTER
        + "guards = [Security(require_admin)]\nif relaxed:\n    guards = []\n"
        + "@router.get('/items', dependencies=guards)\ndef items(): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "alias-shadowed-by-parameter",
        Language.PYTHON,
        "from fastapi import APIRouter, Security\nguards = [Security(require_admin)]\n"
        "def build(guards):\n    router = APIRouter()\n"
        "    @router.get('/items', dependencies=guards)\n    def items(): ...\n    return router\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "outer-class-attribute-is-not-in-scope",
        Language.PYTHON,
        "from fastapi import APIRouter, Security\n"
        "class ItemRouter:\n    guards = [Security(require_admin)]\n"
        "    def build(self) -> APIRouter:\n        router = APIRouter()\n"
        "        @router.get('/items', dependencies=guards)\n        def items(): ...\n        return router\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "security-from-another-library",
        Language.PYTHON,
        "from fastapi import APIRouter\nfrom auth import Security\nrouter = APIRouter()\n"
        "@router.get('/items', dependencies=[Security(require_admin)])\ndef items(): ...\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "decorator-security",
        Language.PYTHON,
        _ROUTER + "@router.get('/items', dependencies=[Security(require_user)])\ndef items(): ...\n",
    ),
    EvaluationCase(
        "fastapi-module-attribute",
        Language.PYTHON,
        "import fastapi\nrouter = fastapi.APIRouter()\n"
        "@router.get('/items', dependencies=[fastapi.Security(require_user)])\ndef items(): ...\n",
    ),
    EvaluationCase(
        "renamed-security-import",
        Language.PYTHON,
        "from fastapi import APIRouter, Security as Guard\nrouter = APIRouter()\n"
        "@router.get('/items', dependencies=[Guard(require_user)])\ndef items(): ...\n",
    ),
    EvaluationCase(
        "parameter-security",
        Language.PYTHON,
        _ANNOTATED + "@router.get('/items')\ndef items(scope: Annotated[Scope, Security(require_user)]): ...\n",
    ),
    EvaluationCase(
        "parameter-default-security",
        Language.PYTHON,
        _ROUTER + "@router.get('/items')\ndef items(scope: Scope = Security(require_user)): ...\n",
    ),
    EvaluationCase(
        "local-annotated-alias",
        Language.PYTHON,
        _ANNOTATED
        + "CurrentScope = Annotated[Scope, Security(require_user)]\n"
        + "@router.get('/items')\ndef items(scope: CurrentScope): ...\n",
    ),
    EvaluationCase(
        "postponed-annotations",
        Language.PYTHON,
        "from __future__ import annotations\n"
        + _ANNOTATED
        + "@router.get('/items')\ndef items(scope: Annotated[Scope, Security(require_user)]): ...\n",
    ),
    EvaluationCase(
        "alias-of-security-list-in-build",
        Language.PYTHON,
        _CLASS_ROUTER
        + "        can_write = [Security(require_writer)]\n"
        + "        @router.post('/items', dependencies=can_write)\n        def create(): ...\n        return router\n",
    ),
    EvaluationCase(
        "starred-alias",
        Language.PYTHON,
        _ROUTER
        + "guards = [Security(require_admin)]\n"
        + "@router.get('/items', dependencies=[*guards, Depends(load_item)])\ndef items(): ...\n",
    ),
    EvaluationCase(
        "concatenated-alias",
        Language.PYTHON,
        _ROUTER
        + "guards = [Security(require_admin)]\n"
        + "@router.get('/items', dependencies=[Depends(load_item)] + guards)\ndef items(): ...\n",
    ),
    EvaluationCase(
        "router-security",
        Language.PYTHON,
        "from fastapi import APIRouter, Security\nrouter = APIRouter(dependencies=[Security(require_admin)])\n"
        "@router.delete('/items/{item_id}')\ndef delete(item_id: str): ...\n",
    ),
    EvaluationCase(
        "class-router-level-security",
        Language.PYTHON,
        "from fastapi import APIRouter, Security\n"
        "class TaskRouter:\n    def build(self) -> APIRouter:\n"
        "        router = APIRouter(prefix='/tasks', dependencies=[Security(self._guard)])\n"
        "        @router.post('/run')\n        def run(): ...\n        return router\n",
    ),
    EvaluationCase(
        "explicit-public-marker",
        Language.PYTHON,
        _ROUTER + "@router.get('/health', dependencies=[Security(public_route)])\ndef health(): ...\n",
    ),
    EvaluationCase("plain-function", Language.PYTHON, "def items(): ...\n"),
    EvaluationCase(
        "non-fastapi-decorator",
        Language.PYTHON,
        "from flask import Flask\napp = Flask(__name__)\n@app.get('/items')\ndef items(): ...\n",
    ),
    EvaluationCase(
        "unpacked-decorator-options",
        Language.PYTHON,
        _ROUTER + "@router.get('/items', **route_options)\ndef items(): ...\n",
    ),
    EvaluationCase("malformed-input", Language.PYTHON, "@router.get('/items'\ndef items(:\n"),
)


def _check(source: str, path: str = "app/routes.py") -> list[Diagnostic]:
    return FastapiRouteDeclaresSecurity().check(Path(path), source)


@pytest.mark.parametrize("case", _CASES, ids=[case.case_id for case in _CASES])
def test_labeled_route_cases(case: EvaluationCase) -> None:
    assert bool(_check(case.source)) is (case.expected is ExpectedOutcome.MATCH)


@pytest.mark.parametrize(
    "example",
    FastapiRouteDeclaresSecurity.public_examples(),
    ids=[example.example_id for example in FastapiRouteDeclaresSecurity.public_examples()],
)
def test_public_examples_are_executable(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_file.path))) == example.expected_count


def test_documented_examples() -> None:
    verify_native_rule(FastapiRouteDeclaresSecurity, analyze)


def test_finding_points_at_the_decorator_and_names_the_route() -> None:
    [finding] = _check(_ROUTER + "\n@router.delete('/items/{item_id}')\ndef delete(item_id: str): ...\n")

    assert (finding.code, finding.line, finding.col, finding.severity) == ("SARJ522", 4, 2, Severity.ERROR)
    assert finding.message.startswith("`DELETE /items/{item_id}` declares no `Security()` dependency")


def test_multi_method_route_reports_once() -> None:
    [finding] = _check(_ROUTER + "@router.api_route('/items', methods=['GET', 'POST'])\ndef items(): ...\n")

    assert finding.message.startswith("`GET/POST /items`")


def test_each_route_decorator_is_judged_on_its_own() -> None:
    source = (
        _ROUTER
        + "@router.get('/items', dependencies=[Security(require_user)])\n"
        + "@router.get('/legacy-items')\ndef items(): ...\n"
    )

    [finding] = _check(source)
    assert "/legacy-items" in finding.message


def _package(tmp_path: Path, dependencies: str) -> Path:
    (tmp_path / ".git").mkdir()
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "dependencies.py").write_text(dependencies, encoding="utf-8")
    return package


def test_imported_security_alias_is_resolved_from_source(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        "from typing import Annotated\nfrom fastapi import Security\n"
        "CurrentScope = Annotated[Scope, Security(require_user)]\n",
    )
    source = (
        _ROUTER + "from .dependencies import CurrentScope\n@router.get('/items')\ndef items(scope: CurrentScope): ...\n"
    )

    assert _check(source, str(package / "routes.py")) == []


def test_imported_depends_alias_is_not_security(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        "from typing import Annotated\nfrom fastapi import Depends\n"
        "CurrentUser = Annotated[User, Depends(require_user)]\n",
    )
    source = (
        _ROUTER + "from .dependencies import CurrentUser\n@router.get('/items')\ndef items(user: CurrentUser): ...\n"
    )

    assert len(_check(source, str(package / "routes.py"))) == 1


@pytest.mark.parametrize("path", ["tests/test_routes.py", "generated/routes.py"])
def test_tests_and_generated_code_are_excluded(path: str) -> None:
    assert _check(_ROUTER + "@router.get('/items')\ndef items(): ...\n", path) == []
