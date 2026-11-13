from dataclasses import fields
from pathlib import Path
import traceback
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator
import pytest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012, Schema

from sarj_iac_lint.architecture import ArchitectureAnnotationError, calm_decorator, parse_module_annotation
from sarj_iac_lint.architecture_types import MinView, ModuleArchitecture, Replacement
from sarj_iac_lint.generate_architecture_types import SCHEMA_PATH, TYPES_PATH, annotation_schema, render_types
from sarj_iac_lint.json_boundary import parse_json
from sarj_iac_lint.rules.no_terraform_comments import NoTerraformComments


if TYPE_CHECKING:
    from jsonschema.protocols import Validator


_BODY = 'resource "example_bucket" "storage" {}\n'
_HEADER = "# Object storage @architecture overview migration"


@pytest.mark.parametrize("view", list(MinView))
@pytest.mark.parametrize("replacement", list(Replacement))
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_typed_header_and_legacy_opt_in(view: MinView, replacement: Replacement, newline: str) -> None:
    source = newline.join([f"# Object storage @architecture {view} {replacement}", "", _BODY])

    assert parse_module_annotation(Path("main.tf"), source) == ModuleArchitecture("Object storage", view, replacement)
    assert NoTerraformComments(module_summaries=True).check(Path("main.tf"), source) == []
    assert len(NoTerraformComments().check(Path("main.tf"), source)) == 1


@pytest.mark.parametrize(
    "header",
    [
        "# Storage @architecture",
        "# Storage @architecture overview",
        "# Storage @architecture overview migration extra",
        "# Storage @architecture overview swappable",
        "# Storage @architecture basic unknown",
        "# Storage @Architecture overview unknown",
        "# Storage @architecture  overview unknown",
        "# Storage @architecture overview unknown ",
        "# Storage @architecture\toverview unknown",
        '# Storage @architecture {"min_view":"overview","replacement":"unknown"}',
        '# Storage @architecture {"min_view":"overview","min_view":"detailed","replacement":"unknown"}',
        "# Storage @architecture min_view=overview replacement=unknown owner=team",
        "# Storage @architecture overview unknown @architecture detailed contract",
        "#  Storage @architecture overview unknown",
        "# Storage  @architecture overview unknown",
        "# @architecture overview unknown",
        "// Storage @architecture overview unknown",
        "/* Storage @architecture overview unknown */",
        "# Storage\u2028Hidden @architecture overview unknown",
        "# Storage\x1bHidden @architecture overview unknown",
    ],
)
def test_malformed_metadata_cannot_fall_back_to_plain_caption(header: str) -> None:
    source = header + "\n\n" + _BODY

    with pytest.raises(ArchitectureAnnotationError):
        parse_module_annotation(Path("main.tf"), source)
    findings = NoTerraformComments(module_summaries=True).check(Path("main.tf"), source)
    assert len(findings) == 1
    assert not findings[0].suppressible


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("variables.tf", _HEADER + "\n\n" + _BODY),
        ("main.tf", "\n" + _HEADER + "\n\n" + _BODY),
        ("main.tf", "  " + _HEADER + "\n\n" + _BODY),
        ("main.tf", _HEADER + "\n" + _BODY),
        ("main.tf", _HEADER + "\n \n" + _BODY),
        ("main.tf", _HEADER + "\n\n" + _HEADER + "\n" + _BODY),
        ("main.tf", _BODY + _HEADER + "\n"),
        ("main.tf", 'locals { text = "${1 /* @architecture overview unknown */ + 2}" }\n'),
        ("main.tf", "/* note\n@architecture overview unknown\n*/\n" + _BODY),
        ("main.tf", "# Storage @architecture overview invalid\n\nlocals { value =\n"),
    ],
)
def test_misplaced_and_conflicting_annotations(name: str, source: str) -> None:
    with pytest.raises(ArchitectureAnnotationError):
        parse_module_annotation(Path(name), source)


@pytest.mark.parametrize("length", [39, 40, 41])
def test_summary_bound(length: int) -> None:
    source = "# " + "A" * length + " @architecture overview unknown\n\n" + _BODY

    if length <= 40:
        assert parse_module_annotation(Path("main.tf"), source) is not None
    else:
        with pytest.raises(ArchitectureAnnotationError):
            parse_module_annotation(Path("main.tf"), source)


@pytest.mark.parametrize(
    "source",
    [
        "# Object storage\n\n" + _BODY,
        _BODY,
        'locals { value = "# Storage @architecture overview contract" }\n',
        "locals { script = <<DOC\n# Storage @architecture overview contract\nDOC\n}\n",
    ],
)
def test_absent_and_literal_markers_are_unassessed(source: str) -> None:
    assert parse_module_annotation(Path("main.tf"), source) is None
    assert NoTerraformComments(module_summaries=True).check(Path("main.tf"), source) == []


def test_errors_do_not_disclose_annotation_values() -> None:
    private = "PRIVATE_SENTINEL_DO_NOT_LOG"
    source = f"# Storage @architecture overview {private}\n\n" + _BODY

    with pytest.raises(ArchitectureAnnotationError) as caught:
        parse_module_annotation(Path("main.tf"), source)
    assert private not in "".join(traceback.format_exception(caught.value))
    assert private not in str(NoTerraformComments(module_summaries=True).check(Path("main.tf"), source))


def test_generated_types_match_authoritative_schema() -> None:
    assert TYPES_PATH.read_text(encoding="utf-8") == render_types()
    assert [field.name for field in fields(ModuleArchitecture)] == annotation_schema()["required"]


@pytest.fixture
def calm_validator() -> Validator:
    # FINOS calm-schema v1.3/schema/decorators.json, Apache-2.0; immutable upstream fixture.
    upstream = parse_json((Path(__file__).parent / "fixtures" / "calm-decorators-1.3.json").read_text(encoding="utf-8"))
    schema = parse_json(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert isinstance(upstream, dict)
    assert isinstance(schema, dict)
    registry = Registry[Schema]().with_resource(
        "https://calm.finos.org/release/1.3/meta/decorators.json",
        Resource.from_contents({str(key): value for key, value in upstream.items()}, default_specification=DRAFT202012),
    )
    return Draft202012Validator(schema, registry=registry)


def test_calm_extension_and_multiple_elements_validate_offline(calm_validator: Validator) -> None:
    annotation = ModuleArchitecture("Object storage", MinView.OVERVIEW, Replacement.MIGRATION)
    decorator = calm_decorator(
        annotation, unique_id="module-blob", target="architecture.json", applies_to=["app", "local"]
    )

    assert calm_validator.is_valid(decorator)
    assert decorator["data"] == {"summary": "Object storage", "min_view": "overview", "replacement": "migration"}
    assert not calm_validator.is_valid({**decorator, "type": "unrelated"})
    assert not calm_validator.is_valid(
        {
            **decorator,
            "data": {
                "summary": "Object storage",
                "min_view": "overview",
                "replacement": "migration",
                "owner": "unexpected",
            },
        }
    )


@pytest.mark.parametrize("applies_to", [pytest.param([], id="no-targets"), pytest.param([""], id="empty-target")])
def test_decorator_requires_real_element_targets(applies_to: list[str]) -> None:
    with pytest.raises(ArchitectureAnnotationError):
        calm_decorator(
            ModuleArchitecture("Object storage", MinView.OVERVIEW, Replacement.UNKNOWN),
            unique_id="blob",
            target="architecture.json",
            applies_to=applies_to,
        )
