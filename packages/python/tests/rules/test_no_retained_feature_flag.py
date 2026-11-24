from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.feature_flag_options import FeatureFlagOptions, parse_feature_flag_options
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_retained_feature_flag import NoRetainedFeatureFlag


if TYPE_CHECKING:
    from pathlib import Path


_MANIFEST = (
    "[python.no-retained-feature-flag]\n"
    'modules = ["app.flags"]\n'
    'snapshot_types = ["FlagSnapshot"]\n'
    'resolver_functions = ["pinned_flags"]\n'
    'resolver_methods = ["evaluate"]\n'
    'selector_methods = ["for_"]\n'
    'startup_functions = ["create_app", "Worker.start"]\n'
    'unit_of_work_types = ["RequestFlags"]\n'
    'memoizers = ["app.caching.memoize"]\n'
)
_HEADER = (
    "from functools import cache, cached_property, lru_cache\n"
    "from app.caching import memoize\n"
    "from app.flags import NEW_CHECKOUT, FlagSnapshot, Switch, pinned_flags\n"
    "CHECKOUT = Switch(NEW_CHECKOUT, on=1, off=0)\n"
)
_FIRST_LINE = _HEADER.count("\n") + 1


def _lines(root: Path, body: str, *, manifest: str | None = _MANIFEST, name: str = "app/checkout.py") -> list[int]:
    (root / ".git").mkdir(exist_ok=True)
    if manifest is not None:
        (root / ".sarj-standards.toml").write_text(manifest)
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_HEADER + body)
    findings = analyze([NoRetainedFeatureFlag.id], [path])
    assert {(finding.code, finding.severity) for finding in findings} <= {("SARJ594", Severity.WARNING)}
    return [finding.line - _FIRST_LINE + 1 for finding in findings]


def test_documented_examples() -> None:
    verify_native_rule(NoRetainedFeatureFlag, analyze)


@pytest.mark.parametrize(
    "body",
    [
        "FLAGS = pinned_flags()\n",
        "ENABLED = CHECKOUT.for_(pinned_flags())\n",
        "ENABLED = pinned_flags().get(NEW_CHECKOUT)\n",
        "def pay(order, flags=pinned_flags()): ...\n",
        "LIMITS = [source.evaluate(tenant) for tenant in TENANTS]\n",
    ],
    ids=["module-snapshot", "module-selection", "module-read", "default-argument", "module-comprehension"],
)
def test_resolution_at_import_time(tmp_path: Path, body: str) -> None:
    assert _lines(tmp_path, body) == [1]


def test_resolution_in_a_class_body(tmp_path: Path) -> None:
    assert _lines(tmp_path, "class Settings:\n    enabled = pinned_flags().get(NEW_CHECKOUT)\n") == [2]


@pytest.mark.parametrize(
    ("body", "line"),
    [
        ("class Service:\n    def __init__(self, flags: FlagSnapshot) -> None:\n        self.flags = flags\n", 3),
        (
            "class Service:\n    def load(self, flags: FlagSnapshot | None) -> None:\n        self.on = flags.get(NEW_CHECKOUT)\n",
            3,
        ),
        (
            "class Service:\n    async def load(self, source) -> None:\n        self.pay = CHECKOUT.for_(await source.evaluate(None))\n",
            3,
        ),
        (
            "class Service:\n    def load(self) -> None:\n        flags = pinned_flags()\n        on = flags.get(NEW_CHECKOUT)\n        self.cache['on'] = not on\n",
            5,
        ),
        (
            "class Service:\n    def load(self, flags: 'FlagSnapshot') -> None:\n        def keep() -> None:\n            self.flags = flags\n",
            4,
        ),
        (
            "class Service:\n    @classmethod\n    def load(cls, flags: FlagSnapshot) -> None:\n        cls.flags = flags\n",
            4,
        ),
        ("class Service: ...\ndef load(flags: FlagSnapshot) -> None:\n    Service.flags = flags\n", 3),
        ("def load() -> None:\n    global FLAGS\n    FLAGS = pinned_flags()\n", 3),
        ("CACHE = {}\ndef load(tenant) -> None:\n    CACHE[tenant] = pinned_flags().get(NEW_CHECKOUT)\n", 3),
        ("def load(app, flags: FlagSnapshot) -> None:\n    app.state.flags = flags\n", 2),
        ("def load(request) -> None:\n    request.app.state.pay = CHECKOUT.for_(pinned_flags())\n", 2),
        (
            "def current() -> FlagSnapshot: ...\nclass Service:\n    def load(self) -> None:\n        self.flags: FlagSnapshot = current()\n",
            4,
        ),
    ],
    ids=[
        "self-snapshot",
        "self-read",
        "self-selection",
        "self-container-through-locals",
        "self-from-closure",
        "class-attribute-through-cls",
        "class-attribute-by-name",
        "module-global",
        "module-level-container",
        "application-state",
        "nested-application-state",
        "same-file-resolver",
    ],
)
def test_flag_values_kept_in_long_lived_state(tmp_path: Path, body: str, line: int) -> None:
    assert _lines(tmp_path, body) == [line]


@pytest.mark.parametrize(
    "decorator",
    ["@cache", "@lru_cache(maxsize=1)", "@memoize"],
)
def test_memoised_functions_that_resolve_flags(tmp_path: Path, decorator: str) -> None:
    assert _lines(tmp_path, f"{decorator}\ndef enabled() -> bool:\n    return pinned_flags().get(NEW_CHECKOUT)\n") == [
        3
    ]


def test_memoised_wrappers_and_properties(tmp_path: Path) -> None:
    body = (
        "def enabled() -> bool:\n"
        "    return pinned_flags().get(NEW_CHECKOUT)\n"
        "cached_enabled = cache(enabled)\n"
        "cached_choice = lru_cache(maxsize=1)(lambda: CHECKOUT.for_(pinned_flags()))\n"
        "class Service:\n"
        "    @cached_property\n"
        "    def enabled(self) -> bool:\n"
        "        return pinned_flags().get(NEW_CHECKOUT)\n"
    )

    assert _lines(tmp_path, body) == [2, 4, 8]


def test_resolution_in_configured_startup_functions(tmp_path: Path) -> None:
    body = (
        "def create_app(source):\n"
        "    if CHECKOUT.for_(pinned_flags()):\n"
        "        install()\n"
        "    def handler():\n"
        "        return CHECKOUT.for_(pinned_flags())\n"
        "    return handler\n"
        "class Worker:\n"
        "    async def start(self, source) -> None:\n"
        "        flags = await source.evaluate(None)\n"
        "        check(flags)\n"
        "    async def run(self, source, job) -> None:\n"
        "        check(await source.evaluate(job))\n"
        "def start(source) -> None:\n"
        "    check(pinned_flags())\n"
    )

    assert _lines(tmp_path, body) == [2, 9]


@pytest.mark.parametrize(
    "body",
    [
        "async def handle(source, request):\n    flags = await source.evaluate(request)\n    return CHECKOUT.for_(flags)(request)\n",
        "def pay(flags: FlagSnapshot, order):\n    charge = CHECKOUT.for_(flags)\n    return charge(order)\n",
        "def handle(order):\n    return pay(pinned_flags(), order)\n",
        "class Service:\n    def __init__(self, source, checkout) -> None:\n        self.source = source\n        self.checkout = checkout\n",
        "class RequestFlags:\n    def __init__(self) -> None:\n        self.snapshot: FlagSnapshot | None = None\n    def pin(self, flags: FlagSnapshot) -> None:\n        self.snapshot = flags\n    @cached_property\n    def on(self) -> bool:\n        return pinned_flags().get(NEW_CHECKOUT)\n",
        "def pin(holder, request, flags: FlagSnapshot) -> None:\n    holder.snapshot = flags\n    request.state.flags = flags\n    current().snapshot = flags\n",
        "def build(flags: FlagSnapshot):\n    job = Job()\n    job.flags = flags\n    choices = {}\n    choices['pay'] = CHECKOUT.for_(flags)\n    return job, choices\n",
        "@cache\ndef price(flags: FlagSnapshot, order) -> int:\n    return CHECKOUT.for_(flags)(order)\n",
        "class Service:\n    def load(self, registry) -> None:\n        self.rules = registry.evaluate\n        self.total = compute(self.rules)\n",
        "class Service:\n    def __init__(self, flags: FlagSnapshot) -> None:\n        self.flags = flags  # sarj-noqa: SARJ594 -- one instance is built per job\n",
    ],
    ids=[
        "resolved-per-request",
        "snapshot-argument",
        "snapshot-passed-on",
        "source-and-selector-kept",
        "unit-of-work-holder",
        "per-request-objects",
        "local-objects",
        "memoised-by-snapshot",
        "unrelated-attribute",
        "suppressed-with-reason",
    ],
)
def test_allowed_shapes(tmp_path: Path, body: str) -> None:
    assert _lines(tmp_path, body) == []


@pytest.mark.parametrize(
    ("manifest", "name"),
    [
        (None, "app/checkout.py"),
        ("[python]\n", "app/checkout.py"),
        (_MANIFEST, "tests/test_checkout.py"),
        (_MANIFEST.replace("app.flags", "other.flags"), "app/checkout.py"),
    ],
    ids=["no-manifest", "not-configured", "test-file", "module-not-named"],
)
def test_rule_is_inactive_without_matching_configuration(tmp_path: Path, manifest: str | None, name: str) -> None:
    assert _lines(tmp_path, "FLAGS = pinned_flags()\n", manifest=manifest, name=name) == []


def test_minimal_options_use_defaults() -> None:
    expected = FeatureFlagOptions(modules=("app.flags",), snapshot_types=("FlagSnapshot",))

    assert parse_feature_flag_options({"modules": ["app.flags"], "snapshot_types": ["FlagSnapshot"]}) == expected
    assert expected.process_state == ("app.state",)
    assert expected.owns_module("app.flags.snapshot")
    assert not expected.owns_module("app.flagship")
    assert parse_feature_flag_options({}) is None


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ({"modules": ["app.flags"]}, "requires nonempty: snapshot_types"),
        ({"modules": [], "snapshot_types": ["FlagSnapshot"]}, "requires nonempty: modules"),
        (
            {"modules": ["app.flags"], "snapshot_types": ["FlagSnapshot"], "resolvers": []},
            "does not support: resolvers",
        ),
        ({"modules": "app.flags", "snapshot_types": ["FlagSnapshot"]}, "modules must be an array"),
        ({"modules": ["app.flags"], "snapshot_types": ["app.FlagSnapshot"]}, "snapshot_types must be an array"),
        ({"modules": ["app.flags", "app.flags"], "snapshot_types": ["FlagSnapshot"]}, "modules must be an array"),
    ],
    ids=["missing-types", "empty-modules", "unknown-key", "not-a-list", "dotted-type-name", "duplicate"],
)
def test_malformed_options_are_rejected(table: dict[str, list[str] | str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_feature_flag_options(table)


def test_malformed_manifest_table_stops_analysis(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires nonempty: snapshot_types"):
        _lines(
            tmp_path,
            "FLAGS = pinned_flags()\n",
            manifest='[python.no-retained-feature-flag]\nmodules = ["app.flags"]\n',
        )
