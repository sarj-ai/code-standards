from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting import embedded_shell
from sarj_standards.libs.linting.devops_programs import execution_blocks
from sarj_standards.libs.linting.embedded_shell import analyze_sources


if TYPE_CHECKING:
    from pathlib import Path


_SEPARATORS = ("\v", "\f", "\r", "\x85", "\u2028", "\u2029")


@pytest.mark.parametrize("separator", _SEPARATORS)
@pytest.mark.parametrize("instruction", ["RUN", "ONBUILD RUN", "ENTRYPOINT", "CMD", "HEALTHCHECK CMD"])
def test_docker_instruction_preserves_literal_separator_data(separator: str, instruction: str) -> None:
    command = f"printf '%s' 'before{separator}after'; printf '%s' end"
    [block] = execution_blocks("Dockerfile", f"FROM scratch\n{instruction} {command}\n")
    assert block.source == command


@pytest.mark.parametrize("separator", _SEPARATORS)
def test_docker_comment_cannot_select_an_interpreter(separator: str) -> None:
    source = f'FROM scratch\n# inert{separator}SHELL ["python3", "-c"]\nRUN printf "%s" $value\n'
    [block] = execution_blocks("Dockerfile", source)
    shell = embedded_shell.shell_block(block)
    assert shell is not None
    assert shell.dialect == "posix"


@pytest.mark.parametrize("separator", _SEPARATORS)
def test_docker_heredoc_preserves_literal_separator_data(separator: str) -> None:
    command = f"printf '%s' 'before{separator}after'"
    blocks = execution_blocks("Dockerfile", f"FROM scratch\nRUN <<'EOF'\n{command}\nEOF\nRUN printf next\n")
    assert [block.source for block in blocks] == [command, "printf next"]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_docker_lf_and_crlf_instruction_coordinates(newline: str) -> None:
    source = newline.join(("FROM scratch", "RUN printf first", "RUN printf next", ""))
    blocks = execution_blocks("Dockerfile", source)
    assert [(block.line, block.source, block.end_line) for block in blocks] == [
        (2, "printf first", 2),
        (3, "printf next", 3),
    ]


def test_docker_carriage_return_maps_instruction_and_end_to_editor_coordinates() -> None:
    source = "FROM scratch\n# comment\rdata\nRUN printf '%s' 'a\r🙂b'\nRUN printf next\n"
    first, second = execution_blocks("Dockerfile", source)
    assert (first.line, first.end_line, first.end_column) == (4, 5, 4)
    assert (second.line, second.end_line, second.end_column) == (6, 6, 16)


@pytest.mark.parametrize("separator", _SEPARATORS)
def test_docker_native_formatter_anchor_follows_real_instruction(tmp_path: Path, separator: str) -> None:
    source = f'FROM scratch\n# inert{separator}SHELL ["python3", "-c"]\nRUN printf "%s" $value;printf next\n'
    path = tmp_path / "Dockerfile"
    path.write_bytes(source.encode())
    [report] = analyze_sources(root=tmp_path, paths=[str(path)], selected=frozenset({"shfmt"}))
    [finding] = report.diagnostics
    assert finding.location.position is not None
    assert finding.location.position.byte_offset == source.encode().index(b"RUN")


def test_docker_copy_heredoc_does_not_introduce_instructions() -> None:
    source = "FROM scratch\nCOPY <<EOF /data\ntext\u2028RUN printf fake\nEOF\nRUN printf real\n"
    [block] = execution_blocks("Dockerfile", source)
    assert block.source == "printf real"
