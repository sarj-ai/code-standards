from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze, check_source
from sarj_python_lint.rule_base import is_suppressed
from sarj_python_lint.rules.no_blanket_suppression import NoBlanketSuppression
from sarj_python_lint.rules.no_file_level_escape_hatch_suppression import NoFileLevelEscapeHatchSuppression
from sarj_python_lint.rules.no_vague_suppression_description import NoVagueSuppressionDescription


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Rule, RuleExample


@pytest.mark.parametrize(
    "source",
    [
        "value = vendor.value # sarj-noqa\n",
        "value = vendor.value # sarj-noqa -- vendor boundary\n",
        "value = vendor.value # SARJ-NOQA\n",
        "value = vendor.value # sarj-noqa:\n",
        "value = vendor.value # pyright: ignore\n",
        "value = vendor.value # pyright: ignore []\n",
        "# pyright: basic\nvalue = vendor.value\n",
        "# pyright: strict, reportPrivateUsage=false\nvalue = vendor.value\n",
        "# pyright: reportReturnType=none\nvalue = vendor.value\n",
        "# pyright: reportReturnType=warning\nvalue = vendor.value\n",
        "# pyright: reportReturnType=information\nvalue = vendor.value\n",
        "# pyright: reportReturnType=hint\nvalue = vendor.value\n",
        "# pyright: strictParameterNoneValue=false\ndef result(value: int = None) -> None:\n    pass\n",
        "# ruff: file-ignore[unused-import]\nimport vendor\n",
        "# ruff: noqa: F401\nimport vendor\n",
        "# ruff: disable[unused-import]\nimport vendor\n# ruff: enable[unused-import]\n",
        "# pyright: reportIgnoreCommentWithoutRule=false\nvalue = vendor.value # pyright: ignore\n",
    ],
)
def test_blocks_unscoped_or_file_wide_type_suppression(source: str) -> None:
    assert NoBlanketSuppression().check(Path("app/service.py"), source)


@pytest.mark.parametrize(
    "source",
    [
        "value = vendor.value # sarj-noqa: SARJ008 -- wire data is owned by the dependency\n",
        "value = vendor.value # pyright: ignore[reportPrivateUsage] -- dependency exposes this API only privately\n",
        "value = vendor.value # pyright: ignore[reportPrivateUsage,] -- dependency exposes this API only privately\n",
        "# pyright: strict\nvalue = 1\n",
        "# pyright: reportPrivateUsage=true, reportReturnType=error\nvalue = 1\n",
        "# pyright: enableExperimentalFeatures=false\nvalue = 1\n",
        "# The vendor requires a pyright: ignore directive in its examples.\nvalue = 1\n",
        "# A local example is `# pyright: ignore`.\nvalue = 1\n",
        '# The example uses "# pyright: reportReturnType=false".\nvalue = 1\n',
        "text = '# sarj-noqa'\n",
        "text = '# pyright: basic'\n",
        '"""Example:\n# pyright: reportReturnType=false\n"""\n',
        "value = vendor.value # noqa: F401 -- exact Ruff exception\n",
    ],
)
def test_preserves_scoped_exceptions_and_comment_provenance(source: str) -> None:
    assert NoBlanketSuppression().check(Path("app/service.py"), source) == []


def test_bare_sarj_marker_cannot_waive_an_unrelated_rule() -> None:
    assert not is_suppressed(["value = vendor.value # sarj-noqa"], 1, "SARJ008")
    assert is_suppressed(["value = vendor.value # sarj-noqa: SARJ008 -- wire contract"], 1, "SARJ008")


@pytest.mark.parametrize(
    ("rule", "source"),
    [
        (NoBlanketSuppression(), "value = vendor.value # pyright: ignore # sarj-noqa: SARJ523 -- fixture\n"),
        (NoFileLevelEscapeHatchSuppression(), "# ruff: file-ignore[banned-api] # sarj-noqa: SARJ054 -- fixture\n"),
        (
            NoVagueSuppressionDescription(),
            "value = vendor.value # pyright: ignore[reportAny] -- false positive # sarj-noqa: SARJ419 -- fixture\n",
        ),
    ],
)
def test_suppression_integrity_checks_cannot_suppress_themselves(rule: Rule, source: str) -> None:
    assert len(check_source([rule], Path("app/service.py"), source)) == 1


@pytest.mark.parametrize("code", ["SARJ054", "SARJ419", "SARJ448", "SARJ523"])
def test_protected_code_checks_retain_the_case_insensitive_noqa_contract(code: str) -> None:
    assert not is_suppressed([f"value = 1 # sarj-noqa: {code} -- adapter boundary"], 1, code.lower())


def test_native_legacy_baseline_cannot_hide_suppression_policy(tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    path.write_text("value = vendor.value # sarj-noqa\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"service.py": {"SARJ523": 100}}\n', encoding="utf-8")
    assert len(analyze([NoBlanketSuppression.id], [path], baseline=baseline, root=tmp_path)) == 1


@pytest.mark.parametrize("path", ["app/generated.py", "vendor/service.py", "third_party/service.py"])
def test_source_cannot_self_authorize_a_generated_or_vendor_waiver(path: str) -> None:
    source = "# @generated\nvalue = vendor.value # sarj-noqa\n"
    assert len(NoBlanketSuppression().check(Path(path), source)) == 1


@pytest.mark.parametrize("example", NoBlanketSuppression.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoBlanketSuppression().check(Path(focus.path), focus.source)) == example.expected_count
