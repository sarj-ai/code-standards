"""Direct tests for the pytest-benchmark carve-out used by SARJ057."""

import ast

from sarj_python_lint.rules._pytest import has_benchmark_marker, uses_benchmark_fixture


def _func(source: str) -> ast.FunctionDef:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def test_a_declared_and_used_fixture_is_a_benchmark() -> None:
    assert uses_benchmark_fixture(_func("def test_x(benchmark):\n    benchmark(work, 1)\n"))


def test_a_keyword_only_fixture_counts_too() -> None:
    assert uses_benchmark_fixture(_func("def test_x(*, benchmark):\n    benchmark(work)\n"))


def test_the_fixture_used_as_a_decorator_on_a_nested_function_counts() -> None:
    source = "def test_x(benchmark):\n    @benchmark\n    def run():\n        work()\n"
    assert uses_benchmark_fixture(_func(source))


def test_a_parameter_that_is_merely_named_benchmark_does_not_silence_a_rule() -> None:
    """Requiring the name to be USED is what keeps an unrelated parameter from exempting a test."""
    assert not uses_benchmark_fixture(_func("def test_x(benchmark):\n    assert compute() == 1\n"))


def test_using_the_name_without_declaring_it_is_not_the_fixture() -> None:
    assert not uses_benchmark_fixture(_func("def test_x():\n    benchmark(work)\n"))


def test_the_marker_is_the_other_half_of_the_surface() -> None:
    assert has_benchmark_marker(_func("@pytest.mark.benchmark\ndef test_x():\n    work()\n"))
    assert has_benchmark_marker(_func("@pytest.mark.benchmark(group='a')\ndef test_x():\n    work()\n"))


def test_only_a_mark_qualified_decorator_is_a_pytest_marker() -> None:
    # `@benchmark.something` is a helper, not a marker.
    assert not has_benchmark_marker(_func("@benchmark.setup\ndef test_x():\n    work()\n"))
    assert not has_benchmark_marker(_func("@helpers.benchmark\ndef test_x():\n    work()\n"))
    assert not has_benchmark_marker(_func("@pytest.mark.slow\ndef test_x():\n    work()\n"))
    assert not has_benchmark_marker(_func("@benchmark\ndef test_x():\n    work()\n"))
