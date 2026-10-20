from __future__ import annotations

import pytest

from sarj_iac_lint.hcl import local_exec_commands


def _resource(command: str, interpreter: str | None = None) -> str:
    declaration = f"    interpreter = {interpreter}\n" if interpreter is not None else ""
    return (
        'resource "terraform_data" "bootstrap" {\n'
        '  provisioner "local-exec" {\n'
        f"{declaration}    command = {command}\n"
        "  }\n"
        "}\n"
    )


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (r'"\U00000067cloud services enable example.googleapis.com"', "gcloud services enable example.googleapis.com"),
        ('(("kubectl apply -f deployment.yaml"))', "kubectl apply -f deployment.yaml"),
        (r'"echo \u0024{USER}"', "echo ${USER}"),
        ('"echo $${USER}"', "echo ${USER}"),
        ('"echo %%{literal}"', "echo %{literal}"),
        (r'"echo \\u0067cloud"', r"echo \u0067cloud"),
    ],
)
def test_local_exec_uses_hcl_literal_semantics(command: str, expected: str) -> None:
    [literal] = local_exec_commands(_resource(command))
    assert literal.source == expected
    assert literal.line == 3
    assert literal.physical_lines is False


@pytest.mark.parametrize(
    "interpreter",
    [
        '["/bin/bash", "-c",]',
        '(["/bin/sh", "-c"])',
        r'["/bin/\U00000062ash", "-eu", "-c"]',
        '[\n      "/bin/bash",\n      "-c",\n    ]',
    ],
)
def test_static_hcl_shell_interpreters_allow_command_analysis(interpreter: str) -> None:
    [literal] = local_exec_commands(_resource('"gcloud services enable example.googleapis.com"', interpreter))
    assert literal.source == "gcloud services enable example.googleapis.com"


@pytest.mark.parametrize(
    ("command", "interpreter"),
    [
        ('"${var.command}"', None),
        ('"%{ if var.enabled }kubectl apply -f deployment.yaml%{ endif }"', None),
        ('("gcloud services enable " + var.api)', None),
        ('"echo ready"', '[var.shell, "-c"]'),
        ('"echo ready"', '["/bin/${var.shell}", "-c"]'),
        ('"echo ready"', '["/bin/bash" "-c"]'),
        ('"echo ready"', '["/bin/bash", "--unknown", "-c"]'),
        ('"echo ready"', '["python", "-c"]'),
        (r'"\U00110000"', None),
        (r'"\uD800"', None),
    ],
)
def test_unresolved_invalid_or_non_shell_commands_abstain(command: str, interpreter: str | None) -> None:
    assert local_exec_commands(_resource(command, interpreter)) == ()
