from pathlib import Path

import pytest

from sarj_iac_lint.__main__ import analyze, apply_baseline
from sarj_iac_lint.rules.no_mocked_terraform_test_oracle import NoMockedTerraformTestOracle


def _check(source: str, name: str = "routing.tftest.hcl"):
    return NoMockedTerraformTestOracle().check(Path(name), source)


@pytest.mark.parametrize(
    ("override", "condition", "expression"),
    [
        (
            'override_resource {\n  target = aws_s3_bucket.main\n  values = { arn = "fixture-arn" }\n}',
            'aws_s3_bucket.main.arn == "fixture-arn"',
            "aws_s3_bucket.main.arn",
        ),
        (
            'override_data {\n  target = data.aws_region.current\n  values = { name = "us-east-1" }\n}',
            '"us-east-1" == data.aws_region.current.name',
            "data.aws_region.current.name",
        ),
        (
            'override_module {\n  target = module.routing\n  outputs = { route = "private" }\n}',
            '(module.routing.route == "private")',
            "module.routing.route",
        ),
    ],
)
def test_flags_direct_override_literal_reassertions(override: str, condition: str, expression: str) -> None:
    source = f'{override}\nrun "routing" {{\n  assert {{\n    condition = {condition}\n  }}\n}}\n'
    diagnostics = _check(source)
    assert [(item.code, item.suppressible, item.baselineable) for item in diagnostics] == [("SARJ206", True, True)]
    assert expression in diagnostics[0].message


def test_flags_run_local_override_only_in_its_run() -> None:
    source = """
run "routing" {
  override_resource {
    target = aws_s3_bucket.main
    values = { arn = "fixture-arn" }
  }
  assert {
    condition = aws_s3_bucket.main.arn == "fixture-arn"
  }
}
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'mock_provider "aws" {}\nrun "plan" { command = plan }\n',
        (
            'mock_provider "aws" {}\nrun "routing" {\n  command = plan\n  assert {\n'
            "    condition = aws_s3_bucket.main.bucket == var.bucket_name\n  }\n}\n"
        ),
        (
            'override_resource { target = aws_s3_bucket.main values = { arn = "fixture-arn" } }\n'
            'run "routing" { assert { condition = upper(aws_s3_bucket.main.arn) == "FIXTURE-ARN" } }\n'
        ),
        (
            'override_resource { target = aws_s3_bucket.main values = { arn = "fixture-arn" } }\n'
            'run "routing" { assert { condition = aws_s3_bucket.other.arn == "fixture-arn" } }\n'
        ),
        (
            'mock_provider "aws" { override_resource { target = aws_s3_bucket.main '
            'values = { arn = "fixture-arn" } } }\n'
            'run "routing" { assert { condition = aws_s3_bucket.main.arn == "fixture-arn" } }\n'
        ),
    ],
)
def test_allows_mock_backed_configuration_and_non_tautological_assertions(source: str) -> None:
    assert _check(source) == []


def test_run_local_override_does_not_leak_to_another_run() -> None:
    source = """
run "setup" {
  override_resource {
    target = aws_s3_bucket.main
    values = { arn = "fixture-arn" }
  }
}
run "routing" {
  assert {
    condition = aws_s3_bucket.main.arn == "fixture-arn"
  }
}
"""
    assert _check(source) == []


@pytest.mark.parametrize("name", ["main.tf", "routing.hcl", "routing.tftest.json", "data.tfmock.hcl"])
def test_ignores_unsupported_files(name: str) -> None:
    source = (
        'override_resource { target = aws_s3_bucket.main values = { arn = "fixture-arn" } }\n'
        'run "routing" { assert { condition = aws_s3_bucket.main.arn == "fixture-arn" } }\n'
    )
    assert _check(source, name) == []


def test_malformed_or_excessively_nested_hcl_abstains() -> None:
    nested = "x {" * 130 + "}" * 130
    assert _check(nested) == []


def test_reports_each_harmful_assertion_independently() -> None:
    source = """
override_resource {
  target = aws_s3_bucket.main
  values = { arn = "fixture-arn", id = "fixture-id" }
}
run "routing" {
  assert { condition = aws_s3_bucket.main.arn == "fixture-arn" }
  assert { condition = aws_s3_bucket.main.id == "fixture-id" }
}
"""
    assert len(_check(source)) == 2


def test_public_examples_execute() -> None:
    examples = NoMockedTerraformTestOracle.public_examples()
    assert [len(_check(example.focus_file.source)) for example in examples] == [
        example.expected_count for example in examples
    ]


def test_inline_suppression_documents_exception(tmp_path: Path) -> None:
    path = tmp_path / "routing.tftest.hcl"
    path.write_text(
        'override_resource { target = aws_s3_bucket.main values = { arn = "fixture-arn" } }\n'
        'run "routing" { assert { condition = aws_s3_bucket.main.arn == "fixture-arn" '
        "# sarj-noqa: SARJ206\n} }\n",
        encoding="utf-8",
    )
    assert analyze(["no-mocked-terraform-test-oracle"], [path]) == []


def test_baseline_can_ratchet_existing_finding(tmp_path: Path) -> None:
    path = tmp_path / "routing.tftest.hcl"
    path.write_text(
        'override_resource { target = aws_s3_bucket.main values = { arn = "fixture-arn" } }\n'
        'run "routing" { assert { condition = aws_s3_bucket.main.arn == "fixture-arn" } }\n',
        encoding="utf-8",
    )
    diagnostics = analyze(["no-mocked-terraform-test-oracle"], [path])
    assert apply_baseline(diagnostics, {str(path): {"SARJ206": 1}}) == []
