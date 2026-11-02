from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.prefer_validated_uuid_comparison import PreferValidatedUuidComparison


P = Path("app/router.py")


def test_documented_examples() -> None:
    verify_native_rule(PreferValidatedUuidComparison, analyze)


@pytest.mark.parametrize("factory", ["UUID", "NativeId", "uuid.UUID"])
@pytest.mark.parametrize("operator", ["==", "!="])
def test_inline_uuid_normalization_of_both_comparison_operands(factory: str, operator: str) -> None:
    source = f"import uuid\nfrom uuid import UUID, UUID as NativeId\ndef transfer(item, request):\n    return {factory}(item.owner_id) {operator} {factory}(request.owner_id)\n"
    [finding] = PreferValidatedUuidComparison().check(P, source)
    assert finding.code == "SARJ562"
    assert finding.line == 4
    assert "boundary" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        "from uuid import UUID\ndef parse(value: str): return UUID(value)\n",
        "from uuid import UUID\ndef compare(a: UUID, b: UUID): return a == b\n",
        "from uuid import UUID\ndef compare(value): return value == UUID('00000000-0000-0000-0000-000000000001')\n",
        "from uuid import UUID\ndef compare(UUID, a, b): return UUID(a) == UUID(b)\n",
        "from local import UUID\ndef compare(a, b): return UUID(a) == UUID(b)\n",
        "from uuid import UUID\ndef compare(a, b): return UUID(a).hex == UUID(b).hex\n",
    ],
)
def test_parsing_typed_comparisons_and_unknown_factories_remain_valid(source: str) -> None:
    assert PreferValidatedUuidComparison().check(P, source) == []


def test_suppression_generated_and_malformed_source() -> None:
    source = "from uuid import UUID\ndef compare(a, b):\n    return UUID(a) == UUID(b)  # sarj-noqa: SARJ562 -- ingestion compares wire encodings before normalization\n"
    assert PreferValidatedUuidComparison().check(P, source) == []
    assert PreferValidatedUuidComparison().check(P, "# Code generated. DO NOT EDIT.\n" + source) == []
    assert PreferValidatedUuidComparison().check(P, "def (") == []
