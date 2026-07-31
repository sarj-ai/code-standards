from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.duplicated_override_docstring import DuplicatedOverrideDocstring


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: Path = Path("<t>.py")) -> list[Diagnostic]:
    return DuplicatedOverrideDocstring().check(path, source)


def _pair(base_doc: str, override_doc: str, *, base: str = "Store", child: str = "MemoryStore") -> str:
    """Build a base class and a subclass that both define `get` with a docstring.

    Returns:
        Module source with the two classes, each method carrying a real body.

    """
    return (
        f"class {base}:\n"
        f"    def get(self, key: str) -> str:\n"
        f'        """{base_doc}"""\n'
        "        return key\n"
        "\n"
        f"class {child}({base}):\n"
        f"    def get(self, key: str) -> str:\n"
        f'        """{override_doc}"""\n'
        "        return key\n"
    )


def test_flags_a_verbatim_copy():
    diags = _check(_pair("Get a value by key.", "Get a value by key."))
    assert len(diags) == 1
    assert diags[0].code == "SARJ084"
    assert (diags[0].line, diags[0].col) == (8, 9)
    assert "Store.get" in diags[0].message


def test_flags_an_async_override():
    src = (
        "class Store:\n"
        "    async def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
        "        return key\n"
        "\n"
        "class MemoryStore(Store):\n"
        "    async def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
        "        return key\n"
    )
    assert len(_check(src)) == 1


def test_flags_every_copied_method_independently():
    src = (
        "class Store:\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
        "        return key\n"
        "    def put(self, key: str) -> None:\n"
        '        """Store a value under key."""\n'
        "        return None\n"
        "\n"
        "class MemoryStore(Store):\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
        "        return key\n"
        "    def put(self, key: str) -> None:\n"
        '        """Store a value under key."""\n'
        "        return None\n"
    )
    assert len(_check(src)) == 2


def test_indentation_differences_do_not_hide_a_copy():
    # `ast.get_docstring(clean=True)` normalises the common indent, so the same
    # sentence pasted one level deeper is still the same sentence.
    src = (
        "class Store:\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value.\n'
        "\n"
        "        Longer wording that wrapped.\n"
        '        """\n'
        "        return key\n"
        "\n"
        "class MemoryStore(Store):\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value.\n'
        "\n"
        "        Longer wording that wrapped.\n"
        '        """\n'
        "        return key\n"
    )
    assert len(_check(src)) == 1


# --- exemptions ---------------------------------------------------------------


def test_a_reworded_override_is_kept():
    assert _check(_pair("Get a value by key.", "Get a value by key, hitting the replica first.")) == []


def test_an_override_the_base_does_not_document_is_kept():
    src = (
        "class Store:\n"
        "    def get(self, key: str) -> str:\n"
        "        return key\n"
        "\n"
        "class MemoryStore(Store):\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
        "        return key\n"
    )
    assert _check(src) == []


def test_a_base_this_file_does_not_define_is_out_of_reach():
    # A per-file linter cannot follow the import, and guessing would make every
    # same-named class in the repo a candidate parent.
    src = (
        "from elsewhere import Store\n"
        "\n"
        "class MemoryStore(Store):\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
        "        return key\n"
    )
    assert _check(src) == []


def test_a_dotted_base_never_resolves_to_a_local_class():
    # A subclass that shadows the name of the imported base it extends is not
    # its own parent; matching on the last dotted part alone made it one.
    src = (
        "import upstream\n"
        "\n"
        "class Stream(upstream.Stream):\n"
        "    def send(self, chunk: bytes) -> None:\n"
        '        """Send one chunk."""\n'
        "        return None\n"
    )
    assert _check(src) == []


def test_a_sibling_class_is_not_a_parent():
    src = (
        "class Store:\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
        "        return key\n"
        "\n"
        "class OtherStore:\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
        "        return key\n"
    )
    assert _check(src) == []


def test_a_stub_whose_body_is_the_docstring_is_exempt():
    # "Delete the override's docstring" would leave an empty suite.
    src = (
        "class Store:\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
        "        return key\n"
        "\n"
        "class MemoryStore(Store):\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
    )
    assert _check(src) == []


@pytest.mark.parametrize("decorator", ["@overload", "@typing.overload"])
def test_overload_declarations_are_exempt(decorator: str):
    src = (
        "class Store:\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
        "        return key\n"
        "\n"
        "class MemoryStore(Store):\n"
        f"    {decorator}\n"
        "    def get(self, key: str) -> str:\n"
        '        """Get a value by key."""\n'
        "        return key\n"
    )
    assert _check(src) == []


def test_generated_file_is_skipped():
    assert _check("# Code generated by openapi-generator. DO NOT EDIT.\n" + _pair("Get a value.", "Get a value.")) == []


def test_banner_less_generated_tree_is_skipped_by_path():
    """A generated module with no header marker is still exempt.

    The exemption is named after an OpenAPI client, and openapi-python-client
    emits no banner at all — a header-only guard exempted nothing it was
    written for.
    """
    src = _pair("Get a value.", "Get a value.")
    assert _check(src, Path("src/generated/models.py")) == []


def test_a_hand_written_path_still_reports():
    """Pins the surviving true positives: the guard is about generated trees only.

    Without this, widening the path predicate later would silently take the
    rule's whole population with it.
    """
    src = _pair("Get a value.", "Get a value.")
    assert len(_check(src, Path("src/app/stores.py"))) == 1


def test_unparseable_source_returns_nothing():
    assert _check("class (:\n") == []


def test_a_class_without_bases_is_ignored():
    src = 'class Store:\n    def get(self, key: str) -> str:\n        """Get a value."""\n        return key\n'
    assert _check(src) == []
