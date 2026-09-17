from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.prefer_collection_comprehension import PreferCollectionComprehension


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/service.py") -> list[Diagnostic]:
    return PreferCollectionComprehension().check(Path(path), source)


_PUBLIC_EXAMPLES = PreferCollectionComprehension.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def test_flags_each_upstream_gap_once() -> None:
    source = """def build_caps(rows):
    caps: dict[str, int] = {}
    for row in rows:
        caps[row.organization_id] = row.organization_cap
    return caps

def build_pairs(rows):
    pairs = []
    for key, value in rows:
        pairs.append((key, value))
    return pairs

def build_active(rows):
    active = set()
    for item in rows:
        if item.active:
            active.add(item.organization_id)
    return active
"""

    findings = _check(source)

    assert [(finding.line, finding.code, finding.severity) for finding in findings] == [
        (3, "SARJ430", Severity.ERROR),
        (9, "SARJ430", Severity.ERROR),
        (15, "SARJ430", Severity.ERROR),
    ]


def test_flags_filtered_destructured_list_builders() -> None:
    source = """def build_positive(rows):
    result: list[tuple[str, int]] = []
    for key, value in rows:
        if value > 0:
            result.append((key, value))
    return result

def build_guarded(rows):
    result: list[tuple[str, int]] = []
    for key, value in rows:
        if value <= 0:
            continue
        result.append((key, value))
    return result
"""

    findings = _check(source)

    assert [(finding.line, finding.message) for finding in findings] == [
        (3, "This loop only filters and appends to fresh list 'result' — prefer a filtered list comprehension."),
        (10, "This loop only filters and appends to fresh list 'result' — prefer a filtered list comprehension."),
    ]


def test_flags_single_computed_candidate_list_builders() -> None:
    source = """def build_positive(values):
    result: list[Parsed] = []
    for value in values:
        parsed = parse(value)
        if parsed is not None:
            result.append(Parsed(parsed))
    return result

def build_guarded(values):
    result: list[Parsed] = []
    for value in values:
        parsed = parse(value)
        if parsed is None:
            continue
        result.append(parsed.value)
    return result
"""

    findings = _check(source)

    assert [(finding.line, finding.message) for finding in findings] == [
        (
            3,
            (
                "This loop only computes, filters, and appends to fresh list 'result' — "
                "prefer a filtered list comprehension."
            ),
        ),
        (
            11,
            (
                "This loop only computes, filters, and appends to fresh list 'result' — "
                "prefer a filtered list comprehension."
            ),
        ),
    ]


@pytest.mark.parametrize(
    "source",
    [
        "def build(rows):\n    result = {}\n    for key, value in rows:\n        result[key] = value\n    return result\n",
        "def build(rows):\n    result = []\n    for row in rows:\n        result.append(row.value)\n    return result\n",
        (
            "def build(comments):\n"
            "    result: list[Diagnostic] = []\n"
            "    for comment in comments:\n"
            "        if issue := suppression_issue(comment):\n"
            "            result.append(Diagnostic(issue))\n"
            "    result.sort(key=lambda diagnostic: diagnostic.line)\n"
            "    return result\n"
        ),
        (
            "def build(rows):\n"
            "    result: list[str] = []\n"
            "    for row in rows:\n"
            "        if row.active:\n"
            "            result.append(row.value)\n"
            "    return result\n"
        ),
        "def build(rows):\n    result = set()\n    for row in rows:\n        result.add(row.value)\n    return result\n",
    ],
)
def test_defers_shapes_owned_by_ruff(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "caps = {}\nfor row in rows:\n    caps[row.id] = row.cap\n",
        "class Caps:\n    caps = {}\n    for row in rows:\n        caps[row.id] = row.cap\n",
        "def build(rows):\n    caps = existing\n    for row in rows:\n        caps[row.id] = row.cap\n",
        "def build(rows):\n    caps = {'default': 1}\n    for row in rows:\n        caps[row.id] = row.cap\n",
        "def build(rows):\n    caps = {}\n    prepare()\n    for row in rows:\n        caps[row.id] = row.cap\n",
        "def build(rows):\n    caps = {}\n    for row in rows:\n        caps[row.id] = row.cap\n        audit(row)\n",
        "def build(rows):\n    caps = {}\n    for row in rows:\n        caps[row.id] = row.cap\n    else:\n        finish()\n",
        "async def build(rows):\n    caps = {}\n    async for row in rows:\n        caps[row.id] = row.cap\n",
        "def build(rows):\n    caps = {}\n    try:\n        for row in rows:\n            caps[row.id] = row.cap\n    except ValueError:\n        return caps\n",
        "def build(rows):\n    caps = {}\n    for row in caps:\n        caps[row.id] = row.cap\n",
        "def build(rows):\n    caps = {}\n    for row in rows:\n        caps[row.id] = caps.get(row.id, 0)\n",
        "def build(rows):\n    caps = {}\n    for row in rows:\n        caps[normalize(row.id)] = row.cap\n",
        "def build(rows):\n    row = rows[0]\n    caps = {}\n    for row in rows:\n        caps[row.id] = row.cap\n",
        "def build(rows):\n    caps = {}\n    for row in rows:\n        caps[row.id] = row.cap\n    return row\n",
        "def build(rows):\n    caps = {}  # retained for incremental inspection\n    for row in rows:\n        caps[row.id] = row.cap\n",
        "def build(rows):\n    caps = {}\n    for row in rows:  # noqa: PERF403\n        caps[row.id] = row.cap\n",
        "def build(rows):\n    set = custom_set\n    active = set()\n    for row in rows:\n        if row.active:\n            active.add(row.id)\n",
        "row = None\ndef build(rows):\n    global row\n    caps = {}\n    for row in rows:\n        caps[row.id] = row.cap\n",
        "def outer(rows):\n    row = None\n    def build():\n        nonlocal row\n        caps = {}\n        for row in rows:\n            caps[row.id] = row.cap\n",
        "def build(rows):\n    caps = {}\n    for row in rows:\n        caps[row.id] = row.cap\n    del row\n    return caps\n",
        "def build(rows):\n    def last_row():\n        return row\n    caps = {}\n    for row in rows:\n        caps[row.id] = row.cap\n    return caps, last_row\n",
        "def build(rows):\n    caps = {}\n    for row in (selected := rows):\n        caps[row.id] = row.cap\n",
        "def outer(set, rows):\n    def build():\n        active = set()\n        for row in rows:\n            if row.active:\n                active.add(row.id)\n",
        "from contextlib import suppress\ndef build(rows):\n    with suppress(AttributeError):\n        caps = {}\n        for row in rows:\n            caps[row.id] = row.cap\n    return caps\n",
        "def build(value, rows):\n    match value:\n        case {'factory': set}:\n            active = set()\n            for row in rows:\n                if row.active:\n                    active.add(row.id)\n",
        "def build(rows):\n    try:\n        load()\n    except Error as set:\n        active = set()\n        for row in rows:\n            if row.active:\n                active.add(row.id)\n",
        (
            "def reasons(integration, endpoints, actions):\n"
            "    result = []\n"
            "    result.extend(integration_reasons(integration))\n"
            "    result.extend(endpoint_reasons(endpoints))\n"
            "    result.extend(action_reasons(actions, endpoints))\n"
            "    return result\n"
        ),
    ],
)
def test_excludes_non_equivalent_or_less_readable_forms(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "body",
    [
        "first = parse(value)\n        second = normalize(first)\n        if second:\n            result.append(second)",
        "candidate: Parsed = parse(value)\n        if candidate:\n            result.append(candidate)",
        "holder.candidate = parse(value)\n        if holder.candidate:\n            result.append(holder.candidate)",
        "candidate = parse(value)\n        if candidate and candidate.enabled:\n            result.append(candidate)",
        "candidate = parse(value)\n        if candidate:\n            result.append(value)",
        "candidate = parse(value)\n        if candidate:\n            result.append(candidate)\n        audit(candidate)",
        "candidate = parse(value)\n        if candidate:\n            result.append(candidate)\n        else:\n            reject(value)",
        "candidate = parse(value)\n        if candidate is None:\n            continue\n        audit(candidate)\n        result.append(candidate)",
        "candidate = parse(value)\n        if candidate is None:\n            continue\n        result.extend(candidate)",
        "candidate = [part for part in value]\n        if candidate:\n            result.append(candidate)",
        "candidate = parse(result, value)\n        if candidate:\n            result.append(candidate)",
    ],
)
def test_excludes_unsafe_or_dense_computed_candidate_forms(body: str) -> None:
    source = f"def build(values):\n    result = []\n    for value in values:\n        {body}\n    return result\n"

    assert _check(source) == []


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("    candidate = existing\n", ""),
        ("", "    return result, candidate\n"),
    ],
)
def test_excludes_observable_computed_candidate_binding(before: str, after: str) -> None:
    source = (
        "def build(values):\n"
        f"{before}"
        "    result = []\n"
        "    for value in values:\n"
        "        candidate = parse(value)\n"
        "        if candidate is not None:\n"
        "            result.append(candidate)\n"
        f"{after or '    return result\n'}"
    )

    assert _check(source) == []


def test_exact_suppression_is_local() -> None:
    source = """def build(rows):
    first = {}
    for row in rows:  # sarj-noqa: SARJ430 — incremental form is intentionally inspected
        first[row.id] = row.cap

    second = {}
    for item in rows:
        second[item.id] = item.cap

    return first, second
"""

    assert [(finding.line, finding.code) for finding in _check(source)] == [(7, "SARJ430")]


def test_filtered_list_suppression_is_local() -> None:
    source = """def build_first(values):
    first = []
    for value in values:  # sarj-noqa: SARJ430 — incremental form is intentionally inspected
        candidate = parse(value)
        if candidate is not None:
            first.append(candidate)
    return first

def build_second(values):
    second = []
    for value in values:
        candidate = parse(value)
        if candidate is not None:
            second.append(candidate)
    return second
"""

    assert [(finding.line, finding.code) for finding in _check(source)] == [(11, "SARJ430")]


def test_skips_malformed_and_generated_sources() -> None:
    assert _check("def broken(:\n") == []
    assert (
        _check("# @generated\ndef build(rows):\n    caps = {}\n    for row in rows:\n        caps[row.id] = row.cap\n")
        == []
    )


def test_replacement_width_gate_is_bounded() -> None:
    source = """def build(rows_with_a_deliberately_long_and_specific_name):
    organization_capacities_by_identifier: dict[str, int] = {}
    for dispatchable_organization_capacity_row in rows_with_a_deliberately_long_and_specific_name:
        organization_capacities_by_identifier[dispatchable_organization_capacity_row.organization_identifier] = dispatchable_organization_capacity_row.organization_capacity
    return organization_capacities_by_identifier
"""

    assert _check(source) == []


def test_filtered_replacement_width_gate_is_bounded() -> None:
    source = """def build(rows_with_a_deliberately_long_and_specific_name):
    projected_dispatchable_organization_capacity_rows: list[OrganizationCapacity] = []
    for dispatchable_organization_capacity_row in rows_with_a_deliberately_long_and_specific_name:
        projected_organization_capacity = dispatchable_organization_capacity_row.to_organization_capacity()
        if projected_organization_capacity is not None:
            projected_dispatchable_organization_capacity_rows.append(projected_organization_capacity)
    return projected_dispatchable_organization_capacity_rows
"""

    assert _check(source) == []
