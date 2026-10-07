from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.prefer_collection_comprehension import PreferCollectionComprehension


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/service.py") -> list[Diagnostic]:
    return PreferCollectionComprehension().check(Path(path), source)


@pytest.mark.parametrize("local_import", [False, True])
@pytest.mark.parametrize(
    ("import_statement", "frame"),
    [
        ("import inspect", "inspect.currentframe()"),
        ("import inspect as frames", "frames.currentframe()"),
        ("from inspect import currentframe", "currentframe()"),
        ("from inspect import currentframe as frame", "frame()"),
        ("import sys", "sys._getframe()"),
        ("import sys as frames", "frames._getframe()"),
        ("from sys import _getframe", "_getframe()"),
        ("from sys import _getframe as frame", "frame()"),
    ],
)
def test_keeps_builders_when_explicit_frame_access_can_observe_loop_bindings(
    import_statement: str, frame: str, *, local_import: bool
) -> None:
    import_source = f"    {import_statement}\n" if local_import else ""
    source = (
        ("" if local_import else f"{import_statement}\n")
        + "def build(rows):\n"
        + import_source
        + "    result = {}\n"
        + "    for row in rows:\n"
        + "        result[row.id] = row.value\n"
        + f"    return result, {frame}.f_locals\n"
    )

    assert _check(source) == []


@pytest.mark.parametrize(
    ("imports", "expression"),
    [
        ("", "currentframe()"),
        ("", "_getframe()"),
        ("", "provider.currentframe()"),
        ("import providers as inspect\n", "inspect.currentframe()"),
        ("from providers import currentframe\n", "currentframe()"),
        ("import inspect\n", "provider.currentframe()"),
        ("import sys\n", "provider._getframe()"),
    ],
)
def test_unrelated_frame_names_do_not_hide_builder_findings(imports: str, expression: str) -> None:
    source = (
        imports
        + "def build(rows, provider):\n"
        + f"    observation = {expression}\n"
        + "    result = {}\n"
        + "    for row in rows:\n"
        + "        result[row.id] = row.value\n"
        + "    return result, observation\n"
    )

    assert len(_check(source)) == 1


def test_frame_import_aliases_remain_conservative_when_reused_in_other_scopes() -> None:
    source = """def inspect_rows(rows):
    import inspect as tools
    result = {}
    for row in rows:
        result[row.id] = row.value
    return result, tools.currentframe().f_locals

def sys_rows(rows):
    import sys as tools
    result = {}
    for row in rows:
        result[row.id] = row.value
    return result, tools._getframe().f_locals

def unrelated():
    import builtins as tools
    return tools.locals()
"""

    assert _check(source) == []


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


def test_flags_multiline_dictionary_constructor_projection() -> None:
    source = """def views(rows, counts, states, names, empty):
    ids = [row.id for row in rows]
    result: dict[str, EntryView] = {}
    for row in rows:
        result[row.id] = EntryView(
            history=counts.get(row.phone, empty) if row.phone is not None else empty,
            name=names.get(row.id),
            flags=states.result()[row.id] if states is not None else [],
            active=row.id in states.result(),
        )
    return result
"""
    findings = _check(source)
    assert [(finding.code, finding.line) for finding in findings] == [("SARJ430", 4)]


@pytest.mark.parametrize(
    "value",
    ["Entry(row.id)", "views.Entry(id=row.id, name=names.get(row.id))"],
)
def test_flags_dictionary_constructor_values(value: str) -> None:
    source = f"def views(rows, names):\n    result = {{}}\n    for row in rows:\n        result[row.id] = {value}\n    return result\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "value",
    [
        "Entry(raw=result)",
        "Entry(raw=await load(row))",
        "Entry(raw=(value := row.value))",
        "Entry(raw=[part for part in row.parts])",
        "Entry(raw=lambda: row.value)",
        "Entry(*row.parts)",
        "Entry(**row.fields)",
        "Entry(raw=merge(*row.parts))",
        "Entry(raw=merge(**row.fields))",
        "make_factory()(row)",
    ],
)
def test_excludes_unsafe_dictionary_constructor_values(value: str) -> None:
    source = f"async def views(rows):\n    result = {{}}\n    for row in rows:\n        result[row.id] = {value}\n    return result\n"
    assert _check(source) == []


def test_constructor_comprehension_is_already_compliant() -> None:
    source = "def views(rows, names):\n    return {row.id: Entry(id=row.id, name=names.get(row.id)) for row in rows}\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "projection",
    [
        "[row.id for row in rows]",
        "{row.id for row in rows}",
        "{row.id: row.value for row in rows}",
        "(row.id for row in rows)",
    ],
)
@pytest.mark.parametrize("placement", ["before", "after"])
def test_comprehension_local_names_do_not_leak(projection: str, placement: str) -> None:
    statement = f"    ids = {projection}\n"
    before = statement if placement == "before" else ""
    after = statement if placement == "after" else ""
    source = f"def views(rows):\n{before}    result = {{}}\n    for row in rows:\n        result[row.id] = Entry(row.id)\n{after}    return result\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "projection",
    [
        "[row.id for row in row]",
        "[value for value in row]",
        "[value for value in rows if (row := value)]",
        "[row.id for other in rows]",
        "[row.id for other in rows for row in row]",
        "[row.id for other in rows if row.active for row in other]",
    ],
)
def test_comprehension_outer_reads_and_walrus_bindings_remain_observable(projection: str) -> None:
    source = f"def views(rows):\n    ids = {projection}\n    result = {{}}\n    for row in rows:\n        result[row.id] = Entry(row.id)\n    return result\n"
    assert _check(source) == []


@pytest.mark.parametrize("observer", ["locals().get('row')", "vars().get('row')", "eval('row')"])
def test_excludes_observed_local_namespace(observer: str) -> None:
    source = f"def build(rows):\n    result = {{}}\n    for row in rows:\n        result[row.id] = Entry(row.id)\n    return result, {observer}\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "constructor", ["def Entry(value):\n        return len(result)", "Entry = lambda value: len(result)"]
)
def test_excludes_constructor_capturing_destination(constructor: str) -> None:
    source = f"def build(rows):\n    {constructor}\n    result = {{}}\n    for row in rows:\n        result[row.id] = Entry(row)\n    return result\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "statement",
    [
        "result[row.id] = {expression}",
        "result[{expression}] = Entry(row.id)",
        "result[row.id] = Entry(raw={expression})",
    ],
)
def test_deep_projection_does_not_crash(statement: str) -> None:
    expression = "row" + ".value" * 500
    source = f"def build(rows):\n    result = {{}}\n    for row in rows:\n        {statement.format(expression=expression)}\n    return result\n"
    assert _check(source) == []


@pytest.mark.parametrize("placement", ["before", "after"])
def test_first_generator_binding_stays_local_in_later_generators(placement: str) -> None:
    statement = "    ids = [row.id for row in rows for tag in row.tags]\n"
    before = statement if placement == "before" else ""
    after = statement if placement == "after" else ""
    source = f"def build(rows):\n{before}    result = {{}}\n    for row in rows:\n        result[row.id] = Entry(row.id)\n{after}    return result\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "value",
    [
        "Entry(row.id)",
        "Entry(first=row.id, second=row.name, third=row.phone, fourth=row.cap, fifth=row.active, sixth=row.status)",
    ],
)
def test_conditional_iterable_serializes_as_valid_comprehension(value: str) -> None:
    source = f"def build(rows, others, flag):\n    result = {{}}\n    for row in (rows if flag else others):\n        result[row.id] = {value}\n    return result\n"
    assert len(_check(source)) == 1


@pytest.mark.parametrize("value", ["row.value", "Entry(row.value)"])
@pytest.mark.parametrize(
    "body",
    [
        "if row.active:\n            result[row.id] = {value}",
        "if not row.active:\n            continue\n        result[row.id] = {value}",
    ],
    ids=["if", "continue"],
)
def test_flags_filtered_dictionary_projections(value: str, body: str) -> None:
    source = f"def build(rows):\n    result = {{}}\n    for row in rows:\n        {body.format(value=value)}\n    return result\n"

    assert [(finding.line, finding.message) for finding in _check(source)] == [
        (3, "This loop only filters and populates fresh dict 'result' — prefer a filtered dict comprehension."),
    ]


def test_flags_filtered_set_continue_guard() -> None:
    source = """def build(rows):
    result = set()
    for row in rows:
        if not row.active:
            continue
        result.add(row.id)
    return result
"""

    assert [(finding.line, finding.code) for finding in _check(source)] == [(3, "SARJ430")]


@pytest.mark.parametrize(
    "body",
    [
        "if result.get(row.id):\n            result[row.id] = Entry(row)",
        "if enabled := row.active:\n            result[row.id] = Entry(row)",
        "if row.active:\n            result[row.id] = Entry(row)\n        else:\n            audit(row)",
        "if not row.active:\n            audit(row)\n            continue\n        result[row.id] = Entry(row)",
        "if not row.active:\n            continue\n        if row.valid:\n            result[row.id] = Entry(row)",
    ],
)
def test_excludes_filtered_dictionary_guards_with_additional_behavior(body: str) -> None:
    source = f"def build(rows):\n    result = {{}}\n    for row in rows:\n        {body}\n    return result\n"

    assert _check(source) == []


def test_filtered_constructor_width_gate_includes_guard() -> None:
    guard = "row." + "requires_a_deliberately_oversized_guard_" * 4
    source = (
        "def build(rows):\n"
        "    result = {}\n"
        "    for row in rows:\n"
        f"        if {guard}:\n"
        "            result[row.id] = Entry(first=row.value, second=row.id, third=row.active, fourth=row.valid)\n"
        "    return result\n"
    )

    assert _check(source) == []


@pytest.mark.parametrize(
    ("imports", "observer"),
    [
        ("from builtins import locals as snapshot", "snapshot()"),
        ("from builtins import vars as snapshot", "snapshot()"),
        ("from builtins import eval as evaluate", "evaluate('row')"),
        ("import builtins", "builtins.locals()"),
        ("import builtins as runtime", "runtime.vars()"),
    ],
    ids=["aliased-locals", "aliased-vars", "aliased-eval", "qualified-locals", "aliased-module-vars"],
)
def test_excludes_aliased_and_qualified_namespace_observers(imports: str, observer: str) -> None:
    source = (
        f"{imports}\n"
        "def build(rows):\n"
        "    result = {}\n"
        "    for row in rows:\n"
        "        result[row.id] = Entry(row.id)\n"
        f"    return result, {observer}\n"
    )

    assert _check(source) == []


@pytest.mark.parametrize(
    ("imports", "observer"),
    [
        ("from builtins import locals as snapshot", "snapshot()"),
        ("import builtins as runtime", "runtime.locals()"),
    ],
    ids=["local-symbol-alias", "local-module-alias"],
)
def test_excludes_function_local_namespace_imports(imports: str, observer: str) -> None:
    source = (
        "def build(rows):\n"
        f"    {imports}\n"
        "    result = {}\n"
        "    for row in rows:\n"
        "        result[row.id] = Entry(row.id)\n"
        f"    return result, {observer}\n"
    )

    assert _check(source) == []


def test_unrelated_parameter_shadow_does_not_hide_namespace_alias() -> None:
    source = """from builtins import locals as snapshot
def unrelated(snapshot):
    return snapshot()

def build(rows):
    result = {}
    for row in rows:
        result[row.id] = Entry(row.id)
    return result, snapshot()
"""

    assert _check(source) == []


@pytest.mark.parametrize(
    ("initializer", "target", "body"),
    [
        ("{}", "row", "if row.active if flag else row.valid:\n            result[row.id] = Entry(row.value)"),
        (
            "{}",
            "row",
            "if row.active if flag else row.valid:\n            continue\n        result[row.id] = row.value",
        ),
        ("[]", "key, value", "if key if flag else value:\n            result.append((key, value))"),
        ("[]", "key, value", "if key if flag else value:\n            continue\n        result.append((key, value))"),
        ("set()", "row", "if row.active if flag else row.valid:\n            result.add(row.id)"),
        ("set()", "row", "if row.active if flag else row.valid:\n            continue\n        result.add(row.id)"),
    ],
    ids=["dict-if", "dict-continue", "list-if", "list-continue", "set-if", "set-continue"],
)
def test_conditional_filters_and_iterables_serialize_as_valid_comprehensions(
    initializer: str, target: str, body: str
) -> None:
    source = (
        "def build(rows, others, flag):\n"
        f"    result = {initializer}\n"
        f"    for {target} in (rows if flag else others):\n"
        f"        {body}\n"
        "    return result\n"
    )

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("values", "expected"),
    [([], []), ([None, 0, False, 2], [0, False, 2]), ([3, 3, 3], [3, 3, 3])],
    ids=["empty", "none-versus-falsy", "duplicates"],
)
def test_computed_none_filter_preserves_values_and_single_evaluation(
    values: list[int | None], expected: list[int]
) -> None:
    source = """def build(values):
    result = []
    for value in values:
        candidate = parse(value)
        if candidate is not None:
            result.append(candidate)
    return result
"""
    replacement = (
        "def build(values):\n    return [candidate for value in values if (candidate := parse(value)) is not None]\n"
    )
    assert len(_check(source)) == 1
    assert _check(replacement) == []
    calls: list[int | None] = []

    def parse(value: int | None) -> int | None:
        calls.append(value)
        return value

    for implementation in (source, replacement):
        calls.clear()
        namespace: dict[str, object] = {"values": values, "expected": expected, "parse": parse}
        executable = implementation + "\nassert build(values) == expected\n"
        exec(compile(executable, "<semantic-fixture>", "exec"), namespace)  # ruff: ignore[exec-builtin] -- execute authored semantic fixtures without external inputs.
        assert calls == values


@pytest.mark.parametrize("rows", [[], [(1, 5), (1, 8)]], ids=["empty", "duplicate-keys"])
def test_constructor_dictionary_preserves_empty_inputs_and_duplicate_keys(rows: list[tuple[int, int]]) -> None:
    source = """def build(rows):
    result = {}
    for key, value in rows:
        result[key] = Entry(value)
    return result
"""
    replacement = "def build(rows):\n    return {key: Entry(value) for key, value in rows}\n"
    assert len(_check(source)) == 1
    assert _check(replacement) == []
    for implementation in (source, replacement):
        namespace: dict[str, object] = {"rows": rows}
        executable = "def Entry(value):\n    return value\n" + implementation
        executable += "\nassert build(rows) == dict(rows)\n"
        exec(compile(executable, "<semantic-fixture>", "exec"), namespace)  # ruff: ignore[exec-builtin] -- execute authored semantic fixtures without external inputs.


def test_dictionary_evaluation_order_requires_manual_review() -> None:
    source = """def build(rows):
    result = {}
    for row in rows:
        result[row.id] = Entry(row)
    return result
"""
    replacement = "def build(rows):\n    return {row.id: Entry(row) for row in rows}\n"
    assert len(_check(source)) == 1
    assert _check(replacement) == []
    documentation = PreferCollectionComprehension.documentation
    assert documentation is not None
    assert documentation.autofix is AutofixPolicy.NONE
    for implementation, expected in ((source, {2: 2}), (replacement, {1: 2})):
        executable = (
            "from types import SimpleNamespace\n"
            "def Entry(row):\n"
            "    row.id += 1\n"
            "    return row.id\n"
            f"{implementation}\n"
            "assert build([SimpleNamespace(id=1)]) == expected\n"
        )
        exec(compile(executable, "<evaluation-order-fixture>", "exec"), {"expected": expected})  # ruff: ignore[exec-builtin] -- prove the documented no-autofix evaluation-order boundary.
