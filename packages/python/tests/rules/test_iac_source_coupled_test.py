from pathlib import Path
import textwrap

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.iac_source_coupled_test import IacSourceCoupledTest
from sarj_python_lint.rules.no_raw_source_text_test_oracle import NoRawSourceTextTestOracle


def check(source: str, path: str = "tests/test_policy.py"):
    imports = "from pathlib import Path\nimport inspect\nimport io\nimport unittest\n\n"
    return IacSourceCoupledTest().check(Path(path), imports + textwrap.dedent(source))


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
    assert diagnostics[0].severity is Severity.WARNING


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


@pytest.mark.parametrize(("rule", "suffix"), [(NoRawSourceTextTestOracle, "py"), (IacSourceCoupledTest, "tf")])
@pytest.mark.parametrize(
    "assertion",
    [
        'assert (lambda source: "ready" in source)("ready")',
        'assert all("ready" in source for source in ["ready"])',
        'assert ["ready" in source for source in ["ready"]] == [True]',
        'assert all(line for source in ["ready"] for line in source.splitlines())',
        "assert all(True for line in source.splitlines())",
        'assert {source: "ready" in source for source in ["ready"]} == {"ready": True}',
        'assert ("ready" in source for _ in [1])',
        'assert all("ready" in source for _ in ())',
        'assert all("ready" in source for _ in {})',
        'assert all("ready" in source for _ in [1] if False)',
        'assert type((line for line in source.splitlines())).__name__ == "generator"',
        'from runtime import all\n    assert all("ready" in source for _ in [1]) == {"ready": True}',
        'match "ready":\n        case source:\n            assert "ready" in source',
        'match {"value": "ready"}:\n        case {"value": source}:\n            assert "ready" in source',
        'match ["ready"]:\n        case [*source]:\n            assert "ready" in source',
    ],
)
def test_source_oracle_keeps_nested_and_capture_bindings_separate(
    rule: type[NoRawSourceTextTestOracle | IacSourceCoupledTest], suffix: str, assertion: str
) -> None:
    source = (
        "from pathlib import Path\ndef test_policy():\n"
        f"    source = Path('policy.{suffix}').read_text()\n    {assertion}\n"
    )
    assert rule().check(Path("tests/test_policy.py"), source) == []


@pytest.mark.parametrize(("rule", "suffix"), [(NoRawSourceTextTestOracle, "py"), (IacSourceCoupledTest, "tf")])
@pytest.mark.parametrize(
    "assertion",
    [
        'assert all("ready" in source for _ in [1])',
        'assert any("ready" in line for line in source.splitlines())',
        "assert all(line for line in source.splitlines())",
        'assert all("ready" in line for source in source.splitlines() for line in [source])',
        'match "ready":\n        case runtime_value:\n            assert "ready" in source',
        '["ready" in source for source in ["ready"]]\n    assert "ready" in source',
    ],
)
def test_source_oracle_preserves_proven_outer_and_line_contents(
    rule: type[NoRawSourceTextTestOracle | IacSourceCoupledTest], suffix: str, assertion: str
) -> None:
    source = (
        "from pathlib import Path\ndef test_policy():\n"
        f"    source = Path('policy.{suffix}').read_text()\n    {assertion}\n"
    )
    assert len(rule().check(Path("tests/test_policy.py"), source)) == 1


@pytest.mark.parametrize(("rule", "suffix"), [(NoRawSourceTextTestOracle, "py"), (IacSourceCoupledTest, "tf")])
@pytest.mark.parametrize(
    "body",
    [
        "assert (tmp_path / 'copy').read_bytes() == Path('policy.{suffix}').read_bytes()",
        "assert Path('policy.{suffix}').read_bytes() == (tmp_path / 'copy').read_bytes()",
        "target = Path('policy.{suffix}')\n    before = original_bytes()\n    target.write_bytes(before)\n    execute_update()\n    assert target.read_bytes() == before",
    ],
)
def test_source_oracle_allows_proven_exact_byte_copy_and_preservation(
    rule: type[NoRawSourceTextTestOracle | IacSourceCoupledTest], suffix: str, body: str
) -> None:
    source = f"from pathlib import Path\ndef test_policy(tmp_path):\n    {body.format(suffix=suffix)}\n"
    assert rule().check(Path("tests/test_policy.py"), source) == []


@pytest.mark.parametrize(("rule", "suffix"), [(NoRawSourceTextTestOracle, "py"), (IacSourceCoupledTest, "tf")])
@pytest.mark.parametrize(
    "body",
    [
        "assert Path('policy.{suffix}').read_bytes() == b'fixed implementation'",
        "assert b'feature_enabled' in Path('policy.{suffix}').read_bytes()",
        "target = Path('policy.{suffix}')\n    before = original_bytes()\n    target.write_bytes(before)\n    before = replacement_bytes()\n    assert target.read_bytes() == before",
        "target = Path('policy.{suffix}')\n    before = original_bytes()\n    target.write_bytes(before)\n    target = Path('other.{suffix}')\n    assert target.read_bytes() == before",
        "target = Path('policy.{suffix}')\n    before = original_bytes()\n    target.write_bytes(before)\n    target.write_bytes(replacement_bytes())\n    assert target.read_bytes() == before",
        "target = Path('policy.{suffix}')\n    before = original_bytes()\n    unknown_target.write_bytes(before)\n    assert target.read_bytes() == before",
        "target = Path('policy.{suffix}')\n    before = original_bytes()\n    if condition:\n        target.write_bytes(before)\n    assert target.read_bytes() == before",
    ],
)
def test_source_oracle_retains_constant_and_unproven_byte_oracles(
    rule: type[NoRawSourceTextTestOracle | IacSourceCoupledTest], suffix: str, body: str
) -> None:
    source = f"from pathlib import Path\ndef test_policy(tmp_path, condition):\n    {body.format(suffix=suffix)}\n"
    assert len(rule().check(Path("tests/test_policy.py"), source)) == 1


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
    "read",
    [
        "with Path('main.tf').open() as handle:\n        source = handle.read()",
        "with io.open('main.tf') as handle:\n        source = handle.readlines()",
        "source = Path('main.tf').read_bytes().decode()",
    ],
)
def test_follows_path_open_io_open_and_decoded_bytes(read: str) -> None:
    body = textwrap.indent(read, "    ")
    diagnostics = check(f'def test_policy():\n{body}\n    assert "prevent_destroy" in source\n')
    assert len(diagnostics) == 1


def test_with_suffix_recomputes_the_source_kind() -> None:
    assert (
        check("""
        def test_notes():
            source = Path("main.tf").with_suffix(".txt").read_text()
            assert "resource" in source
        """)
        == []
    )
    assert (
        len(
            check("""
        def test_policy():
            source = Path("notes.txt").with_name("main.tf").read_text()
            assert "resource" in source
        """)
        )
        == 1
    )


@pytest.mark.parametrize("fixture", ["tmp_path_factory", "tmpdir_factory"])
def test_factory_generated_output_is_not_repository_source(fixture: str) -> None:
    assert (
        check(f"""
        def test_render({fixture}):
            output = {fixture}.mktemp("terraform") / "main.tf"
            output.write_text(render_terraform())
            source = output.read_text()
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
    assert NoRawSourceTextTestOracle().check(Path("tests/test_policy.py"), source) == []


def test_exact_sarj412_suppression_and_unrelated_code() -> None:
    assert (
        check("""
        def test_policy():
            source = Path("main.tf").read_text()
            assert "resource" in source  # sarj-noqa: SARJ412 — compatibility format
    """)
        == []
    )
    assert (
        len(
            check("""
        def test_policy():
            source = Path("main.tf").read_text()
            assert "resource" in source  # sarj-noqa: SARJ402 — separate policy
    """)
        )
        == 1
    )


@pytest.mark.parametrize("directory", ["fixtures", "golden", "snapshots"])
def test_allows_iac_representation_contract_directories(directory: str) -> None:
    assert (
        check(f"""
        def test_policy():
            source = Path("tests/{directory}/main.tf").read_text()
            assert "resource" in source
    """)
        == []
    )


@pytest.mark.parametrize("suffix", ["tf", "hcl", "tfvars", "tf.json", "tftest.hcl", "tftest.json"])
def test_module_tuple_unpack_has_only_iac_owner(suffix: str) -> None:
    source = f"""
        PATHS = (Path('first.{suffix}'), Path('second.{suffix}'))
        def test_policy():
            first, second = (path.read_text() for path in PATHS)
            assert 'prevent_destroy' in first
            assert 'prevent_destroy' in second
    """
    [diagnostic] = check(source)
    assert diagnostic.code == "SARJ412"
    assert (
        NoRawSourceTextTestOracle().check(
            Path("tests/test_policy.py"), "from pathlib import Path\n" + textwrap.dedent(source)
        )
        == []
    )


@pytest.mark.parametrize("artifact", ["Dockerfile", "bootstrap.sh.tftpl"])
def test_general_source_extensions_have_only_general_owner(artifact: str) -> None:
    source = f"""
        def test_policy():
            source = Path('{artifact}').read_text()
            assert 'install_agent' in source
    """
    assert check(source) == []
    [diagnostic] = NoRawSourceTextTestOracle().check(
        Path("tests/test_policy.py"), "from pathlib import Path\n" + textwrap.dedent(source)
    )
    assert diagnostic.code == "SARJ402"


@pytest.mark.parametrize(
    "binding",
    [
        "match runtime_paths():\n    case PATHS:\n        pass",
        "try:\n    run()\nexcept RuntimePaths as PATHS:\n    pass",
        "callback = lambda replacement=(PATHS := runtime_paths()): replacement",
    ],
)
def test_local_binding_invalidates_module_iac_tuple(binding: str) -> None:
    body = f"{binding}\nfirst, second = (path.read_text() for path in PATHS)\nassert 'prevent_destroy' in first\n"
    assert (
        check(f"PATHS = (Path('first.tf'), Path('second.tf'))\ndef test_policy():\n{textwrap.indent(body, '    ')}")
        == []
    )
