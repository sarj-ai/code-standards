from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_create_verb_in_post_path import NoCreateVerbInPostPath


_HEADER = "from fastapi import APIRouter\n\nrouter = APIRouter(prefix='/items')\n\n"


def _lines(decorator: str, path: str = "api.py") -> list[int]:
    source = f"{_HEADER}{decorator}\nasync def handler() -> None:\n    return None\n"
    return [finding.line for finding in NoCreateVerbInPostPath().check(Path(path), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoCreateVerbInPostPath, analyze)


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@router.post('/create')", id="bare-create"),
        pytest.param("@router.post('/add-users-to-organization')", id="add-words"),
        pytest.param("@router.post('/create-for-user')", id="create-words"),
        pytest.param("@router.post('/desk/create_ticket')", id="nested-underscore"),
        pytest.param("@router.post('/{item_id}/notes/new/')", id="trailing-slash"),
        pytest.param("@router.post(\n    '/tickets/create',\n    status_code=201,\n)", id="multiline"),
        pytest.param("@router.api_route('/create', methods=['POST'])", id="api-route"),
        pytest.param("@router.post(path='/create')", id="path-keyword"),
    ],
)
def test_reports_create_segment_on_post(decorator: str) -> None:
    assert _lines(decorator) == [5]


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@router.post('/webhooks/new-relic')", id="vendor-name"),
        pytest.param("@router.post('/billing/add-ons')", id="add-ons-noun"),
    ],
)
def test_allows_nouns_that_start_with_a_create_word(decorator: str) -> None:
    assert _lines(decorator) == []


@pytest.mark.parametrize(
    "decorator",
    [
        pytest.param("@router.post('')", id="collection-root"),
        pytest.param("@router.post('/addresses')", id="word-prefix-only"),
        pytest.param("@router.post('/create/{draft_id}')", id="final-parameter"),
        pytest.param("@router.get('/new')", id="get-route"),
        pytest.param("@router.put('/create')", id="put-route"),
        pytest.param("@router.post(PATH)", id="dynamic-path"),
        pytest.param("@other.post('/create')", id="unknown-receiver"),
    ],
)
def test_allows_collection_paths(decorator: str) -> None:
    assert _lines(decorator) == []


def test_skips_test_modules() -> None:
    assert _lines("@router.post('/create')", path="tests/test_api.py") == []


def test_resource_path_policy_blocks_cli_and_retains_external_rpc_exception(tmp_path: Path) -> None:
    path = tmp_path / "api.py"
    body = "\nasync def handler() -> None:\n    return None\n"
    path.write_text(f"{_HEADER}@router.post('/tickets/create'){body}")
    arguments = ["check", "--rule", NoCreateVerbInPostPath.id, str(path)]
    baseline = tmp_path / "baseline.json"

    assert [finding.severity for finding in analyze([NoCreateVerbInPostPath.id], [path])] == [Severity.ERROR]
    assert main(arguments) == 1
    assert main([*arguments, "--update-baseline", str(baseline)]) == 0
    assert main([*arguments, "--baseline", str(baseline)]) == 0
    path.write_text(
        f"{_HEADER}@router.post('/tickets/create')  "
        f"# sarj-noqa: SARJ500 -- Preserve the partner's published RPC path.{body}"
    )
    assert main(arguments) == 0


@pytest.mark.parametrize(
    "source",
    [
        "class FastAPI:\n    def post(self, path): ...\nrouter = FastAPI()\n",
        "from fastapi import APIRouter\nrouter = APIRouter()\nrouter = unknown_router()\n",
    ],
)
def test_unproven_or_reassigned_receivers_are_not_resource_path_evidence(source: str) -> None:
    source += "@router.post('/create')\nasync def handler(): pass\n"
    assert NoCreateVerbInPostPath().check(Path("api.py"), source) == []
