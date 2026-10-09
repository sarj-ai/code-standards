from __future__ import annotations

from pathlib import Path

import pytest

from sarj_iac_lint.rules.no_project_basic_privilege import NoProjectBasicPrivilege


@pytest.mark.parametrize(
    ("role", "count"),
    [
        ('"roles/owner"', 1),
        ('"roles/editor"', 1),
        ('"roles/viewer"', 0),
        ('"roles/storage.admin"', 0),
        ("var.role", 0),
        ('"${var.role}"', 0),
    ],
)
def test_literal_roles(role: str, count: int) -> None:
    source = f'resource "google_project_iam_binding" "app" {{ role = {role} }}'
    assert len(NoProjectBasicPrivilege().check(Path("main.tf"), source)) == count


@pytest.mark.parametrize(
    ("source", "count"),
    [
        ('resource "google_folder_iam_member" "app" { role = "roles/editor" }', 0),
        (
            'resource "google_project_iam_member" "app" { role = each.value\nfor_each = toset(["roles/editor", "roles/viewer"]) }',
            1,
        ),
        (
            'resource "google_project_iam_member" "app" { role = each.key\nfor_each = toset([var.role, "roles/editor"]) }',
            0,
        ),
        (
            'resource "google_project_iam_policy" "app" { policy_data = jsonencode({bindings = [{role = "roles/editor", members = []}]}) }',
            1,
        ),
        ('resource "google_project_iam_policy" "app" { policy_data = jsonencode({members = ["roles/editor"]}) }', 0),
        (
            'resource "google_project_iam_policy" "app" { policy_data = jsonencode({metadata = {role = "roles/editor"}}) }',
            0,
        ),
        (
            'resource "google_project_iam_policy" "app" { policy_data = jsonencode({bindings = [{role = var.role}]}) }',
            0,
        ),
        (
            'data "google_iam_policy" "app" { binding { role = "roles/owner" } }\nresource "google_project_iam_policy" "app" { policy_data = data.google_iam_policy.app.policy_data }',
            1,
        ),
        ('data "google_iam_policy" "app" { binding { role = "roles/owner" } }', 0),
        ('resource "google_project_iam_policy" "app" { policy_data = data.google_iam_policy.unknown.policy_data }', 0),
        ('resource "google_project_iam_member" "app" { role = "roles/editor"', 0),
    ],
)
def test_policy_shapes(source: str, count: int) -> None:
    assert len(NoProjectBasicPrivilege().check(Path("main.tf"), source)) == count


def test_findings_are_deterministic() -> None:
    source = '\nresource "google_project_iam_member" "app" { role = "roles/editor" }'
    findings = NoProjectBasicPrivilege().check(Path("main.tf"), source)
    assert [(finding.line, finding.col, finding.code) for finding in findings] == [(2, 1, "SARJ212")]
    assert findings == NoProjectBasicPrivilege().check(Path("main.tf"), source)


def test_role_comparison_is_not_a_literal_grant() -> None:
    source = 'resource "google_project_iam_policy" "app" { policy_data = jsonencode({bindings = [{role = "roles/editor" == var.role ? "roles/viewer" : "roles/viewer"}]}) }'
    assert NoProjectBasicPrivilege().check(Path("main.tf"), source) == []


def test_jsonencode_colon_object_form_is_a_grant() -> None:
    source = 'resource "google_project_iam_policy" "app" { policy_data = jsonencode({"bindings": [{"role": "roles/editor"}]}) }'
    assert len(NoProjectBasicPrivilege().check(Path("main.tf"), source)) == 1
