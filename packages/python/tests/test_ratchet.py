from __future__ import annotations

from collections import Counter
import json
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint._ratchet_cli import main
from sarj_python_lint.ratchet import (
    Baseline,
    Measurement,
    count_source,
    discover_packages,
    gate,
    improvements,
    load_baseline,
    measure,
    seed,
)


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("line", "key"),
    [
        pytest.param("x = f()  # noqa: E501", "noqa:E501", id="inline-noqa"),
        pytest.param("x = f()  # noqa:E501", "noqa:E501", id="inline-noqa-tight"),
        pytest.param("x = f()  # noqa", "noqa:<blanket>", id="inline-blanket-noqa"),
        pytest.param(
            "x = f()  # ruff: ignore[banned-api] -- legacy boundary",
            "noqa:banned-api",
            id="inline-named-ruff-ignore",
        ),
        pytest.param(
            "x = f()  # ruff: ignore [banned-api,] -- legacy boundary",
            "noqa:banned-api",
            id="inline-named-ruff-ignore-whitespace-and-trailing-comma",
        ),
        pytest.param("x = f()  # sarj-noqa: SARJ016 — why", "sarj-noqa:SARJ016", id="inline-sarj-noqa"),
        pytest.param("x = f()  # pyright: ignore[reportAny]", "pyright:reportAny", id="inline-pyright-ignore"),
        pytest.param("x = f()  # type: ignore[attr-defined]", "type-ignore:attr-defined", id="scoped-type-ignore"),
        pytest.param("x = f()  # type: ignore", "type-ignore", id="bare-type-ignore"),
        pytest.param("# ruff: noqa: E501", "file-noqa:E501", id="file-level-scoped-noqa"),
        pytest.param(
            "# ruff: noqa: banned-api",
            "file-noqa:banned-api",
            id="file-level-named-noqa",
        ),
        pytest.param(
            "# ruff: file-ignore[banned-api]",
            "file-noqa:banned-api",
            id="file-level-modern-named-ignore",
        ),
        pytest.param("# flake8: noqa", "file-noqa:<blanket>", id="flake8-file-level-blanket-noqa"),
        pytest.param("# pyright: ignore", "pyright:<blanket>", id="blanket-pyright-ignore"),
        pytest.param("# ruff: disable[banned-api]", "ruff-range:banned-api", id="ruff-range-disable"),
        pytest.param("# ruff: noqa", "file-noqa:<blanket>", id="file-level-blanket-noqa"),
        pytest.param("# pyright: reportAny=false", "file-pyright:reportAny", id="file-level-pyright-downgrade"),
    ],
)
def test_counts_every_dialect_under_its_own_key(line: str, key: str):
    assert count_source(line + "\n") == {key: 1}


def test_counts_every_code_in_a_list():
    assert count_source("x = f()  # noqa: E501, F401\n") == {"noqa:E501": 1, "noqa:F401": 1}


def test_counts_every_named_selector_in_a_ruff_ignore_list():
    source = "Mock()  # ruff: ignore[banned-api, unused-import] -- reviewed legacy boundary\n"
    assert count_source(source) == {"noqa:banned-api": 1, "noqa:unused-import": 1}


def test_canonicalizes_ruff_rule_names_and_codes_to_the_same_code():
    aliases = {"TID251": "TID251", "banned-api": "TID251"}
    source = "one()  # noqa: TID251\ntwo()  # ruff: ignore[banned-api]\n"
    assert count_source(source, ruff_aliases=aliases) == {"noqa:TID251": 2}


def test_unknown_ruff_selector_fails_closed_when_a_catalog_is_supplied():
    with pytest.raises(ValueError, match="unknown Ruff suppression selector: not-a-rule"):
        count_source("value = 1  # ruff: ignore[not-a-rule]\n", ruff_aliases={})


def test_counts_every_occurrence_on_a_line_not_just_the_first():
    assert count_source("x = f()  # noqa: A1  # noqa: B2\n") == {"noqa:A1": 1, "noqa:B2": 1}


def test_file_level_noqa_is_not_also_counted_as_an_inline_noqa():
    # Otherwise the two key prefixes overlap and one suppression scores twice.
    assert count_source("# ruff: noqa: TID251\n") == {"file-noqa:TID251": 1}


def test_file_level_pyright_downgrade_counts_each_rule():
    counts = count_source("# pyright: reportAny=false, reportUnusedImport=false\n")
    assert counts == {"file-pyright:reportAny": 1, "file-pyright:reportUnusedImport": 1}


def test_a_pyright_ignore_is_not_a_file_level_downgrade():
    assert count_source("x = f()  # pyright: ignore[reportAny]\n") == {"pyright:reportAny": 1}


def test_clean_source_counts_nothing():
    assert count_source("def f():\n    return 1\n") == {}


def test_suppression_spelling_inside_a_string_or_docstring_does_not_count():
    source = '"""Example: # ruff: ignore[banned-api]."""\nvalue = "# noqa: F401"\n'
    assert count_source(source) == {}


def test_comment_after_a_string_is_still_counted():
    assert count_source('value = "# noqa: F401"  # ruff: ignore[banned-api]\n') == {"noqa:banned-api": 1}


def test_indented_ruff_noqa_is_a_file_directive_but_trailing_text_is_not():
    source = "    # ruff: noqa: banned-api\nvalue = '# ruff: noqa'  # noqa: F401\n"
    assert count_source(source) == {"file-noqa:banned-api": 1, "noqa:F401": 1}


def test_standalone_ruff_ignore_is_budgeted_separately_from_inline_ignore():
    source = "# ruff: ignore[banned-api]\nvalue = 1  # ruff: ignore[banned-api]\n"
    assert count_source(source) == {"standalone-noqa:banned-api": 1, "noqa:banned-api": 1}


def test_ruff_enable_does_not_add_suppression_debt():
    assert count_source("# ruff: enable[banned-api]\n") == {}


def _tree(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(text, encoding="utf-8")


def test_measure_buckets_by_code_package_and_file(tmp_path: Path):
    _tree(
        tmp_path,
        {
            "svc_a/one.py": "x = 1  # noqa: E501\ny = 2  # noqa: E501\n",
            "svc_a/sub/two.py": "z = 3  # type: ignore\n",
            "svc_b/three.py": "w = 4  # noqa: F401\n",
        },
    )
    m = measure(tmp_path, ["svc_a", "svc_b"])
    assert m.codes == {"noqa:E501": 2, "type-ignore": 1, "noqa:F401": 1}
    assert m.packages == {"svc_a": 3, "svc_b": 1}
    assert m.files == {"svc_a/one.py": 2, "svc_a/sub/two.py": 1, "svc_b/three.py": 1}
    assert m.total == 4


def test_measure_skips_excluded_directories(tmp_path: Path):
    _tree(
        tmp_path,
        {
            "svc/app.py": "x = 1  # noqa: E501\n",
            "svc/.venv/lib/vendored.py": "y = 2  # noqa: E501\n",
            "svc/__pycache__/cached.py": "z = 3  # noqa: E501\n",
        },
    )
    assert measure(tmp_path, ["svc"]).total == 1


def test_measure_honours_excluded_subtrees(tmp_path: Path):
    _tree(
        tmp_path,
        {
            "svc/app.py": "x = 1  # noqa: E501\n",
            "svc/generated/client.py": "y = 2  # noqa: E501\n",
        },
    )
    m = measure(tmp_path, ["svc"], excluded_subtrees=["svc/generated"])
    assert m.total == 1
    assert m.packages == {"svc": 1}


def test_measure_reports_a_vanished_package_as_zero(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\n"})
    m = measure(tmp_path, ["svc", "renamed_away"])
    assert m.packages == {"svc": 1, "renamed_away": 0}


def test_measure_records_no_entry_for_a_clean_file(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "x = 1\n"})
    assert measure(tmp_path, ["svc"]).files == {}


def test_discover_packages_finds_dirs_containing_python(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "", "docs/readme.md": "", ".hidden/x.py": ""})
    assert discover_packages(tmp_path) == ["svc"]


def _measurement(
    codes: dict[str, int] | None = None,
    packages: dict[str, int] | None = None,
    files: dict[str, int] | None = None,
) -> Measurement:
    return Measurement(
        codes=Counter(codes or {}),
        packages=Counter(packages or {}),
        files=dict(files or {}),
    )


def test_gate_passes_when_every_count_is_at_or_below_its_ceiling():
    m = _measurement(codes={"noqa:E501": 3}, packages={"svc": 3}, files={"svc/a.py": 3})
    baseline = Baseline(codes={"noqa:E501": 3}, packages={"svc": 3})
    assert gate(m, baseline) == []


def test_gate_fails_a_code_over_its_ceiling():
    m = _measurement(codes={"noqa:E501": 4}, packages={"svc": 4}, files={"svc/a.py": 4})
    baseline = Baseline(codes={"noqa:E501": 3}, packages={"svc": 4})
    failures = gate(m, baseline)
    assert [(f.dimension, f.key, f.ceiling, f.actual) for f in failures] == [("code", "noqa:E501", 3, 4)]


def test_a_code_absent_from_the_baseline_has_a_ceiling_of_zero():
    m = _measurement(codes={"noqa:NEW1": 1}, packages={"svc": 1})
    failures = gate(m, Baseline(packages={"svc": 1}))
    assert [f.key for f in failures] == ["noqa:NEW1"]


def test_gate_fails_a_package_over_its_ceiling_even_when_codes_hold():
    # Moving a suppression between codes keeps every per-code ceiling but the
    # package total still rose.
    m = _measurement(codes={"noqa:A1": 2, "noqa:B2": 2}, packages={"svc": 4})
    baseline = Baseline(codes={"noqa:A1": 2, "noqa:B2": 2}, packages={"svc": 3})
    assert [(f.dimension, f.key) for f in gate(m, baseline)] == [("package", "svc")]


def test_gate_fails_a_file_over_the_per_file_ceiling():
    m = _measurement(codes={"noqa:A1": 12}, packages={"svc": 12}, files={"svc/hot.py": 12})
    baseline = Baseline(codes={"noqa:A1": 12}, packages={"svc": 12}, per_file_ceiling=10)
    assert [(f.dimension, f.key, f.ceiling) for f in gate(m, baseline)] == [("file", "svc/hot.py", 10)]


def test_a_grandfathered_file_is_held_at_its_own_ceiling():
    baseline = Baseline(
        codes={"noqa:A1": 25},
        packages={"svc": 25},
        per_file_ceiling=10,
        file_exceptions={"svc/legacy.py": 25},
    )
    at_ceiling = _measurement(codes={"noqa:A1": 25}, packages={"svc": 25}, files={"svc/legacy.py": 25})
    assert gate(at_ceiling, baseline) == []
    over = _measurement(codes={"noqa:A1": 26}, packages={"svc": 26}, files={"svc/legacy.py": 26})
    assert {f.dimension for f in gate(over, baseline)} == {"code", "package", "file"}


def test_failures_are_ordered_code_then_package_then_file():
    m = _measurement(codes={"noqa:A1": 20}, packages={"svc": 20}, files={"svc/a.py": 20})
    assert [f.dimension for f in gate(m, Baseline())] == ["code", "package", "file"]


def test_failure_message_names_both_numbers_and_a_remedy():
    m = _measurement(codes={"noqa:A1": 4}, packages={"svc": 4})
    text = gate(m, Baseline(codes={"noqa:A1": 3}, packages={"svc": 4}))[0].format()
    assert "noqa:A1" in text
    assert "4" in text
    assert "3" in text
    assert "--allow-increase" in text


def test_improvements_reports_shrunk_and_retired_codes():
    m = _measurement(codes={"noqa:A1": 1}, packages={"svc": 1})
    baseline = Baseline(codes={"noqa:A1": 3, "noqa:GONE": 2}, packages={"svc": 3})
    assert improvements(m, baseline) == {"noqa:A1": (3, 1), "noqa:GONE": (2, 0)}


def test_seed_drops_a_file_exception_once_the_debt_is_paid():
    baseline = Baseline(per_file_ceiling=10, file_exceptions={"svc/legacy.py": 25})
    m = _measurement(codes={"noqa:A1": 9}, packages={"svc": 9}, files={"svc/legacy.py": 9})
    assert seed(m, baseline).file_exceptions == {}


def test_seed_keeps_a_still_needed_file_exception_at_the_new_lower_count():
    baseline = Baseline(per_file_ceiling=10, file_exceptions={"svc/legacy.py": 25})
    m = _measurement(codes={"noqa:A1": 18}, packages={"svc": 18}, files={"svc/legacy.py": 18})
    assert seed(m, baseline).file_exceptions == {"svc/legacy.py": 18}


def test_seed_preserves_the_per_file_ceiling():
    assert seed(_measurement(), Baseline(per_file_ceiling=4)).per_file_ceiling == 4


def test_load_baseline_reads_all_three_sections(tmp_path: Path):
    path = tmp_path / "b.json"
    _ = path.write_text(
        json.dumps(
            {
                "codes": {"noqa:E501": 3},
                "packages": {"svc": 3},
                "files": {"per_file_ceiling": 4, "exceptions": {"svc/a.py": 9}},
            }
        ),
        encoding="utf-8",
    )
    baseline = load_baseline(path)
    assert baseline.codes == {"noqa:E501": 3}
    assert baseline.packages == {"svc": 3}
    assert baseline.per_file_ceiling == 4
    assert baseline.file_exceptions == {"svc/a.py": 9}


def test_dumped_baseline_declares_its_schema_version(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\n"})
    assert main([str(tmp_path), "--update"]) == 0
    text = (tmp_path / "suppression-baseline.json").read_text(encoding="utf-8")
    assert '"schema_version": 1' in text


def test_load_baseline_rejects_an_unknown_schema_version(tmp_path: Path):
    path = tmp_path / "b.json"
    _ = path.write_text('{"schema_version": 999}', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported suppression baseline schema_version"):
        load_baseline(path)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("[]", id="top-level-list"),
        pytest.param('"nope"', id="top-level-string"),
        pytest.param('{"codes": "nope"}', id="codes-not-an-object"),
        pytest.param('{"codes": {"noqa:A1": "three"}}', id="count-not-an-int"),
        pytest.param('{"codes": {"noqa:A1": true}}', id="count-is-a-bool"),
        pytest.param('{"files": {"per_file_ceiling": "ten"}}', id="ceiling-not-an-int"),
    ],
)
def test_a_malformed_baseline_degrades_to_no_allowance(tmp_path: Path, payload: str):
    path = tmp_path / "b.json"
    _ = path.write_text(payload, encoding="utf-8")
    baseline = load_baseline(path)
    assert baseline.codes == {}
    assert baseline.per_file_ceiling == 10


def test_a_comment_key_is_not_read_as_a_ceiling(tmp_path: Path):
    path = tmp_path / "b.json"
    _ = path.write_text(json.dumps({"_comment": "prose", "codes": {"noqa:A1": 1}}), encoding="utf-8")
    assert load_baseline(path).codes == {"noqa:A1": 1}


def test_cli_seeds_a_first_baseline_without_allow_increase(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\n"})
    assert main([str(tmp_path), "--update"]) == 0
    written = load_baseline(tmp_path / "suppression-baseline.json")
    assert written.codes == {"noqa:E501": 1}
    assert written.packages == {"svc": 1}


def test_cli_persists_excluded_subtrees_for_future_checks(tmp_path: Path):
    _tree(
        tmp_path,
        {
            "svc/app.py": "x = 1  # noqa: E501\n",
            "generated/client.py": "y = 2  # type: ignore\n",
        },
    )

    assert main([str(tmp_path), "--exclude-subtree", "generated", "--update"]) == 0
    written = load_baseline(tmp_path / "suppression-baseline.json")

    assert written.excluded_subtrees == ("generated",)
    assert main([str(tmp_path)]) == 0


def test_cli_passes_when_counts_hold(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\n"})
    assert main([str(tmp_path), "--update"]) == 0
    assert main([str(tmp_path)]) == 0


def test_cli_fails_when_a_count_rises(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\n"})
    assert main([str(tmp_path), "--update"]) == 0
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\ny = 2  # noqa: E501\n"})
    assert main([str(tmp_path)]) == 1


def test_cli_update_refuses_a_raise_without_allow_increase(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\n"})
    assert main([str(tmp_path), "--update"]) == 0
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\ny = 2  # noqa: E501\n"})
    assert main([str(tmp_path), "--update"]) == 1
    written = load_baseline(tmp_path / "suppression-baseline.json")
    assert written.codes == {"noqa:E501": 1}, "the refused update must not have written"


def test_cli_update_accepts_a_reviewed_raise(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\n"})
    assert main([str(tmp_path), "--update"]) == 0
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\ny = 2  # noqa: E501\n"})
    assert main([str(tmp_path), "--update", "--allow-increase"]) == 0
    written = load_baseline(tmp_path / "suppression-baseline.json")
    assert written.codes == {"noqa:E501": 2}


def test_cli_update_always_locks_in_a_drop(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\ny = 2  # noqa: E501\n"})
    assert main([str(tmp_path), "--update"]) == 0
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\n"})
    assert main([str(tmp_path), "--update"]) == 0
    written = load_baseline(tmp_path / "suppression-baseline.json")
    assert written.codes == {"noqa:E501": 1}


def test_cli_per_file_ceiling_flag_overrides_the_baseline(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "".join(f"x{i} = 1  # noqa: E501\n" for i in range(6))})
    assert main([str(tmp_path), "--update"]) == 0
    assert main([str(tmp_path)]) == 0
    assert main([str(tmp_path), "--per-file-ceiling", "5"]) == 1


def test_cli_scopes_to_named_packages(tmp_path: Path):
    _tree(
        tmp_path,
        {"svc_a/app.py": "x = 1  # noqa: E501\n", "svc_b/app.py": "y = 2  # noqa: F401\n"},
    )
    assert main([str(tmp_path), "--package", "svc_a", "--update"]) == 0
    written = load_baseline(tmp_path / "suppression-baseline.json")
    assert written.codes == {"noqa:E501": 1}


def test_cli_honours_a_custom_baseline_path(tmp_path: Path):
    _tree(tmp_path, {"svc/app.py": "x = 1  # noqa: E501\n"})
    custom = tmp_path / "ceilings.json"
    assert main([str(tmp_path), "--baseline", str(custom), "--update"]) == 0
    assert custom.exists()
    assert not (tmp_path / "suppression-baseline.json").exists()


def test_cli_errors_when_the_tree_has_no_python(tmp_path: Path):
    assert main([str(tmp_path)]) == 1
