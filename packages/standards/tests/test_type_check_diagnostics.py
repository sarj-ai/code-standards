from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from sarj_standards.libs.diagnostics import Location, Severity
from sarj_standards.libs.linting.oxlint import type_check_diagnostic
from tests.oxlint_json import OxlintReport


BINARIES = Path(__file__).resolve().parents[3] / "packages/typescript/node_modules/.bin"


def test_typescript_compiler_codes_map_to_tsc_rules() -> None:
    location = Location("src/a.ts")

    diagnostic = type_check_diagnostic(
        "typescript(TS2322)", "Type 'string' is not assignable to type 'number'.", location, help_text=None
    )

    assert diagnostic is not None
    assert (diagnostic.code, diagnostic.rule_id, diagnostic.source, diagnostic.severity) == (
        "TS2322",
        "tsc/TS2322",
        "oxlint",
        Severity.ERROR,
    )
    assert diagnostic.message == "Type 'string' is not assignable to type 'number'."
    assert diagnostic.location == location
    assert diagnostic.tags == ("type-check",)


def test_rejected_tsconfig_maps_to_tsconfig_rule_with_compiler_message() -> None:
    help_text = (
        "Option 'baseUrl' has been removed. Please remove it from your configuration.\n"
        "See https://github.com/oxc-project/tsgolint/issues/351 for more information."
    )

    diagnostic = type_check_diagnostic(
        "typescript(tsconfig-error)", "Invalid tsconfig", Location("tsconfig.json"), help_text=help_text
    )

    assert diagnostic is not None
    assert diagnostic.rule_id == "tsc/tsconfig-error"
    assert diagnostic.message == "Option 'baseUrl' has been removed. Please remove it from your configuration."
    assert diagnostic.notes


@pytest.mark.parametrize(
    "code", ["typescript(no-floating-promises)", "eslint(no-unused-vars)", "typescript(TS)", "typescript(TS0)", ""]
)
def test_lint_diagnostics_are_not_type_check_results(code: str) -> None:
    assert type_check_diagnostic(code, "message", Location("a.ts"), help_text=None) is None


@pytest.mark.skipif(
    not (BINARIES / "oxlint").is_file() or not (BINARIES / "tsrs-lint").is_file(),
    reason="the pinned oxlint and tsrs-lint are not installed",
)
def test_oxlint_type_check_reports_one_tsconfig_error_instead_of_the_rejected_projects_errors(tmp_path: Path) -> None:
    (tmp_path / ".oxlintrc.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {"strict": true}, "include": ["src"]}')
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.ts").write_text('export const a: number = "x";\n', encoding="utf-8")
    legacy = tmp_path / "legacy"
    (legacy / "src").mkdir(parents=True)
    (legacy / "tsconfig.json").write_text('{"compilerOptions": {"baseUrl": "."}, "include": ["src"]}')
    (legacy / "src/b.ts").write_text('export const b: number = "hidden";\n', encoding="utf-8")
    environment = {
        "PATH": os.environ["PATH"],  # ruff: ignore[banned-api] -- keep the runner's tool path.
        "HOME": str(tmp_path),
        "OXLINT_TSGOLINT_PATH": str(BINARIES / "tsrs-lint"),
    }

    completed = subprocess.run(
        (str(BINARIES / "oxlint"), "--type-aware", "--type-check", "-f", "json", "."),
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    mapped = {
        (item.location.path, item.rule_id)
        for raw in OxlintReport.model_validate_json(completed.stdout).diagnostics
        if (item := type_check_diagnostic(raw.code, raw.message, Location(raw.filename), help_text=raw.help))
    }
    assert completed.returncode == 1, completed.stderr
    assert mapped == {("src/a.ts", "tsc/TS2322"), ("legacy/tsconfig.json", "tsc/tsconfig-error")}
