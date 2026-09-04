from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_raw_source_text_test_oracle import NoRawSourceTextTestOracle


def check(source: str, path: str = "tests/test_policy.py"):
    imports = "from pathlib import Path\nfrom pytest import mark\nimport inspect\nimport io\nimport pytest\nimport unittest\n\n"
    return NoRawSourceTextTestOracle().check(Path(path), imports + textwrap.dedent(source))


def test_flags_raw_workflow_membership():
    [diagnostic] = check("""
        def test_policy():
            source = (ROOT / "workflow.yml").read_text()
            assert "permissions:" in source
    """)
    assert diagnostic.severity is Severity.WARNING


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


def test_exact_suppression_applies_only_to_sarj402():
    assert (
        check("""
        def test_policy():
            source = Path("workflow.yml").read_text()
            assert "permissions:" in source  # sarj-noqa: SARJ402 — wire snapshot contract
    """)
        == []
    )


def test_suppressed_assertion_does_not_hide_later_unsuppressed_assertion():
    diagnostics = check("""
        def test_policy():
            source = Path("workflow.yml").read_text()
            assert "one" in source  # sarj-noqa: SARJ402 — exact sentinel
            assert "two" in source
    """)
    assert len(diagnostics) == 1
    assert (
        len(
            check("""
        def test_policy():
            source = Path("workflow.yml").read_text()
            assert "permissions:" in source  # sarj-noqa: SARJ999 — separate policy
    """)
        )
        == 1
    )


@pytest.mark.parametrize(
    "source",
    [
        """
        def helper():
            source = Path("workflow.yml").read_text()
            assert "permissions:" in source
        """,
        """
        class Helpers:
            def test_like_helper(self):
                source = Path("workflow.yml").read_text()
                assert "permissions:" in source
        """,
        """
        @pytest.fixture
        def test_data():
            source = Path("workflow.yml").read_text()
            assert "permissions:" in source
        """,
        """
        class TestDerived(BaseTests):
            def test_policy(self):
                source = Path("workflow.yml").read_text()
                assert "permissions:" in source
        """,
        """
        class TestConstructed:
            def __init__(self):
                pass
            def test_policy(self):
                source = Path("workflow.yml").read_text()
                assert "permissions:" in source
        """,
        """
        class TestDisabled:
            __test__ = False
            def test_policy(self):
                source = Path("workflow.yml").read_text()
                assert "permissions:" in source
        """,
    ],
)
def test_skips_non_collected_test_like_functions(source: str):
    assert check(source) == []


def test_flags_import_proven_unittest_testcase():
    assert (
        len(
            check("""
        class TestPolicy(unittest.TestCase):
            def test_policy(self):
                source = Path("workflow.yml").read_text()
                self.assertIn("permissions:", source)
    """)
        )
        == 1
    )


@pytest.mark.parametrize(
    "source",
    [
        """
        def test_policy():
            class Path:
                pass
            source = Path("workflow.yml").read_text()
            assert "permissions:" in source
        """,
        """
        def test_policy(Path):
            source = Path("workflow.yml").read_text()
            assert "permissions:" in source
        """,
        """
        def test_policy(open):
            source = open("workflow.yml").read()
            assert "permissions:" in source
        """,
        """
        def test_policy():
            source = archive.member("workflow.yml").read_text()
            assert "permissions:" in source
        """,
    ],
)
def test_requires_proven_source_read_apis(source: str):
    assert check(source) == []


@pytest.mark.parametrize("binding", ["pytest = custom", "mark = custom"])
def test_class_scope_mark_shadowing_abstains(binding: str):
    decorator = "pytest.mark.custom" if binding.startswith("pytest") else "mark.custom"
    assert (
        check(f"""
        class TestPolicy:
            {binding}

            @{decorator}
            def test_policy(self):
                source = Path("workflow.yml").read_text()
                assert "permissions:" in source
    """)
        == []
    )


@pytest.mark.parametrize(
    "binding",
    [
        "if FLAG:\n    pytest = custom",
        "try:\n    from custom import mark\nexcept ImportError:\n    pass",
    ],
)
def test_compound_class_scope_mark_shadowing_abstains(binding: str):
    decorator = "pytest.mark.custom" if "pytest" in binding else "mark.custom"
    indented = textwrap.indent(binding, "    ")
    assert (
        check(f"""
        class TestPolicy:
{indented}

            @{decorator}
            def test_policy(self):
                source = Path("workflow.yml").read_text()
                assert "permissions:" in source
    """)
        == []
    )


@pytest.mark.parametrize("directory", ["fixtures", "golden", "snapshots"])
def test_allows_representation_contract_directories(directory: str):
    assert (
        check(f"""
        def test_policy():
            source = Path("tests/{directory}/workflow.yml").read_text()
            assert "permissions:" in source
    """)
        == []
    )


@pytest.mark.parametrize(
    "read",
    [
        "with Path('workflow.yml').open() as handle:\n        source = handle.read()",
        "with io.open('workflow.yml') as handle:\n        source = handle.readlines()",
    ],
)
def test_flags_import_proven_open_variants(read: str):
    body = textwrap.indent(read, "    ")
    assert len(check(f'def test_policy():\n{body}\n    assert "permissions:" in source\n')) == 1


@pytest.mark.parametrize("suffix", ["json", "jsonc", "sql", "toml"])
def test_flags_source_like_configuration_suffixes(suffix: str):
    assert (
        len(
            check(f"""
        def test_policy():
            source = Path("policy.{suffix}").read_text()
            assert "required" in source
    """)
        )
        == 1
    )


@pytest.mark.parametrize("raw_first", [True, False])
def test_mixed_branch_assignment_is_not_definitely_raw(raw_first: bool):
    first = 'Path("workflow.yml").read_text()' if raw_first else "render_runtime_value()"
    second = "render_runtime_value()" if raw_first else 'Path("workflow.yml").read_text()'
    assert (
        check(f"""
        def test_policy(condition):
            if condition:
                source = {first}
            else:
                source = {second}
            assert "permissions:" in source
    """)
        == []
    )


def test_zero_iteration_loop_does_not_create_definite_raw_taint():
    assert (
        check("""
        def test_policy(items):
            source = render_runtime_value()
            for item in items:
                source = Path("workflow.yml").read_text()
            assert "permissions:" in source
    """)
        == []
    )


def test_zero_iteration_while_does_not_create_definite_raw_taint():
    assert (
        check("""
        def test_policy():
            source = render_runtime_value()
            while False:
                source = Path("workflow.yml").read_text()
            else:
                observe(source)
            assert "permissions:" in source
    """)
        == []
    )


@pytest.mark.parametrize(
    "body",
    [
        "for source in runtime_values:\n        assert 'permissions:' in source",
        "with runtime_context() as source:\n        assert 'permissions:' in source",
        "try:\n        raises()\n    except Exception as source:\n        assert 'permissions:' in source",
        "source, other = runtime_pair()\n    assert 'permissions:' in source",
    ],
)
def test_binding_targets_kill_stale_raw_taint(body: str):
    indented = textwrap.indent(body, "    ")
    assert (
        check(f"""
        def test_policy():
            source = Path("workflow.yml").read_text()
{indented}
    """)
        == []
    )


def test_try_handler_siblings_do_not_share_taint():
    assert (
        check("""
        def test_policy():
            source = render_runtime_value()
            result = render_runtime_value()
            try:
                source = Path("workflow.yml").read_text()
            except OSError:
                result = source
            assert "permissions:" in result
    """)
        == []
    )


def test_match_case_siblings_do_not_share_taint():
    assert (
        check("""
        def test_policy(kind):
            source = render_runtime_value()
            result = render_runtime_value()
            match kind:
                case "source":
                    source = Path("workflow.yml").read_text()
                case "runtime":
                    result = source
            assert "permissions:" in result
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
