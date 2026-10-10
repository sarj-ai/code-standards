import pytest

from sarj_python_lint.interpreter_argv import classify_interpreter


@pytest.mark.parametrize("mode", ["default", "always", "never"])
def test_native_hash_pyc_option_consumes_its_own_operand(mode: str) -> None:
    external = classify_interpreter(("python3", "--check-hash-based-pycs", mode, "scripts/validate.py", "-c", "data"))
    assert external.kind == "external"
    inline = classify_interpreter(("python3", "--check-hash-based-pycs", mode, "-c", "print(1)"))
    assert inline.kind == "inline"
    assert inline.payload == "print(1)"


@pytest.mark.parametrize(
    "arguments",
    [
        ("--check-hash-based-pycs=always", "scripts/validate.py"),
        ("--check-hash-based-pycs", "invalid", "scripts/validate.py"),
        ("--check-hash-based-pycs",),
    ],
    ids=("attached-invalid", "invalid-mode", "missing-mode"),
)
def test_invalid_hash_pyc_option_remains_unknown(arguments: tuple[str, ...]) -> None:
    assert classify_interpreter(("python3", *arguments)).kind == "unknown"
