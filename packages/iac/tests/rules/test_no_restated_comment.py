from pathlib import Path

import pytest

from sarj_iac_lint.rules.no_restated_comment import NoRestatedComment


def _check(source: str):
    return NoRestatedComment().check(Path("main.tf"), source)


def test_flags_exact_attribute_restatement() -> None:
    assert len(_check("# Set instance type\ninstance_type = var.instance_type\n")) == 1


@pytest.mark.parametrize(
    "source",
    [
        "# Keep this type because the provider rejects ARM nodes.\ninstance_type = var.instance_type\n",
        "# Instance type?\ninstance_type = var.instance_type\n",
        "# tflint-ignore: terraform_unused_declarations\ninstance_type = var.instance_type\n",
        "# First line\n# Set instance type\ninstance_type = var.instance_type\n",
        "script = <<EOF\n# Set instance type\ninstance_type = var.instance_type\nEOF\n",
        "# @generated - do not edit\n# Set instance type\ninstance_type = var.instance_type\n",
    ],
)
def test_preserves_non_restatements(source: str) -> None:
    assert _check(source) == []


def test_public_examples_execute() -> None:
    examples = NoRestatedComment.public_examples()
    assert [len(_check(example.focus_file.source)) for example in examples] == [1, 0]
