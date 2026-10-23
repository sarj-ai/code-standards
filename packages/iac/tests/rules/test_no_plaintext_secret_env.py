from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint.rules.no_plaintext_secret_env import NoPlaintextSecretEnv


def _lines(source: str, path: str = "main.tf") -> list[int]:
    return [finding.line for finding in NoPlaintextSecretEnv().check(Path(path), source)]


def _service(env: str) -> str:
    return f'resource "google_cloud_run_v2_service" "api" {{\n  template {{\n    containers {{\n{env}    }}\n  }}\n}}\n'


def test_documented_examples() -> None:
    verify_native_rule(NoPlaintextSecretEnv, analyze)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        pytest.param("API_KEY", "var.api_key", id="api-key"),
        pytest.param("LIVEKIT_API_SECRET", "var.livekit_secret", id="secret-suffix"),
        pytest.param("DATABASE_PASSWORD", '"hunter2"', id="literal-password"),
        pytest.param("ADMIN_PASSWORD", '"123456"', id="numeric-password"),
        pytest.param("GITHUB_TOKEN", "local.github_token", id="token"),
        pytest.param("SIGNING_PRIVATE_KEY", '"${var.private_key}"', id="private-key"),
    ],
)
def test_reports_plain_secret_values(name: str, value: str) -> None:
    env = f'      env {{\n        name  = "{name}"\n        value = {value}\n      }}\n'
    assert _lines(_service(env)) == [6]


def test_reports_kubernetes_container_env() -> None:
    source = (
        'resource "kubernetes_deployment" "worker" {\n  spec {\n    template {\n      spec {\n        container {\n'
        '          env {\n            name  = "WEBHOOK_SECRET"\n            value = var.webhook_secret\n'
        "          }\n        }\n      }\n    }\n  }\n}\n"
    )
    assert _lines(source) == [8]


@pytest.mark.parametrize(
    "env",
    [
        pytest.param(
            '      env {\n        name  = "OTEL_ENABLED"\n        value = "false"\n      }\n', id="plain-setting"
        ),
        pytest.param(
            '      env {\n        name  = "TOKEN_TTL_SECONDS"\n        value = "300"\n      }\n', id="metadata"
        ),
        pytest.param('      env {\n        name  = "API_KEY"\n        value = ""\n      }\n', id="empty"),
        pytest.param(
            '      env {\n        name = "API_KEY"\n        value_source {\n          secret_key_ref {\n'
            '            secret = "api-key"\n          }\n        }\n      }\n',
            id="secret-reference",
        ),
        pytest.param("      env {\n        name  = each.key\n        value = each.value\n      }\n", id="dynamic-name"),
    ],
)
def test_allows_references_and_non_secret_settings(env: str) -> None:
    assert _lines(_service(env)) == []


def test_ignores_malformed_and_non_terraform_sources() -> None:
    env = '      env {\n        name  = "API_KEY"\n        value = var.api_key\n      }\n'
    assert _lines(_service(env)[:-3]) == []
    assert _lines(_service(env), path="values.tfvars") == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        pytest.param("SLACK_TOKEN_SECRET", "google_secret_manager_secret.slack.secret_id", id="secret-name-reference"),
        pytest.param("ALLOW_TOKEN", '"true"', id="boolean-flag"),
    ],
)
def test_allows_secret_names_and_non_secret_literals(name: str, value: str) -> None:
    env = f'      env {{\n        name  = "{name}"\n        value = {value}\n      }}\n'
    assert _lines(_service(env)) == []


@pytest.mark.parametrize(
    "value",
    [
        'format("projects/%s", google_secret_manager_secret.api.name)',
        "var.use_name ? google_secret_manager_secret.api.name : google_secret_manager_secret.api.secret_id",
    ],
)
def test_composed_public_metadata_remains_inert(value: str) -> None:
    env = f'      env {{\n        name = "API_KEY"\n        value = {value}\n      }}\n'
    assert _lines(_service(env)) == []
