"""SARJ205 — every guard pinned in both directions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sarj_iac_lint.rules.no_deployed_state_snapshot_test import NoDeployedStateSnapshotTest


if TYPE_CHECKING:
    from sarj_iac_lint.rule_base import Diagnostic


def _check(source: str, name: str = "runtime-inventory.test.mjs") -> list[Diagnostic]:
    return NoDeployedStateSnapshotTest().check(Path(name), source)


_REAL_LINEAGE = "aefd9bf8-9adf-0071-d2b9-fb5e6592626f"


def test_flags_a_pinned_state_lineage_uuid():
    src = f'const state = {{ serial: 152, lineage: "{_REAL_LINEAGE}" }};\n'
    diags = _check(src)
    assert len(diags) == 1
    assert "lineage UUID" in diags[0].message
    assert diags[0].code == "SARJ205"


def test_flags_a_json_quoted_lineage_key():
    src = f'const state = JSON.parse(\'{{"lineage": "{_REAL_LINEAGE}"}}\');\n'
    assert len(_check(src)) == 1


def test_flags_a_lineage_assignment():
    src = f'expected.lineage = "{_REAL_LINEAGE}";\n'
    assert len(_check(src)) == 1


def test_spares_a_synthetic_lineage():
    """A fake lineage is how a fixture is supposed to be written."""
    src = 'const LINEAGE = "test-dev-lineage";\nconst state = { serial: 56, lineage: LINEAGE };\n'
    assert _check(src) == []


def test_flags_bulk_deployment_identity_literals():
    src = (
        'const repo = "me-central2-docker.pkg.dev/some-project/artifacts";\n'
        'const model = "gs://some-bucket/models/eou";\n'
        'const sa = "runtime@some-project.iam.gserviceaccount.com";\n'
        'const parent = "projects/some-project";\n'
        'const zone = "europe-west3-b";'
    )
    diags = _check(src)
    assert len(diags) == 1
    assert "5 distinct deployment-identity literals" in diags[0].message
    assert diags[0].line == 1


def test_spares_a_fixture_that_mentions_a_few_identifiers():
    """The verify-environment-boundary shape: four SA emails as fixture inputs."""
    src = (
        'const a = "terraform@dev-project.iam.gserviceaccount.com";\n'
        'const b = "terraform-plan@sarj-platform-dev.iam.gserviceaccount.com";\n'
        'const c = "dev-build-monitor@sarj-platform-dev.iam.gserviceaccount.com";\n'
        'const d = "terraform@sarj-platform-dev.iam.gserviceaccount.com";'
    )
    assert _check(src) == []


def test_a_repeated_literal_counts_once():
    src = 'const r = "me-central2-docker.pkg.dev/p/a";\n' * 20
    assert _check(src) == []


def test_a_single_region_literal_is_not_bulk_identity():
    src = 'const region = "us-east1";\nassert.equal(pick(region), "us-east1");\n'
    assert _check(src) == []


def test_serial_alone_is_not_a_signal():
    src = "const state = { serial: 148 };\nassert.equal(state.serial, 148);\n"
    assert _check(src) == []


def test_never_fires_on_the_module_under_test():
    """The module legitimately holds the pins the test must not; only tests are read."""
    src = f'export const EXPECTED = {{ lineage: "{_REAL_LINEAGE}" }};\n'
    assert _check(src, name="runtime-inventory.mjs") == []


def test_never_fires_on_non_javascript_files():
    src = f'lineage = "{_REAL_LINEAGE}"\n'
    assert _check(src, name="main.tf") == []
    assert _check(src, name="conftest.py") == []


def test_fires_on_js_and_cjs_test_files_too():
    src = f'const state = {{ lineage: "{_REAL_LINEAGE}" }};\n'
    assert len(_check(src, name="inventory.test.js")) == 1
    assert len(_check(src, name="inventory.test.cjs")) == 1


def test_reports_the_lineage_line():
    src = "\n".join(
        [
            "import test from 'node:test';",
            "",
            f'const state = {{ lineage: "{_REAL_LINEAGE}" }};',
        ]
    )
    (diag,) = _check(src)
    assert diag.line == 3


def test_one_finding_per_file_not_per_literal():
    src = "\n".join(
        [
            f'const a = {{ lineage: "{_REAL_LINEAGE}" }};',
            'const repo = "me-central2-docker.pkg.dev/p/a";',
            'const model = "gs://bucket/m";',
            'const sa = "x@p.iam.gserviceaccount.com";',
            'const parent = "projects/p";',
            'const zone = "europe-west3-b";',
        ]
    )
    assert len(_check(src)) == 1
