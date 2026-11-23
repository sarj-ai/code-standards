from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.server_proxied_file_upload import ServerProxiedFileUpload


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_ROUTER = "from typing import Annotated\nfrom fastapi import APIRouter, File, UploadFile\nrouter = APIRouter()\n"


def _check(source: str, path: str = "app/routes.py") -> list[Diagnostic]:
    return ServerProxiedFileUpload().check(Path(path), source)


def test_documented_examples() -> None:
    verify_native_rule(ServerProxiedFileUpload, analyze)


@pytest.mark.parametrize(
    "parameters",
    [
        "file: UploadFile | None = None",
        "files: list[UploadFile]",
        "*, file: Annotated[UploadFile, File(description='document')]",
        "content: bytes = File()",
        "file: 'UploadFile'",
    ],
)
def test_route_parameters_that_receive_file_bytes(parameters: str) -> None:
    [finding] = _check(_ROUTER + f"@router.post('/files')\ndef upload({parameters}): ...\n")

    assert (finding.code, finding.line, finding.severity) == ("SARJ593", 5, Severity.WARNING)
    assert "pre-signed upload URL" in finding.message


def test_qualified_and_aliased_imports_are_resolved() -> None:
    source = (
        "import fastapi\nfrom starlette.datastructures import UploadFile as Incoming\nrouter = fastapi.APIRouter()\n"
        "@router.put('/a')\ndef a(file: fastapi.UploadFile): ...\n"
        "@router.put('/b')\ndef b(file: Incoming): ...\n"
    )

    assert [finding.line for finding in _check(source)] == [5, 7]


@pytest.mark.parametrize(
    "source",
    [
        _ROUTER + "@router.post('/files')\ndef create(upload_id: str): ...\n",
        _ROUTER + "async def read(file: UploadFile) -> bytes: ...\n",
        (
            "from fastapi import APIRouter\nclass UploadFile: ...\nrouter = APIRouter()\n"
            "@router.post('/files')\ndef create(file: UploadFile): ...\n"
        ),
        (
            "from fastapi import APIRouter\nfrom forms import File\nrouter = APIRouter()\n"
            "@router.post('/files')\ndef create(content: bytes = File()): ...\n"
        ),
    ],
    ids=["upload-id-only", "non-route-helper", "local-same-name-class", "non-fastapi-file-marker"],
)
def test_near_misses_are_not_reported(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("path", ["tests/test_routes.py", "generated/routes.py"])
def test_tests_and_generated_code_are_excluded(path: str) -> None:
    assert _check(_ROUTER + "@router.post('/files')\ndef upload(file: UploadFile): ...\n", path) == []
