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


@pytest.mark.parametrize("run_values", ["", "values = {}", 'values = { id = "different" }'])
def test_run_override_shadows_entire_file_override_target(run_values: str) -> None:
    source = f"""
override_resource {{
  target = aws_s3_bucket.main
  values = {{ arn = "fixture-arn" }}
}}
run "routing" {{
  override_resource {{
    target = aws_s3_bucket.main
    {run_values}
  }}
  assert {{ condition = aws_s3_bucket.main.arn == "fixture-arn" }}
}}
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    ("values", "condition"),
    [
        ('{ nested = { arn = "fixture-arn" } }', 'aws_s3_bucket.main.arn == "fixture-arn"'),
        ('{ arn = "fixture-arn" + var.suffix }', 'aws_s3_bucket.main.arn == "fixture-arn"'),
        ("{ enabled = true && var.enabled }", "aws_s3_bucket.main.enabled == true"),
        ("{ size = 12 + var.size }", "aws_s3_bucket.main.size == 12"),
        ('{ arn = "${var.fixture}" }', 'aws_s3_bucket.main.arn == "${var.fixture}"'),
        (
            '{ arn = "%{if var.enabled}fixture%{endif}" }',
            'aws_s3_bucket.main.arn == "%{if var.enabled}fixture%{endif}"',
        ),
        ('merge({ arn = "fixture-arn" }, var.values)', 'aws_s3_bucket.main.arn == "fixture-arn"'),
        ('{ arn = "fixture-arn" }.nested', 'aws_s3_bucket.main.arn == "fixture-arn"'),
        ('{ "nested.arn" = "fixture-arn" }', 'aws_s3_bucket.main.arn == "fixture-arn"'),
        ('{ (var.key) = "fixture-arn" }', 'aws_s3_bucket.main.arn == "fixture-arn"'),
        ('{ note = "arn = \\"fixture-arn\\"" }', 'aws_s3_bucket.main.arn == "fixture-arn"'),
    ],
)
def test_excludes_non_direct_or_non_literal_object_entries(values: str, condition: str) -> None:
    source = f"""
override_resource {{
  target = aws_s3_bucket.main
  values = {values}
}}
run "routing" {{
  assert {{ condition = {condition} }}
}}
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    ("values", "condition"),
    [
        ('{ "arn" = "fixture-arn" }', 'aws_s3_bucket.main.arn == "fixture-arn"'),
        ('{ "arn": "fixture-arn" }', 'aws_s3_bucket.main.arn == "fixture-arn"'),
        ("{ size = -12.5 }", "aws_s3_bucket.main.size == -12.5"),
        ('{ nested = { arn = "nested" }, arn = "fixture-arn" }', 'aws_s3_bucket.main.arn == "fixture-arn"'),
        ('{ note = "arn = \\"nested\\"", arn = "fixture-arn" }', 'aws_s3_bucket.main.arn == "fixture-arn"'),
        (r'{ arn = "fixture-\\\"arn" }', r'aws_s3_bucket.main.arn == "fixture-\\\"arn"'),
        ('{ arn = "$${var.fixture}" }', 'aws_s3_bucket.main.arn == "$${var.fixture}"'),
    ],
)
def test_complete_direct_literals_remain_active(values: str, condition: str) -> None:
    source = f"""
override_resource {{
  target = aws_s3_bucket.main
  values = {values}
}}
run "routing" {{
  assert {{ condition = {condition} }}
}}
"""
    assert len(_check(source)) == 1


def test_run_override_preserves_other_targets_and_uses_active_literal() -> None:
    source = """
override_resource {
  target = aws_s3_bucket.main
  values = { arn = "old" }
}
override_resource {
  target = aws_s3_bucket.other
  values = { arn = "other" }
}
run "routing" {
  override_resource {
    target = aws_s3_bucket.main
    values = { arn = "active" }
  }
  assert { condition = aws_s3_bucket.main.arn == "old" }
  assert { condition = aws_s3_bucket.main.arn == "active" }
  assert { condition = aws_s3_bucket.other.arn == "other" }
}
"""
    assert len(_check(source)) == 2


@pytest.mark.parametrize(
    ("override", "target", "value_attribute"),
    [
        ("override_resource", "aws_s3_bucket.main", "values"),
        ("override_data", "data.aws_region.current", "values"),
        ("override_module", "module.routing", "outputs"),
    ],
)
def test_target_shadowing_applies_to_every_override_kind(override: str, target: str, value_attribute: str) -> None:
    source = f"""
{override} {{
  target = {target}
  {value_attribute} = {{ name = "old" }}
}}
run "routing" {{
  {override} {{
    target = {target}
  }}
  assert {{ condition = {target}.name == "old" }}
}}
"""
    assert _check(source) == []


def test_target_shadowing_ignores_index_whitespace() -> None:
    source = """
override_resource {
  target = aws_s3_bucket.main[0]
  values = { arn = "old" }
}
run "routing" {
  override_resource {
    target = aws_s3_bucket.main [ 0 ]
  }
  assert { condition = aws_s3_bucket.main[0].arn == "old" }
}
"""
    assert _check(source) == []


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
