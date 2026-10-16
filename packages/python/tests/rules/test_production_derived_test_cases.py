from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rules.production_derived_test_cases import ProductionDerivedTestCases


TEST_PATH = Path("app/tests/test_factory.py")


def _check(source: str, path: Path = TEST_PATH):
    return ProductionDerivedTestCases().check(path, textwrap.dedent(source))


@pytest.mark.parametrize(
    "decorator",
    [
        "@pytest.mark.parametrize('model', ELIGIBLE_MODELS)",
        "@pytest.mark.parametrize('model', sorted(ELIGIBLE_MODELS))",
        "@pytest.mark.parametrize('model', tuple(ELIGIBLE_MODELS))",
        "@pytest.mark.parametrize('model', set(Model) - ELIGIBLE_MODELS)",
    ],
)
def test_flags_imported_production_collections_as_case_oracles(decorator: str) -> None:
    source = f"""
    import pytest
    from app.models import ELIGIBLE_MODELS
    {decorator}
    def test_model(model):
        assert build(model) is not None
    """
    [diag] = _check(source)
    assert diag.code == "SARJ409"
    assert diag.line == 4


def test_allows_independent_local_case_tables() -> None:
    source = """
    EXPECTED_ELIGIBLE_MODELS = ("a", "b")

    @pytest.mark.parametrize("model", EXPECTED_ELIGIBLE_MODELS)
    def test_model(model):
        assert build(model).tier == "priority"
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "decorator",
    [
        "@pytest.mark.parametrize('kind', list(Kind))",
        "@pytest.mark.parametrize('kind', tuple(Kind))",
        "@pytest.mark.parametrize('kind', [Kind.A, Kind.B])",
    ],
)
def test_allows_enum_exhaustiveness_sweeps(decorator: str) -> None:
    source = f"""
    from app.models import Kind
    {decorator}
    def test_kind(kind):
        assert classify(kind) in {{"x", "y"}}
    """
    assert _check(source) == []


def test_allows_fixture_data_imported_from_test_helpers() -> None:
    source = """
    from tests.cases import CASES

    @pytest.mark.parametrize("case", CASES)
    def test_case(case):
        assert normalize(case.input) == case.expected
    """
    assert _check(source) == []


def test_allows_registry_meta_tests_that_must_cover_every_registered_rule() -> None:
    source = """
    from app.rules import REGISTRY

    @pytest.mark.parametrize("rule", REGISTRY)
    def test_every_registered_rule_has_docs(rule):
        assert docs_exist(rule)
    """
    assert _check(source) == []


def test_allows_behavior_sweeps_when_membership_has_an_independent_oracle() -> None:
    source = """
    from app.models import ELIGIBLE_MODELS

    @pytest.mark.parametrize("model", ELIGIBLE_MODELS)
    def test_model(model):
        assert build(model).tier == "priority"

    def test_eligible_models_are_exact():
        assert ELIGIBLE_MODELS == {"a", "b"}
    """
    assert _check(source) == []


def test_skips_non_test_files_and_malformed_input() -> None:
    source = "import pytest\nfrom app.models import CASES\n@pytest.mark.parametrize('x', CASES)\ndef test_x(x): pass\n"
    assert _check(source, Path("src/module.py")) == []
    assert _check("def test_broken(") == []


@pytest.mark.parametrize(
    ("imports", "decorator"),
    [
        ("import pytest as pt", "@pt.mark.parametrize('model', ELIGIBLE_MODELS)"),
        ("from pytest import mark as cases", "@cases.parametrize('model', ELIGIBLE_MODELS)"),
    ],
)
def test_resolves_pytest_aliases(imports: str, decorator: str) -> None:
    source = f"""
    {imports}
    from app.models import ELIGIBLE_MODELS

    {decorator}
    def test_model(model):
        assert build(model) is not None
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        """
        from app.models import ELIGIBLE_MODELS

        @runner.mark.parametrize('model', ELIGIBLE_MODELS)
        def test_model(model):
            assert build(model) is not None
        """,
        """
        import pytest
        from app.models import ELIGIBLE_MODELS
        pytest = custom_runner

        @pytest.mark.parametrize('model', ELIGIBLE_MODELS)
        def test_model(model):
            assert build(model) is not None
        """,
        """
        import pytest
        from app.models import ELIGIBLE_MODELS
        ELIGIBLE_MODELS = ('independent',)

        @pytest.mark.parametrize('model', ELIGIBLE_MODELS)
        def test_model(model):
            assert build(model) is not None
        """,
    ],
)
def test_rejects_unproven_or_rebound_bindings(source: str) -> None:
    assert _check(source) == []


def test_checks_module_functions_and_collected_class_methods_only() -> None:
    source = """
    import pytest
    from app.models import ELIGIBLE_MODELS

    @pytest.mark.parametrize('model', ELIGIBLE_MODELS)
    def test_module(model):
        assert build(model) is not None

    class TestModels:
        @pytest.mark.parametrize('model', ELIGIBLE_MODELS)
        def test_method(self, model):
            assert build(model) is not None

    def helper():
        @pytest.mark.parametrize('model', ELIGIBLE_MODELS)
        def test_nested(model):
            assert build(model) is not None
    """
    assert len(_check(source)) == 2


def test_class_scope_shadowing_rejects_pytest_provenance() -> None:
    source = """
    import pytest
    from app.models import ELIGIBLE_MODELS

    class TestModels:
        pytest = custom_runner

        @pytest.mark.parametrize('model', ELIGIBLE_MODELS)
        def test_method(self, model):
            assert build(model) is not None
    """
    assert _check(source) == []


def test_class_scope_shadowing_rejects_collection_provenance() -> None:
    source = """
    import pytest
    from app.models import ELIGIBLE_MODELS

    class TestModels:
        ELIGIBLE_MODELS = ("local",)

        @pytest.mark.parametrize("model", ELIGIBLE_MODELS)
        def test_method(self, model):
            assert build(model) is not None
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "import_line",
    [
        pytest.param("from .cases import ELIGIBLE_MODELS", id="relative-helper"),
        pytest.param("from app.tests.cases import ELIGIBLE_MODELS", id="test-package"),
        pytest.param("from app.testing.cases import ELIGIBLE_MODELS", id="testing-package"),
        pytest.param("from app.testing_utils.cases import ELIGIBLE_MODELS", id="testing-utilities"),
        pytest.param("from app.fakes.cases import ELIGIBLE_MODELS", id="fake-package"),
        pytest.param("from string import ascii_letters as ELIGIBLE_MODELS", id="stdlib"),
    ],
)
def test_excludes_unproven_or_test_support_imports(import_line: str) -> None:
    source = f"""
    import pytest
    {import_line}

    @pytest.mark.parametrize("model", ELIGIBLE_MODELS)
    def test_model(model):
        assert build(model) is not None
    """
    assert _check(source) == []


def test_ignores_generic_dynamic_sweep_without_membership_contract_name() -> None:
    source = """
    import pytest
    from app.formats import ALL_FORMATS

    @pytest.mark.parametrize("format", ALL_FORMATS)
    def test_every_format_round_trips(format):
        assert round_trip(format)
    """
    assert _check(source) == []


def test_tautological_or_unreachable_assertion_is_not_an_oracle() -> None:
    source = """
    import pytest
    from app.models import ELIGIBLE_MODELS

    if False:
        assert ELIGIBLE_MODELS == {"a", "b"}

    def helper():
        assert ELIGIBLE_MODELS == {"a", "b"}

    assert ELIGIBLE_MODELS == ELIGIBLE_MODELS

    @pytest.mark.parametrize("model", ELIGIBLE_MODELS)
    def test_model(model):
        assert build(model) is not None
    """
    assert len(_check(source)) == 1


def test_rebound_expected_table_is_not_an_independent_oracle() -> None:
    source = """
    import pytest
    from app.models import ELIGIBLE_MODELS

    EXPECTED_MODELS = ("a", "b")
    EXPECTED_MODELS = ELIGIBLE_MODELS

    def test_membership():
        assert ELIGIBLE_MODELS == EXPECTED_MODELS

    @pytest.mark.parametrize("model", ELIGIBLE_MODELS)
    def test_model(model):
        assert build(model) is not None
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "oracle",
    [
        pytest.param(
            "def test_membership(ELIGIBLE_MODELS):\n    assert ELIGIBLE_MODELS == ('a', 'b')\n",
            id="production-fixture-parameter",
        ),
        pytest.param(
            "def test_membership(*ELIGIBLE_MODELS):\n    assert ELIGIBLE_MODELS == ('a', 'b')\n",
            id="production-vararg",
        ),
        pytest.param(
            "def test_membership(**ELIGIBLE_MODELS):\n    assert ELIGIBLE_MODELS == {'a', 'b'}\n",
            id="production-keyword-capture",
        ),
        pytest.param(
            "def test_membership():\n    ELIGIBLE_MODELS = ('a', 'b')\n    assert ELIGIBLE_MODELS == ('a', 'b')\n",
            id="production-local-setup",
        ),
        pytest.param(
            "def test_membership():\n    from tests.cases import ELIGIBLE_MODELS\n    assert ELIGIBLE_MODELS == ('a', 'b')\n",
            id="production-local-import",
        ),
        pytest.param(
            "def test_membership(EXPECTED_MODELS):\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="expected-fixture-parameter",
        ),
        pytest.param(
            "def test_membership():\n    EXPECTED_MODELS = ELIGIBLE_MODELS\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="expected-production-alias",
        ),
        pytest.param(
            "def test_membership():\n    EXPECTED_MODELS = ['a', 'b']\n    EXPECTED_MODELS[:] = ELIGIBLE_MODELS\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="expected-local-mutation",
        ),
        pytest.param(
            "def test_membership(ELIGIBLE_MODELS=ELIGIBLE_MODELS):\n    ELIGIBLE_MODELS = ('a', 'b')\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="rebound-production-capture",
        ),
        pytest.param(
            "def test_membership(EXPECTED_MODELS=EXPECTED_MODELS):\n    EXPECTED_MODELS = ELIGIBLE_MODELS\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="rebound-expected-capture",
        ),
        pytest.param(
            "class TestMembership:\n    ELIGIBLE_MODELS = ('a', 'b')\n    def test_exact(self, ELIGIBLE_MODELS=ELIGIBLE_MODELS):\n        assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="production-default-reads-class-namespace",
        ),
        pytest.param(
            "class TestMembership:\n    EXPECTED_MODELS = ELIGIBLE_MODELS\n    def test_exact(self, EXPECTED_MODELS=EXPECTED_MODELS):\n        assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="expected-default-reads-class-namespace",
        ),
        pytest.param(
            "def test_membership():\n    from app.other import ELIGIBLE_MODELS\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="same-symbol-different-module",
        ),
        pytest.param(
            "def test_membership():\n    from app.models import SUPPORTED_MODELS as ELIGIBLE_MODELS\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="same-module-different-symbol",
        ),
        pytest.param(
            "def test_membership():\n    from .app.models import ELIGIBLE_MODELS\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="relative-reimport",
        ),
        pytest.param(
            "def test_membership():\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n    from app.models import ELIGIBLE_MODELS\n",
            id="reimport-after-assertion",
        ),
    ],
)
def test_shadowed_equality_does_not_prove_production_membership(oracle: str) -> None:
    source = (
        "import pytest\nfrom app.models import ELIGIBLE_MODELS\nEXPECTED_MODELS = ('a', 'b')\n"
        f"{oracle}\n@pytest.mark.parametrize('model', ELIGIBLE_MODELS)\n"
        "def test_model(model):\n    assert build(model)\n"
    )
    assert [finding.code for finding in _check(source)] == ["SARJ409"]


@pytest.mark.parametrize(
    "oracle",
    [
        pytest.param(
            "def test_membership():\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="module-expected-tuple",
        ),
        pytest.param(
            "def test_membership():\n    EXPECTED_MODELS = ('a', 'b')\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="local-expected-tuple",
        ),
        pytest.param(
            "def test_membership():\n    EXPECTED_MODELS = ['a', 'b']\n    assert EXPECTED_MODELS == ELIGIBLE_MODELS\n",
            id="fresh-local-expected-list",
        ),
        pytest.param(
            "def test_membership():\n    EXPECTED_MODELS = {'a', 'b'}\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="fresh-local-expected-set",
        ),
        pytest.param(
            "def test_membership():\n    def helper():\n        ELIGIBLE_MODELS = ()\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="nested-helper-scope",
        ),
        pytest.param(
            "class TestMembership:\n    ELIGIBLE_MODELS = ()\n    def test_exact(self):\n        assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="class-namespace-is-not-method-lexical-scope",
        ),
        pytest.param(
            "def test_membership(ELIGIBLE_MODELS=ELIGIBLE_MODELS):\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="production-default-capture",
        ),
        pytest.param(
            "def test_membership(EXPECTED_MODELS=EXPECTED_MODELS):\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="expected-tuple-default-capture",
        ),
        pytest.param(
            "def test_membership(ELIGIBLE_MODELS=ELIGIBLE_MODELS, /):\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="positional-only-default-capture",
        ),
        pytest.param(
            "def test_membership(*, ELIGIBLE_MODELS=ELIGIBLE_MODELS):\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="keyword-only-default-capture",
        ),
        pytest.param(
            "class TestMembership:\n    def test_exact(self, ELIGIBLE_MODELS=ELIGIBLE_MODELS):\n        assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="method-default-without-class-shadow",
        ),
        pytest.param(
            "def test_membership():\n    from app.models import ELIGIBLE_MODELS\n    assert ELIGIBLE_MODELS == EXPECTED_MODELS\n",
            id="exact-production-reimport",
        ),
    ],
)
def test_preserves_independent_oracles_in_their_lexical_scope(oracle: str) -> None:
    source = (
        "import pytest\nfrom app.models import ELIGIBLE_MODELS\nEXPECTED_MODELS = ('a', 'b')\n"
        f"{oracle}\n@pytest.mark.parametrize('model', ELIGIBLE_MODELS)\n"
        "def test_model(model):\n    assert build(model)\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    ("local_import", "expected_codes"),
    [
        ("from app.models import ELIGIBLE_MODELS as SUPPORTED_MODELS", []),
        ("from app.models import SUPPORTED_MODELS", ["SARJ409"]),
        ("from app.models import ELIGIBLE_MODELS as SUPPORTED_MODELS, OTHER as SUPPORTED_MODELS", ["SARJ409"]),
        ("from app.models import OTHER, ELIGIBLE_MODELS as SUPPORTED_MODELS", []),
    ],
)
def test_reimports_preserve_original_symbol_identity_through_aliases(
    local_import: str, expected_codes: list[str]
) -> None:
    source = (
        "import pytest\nfrom app.models import ELIGIBLE_MODELS as SUPPORTED_MODELS\n"
        "def test_membership():\n"
        f"    {local_import}\n    assert SUPPORTED_MODELS == ('a', 'b')\n"
        "@pytest.mark.parametrize('model', SUPPORTED_MODELS)\n"
        "def test_model(model):\n    assert build(model)\n"
    )
    assert [finding.code for finding in _check(source)] == expected_codes


def test_accepts_keyword_argvalues_and_exact_suppression() -> None:
    source = """
    import pytest
    from app.models import ELIGIBLE_MODELS

    @pytest.mark.parametrize(argnames="model", argvalues=ELIGIBLE_MODELS)  # sarj-noqa: SARJ409 — dynamic smoke sweep
    def test_model(model):
        assert build(model) is not None
    """
    assert _check(source) == []


def test_shadowed_collection_wrapper_is_not_treated_as_builtin() -> None:
    source = """
    import pytest
    from app.models import ELIGIBLE_MODELS

    sorted = custom_sort

    @pytest.mark.parametrize("model", sorted(ELIGIBLE_MODELS))
    def test_model(model):
        assert build(model) is not None
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    ("path", "banner"),
    [
        (Path("tests/generated/test_factory.py"), ""),
        (TEST_PATH, "# Code generated by case compiler. DO NOT EDIT.\n"),
    ],
)
def test_skips_generated_tests(path: Path, banner: str) -> None:
    source = f"{banner}import pytest\nfrom app.models import CASES\n@pytest.mark.parametrize('x', CASES)\ndef test_x(x): pass\n"
    assert _check(source, path) == []
