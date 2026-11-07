from __future__ import annotations

from pathlib import Path
import re
import subprocess

from pydantic import BaseModel, RootModel
import pytest

from sarj_standards.libs.linting import oxlint
from tests.oxlint_project import OXLINT, environment, require_oxlint


class _Rule(BaseModel):
    scope: str
    value: str


class _Rules(RootModel[list[_Rule]]):
    pass


_PLATFORM_CONFIG = Path.home() / "Developer" / "sarj" / "platform" / "oxlint.config.ts"


# Codes recorded from Oxlint 1.91.0 JSON on fixtures and on a copy of the
# automations corpus linted with Platform's config.
@pytest.mark.parametrize(
    ("code", "rule_id"),
    [
        ("eslint(no-debugger)", "no-debugger"),
        ("typescript(no-explicit-any)", "typescript/no-explicit-any"),
        ("typescript(no-floating-promises)", "typescript/no-floating-promises"),
        ("unicorn(no-null)", "unicorn/no-null"),
        ("jsx-a11y(alt-text)", "jsx-a11y/alt-text"),
        ("react-perf(jsx-no-new-object-as-prop)", "react-perf/jsx-no-new-object-as-prop"),
        ("react(jsx-key)", "react/jsx-key"),
        ("react(immutability)", "react/immutability"),
        ("react-hooks(rules-of-hooks)", "react/rules-of-hooks"),
        ("react-hooks(exhaustive-deps)", "react/exhaustive-deps"),
        ("next(no-img-element)", "nextjs/no-img-element"),
        ("import(no-nodejs-modules)", "import/no-nodejs-modules"),
        ("promise(avoid-new)", "promise/avoid-new"),
        ("vitest(no-focused-tests)", "vitest/no-focused-tests"),
        ("node(no-process-env)", "node/no-process-env"),
        ("oxc(no-const-enum)", "oxc/no-const-enum"),
        ("jsdoc(check-tag-names)", "jsdoc/check-tag-names"),
        ("@sarj(no-test-comments)", "@sarj/no-test-comments"),
        ("unicorn-js(no-unnecessary-parameters)", "unicorn-js/no-unnecessary-parameters"),
        ("eslint-js(preserve-caught-error)", "eslint-js/preserve-caught-error"),
        (
            "@eslint-community/eslint-comments(no-restricted-disable)",
            "@eslint-community/eslint-comments/no-restricted-disable",
        ),
        ("typescript(TS2322)", "tsc/TS2322"),
        ("TS(1036)", "tsc/TS1036"),
    ],
)
def test_oxlint_codes_map_to_config_rule_ids(code: str, rule_id: str) -> None:
    assert oxlint.oxlint_rule_id(code) == rule_id


@pytest.mark.parametrize(
    ("name", "rule_id"),
    [
        ("eslint/no-console", "no-console"),
        ("no-console", "no-console"),
        ("@typescript-eslint/ban-ts-comment", "typescript/ban-ts-comment"),
        ("jsx_a11y/alt-text", "jsx-a11y/alt-text"),
        ("react_perf/jsx-no-new-function-as-prop", "react-perf/jsx-no-new-function-as-prop"),
        ("next/no-img-element", "nextjs/no-img-element"),
        ("@next/next/no-img-element", "nextjs/no-img-element"),
        ("react-hooks/exhaustive-deps", "react/exhaustive-deps"),
        ("@eslint-community/eslint-comments/no-use", "@eslint-community/eslint-comments/no-use"),
    ],
)
def test_directive_and_suppression_aliases_share_one_rule_id(name: str, rule_id: str) -> None:
    assert oxlint.canonical_rule_id(name) == rule_id


@pytest.mark.parametrize("code", ["", "no-debugger", "eslint(no-debugger", "a(b)(c)"])
def test_unrecognized_codes_fail_instead_of_inventing_rule_ids(code: str) -> None:
    with pytest.raises(ValueError, match="unsupported Oxlint diagnostic code"):
        oxlint.oxlint_rule_id(code)


def test_every_native_oxlint_rule_maps_into_a_config_namespace() -> None:
    require_oxlint()
    listing = subprocess.run(
        (str(OXLINT), "--rules", "-f", "json"), env=environment(), capture_output=True, text=True, check=True
    )
    namespaces = {
        oxlint.canonical_rule_id(f"{row.scope}/{row.value}").rpartition("/")[0]
        for row in _Rules.model_validate_json(listing.stdout).root
    }
    assert namespaces == {
        "",
        "typescript",
        "unicorn",
        "react",
        "react-perf",
        "jsx-a11y",
        "nextjs",
        "import",
        "promise",
        "node",
        "vitest",
        "jest",
        "jsdoc",
        "oxc",
        "vue",
    }


def test_platform_config_names_are_already_canonical() -> None:
    if not _PLATFORM_CONFIG.is_file():
        pytest.skip("requires the Platform checkout's Oxlint config")
    text = _PLATFORM_CONFIG.read_text(encoding="utf-8")
    names = {match[1] for match in re.finditer(r'^\s+"([^"\s]+/[^"\s]+|[a-z][a-z-]+)":', text, re.MULTILINE)}
    assert {name for name in names if oxlint.canonical_rule_id(name) != name} == set()


@pytest.mark.parametrize(
    ("configured", "reported"),
    [
        ("react/exhaustive-deps", "react-hooks/exhaustive-deps"),
        ("react-hooks/rules-of-hooks", "react-hooks/rules-of-hooks"),
        ("react/immutability", "react/immutability"),
        ("nextjs/no-img-element", "next/no-img-element"),
        ("@next/next/no-img-element", "next/no-img-element"),
        ("eslint/no-console", "no-console"),
        ("@typescript-eslint/no-explicit-any", "typescript/no-explicit-any"),
    ],
)
def test_reported_rule_ids_invert_the_config_namespaces(configured: str, reported: str) -> None:
    assert oxlint.reported_rule_id(configured) == reported
    assert oxlint.canonical_rule_id(reported) == oxlint.canonical_rule_id(configured)
