from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rules.source_coupled_test import SourceCoupledTest


def check(source: str, path: str = "tests/test_policy.py"):
    return SourceCoupledTest().check(Path(path), textwrap.dedent(source))


def test_flags_raw_terraform_membership():
    assert (
        len(
            check("""
        def test_policy():
            source = (ROOT / "iac/main.tf").read_text()
            assert "prevent_destroy = true" in source
    """)
        )
        == 1
    )


def test_flags_alias_and_normalization():
    assert (
        len(
            check("""
        def test_policy():
            source = Path("workflow.yml").read_text()
            normalized = source.lower().strip()
            assert normalized.startswith("name:")
    """)
        )
        == 1
    )


def test_flags_regex_over_raw_python_source():
    assert (
        len(
            check("""
        def test_removed_route():
            source = open("app/router.py").read()
            assert re.search(r"ProxyRouter", source) is None
    """)
        )
        == 1
    )


def test_reports_once_per_test():
    assert (
        len(
            check("""
        def test_policy():
            source = Path("main.tf").read_text()
            assert "resource" in source
            assert "prevent_destroy" in source
    """)
        )
        == 1
    )


@pytest.mark.parametrize("parser", ["json.loads", "ast.parse", "yaml.safe_load"])
def test_allows_structured_parsing(parser: str):
    assert (
        check(f"""
        def test_policy():
            raw = Path("workflow.yml").read_text()
            parsed = {parser}(raw)
            assert validate(parsed) == []
    """)
        == []
    )


def test_allows_runtime_text_and_fixtures():
    assert (
        check("""
        def test_rendering():
            rendered = render_template()
            assert "hello" in rendered
    """)
        == []
    )


def test_allows_generated_output_under_tmp_path():
    assert (
        check("""
        def test_generator(tmp_path):
            generated = (tmp_path / ".github/workflows/check.yml").read_text()
            assert "permissions:" in generated
    """)
        == []
    )


def test_allows_generated_output_through_tmp_path_aliases():
    assert (
        check("""
        def test_generator(tmp_path):
            repo = tmp_path / "repo"
            workflow = repo / ".github/workflows/check.yml"
            generated = workflow.read_text()
            assert "permissions:" in generated
    """)
        == []
    )


def test_allows_direct_validator_execution():
    assert (
        check("""
        def test_policy():
            source = Path("main.tf").read_text()
            assert validate(source) == []
    """)
        == []
    )


def test_skips_non_test_and_generated_paths():
    source = "source = Path('main.tf').read_text()\nassert 'x' in source\n"
    assert check(source, "src/policy.py") == []
    assert check(f"# @generated\n{source}", "tests/test_generated.py") == []


def test_malformed_python_is_ignored():
    assert check("def test_x(:") == []
