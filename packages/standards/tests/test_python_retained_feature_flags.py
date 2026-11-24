from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sarj_python_lint.feature_flag_options import FeatureFlagOptions

from sarj_standards import api
from sarj_standards.libs.adoption.manifest import Manifest, load


if TYPE_CHECKING:
    from pathlib import Path


_RULE = "python:no-retained-feature-flag"
_MINIMAL = FeatureFlagOptions(modules=("app.flags",), snapshot_types=("FlagSnapshot",))
_FULL = FeatureFlagOptions(
    modules=("app.flags", "app.web.flags"),
    snapshot_types=("FlagSnapshot",),
    resolver_functions=("pinned_flags",),
    resolver_methods=("evaluate",),
    selector_methods=("for_",),
    startup_functions=("create_app", "Worker.start"),
    unit_of_work_types=("RequestFlags",),
    memoizers=("app.caching.memoize",),
    process_state=(),
)


@pytest.mark.parametrize("options", [None, _MINIMAL, _FULL], ids=["absent", "minimal", "full"])
def test_feature_flag_options_round_trip(tmp_path: Path, options: FeatureFlagOptions | None) -> None:
    adopted = Manifest(api.__version__, (), ".", ".", retained_feature_flags=options)
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render())

    assert load(tmp_path) == adopted


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ('modules = ["app.flags"]\n', "requires nonempty: snapshot_types"),
        ('modules = ["app.flags"]\nsnapshot_types = ["FlagSnapshot"]\nresolvers = []\n', "does not support: resolvers"),
        ('modules = "app.flags"\nsnapshot_types = ["FlagSnapshot"]\n', "modules must be an array"),
    ],
    ids=["missing-types", "unknown-key", "not-a-list"],
)
def test_malformed_feature_flag_options_are_rejected(tmp_path: Path, table: str, message: str) -> None:
    adopted = Manifest(api.__version__, (), ".", ".")
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render() + f"\n[python.no-retained-feature-flag]\n{table}")

    with pytest.raises(ValueError, match=message):
        load(tmp_path)


@pytest.mark.parametrize("configured", [False, True])
def test_analysis_reports_only_for_configured_repositories(tmp_path: Path, *, configured: bool) -> None:
    options = FeatureFlagOptions(
        modules=("app.flags",), snapshot_types=("FlagSnapshot",), resolver_functions=("pinned_flags",)
    )
    adopted = Manifest(api.__version__, (), ".", ".", retained_feature_flags=options if configured else None)
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render())
    (tmp_path / "service.py").write_text("from app.flags import pinned_flags\nFLAGS = pinned_flags()\n")

    report = api.Standards(tmp_path).analyze(["service.py"], rules=[_RULE])

    assert report.completion is api.Completion.COMPLETE
    assert [item.code for item in report.diagnostics] == (["SARJ594"] if configured else [])
