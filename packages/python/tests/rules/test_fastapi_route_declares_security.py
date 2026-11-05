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

    assert (finding.code, finding.line, finding.col, finding.severity) == ("SARJ563", 4, 2, Severity.WARNING)
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


@pytest.mark.parametrize(
    ("mounts", "expected"),
    [
        ("app = FastAPI(dependencies=[Security(require_user)])\napp.include_router(router)\n", 0),
        ("app = FastAPI()\napp.include_router(router, dependencies=[Security(require_user)])\n", 0),
        (
            "parent = APIRouter(dependencies=[Security(require_user)])\nparent.include_router(router)\napp = FastAPI()\napp.include_router(parent)\n",
            0,
        ),
        ("app = FastAPI()\napp.include_router(router)\n", 1),
        ("app = FastAPI()\napp.include_router(router, dependencies=[Depends(require_user)])\n", 1),
        (
            "app = FastAPI()\napp.include_router(router, dependencies=[Security(require_user)])\nother = FastAPI()\nother.include_router(router)\n",
            1,
        ),
        ("app = FastAPI(**options)\napp.include_router(router)\n", 0),
        ("app = FastAPI()\napp.include_router(router, **options)\n", 0),
        ("parent = APIRouter()\nparent.include_router(router)\nrouter.include_router(parent)\n", 0),
    ],
)
def test_effective_router_mount_dependencies(mounts: str, expected: int) -> None:
    source = "from fastapi import FastAPI\n" + _ROUTER
    source += "@router.get('/items')\ndef items(): ...\n" + mounts

    assert len(_check(source)) == expected


@pytest.mark.parametrize("guarded", [False, True])
@pytest.mark.parametrize("reexport", [False, True])
def test_imported_router_inherits_application_dependencies(tmp_path: Path, *, guarded: bool, reexport: bool) -> None:
    package = _package(tmp_path, "")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0"\nrequires-python = ">=3.14"\n', encoding="utf-8"
    )
    route = package / "routes.py"
    route.write_text(_ROUTER + "@router.get('/items')\ndef items(): ...\n", encoding="utf-8")
    (package / "exports.py").write_text("from .routes import router\n", encoding="utf-8")
    imported = "exports" if reexport else "routes"
    dependencies = "dependencies=[Security(require_user)]" if guarded else ""
    (package / "main.py").write_text(
        f"from fastapi import FastAPI, Security\nfrom .{imported} import router as items\napp = FastAPI({dependencies})\napp.include_router(items)\n",
        encoding="utf-8",
    )

    findings = analyze([FastapiRouteDeclaresSecurity.id], [route], jobs=1)

    assert len(findings) == (0 if guarded else 1)
    assert all(finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize(
    "setup",
    [
        "Security = other\n",
        "guards = [Security(require_user)]\nguards.clear()\n",
    ],
)
def test_rebound_or_mutated_security_is_not_borrowed(setup: str) -> None:
    dependency = "guards" if "guards" in setup else "[Security(require_user)]"
    source = _ROUTER + setup + f"@router.get('/items', dependencies={dependency})\ndef items(): ...\n"

    assert len(_check(source)) == 1


@pytest.mark.parametrize("mutation", ["alias = guards; alias.clear()", "unknown(guards)", "unknown([guards])"])
def test_dependency_aliases_do_not_hide_mutation_or_escape(mutation: str) -> None:
    source = _ROUTER + "guards = [Security(require_user)]\n" + mutation + "\n"
    source += "@router.get('/items', dependencies=guards)\ndef items(): ...\n"

    assert len(_check(source)) == 1


def test_unrelated_local_mutation_does_not_poison_a_global_declaration() -> None:
    source = _ROUTER + "guards = [Security(require_user)]\n"
    source += "def clear_local(guards):\n    guards.clear()\n"
    source += "@router.get('/items', dependencies=guards)\ndef items(): ...\n"

    assert _check(source) == []


def test_asgi_mount_does_not_inherit_parent_application_dependencies() -> None:
    source = (
        "from fastapi import FastAPI, Security\n"
        "child = FastAPI()\n@child.get('/items')\ndef items(): ...\n"
        "parent = FastAPI(dependencies=[Security(require_user)])\nparent.mount('/sub', child)\n"
    )

    assert len(_check(source)) == 1


def test_shared_mount_paths_are_resolved_without_repeating_each_path() -> None:
    fragments = [
        "from fastapi import APIRouter, Security\nrouter = APIRouter()\n",
        "@router.get('/items')\ndef items(): ...\n",
    ]
    children = ["router"]
    for level in range(6):
        parents = [f"parent_{level}_{index}" for index in range(8)]
        for parent in parents:
            dependencies = "dependencies=[Security(require_user)]" if level == 5 else ""
            fragments.append(f"{parent} = APIRouter({dependencies})\n")
            fragments.extend(f"{parent}.include_router({child})\n" for child in children)
        children = parents

    assert _check("".join(fragments)) == []


def test_chained_dependency_bindings_do_not_hide_mutation() -> None:
    source = _ROUTER + "guards = alias = [Security(require_user)]\nalias.clear()\n"
    source += "@router.get('/items', dependencies=guards)\ndef items(): ...\n"

    assert len(FastapiRouteDeclaresSecurity().check(Path("app/routes.py"), source)) == 1


@pytest.mark.parametrize("guarded", [True, False], ids=["guarded-production", "unguarded-production"])
def test_test_application_mount_does_not_change_production_access(tmp_path: Path, *, guarded: bool) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="access-fixture"\nversion="0.0.0"\n')
    (tmp_path / "routes.py").write_text(_ROUTER + "@router.get('/items')\ndef items(): ...\n")
    dependency = "dependencies=[Security(require_user)]"
    imports = "from fastapi import FastAPI, Security\nfrom routes import router\n"
    (tmp_path / "app.py").write_text(
        imports + f"app = FastAPI({dependency if guarded else ''})\napp.include_router(router)\n"
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text(
        imports + f"app = FastAPI({'' if guarded else dependency})\napp.include_router(router)\n"
    )

    findings = analyze([FastapiRouteDeclaresSecurity.id], [tmp_path])

    assert len(findings) == (0 if guarded else 1)


@pytest.mark.parametrize(
    ("imports", "parameter", "expected"),
    [
        ("from fastapi import Security", "user: User = Security(require_user)", 0),
        ("from fastapi import Security as Guard", "user: User = Guard(require_user)", 0),
        ("from typing import Annotated", "user: Annotated[User, Security(require_user)]", 0),
        ("from typing import Annotated", "user: 'Annotated[User, Security(require_user)]'", 0),
        ("from auth import Security", "user: User = Security(require_user)", 1),
        ("from vendor import Annotated", "user: Annotated[User, Security(require_user)]", 1),
        ("Annotated = other", "user: Annotated[User, Security(require_user)]", 1),
        ("CurrentUser = other", "user: CurrentUser", 1),
    ],
)
def test_dependency_markers_follow_their_lexical_imports(imports: str, parameter: str, expected: int) -> None:
    source = _ANNOTATED + "CurrentUser = Annotated[User, Security(require_user)]\n"
    source += f"def build():\n    {imports}\n    router = APIRouter()\n"
    source += f"    @router.get('/items')\n    def items({parameter}): ...\n    return router\n"

    assert len(_check(source)) == expected


def test_annotation_alias_reuse_is_not_dependency_list_mutation() -> None:
    source = _ANNOTATED + "CurrentUser = Annotated[User, Security(require_user)]\n"
    source += "Users = list[CurrentUser]\n@router.get('/items')\ndef items(user: CurrentUser): ...\n"

    assert _check(source) == []
