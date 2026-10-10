from typing import TYPE_CHECKING

import pytest
import yaml

from sarj_standards.libs.linting import textlint


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "prefix",
    [
        "payload: |\n  # sarj-noqa: SARJ306\n",
        "payload: >\n  # sarj-noqa: SARJ306\n",
        'payload: "# sarj-noqa: SARJ306"\n',
        "# sarj-noqa: SARJ300\n",
        "",
    ],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_scalar_data_cannot_waive_real_comment(tmp_path: Path, prefix: str, newline: str) -> None:
    source = f"{prefix}# Retry count is 3\nretry_count: 3\n".replace("\n", newline)
    assert yaml.safe_load(source)["retry_count"] == 3
    path = tmp_path / "config.yaml"
    path.write_bytes(source.encode())
    findings = textlint.check_paths(
        [str(path)], root=tmp_path, rule_ids=frozenset({"exact-config-comment-restatement"})
    )
    assert len(findings) == 1


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_real_exact_code_comment_retains_waiver(tmp_path: Path, newline: str) -> None:
    source = "# sarj-noqa: SARJ306\n# Retry count is 3\nretry_count: 3\n".replace("\n", newline)
    path = tmp_path / "config.yaml"
    path.write_bytes(source.encode())
    assert (
        textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"exact-config-comment-restatement"})) == []
    )


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("", 1),
        ("payload: |\n  # sarj-noqa: SARJ300\n", 1),
        ("payload: >\n  # sarj-noqa: SARJ300\n", 1),
        ("# sarj-noqa: SARJ300\n", 0),
    ],
)
def test_comment_wall_waivers_require_real_comments(tmp_path: Path, prefix: str, expected: int) -> None:
    source = f"{prefix}# Set build name\nname: build\n# Run build command\nrun: make build\n# Set deploy image\nimage: app\n# Run deploy command\ncommand: deploy\n"
    assert yaml.safe_load(source)["name"] == "build"
    path = tmp_path / "config.yaml"
    path.write_text(source, encoding="utf-8")
    findings = textlint.check_paths([str(path)], root=tmp_path, rule_ids=frozenset({"config-comment-wall"}))
    assert len(findings) == expected
