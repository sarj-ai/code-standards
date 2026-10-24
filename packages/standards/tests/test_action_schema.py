from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting import action_metadata, devops_schema
from sarj_standards.libs.linting.external import ProcessOutput, analyze_external


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@pytest.mark.parametrize(
    "source",
    [
        "runs: {using: node24, main: index.js}\n",
        "runs: {plugin: 'GitHub.Runner.Plugins.Repository.v1_0.CheckoutAction, Runner.Plugins'}\n",
        "runs: {using: docker, image: Dockerfile, args: ['${{ inputs.name }}']}\n",
        "runs:\n  using: composite\n  steps:\n  - run: ./build.sh\n    shell: bash\n    if: false\n    env: {COUNT: 2, ENABLED: true}\n",
        "runs: {using: composite, steps: [{uses: 'actions/checkout@v5', with: {fetch-depth: 0}}]}\n",
        "runs: {using: composite, steps: [{uses: '$/.github/actions/build'}]}\n",
        "runs: {using: composite, steps: [{run: ./build.sh, shell: bash, if: \"matrix.os == 'linux' && strategy.job-index == 0\"}]}\n",
        "inputs: {enabled: {default: false}, count: {default: 2}}\nruns: {using: node24, main: index.js}\n",
        "runs: {using: node24, main: index.js, post: cleanup.js, post-if: 'always()'}\n",
    ],
    ids=(
        "node-without-marketplace-labels",
        "runner-plugin",
        "docker",
        "constant-condition",
        "uses",
        "self-repository",
        "matrix-context",
        "scalar-defaults",
        "post-condition",
    ),
)
def test_standalone_metadata_uses_the_official_parser_without_a_referencing_workflow(
    tmp_path: Path, source: str
) -> None:
    (tmp_path / "action.yml").write_text(source, encoding="utf-8")
    (report,) = devops_schema.analyze_source_schemas(root=tmp_path, paths=("action.yml",))
    assert report.name == "action-schema"
    assert report.completion is Completion.COMPLETE
    assert not report.diagnostics
    assert not report.issues


@pytest.mark.parametrize(
    "source",
    [
        "name: Example\n",
        "runs: {using: node24}\n",
        "runs: {using: docker}\n",
        "runs: {using: unsupported, main: index.js}\n",
        "runs: {using: composite, steps: [{run: ./build.sh}]}\n",
        "runs: {using: composite, steps: [{run: ./build.sh, uses: ./nested}]}\n",
        "runs: {using: composite, steps: [{uses: ./nested, shell: bash}]}\n",
        "runs: {using: composite, steps: [{uses: ./nested, working-directory: ./src}]}\n",
        "runs: {using: composite, steps: [{run: ./build.sh, shell: bash, with: {input: value}}]}\n",
        "runs: {using: composite, steps: [{uses: ./nested, timeout-minutes: 5}]}\n",
        "runs: {using: composite, steps: [{uses: ./nested, if: 'needs.build.result'}]}\n",
        "runs: {using: composite, steps: [{uses: ./nested, if: 'unknownFunction()'}]}\n",
        "runs: {using: composite, steps: [{uses: ./nested, if: 'inputs.name =='}]}\n",
        "runs: {using: composite, steps: [{uses: ./nested, id: same}, {uses: ./nested, id: SAME}]}\n",
        "runs: {using: composite, steps: [{uses: ./nested, id: 'bad-id!'}]}\n",
        "runs: {using: composite, steps: [{uses: checkout}]}\n",
        "runs: {using: node24, main: index.js, post-if: 'needs.job'}\n",
        "[]\n",
        "",
        "runs: [",
        "name: First\nname: Duplicate\n",
        "[" * 5_000 + "1" + "]" * 5_000,
    ],
    ids=(
        "runs-required",
        "node-main",
        "docker-image",
        "runtime",
        "run-shell",
        "run-and-uses",
        "uses-shell",
        "uses-directory",
        "run-with",
        "workflow-field",
        "unavailable-context",
        "unknown-function",
        "expression-syntax",
        "duplicate-id",
        "invalid-id",
        "action-reference",
        "post-context",
        "root-shape",
        "empty",
        "malformed",
        "duplicate-key",
        "bounded-deep-collections",
    ),
)
def test_invalid_metadata_expressions_and_composite_steps_report_authored_source(tmp_path: Path, source: str) -> None:
    (tmp_path / "action.yaml").write_text(source, encoding="utf-8")
    (report,) = devops_schema.analyze_source_schemas(root=tmp_path, paths=("action.yaml",))
    assert report.completion is Completion.COMPLETE
    assert report.diagnostics
    assert not report.issues
    assert all(
        item.location.path == "action.yaml" and item.location.position is not None for item in report.diagnostics
    )


def test_expression_error_keeps_the_original_unicode_crlf_source_location(tmp_path: Path) -> None:
    source = "name: 🛠\r\nruns:\r\n  using: composite\r\n  steps:\r\n  - uses: ./nested\r\n    if: inputs.name ==\r\n"
    (tmp_path / "action.yml").write_bytes(source.encode())
    (report,) = action_metadata.analyze_actions(root=tmp_path, paths=("action.yml",))
    assert report.completion is Completion.COMPLETE
    assert report.diagnostics
    assert all(item.location.position is not None and item.location.position.line == 5 for item in report.diagnostics)
    assert all(
        item.location.position is not None
        and item.location.position.byte_offset == source.encode().index(b"inputs.name")
        for item in report.diagnostics
    )


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "[]",
        '[{"path":"action.yml","errors":[]},{"path":"action.yml","errors":[]}]',
        '[{"path":"other.yml","errors":[]}]',
        '[{"path":"action.yml","errors":[{"message":"bad","line":999,"column":1}]}]',
    ],
)
def test_native_protocol_errors_cannot_look_like_clean_coverage(tmp_path: Path, payload: str) -> None:
    (tmp_path / "action.yml").write_text("runs: {using: node24, main: index.js}\n")

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        assert argv
        return ProcessOutput(0, payload, "")

    (report,) = action_metadata.analyze_actions(root=tmp_path, paths=("action.yml",), runner=runner)
    assert report.completion is Completion.FAILED
    assert report.issues
    assert not report.diagnostics


def test_modified_bundle_cannot_produce_clean_coverage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "action.yml").write_text("runs: {using: node24, main: index.js}\n")
    (tmp_path / "action-parser.cjs").write_text("process.stdout.write('[]');\n")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- simulate a damaged installed wheel at the production artifact lookup; injecting a parser would bypass the digest guard.
        action_metadata, "CONFIGS_DIR", tmp_path
    )
    (report,) = action_metadata.analyze_actions(root=tmp_path, paths=("action.yml",))
    assert report.completion is Completion.FAILED
    assert "digest does not match" in report.issues[0].message


def test_all_selected_actions_are_returned_in_one_native_batch(tmp_path: Path) -> None:
    for name in ("action.yml", "nested/action.yaml"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("runs: {using: node24, main: index.js}\n")
    reports = action_metadata.analyze_actions(root=tmp_path, paths=("action.yml", "nested/action.yaml"))
    assert len(reports) == 2
    assert all(report.completion is Completion.COMPLETE and not report.diagnostics for report in reports)
    assert [report.file_count for report in reports] == [1, 1]


def test_normal_external_routing_preserves_repository_relative_diagnostic_paths(tmp_path: Path) -> None:
    directory = tmp_path / "nested"
    directory.mkdir()
    (directory / "action.yml").write_text("runs: {using: composite, steps: [{uses: ./nested, if: 'inputs.name =='}]}\n")
    reports = analyze_external(
        (str(directory),), root=tmp_path, trust="safe", capabilities=frozenset({"devops-schema"})
    )
    (report,) = (item for item in reports if item.name == "action-schema")
    assert report.completion is Completion.COMPLETE, report.issues
    assert report.diagnostics
    assert all(item.location.path == "nested/action.yml" for item in report.diagnostics)
