from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rules.production_derived_test_cases import ProductionDerivedTestCases


TEST_PATH = Path("tests/test_factory.py")


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
