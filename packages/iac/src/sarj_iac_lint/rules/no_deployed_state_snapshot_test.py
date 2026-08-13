"""SARJ205: IaC test files must not pin snapshots of live deployed state."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
)


if TYPE_CHECKING:
    from pathlib import Path

# A Terraform state lineage is a UUID minted when the state is first created. A
# synthetic fixture writes a fake ("test-lineage"); only a snapshot of the real,
# deployed state embeds the UUID — there is no other way to know it.
_LINEAGE_UUID = re.compile(
    r"""["']?lineage["']?\s*[:=]\s*["'][0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}["']""",
    re.IGNORECASE,
)

# Deployment-identity literals: values that name one live deployment rather than
# describe behaviour. Each is unambiguous on its own; the THRESHOLD is what
# separates a fixture that mentions one from an inventory that pins many.
_IDENTITY_PATTERNS = (
    re.compile(r'["\'][^"\']*\.pkg\.dev/[^"\']*["\']'),
    re.compile(r'["\']gs://[^"\']+["\']'),
    re.compile(r'["\'][^"\']*\.iam\.gserviceaccount\.com["\']'),
    re.compile(r'["\']projects/[^"\']+["\']'),
    re.compile(r'["\'](?:me|europe|us|asia|australia|southamerica|northamerica|africa)-[a-z]+[0-9](?:-[a-z])?["\']'),
)

_IDENTITY_THRESHOLD = 5

_TEST_SUFFIXES = (".test.mjs", ".test.js", ".test.cjs")


@final
class NoDeployedStateSnapshotTest(Rule):
    """A test whose expectations are a snapshot of live infrastructure."""

    id = "no-deployed-state-snapshot-test"
    code = "SARJ205"
    documentation = RuleDocumentation(
        summary=(
            "An IaC test must not pin live deployed state — a real state lineage or a bulk of deployment "
            "identity literals only ever gets re-pinned to match reality."
        ),
        rationale=(
            "A test that embeds the deployed state's lineage UUID, serials, or an inventory of live project, "
            "registry, and service-account names can never fail meaningfully: when infrastructure changes the "
            "test is edited to match, so its entire history is re-pinning and it guards nothing."
        ),
        remediation=(
            "Test behaviour with synthetic fixtures (a fake lineage, invented names), or delete the test — "
            "drift against live state belongs to terraform plan, not to a test that mirrors the state."
        ),
        category=RuleCategory.TESTING,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only .test.mjs/.test.js/.test.cjs files are read; the rule never fires on modules under test.",
            (
                "A fixture-style unit test that mentions a few real identifiers as inputs is deliberately "
                "spared: the threshold is five distinct identity literals, and a synthetic lineage never "
                "matches the UUID form."
            ),
            "Serial numbers alone are not a signal — `serial: 56` in a fixture and a pinned serial look identical.",
        ),
        examples=(
            RuleExample(
                example_id="pinned-state-inventory",
                title="Expectations snapshot the deployed state",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.iac(
                        "iac/dev-plan/runtime-inventory.test.mjs",
                        "const state = {\n"
                        '  lineage: "aefd9bf8-9adf-0071-d2b9-fb5e6592626f",\n'
                        "  serial: 152,\n"
                        "};\n"
                        'assert.equal(state.lineage, "aefd9bf8-9adf-0071-d2b9-fb5e6592626f");\n',
                    ),
                ),
                focus_path=PurePosixPath("iac/dev-plan/runtime-inventory.test.mjs"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="synthetic-fixture-test",
                title="Behaviour tested with a synthetic fixture",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.iac(
                        "iac/dev-plan/filter-state.test.mjs",
                        'const LINEAGE = "test-dev-lineage";\n'
                        "const state = { serial: 56, lineage: LINEAGE };\n"
                        "assert.throws(() => filterState(state, { lineage: 'other' }));\n",
                    ),
                ),
                focus_path=PurePosixPath("iac/dev-plan/filter-state.test.mjs"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag a test file that embeds a real state lineage or bulk deployment identity."""
        if not str(path).endswith(_TEST_SUFFIXES):
            return []
        if (lineage := _LINEAGE_UUID.search(source)) is not None:
            line = source.count("\n", 0, lineage.start()) + 1
            return [self._diagnostic(path, line, "embeds the deployed state's lineage UUID")]
        distinct: set[str] = set()
        first: tuple[int, str] | None = None
        for pattern in _IDENTITY_PATTERNS:
            for match in pattern.finditer(source):
                if match.group(0) not in distinct and first is None:
                    first = (source.count("\n", 0, match.start()) + 1, match.group(0))
                distinct.add(match.group(0))
        if len(distinct) < _IDENTITY_THRESHOLD or first is None:
            return []
        return [
            self._diagnostic(
                path,
                first[0],
                f"pins {len(distinct)} distinct deployment-identity literals (first: {first[1]})",
            )
        ]

    def _diagnostic(self, path: Path, line: int, detail: str) -> Diagnostic:
        return Diagnostic(
            path=path,
            line=line,
            col=1,
            code=self.code,
            message=(
                f"this test {detail} — a test that mirrors live state only ever gets re-pinned to match "
                "reality and guards nothing. Test behaviour with synthetic fixtures, or delete it; drift "
                "detection belongs to terraform plan."
            ),
        )
