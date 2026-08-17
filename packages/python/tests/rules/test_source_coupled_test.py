from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.source_coupled_test import SourceCoupledTest


def check(source: str, path: str = "tests/test_policy.py"):
    return SourceCoupledTest().check(Path(path), textwrap.dedent(source))


def test_flags_raw_workflow_membership():
    [diagnostic] = check("""
        def test_policy():
            source = (ROOT / "workflow.yml").read_text()
            assert "permissions:" in source
    """)
    assert diagnostic.severity is Severity.ERROR


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


@pytest.mark.parametrize("suffix", ["tsx", "jsx"])
def test_flags_raw_component_source(suffix: str):
    diagnostics = check(f"""
        def test_component_contract():
            source = Path("component.{suffix}").read_text()
            assert re.search(r"MAX_DURATION", source)
    """)
    assert len(diagnostics) == 1


def test_flags_open_of_module_file_source():
    diagnostics = check("""
        def test_removed_proxy():
            source = open(proxy_router.__file__).read()
            assert "ProxyRouter" not in source
    """)
    assert len(diagnostics) == 1


def test_flags_inspect_getfile_source_read():
    diagnostics = check("""
        def test_strategy_source():
            source = Path(inspect.getfile(TransferStrategy)).read_text()
            assert "legacy_transfer" not in source
    """)
    assert len(diagnostics) == 1


def test_allows_module_file_path_without_raw_content_assertion():
    assert (
        check("""
        def test_module_location():
            assert Path(proxy_router.__file__).exists()
    """)
        == []
    )


def test_allows_inspect_getfile_without_source_read():
    assert (
        check("""
        def test_module_location():
            assert Path(inspect.getfile(TransferStrategy)).exists()
    """)
        == []
    )


def test_reports_once_for_multiple_assertions_on_one_source():
    assert (
        len(
            check("""
        def test_policy():
            source = Path("workflow.yml").read_text()
            assert "resource" in source
            assert "prevent_destroy" in source
    """)
        )
        == 1
    )


def test_reports_each_independent_source_in_one_test():
    diagnostics = check("""
        def test_policy():
            workflow = Path("workflow.yml").read_text()
            assert "permissions" in workflow
            workflow = Path("workflow.yml").read_text()
            assert "permissions:" in workflow
    """)
    assert len(diagnostics) == 2


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


def test_flags_inline_read_and_chained_transform():
    diagnostics = check("""
        def test_policy():
            assert "permissions:" in Path("workflow.yml").read_text().lower().strip()
    """)
    assert len(diagnostics) == 1


def test_flags_path_alias():
    diagnostics = check("""
        def test_policy():
            policy = Path("workflow.yml")
            source = policy.read_text()
            assert source.find("resource") >= 0
    """)
    assert len(diagnostics) == 1


def test_flags_source_path_collection_loop():
    diagnostics = check("""
        def test_policy():
            paths = ("deploy.sh", "workflow.yml")
            for path in paths:
                source = (ROOT / path).read_text()
                assert "resource" in source
    """)
    assert len(diagnostics) == 1


def test_flags_context_managed_read():
    diagnostics = check("""
        def test_policy():
            with open("scripts/deploy.sh") as source:
                assert source.read().startswith("#!/bin/bash")
    """)
    assert len(diagnostics) == 1


def test_reassignment_kills_taint():
    assert (
        check("""
        def test_policy():
            source = Path("workflow.yml").read_text()
            source = render_runtime_value()
            assert "resource" in source
    """)
        == []
    )


def test_nested_scope_does_not_inherit_or_leak_taint():
    assert (
        check("""
        def test_policy():
            source = render_runtime_value()
            def helper():
                source = Path("workflow.yml").read_text()
                assert "resource" in source
            assert "resource" in source
    """)
        == []
    )


def test_flags_unittest_method_and_async_test():
    diagnostics = check("""
        class TestPolicy:
            def test_sync(self):
                assert "permissions" in Path("workflow.yml").read_text()

            async def test_async(self):
                source = Path("workflow.yml").read_text()
                assert source.count("permissions:") == 1
    """)
    assert len(diagnostics) == 2


def test_allows_direct_validator_execution():
    assert (
        check("""
        def test_policy():
            source = Path("workflow.yml").read_text()
            assert validate(source) == []
    """)
        == []
    )


def test_skips_non_test_and_generated_paths():
    source = "source = Path('workflow.yml').read_text()\nassert 'x' in source\n"
    assert check(source, "src/policy.py") == []
    assert check(f"# @generated\n{source}", "tests/test_generated.py") == []


def test_malformed_python_is_ignored():
    assert check("def test_x(:") == []
