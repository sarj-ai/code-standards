from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.iac_source_coupled_test import IacSourceCoupledTest
from sarj_python_lint.rules.source_coupled_test import SourceCoupledTest


def check(source: str, path: str = "tests/test_policy.py"):
    return IacSourceCoupledTest().check(Path(path), textwrap.dedent(source))


@pytest.mark.parametrize("suffix", ["tf", "hcl", "tfvars", "tf.json", "tftest.hcl", "tftest.json"])
def test_flags_labeled_iac_membership_cases(suffix: str) -> None:
    assert (
        len(
            check(
                f"""\n        def test_policy():\n            source = Path("policy.{suffix}").read_text()\n            assert "prevent_destroy" in source\n    """
            )
        )
        == 1
    )


def test_follows_alias_normalization_regex_and_context_manager() -> None:
    diagnostics = check("""
        def test_policy():
            path = ROOT / "main.tf"
            with open(path) as handle:
                normalized = handle.read().lower().strip()
                assert re.search("prevent_destroy", normalized)
    """)
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.ERROR


@pytest.mark.parametrize(
    "assertion",
    [
        "assert len(source) > 0",
        'assert any("resource" in line for line in source.splitlines())',
    ],
)
def test_flags_raw_text_measurement_and_line_iteration(assertion: str) -> None:
    diagnostics = check(f"""
        def test_policy():
            source = Path("main.tf").read_text()
            {assertion}
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "body",
    [
        'plan = json.loads(Path("plan.json").read_text()); assert len(plan["resource_changes"]) > 0',
        'source = Path("notes.txt").read_text(); assert any("resource" in line for line in source.splitlines())',
        'source = Path("main.tf").read_text(); assert len(parse_hcl(source)) > 0',
    ],
)
def test_allows_structured_non_iac_and_parsed_measurements(body: str) -> None:
    assert check(f"def test_policy():\n    {body}\n") == []


@pytest.mark.parametrize(
    "assertion",
    [
        'self.assertIn("prevent_destroy", source)',
        'self.assertRegex(source, r"prevent_destroy")',
        'self.assertTrue(source.startswith("resource"))',
        "self.assertGreater(len(source), 0)",
    ],
)
def test_flags_unittest_testcase_assertions(assertion: str) -> None:
    diagnostics = check(f"""
        class TestPolicy(unittest.TestCase):
            def test_policy(self):
                source = Path("main.tf").read_text()
                {assertion}
    """)
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "body",
    [
        'plan = json.loads(Path("plan.json").read_text()); self.assertEqual(verify(plan), [])',
        'source = Path("workflow.yml").read_text(); self.assertIn("permissions:", source)',
    ],
)
def test_allows_unittest_structured_and_non_iac_assertions(body: str) -> None:
    assert (
        check(f"""
        class TestPolicy(unittest.TestCase):
            def test_policy(self):
                {body}
    """)
        == []
    )


def test_does_not_infer_unittest_assertions_from_unrelated_classes() -> None:
    assert (
        check("""
        class TestPolicy(CustomAssertions):
            def test_policy(self):
                source = Path("main.tf").read_text()
                self.assertIn("resource", source)
    """)
        == []
    )


@pytest.mark.parametrize(
    "body",
    [
        "plan = json.loads(Path('plan.json').read_text()); assert verify(plan) == []",
        "assert provider_api().alerts_enabled is True",
        "assert deploy_and_probe().status_code == 200",
        "source = Path('workflow.yml').read_text(); assert 'permissions:' in source",
    ],
)
def test_allows_parsed_plan_runtime_and_non_iac_source(body: str) -> None:
    assert check(f"def test_policy():\n    {body}\n") == []


def test_generated_tmp_output_is_not_repository_source() -> None:
    assert (
        check("""
        def test_policy(tmp_path):
            source = (tmp_path / "main.tf").read_text()
            assert "resource" in source
    """)
        == []
    )


@pytest.mark.parametrize(
    "path_expression",
    ["module.__file__", "inspect.getfile(module)", "getattr(module, '__file__')"],
)
def test_python_runtime_source_path_is_not_misclassified_as_iac(path_expression: str) -> None:
    assert (
        check(f"""
        def test_removed_symbol():
            source_path = {path_expression}
            with open(source_path) as handle:
                source = handle.read()
            assert "RemovedRouter" not in source
    """)
        == []
    )


def test_iac_path_derived_from_module_directory_is_still_checked() -> None:
    diagnostics = check("""
        def test_policy():
            path = Path(module.__file__).parent / "main.tf"
            source = path.read_text()
            assert "prevent_destroy" in source
    """)

    assert len(diagnostics) == 1


def test_malformed_input_and_non_test_paths_are_ignored() -> None:
    assert check("def test_policy(:\n", "tests/test_policy.py") == []
    assert check("source = Path('main.tf').read_text(); assert 'x' in source", "tools/policy.py") == []


def test_specific_rule_owns_iac_without_duplicate_from_sarj402() -> None:
    source = textwrap.dedent("""
        def test_policy():
            source = Path("main.tf").read_text()
            assert "resource" in source
    """)
    assert len(check(source)) == 1
    assert SourceCoupledTest().check(Path("tests/test_policy.py"), source) == []
