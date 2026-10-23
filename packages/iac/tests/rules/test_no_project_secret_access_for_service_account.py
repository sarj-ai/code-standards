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


@pytest.mark.parametrize(
    "role",
    [
        pytest.param('"roles/\\u0073ecretmanager.secretAccessor"', id="escaped-role"),
        pytest.param('join("", ["roles/secret", "manager.secretAccessor"])', id="joined-role"),
        pytest.param("local.role", id="local-role"),
    ],
)
def test_static_roles_do_not_require_a_raw_secretmanager_word(role: str) -> None:
    source = (
        'locals { role = join("", ["roles/secret", "manager.secretAccessor"]) }\n'
        'resource "google_project_iam_member" "app" {\n'
        f"  role = {role}\n"
        '  member = "serviceAccount:worker@example.com"\n}\n'
    )
    findings = NoProjectSecretAccessForServiceAccount().check(Path("main.tf"), source)
    assert [(finding.code, finding.line, finding.col) for finding in findings] == [("SARJ213", 2, 1)]


@pytest.mark.parametrize(
    ("member_attribute", "expected"),
    [
        ('member = ("serviceAccount:worker@example.com")', 1),
        ('member = "\\u0073erviceAccount:worker@example.com"', 1),
        ('member = "\\u0073erviceAccount:${var.email}"', 1),
        ('member = "serviceAccount\\u003a${var.email}"', 1),
        ('member = "\\u0067roup:serviceAccount:${var.email}"', 0),
        ('member = "${var.kind}:\\u0073erviceAccount:${var.email}"', 0),
        ('members = [("serviceAccount:${var.email}"), "group:eng@example.com"]', 1),
        ('members = toset(["serviceAccount:${var.email}", "group:eng@example.com"])', 1),
        ('members = tolist((["serviceAccount:worker@example.com"]))', 1),
        ('members = toset(tolist(["serviceAccount:worker@example.com"]))', 1),
        ('members = custom(["serviceAccount:worker@example.com"])', 0),
        ('members = toset([replace("serviceAccount:worker@example.com", "serviceAccount:", "group:")])', 0),
        ('members = tolist(["group:serviceAccount:eng@example.com"])', 0),
        ('member = replace("serviceAccount:worker@example.com", "serviceAccount:", "group:")', 0),
        (
            'member = var.member == "serviceAccount:worker@example.com" ? "group:a@example.com" : "group:b@example.com"',
            0,
        ),
        ('members = [replace("serviceAccount:worker@example.com", "serviceAccount:", "group:")]', 0),
        ('member = "${var.kind}:serviceAccount:worker@example.com"', 0),
    ],
)
def test_member_expressions_prove_the_granted_identity(member_attribute: str, expected: int) -> None:
    resource_type = (
        "google_project_iam_binding" if member_attribute.startswith("members") else "google_project_iam_member"
    )
    source = (
        f'resource "{resource_type}" "app" {{\n'
        '  role = "roles/secretmanager.secretAccessor"\n'
        f"  {member_attribute}\n}}\n"
    )
    assert _count(source) == expected


def test_deep_collection_conversions_remain_a_bounded_unknown() -> None:
    member = "toset(" * 1000 + '["serviceAccount:worker@example.com"]' + ")" * 1000
    source = (
        'resource "google_project_iam_binding" "app" {\n'
        '  role = "roles/secretmanager.secretAccessor"\n'
        f"  members = {member}\n}}\n"
    )
    assert _count(source) == 0
