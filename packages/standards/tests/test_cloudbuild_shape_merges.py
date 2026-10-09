from __future__ import annotations

from pathlib import Path

import pytest

from sarj_standards.libs.linting.cloudbuild import CloudBuildParseError, check_cloudbuild
from sarj_standards.libs.linting.text_rules.cloudbuild_contract import CloudBuildContract


_CASES = (
    ("direct-unsafe-shell", "steps:\n- name: builder\n  entrypoint: bash\n  args: [-c, 'echo ${BRANCH_NAME}']\n", 1),
    (
        "root-merge-unsafe-shell",
        "defaults: &build\n  steps:\n  - name: builder\n    entrypoint: bash\n    args: [-c, 'echo ${BRANCH_NAME}']\n<<: *build\n",
        1,
    ),
    (
        "root-nested-merge-unsafe-shell",
        "defaults: &outer\n  defaults: &inner\n    steps:\n    - name: builder\n      entrypoint: bash\n      args: [-c, 'echo ${BRANCH_NAME}']\n  <<: *inner\n<<: *outer\n",
        1,
    ),
    (
        "step-merge-name-unsafe-shell",
        "base: &base {name: builder}\nsteps:\n- <<: *base\n  entrypoint: bash\n  args: [-c, 'echo ${BRANCH_NAME}']\n",
        1,
    ),
    (
        "root-step-merged-unsafe-shell",
        "step: &step {name: builder, entrypoint: bash, args: [-c, 'echo ${BRANCH_NAME}']}\nbuild: &build\n  steps: [{<<: *step}]\n<<: *build\n",
        1,
    ),
    (
        "root-merge-forward-dependency",
        "defaults: &build\n  steps:\n  - name: builder\n    waitFor: [later]\n<<: *build\n",
        1,
    ),
    ("step-merge-forward-dependency", "base: &base {name: builder, waitFor: [later]}\nsteps:\n- <<: *base\n", 1),
    (
        "direct-valid",
        "steps:\n- name: builder\n  entrypoint: bash\n  args: ['scripts/build.sh', '${BRANCH_NAME}']\n",
        0,
    ),
    (
        "root-merged-valid",
        "defaults: &build\n  steps:\n  - name: builder\n    entrypoint: bash\n    args: ['scripts/build.sh', '${BRANCH_NAME}']\n<<: *build\n",
        0,
    ),
    (
        "root-explicit-steps-override",
        "defaults: &build\n  steps:\n  - name: builder\n    entrypoint: bash\n    args: [-c, 'echo ${BRANCH_NAME}']\n<<: *build\nsteps:\n- name: builder\n  entrypoint: bash\n  args: ['scripts/build.sh', '${BRANCH_NAME}']\n",
        0,
    ),
    (
        "step-explicit-args-override",
        "base: &base {name: builder, entrypoint: bash, args: [-c, 'echo ${BRANCH_NAME}']}\nsteps:\n- <<: *base\n  args: [scripts/build.sh]\n",
        0,
    ),
    (
        "merge-sequence-first-valid",
        "defaults: &good\n  steps:\n  - name: builder\n    entrypoint: bash\n    args: ['scripts/build.sh', '${BRANCH_NAME}']\nother: &bad\n  steps:\n  - name: builder\n    entrypoint: bash\n    args: [-c, 'echo ${BRANCH_NAME}']\n<<: [*good, *bad]\n",
        0,
    ),
    (
        "merge-sequence-first-invalid",
        "defaults: &good\n  steps:\n  - name: builder\n    entrypoint: bash\n    args: ['scripts/build.sh', '${BRANCH_NAME}']\nother: &bad\n  steps:\n  - name: builder\n    entrypoint: bash\n    args: [-c, 'echo ${BRANCH_NAME}']\n<<: [*bad, *good]\n",
        1,
    ),
    (
        "step-sequence-first-name",
        "a: &a {name: builder}\nb: &b {name: other}\nsteps:\n- <<: [*a, *b]\n  waitFor: [later]\n",
        1,
    ),
    ("merged-named-step-alias", "base: &base {name: builder, waitFor: [later]}\nsteps: [*base]\n", 1),
    ("azure-task", "steps:\n- task: PythonScript@0\n  inputs:\n    scriptSource: inline\n    script: print(1)\n", 0),
    ("azure-script-name", "steps:\n- script: echo hello\n  name: build\n  displayName: Build\n", 0),
    ("github-nested-steps", "jobs:\n  build:\n    steps:\n    - name: Build\n      run: python3 -c 'print(1)'\n", 0),
    ("generic-root-step-list", "steps: [first, second]\n", 0),
    ("generic-root-step-mappings", "steps:\n- command: python3\n  args: [-c, 'print(1)']\n", 0),
    ("unrelated-root-merge", "defaults: &base {jobs: [first]}\n<<: *base\n", 0),
    (
        "explicit-empty-steps",
        "defaults: &build\n  steps:\n  - name: builder\n    entrypoint: bash\n    args: [-c, 'echo ${BRANCH_NAME}']\n<<: *build\nsteps: []\n",
        0,
    ),
    ("unrelated-integer-root-key", "1: data\n", 0),
    ("unrelated-merged-integer-key", "base: &base {1: data}\n<<: *base\n", 0),
    ("unrelated-steps-and-integer-key", "steps: [{command: echo}]\n1: data\n", 0),
    ("unrelated-step-integer-key", "steps: [{1: echo}]\n", 0),
    ("unrelated-sequence-key", "? [first, second]\n: data\n", 0),
    (
        "build-non-string-key",
        "steps:\n- name: builder\n  entrypoint: bash\n  args: [-c, 'echo ${BRANCH_NAME}']\n1: data\n",
        "error",
    ),
    ("duplicate-root-selected", "steps: []\nsteps: []\n", "error"),
    ("duplicate-merged-name", "base: &base {name: builder, name: other}\nsteps: [{<<: *base}]\n", 0),
    ("duplicate-merged-name-selected", "base: &base {name: builder, name: other}\nsteps: [{<<: *base}]\n", "error"),
    ("invalid-merge-type-selected", "<<: 42\nsteps: [{name: builder}]\n", "error"),
    ("invalid-merge-type", "<<: 42\nsteps: [{name: builder}]\n", "error"),
    ("unrelated-bad-merge", "<<: 42\n", 0),
    ("unrelated-duplicate-keys", "jobs: []\njobs: []\n", 0),
    ("unrelated-merged-duplicate-keys", "base: &base {jobs: [], jobs: []}\n<<: *base\n", 0),
    ("unrelated-cyclic-merge", "base: &base {<<: *base}\n<<: *base\n", 0),
    (
        "explicit-non-build-override",
        "defaults: &build\n  steps:\n  - name: builder\n    entrypoint: bash\n    args: [-c, 'echo ${BRANCH_NAME}']\n<<: *build\nsteps: [{command: echo}]\n",
        0,
    ),
    (
        "mixed-non-build-key-types",
        "base: &base {1: numeric, label: text}\n<<: *base\nsteps: [{2: numeric, command: echo}]\n",
        0,
    ),
    ("cyclic-merge-selected", "base: &base {<<: *base}\nsteps: [{name: builder}]\n", "error"),
)


@pytest.mark.parametrize(("case_id", "source", "expected"), _CASES, ids=[case[0] for case in _CASES])
def test_build_shape_resolves_merges_without_claiming_other_yaml(
    case_id: str, source: str, expected: int | str
) -> None:
    if expected == "error":
        with pytest.raises(CloudBuildParseError):
            check_cloudbuild(Path("config.yaml"), source, selected=case_id.endswith("-selected"))
    else:
        assert len(check_cloudbuild(Path("config.yaml"), source)) == expected


def test_generic_filename_uses_merged_build_shape() -> None:
    source = "base: &base {name: builder, waitFor: [later]}\nsteps: [{<<: *base}]\n"
    findings = CloudBuildContract().check(Path("config.yaml"), source)
    assert [(finding.line, finding.code) for finding in findings] == [(2, "SARJ315")]
