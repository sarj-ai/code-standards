from __future__ import annotations

import json

import pytest

from sarj_iac_lint.module_outputs import unused_module_outputs


_CHILD = """resource "google_storage_bucket" "owned" {
  name = "owned"
}
output "used" {
  value = google_storage_bucket.owned.name
}
output "other" {
  value = google_storage_bucket.owned.url
}
"""


def _sources(expression: str, *, prelude: str = "") -> dict[str, str]:
    return {
        "root/main.tf": f"""module "child" {{
  source = "./child"
}}
{prelude}
resource "google_logging_metric" "consumer" {{
  name = {expression}
}}
""",
        "root/child/outputs.tf": _CHILD,
    }


def _names(sources: dict[str, str], *, external: tuple[tuple[str, str], ...] = ()) -> set[tuple[str, str]]:
    return {(item.path, item.name) for item in unused_module_outputs(sources, external_outputs=external)}


@pytest.mark.parametrize(
    "expression",
    [
        "module.child.used",
        'module.child["selected"].used',
        "module.child[each.key].used",
        "module.child[*].used",
        "module.child.*.used",
        'module.child["selected"]["used"]',
        '"bucket-${module.child.used}"',
        "<<EOT\n${module.child.used}\nEOT",
    ],
)
def test_named_traversals_keep_the_selected_export_only(expression: str) -> None:
    assert _names(_sources(expression)) == {("root/child/outputs.tf", "other")}


@pytest.mark.parametrize(
    "expression", ["module.child", "module.child[each.key][var.output]", "jsonencode(module.child)"]
)
def test_whole_objects_and_computed_output_selection_remain_consumers(expression: str) -> None:
    assert _names(_sources(expression)) == set()


def test_dead_local_alias_does_not_fabricate_a_consumer() -> None:
    sources = _sources('"consumer"', prelude="locals { unused = module.child }")
    assert _names(sources) == {("root/child/outputs.tf", name) for name in ["used", "other"]}


@pytest.mark.parametrize(
    ("prelude", "expression"),
    [
        ("locals { alias = module.child }", "local.alias.used"),
        ("locals { alias = module.child }", 'local.alias["used"]'),
        ("locals { alias = { selected = module.child.used\n ignored = module.child.other } }", "local.alias.selected"),
        ("locals { alias = var.choose ? module.child : null }", "local.alias.used"),
        ("locals { alias = try(module.child, null) }", "local.alias.used"),
    ],
)
def test_reachable_local_projections_resolve_precise_outputs(prelude: str, expression: str) -> None:
    assert _names(_sources(expression, prelude=prelude)) == {("root/child/outputs.tf", "other")}


def test_ternary_object_members_keep_both_reachable_branches() -> None:
    sources = _sources(
        "local.alias.selected",
        prelude="locals { alias = { selected = var.choose ? module.child.used : module.child.other } }",
    )
    assert _names(sources) == set()


def test_nested_reexports_and_unchanged_consumers_across_roots() -> None:
    sources = _sources("module.child.used")
    sources["other-root/main.tf"] = """module "shared" {
  source = "../root/child"
}
output "public" {
  value = module.shared.other
}
"""
    assert _names(sources) == set()
    sources["root/child/outputs.tf"] += """module "leaf" {
  source = "./leaf"
}
output "forwarded" {
  value = module.leaf.used
}
"""
    sources["root/child/leaf/outputs.tf"] = _CHILD
    sources["other-root/main.tf"] += 'output "leaf_contract" { value = module.shared.forwarded }\n'
    assert _names(sources) == {("root/child/leaf/outputs.tf", "other")}


def test_only_inputs_reached_by_actual_callee_values_keep_exports() -> None:
    sources = _sources('"consumer"')
    sources["root/main.tf"] += """module "receiving" {
  source = "./receiving"
  values = module.child
  unused = module.child.other
}
"""
    sources["root/receiving/main.tf"] = """variable "values" {}
variable "unused" {}
resource "google_logging_metric" "receiver" {
  name = var.values.used
}
"""
    assert _names(sources) == {("root/child/outputs.tf", "other")}


def test_external_module_arguments_are_consumers_even_before_local_module_declarations() -> None:
    sources = _sources("module.child.used")
    sources["root/main.tf"] = """module "external" {
  source = "example/consumer/provider"
  value = module.child.other
}
""" + sources["root/main.tf"]
    assert _names(sources) == set()


def test_ordering_comments_and_literal_lookalikes_do_not_consume_exports() -> None:
    sources = _sources('"module.child.other"', prelude="# module.child.used\n")
    sources["root/main.tf"] += 'module "ordered" { source = "./ordered"\n depends_on = [module.child] }\n'
    sources["root/ordered/main.tf"] = 'resource "google_storage_bucket" "ordered" { name = "ordered" }\n'
    assert _names(sources) == {("root/child/outputs.tf", name) for name in ["used", "other"]}


def test_justified_dependency_through_a_receiving_input_keeps_the_producer() -> None:
    sources = _sources("module.child.used")
    sources["root/main.tf"] += """module "receiving" {
  source = "./receiving"
  ready = module.child.other
}
"""
    sources["root/receiving/main.tf"] = """variable "ready" {}
resource "google_example" "ordered" {
  depends_on = [var.ready]
}
"""
    assert _names(sources) == set()


def test_root_standalone_and_explicit_external_output_contracts_remain() -> None:
    sources = _sources("module.child.used")
    sources["standalone/outputs.tf"] = _CHILD
    assert _names(sources, external=(("root/child", "other"),)) == set()
    sources["root/child/outputs.tf"] += 'terraform { backend "gcs" {} }\n'
    assert _names(sources) == set()


def test_dynamic_nested_content_and_interpolations_are_consumers() -> None:
    sources = _sources("module.child.used")
    sources["root/main.tf"] += """resource "google_example" "dynamic" {
  dynamic "entry" {
    for_each = var.entries
    content {
      value = "${module.child.other}"
    }
  }
}
"""
    assert _names(sources) == set()


@pytest.mark.parametrize("kind", ["resource", "data"])
def test_resource_description_values_keep_their_actual_producer(kind: str) -> None:
    sources = _sources("module.child.used")
    sources["root/main.tf"] += f"""{kind} "google_example" "described" {{
  description = module.child.other
}}
"""
    assert _names(sources) == set()


@pytest.mark.parametrize(
    "declaration",
    [
        "moved { from = module.child.google_example.old\n to = module.child.google_example.new }",
        "removed { from = module.child.google_example.old\n lifecycle { destroy = false } }",
        "import { to = module.child.google_example.imported\n id = module.child.other }",
    ],
)
def test_state_addresses_are_distinct_from_module_output_values(declaration: str) -> None:
    sources = _sources("module.child.used")
    sources["root/main.tf"] += declaration + "\n"
    expected: set[tuple[str, str]] = set() if declaration.startswith("import") else {("root/child/outputs.tf", "other")}
    assert _names(sources) == expected


def test_terraform_json_uses_templates_without_treating_plain_strings_as_references() -> None:
    sources = {
        "root/main.tf.json": json.dumps(
            {
                "module": {"child": {"source": "./child"}},
                "resource": {
                    "google_logging_metric": {
                        "consumer": {"name": "${module.child.used}", "description": "module.child.other"}
                    }
                },
            }
        ),
        "root/child/outputs.tf.json": json.dumps(
            {
                "output": {"used": {"value": "used"}, "other": {"value": "other"}},
            }
        ),
    }
    assert _names(sources) == {("root/child/outputs.tf.json", "other")}


@pytest.mark.parametrize(
    ("path", "content", "message"),
    [
        ("root/bad.tf", 'output "broken" { value = [', "Cannot establish Terraform consumers"),
        ("root/bad.tf.json", '{"output": {}, "output": {}}', "Duplicate Terraform JSON"),
        ("root/child/outputs.tf", 'module "missing" { source = "./missing" }', "absent from the selected source tree"),
        ("root/child/outputs.tf", 'module "parent" { source = var.source }', "Cannot establish the source"),
        ("root/child/outputs.tf", 'module "parent" { source = "../" }', "recursive|cycle"),
    ],
)
def test_incomplete_or_ambiguous_sources_cannot_prove_nonuse(path: str, content: str, message: str) -> None:
    sources = _sources("module.child.used")
    sources[path] = content
    with pytest.raises(ValueError, match=message):
        unused_module_outputs(sources)


@pytest.mark.parametrize(
    ("declaration", "message"),
    [
        ('output "invalid" "extra" { value = "literal" }', "Invalid Terraform output label count"),
        ('module { source = "./child" }', "Invalid Terraform module label count"),
        (
            'output "invalid" { value = module.child.used\n value = "replacement" }',
            "Duplicate Terraform attribute value",
        ),
        (
            'resource "example" "consumer" { lifecycle { prevent_destroy = true\n prevent_destroy = false } }',
            "Duplicate Terraform attribute prevent_destroy",
        ),
    ],
)
def test_invalid_declarations_do_not_establish_unused_outputs(declaration: str, message: str) -> None:
    sources = _sources('"consumer"')
    sources["root/main.tf"] += declaration + "\n"
    with pytest.raises(ValueError, match=message):
        unused_module_outputs(sources)


def test_duplicate_receiving_arguments_cannot_hide_the_original_output_consumer() -> None:
    sources = _sources('"consumer"')
    sources["root/main.tf"] += """module "receiver" {
  source = "./receiver"
  value = module.child.used
  value = "replacement"
}
"""
    sources["root/receiver/main.tf"] = 'variable "value" {}\nresource "example" "receiver" { value = var.value }\n'
    with pytest.raises(ValueError, match="Duplicate Terraform attribute value"):
        unused_module_outputs(sources)
