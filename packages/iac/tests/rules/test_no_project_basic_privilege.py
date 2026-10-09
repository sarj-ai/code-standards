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


@pytest.mark.parametrize(
    ("source", "expected", "path"),
    [
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/owner"\n}\n', 1, "main.tf", id="owner"
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/editor"\n}\n', 1, "main.tf", id="editor"
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = ("roles/editor")\n}\n', 1, "main.tf", id="grouped"
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = ((("roles/owner")))\n}\n', 1, "main.tf", id="nested"
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/\\U00000065ditor"\n}\n',
            1,
            "main.tf",
            id="long-escape",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/\\u0065ditor"\n}\n',
            1,
            "main.tf",
            id="short-escape",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = (("roles/\\U0000006fwner"))\n}\n',
            1,
            "main.tf",
            id="grouped-long-escape",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = (("roles/\\u0065ditor"))\n}\n',
            1,
            "main.tf",
            id="grouped-short-escape",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/viewer"\n}\n', 0, "main.tf", id="viewer"
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = (("roles/viewer"))\n}\n',
            0,
            "main.tf",
            id="grouped-viewer",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/logging.logWriter"\n}\n',
            0,
            "main.tf",
            id="specific",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = (("roles/storage.admin"))\n}\n',
            0,
            "main.tf",
            id="grouped-specific",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = var.role\n}\n', 0, "main.tf", id="dynamic"
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = ((var.role))\n}\n',
            0,
            "main.tf",
            id="grouped-dynamic",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/${var.role}"\n}\n',
            0,
            "main.tf",
            id="template",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/$${var.role}"\n}\n',
            0,
            "main.tf",
            id="literal-template",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/%%{editor}"\n}\n',
            0,
            "main.tf",
            id="literal-directive",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/%{if true}editor%{endif}"\n}\n',
            0,
            "main.tf",
            id="directive",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/editor" == "roles/editor"\n}\n',
            0,
            "main.tf",
            id="comparison",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = true ? "roles/editor" : "roles/viewer"\n}\n',
            0,
            "main.tf",
            id="conditional",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = ((true ? "roles/editor" : "roles/viewer"))\n}\n',
            0,
            "main.tf",
            id="grouped-conditional",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles\\/editor"\n}\n',
            0,
            "main.tf",
            id="slash-escaped",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/\\qditor"\n}\n',
            0,
            "main.tf",
            id="invalid-escape",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/\\uD800editor"\n}\n',
            0,
            "main.tf",
            id="surrogate",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/\\U00110000editor"\n}\n',
            0,
            "main.tf",
            id="outside-unicode",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n  role = "roles/\\\\U00000065ditor"\n}\n',
            0,
            "main.tf",
            id="escaped-backslash",
        ),
        pytest.param(
            'resource "google_folder_iam_member" "app" {\n  role = (("roles/\\U00000065ditor"))\n}\n',
            0,
            "main.tf",
            id="nonproject-google_folder_iam_member",
        ),
        pytest.param(
            'resource "google_organization_iam_binding" "app" {\n  role = (("roles/\\U00000065ditor"))\n}\n',
            0,
            "main.tf",
            id="nonproject-google_organization_iam_binding",
        ),
        pytest.param('data "google_project_iam_member" "app" { role = "roles/editor" }', 0, "main.tf", id="data-only"),
        pytest.param(
            '# resource "google_project_iam_member" "app" { role = "roles/editor" }', 0, "main.tf", id="comment-only"
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" { role = (("roles/editor"))', 0, "main.tf", id="malformed-block"
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" { role = each.value\nfor_each = toset(["roles/\\U00000065ditor", "roles/viewer"]) }',
            1,
            "main.tf",
            id="for-each-long-escape",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" { role = each.value\nfor_each = toset([var.role, "roles/editor"]) }',
            0,
            "main.tf",
            id="for-each-dynamic",
        ),
        pytest.param(
            'resource "google_project_iam_policy" "app" { policy_data = jsonencode({bindings = [{role = "roles/\\U00000065ditor", members = []}]}) }',
            1,
            "main.tf",
            id="policy-long-escape",
        ),
        pytest.param(
            'resource "google_project_iam_policy" "app" { policy_data = jsonencode({bindings = [{role = "roles/editor" == var.role ? "roles/viewer" : "roles/viewer"}]}) }',
            0,
            "main.tf",
            id="policy-comparison",
        ),
        pytest.param(
            'data "google_iam_policy" "app" { binding { role = (("roles/\\U00000065ditor")) } }\nresource "google_project_iam_policy" "app" { policy_data = data.google_iam_policy.app.policy_data }',
            1,
            "main.tf",
            id="data-policy-grouped",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" { role = "roles/editor" }', 0, "main.tf.json", id="wrong-suffix"
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n role = "roles/editor",\n}\n',
            0,
            "main.tf",
            id="malformed-block-comma",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n role = ("roles/editor",)\n}\n',
            0,
            "main.tf",
            id="malformed-group-comma",
        ),
        pytest.param(
            'resource "google_project_iam_member" "app" {\n role = ("roles/editor"),\n}\n',
            0,
            "main.tf",
            id="malformed-group-outer-comma",
        ),
    ],
)
def test_proven_literal_roles_preserve_hcl_semantics(source: str, expected: int, path: str) -> None:
    rule = NoProjectBasicPrivilege()
    findings = rule.check(Path(path), source)
    assert len(findings) == expected
    assert all(finding.code == "SARJ212" for finding in findings)
    assert len({(finding.line, finding.col, finding.code) for finding in findings}) == len(findings)
    assert rule.check(Path(path), source) == findings
