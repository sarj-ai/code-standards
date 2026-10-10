from pathlib import Path, PurePosixPath

import pytest

from sarj_standards.libs.diagnostics import baseline
from sarj_standards.libs.linting import textlint
from sarj_standards.libs.linting.analysis import analyze
from sarj_standards.libs.linting.devops_programs import (
    ExecutionBlock,
    ProgramProjectionError,
    block_embeds_program,
    execution_blocks,
)
from sarj_standards.libs.linting.shell_ast import ShellSyntaxError, parse_shell
from sarj_standards.libs.rules.contracts import EvaluationCase, ExpectedOutcome, Language


_SHELL_CASES = (
    ("python-warnings-file", "python3 -W once scripts/check.py -c strict", False),
    ("python-attached-warnings-file", "python3 -Wonce scripts/check.py", False),
    ("python-x-inline", "python3 -X dev -c 'print(1)'", True),
    ("escaped-interpreter-name", r"py\thon3 -c 'print(1)'", True),
    ("escaped-source-flag", r"python3 \-c 'print(1)'", True),
    ("ansi-quoted-interpreter-name", r"$'py\x74hon3' -c 'print(1)'", True),
    ("ansi-quoted-source-flag", r"python3 $'\055c' 'print(1)'", True),
    ("single-quoted-escaped-file-name", r"python3 '\-c' 'print(1)'", False),
    ("double-quoted-retained-escape-file", r'python3 "\-c" strict', False),
    ("python-attached-x-inline", "python3 -Xdev -Bc 'print(1)'", True),
    ("python-w-operand-not-source", "python3 -W -c scripts/check.py", False),
    ("python-module-boundary", "python3 -m tools.check -c strict", False),
    ("python-double-dash-file", "python3 -- -c --strict", False),
    ("node-preloader-value", "node --require preload.js scripts/check.js", False),
    ("node-attached-preloader", "node -rpreload.js scripts/check.js", False),
    ("node-eval", "node --eval='process.exit(0)'", True),
    ("jq-inline-one-line", "jq '.items' report.json", True),
    ("jq-file-with-arguments", "jq --arg mode strict -f scripts/filter.jq report.json", False),
    ("jq-combined-file-option", "jq -nf scripts/filter.jq", False),
    ("awk-inline-one-line", "awk -F : '{print $1}' report.txt", True),
    ("awk-external-file", "awk -v mode=strict -f scripts/filter.awk report.txt", False),
    ("gawk-additional-source", "gawk -f scripts/filter.awk --source='{print $1}' report.txt", True),
    ("external-shell-wrapper", "bash -ceu 'exec python3 scripts/check.py \"$@\"' -- arg", False),
    ("nested-external-shell-wrapper", "sh -c 'bash -c \"make test\"'", False),
    ("forwarded-inline-interpreter", "sh -c 'exec \"$@\"' -- python3 -c 'print(1)'", True),
    ("forwarded-external-interpreter", "sh -c 'exec \"$@\"' -- python3 scripts/check.py -c strict", False),
    ("wrapped-inline-program", "env MODE=test sudo -u worker python3 -c 'print(1)'", True),
    ("exec-arg-zero-inline", "exec -a worker python3 -c 'print(1)'", True),
    ("command-query", "command -v python3", False),
    ("timeout-external-program", "timeout -k 5 30 python3 scripts/check.py", False),
    ("quoted-control-flow-data", "printf '%s\\n' 'if x; then y; fi'", False),
    ("quoted-command-substitution-data", "printf '%s\\n' '$(python3 -c 1)'", False),
    ("actual-command-substitution", "printf '%s\\n' \"$(python3 -c 1)\"", True),
    ("command-chain", "make lint && make test", True),
    ("linear-command-list", "make lint\nmake test", True),
    ("single-if-still-program", "if make probe; then make test; fi", True),
    ("assignment-with-invocation", "MODE=strict python3 scripts/check.py", False),
    ("assignment-only-program", "MODE=strict", True),
    ("stdin-inline-here-string", "python3 <<< 'print(1)'", True),
    ("stdin-external-file", "python3 - < scripts/check.py", False),
    ("stdin-data-for-external-script", "python3 scripts/check.py <<'DATA'\ninput\nDATA\n", False),
    ("stdin-inline-heredoc", "python3 - <<'PY'\nprint(1)\nPY\n", True),
    ("heredoc-data", "cat <<'DATA'\nif this is data\nDATA\n", False),
)


@pytest.mark.parametrize(("case_id", "source", "expected"), _SHELL_CASES, ids=[case[0] for case in _SHELL_CASES])
def test_shell_execution_policy_uses_native_ast(case_id: str, source: str, expected: bool) -> None:
    assert block_embeds_program(ExecutionBlock(1, source), parse_shell=parse_shell) is expected, case_id


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('[tasks.check]\nshell = "python3 -c"\nrun = "print(1)"\n', True),
        ('[task_config]\nshell = "node -e"\n[tasks.check]\nrun = "process.exit(0)"\n', True),
        (
            '[task_config]\nshell = "python3 -c"\n[tasks.check]\nshell = "bash -c"\nrun = "make check"\n',
            False,
        ),
        ("[tasks]\ncheck = \"python3 -c 'print(1)'\"\n", True),
    ],
    ids=("task-python-shell", "global-node-shell", "task-shell-override", "abbreviated-task"),
)
def test_mise_execution_shell_projection(source: str, expected: bool) -> None:
    blocks = execution_blocks(".mise/config.toml", source)
    assert len(blocks) == 1
    assert block_embeds_program(blocks[0], parse_shell=parse_shell) is expected


def test_cyclic_make_variable_is_bounded_coverage_error() -> None:
    with pytest.raises(ProgramProjectionError, match="Make variable expansion exceeds"):
        execution_blocks("Makefile", "FIRST = $(SECOND)\nSECOND = $(FIRST)\ncheck:\n\t$(FIRST)\n")


@pytest.mark.parametrize(
    "filename",
    ["Dockerfile.dockerignore", "Dockerfile.migrate.dockerignore", "Dockerfile.test.DOCKERIGNORE"],
)
def test_dockerfile_ignore_patterns_are_not_execution_source(filename: str, tmp_path: Path) -> None:
    source = "# Build-context exclusions\nRUN **\n!RUN scripts/check.py\n**/.venv\n"
    path = tmp_path / filename
    path.write_text(source, encoding="utf-8")
    assert execution_blocks(filename, source) == []
    assert not textlint.is_text_path(path)
    assert textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"})) == []


def test_selected_mise_invalid_toml_is_coverage_error() -> None:
    with pytest.raises(ProgramProjectionError, match="invalid selected mise"):
        execution_blocks("mise.toml", "[tasks\n")


@pytest.mark.parametrize(
    ("path", "source", "expected"),
    [
        (
            "compose.yaml",
            "services:\n  seed:\n    entrypoint: [sh, -c]\n    command: ['seeded=$$(psql --file seed.sql)']\n",
            True,
        ),
        (
            "compose.yaml",
            "services:\n  check:\n    healthcheck:\n      test: [CMD-SHELL, 'printf %s $$(date)']\n",
            True,
        ),
        (
            "compose.yaml",
            "services:\n  check:\n    entrypoint: [sh, -c]\n    command: ['exec python3 scripts/check.py \"$$MODE\"']\n",
            False,
        ),
        (
            "cloudbuild.yaml",
            "steps:\n  - name: runner\n    entrypoint: sh\n    args: [-c, 'seeded=$$(psql --file seed.sql)']\n",
            True,
        ),
    ],
    ids=(
        "compose-substitution",
        "compose-healthcheck-substitution",
        "compose-external-data",
        "cloudbuild-argv-substitution",
    ),
)
def test_consumer_dollar_escaping_precedes_shell_analysis(path: str, source: str, expected: bool) -> None:
    blocks = execution_blocks(path, source)
    assert len(blocks) == 1
    assert block_embeds_program(blocks[0], parse_shell=parse_shell) is expected


def test_cloudbuild_script_does_not_expand_substitution_escaping() -> None:
    [block] = execution_blocks("cloudbuild.yaml", "steps:\n  - name: runner\n    script: 'printf %s $$'\n")
    assert block.source == "printf %s $$"
    assert not block_embeds_program(block, parse_shell=parse_shell)


@pytest.mark.parametrize(
    "source",
    [
        "[env]\nVALUE = \"{{ exec(command='python3 -c 1') }}\"\n",
        "[vars]\nVALUE = \"{{ exec(command='python3 -c 1') }}\"\n",
        '[tasks.check]\nrun = "python3 {{ source }}"\n',
        '[tasks.check]\nrun = "make check"\nenv.VALUE = "{{ exec(command=\'python3 -c 1\') }}"\n',
    ],
    ids=("env-exec", "vars-exec", "dynamic-execution-word", "task-env-exec"),
)
def test_mise_executable_templates_fail_coverage_without_loading(source: str) -> None:
    with pytest.raises(ProgramProjectionError, match="mise executable template"):
        execution_blocks("mise.toml", source)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('[env]\nROOT = "{{ config_root }}"\n[tasks.check]\nrun = "make check"\n', False),
        ("[vars]\nMODE = \"{{ 'strict' }}\"\n[tasks.check]\nrun = \"make {{ 'check' }}\"\n", False),
        ("[tasks.check]\nrun = \"python3 {{ '-c' }} 'print(1)'\"\n", True),
    ],
    ids=("environment-reference", "literal-template", "literal-source-flag"),
)
def test_mise_harmless_templates_and_literal_programs(source: str, expected: bool) -> None:
    blocks = execution_blocks("mise.toml", source)
    assert len(blocks) == 1
    assert block_embeds_program(blocks[0], parse_shell=parse_shell) is expected


@pytest.mark.parametrize(
    "source",
    [
        "FROM test\nRUN printf '%s' '<<EOF'\n",
        'FROM test\nRUN printf "%s" "<<EOF"\n',
        r"FROM test" + "\n" + r"RUN printf '%s' \<\<EOF" + "\n",
        'FROM test\nRUN ["printf", "%s", "<<EOF"]\n',
    ],
    ids=("single-quoted-data", "double-quoted-data", "escaped-data", "json-argv-data"),
)
def test_docker_quoted_heredoc_tokens_are_data(source: str) -> None:
    blocks = execution_blocks("Dockerfile", source)
    assert len(blocks) == 1
    assert not block_embeds_program(blocks[0], parse_shell=parse_shell)


def test_multiple_docker_heredocs_are_unproven_instead_of_truncated() -> None:
    with pytest.raises(ProgramProjectionError, match="multiple Docker heredoc"):
        execution_blocks("Dockerfile", "FROM test\nRUN cat <<FIRST <<SECOND\nfirst\nFIRST\nsecond\nSECOND\n")


_CONFIG_CASES = (
    EvaluationCase(
        "skaffold-python-payload",
        Language.CONFIG,
        "apiVersion: skaffold/v4beta7\nkind: Config\nverify:\n  - name: check\n    container:\n      command: [python3]\n      args: [-X, dev, -c, 'print(1)']\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("clouddeploy/scheduler/skaffold.yaml"),
    ),
    EvaluationCase(
        "skaffold-external-wrapper",
        Language.CONFIG,
        "apiVersion: skaffold/v4beta7\nkind: Config\ndeploy:\n  hooks:\n    before:\n      - host:\n          command: [sh, -ceu, 'exec python3 scripts/check.py']\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("clouddeploy/scheduler/skaffold.yaml"),
    ),
    EvaluationCase(
        "cloudbuild-python-payload",
        Language.CONFIG,
        "steps:\n  - name: python-image\n    entrypoint: python3\n    args: [-c, 'print(1)']\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("build.cloudbuild.yaml"),
    ),
    EvaluationCase(
        "cloudbuild-python-shebang",
        Language.CONFIG,
        "steps:\n  - name: python-image\n    script: |\n      #!/usr/bin/env python3\n      print(1)\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("build.cloudbuild.yaml"),
    ),
    EvaluationCase(
        "cloudbuild-external-command",
        Language.CONFIG,
        "steps:\n  - name: python-image\n    entrypoint: python3\n    args: [scripts/check.py, -c, strict]\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("build.cloudbuild.yaml"),
    ),
    EvaluationCase(
        "compose-explicit-shell-program",
        Language.CONFIG,
        "services:\n  test:\n    image: test\n    entrypoint: [sh, -c]\n    command: ['make lint; make test']\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("compose.yaml"),
    ),
    EvaluationCase(
        "compose-quoted-semicolon-argv",
        Language.CONFIG,
        "services:\n  test:\n    image: test\n    command: 'printf \"if x; then y; fi\"'\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("compose.yaml"),
    ),
    EvaluationCase(
        "compose-healthcheck-program",
        Language.CONFIG,
        "services:\n  test:\n    image: test\n    healthcheck:\n      test: [CMD-SHELL, 'make probe || exit 1']\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("compose.yaml"),
    ),
    EvaluationCase(
        "kubernetes-probe-python",
        Language.CONFIG,
        "apiVersion: v1\nkind: Pod\nspec:\n  containers:\n    - name: test\n      image: test\n      readinessProbe:\n        exec:\n          command: [python3, -c, 'print(1)']\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("deployment.yaml"),
    ),
    EvaluationCase(
        "docker-exec-program",
        Language.CONFIG,
        'FROM test\nRUN ["python3", "-c", "print(1)"]\n',
        ExpectedOutcome.MATCH,
        PurePosixPath("Dockerfile"),
    ),
    EvaluationCase(
        "docker-mount-command-chain",
        Language.CONFIG,
        "FROM test\nRUN --mount=type=cache,target=/cache make lint && make test\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("Dockerfile.test"),
    ),
    EvaluationCase(
        "docker-external-command",
        Language.CONFIG,
        'FROM test\nENTRYPOINT ["python3", "scripts/check.py"]\n',
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("Dockerfile"),
    ),
    EvaluationCase(
        "mise-program",
        Language.CONFIG,
        '[tasks.check]\nrun = "make lint && make test"\n',
        ExpectedOutcome.MATCH,
        PurePosixPath("mise.toml"),
    ),
    EvaluationCase(
        "mise-array-separate-units",
        Language.CONFIG,
        '[tasks.check]\nrun = ["make lint", "make test"]\n',
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("mise.toml"),
    ),
    EvaluationCase(
        "make-separate-recipe-units",
        Language.CONFIG,
        "check:\n\t$(MAKE) lint\n\t$(MAKE) test\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("Makefile"),
    ),
    EvaluationCase(
        "make-oneshell-program",
        Language.CONFIG,
        ".ONESHELL:\ncheck:\n\tmake lint\n\tmake test\n",
        ExpectedOutcome.MATCH,
        PurePosixPath("Makefile"),
    ),
    EvaluationCase(
        "make-shell-substitution",
        Language.CONFIG,
        'check:\n\tprintf "%s" "$$(python3 -c 1)"\n',
        ExpectedOutcome.MATCH,
        PurePosixPath("Makefile"),
    ),
    EvaluationCase(
        "non-executable-config-data",
        Language.CONFIG,
        "apiVersion: v1\nkind: ConfigMap\ndata:\n  command: python3 -c 'print(1)'\n",
        ExpectedOutcome.NO_MATCH,
        PurePosixPath("settings.yaml"),
    ),
)


@pytest.mark.parametrize("case", _CONFIG_CASES, ids=[case.case_id for case in _CONFIG_CASES])
def test_execution_fields_labeled_cases(case: EvaluationCase, tmp_path: Path) -> None:
    path = tmp_path / case.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(case.source, encoding="utf-8")
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len({(finding.path, finding.line, finding.code) for finding in findings}) == len(findings)


def test_alias_merge_reports_execution_use_site_and_respects_override() -> None:
    source = (
        "defaults: &defaults\n  run: python3 -c 'print(1)'\njobs:\n  test:\n    steps:\n"
        "      - <<: *defaults\n      - <<: *defaults\n        run: python3 scripts/check.py\n"
    )
    blocks = execution_blocks(".github/workflows/ci.yml", source)
    assert [(block.line, block_embeds_program(block, parse_shell=parse_shell)) for block in blocks] == [
        (6, True),
        (8, False),
    ]


def test_multidocument_and_scalar_aliases_preserve_each_occurrence() -> None:
    source = (
        "jobs:\n  test:\n    steps:\n      - run: &program python3 -c 'print(1)'\n      - run: *program\n"
        "---\njobs:\n  test:\n    steps:\n      - run: *missing\n"
    )
    # Anchors cannot cross document boundaries; the syntax owner rejects this
    # input. A valid second document remains independently covered.
    with pytest.raises(ProgramProjectionError, match="undefined YAML alias"):
        execution_blocks(".github/workflows/ci.yml", source)
    valid = source.replace("*missing", "node -e 'process.exit(0)'")
    blocks = execution_blocks(".github/workflows/ci.yml", valid)
    assert [block.line for block in blocks] == [4, 5, 10]
    assert all(block_embeds_program(block, parse_shell=parse_shell) for block in blocks)


@pytest.mark.parametrize("source", ["python3 -c", "env -S 'python3 -c 1'", 'sh -c "$PROGRAM"'])
def test_unprovable_payload_is_coverage_failure(source: str) -> None:
    with pytest.raises(ProgramProjectionError):
        block_embeds_program(ExecutionBlock(1, source), parse_shell=parse_shell)


def test_malformed_selected_shell_is_not_clean() -> None:
    with pytest.raises(ShellSyntaxError):
        block_embeds_program(ExecutionBlock(1, "python3 'unterminated"), parse_shell=parse_shell)


def test_duplicate_execution_key_is_not_baselinable_finding() -> None:
    with pytest.raises(ProgramProjectionError, match="duplicate YAML key"):
        execution_blocks(
            ".github/workflows/ci.yml",
            "jobs:\n  test:\n    steps:\n      - run: make test\n        run: python3 -c 1\n",
        )


def test_recursive_yaml_alias_cannot_silently_disappear() -> None:
    with pytest.raises(ProgramProjectionError, match="recursive YAML alias"):
        execution_blocks(".github/workflows/ci.yml", "jobs: &jobs\n  test: *jobs\n")


def test_yaml_alias_expansion_is_bounded() -> None:
    source = "a0: &a0 [data, data]\n" + "".join(
        f"a{number}: &a{number} [*a{number - 1}, *a{number - 1}]\n" for number in range(1, 17)
    )
    with pytest.raises(ProgramProjectionError, match="node bound"):
        execution_blocks("workflow.yaml", source)


def test_payload_body_edit_invalidates_baseline_but_next_field_does_not(tmp_path: Path) -> None:
    relative = ".github/workflows/ci.yml"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        "jobs:\n  test:\n    steps:\n      - run: |\n          python3 -c 'print(1)'\n      - run: make test\n",
        encoding="utf-8",
    )
    report = analyze([relative], root=tmp_path)
    (finding,) = [item for item in report.diagnostics if item.code == "SARJ310"]
    assert finding.location.region is not None
    changed_body = baseline.ChangedLineScope(frozenset({relative}), {relative: frozenset({5})})
    changed_next_field = baseline.ChangedLineScope(frozenset({relative}), {relative: frozenset({6})})
    assert baseline.touches_changed_lines(finding, changed_body)
    assert not baseline.touches_changed_lines(finding, changed_next_field)


def test_argument_field_order_does_not_fabricate_reversed_source_span(tmp_path: Path) -> None:
    path = tmp_path / "build.cloudbuild.yaml"
    path.write_text(
        "steps:\n  - name: python-image\n    args: [-c, 'print(1)']\n    entrypoint: python3\n", encoding="utf-8"
    )
    report = analyze([path.name], root=tmp_path)
    (finding,) = [item for item in report.diagnostics if item.code == "SARJ310"]
    assert finding.location.region is not None
    assert finding.location.region.start.line == 2
    assert finding.location.region.end.line == 3


def test_make_variable_identity_is_resolved_without_running_make() -> None:
    source = "PYTHON := python3 # interpreter\ncheck:\n\t$(PYTHON) -X dev -c 'print(1)'\n"
    (block,) = execution_blocks("Makefile", source)
    assert block_embeds_program(block, parse_shell=parse_shell)
    assert block.end_line is None


def test_custom_docker_shell_cannot_turn_source_into_an_unchecked_program() -> None:
    source = 'FROM test\nSHELL ["python3", "-c"]\nRUN print(1)\nFROM another\nRUN make test\n'
    blocks = execution_blocks("Dockerfile", source)
    assert [block_embeds_program(block, parse_shell=parse_shell) for block in blocks] == [True, False]


_KUBERNETES_WORKLOAD_PATHS = (
    ("v1", "Pod", ("spec",)),
    ("v1", "PodTemplate", ("template", "spec")),
    ("v1", "ReplicationController", ("spec", "template", "spec")),
    ("apps/v1", "ReplicaSet", ("spec", "template", "spec")),
    ("apps/v1", "Deployment", ("spec", "template", "spec")),
    ("apps/v1", "StatefulSet", ("spec", "template", "spec")),
    ("apps/v1", "DaemonSet", ("spec", "template", "spec")),
    ("batch/v1", "Job", ("spec", "template", "spec")),
    ("batch/v1", "CronJob", ("spec", "jobTemplate", "spec", "template", "spec")),
)


def _indent_kubernetes_context(source: str) -> str:
    return "".join("  " + line for line in source.splitlines(keepends=True))


def _kubernetes_context_header(api_version: str, kind: str) -> str:
    return f"apiVersion: {api_version}\nkind: {kind}\nmetadata:\n  name: public-control\n"


def _kubernetes_context_cases() -> list[tuple[str, str, int]]:
    cases: list[tuple[str, str, int]] = []
    command = "command:\n- python3\n- -c\n- print(1)\n"
    container = "- name: app\n  image: public-example:1\n" + _indent_kubernetes_context(command)
    for api_version, kind, path in _KUBERNETES_WORKLOAD_PATHS:
        for container_kind in ("containers", "initContainers", "ephemeralContainers"):
            prefix = "".join("  " * depth + f"{component}:\n" for depth, component in enumerate(path))
            body = prefix + "".join(
                "  " * len(path) + line for line in f"{container_kind}:\n{container}".splitlines(keepends=True)
            )
            cases.append((f"{kind}-{container_kind}", _kubernetes_context_header(api_version, kind) + body, 1))
    for hook in ("postStart", "preStop", "livenessProbe", "readinessProbe", "startupProbe"):
        body = f"{hook}:\n  exec:\n" + _indent_kubernetes_context(_indent_kubernetes_context(command))
        if hook in {"postStart", "preStop"}:
            body = "lifecycle:\n" + _indent_kubernetes_context(body)
        body = "containers:\n- name: app\n  image: public-example:1\n" + _indent_kubernetes_context(body)
        cases.append((hook, _kubernetes_context_header("v1", "Pod") + "spec:\n" + _indent_kubernetes_context(body), 1))
    for api_version, kind in (
        ("example.com/v1", "ExampleRecord"),
        ("apps/v99", "Deployment"),
        ("example.com/v1", "Pod"),
        ("v1", "ConfigMap"),
    ):
        body = "data:\n  examples:\n    containers:\n    - name: sample\n" + "".join(
            "      " + line for line in command.splitlines(keepends=True)
        )
        source = _kubernetes_context_header(api_version, kind) + body
        cases.append((f"data-{kind}-{api_version}", source, 0))
        source = "apiVersion: v1\nkind: List\nitems:\n- " + source.replace("\n", "\n  ").rstrip() + "\n"
        cases.append((f"list-data-{kind}-{api_version}", source, 0))
    cases.extend(
        (
            (
                "unknown-pod-shaped",
                "apiVersion: example.com/v1\nkind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n      - command:\n        - python3\n        - -c\n        - print(1)\n",
                0,
            ),
            (
                "known-metadata-data",
                "apiVersion: v1\nkind: Pod\nmetadata:\n  name: public-control\n  examples:\n    containers:\n    - command:\n      - python3\n      - -c\n      - print(1)\n",
                0,
            ),
            (
                "wrong-version",
                "apiVersion: apps/v99\nkind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n      - command:\n        - python3\n        - -c\n        - print(1)\n",
                0,
            ),
            (
                "http-probe-data",
                "apiVersion: v1\nkind: Pod\nspec:\n  containers:\n  - name: app\n    readinessProbe:\n      httpGet:\n        path: /\n        examples:\n          exec:\n            command:\n            - python3\n            - -c\n            - print(1)\n",
                0,
            ),
            (
                "aliased-command",
                "apiVersion: v1\nkind: Pod\ndata: &args [python3, -c, 'print(1)']\nspec:\n  containers:\n  - name: app\n    command: *args\n",
                1,
            ),
            (
                "merge-container-command",
                "apiVersion: v1\nkind: Pod\nexample: &container\n  name: app\n  command: [python3, -c, 'print(1)']\nspec:\n  containers:\n  - <<: *container\n",
                1,
            ),
            (
                "merge-command-override",
                "apiVersion: v1\nkind: Pod\nexample: &container\n  name: app\n  command: [python3, -c, 'print(1)']\nspec:\n  containers:\n  - <<: *container\n    command: [python3, scripts/check.py]\n",
                0,
            ),
            (
                "nested-list",
                "apiVersion: v1\nkind: List\nitems:\n- apiVersion: v1\n  kind: List\n  items:\n  - apiVersion: v1\n    kind: Pod\n    metadata:\n      name: public-control\n    spec:\n      containers:\n      - name: app\n        image: public-example:1\n        command:\n        - python3\n        - -c\n        - print(1)\n",
                1,
            ),
            (
                "external-module",
                "apiVersion: v1\nkind: Pod\nmetadata:\n  name: public-control\nspec:\n  containers:\n  - name: app\n    image: public-example:1\n    command:\n    - python3\n    - -m\n    - tools.check\n",
                0,
            ),
            (
                "image-default-stdin-data",
                "apiVersion: v1\nkind: Pod\nspec:\n  containers:\n  - name: app\n    args:\n    - python3\n    - -c\n    - print(1)\n",
                0,
            ),
        )
    )
    return cases


_KUBERNETES_CONTEXT_CASES = _kubernetes_context_cases()


@pytest.mark.parametrize(
    ("case_id", "source", "count"),
    _KUBERNETES_CONTEXT_CASES,
    ids=[case[0] for case in _KUBERNETES_CONTEXT_CASES],
)
def test_kubernetes_programs_require_a_known_execution_context(
    tmp_path: Path, case_id: str, source: str, count: int
) -> None:
    path = tmp_path / "resource.yaml"
    path.write_text(source, encoding="utf-8")
    blocks = execution_blocks(path.name, source)
    assert sum(block_embeds_program(block, parse_shell=parse_shell) for block in blocks) == count, case_id
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
    assert len(findings) == count, case_id
    assert (
        textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"})) == findings
    )
    assert len({(finding.path, finding.line, finding.code) for finding in findings}) == count


def test_kubernetes_alias_execution_uses_occurrence_coordinates() -> None:
    source = "apiVersion: v1\nkind: Pod\nexample: &argv [python3, -c, 'print(1)']\nspec:\n  containers:\n  - name: app\n    command: *argv\n"
    [block] = execution_blocks("resource.yaml", source)
    assert block.line == 7
    assert block.end_line == 7


def test_kubernetes_nested_lists_retain_a_coverage_bound() -> None:
    prefix = ["apiVersion: v1\nkind: List\nitems:\n"]
    prefix.extend(
        "  " * (depth - 1) + "- apiVersion: v1\n" + "  " * depth + "kind: List\n" + "  " * depth + "items:\n"
        for depth in range(1, 33)
    )
    source = "".join(prefix) + "  " * 32 + "- apiVersion: v1\n" + "  " * 33 + "kind: Pod\n" + "  " * 33 + "spec: {}\n"
    with pytest.raises(ProgramProjectionError, match=r"nesting exceeds|node bound"):
        execution_blocks("resource.yaml", source)


_MISE_NATIVE_SOURCE_LOCATIONS = (
    pytest.param('[tasks]\nprobe = "printf first; printf second"\n', [2], id="shorthand"),
    pytest.param('[tasks.probe]\n"run" = "printf first; printf second"\n', [2], id="quoted-run-key"),
    pytest.param('tasks.probe.run = "printf first; printf second"\n', [1], id="dotted-task"),
    pytest.param('[tasks]\nprobe = {run = "printf first; printf second"}\n', [2], id="inline-task"),
    pytest.param(
        "[vars]\ntext = '''\nrun = \"decoy\"\n'''\n[tasks.probe]\nrun = \"printf first; printf second\"\n",
        [6],
        id="multiline-decoy",
    ),
    pytest.param(
        '[vars]\ndecoy = "printf first; printf second"\n[tasks.other]\nrun = "printf first; printf second"\n[tasks.probe]\nrun = "printf first; printf second" # sarj-noqa: SARJ310 - marker\n',
        [4, 6],
        id="repeated-command-data",
    ),
    pytest.param(
        '[vars]\nlabel="λ"\n[tasks.probe]\n"run"="printf first; printf second"\n', [4], id="unicode-before-key"
    ),
    pytest.param(
        '[tasks.probe]\nrun="printf \\x66irst; printf second"\n',
        [2],
        id="toml11-escape",
        marks=pytest.mark.skipif("sys.version_info < (3, 15)", reason="native tomllib TOML 1.1 requires Python 3.15"),
    ),
    pytest.param(
        '[tasks]\nprobe = {\n run="printf first; printf second",\n}\n',
        [3],
        id="toml11-inline-newline",
        marks=pytest.mark.skipif("sys.version_info < (3, 15)", reason="native tomllib TOML 1.1 requires Python 3.15"),
    ),
    pytest.param(
        "[tasks.probe]\nrun=[\n  \"printf first; printf second\", # decoy\n  'printf first; printf second',\n]\n",
        [3, 4],
        id="array-comments",
    ),
    pytest.param(
        '["tasks"."probe".env]\nVAR="public"\n[tasks.probe]\n"run"="printf first; printf second"\n',
        [4],
        id="quoted-key-bare-extension",
    ),
    pytest.param(
        '[tasks.probe.env]\nVAR="value"\n["tasks"."probe"]\nrun="printf first; printf second"\n',
        [4],
        id="bare-key-quoted-extension",
    ),
    pytest.param(
        '[[data]]\nname="public"\n[other]\nvalue=1\n[data.child]\nvalue=2\n[tasks.probe]\nrun="printf first; printf second"\n',
        [8],
        id="out-of-order-aot",
    ),
    pytest.param(
        '[["data"]]\nname="first"\n[[data]]\nname="second"\n[data.child]\nvalue="public"\n[tasks."probe"]\nrun="printf first; printf second"\n',
        [8],
        id="mixed-key-aot",
    ),
    pytest.param(
        'value=nan\ntime=1979-05-27T07:32:00Z\n[tasks.probe]\nrun="printf first; printf second"\n',
        [4],
        id="nan-datetime-data",
    ),
    pytest.param(
        'data="__sarj_source_span_0__"\n[tasks.probe]\nrun="printf first; printf second"\n',
        [3],
        id="marker-collision-data",
    ),
    pytest.param(
        '"\\u005f_sarj_source_span_0__"="public"\n[tasks.probe]\nrun="printf first; printf second"\n',
        [3],
        id="escaped-marker-key",
    ),
    pytest.param(
        'data="\\u005f_sarj_source_span_0__"\n[tasks.probe]\nrun="printf first; printf second"\n',
        [3],
        id="escaped-marker-value",
    ),
    pytest.param('[tasks.probe]\n"r\\u0075n"="printf first; printf second"\n', [2], id="escaped-run-key"),
    pytest.param('[tasks."probe.name"]\nrun="printf first; printf second"\n', [2], id="dot-in-task-name"),
    pytest.param(
        "[tasks.probe]\nrun='''printf 'first'; printf 'second''''\n", [2], id="literal-command-four-closing-quotes"
    ),
    pytest.param(
        '[tasks.probe]\nrun="""printf "first"; printf "second""""\n', [2], id="basic-command-four-closing-quotes"
    ),
    pytest.param(
        "[tasks.probe]\nrun='''printf first; printf second'''''\n", [2], id="literal-command-five-closing-quotes"
    ),
    pytest.param(
        '[tasks.probe]\nrun="""printf first; printf second"""""\n', [2], id="basic-command-five-closing-quotes"
    ),
    pytest.param(
        '# run="decoy"\n[vars]\ntext=\'\'\'\n# quoted "data" and run="decoy"\n\'\'\'\n[tasks.probe]\nrun="printf first; printf second" # "decoy"\n',
        [7],
        id="multiline-comments",
    ),
    pytest.param('[tasks.probe]\nrun="""\nprintf first; printf second\n"""\n', [2], id="multiline-command"),
    pytest.param(
        "data=''''value''''\n[tasks.probe]\nrun=\"printf first; printf second\"\n", [3], id="four-literal-quotes"
    ),
    pytest.param(
        'data="""""value"""""\n[tasks.probe]\nrun="printf first; printf second"\n', [3], id="five-basic-quotes"
    ),
    pytest.param(
        '[vars]\ntext="""[tasks.decoy]\\nrun=\\"decoy\\""""\n[tasks.probe]\nrun="printf first; printf second"\n',
        [4],
        id="multiline-key-shaped-data",
    ),
    pytest.param(
        'a=+nan\nb=-nan\nc=nan\n[tasks.probe]\nrun="printf first; printf second"\n',
        [5],
        id="positive-negative-nan-data",
    ),
    pytest.param(
        'data="run = \\"decoy\\""\n[tasks.probe]\nrun="printf first; printf second"\n', [3], id="double-escaped-data"
    ),
)


@pytest.mark.parametrize(("source", "expected_lines"), _MISE_NATIVE_SOURCE_LOCATIONS)
def test_mise_runtime_strings_retain_exact_native_source_lines(source: str, expected_lines: list[int]) -> None:
    blocks = execution_blocks("mise.toml", source)
    assert [block.line for block in blocks] == expected_lines


def test_mise_array_commands_report_at_their_individual_use_sites(tmp_path: Path) -> None:
    source = '[tasks.probe]\nrun = [\n  "printf first; printf second", # first command use-site\n  "printf third; printf fourth",\n]\n'
    path = tmp_path / "mise.toml"
    path.write_text(source)
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"workflow-embedded-program"}))
    assert [(finding.code, finding.line) for finding in findings] == [("SARJ310", 3), ("SARJ310", 4)]


@pytest.mark.parametrize("source", ["[tasks.probe]\nrun=1\n", '[tasks.probe]\nrun=["printf first", 2]\n'])
def test_mise_non_string_runtime_values_fail_analysis_coverage(source: str) -> None:
    with pytest.raises(ProgramProjectionError, match="mise task run must be"):
        execution_blocks("mise.toml", source)
