from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.uncontrolled_randomness_in_test import UncontrolledRandomnessInTest


TEST_PATH = Path("tests/test_selector.py")


def _check(source: str, path: Path = TEST_PATH):
    return UncontrolledRandomnessInTest().check(path, textwrap.dedent(source))


@pytest.mark.parametrize(
    ("imports", "call"),
    [
        ("import random", "random.choice(items)"),
        ("import random as rnd", "rnd.randint(1, 5)"),
        ("from random import choice", "choice(items)"),
        ("from random import choice as pick", "pick(items)"),
    ],
)
def test_flags_unseeded_prng_calls_repeated_in_a_test(imports: str, call: str) -> None:
    source = f"""
    {imports}
    def test_distribution():
        counts = []
        for _ in range(100):
            counts.append({call})
        assert len(counts) == 100
    """
    [diag] = _check(source)
    assert diag.code == "SARJ410"
    assert diag.line == 6
    assert diag.severity is Severity.WARNING


def test_flags_randomness_in_a_comprehension() -> None:
    source = """
    import random
    def test_distribution():
        values = [random.random() for _ in range(50)]
        assert min(values) < 0.5
    """
    assert len(_check(source)) == 1


def test_allows_a_fixed_seed() -> None:
    source = """
    import random
    def test_distribution():
        random.seed(17)
        values = [random.random() for _ in range(50)]
        assert min(values) < 0.5
    """
    assert _check(source) == []


@pytest.mark.parametrize("seed", ["", "None", "time.time()"], ids=["implicit", "none", "dynamic"])
def test_nondeterministic_seed_does_not_suppress(seed: str) -> None:
    argument = seed
    source = f"""
    import random
    import time
    def test_distribution():
        random.seed({argument})
        values = [random.random() for _ in range(50)]
        assert min(values) < 0.5
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "seed_statement",
    [
        "if enabled:\n        random.seed(17)",
        "values = [random.random() for _ in range(50)]\n    random.seed(17)",
    ],
)
def test_conditional_or_late_seed_does_not_suppress(seed_statement: str) -> None:
    sample = "values = [random.random() for _ in range(50)]"
    body = seed_statement if sample in seed_statement else f"{seed_statement}\n    {sample}"
    source = f"import random\ndef test_distribution(enabled=True):\n    {body}\n    assert values\n"
    assert len(_check(source)) == 1


def test_unconditional_seed_only_suppresses_later_samples() -> None:
    source = """
    import random
    def test_distribution():
        before = [random.random() for _ in range(10)]
        random.seed(17)
        after = [random.random() for _ in range(10)]
        assert before != after
    """
    [diag] = _check(source)
    assert diag.line == 4


def test_allows_single_draw_domain_assertion() -> None:
    source = """
    import random
    def test_choice_is_from_domain():
        result = random.choice(["a", "b"])
        assert result in {"a", "b"}
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "for item in random.sample(items, 3):\n        consume(item)",
        "values = [item for item in random.sample(items, 3)]",
        "for item in items:\n        consume(item)\n    else:\n        value = random.random()",
        "for _ in range(1):\n        value = random.random()",
        "values = [random.random() for _ in range(1)]",
        "values = [random.random() for _ in range(1) for _ in range(1)]",
        "while False:\n        value = random.random()",
    ],
    ids=[
        "for-iter",
        "first-comprehension-iter",
        "for-else",
        "single-iteration",
        "single-iteration-comprehension",
        "nested-single-iteration-comprehension",
        "statically-false-while",
    ],
)
def test_does_not_flag_single_evaluation_regions(source: str) -> None:
    body = source.replace("\n", "\n    ")
    assert _check(f"import random\ndef test_distribution(items):\n    {body}\n") == []


def test_flags_a_test_local_random_import() -> None:
    source = """
    def test_distribution():
        import random
        values = [random.random() for _ in range(50)]
        assert min(values) < 0.5
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize("method", ["gauss(0, 1)", "getrandbits(8)", "randbytes(4)"])
def test_flags_additional_stdlib_sampling_apis(method: str) -> None:
    source = f"import random\ndef test_distribution():\n    assert [random.{method} for _ in range(5)]\n"
    assert len(_check(source)) == 1


def test_flags_an_unseeded_local_random_instance() -> None:
    source = """
    import random
    def test_distribution():
        rng = random.Random()
        values = [rng.random() for _ in range(50)]
        assert min(values) < 0.5
    """
    assert len(_check(source)) == 1


def test_allows_a_seeded_local_random_instance() -> None:
    source = """
    import random
    def test_distribution():
        rng = random.Random(17)
        values = [rng.random() for _ in range(50)]
        assert min(values) < 0.5
    """
    assert _check(source) == []


def test_allows_injected_rng_and_property_frameworks() -> None:
    source = """
    from hypothesis import given, strategies as st
    @given(st.integers())
    def test_property(value):
        assert roundtrip(value) == value

    def test_with_injected_rng(rng):
        values = [rng.random() for _ in range(50)]
        assert values
    """
    assert _check(source) == []


def test_does_not_attribute_nested_helper_randomness_to_the_test() -> None:
    source = """
    import random
    def test_distribution():
        def generate_samples():
            return [random.random() for _ in range(50)]
        assert len(generate_samples()) == 50
    """
    assert _check(source) == []


def test_does_not_walk_nested_function_or_class_inside_repeat() -> None:
    source = """
    import random
    def test_distribution():
        for _ in range(2):
            def nested():
                return random.random()
            class Nested:
                value = random.random()
        assert nested
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        """
        import random
        random = fake_random
        def test_distribution():
            values = [random.random() for _ in range(50)]
            assert values
        """,
        """
        from random import choice as pick
        def test_distribution(pick):
            values = [pick(items) for _ in range(50)]
            assert values
        """,
        """
        import random
        def test_distribution():
            random = fake_random
            values = [random.random() for _ in range(50)]
            assert values
        """,
    ],
)
def test_rejects_rebound_or_shadowed_random_aliases(source: str) -> None:
    assert _check(source) == []


def test_only_checks_module_functions_and_collected_class_methods() -> None:
    source = """
    import random

    def test_module():
        assert [random.random() for _ in range(5)]

    class TestDistribution:
        def test_method(self):
            assert [random.random() for _ in range(5)]

    def helper():
        def test_nested():
            assert [random.random() for _ in range(5)]
    """
    assert len(_check(source)) == 2


def test_skips_disabled_modules_classes_and_fixtures() -> None:
    module = "import random\n__test__ = False\ndef test_x():\n    assert [random.random() for _ in range(5)]\n"
    assert _check(module) == []
    source = """
    import random
    import pytest
    @pytest.fixture
    def test_data():
        return [random.random() for _ in range(5)]
    class TestDisabled:
        __test__ = False
        def test_x(self):
            assert [random.random() for _ in range(5)]
    """
    assert _check(source) == []


def test_skips_non_test_files_and_malformed_input() -> None:
    source = "import random\ndef test_x():\n    return [random.random() for _ in range(5)]\n"
    assert _check(source, Path("src/module.py")) == []
    assert _check("def test_broken(") == []


@pytest.mark.parametrize(
    "path",
    [Path("tests/helpers.py"), Path("scripts/test_probe.py")],
    ids=["test-support-module", "script-with-test-prefix"],
)
def test_skips_uncollected_module_names(path: Path) -> None:
    source = "import random\ndef test_x():\n    assert [random.random() for _ in range(5)]\n"
    assert _check(source, path) == []


@pytest.mark.parametrize(
    ("path", "banner"),
    [
        (Path("tests/generated/test_selector.py"), ""),
        (TEST_PATH, "# Code generated by distribution compiler. DO NOT EDIT.\n"),
    ],
    ids=["generated-directory", "generated-banner"],
)
def test_skips_generated_tests(path: Path, banner: str) -> None:
    source = f"{banner}import random\ndef test_distribution():\n    assert [random.random() for _ in range(5)]\n"
    assert _check(source, path) == []
