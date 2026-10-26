from __future__ import annotations

from pathlib import Path

import pytest

from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.linting.cloudbuild import CloudBuildParseError
from sarj_standards.libs.linting.text_rules.cloudbuild_contract import CloudBuildContract
from sarj_standards.libs.linting.textlint import fix_source
from sarj_standards.libs.yaml_boundary import parse_yaml_documents


_PATH = Path("cloudbuild.yaml")
_SOURCE = "steps:\n- name: builder\n  waitFor: ['-', '-']\n"
_RULE = CloudBuildContract()


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize(
    ("spellings", "expected_content"),
    [
        ("'-', '-'", "'-' "),
        ('"-", "-"', '"-" '),
        ("-, -, -", "-"),
        ("-,\n    -", "-,\n    "),
        ("'-',\n    '-',\n    '-'", "'-'\n    \n    "),
        ("'-', '-',", "'-' "),
    ],
)
def test_start_sentinel_repair_has_exact_output_and_converges(
    spellings: str, expected_content: str, ending: str
) -> None:
    source = f"label: é\nsteps:\n- name: builder\n  waitFor: [{spellings}]\n".replace("\n", ending)
    expected = f"label: é\nsteps:\n- name: builder\n  waitFor: [{expected_content}]\n".replace("\n", ending)
    assert len(_RULE.check(_PATH, source)) >= 2
    fixed = fix_source(_PATH, source, rule_ids=["cloudbuild-contract"])
    assert fixed == expected
    assert not _RULE.check(_PATH, fixed)
    assert parse_yaml_documents(fixed) == ({"label": "é", "steps": [{"name": "builder", "waitFor": ["-"]}]},)
    assert fix_source(_PATH, fixed, rule_ids=["cloudbuild-contract"]) == fixed


@pytest.mark.parametrize(
    "source",
    [
        _SOURCE.replace("'-', '-'", "'-', later"),
        _SOURCE.replace("'-', '-'", "'-'"),
        _SOURCE.replace("'-', '-'", ""),
        _SOURCE.replace("['-', '-']", "\n  - '-'\n  - '-'"),
        _SOURCE.replace("['-', '-']", "&waits ['-', '-']"),
        _SOURCE.replace("['-', '-']", "!!seq ['-', '-']"),
        _SOURCE.replace("['-', '-']", "['-', !!str '-']"),
        _SOURCE.replace("['-', '-']", '["-", "\\u002d"]'),
        _SOURCE.replace("['-', '-']", "['-', # preserve rationale\n    '-']"),
        "# Generated; DO NOT EDIT\n" + _SOURCE,
        "# sarj-noqa: SARJ315\n" + _SOURCE,
        "# SPDX-License-Identifier: MIT\n" + _SOURCE,
        "\ufeff%YAML 1.1\n---\n" + _SOURCE,
        "base: &base {name: builder}\nsteps:\n- <<: *base\n  waitFor: ['-', '-']\n",
        "steps:\n- {<<: {name: builder}, waitFor: ['-', '-']}\n",
        "waits: &waits ['-', '-']\nsteps:\n- name: builder\n  waitFor: *waits\n",
        "steps:\n- name: builder\n  id: prior\n- name: builder\n  waitFor: [prior, prior]\n",
        "payload: {waitFor: ['-', '-']}\n",
        "steps:\n- name: builder\n  args: ['-', '-']\n",
        _SOURCE + "steps: []\n",
        _SOURCE + "  waitFor: ['-']\n",
        _SOURCE.replace("['-', '-']", "['-']") + "  waitFor: ['-', '-']\n",
        _SOURCE.removesuffix("\n") + " [\n",
    ],
)
def test_uncertain_or_unreported_cloudbuild_forms_remain_unchanged(source: str) -> None:
    assert fix_source(_PATH, source, rule_ids=["cloudbuild-contract"]) == source


def test_repair_preserves_other_values_and_unrelated_native_findings() -> None:
    source = (
        "options: {automapSubstitutions: false, machineType: E2_HIGHCPU_8}\n"
        "steps:\n- name: builder\n  waitFor: ['-', '-']\n"
        "- name: builder\n  waitFor: [later]\n- name: builder\n  id: later\n"
    )
    fixed = fix_source(_PATH, source, rule_ids=["cloudbuild-contract"])
    assert fixed == source.replace("['-', '-']", "['-' ]")
    assert [finding.message for finding in _RULE.check(_PATH, fixed)] == [
        "Cloud Build waitFor 'later' does not name a prior step; order dependencies first"
    ]
    assert fix_source(_PATH, fixed, rule_ids=["cloudbuild-contract"]) == fixed


def test_multiple_documents_and_selected_sentinel_lists_are_independent() -> None:
    source = _SOURCE + "---\n" + _SOURCE.replace("['-', '-']", "\n  - '-'\n  - '-'")
    fixed = fix_source(_PATH, source, rule_ids=["cloudbuild-contract"])
    assert fixed == source.replace("['-', '-']", "['-' ]")
    assert len(_RULE.check(_PATH, fixed)) == 2
    assert fix_source(_PATH, fixed, rule_ids=["cloudbuild-contract"]) == fixed


def test_sentinel_repairs_honor_rule_selection_and_file_exclusions(tmp_path: Path) -> None:
    assert fix_source(_PATH, _SOURCE, rule_ids=[]) == _SOURCE
    assert fix_source(Path("cloudbuild.toml"), _SOURCE, rule_ids=["cloudbuild-contract"]) == _SOURCE
    path = tmp_path / "cloudbuild.yaml"
    (tmp_path / ".sarj-standards.toml").write_text('[text]\nexclude = ["cloudbuild.yaml"]\n')
    assert fix_source(path, _SOURCE, rule_ids=["cloudbuild-contract"], root=tmp_path) == _SOURCE


def test_sentinel_and_comment_fixes_share_the_normal_text_api() -> None:
    source = "# name is build\nname: build\n" + _SOURCE
    fixed = fix_source(_PATH, source)
    assert fixed == "\nname: build\n" + _SOURCE.replace("['-', '-']", "['-' ]")
    assert fix_source(_PATH, fixed) == fixed


def test_raw_bom_source_keeps_its_prefix_and_converges() -> None:
    source = "\ufeff" + _SOURCE
    fixed = fix_source(_PATH, source, rule_ids=["cloudbuild-contract"])
    assert fixed == source.replace("['-', '-']", "['-' ]")
    assert fix_source(_PATH, fixed, rule_ids=["cloudbuild-contract"]) == fixed


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize(
    ("waits", "expected_waits", "count"),
    [
        ('["-", "-"]', '["-" ]', 2),
        ('["-","-","-"]', '["-"]', 3),
        ('[\n  "-",\n  "-"\n]', '[\n  "-"\n  \n]', 2),
    ],
)
def test_strict_json_start_sentinels_preserve_exact_source_and_values(
    ending: str, waits: str, expected_waits: str, count: int
) -> None:
    source = (
        '{"description": "snow ☃", "attempt": 1.20e+03, "zero": -0,\n'
        f' "steps": [{{"name": "builder", "waitFor": {waits}}}]\n}}\n'
    ).replace("\n", ending)
    expected = source.replace(waits.replace("\n", ending), expected_waits.replace("\n", ending))
    path = Path("cloudbuild.json")
    assert len(_RULE.check(path, source)) == count
    fixed = fix_source(path, source, rule_ids=["cloudbuild-contract"])
    assert fixed == expected
    assert parse_unique_json(fixed) == {
        "description": "snow ☃",
        "attempt": 1200.0,
        "zero": 0,
        "steps": [{"name": "builder", "waitFor": ["-"]}],
    }
    assert "1.20e+03" in fixed
    assert '"zero": -0' in fixed
    assert not _RULE.check(path, fixed)
    assert fix_source(path, source) == fixed
    assert fix_source(path, fixed, rule_ids=["cloudbuild-contract"]) == fixed


@pytest.mark.parametrize(
    "source",
    [
        '{"steps": [}',
        '{"steps": [], "steps": []}',
        '{"steps": [{"name": "builder", "waitFor": ["-", "-"], "waitFor": ["-"]}]}',
        '{"steps": [], "payload": {"name": 1, "name": 2}}',
        '{"steps": [], "timeout": NaN}',
        '{"steps": [], "timeout": Infinity}',
        '{"steps": [], "timeout": -Infinity}',
        "steps: []\n",
        "{'steps': []}",
        '{"steps": [],}',
        '{"steps": [/* comment */]}',
        '{"steps": []}\n---\n{}\n',
    ],
)
def test_invalid_json_is_not_repaired_or_accepted_as_yaml(source: str) -> None:
    path = Path("cloudbuild.json")
    assert fix_source(path, source, rule_ids=["cloudbuild-contract"]) == source
    with pytest.raises(CloudBuildParseError):
        _RULE.check(path, source)


@pytest.mark.parametrize(
    "source",
    [
        r'{"steps": [{"name": "builder", "waitFor": ["-", "\u002d"]}]}',
        '{"steps": [{"name": "builder", "waitFor": ["-", "prior"]}]}',
        '{"steps": [{"name": "builder", "waitFor": ["prior", "prior"]}]}',
        '{"steps": [{"name": "builder", "waitFor": "-"}]}',
        '{"steps": [{"name": "builder", "waitFor": []}]}',
        '{"steps": [{"name": "builder", "waitFor": ["-"]}]}',
        '{"steps": [{"name": "builder", "args": ["-", "-"]}]}',
        '{"payload": {"waitFor": ["-", "-"]}}',
        '{"description": "# owned rationale", "steps": [{"name": "builder", "waitFor": ["-", "-"]}]}',
    ],
)
def test_unowned_or_ambiguous_json_sentinels_remain_manual(source: str) -> None:
    parse_unique_json(source)
    assert fix_source(Path("cloudbuild.json"), source, rule_ids=["cloudbuild-contract"]) == source


def test_json_repair_preserves_other_values_and_unrelated_native_findings() -> None:
    source = (
        '{"options": {"automapSubstitutions": false}, "steps": ['
        '{"name": "builder", "waitFor": ["-", "-"]},'
        '{"name": "builder", "waitFor": ["later"]},'
        '{"name": "builder", "id": "later"}]}\n'
    )
    path = Path("cloudbuild.json")
    fixed = fix_source(path, source, rule_ids=["cloudbuild-contract"])
    assert fixed == source.replace('["-", "-"]', '["-" ]')
    assert [finding.message for finding in _RULE.check(path, fixed)] == [
        "Cloud Build waitFor 'later' does not name a prior step; order dependencies first"
    ]
    assert fix_source(path, fixed, rule_ids=["cloudbuild-contract"]) == fixed


def test_two_owned_json_sentinel_lists_preserve_unrelated_nested_values() -> None:
    source = (
        ' \n  {"payload": {"values": [null, true, false, {"keep": [1, "x"]}]}, "steps": ['
        '{"name": "builder", "waitFor": ["-", "-"]},'
        '{"name": "builder", "waitFor": ["-","-","-"]}]}\n'
    )
    path = Path("cloudbuild.json")
    assert len(_RULE.check(path, source)) == 5
    fixed = fix_source(path, source, rule_ids=["cloudbuild-contract"])
    assert fixed == source.replace('["-", "-"]', '["-" ]').replace('["-","-","-"]', '["-"]')
    assert parse_unique_json(fixed) == {
        "payload": {"values": [None, True, False, {"keep": [1, "x"]}]},
        "steps": [{"name": "builder", "waitFor": ["-"]}, {"name": "builder", "waitFor": ["-"]}],
    }
    assert not _RULE.check(path, fixed)
    assert fix_source(path, fixed, rule_ids=["cloudbuild-contract"]) == fixed


def test_json_tab_indentation_retains_the_native_parser_refusal() -> None:
    source = '\n\t{"steps": [{"name": "builder", "waitFor": ["-", "-"]}]}\n'
    parse_unique_json(source)
    path = Path("cloudbuild.json")
    assert fix_source(path, source, rule_ids=["cloudbuild-contract"]) == source
    with pytest.raises(CloudBuildParseError, match="cannot start any token"):
        _RULE.check(path, source)


def test_json_sentinel_repairs_keep_rule_selection_and_file_exclusions(tmp_path: Path) -> None:
    source = '{"steps": [{"name": "builder", "waitFor": ["-", "-"]}]}\n'
    assert fix_source(Path("cloudbuild.json"), source, rule_ids=[]) == source
    for name in ("cloudbuild.jsonc", "cloudbuild.toml"):
        assert fix_source(Path(name), source, rule_ids=["cloudbuild-contract"]) == source
    path = tmp_path / "cloudbuild.json"
    (tmp_path / ".sarj-standards.toml").write_text('[text]\nexclude = ["cloudbuild.json"]\n')
    assert fix_source(path, source, rule_ids=["cloudbuild-contract"], root=tmp_path) == source


def test_private_json_metadata_example_is_the_exact_fixed_source() -> None:
    example = next(item for item in _RULE.documentation.examples if item.example_id == "repeated-json-start-sentinel")
    source = example.files[0].source
    fixed = fix_source(Path("cloudbuild.json"), source, rule_ids=["cloudbuild-contract"])
    assert fixed == example.fixed_files[0].source
