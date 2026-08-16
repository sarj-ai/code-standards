from pathlib import Path
import textwrap

import pytest

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


def test_allows_single_draw_domain_assertion() -> None:
    source = """
    import random
    def test_choice_is_from_domain():
        result = random.choice(["a", "b"])
        assert result in {"a", "b"}
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


def test_skips_non_test_files_and_malformed_input() -> None:
    source = "import random\ndef test_x():\n    return [random.random() for _ in range(5)]\n"
    assert _check(source, Path("src/module.py")) == []
    assert _check("def test_broken(") == []
