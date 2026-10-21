from __future__ import annotations

from pathlib import Path

import pytest

from sarj_standards.libs.linting.cloudbuild import CloudBuildParseError
from sarj_standards.libs.linting.text_rules.ci_cloud_target_literal import CiCloudTargetLiteral


def _findings(source: str, path: str = "scripts/ci/publish.sh") -> list[int]:
    return [finding.line for finding in CiCloudTargetLiteral().check(Path(path), source)]


@pytest.mark.parametrize(
    ("source", "lines"),
    [
        ("gcloud artifacts repositories list --project=example-dev\n", [1]),
        ("g'cloud' artifacts repositories list --pro'ject'=example-dev\n", [1]),
        ('/usr/bin/gcloud --project "example-prod" artifacts repositories list\n', [1]),
        ('gcloud artifacts repositories list --project="${PROJECT_ID}"\n', []),
        ('gcloud artifacts repositories list --project="${{ inputs.project }}"\n', []),
        ('echo "gcloud --project=example-dev"\n', []),
        ("# gcloud --project=example-dev\nprintf done\n", []),
        ("cat <<'DATA'\ngcloud --project=example-dev\nDATA\n", []),
        ('[[ "$PROJECT_ID" == example-dev ]]\n', []),
        ('gcloud --project="$PROJECT_ID" artifacts repositories list --format="--project=example-dev"\n', []),
        ("docker push us-docker.pkg.dev/example-dev/images/app:$TAG\n", []),
        ("docker tag app us-docker.pkg.dev/example-dev/images/app:$TAG\n", []),
        ("docker pull us-docker.pkg.dev/example-dev/images/app@sha256:abc\n", []),
        ("custom-wrapper gcloud --project=example-dev\n", []),
        ("gcloud artifacts repositories list -- --project=example-dev\n", []),
    ],
)
def test_actual_command_targets_exclude_shell_data_and_inputs(source: str, lines: list[int]) -> None:
    assert _findings(source) == lines


@pytest.mark.parametrize("project", ["example-dev", "example-prod", "other-company", "123456789012"])
def test_project_detection_has_no_repository_or_environment_name_allowlist(project: str) -> None:
    assert _findings(f"gcloud artifacts repositories list --project={project}\n") == [1]


@pytest.mark.parametrize("project", ["example-trust", "another-signer", "123456789012"])
@pytest.mark.parametrize("flag", ["--project {project}", "--project={project}"])
def test_public_key_reads_preserve_fixed_authority_at_every_project_flag_position(project: str, flag: str) -> None:
    command = ["kms", "keys", "versions", "get-public-key", "1"]
    for position in range(len(command) + 1):
        arguments = [*command[:position], flag.format(project=project), *command[position:]]
        assert _findings(f"gcloud {' '.join(arguments)} --key signer --keyring trust --location global\n") == []


@pytest.mark.parametrize(
    "command", ["keys create signer", "keys versions create", "keys versions get-public-key-extra"]
)
def test_public_key_exception_does_not_hide_other_kms_operations(command: str) -> None:
    assert _findings(f"gcloud kms {command} --project=example-dev\n") == [1]


def test_public_key_read_does_not_hide_a_separate_deployment_target() -> None:
    source = "gcloud kms keys versions get-public-key 1 --project=example-trust\ngcloud run deploy app --project=example-dev\n"
    assert _findings(source) == [2]


@pytest.mark.parametrize("option", ["--quiet", "-q", "--format=json"])
def test_known_global_options_preserve_trust_reads_and_deployment_findings(option: str) -> None:
    assert _findings(f"gcloud {option} kms keys versions get-public-key 1 --project=example-trust\n") == []
    assert _findings(f"gcloud {option} run deploy app --project=example-dev\n") == [1]


@pytest.mark.parametrize(
    "prefix", ["--format json", '"$OPERATION"', 'kms "$KEY_OPERATION"', "--format=$FORMAT", '--format="$FORMAT"']
)
def test_unknown_option_values_and_dynamic_command_prefixes_remain_unreported(prefix: str) -> None:
    assert _findings(f"gcloud {prefix} --project=example-dev\n") == []


def test_dynamic_option_after_clear_deployment_command_keeps_literal_target_finding() -> None:
    assert _findings("gcloud run deploy app --format=$FORMAT --project=example-dev\n") == [1]


@pytest.mark.parametrize("project", ["--project $PROJECT", '--project "$PROJECT"', "--project=$PROJECT"])
def test_dynamic_project_operands_preserve_unknown_command_purpose(project: str) -> None:
    assert _findings(f"gcloud {project} --project=example-trust\n") == []
    assert _findings(f"gcloud run deploy app {project} --project=example-dev\n") == [1]


@pytest.mark.parametrize("operation", ["get-public-key*", "get-public-ke?", "get-public-ke[y]"])
def test_unquoted_globs_do_not_select_a_literal_operation(operation: str) -> None:
    assert _findings(f"gcloud kms keys versions {operation} 1 --project=example-trust\n") == []
    assert _findings(f"gcloud kms keys versions '{operation}' 1 --project=example-dev\n") == [1]
    assert _findings(f'gcloud kms keys versions "{operation}" 1 --project=example-dev\n') == [1]


def test_custom_workflow_env_image_aliases_are_deliberately_not_resolved() -> None:
    source = """env:
  IMAGE: us-docker.pkg.dev/example-dev/images/app:${{ github.sha }}
jobs:
  publish:
    steps:
    - run: docker push "$IMAGE"
    - run: docker push "$IMAGE"
"""
    assert _findings(source, ".github/workflows/publish.yml") == []


def test_step_override_and_input_images_do_not_inherit_a_job_target_finding() -> None:
    source = """jobs:
  publish:
    env:
      IMAGE: us-docker.pkg.dev/example-dev/images/app:fixed
    steps:
    - run: docker pull "$IMAGE"
    - run: docker push "$IMAGE"
      env:
        IMAGE: us-docker.pkg.dev/${{ inputs.project }}/images/app:fixed
"""
    assert _findings(source, ".github/workflows/publish.yml") == []


def test_google_sdk_project_and_auth_project_are_data_but_trust_pins_are_not() -> None:
    source = """jobs:
  publish:
    env:
      GOOGLE_CLOUD_PROJECT: example-dev
    steps:
    - uses: google-github-actions/auth@0123456789abcdef
      with:
        project_id: example-dev
        workload_identity_provider: projects/123456789012/locations/global/workloadIdentityPools/trust/providers/github
        service_account: publisher@example-dev.iam.gserviceaccount.com
"""
    assert _findings(source, ".github/workflows/publish.yml") == [4, 8]


def test_cloud_build_output_is_checked_without_flagging_immutable_vendor_builder() -> None:
    source = """steps:
- name: gcr.io/cloud-builders/docker@sha256:0123456789abcdef
  args: [build, .]
images:
- us-docker.pkg.dev/example-dev/images/app:$COMMIT_SHA
- us-docker.pkg.dev/$PROJECT_ID/images/app:$COMMIT_SHA
"""
    assert _findings(source, "cloudbuild/build.yaml") == [5]


def test_yaml_merged_env_is_reported_at_its_executable_use_site() -> None:
    source = """env: &shared
  GOOGLE_CLOUD_PROJECT: example-dev
jobs:
  publish:
    env:
      <<: *shared
    steps:
    - run: docker push "$IMAGE"
"""
    assert _findings(source, ".github/workflows/publish.yml") == [6]


@pytest.mark.parametrize(
    "path", ["envs.json", "tests/fixtures/publish.sh", "docs/publish.yaml", "scripts/dev/secrets.sh"]
)
def test_catalogs_fixture_paths_and_non_ci_configuration_are_outside_the_rule(path: str) -> None:
    assert _findings("gcloud --project=example-dev\n", path) == []


def test_explicit_generated_owner_header_is_preserved() -> None:
    assert _findings("# Generated by build-config. DO NOT EDIT.\ngcloud --project=example-dev\n") == []


def test_malformed_selected_yaml_does_not_look_clean() -> None:
    with pytest.raises(CloudBuildParseError):
        _findings("steps: [\n", "cloudbuild/build.yaml")


@pytest.mark.parametrize(
    ("configuration", "lines"),
    [
        ("defaults: {run: {shell: pwsh}}\n", []),
        ("defaults: {run: {shell: bash}}\n", [5]),
        ("", [4]),
    ],
)
def test_workflow_default_shell_is_respected(configuration: str, lines: list[int]) -> None:
    source = f"{configuration}jobs:\n  publish:\n    steps:\n    - run: gcloud --project=example-dev artifacts repositories list\n"
    assert _findings(source, ".github/workflows/publish.yml") == lines


def test_step_shell_overrides_windows_and_workflow_defaults() -> None:
    source = """defaults: {run: {shell: pwsh}}
jobs:
  publish:
    runs-on: windows-latest
    steps:
    - run: gcloud --project=example-dev artifacts repositories list
      shell: bash
"""
    assert _findings(source, ".github/workflows/publish.yml") == [6]


def test_implicit_windows_shell_is_outside_bash_analysis() -> None:
    source = "jobs:\n  publish:\n    runs-on: windows-latest\n    steps:\n    - run: gcloud --project=example-dev artifacts repositories list\n"
    assert _findings(source, ".github/workflows/publish.yml") == []


def test_unknown_yaml_duplicate_keys_do_not_expand_ci_scope() -> None:
    assert _findings("project: example-dev\nproject: example-prod\n", "config/settings.yml") == []


def test_exact_rule_comment_does_not_claim_unsupported_suppression() -> None:
    assert _findings("# sarj-noqa: SARJ316\ngcloud --project=example-dev artifacts repositories list\n") == [2]


def test_real_github_trigger_key_does_not_fail_cloud_build_mapping_validation() -> None:
    source = """on: {workflow_dispatch: {}}
jobs:
  publish:
    steps:
    - run: gcloud --project=example-dev artifacts repositories list
"""
    assert _findings(source, ".github/workflows/publish.yml") == [5]


@pytest.mark.parametrize("name", ["on", "off", "yes", "no"])
def test_github_job_and_environment_keys_preserve_yaml_12_strings(name: str) -> None:
    source = f"""jobs:
  {name}:
    env:
      {name}: true
    steps:
    - run: gcloud --project=example-dev artifacts repositories list
"""
    assert _findings(source, ".github/workflows/publish.yml") == [6]


@pytest.mark.parametrize("quote", ['"', ""])
def test_multiline_workflow_expression_preserves_commands_and_run_field_location(quote: str) -> None:
    source = f"""jobs:
  publish:
    steps:
    - run: |
        echo {quote}${{{{
          inputs.project
        }}}}{quote} gcloud --project=example-dev
        gcloud --project=example-prod artifacts repositories list
"""
    assert _findings(source, ".github/workflows/publish.yml") == [4]


@pytest.mark.parametrize(
    "run",
    [
        '"echo ready\\ngcloud --project=example-dev"',
        ">-\n        gcloud --project=example-dev\n        artifacts repositories list",
    ],
)
def test_yaml_scalar_formats_report_the_containing_field(run: str) -> None:
    source = f"jobs:\n  publish:\n    steps:\n    - run: {run}\n"
    assert _findings(source, ".github/workflows/publish.yml") == [4]
