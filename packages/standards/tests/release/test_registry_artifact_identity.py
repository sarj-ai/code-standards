import json
from typing import Self

import pytest

from sarj_standards.libs.release import registry as registry_module
from sarj_standards.libs.release.registry import RegistryRequirement


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("public_fixture-1.2.3-py3-none-any.whl", True),
        ("Public_Fixture-1.2.3-py3-none-any.whl", True),
        ("public.fixture-1.2.3-py3-none-any.whl", True),
        ("foreign_fixture-1.2.3-py3-none-any.whl", False),
        ("public_fixture-1.2.4-py3-none-any.whl", False),
        ("public_fixture-1.2.3.tar.gz", True),
        ("Public.Fixture-1.2.3.zip", True),
        ("foreign_fixture-1.2.3.tar.gz", False),
        ("foreign_fixture-1.2.3.zip", False),
        ("public_fixture-1.2.4.tar.gz", False),
        ("invalid.whl", False),
    ],
)
def test_simple_artifact_requires_its_own_project_identity(
    monkeypatch: pytest.MonkeyPatch, filename: str, *, expected: bool
) -> None:
    class Response:
        status: int = 200

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"files": [{"filename": filename}]}).encode()

    def open_url(
        _request: object,
        *,
        timeout: int,  # ruff: ignore[unused-function-argument] -- HTTP transport fixes this keyword.
    ) -> Response:
        return Response()

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- deterministic HTTP transport preserves real Simple API parsing
        registry_module, "urlopen", open_url
    )
    assert registry_module.publication_exists(RegistryRequirement("pypi", "public-fixture", "1.2.3")) is expected
