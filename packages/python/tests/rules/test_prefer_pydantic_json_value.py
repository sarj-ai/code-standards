from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_pydantic_json_value import PreferPydanticJsonValue


if TYPE_CHECKING:
    from pathlib import Path


_ALIAS = "type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]\n"


def _project(tmp_path: Path, source: str, *, dependency: str = "pydantic>=2") -> Path:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "sample"\nversion = "0.1.0"\ndependencies = ["{dependency}"]\n',
        encoding="utf-8",
    )
    path = tmp_path / "src" / "sample" / "types.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_flags_exact_recursive_alias_in_pydantic_v2_distribution(tmp_path: Path) -> None:
    path = _project(tmp_path, _ALIAS)

    diagnostics = PreferPydanticJsonValue().check(path, path.read_text(encoding="utf-8"))

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ454"
    assert diagnostics[0].line == 1
    assert "pydantic.JsonValue" in diagnostics[0].message


def test_accepts_legacy_type_alias_and_qualified_containers(tmp_path: Path) -> None:
    source = (
        "import typing\n"
        "JsonValue: typing.TypeAlias = typing.Union[None, bool, int, float, str, "
        "typing.List['JsonValue'], typing.Dict[str, 'JsonValue']]\n"
    )
    path = _project(tmp_path, source, dependency="pydantic==2.13.5")

    assert len(PreferPydanticJsonValue().check(path, source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "type JsonValue = str | int | bool | None | list[JsonValue] | dict[str, JsonValue]\n",
        _ALIAS.replace("None | ", "None | bytes | "),
        _ALIAS.replace("dict[str, JsonValue]", "dict[int, JsonValue]"),
        _ALIAS.replace("list[JsonValue]", "tuple[JsonValue, ...]"),
        "type JsonObject = dict[str, JsonValue]\n",
        "type JsonValue[T] = T | list[JsonValue[T]]\n",
    ],
    ids=["narrower", "extended", "non-string-key", "tuple-domain", "non-recursive", "generic"],
)
def test_allows_non_equivalent_json_domains(tmp_path: Path, source: str) -> None:
    path = _project(tmp_path, source)

    assert PreferPydanticJsonValue().check(path, source) == []


@pytest.mark.parametrize(
    "dependency",
    [
        "pydantic<2",
        "pydantic>=1",
        "pydantic!=1.999.999",
        "pydantic>=2; python_version >= '3.12'",
        "requests>=2",
    ],
)
def test_requires_proven_pydantic_v2_dependency(tmp_path: Path, dependency: str) -> None:
    path = _project(tmp_path, _ALIAS, dependency=dependency)

    assert PreferPydanticJsonValue().check(path, _ALIAS) == []


@pytest.mark.parametrize("dependency", ["pydantic>=2.21", "pydantic==2.21.7", "pydantic==2.*"])
def test_accepts_proven_future_pydantic_v2_dependency(tmp_path: Path, dependency: str) -> None:
    path = _project(tmp_path, _ALIAS, dependency=dependency)

    assert len(PreferPydanticJsonValue().check(path, _ALIAS)) == 1


def test_dependency_cache_tracks_manifest_content(tmp_path: Path) -> None:
    path = _project(tmp_path, _ALIAS)
    rule = PreferPydanticJsonValue()
    assert len(rule.check(path, _ALIAS)) == 1

    _project(tmp_path, _ALIAS, dependency="pydantic<2")

    assert rule.check(path, _ALIAS) == []


def test_duplicate_or_rebound_alias_is_ambiguous(tmp_path: Path) -> None:
    source = _ALIAS + "JsonValue = object\n"
    path = _project(tmp_path, source)

    assert PreferPydanticJsonValue().check(path, source) == []


def test_exact_suppression_is_honored(tmp_path: Path) -> None:
    source = _ALIAS.rstrip() + "  # sarj-noqa: SARJ454 — runtime metadata differs\n"
    path = _project(tmp_path, source)

    assert PreferPydanticJsonValue().check(path, source) == []


@pytest.mark.parametrize("part", ["vendor", "vendored", "third_party"])
def test_vendor_sources_are_excluded(tmp_path: Path, part: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nversion = "0.1.0"\ndependencies = ["pydantic>=2"]\n',
        encoding="utf-8",
    )
    path = tmp_path / part / "types.py"
    path.parent.mkdir()

    assert PreferPydanticJsonValue().check(path, _ALIAS) == []


def test_malformed_source_is_ignored(tmp_path: Path) -> None:
    path = _project(tmp_path, "type JsonValue = [\n")

    assert PreferPydanticJsonValue().check(path, "type JsonValue = [\n") == []
