from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import doctor, retired_suppressions


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "// eslint-disable-next-line @sarj/prefer-string-literal-union\nconst value = 1;\n",
            "const value = 1;\n",
        ),
        (
            "/* eslint-disable unicorn/no-null, @sarj/prefer-string-literal-union -- migration */\n",
            "/* eslint-disable unicorn/no-null -- migration */\n",
        ),
        (
            "const value = 1; // eslint-disable-line @sarj/prefer-string-literal-union\r\n",
            "const value = 1;\r\n",
        ),
        (
            "// eslint-disable-next-line @sarj/require-interface-for-injected-service\n",
            "// eslint-disable-next-line @sarj/require-port-for-service\n",
        ),
        (
            "// eslint-disable-next-line @sarj/require-interface-for-injected-service, @sarj/require-port-for-service\n",
            "// eslint-disable-next-line @sarj/require-port-for-service\n",
        ),
        (
            "// eslint-enable @sarj/prefer-string-literal-union, unicorn/no-null\n",
            "// eslint-enable unicorn/no-null\n",
        ),
        ("value = 1  # sarj-noqa: SARJ061, SARJ096\n", "value = 1  # sarj-noqa: SARJ096\n"),
        ("# sarj-noqa: SARJ061\nvalue = 1\n", "value = 1\n"),
    ],
)
def test_plans_unambiguous_retired_suppression_migrations(tmp_path: Path, source: str, expected: str) -> None:
    target = tmp_path / ("service.py" if "sarj-noqa" in source else "service.ts")
    target.write_text(source, encoding="utf-8", newline="")

    rewrites = retired_suppressions.plan((target,))

    assert rewrites == (retired_suppressions.Rewrite(target, expected),)


@pytest.mark.parametrize("comment", ["#", "//"])
def test_migrates_retired_iac_suppression_to_general_rule(tmp_path: Path, comment: str) -> None:
    target = tmp_path / "main.tf"
    source = f"groups = local.groups  {comment} sarj-noqa: SARJ208 -- reviewed access exception\n"
    target.write_text(source, encoding="utf-8")

    assert retired_suppressions.plan((target,)) == (
        retired_suppressions.Rewrite(
            target,
            f"groups = local.groups  {comment} sarj-noqa: SARJ204 -- reviewed access exception\n",
        ),
    )


@pytest.mark.parametrize(
    "source",
    [
        'const note = "eslint-disable-next-line @sarj/prefer-string-literal-union";\n',
        'export default { rules: { "@sarj/prefer-string-literal-union": "off" } };\n',
        "// The old @sarj/prefer-string-literal-union rule was retired.\n",
        "// eslint-disable\n",
        "// eslint-disable-next-line @sarj/prefer-string-literal-union ???\n",
    ],
)
def test_leaves_ambiguous_or_non_suppression_references_untouched(tmp_path: Path, source: str) -> None:
    target = tmp_path / "service.ts"
    target.write_text(source, encoding="utf-8")

    assert retired_suppressions.plan((target,)) == ()


def test_honors_doctor_exclusions_and_fixture_sentinel(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text(
        'schema = 3\nbundle = "5.6.2"\nprofile = "standard"\nrule_profile = "all"\n'
        '[capabilities]\ndisable = []\n[dest]\npython = "."\ntypescript = "."\n'
        '[hooks]\nmanager = "none"\n[doctor]\nexclude = ["excluded.ts"]\n',
        encoding="utf-8",
    )
    excluded = tmp_path / "excluded.ts"
    excluded.write_text("// eslint-disable @sarj/prefer-string-literal-union\n", encoding="utf-8")
    fixture = tmp_path / "fixture.ts"
    fixture.write_text(
        "// sarj-doctor-ignore-retired-rules -- compatibility fixture\n"
        "// eslint-disable @sarj/prefer-string-literal-union\n",
        encoding="utf-8",
    )

    assert retired_suppressions.plan(doctor.authored_files(tmp_path)) == ()


def test_template_fixture_is_not_rewritten_and_remains_a_blocker(tmp_path: Path) -> None:
    target = tmp_path / "fixture.ts"
    source = "const fixture = `\n// eslint-disable-next-line @sarj/prefer-string-literal-union\nconst value = 1;\n`;\n"
    target.write_text(source, encoding="utf-8")

    assert retired_suppressions.plan((target,)) == ()
    assert retired_suppressions.reference_counts(target, source) == {"@sarj/prefer-string-literal-union": 1}


@pytest.mark.parametrize(
    "source",
    [
        "// Example: // eslint-disable-next-line @sarj/prefer-string-literal-union\n",
        "/* Example: // eslint-disable-next-line @sarj/prefer-string-literal-union */\n",
        "// eslint-disable-next-line @sarj/prefer-string-literal-union ???\n",
    ],
)
def test_nested_or_malformed_directive_is_not_rewritten_and_remains_blocking(tmp_path: Path, source: str) -> None:
    target = tmp_path / "fixture.ts"
    target.write_text(source, encoding="utf-8")

    assert retired_suppressions.plan((target,)) == ()
    assert retired_suppressions.reference_counts(target, source) == {"@sarj/prefer-string-literal-union": 1}


def test_retired_name_in_directive_reason_is_not_a_reference(tmp_path: Path) -> None:
    target = tmp_path / "service.ts"
    source = "// eslint-disable-next-line unicorn/no-null -- migrated from @sarj/prefer-string-literal-union\n"

    assert retired_suppressions.reference_counts(target, source) == {}


def test_migrates_retired_ids_in_mixed_core_plugin_and_scoped_eslint_directive(
    tmp_path: Path,
) -> None:
    target = tmp_path / "service.ts"
    source = (
        "// eslint-disable-next-line no-console, react/jsx-uses-react, "
        "@typescript-eslint/no-explicit-any, @sarj/prefer-string-literal-union, "
        "@sarj/require-interface-for-injected-service -- compatibility bridge\n"
    )
    target.write_text(source, encoding="utf-8")

    assert retired_suppressions.plan((target,)) == (
        retired_suppressions.Rewrite(
            target,
            "// eslint-disable-next-line no-console, react/jsx-uses-react, "
            "@typescript-eslint/no-explicit-any, @sarj/require-port-for-service "
            "-- compatibility bridge\n",
        ),
    )
    assert retired_suppressions.reference_counts(target, source) == {
        "@sarj/prefer-string-literal-union": 1,
        "@sarj/require-interface-for-injected-service": 1,
    }


@pytest.mark.parametrize(
    "malformed_id",
    [
        "@scope",
        "/no-console",
        "react/",
        "react//jsx-uses-react",
        "react/jsx.uses.react",
        "-no-console",
    ],
)
def test_malformed_eslint_id_keeps_mixed_directive_ambiguous_and_blocking(tmp_path: Path, malformed_id: str) -> None:
    target = tmp_path / "service.ts"
    source = (
        "// eslint-disable-next-line "
        f"no-console, {malformed_id}, @sarj/prefer-string-literal-union "
        "-- compatibility bridge\n"
    )
    target.write_text(source, encoding="utf-8")

    assert retired_suppressions.plan((target,)) == ()
    assert retired_suppressions.reference_counts(target, source) == {"@sarj/prefer-string-literal-union": 1}


def test_migrates_python_directive_with_reason_suffix(tmp_path: Path) -> None:
    target = tmp_path / "service.pyi"
    source = "value: int  # sarj-noqa: SARJ061, SARJ096 -- compatibility bridge\r\n"
    target.write_text(source, encoding="utf-8", newline="")

    assert retired_suppressions.plan((target,)) == (
        retired_suppressions.Rewrite(
            target,
            "value: int  # sarj-noqa: SARJ096 -- compatibility bridge\r\n",
        ),
    )


@pytest.mark.parametrize("separator", ["–", "—"])
def test_migrates_python_directive_with_unicode_reason_separator(tmp_path: Path, separator: str) -> None:
    target = tmp_path / "service.py"
    source = f"value = 1  # sarj-noqa: SARJ061, SARJ096 {separator} compatibility bridge\n"
    target.write_text(source, encoding="utf-8")

    assert retired_suppressions.plan((target,)) == (
        retired_suppressions.Rewrite(
            target,
            f"value = 1  # sarj-noqa: SARJ096 {separator} compatibility bridge\n",
        ),
    )


def test_jsx_wrapped_directive_is_not_deleted_into_an_empty_expression(tmp_path: Path) -> None:
    target = tmp_path / "component.tsx"
    source = "<Panel>{/* eslint-disable @sarj/prefer-string-literal-union */}</Panel>\n"
    target.write_text(source, encoding="utf-8")

    assert retired_suppressions.plan((target,)) == ()
    assert retired_suppressions.reference_counts(target, source) == {"@sarj/prefer-string-literal-union": 1}


def test_migrates_valid_eslint_bulk_suppressions_without_adding_budgets(tmp_path: Path) -> None:
    target = tmp_path / "eslint-suppressions.json"
    target.write_text(
        "{\n"
        '  "src/app.ts": {\n'
        '    "@sarj/jsdoc-restates-signature": {"count": 5},\n'
        '    "@sarj/no-restated-jsdoc": {"count": 2},\n'
        '    "@sarj/no-unsafe-cast": {"count": 7},\n'
        '    "unicorn/no-null": {"count": 1}\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    rewrites = retired_suppressions.plan((target,))

    assert len(rewrites) == 1
    assert rewrites[0].contents == (
        "{\n"
        '  "src/app.ts": {\n'
        '    "@sarj/no-restated-jsdoc": {\n'
        '      "count": 5\n'
        "    },\n"
        '    "unicorn/no-null": {\n'
        '      "count": 1\n'
        "    }\n"
        "  }\n"
        "}\n"
    )


def test_migrates_bom_crlf_eslint_bulk_suppressions_without_normalizing_file_style(
    tmp_path: Path,
) -> None:
    target = tmp_path / "eslint-suppressions.json"
    target.write_text(
        '\ufeff{\r\n  "src/app.ts": {\r\n    "@sarj/jsdoc-restates-signature": {"count": 2}\r\n  }\r\n}\r\n',
        encoding="utf-8",
        newline="",
    )

    rewrites = retired_suppressions.plan((target,))

    assert len(rewrites) == 1
    assert rewrites[0].contents.startswith("\ufeff{\r\n")
    assert rewrites[0].contents.endswith("\r\n")
    assert "@sarj/no-restated-jsdoc" in rewrites[0].contents


def test_duplicate_bulk_suppression_keys_are_not_lossily_migrated(tmp_path: Path) -> None:
    target = tmp_path / "eslint-suppressions.json"
    source = (
        '{"src/app.ts":{"@sarj/jsdoc-restates-signature":{"count":1},"@sarj/jsdoc-restates-signature":{"count":2}}}\n'
    )
    target.write_text(source, encoding="utf-8")

    assert retired_suppressions.plan((target,)) == ()
    assert retired_suppressions.reference_counts(target, source) == {"@sarj/jsdoc-restates-signature": 2}


@pytest.mark.parametrize(
    "source",
    [
        "[]\n",
        '{"src/app.ts":{"@sarj/no-unsafe-cast":{"count":true}}}\n',
        '{"src/app.ts":{"@sarj/no-unsafe-cast":{"count":1,"note":"keep"}}}\n',
        "{ invalid json\n",
    ],
)
def test_leaves_unknown_eslint_bulk_suppression_shapes_blocking(tmp_path: Path, source: str) -> None:
    target = tmp_path / "eslint-suppressions.json"
    target.write_text(source, encoding="utf-8")

    assert retired_suppressions.plan((target,)) == ()
