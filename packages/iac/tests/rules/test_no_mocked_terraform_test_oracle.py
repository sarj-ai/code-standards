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
            'override_module {\n  target = module.storage\n  outputs = { arn = "fixture-arn" }\n}',
            'module.storage.arn == "fixture-arn"',
            "module.storage.arn",
        ),
        (
            'override_module {\n  target = module.region\n  outputs = { name = "us-east-1" }\n}',
            '"us-east-1" == module.region.name',
            "module.region.name",
        ),
        (
            'override_module {\n  target = module.routing\n  outputs = { route = "private" }\n}',
            '(module.routing.route == "private")',
            "module.routing.route",
        ),
        (
            'override_module {\n  target = module.routing\n  outputs = { route = "private" }\n}',
            '((module.routing.route)) == (("private"))',
            "module.routing.route",
        ),
        (
            'override_module {\n  target = module.routing\n  outputs = { route = "private" }\n}',
            '((("private") == (module.routing.route)))',
            "module.routing.route",
        ),
    ],
)
def test_flags_direct_override_literal_reassertions(override: str, condition: str, expression: str) -> None:
    source = f'{override}\nrun "routing" {{\n  assert {{\n    condition = {condition}\n  }}\n}}\n'
    diagnostics = _check(source)
    assert [(item.code, item.suppressible, item.baselineable) for item in diagnostics] == [("SARJ206", True, True)]
    assert expression in diagnostics[0].message


@pytest.mark.parametrize(
    "condition",
    [
        '(module.routing.route == "private") && (var.enabled)',
        '(module.routing.route == "private") || (var.enabled)',
        '(module.routing.route) != ("private")',
        'upper(module.routing.route) == ("PRIVATE")',
        "(module.routing.route) == (var.expected)",
        '(module.routing.route) == ("private" + var.suffix)',
    ],
)
def test_parentheses_do_not_hide_an_additional_assertion(condition: str) -> None:
    source = (
        'override_module {\n target = module.routing\n outputs = { route = "private" }\n}\n'
        f'run "routing" {{\n assert {{\n condition = {condition}\n }}\n}}\n'
    )
    assert _check(source) == []


def test_flags_run_local_override_only_in_its_run() -> None:
    source = """
run "routing" {
  override_module {
    target = module.storage
    outputs = { arn = "fixture-arn" }
  }
  assert {
    condition = module.storage.arn == "fixture-arn"
  }
}
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize("run_values", ["", "outputs = {}", 'outputs = { id = "different" }'])
def test_run_override_shadows_entire_file_override_target(run_values: str) -> None:
    source = f"""
override_module {{
  target = module.storage
  outputs = {{ arn = "fixture-arn" }}
}}
run "routing" {{
  override_module {{
    target = module.storage
    {run_values}
  }}
  assert {{ condition = module.storage.arn == "fixture-arn" }}
}}
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    ("values", "condition"),
    [
        ('{ nested = { arn = "fixture-arn" } }', 'module.storage.arn == "fixture-arn"'),
        ('{ arn = "fixture-arn" + var.suffix }', 'module.storage.arn == "fixture-arn"'),
        ("{ enabled = true && var.enabled }", "module.storage.enabled == true"),
        ("{ size = 12 + var.size }", "module.storage.size == 12"),
        ('{ arn = "${var.fixture}" }', 'module.storage.arn == "${var.fixture}"'),
        (
            '{ arn = "%{if var.enabled}fixture%{endif}" }',
            'module.storage.arn == "%{if var.enabled}fixture%{endif}"',
        ),
        ('merge({ arn = "fixture-arn" }, var.values)', 'module.storage.arn == "fixture-arn"'),
        ('{ arn = "fixture-arn" }.nested', 'module.storage.arn == "fixture-arn"'),
        ('{ "nested.arn" = "fixture-arn" }', 'module.storage.arn == "fixture-arn"'),
        ('{ (var.key) = "fixture-arn" }', 'module.storage.arn == "fixture-arn"'),
        ('{ note = "arn = \\"fixture-arn\\"" }', 'module.storage.arn == "fixture-arn"'),
    ],
)
def test_excludes_non_direct_or_non_literal_object_entries(values: str, condition: str) -> None:
    source = f"""
override_module {{
  target = module.storage
  outputs = {values}
}}
run "routing" {{
  assert {{ condition = {condition} }}
}}
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    ("values", "condition"),
    [
        ('{ "arn" = "fixture-arn" }', 'module.storage.arn == "fixture-arn"'),
        ('{ "arn": "fixture-arn" }', 'module.storage.arn == "fixture-arn"'),
        ("{ size = -12.5 }", "module.storage.size == -12.5"),
        ('{ nested = { arn = "nested" }, arn = "fixture-arn" }', 'module.storage.arn == "fixture-arn"'),
        ('{ note = "arn = \\"nested\\"", arn = "fixture-arn" }', 'module.storage.arn == "fixture-arn"'),
        (r'{ arn = "fixture-\\\"arn" }', r'module.storage.arn == "fixture-\\\"arn"'),
        ('{ arn = "$${var.fixture}" }', 'module.storage.arn == "$${var.fixture}"'),
    ],
)
def test_complete_direct_literals_remain_active(values: str, condition: str) -> None:
    source = f"""
override_module {{
  target = module.storage
  outputs = {values}
}}
run "routing" {{
  assert {{ condition = {condition} }}
}}
"""
    assert len(_check(source)) == 1


def test_run_override_preserves_other_targets_and_uses_active_literal() -> None:
    source = """
override_module {
  target = module.storage
  outputs = { arn = "old" }
}
override_module {
  target = module.other
  outputs = { arn = "other" }
}
run "routing" {
  override_module {
    target = module.storage
    outputs = { arn = "active" }
  }
  assert { condition = module.storage.arn == "old" }
  assert { condition = module.storage.arn == "active" }
  assert { condition = module.other.arn == "other" }
}
"""
    assert len(_check(source)) == 2


@pytest.mark.parametrize(
    ("override", "target", "value_attribute"),
    [
        ("override_module", "module.storage", "outputs"),
        ("override_module", "module.region", "outputs"),
        ("override_module", "module.routing", "outputs"),
    ],
)
def test_target_shadowing_applies_to_each_module_target(override: str, target: str, value_attribute: str) -> None:
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
override_module {
  target = module.storage[0]
  outputs = { arn = "old" }
}
run "routing" {
  override_module {
    target = module.storage [ 0 ]
  }
  assert { condition = module.storage[0].arn == "old" }
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
  override_module {
    target = module.storage
    outputs = { arn = "fixture-arn" }
  }
}
run "routing" {
  assert {
    condition = module.storage.arn == "fixture-arn"
  }
}
"""
    assert _check(source) == []


@pytest.mark.parametrize("name", ["main.tf", "routing.hcl", "routing.tftest.json", "data.tfmock.hcl"])
def test_ignores_unsupported_files(name: str) -> None:
    source = (
        'override_module { target = module.storage outputs = { arn = "fixture-arn" } }\n'
        'run "routing" { assert { condition = module.storage.arn == "fixture-arn" } }\n'
    )
    assert _check(source, name) == []


def test_malformed_or_excessively_nested_hcl_abstains() -> None:
    nested = "x {" * 130 + "}" * 130
    assert _check(nested) == []


def test_reports_each_harmful_assertion_independently() -> None:
    source = """
override_module {
  target = module.storage
  outputs = { arn = "fixture-arn", id = "fixture-id" }
}
run "routing" {
  assert { condition = module.storage.arn == "fixture-arn" }
  assert { condition = module.storage.id == "fixture-id" }
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
        'override_module { target = module.storage outputs = { arn = "fixture-arn" } }\n'
        'run "routing" { assert { condition = module.storage.arn == "fixture-arn" '
        "# sarj-noqa: SARJ206\n} }\n",
        encoding="utf-8",
    )
    assert analyze(["no-mocked-terraform-test-oracle"], [path]) == []


def test_baseline_can_ratchet_existing_finding(tmp_path: Path) -> None:
    path = tmp_path / "routing.tftest.hcl"
    path.write_text(
        'override_module { target = module.storage outputs = { arn = "fixture-arn" } }\n'
        'run "routing" { assert { condition = module.storage.arn == "fixture-arn" } }\n',
        encoding="utf-8",
    )
    diagnostics = analyze(["no-mocked-terraform-test-oracle"], [path])
    assert apply_baseline(diagnostics, {str(path): {"SARJ206": 1}}) == []


@pytest.mark.parametrize("test_directory", ["", "tests"])
def test_resource_override_does_not_replace_explicitly_configured_attributes(
    tmp_path: Path, test_directory: str
) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "terraform_data" "sample" {\n  input = var.payload\n}\n', encoding="utf-8"
    )
    directory = tmp_path / test_directory
    directory.mkdir(exist_ok=True)
    path = directory / "overrides.tftest.hcl"
    source = """
override_resource {
  target = terraform_data.sample
  values = {
    input = "configured"
    output = "computed-fixture"
  }
}
run "configuration" {
  assert { condition = terraform_data.sample.input == "configured" }
  assert { condition = terraform_data.sample.output == "computed-fixture" }
}
"""
    path.write_text(source, encoding="utf-8")
    diagnostics = NoMockedTerraformTestOracle().check(path, source)
    assert diagnostics == []


@pytest.mark.parametrize(
    ("override", "target", "values", "condition"),
    [
        ("override_resource", "terraform_data.sample", "{ input = null }", "terraform_data.sample.input == null"),
        (
            "override_resource",
            "terraform_data.sample",
            '{ output = "computed-fixture" }',
            'terraform_data.sample.output == "computed-fixture"',
        ),
        (
            "override_data",
            "data.example_lookup.sample",
            "{ optional = false }",
            "data.example_lookup.sample.optional == false",
        ),
    ],
)
def test_provider_attributes_require_computed_provenance(
    override: str, target: str, values: str, condition: str
) -> None:
    source = f"""
{override} {{
  target = {target}
  values = {values}
}}
run "configuration" {{
  assert {{ condition = {condition} }}
}}
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    ("values", "condition"),
    [
        ('(\n { arn = "fixture-arn" }\n)', 'module.storage.arn == "fixture-arn"'),
        ('(( { arn = (("fixture-arn")) } ))', 'module.storage.arn == "fixture-arn"'),
        (r'{ arn = "\u0066ixture-arn" }', 'module.storage.arn == "fixture-arn"'),
        (r'{ "\U00000061rn" = "fixture-arn" }', 'module.storage.arn == "fixture-arn"'),
        ("{ size = (1e3) }", "module.storage.size == 1000"),
        ("{ size = -12.50 }", "module.storage.size == (-12.5)"),
        (r'{ arn = "$${var.fixture}" }', r'module.storage.arn == "\u0024{var.fixture}"'),
    ],
)
def test_equivalent_static_override_values_remain_self_repeating(values: str, condition: str) -> None:
    source = f'override_module {{\n target = module.storage\n outputs = {values}\n}}\nrun "routing" {{\n assert {{\n condition = {condition}\n }}\n}}\n'
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("values", "condition"),
    [
        ('({ arn = "fixture-arn" }).arn', 'module.storage.arn == "fixture-arn"'),
        ("{ size = true }", "module.storage.size == 1"),
        ('{ size = "1000" }', "module.storage.size == 1000"),
        ("{ size = (1e3 + var.extra) }", "module.storage.size == 1000"),
        (r'{ arn = "\uD800" }', r'module.storage.arn == "\uD800"'),
        ('{ arn = "$${literal}${var.suffix}" }', 'module.storage.arn == "$${literal}${var.suffix}"'),
    ],
)
def test_static_equivalence_does_not_cross_types_or_dynamic_expressions(values: str, condition: str) -> None:
    source = f'override_module {{\n target = module.storage\n outputs = {values}\n}}\nrun "routing" {{\n assert {{\n condition = {condition}\n }}\n}}\n'
    assert _check(source) == []
