from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_iac_lint.__main__ import analyze
from sarj_iac_lint.rules.no_project_secret_access_for_service_account import NoProjectSecretAccessForServiceAccount


def _count(source: str, path: str = "main.tf") -> int:
    return len(NoProjectSecretAccessForServiceAccount().check(Path(path), source))


def test_documented_examples() -> None:
    verify_native_rule(NoProjectSecretAccessForServiceAccount, analyze)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'resource "google_project_iam_member" "a" {\n  role = "roles/secretmanager.admin"\n'
            '  member = "serviceAccount:worker@p.iam.gserviceaccount.com"\n}\n',
            id="admin-literal-member",
        ),
        pytest.param(
            'resource "google_project_iam_binding" "a" {\n  role = "roles/secretmanager.secretAccessor"\n'
            '  members = ["group:eng@example.com", "serviceAccount:${var.sa_email}"]\n}\n',
            id="binding-members",
        ),
        pytest.param(
            'resource "google_project_iam_member" "a" {\n  for_each = toset(["roles/logging.viewer", '
            '"roles/secretmanager.secretAccessor"])\n  role = each.value\n'
            '  member = "serviceAccount:${google_service_account.api.email}"\n}\n',
            id="literal-for-each-roles",
        ),
    ],
)
def test_reports_project_secret_access_for_service_accounts(source: str) -> None:
    assert _count(source) == 1


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'resource "google_project_iam_member" "a" {\n  role = "roles/secretmanager.secretAccessor"\n'
            '  member = "group:eng@example.com"\n}\n',
            id="human-group",
        ),
        pytest.param(
            'resource "google_project_iam_member" "a" {\n  role = "roles/secretmanager.viewer"\n'
            '  member = "serviceAccount:${var.sa_email}"\n}\n',
            id="metadata-only-role",
        ),
        pytest.param(
            'resource "google_project_iam_member" "a" {\n  role = var.role\n  member = "serviceAccount:${var.sa}"\n}\n',
            id="unknown-role",
        ),
        pytest.param(
            'resource "google_project_iam_member" "a" {\n  role = "roles/secretmanager.secretAccessor"\n'
            "  member = var.member\n}\n",
            id="unknown-member",
        ),
        pytest.param(
            'resource "google_folder_iam_member" "a" {\n  role = "roles/secretmanager.secretAccessor"\n'
            '  member = "serviceAccount:${var.sa}"\n}\n',
            id="folder-grant",
        ),
        pytest.param(
            'resource "google_project_iam_member" "a" {\n  role = "roles/secretmanager.admin"\n', id="malformed"
        ),
    ],
)
def test_allows_scoped_or_unproven_grants(source: str) -> None:
    assert _count(source) == 0


def test_ignores_non_terraform_files() -> None:
    source = (
        'resource "google_project_iam_member" "a" { role = "roles/secretmanager.admin" member = "serviceAccount:x" }'
    )
    assert _count(source, path="main.tfvars") == 0


def test_allows_conditional_grant_scoped_to_named_secrets() -> None:
    source = (
        'resource "google_project_iam_member" "a" {\n  role = "roles/secretmanager.secretAccessor"\n'
        '  member = "serviceAccount:worker@p.iam.gserviceaccount.com"\n'
        '  condition {\n    title = "app secrets"\n    expression = "resource.name.startsWith(\'projects/1/secrets/app-\')"\n  }\n}\n'
    )
    assert [f.line for f in NoProjectSecretAccessForServiceAccount().check(Path("main.tf"), source)] == []
