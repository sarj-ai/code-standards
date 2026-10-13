from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.libs.diagnostics import Severity, baseline


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("selector", "relative", "blocking", "advisory"),
    [
        pytest.param(
            "sql:no-duplicate-index",
            "migrations/002_indexes.sql",
            "CREATE INDEX one ON event(a);\nCREATE INDEX two ON event(a);\n",
            "CREATE INDEX one ON event(a);\nCREATE INDEX two ON event(a,b);\n",
            id="exact-index-versus-prefix",
        ),
        pytest.param(
            "iac:require-deletion-protection",
            "database.tf",
            'resource "aws_db_instance" "records" { deletion_protection = false }\n',
            'resource "aws_db_instance" "records" { deletion_protection = var.protect }\n',
            id="database-literal-versus-variable",
        ),
        pytest.param(
            "iac:require-prevent-destroy-on-irreplaceable",
            "secret.tf",
            'resource "google_secret_manager_secret" "records" { deletion_protection = false }\n',
            'resource "google_secret_manager_secret" "records" { deletion_protection = var.protect }\n',
            id="secret-literal-versus-variable",
        ),
    ],
)
def test_managed_policy_preserves_native_warning_tiers(
    selector: str, relative: str, blocking: str, advisory: str, tmp_path: Path
) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    standards = api.Standards(tmp_path)
    for source, expected in ((blocking, Severity.ERROR), (advisory, Severity.WARNING)):
        path.write_text(source)
        report = standards.analyze([relative], rules=[selector], external=False, python_type_check=False)
        assert len(report.diagnostics) == 1
        assert report.diagnostics[0].severity is expected
        assert report.exit_code == (1 if expected is Severity.ERROR else 0)
        assert (
            standards.analyze([relative], rules=[selector], external=False, python_type_check=False).diagnostics
            == report.diagnostics
        )
        rendered = baseline.render(
            report.diagnostics,
            bundle_version=api.__version__,
            consumer_base_sha="0" * 40,
            catalog_digest=baseline.bundled_catalog_digest(),
        )
        assert selector.split(":", 1)[1] in rendered
        baseline_path = tmp_path / "diagnostics.json"
        baseline_path.write_text(rendered)
        assert baseline.load(baseline_path) == {report.diagnostics[0].fingerprint: 1}
