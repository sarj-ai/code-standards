from __future__ import annotations

import ast

from sarj_python_lint.rules._annotation_semantics import scope_bound_names


def test_scope_collection_handles_deep_union_annotations() -> None:
    annotation = " | ".join(["str"] * 3001 + ["None"])
    tree = ast.parse(f"payload: {annotation}\n")
    assert scope_bound_names(tree.body) == {"payload"}


def test_scope_collection_preserves_nested_scope_exclusions() -> None:
    tree = ast.parse(
        "def function():\n    nested = 1\n"
        "async def asynchronous():\n    hidden = 1\n"
        "class Record:\n    field = 1\n"
        "factory = lambda: (deferred := 1)\n"
    )
    assert scope_bound_names(tree.body) == {"function", "asynchronous", "Record", "factory"}


def test_scope_collection_keeps_import_exception_and_match_bindings() -> None:
    tree = ast.parse(
        "import typing as types\nfrom pydantic import BaseModel as Model\n"
        "try:\n    pass\nexcept ValueError as caught:\n    local = 1\n"
        "match subject:\n    case {'key': bound, **rest}:\n        selected = 1\n"
        "    case [*items]:\n        pass\n"
    )
    assert scope_bound_names(tree.body) == {"types", "Model", "caught", "local", "bound", "rest", "selected", "items"}


def test_scope_collection_distinguishes_name_and_attribute_targets() -> None:
    tree = ast.parse("first, *remaining = values\nrecord.attribute = value\nlookup[key] = value\ndel removed\n")
    assert scope_bound_names(tree.body) == {"first", "remaining", "removed"}
