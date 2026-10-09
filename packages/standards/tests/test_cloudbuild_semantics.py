from __future__ import annotations

from pathlib import Path

import pytest
from yaml.nodes import MappingNode, SequenceNode

from sarj_standards.libs.linting.cloudbuild import CloudBuildParseError, check_cloudbuild, compose_documents
from sarj_standards.libs.yaml_boundary import mapping_items, sequence_items


def _alias_graph(branches: int) -> str:
    return "a0: &a0 [x]\n" + "".join(
        f"a{level}: &a{level} [{', '.join([f'*a{level - 1}'] * branches)}]\n" for level in range(1, 8)
    )


@pytest.mark.parametrize(
    ("source", "count"),
    [
        ("steps:\n- name: builder\n  id: a\n- name: builder\n  waitFor: [a]\n", 0),
        ("steps:\n- name: builder\n  waitFor: [later]\n- name: builder\n  id: later\n", 1),
        ("steps:\n- name: builder\n  id: a\n- name: builder\n  id: a\n", 1),
        ("steps:\n- name: builder\n  id: a\n  waitFor: [a]\n", 1),
        ("steps:\n- name: builder\n  waitFor: ['-']\n", 0),
        ("steps:\n- name: builder\n  id: a\n- name: builder\n  waitFor: ['-', a]\n", 1),
        ("steps:\n- name: builder\n  script: echo hi\n  args: []\n", 1),
        ("steps:\n- name: builder\n  script: echo hi\n", 0),
        ("jobs:\n  build:\n    steps:\n    - name: hello\n      run: echo hi\n", 0),
        ("steps:\n- name: builder\n  waitFor: [unknown]\n---\nsteps:\n- name: builder\n  id: unknown\n", 1),
    ],
)
def test_build_contract(source: str, count: int) -> None:
    assert len(check_cloudbuild(Path("config.yaml"), source)) == count


@pytest.mark.parametrize(
    ("args", "count"),
    [
        ("['-c', 'echo ${_INPUT}']", 1),
        ("['-lc', 'echo $_INPUT']", 1),
        ("['-c', \"echo '${_INPUT}'\"]", 1),
        ("['-c', 'echo $PROJECT_ID']", 0),
        ("['-c', 'echo $${_INPUT}']", 0),
        ("['-c', 'echo $$INPUT']", 0),
        ("['scripts/build.sh', '${_INPUT}']", 0),
        ("['--', '-c', 'echo ${_INPUT}']", 0),
        ("['-o', 'noclobber', '-c', 'echo ${_INPUT}']", 1),
        ("['-euo', 'pipefail', '-c', 'echo ${_INPUT}']", 1),
        ("['--noprofile', '--norc', '-c', 'echo ${_INPUT}']", 1),
        ("['--rcfile', 'scripts/rc.sh', '-c', 'echo ${_INPUT}']", 1),
        ("['-c', 'echo ${BRANCH_NAME}']", 1),
        ("['-c', 'echo ${TAG_NAME}']", 1),
        ("['-c', 'echo ${COMMIT_SHA}']", 1),
    ],
)
def test_shell_substitution(args: str, count: int) -> None:
    source = f"steps:\n- name: builder\n  entrypoint: /bin/bash\n  args: {args}\n"
    assert len(check_cloudbuild(Path("build.yml"), source)) == count


def test_script_runtime_env_and_direct_argv_are_safe() -> None:
    source = "steps:\n- name: builder\n  script: echo \"$PROJECT_ID\"\n  env: ['PROJECT_ID=$PROJECT_ID']\n- name: builder\n  entrypoint: python\n  args: ['scripts/build.py', '${_INPUT}']\noptions:\n  substitutionOption: ALLOW_LOOSE\n"
    assert check_cloudbuild(Path("build.yml"), source) == []


def test_alias_occurrence_has_own_location() -> None:
    source = "step: &base\n  name: builder\n  id: a\nsteps:\n- *base\n- *base\n"
    findings = check_cloudbuild(Path("build.yml"), source)
    assert [(finding.line, finding.code) for finding in findings] == [(6, "SARJ315")]


def test_merge_preserves_consumer_override_semantics() -> None:
    source = "step: &base\n  name: builder\n  id: a\nsteps:\n- *base\n- <<: *base\n  id: b\n  waitFor: [a]\n"
    assert check_cloudbuild(Path("build.yml"), source) == []


def test_scalar_alias_has_use_site_location() -> None:
    source = "bad: &bad later\nsteps:\n- name: builder\n  waitFor: [*bad]\n"
    findings = check_cloudbuild(Path("build.yml"), source)
    assert [finding.line for finding in findings] == [4]


@pytest.mark.parametrize("source", ["steps: [", "steps: []\nsteps: []\n"])
def test_malformed_and_duplicate_yaml_are_not_clean(source: str) -> None:
    with pytest.raises(CloudBuildParseError):
        check_cloudbuild(Path("build.yml"), source, selected=True)


def test_unselected_malformed_document_belongs_to_yaml_validator() -> None:
    assert check_cloudbuild(Path("other.yaml"), "jobs: [") == []


def test_alias_composition_preserves_a_bounded_shared_graph() -> None:
    source = _alias_graph(2) + "steps:\n- name: builder\n"
    assert check_cloudbuild(Path("cloudbuild.yaml"), source, selected=True) == []
    pending = [node for node in compose_documents(source) if node is not None]
    identities: set[int] = set()
    while pending:
        node = pending.pop()
        if id(node) in identities:
            continue
        identities.add(id(node))
        if isinstance(node, MappingNode):
            pending.extend(child for pair in mapping_items(node) for child in pair)
        elif isinstance(node, SequenceNode):
            pending.extend(sequence_items(node))
    assert len(identities) < 64


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(_alias_graph(5), id="amplified-aliases"),
        pytest.param("unknown: &loop [*loop]\n", id="recursive-sequence"),
        pytest.param("unknown: &loop {<<: *loop}\n", id="recursive-merge"),
        pytest.param("unknown: " + "[" * 70 + "x" + "]" * 70 + "\n", id="deep-composition"),
    ],
)
def test_selected_yaml_expansion_fails_coverage_without_findings(source: str) -> None:
    with pytest.raises(CloudBuildParseError, match=r"bound|Recursive"):
        check_cloudbuild(Path("cloudbuild.yaml"), f"{source}steps:\n- name: builder\n", selected=True)
