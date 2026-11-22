from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest
from sarj_rule_contracts.examples import ExampleFinding, verify_examples

from sarj_iac_lint.autofix import fix_source
from sarj_iac_lint.rules.no_unused_module_inputs import NoUnusedModuleInputs


def test_documented_examples() -> None:
    spec = NoUnusedModuleInputs.native_spec()
    assert spec is not None

    def analyze(root: Path, _focus: Path) -> list[ExampleFinding]:
        return [
            ExampleFinding(d.path, d.line, d.col, d.code, d.message)
            for d in NoUnusedModuleInputs.check_project(
                root,
                {PurePosixPath(path.relative_to(root)): path.read_text() for path in root.rglob("*.tf")},
                internal_modules=("child",),
            )
        ]

    assert verify_examples(spec.examples, analyze, expected_code="SARJ225") == 2


def _findings(sources: dict[str, str], *, internal: tuple[str, ...] = ("child",)) -> set[str]:
    return {
        finding.message.split("'")[1]
        for finding in NoUnusedModuleInputs.check_project(
            Path("/example"),
            {PurePosixPath(path): source for path, source in sources.items()},
            internal_modules=internal,
        )
    }


def _sources(consumer: str = "locals { unused = var.config }\n") -> dict[str, str]:
    return {
        "main.tf": 'module "child" {\n source = "./child"\n config = "west"\n}\n',
        "child/variables.tf": 'variable "config" { type = string }\n',
        "child/main.tf": consumer,
    }


@pytest.mark.parametrize(
    "consumer",
    [
        'resource "example" "live" { value = var.config }',
        'output "public" { value = var.config }',
        'module "external" {\n source = "vendor/service/example"\n config = var.config\n}',
        'resource "example" "live" { value = "${var.config}" }',
        'resource "example" "live" {\n dynamic "entry" {\n for_each = [var.config]\n content { value = entry.value }\n }\n}',
    ],
)
def test_real_consumers_retain_inputs(consumer: str) -> None:
    sources = _sources(consumer)
    if consumer.startswith("output"):
        sources["main.tf"] += 'output "export" { value = module.child.public }\n'
    assert _findings(sources) == set()


def test_native_unused_declarations_and_public_interfaces_are_not_duplicated() -> None:
    assert _findings(_sources("")) == set()
    assert _findings(_sources(), internal=()) == set()


def test_transitive_forwarding_and_multiple_roots() -> None:
    sources = _sources('module "leaf" {\n source = "./leaf"\n config = var.config\n}\n')
    sources["child/leaf/main.tf"] = 'variable "config" { type = string }\nlocals { unused = var.config }\n'
    assert _findings(sources, internal=("child", "child/leaf")) == {"config"}
    sources["second/main.tf"] = (
        'module "leaf" {\n source = "../child/leaf"\n config = "east"\n}\noutput "live" { value = module.leaf.live }\n'
    )
    sources["child/leaf/main.tf"] += 'output "live" { value = var.config }\n'
    assert _findings(sources, internal=("child", "child/leaf")) == {"config"}
    sources["child/main.tf"] += 'output "live" { value = module.leaf.live }\n'
    sources["main.tf"] += 'output "live" { value = module.child.live }\n'
    assert _findings(sources, internal=("child", "child/leaf")) == set()


@pytest.mark.parametrize("projection", ["var.config.keep", "var.config", "var.config[var.key]"])
def test_object_projection_and_dynamic_access(projection: str) -> None:
    sources = _sources()
    sources["child/variables.tf"] = 'variable "config" { type = any }\nvariable "key" { default = "keep" }\n'
    sources["child/main.tf"] = f'resource "example" "live" {{ value = {projection} }}\n'
    assert _findings(sources) == set()


def test_validation_and_preconditions_preserve_startup_failure_contracts() -> None:
    sources = _sources("")
    sources["child/variables.tf"] = (
        'variable "config" {\n type = string\n validation {\n condition = length(var.config) > 0\n error_message = "Required"\n }\n}\n'
    )
    assert _findings(sources) == set()
    sources = _sources(
        'output "guard" {\n value = true\n precondition {\n condition = var.config != ""\n error_message = "Required"\n }\n}\n'
    )
    assert _findings(sources) == set()


def test_json_configuration_uses_the_same_graph() -> None:
    sources = _sources()
    sources.pop("child/main.tf")
    sources["child/main.tf.json"] = json.dumps({"locals": {"unused": "${var.config}"}})
    assert _findings(sources) == {"config"}
    sources["child/main.tf.json"] = json.dumps({"resource": {"example": {"live": {"value": "${var.config}"}}}})
    assert _findings(sources) == set()


@pytest.mark.parametrize("fault", ["missing", "malformed", "override"])
def test_incomplete_evidence_never_proves_nonuse(fault: str) -> None:
    sources = _sources()
    match fault:
        case "missing":
            sources.pop("child/variables.tf")
            sources.pop("child/main.tf")
        case "malformed":
            sources["child/main.tf"] = 'resource "example" "bad" {'
        case _:
            sources["override.tf"] = 'module "child" { config = "changed" }'
    with pytest.raises(ValueError, match=r"absent|Cannot|prevent"):
        _findings(sources)


def test_file_local_and_fix_apis_preserve_interfaces() -> None:
    source = 'variable "config" { type = string }\n'
    assert NoUnusedModuleInputs().check(Path("variables.tf"), source) == []
    assert fix_source(Path("variables.tf"), source, rule_ids=(NoUnusedModuleInputs.id,)) == source


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("crlf", [False, True])
def test_project_suppression_requires_the_exact_reviewed_rule_code(*, selected: bool, crlf: bool) -> None:
    sources = _sources()
    code = NoUnusedModuleInputs.code if selected else "SARJ999"
    declaration = f'variable "config" {{ type = string }} # sarj-noqa: {code} -- fixture exception identity\n'
    sources["child/variables.tf"] = declaration.replace("\n", "\r\n") if crlf else declaration
    assert _findings(sources) == (set() if selected else {"config"})
