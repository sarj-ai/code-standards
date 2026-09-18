from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_nominal_id_types import PreferNominalIdTypes


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/services/files.py") -> list[Diagnostic]:
    return PreferNominalIdTypes().check(Path(path), source)


@pytest.mark.parametrize(
    "example",
    PreferNominalIdTypes.public_examples(),
    ids=[example.example_id for example in PreferNominalIdTypes.public_examples()],
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_file.path))) == example.expected_count


@pytest.mark.parametrize(
    ("source", "path"),
    [
        ("def move(file_id: str, folder_id: str) -> None: ...\n", "app/service.py"),
        ("def _move(file_id: str, folder_id: str) -> None: ...\n", "app/service.py"),
        ("@app.post('/')\ndef move(file_id: str, folder_id: str) -> None: ...\n", "app/routes.py"),
        (
            "from typing import override\nclass Store:\n    @override\n    def put(self, session_id: str, scenario_id: str) -> None: ...\n",
            "tests/fakes/store.py",
        ),
        ("class _Pair:\n    left_id: str\n    right_id: str\n", "tests/fakes/models.py"),
    ],
)
def test_flags_swappable_ids_in_private_decorated_and_test_boundaries(source: str, path: str) -> None:
    findings = _check(source, path)

    assert len(findings) == 1
    assert findings[0].code == "SARJ093"
    assert findings[0].severity is Severity.ERROR


@pytest.mark.parametrize(
    "source",
    [
        "def load(file_id: str) -> None: ...\n",
        "def load(file_id: str, shard_id: int) -> None: ...\n",
        "from typing import NewType\nFileId = NewType('FileId', str)\nFolderId = NewType('FolderId', str)\ndef load(file_id: FileId, folder_id: FolderId) -> None: ...\n",
        "def load(request_id: str, file_id: str) -> None: ...\n",
        "from sqlalchemy.orm import Mapped\nclass Row:\n    file_id: Mapped[str]\n    folder_id: Mapped[str]\n",
        "from pydantic import BaseModel, Field\nclass Wire(BaseModel):\n    file_id: str = Field(alias='fileId')\n    folder_id: str = Field(alias='folderId')\n",
    ],
)
def test_allows_distinct_nominal_operational_and_wire_ids(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    ["app/generated/client.py", "app/migrations/versions/001.py", "app/providers/github/client.py"],
)
def test_skips_generated_migrations_and_external_adapters(path: str) -> None:
    assert _check("def move(file_id: str, folder_id: str) -> None: ...\n", path) == []


def test_exact_suppression_is_recognized() -> None:
    source = (
        "def bridge(\n"
        "    legacy_id: str,  # sarj-noqa: SARJ093 — provider contract is raw\n"
        "    file_id: str,\n"
        ") -> None: ...\n"
    )
    assert _check(source) == []


def test_invalid_source_is_ignored() -> None:
    assert _check("def broken( -> None:\n") == []
