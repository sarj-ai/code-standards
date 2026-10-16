import pytest

from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping
from sarj_standards.libs.yaml_boundary import parse_yaml_documents


@pytest.mark.parametrize(
    "source",
    [
        "name: first\nname: second\n",
        "true: first\nTrue: second\n",
        "1: first\n01: second\n",
        "true: first\n1: second\n",
        "null: first\n~: second\n",
        "1.0: first\n1: second\n",
    ],
    ids=("text", "boolean-spellings", "integer-spellings", "boolean-integer", "null-spellings", "float-integer"),
)
def test_yaml_keys_cannot_silently_overwrite_a_constructed_key(source: str) -> None:
    with pytest.raises(ValueError, match="duplicate YAML key"):
        parse_yaml_documents(source)


def test_yaml_documents_preserve_empty_documents_and_merge_overrides() -> None:
    assert parse_yaml_documents("") == ()
    assert parse_yaml_documents("---\n---\nvalue: 1\n---\n") == (None, {"value": 1}, None)
    assert parse_yaml_documents("base: &base {name: old}\ncopy: {<<: *base, name: new}\n") == (
        {"base": {"name": "old"}, "copy": {"name": "new"}},
    )


@pytest.mark.parametrize("source", ["node: &node [*node]\n", "node: &node {child: *node}\n"])
def test_yaml_alias_cycles_are_rejected(source: str) -> None:
    with pytest.raises(ValueError, match="recursive"):
        parse_yaml_documents(source)


def _aliases(levels: int) -> str:
    return "n0: &n0 [leaf]\n" + "".join(f"n{i}: &n{i} [*n{i - 1}, *n{i - 1}]\n" for i in range(1, levels))


def test_alias_fanout_is_bounded_before_downstream_materialization() -> None:
    with pytest.raises(ValueError, match="expanded YAML"):
        parse_yaml_documents(_aliases(18))


def test_shared_aliases_preserve_their_object_identity() -> None:
    [document] = parse_yaml_documents(_aliases(12))

    assert is_object_mapping(document)
    first_alias = document["n1"]
    assert is_object_list(first_alias)
    assert first_alias[0] is document["n0"]


@pytest.mark.parametrize("depth", [63, 64])
def test_depth_bound_is_preserved_for_direct_nesting(depth: int) -> None:
    source = "[" * depth + "leaf" + "]" * depth
    if depth == 63:
        assert parse_yaml_documents(source)
    else:
        with pytest.raises(ValueError, match="nested YAML"):
            parse_yaml_documents(source)


def test_cached_alias_shape_cannot_hide_a_deeper_path() -> None:
    source = "node: &node [leaf]\ndeep: " + "[" * 62 + "*node" + "]" * 62
    with pytest.raises(ValueError, match="nested YAML"):
        parse_yaml_documents(source)


def test_parser_recursion_limit_is_a_validation_error() -> None:
    source = "[" * 1_000 + "leaf" + "]" * 1_000
    with pytest.raises(ValueError, match="nested YAML"):
        parse_yaml_documents(source)
