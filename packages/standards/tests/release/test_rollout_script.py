from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import TYPE_CHECKING, final

import pytest

from sarj_standards.libs.adoption import doctor as adoption_doctor, manifest as adoption_manifest
from sarj_standards.libs.release import rollout

from .fakes import FakeRolloutRunner as FakeRunner


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def consumer() -> rollout.Consumer:
    return rollout.Consumer("Consumer", "example/consumer", "main", ("make", "check"))


def registry_entry(index: int) -> str:
    branch = "dev" if index < 2 else "main"
    auto_merge = "true" if index == 0 else "false"
    return "\n".join(
        (
            "[[consumer]]",
            f'name = "Consumer {index + 1}"',
            f'repository = "example/consumer-{index + 1}"',
            f'branch = "{branch}"',
            'verify = ["make", "check"]',
            f"auto_merge = {auto_merge}",
        )
    )


def registry_path(tmp_path: Path) -> Path:
    path = tmp_path / "registry.toml"
    entries = tuple(registry_entry(index) for index in range(5))
    path.write_text("schema = 1\n\n" + "\n\n".join(entries) + "\n", encoding="utf-8")
    return path


class TestRegistry:
    def test_registry_is_complete_and_ordered(self, tmp_path: Path) -> None:
        consumers = rollout.load_registry(registry_path(tmp_path))

        assert len(consumers) == 5
        assert consumers[-1].repository == "example/consumer-5"
        assert [item.branch for item in consumers] == ["dev", "dev", "main", "main", "main"]
        assert [item.repository for item in consumers if item.auto_merge] == ["example/consumer-1"]
        assert consumers[1].verify == ("make", "check")

    def test_registry_accepts_a_dynamic_fleet_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "registry.toml"
            path.write_text('schema = 1\n[[consumer]]\nname="one"\nrepository="r"\nbranch="main"\nverify=["true"]\n')

            assert len(rollout.load_registry(path)) == 1

    def test_registry_rejects_an_empty_fleet(self, tmp_path: Path) -> None:
        path = tmp_path / "registry.toml"
        path.write_text("schema = 1\n", encoding="utf-8")

        with pytest.raises(rollout.RolloutError, match="at least one"):
            rollout.load_registry(path)

    def test_rollout_channels_are_cumulative(self) -> None:
        consumers = (
            rollout.Consumer("canary", "r/c", "main", ("true",), channel="canary"),
            rollout.Consumer("early", "r/e", "main", ("true",), channel="early"),
            rollout.Consumer("stable", "r/s", "main", ("true",), channel="stable"),
        )

        assert [item.name for item in rollout.select_channel(consumers, "canary")] == ["canary"]
        assert [item.name for item in rollout.select_channel(consumers, "early")] == ["canary", "early"]
        assert [item.name for item in rollout.select_channel(consumers, "stable")] == ["canary", "early", "stable"]

    def test_registry_carries_explicit_promoted_baseline_rules(self, tmp_path: Path) -> None:
        path = tmp_path / "registry.toml"
        path.write_text(
            'schema=1\n[[consumer]]\nname="one"\nrepository="r"\nbranch="main"\nverify=["true"]\n'
            'baseline_rules=["eslint:@sarj/new-rule"]\n',
            encoding="utf-8",
        )

        assert rollout.load_registry(path)[0].baseline_rules == ("eslint:@sarj/new-rule",)

    def test_react_doctor_policy_change_adds_one_source_wildcard(self) -> None:
        selected = rollout.rollout_baseline_rules(
            rollout.Consumer(
                "one",
                "r/one",
                "main",
                ("true",),
                baseline_rules=("eslint:@sarj/new-rule",),
            ),
            rollout.ReactDoctorPolicy(b'{"blocking":"warning"}', "0.9.12"),
            rollout.ReactDoctorPolicy(b'{"blocking":"error"}', "0.9.12"),
        )

        assert selected == ("eslint:@sarj/new-rule", "react-doctor:*")

    def test_unchanged_react_doctor_policy_does_not_rebaseline(self) -> None:
        policy = rollout.ReactDoctorPolicy(b'{"blocking":"error"}', "0.9.12")

        assert rollout.rollout_baseline_rules(consumer(), policy, policy) == ()

    @pytest.mark.parametrize(
        ("configured", "expected"),
        [
            pytest.param(
                "sarj-iac-lint:no-terraform-test-file",
                "iac:no-mocked-terraform-test-oracle",
                id="retired-native-iac-selector",
            ),
            pytest.param(
                "sarj-iac-lint:no-terraform-test-files",
                "iac:no-terraform-test-files",
                id="native-iac-near-miss-remains-strict",
            ),
            pytest.param(
                "sarj-python-lint:no-unnecessary-docstring",
                "python:no-unnecessary-docstring",
                id="native-python-selector",
            ),
            pytest.param(
                "sarj-sql-lint:no-create-trigger",
                "sql:no-database-triggers",
                id="native-sql-selector",
            ),
            pytest.param(
                "sarj-text-lint:hidden-markdown-heading",
                "text:hidden-markdown-heading",
                id="native-text-selector",
            ),
        ],
    )
    def test_rollout_canonicalizes_catalogued_historical_baseline_selectors(
        self, configured: str, expected: str
    ) -> None:
        selected = rollout.rollout_baseline_rules(
            rollout.Consumer(
                "one",
                "example/one",
                "main",
                ("true",),
                baseline_rules=(configured,),
            ),
            rollout.ReactDoctorPolicy(None, None),
            rollout.ReactDoctorPolicy(None, None),
        )

        assert selected == (expected,)

    def test_react_doctor_policy_snapshot_reads_managed_config_and_direct_pin(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        project = tmp_path / "frontend"
        project.mkdir()
        config = b'{"blocking":"error"}\n'
        (project / "doctor.config.json").write_bytes(config)
        (project / "package.json").write_text(
            '{"devDependencies":{"react-doctor":"0.9.12"}}\n',
            encoding="utf-8",
        )

        @final
        class Adopted:
            typescript_dest: str = "frontend"

        def load_adopted(_root: Path) -> Adopted:
            return Adopted()

        monkeypatch.setattr(adoption_manifest, "load_for_setup", load_adopted)

        assert rollout.react_doctor_policy_snapshot(tmp_path) == rollout.ReactDoctorPolicy(config, "0.9.12")

    def test_react_doctor_policy_snapshot_accepts_schema_three_before_migration(self, tmp_path: Path) -> None:
        project = tmp_path / "frontend"
        project.mkdir()
        config = b'{"blocking":"error"}\n'
        (project / "doctor.config.json").write_bytes(config)
        (project / "package.json").write_text(
            '{"devDependencies":{"react-doctor":"0.9.12"}}\n',
            encoding="utf-8",
        )
        (tmp_path / adoption_manifest.MANIFEST_NAME).write_text(
            'schema = 3\nbundle = "7.7.0"\n[dest]\ntypescript = "frontend"\n',
            encoding="utf-8",
        )

        assert rollout.react_doctor_policy_snapshot(tmp_path) == rollout.ReactDoctorPolicy(config, "0.9.12")

    def test_registry_carries_a_path_constrained_consumer_baseline_update(self, tmp_path: Path) -> None:
        path = tmp_path / "registry.toml"
        path.write_text(
            'schema=1\n[[consumer]]\nname="one"\nrepository="r"\nbranch="main"\nverify=["true"]\n'
            'baseline_paths=["python-standards-baseline.json"]\n'
            'baseline_update=["uv","run","update-baseline"]\n',
            encoding="utf-8",
        )

        consumer = rollout.load_registry(path)[0]

        assert consumer.baseline_paths == ("python-standards-baseline.json",)
        assert consumer.baseline_update == ("uv", "run", "update-baseline")

    @pytest.mark.parametrize(
        "fields",
        [
            'baseline_paths=["python-standards-baseline.json"]',
            'baseline_update=["uv","run","update-baseline"]',
            'baseline_paths=["../python-standards-baseline.json"]\nbaseline_update=["true"]',
            'baseline_paths=["generated.json"]\nbaseline_update=["true"]',
        ],
    )
    def test_registry_rejects_unpaired_or_unsafe_consumer_baselines(self, tmp_path: Path, fields: str) -> None:
        path = tmp_path / "registry.toml"
        path.write_text(
            f'schema=1\n[[consumer]]\nname="one"\nrepository="r"\nbranch="main"\nverify=["true"]\n{fields}\n',
            encoding="utf-8",
        )

        with pytest.raises(rollout.RolloutError, match="baseline"):
            rollout.load_registry(path)


def test_later_wave_is_blocked_until_prior_wave_merges(monkeypatch: pytest.MonkeyPatch) -> None:
    canary = rollout.Consumer("canary", "r/c", "main", ("true",), channel="canary")
    early = rollout.Consumer("early", "r/e", "main", ("true",), channel="early")

    def fake_verify_release(_version: str, _runner: rollout.CommandRunner) -> str:
        return "a" * 64

    def fake_status(
        _version: str,
        _consumers: Sequence[rollout.Consumer],
        _runner: rollout.CommandRunner,
    ) -> tuple[rollout.Outcome, ...]:
        return (rollout.Outcome(canary, "pr-open"),)

    monkeypatch.setattr(rollout, "verify_release", fake_verify_release)
    monkeypatch.setattr(rollout, "status", fake_status)

    outcomes = rollout.apply("9.0.0", (canary, early), FakeRunner())

    assert [item.state for item in outcomes] == ["pr-open", "blocked"]


class TestSafety:
    def test_version_rejects_shell_metacharacters(self) -> None:
        with pytest.raises(rollout.RolloutError):
            rollout.validate_version("5.8.1; touch bad")

    def test_sensitive_and_source_diffs_are_rejected(self) -> None:
        for path in (
            ".github/workflows/deploy.yml",
            "diagnostic-baseline.json",
            "config/exclusions.toml",
            "apps/web/src/index.ts",
        ):
            with pytest.raises(rollout.RolloutError):
                rollout.reject_unsafe_diff((MANIFEST, path))

    def test_expected_generated_diff_is_allowed(self) -> None:
        rollout.reject_unsafe_diff(
            (
                MANIFEST,
                ".shellcheckrc",
                "uv.lock",
                "eslint.config.mjs",
                ".github/workflows/standards.yml",
                ".github/workflows/ci.yml",
            )
        )

    def test_managed_paths_cover_generated_nested_type_configs_and_package_manager_policy(
        self,
        tmp_path: Path,
    ) -> None:
        nested_configs = (
            "apps/assistant/eslint.config.js",
            "apps/dashboard/eslint.config.js",
            "packages/shared/eslint.config.js",
        )
        for relative in nested_configs:
            config = tmp_path / relative
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("export default [];\n", encoding="utf-8")
        (tmp_path / MANIFEST).write_text(
            'schema = 4\nbundle = "7.1.0"\n\n[dest]\npython = "backend"\ntypescript = "typescript"\n',
            encoding="utf-8",
        )
        allowed = rollout.managed_rollout_paths(tmp_path, frozenset())

        assert "backend/pyright.strict.json" in allowed
        assert ".shellcheckrc" in allowed
        assert set(nested_configs) <= allowed
        assert "typescript/.yarnrc.yml" in allowed
        assert "pnpm-workspace.yaml" in allowed
        arbitrary_config = "src/eslint.config.js"
        assert arbitrary_config not in allowed
        with pytest.raises(rollout.RolloutError, match="protected paths"):
            rollout.reject_unsafe_diff((MANIFEST, arbitrary_config), allowed_paths=allowed)

    def test_managed_paths_allow_only_the_selected_root_lefthook_config(self, tmp_path: Path) -> None:
        (tmp_path / MANIFEST).write_text(
            'schema = 4\nbundle = "7.9.5"\n\n[hooks]\nmanager = "lefthook"\n',
            encoding="utf-8",
        )
        (tmp_path / "lefthook.yml").write_text("pre-commit: {}\n", encoding="utf-8")
        nested = tmp_path / "nested" / "lefthook.yml"
        nested.parent.mkdir()
        nested.write_text("pre-commit: {}\n", encoding="utf-8")

        allowed = rollout.managed_rollout_paths(tmp_path, frozenset())

        assert "lefthook.yml" in allowed
        assert "nested/lefthook.yml" not in allowed

    def test_prevalidated_pin_bearing_workflow_is_allowed(self) -> None:
        workflow = ".github/workflows/ci-internal-tools.yml"

        rollout.reject_unsafe_diff((MANIFEST, workflow), allowed_workflow_paths=frozenset({workflow}))

        with pytest.raises(rollout.RolloutError, match="protected paths"):
            rollout.reject_unsafe_diff((MANIFEST, workflow))

    def test_only_prevalidated_retired_suppression_source_is_allowed(self) -> None:
        source = "apps/web/src/index.ts"

        rollout.reject_unsafe_diff((MANIFEST, source), allowed_source_paths=frozenset({source}))

        with pytest.raises(rollout.RolloutError):
            rollout.reject_unsafe_diff((MANIFEST, source))

    def test_source_outside_conventional_directories_is_protected(self) -> None:
        with pytest.raises(rollout.RolloutError, match="protected paths"):
            rollout.reject_unsafe_diff((MANIFEST, "scripts/release.ts"))

    def test_only_manifest_declared_baseline_is_allowed(self) -> None:
        rollout.reject_unsafe_diff(
            (MANIFEST, "quality/diagnostic-baseline.json"),
            allowed_baseline_paths=frozenset({"quality/diagnostic-baseline.json"}),
        )

    def test_unlisted_nonsource_file_is_rejected(self) -> None:
        for path in ("scripts/release.sh", "scripts/.shellcheckrc", "backend/.shellcheckrc"):
            with pytest.raises(rollout.RolloutError, match="protected paths"):
                rollout.reject_unsafe_diff((MANIFEST, path))

    def test_consumer_verification_cannot_mutate_controller_baseline(self, tmp_path: Path) -> None:
        path = tmp_path / "diagnostic-baseline.json"
        path.write_bytes(b"expected\n")
        path.write_bytes(b"expanded\n")

        with pytest.raises(rollout.RolloutError, match="controller-owned"):
            rollout.assert_baseline_unchanged(path, b"expected\n")

    def test_status_parser_includes_untracked_files(self) -> None:
        runner = FakeRunner([(0, " M .sarj-standards.toml\0?? generated.toml\0")])

        assert rollout.changed_paths(Path("repo"), runner) == (MANIFEST, "generated.toml")
        assert "-z" in runner.commands[0]

    def test_status_parser_rejects_deletes(self) -> None:
        runner = FakeRunner([(0, " D protected.toml\0")])

        with pytest.raises(rollout.RolloutError, match="delete or rename"):
            rollout.changed_paths(Path("repo"), runner)

    def test_status_parser_allows_the_prevalidated_retired_launcher_deletion(self) -> None:
        runner = FakeRunner([(0, " D .sarj/standards\0")])

        assert rollout.changed_paths(Path("repo"), runner) == (".sarj/standards",)

    def test_committed_paths_include_the_prevalidated_retired_launcher_deletion(self) -> None:
        runner = FakeRunner([(0, ""), (0, ".sarj/standards\n"), (0, ".sarj/standards\0")])

        assert rollout.committed_paths(Path("repo"), "main", runner) == (".sarj/standards",)
        assert "--diff-filter=ACMD" in runner.commands[-1]

    def test_committed_paths_reject_other_deletions(self) -> None:
        runner = FakeRunner([(0, ""), (0, "protected.toml\n")])

        with pytest.raises(rollout.RolloutError, match="delete or rename"):
            rollout.committed_paths(Path("repo"), "main", runner)

    def test_consumer_environment_scrubs_github_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GH_TOKEN", "secret")
        monkeypatch.setenv("GITHUB_TOKEN", "secret")
        monkeypatch.setenv("VIRTUAL_ENV", "/standards/.venv")
        monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/standards/.venv")
        monkeypatch.setenv("PATH", f"/standards/.venv/bin{os.pathsep}/bin")

        environment = rollout.unauthenticated_environment()

        assert "GH_TOKEN" not in environment
        assert "GITHUB_TOKEN" not in environment
        assert "VIRTUAL_ENV" not in environment
        assert "UV_PROJECT_ENVIRONMENT" not in environment
        assert environment["PATH"] == "/bin"

    def test_repository_owned_make_pin_is_updated_exactly(self, tmp_path: Path) -> None:
        makefile = tmp_path / "Makefile"
        makefile.write_text("STANDARDS_VERSION := 5.7.1\ncheck:\n\t@true\n", encoding="utf-8")

        changed = rollout.synchronize_repository_pin(tmp_path, "5.8.1")

        assert changed
        assert makefile.read_text(encoding="utf-8") == "STANDARDS_VERSION := 5.8.1\ncheck:\n\t@true\n"

    def test_declared_basedpyright_replaces_plain_pyright_wrapper(self, tmp_path: Path) -> None:
        makefile = tmp_path / "Makefile"
        project = tmp_path / "python/pyproject.toml"
        project.parent.mkdir()
        makefile.write_text("check:\n\tcd python && uv run pyright\n", encoding="utf-8")
        project.write_text('dependencies = ["basedpyright==1.39.9"]\n', encoding="utf-8")

        changed = rollout.synchronize_repository_checker(tmp_path)

        assert changed
        assert makefile.read_text(encoding="utf-8") == "check:\n\tcd python && uv run basedpyright\n"

    def test_retired_suppression_migration_removes_only_exact_selector(self, tmp_path: Path) -> None:
        source = tmp_path / "apps/web/src/index.ts"
        source.parent.mkdir(parents=True)
        source.write_text(
            f"/* eslint-disable no-console, {rollout.RETIRED_ESLINT_SELECTORS[1]}, eqeqeq -- legacy */\nconst x = 1;\n",
            encoding="utf-8",
        )
        runner = FakeRunner([(0, "apps/web/src/index.ts\0")])

        changed = rollout.remove_retired_eslint_suppressions(tmp_path, runner)

        assert changed == frozenset({"apps/web/src/index.ts"})
        assert source.read_text(encoding="utf-8") == (
            "/* eslint-disable no-console, eqeqeq -- legacy */\nconst x = 1;\n"
        )


MANIFEST = ".sarj-standards.toml"


def managed_open_pr_payload(
    version: str,
    cached_base_sha: str,
    head_sha: str,
    *,
    url: str = "https://pr/1",
) -> str:
    return json.dumps(
        [
            {
                "state": "OPEN",
                "mergedAt": None,
                "url": url,
                "headRefName": "standards-rollout/current",
                "baseRefName": "main",
                "headRefOid": head_sha,
                "baseRefOid": cached_base_sha,
                "body": rollout.pr_marker(consumer(), version) + "\n" + rollout.desired_marker(version),
            }
        ]
    )


def live_base_ref_payload(base_sha: str) -> str:
    return json.dumps({"ref": "refs/heads/main", "object": {"type": "commit", "sha": base_sha}})


class TestStatus:
    def test_open_pr_is_idempotently_reported(self) -> None:
        base_sha = "a" * 40
        head_sha = "b" * 40
        payload = managed_open_pr_payload("5.8.1", base_sha, head_sha)
        commit = json.dumps({"parents": [{"sha": base_sha}]})
        runner = FakeRunner([(0, payload), (0, commit), (0, live_base_ref_payload(base_sha))])

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "pr-open"
        assert result.url == "https://pr/1"
        assert "--head" in runner.commands[0]
        assert runner.commands[-1] == ("gh", "api", "repos/example/consumer/git/ref/heads%2Fmain")

    def test_open_pr_with_stale_commit_parent_is_refreshed(self) -> None:
        old_base = "9e5cc29955cb89c2dcafca1f0180be1f04b58a7b"
        current_base = "84ad9cac3432c8fba4451138dbf9d69387ff16af"
        head_sha = "a55e7f1ba137a7b068fcec112ed675189fa13a06"
        cached_base = "8" * 40
        payload = managed_open_pr_payload(
            "7.1.14",
            cached_base,
            head_sha,
            url="https://github.com/example/consumer/pull/506",
        )
        commit = json.dumps({"parents": [{"sha": old_base}]})
        runner = FakeRunner([(0, payload), (0, commit), (0, live_base_ref_payload(current_base))])

        result = rollout.status_one(consumer(), "7.1.14", runner)

        assert result.state == "missing"
        assert old_base in result.detail
        assert current_base in result.detail
        assert "reconcile will refresh" in result.detail

    def test_open_pr_ignores_stale_cached_base_when_parent_matches_live_base(self) -> None:
        cached_base = "8" * 40
        current_base = "a" * 40
        head_sha = "b" * 40
        payload = managed_open_pr_payload("5.8.1", cached_base, head_sha)
        commit = json.dumps({"parents": [{"sha": current_base}]})
        runner = FakeRunner([(0, payload), (0, commit), (0, live_base_ref_payload(current_base))])

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "pr-open"

    def test_open_pr_does_not_accept_parent_matching_only_cached_base(self) -> None:
        cached_base = "8" * 40
        current_base = "a" * 40
        head_sha = "b" * 40
        payload = managed_open_pr_payload("5.8.1", cached_base, head_sha)
        commit = json.dumps({"parents": [{"sha": cached_base}]})
        runner = FakeRunner([(0, payload), (0, commit), (0, live_base_ref_payload(current_base))])

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "missing"
        assert cached_base in result.detail
        assert current_base in result.detail

    @pytest.mark.parametrize(
        ("returncode", "response", "expected_detail"),
        [
            (1, "not found", "managed rollout current consumer base ref could not be read"),
            (0, "not-json", "managed rollout current consumer base ref is malformed"),
        ],
        ids=("unreadable-live-base-ref", "malformed-live-base-ref"),
    )
    def test_open_pr_with_unusable_live_base_ref_is_blocked(
        self,
        returncode: int,
        response: str,
        expected_detail: str,
    ) -> None:
        payload = managed_open_pr_payload("5.8.1", "a" * 40, "b" * 40)
        commit = json.dumps({"parents": [{"sha": "a" * 40}]})
        runner = FakeRunner([(0, payload), (0, commit), (returncode, response)])

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "blocked"
        assert result.detail == expected_detail

    def test_open_pr_with_invalid_live_base_sha_is_blocked(self) -> None:
        payload = managed_open_pr_payload("5.8.1", "a" * 40, "b" * 40)
        commit = json.dumps({"parents": [{"sha": "a" * 40}]})
        runner = FakeRunner([(0, payload), (0, commit), (0, live_base_ref_payload("short"))])

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "blocked"
        assert result.detail == "managed rollout current consumer base ref has no valid commit SHA"

    def test_open_pr_with_non_commit_live_base_target_is_blocked(self) -> None:
        payload = managed_open_pr_payload("5.8.1", "a" * 40, "b" * 40)
        target = json.dumps({"ref": "refs/heads/main", "object": {"type": "tag", "sha": "a" * 40}})
        commit = json.dumps({"parents": [{"sha": "a" * 40}]})
        runner = FakeRunner([(0, payload), (0, commit), (0, target)])

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "blocked"
        assert result.detail == "managed rollout current consumer base ref has no valid commit SHA"

    def test_open_pr_with_merge_commit_is_blocked(self) -> None:
        base_sha = "a" * 40
        head_sha = "b" * 40
        payload = managed_open_pr_payload("5.8.1", base_sha, head_sha)
        runner = FakeRunner(
            [
                (0, payload),
                (0, json.dumps({"parents": [{"sha": base_sha}, {"sha": "c" * 40}]})),
            ]
        )

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "blocked"
        assert "exactly one commit with one parent" in result.detail

    def test_open_pr_with_malformed_commit_response_is_blocked(self) -> None:
        base_sha = "a" * 40
        head_sha = "b" * 40
        runner = FakeRunner(
            [
                (0, managed_open_pr_payload("5.8.1", base_sha, head_sha)),
                (0, "not-json"),
            ]
        )

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "blocked"
        assert result.detail == "managed rollout commit provenance is malformed"

    def test_merged_pr_is_reported(self) -> None:
        marker = rollout.pr_marker(consumer(), "5.8.1")
        payload = json.dumps(
            [
                {
                    "state": "MERGED",
                    "mergedAt": "now",
                    "url": "https://pr/1",
                    "headRefName": "standards-rollout/current",
                    "baseRefName": "main",
                    "body": marker + "\n" + rollout.desired_marker("5.8.1"),
                }
            ]
        )
        runner = FakeRunner([(0, payload)])

        assert rollout.status_one(consumer(), "5.8.1", runner).state == "merged"

    def test_open_rolling_pr_is_superseded_when_desired_release_changes(self) -> None:
        payload = json.dumps(
            [
                {
                    "state": "OPEN",
                    "mergedAt": None,
                    "url": "https://pr/1",
                    "headRefName": "standards-rollout/current",
                    "baseRefName": "main",
                    "body": rollout.pr_marker(consumer(), "5.8.0") + "\n" + rollout.desired_marker("5.8.0"),
                }
            ]
        )

        result = rollout.status_one(consumer(), "5.8.1", FakeRunner([(0, payload)]))

        assert result.state == "missing"
        assert result.url == "https://pr/1"
        assert "older" in result.detail

    def test_closed_historical_pr_does_not_block_a_new_rollout(self) -> None:
        runner = FakeRunner([(0, "[]"), (1, "")])

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "missing"
        assert runner.commands[0][5:7] == ("--state", "open")

    def test_foreign_pr_cannot_satisfy_rollout(self) -> None:
        payload = json.dumps(
            [
                {
                    "state": "OPEN",
                    "mergedAt": None,
                    "url": "https://pr/1",
                    "headRefName": "standards-rollout/v5.8.1",
                    "baseRefName": "wrong-base",
                    "body": "human-authored",
                }
            ]
        )
        runner = FakeRunner([(0, payload)])

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "blocked"
        assert "ownership marker" in result.detail

    def test_base_manifest_can_prove_already_current(self) -> None:
        encoded = base64.b64encode(b'bundle = "5.8.1"\n').decode()
        runner = FakeRunner([(0, "[]"), (0, json.dumps({"content": encoded}))])

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "already-current"
        assert "--method" in runner.commands[1]

    def test_stale_manifest_is_missing(self) -> None:
        encoded = base64.b64encode(b'bundle = "5.7.0"\n').decode()
        runner = FakeRunner([(0, "[]"), (0, json.dumps({"content": encoded}))])

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "missing"
        assert "5.7.0" in result.detail


class TestRelease:  # ruff: ignore[too-many-public-methods] -- rollout state-machine cases share one fake runner
    def test_latest_version_refreshes_the_registry_backed_tool(self) -> None:
        runner = FakeRunner([(0, "code-standards 6.0.5")])

        assert rollout.latest_version(runner) == "6.0.5"
        assert runner.commands == [
            (
                "uvx",
                "--isolated",
                "--python",
                "3.14",
                "--refresh-package",
                "code-standards",
                "--from",
                "code-standards",
                "code-standards",
                "--version",
            )
        ]

    def test_release_verification_binds_package_and_tag_sha(self) -> None:
        sha = "a" * 40
        runner = FakeRunner(
            [
                (0, "code-standards 5.8.1"),
                (
                    0,
                    f"{'c' * 40}\trefs/tags/standards-v5.8.1\n{sha}\trefs/tags/standards-v5.8.1^{{}}\n",
                ),
            ]
        )

        assert rollout.verify_release("5.8.1", runner) == sha
        assert "code-standards==5.8.1" in runner.commands[0]
        assert "--refresh-package" in runner.commands[0]
        assert "refs/tags/standards-v5.8.1^{}" in runner.commands[1]

    def test_release_verification_waits_for_pypi_edge_visibility(self) -> None:
        sha = "a" * 40
        sleeps: list[float] = []
        runner = FakeRunner(
            [
                (1, ""),
                (0, "code-standards 5.8.1"),
                (
                    0,
                    f"{'c' * 40}\trefs/tags/standards-v5.8.1\n{sha}\trefs/tags/standards-v5.8.1^{{}}\n",
                ),
            ]
        )

        assert rollout.verify_release("5.8.1", runner, sleep=sleeps.append) == sha
        assert sleeps == [rollout.RELEASE_VISIBILITY_DELAY.total_seconds()]
        assert runner.commands[0] == runner.commands[1]

    def test_release_rejects_version_substring(self) -> None:
        runner = FakeRunner([(0, "code-standards 15.8.10")])

        with pytest.raises(rollout.RolloutError, match="did not report"):
            rollout.verify_release("5.8.1", runner, sleep=lambda _: None)

    def test_dry_run_does_not_clone_or_push(self, tmp_path: Path) -> None:
        sha = "b" * 40
        registry = rollout.load_registry(registry_path(tmp_path))
        responses: list[tuple[int, str]] = [
            (0, "code-standards 5.8.1"),
            (
                0,
                f"{'c' * 40}\trefs/tags/standards-v5.8.1\n{sha}\trefs/tags/standards-v5.8.1^{{}}\n",
            ),
        ]
        for _ in registry:
            responses.extend(((0, "[]"), (1, "")))
        runner = FakeRunner(responses)

        outcomes = rollout.apply("5.8.1", registry, runner, dry_run=True)

        assert all(item.state == "would-create" for item in outcomes)
        assert not any(command[:3] == ("gh", "repo", "clone") for command in runner.commands)

    def test_full_clone_keeps_verification_refs_available(self) -> None:
        runner = FakeRunner([(0, "[]"), (1, "")])

        with pytest.raises(rollout.RolloutError):
            rollout.apply_one(consumer(), "5.8.1", runner)

        clone = next(command for command in runner.commands if command[:3] == ("gh", "repo", "clone"))
        assert "--single-branch" not in clone

    def test_dependency_install_failure_never_falls_back_to_a_lockless_patch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        base_sha = "b" * 40

        class FixedTemporaryDirectory:
            def __enter__(self) -> str:
                return str(tmp_path)

            def __exit__(self, *_args: object) -> None:
                return None

        def missing_status(*_args: object) -> rollout.Outcome:
            return rollout.Outcome(consumer(), "missing")

        def fresh_branch(*_args: object) -> rollout.BranchPreparation:
            return rollout.BranchPreparation("standards-rollout/current", None)

        def fixed_temporary_directory(**kwargs: object) -> FixedTemporaryDirectory:
            assert kwargs == {"prefix": "standards-rollout-", "ignore_cleanup_errors": True}
            return FixedTemporaryDirectory()

        def provisioned_tools(*_args: object) -> rollout.ProvisionedTools:
            return rollout.ProvisionedTools({"PATH": "/tools"}, ())

        monkeypatch.setattr(rollout, "status_one", missing_status)
        monkeypatch.setattr(rollout, "prepare_branch", fresh_branch)
        monkeypatch.setattr(tempfile, "TemporaryDirectory", fixed_temporary_directory)
        monkeypatch.setattr(rollout, "provision_consumer_tools", provisioned_tools)
        runner = FakeRunner([(0, ""), (0, base_sha), (7, "quarantined package")])

        with pytest.raises(rollout.RolloutError, match="before a coherent rollout patch"):
            rollout.apply_one(consumer(), "6.1.3", runner)

        update_commands = [command for command in runner.commands if "update" in command]
        assert len(update_commands) == 1
        assert "--no-install" not in update_commands[0]

    @pytest.mark.parametrize(
        (
            "returncodes",
            "dirty_runs",
            "target_moves",
            "head_refreshes",
            "auto_merge",
            "expected_state",
            "expected_verification_runs",
        ),
        [
            ((1, 0), frozenset({1}), False, True, False, "pr-open", 2),
            ((1,), frozenset[int](), False, True, False, "blocked", 1),
            ((0, 0), frozenset({1}), False, True, False, "pr-open", 2),
            ((0, 0), frozenset({1, 2}), False, True, False, "blocked", 2),
            ((0,), frozenset[int](), True, True, True, "missing", 1),
            ((0,), frozenset[int](), False, False, True, "missing", 1),
            ((0,), frozenset[int](), False, True, True, "pr-open", 1),
        ],
    )
    def test_verification_autofix_amends_a_clean_candidate_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        *,
        returncodes: tuple[int, ...],
        dirty_runs: frozenset[int],
        target_moves: bool,
        head_refreshes: bool,
        auto_merge: bool,
        expected_state: str,
        expected_verification_runs: int,
    ) -> None:
        selected_consumer = rollout.Consumer(
            "Consumer",
            "example/consumer",
            "main",
            ("make", "check"),
            auto_merge=auto_merge,
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        manifest = repo / MANIFEST
        eslint = repo / "eslint.config.mjs"
        manifest.write_text('schema = 3\nbundle = "5.8.0"\n', encoding="utf-8")
        eslint.write_text("export default [];\n", encoding="utf-8")
        subprocess.run(("git", "init", "-b", "main"), cwd=repo, check=True, capture_output=True)
        subprocess.run(("git", "config", "user.name", "Standards Test"), cwd=repo, check=True)
        subprocess.run(("git", "config", "user.email", "standards@example.com"), cwd=repo, check=True)
        subprocess.run(("git", "add", "."), cwd=repo, check=True)
        subprocess.run(("git", "commit", "-m", "base"), cwd=repo, check=True, capture_output=True)
        base_sha = subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()
        subprocess.run(("git", "update-ref", "refs/remotes/origin/main", base_sha), cwd=repo, check=True)

        class FixedTemporaryDirectory:
            def __enter__(self) -> str:
                return str(tmp_path)

            def __exit__(self, *_args: object) -> None:
                return None

        @final
        class AutofixingRunner:
            def __init__(self) -> None:
                self.verification_runs = 0
                self.commands: list[tuple[str, ...]] = []

            def run(
                self,
                command: Sequence[str],
                *,
                cwd: Path | None = None,
                check: bool = True,
                env: Mapping[str, str] | None = None,
            ) -> subprocess.CompletedProcess[str]:
                rendered = tuple(command)
                self.commands.append(rendered)
                if rendered[:3] == ("gh", "repo", "clone") or rendered[:2] == ("git", "push"):
                    return subprocess.CompletedProcess(rendered, 0, "", "")
                if rendered == ("git", "fetch", "origin", "main"):
                    return subprocess.CompletedProcess(rendered, 0, "", "")
                if rendered == ("git", "rev-parse", "FETCH_HEAD"):
                    return subprocess.CompletedProcess(rendered, 0, base_sha + "\n", "")
                if rendered[:3] == ("gh", "pr", "create"):
                    return subprocess.CompletedProcess(rendered, 0, "https://example.test/pr/1\n", "")
                if rendered[:3] == ("gh", "pr", "merge"):
                    return subprocess.CompletedProcess(rendered, 0, "", "")
                if rendered[:2] == ("gh", "api") and rendered[2].startswith("repos/example/consumer/commits/"):
                    return subprocess.CompletedProcess(
                        rendered,
                        0,
                        json.dumps({"parents": [{"sha": base_sha}]}),
                        "",
                    )
                if rendered == ("gh", "api", "repos/example/consumer/git/ref/heads%2Fmain"):
                    live_sha = "c" * 40 if target_moves else base_sha
                    return subprocess.CompletedProcess(rendered, 0, live_base_ref_payload(live_sha), "")
                if "update" in rendered:
                    manifest.write_text('schema = 4\nbundle = "5.8.1"\n', encoding="utf-8")
                    return subprocess.CompletedProcess(rendered, 0, "", "")
                if rendered[-1:] == ("doctor",):
                    return subprocess.CompletedProcess(rendered, 0, "", "")
                if rendered == selected_consumer.verify:
                    self.verification_runs += 1
                    dirty = subprocess.run(
                        ("git", "status", "--porcelain"),
                        cwd=repo,
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout
                    assert not dirty, "verification hooks must run against a clean candidate commit"
                    if self.verification_runs in dirty_runs:
                        eslint.write_text(f'export default ["generated-{self.verification_runs}"];\n', encoding="utf-8")
                    returncode = returncodes[self.verification_runs - 1]
                    return subprocess.CompletedProcess(rendered, returncode, "verification result", "")
                return subprocess.run(
                    rendered,
                    cwd=cwd,
                    check=check,
                    env=env,
                    capture_output=True,
                    text=True,
                )

        runner = AutofixingRunner()

        def missing_status(
            _consumer: rollout.Consumer,
            _version: str,
            _runner: rollout.CommandRunner,
        ) -> rollout.Outcome:
            return rollout.Outcome(selected_consumer, "missing")

        def fresh_branch(
            _repo: Path,
            _version: str,
            _base_sha: str,
            _runner: rollout.CommandRunner,
        ) -> rollout.BranchPreparation:
            return rollout.BranchPreparation("standards-rollout/current", None)

        def fixed_temporary_directory(**_kwargs: object) -> FixedTemporaryDirectory:
            return FixedTemporaryDirectory()

        def no_version_pin_updates(_root: Path) -> tuple[()]:
            return ()

        def no_bootstrap(
            _repo: Path,
            _tool_prefix: tuple[str, ...],
            _runner: rollout.CommandRunner,
            _environment: Mapping[str, str],
        ) -> subprocess.CompletedProcess[str] | None:
            return None

        pull_request_calls = 0

        def managed_pull_request(
            _consumer: rollout.Consumer,
            _version: str,
            _runner: rollout.CommandRunner,
        ) -> dict[str, object] | None:
            nonlocal pull_request_calls
            pull_request_calls += 1
            if pull_request_calls == 1:
                return None
            head_sha = subprocess.run(
                ("git", "rev-parse", "HEAD"),
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if not head_refreshes:
                head_sha = "d" * 40
            return {
                "state": "OPEN",
                "mergedAt": None,
                "url": "https://example.test/pr/1",
                "headRefName": "standards-rollout/current",
                "baseRefName": "main",
                "headRefOid": head_sha,
                "body": rollout.pr_marker(selected_consumer, "5.8.1"),
            }

        monkeypatch.setattr(rollout, "status_one", missing_status)
        monkeypatch.setattr(rollout, "prepare_branch", fresh_branch)
        monkeypatch.setattr(tempfile, "TemporaryDirectory", fixed_temporary_directory)
        monkeypatch.setattr(adoption_doctor, "plan_version_pin_updates", no_version_pin_updates)
        monkeypatch.setattr(rollout, "run_consumer_bootstrap", no_bootstrap)
        monkeypatch.setattr(rollout, "pull_request", managed_pull_request)

        result = rollout.apply_one(selected_consumer, "5.8.1", runner)

        assert result.state == expected_state
        assert runner.verification_runs == expected_verification_runs
        assert not subprocess.run(
            ("git", "status", "--porcelain"), cwd=repo, check=True, capture_output=True, text=True
        ).stdout
        assert (
            subprocess.run(
                ("git", "rev-list", "--count", base_sha + "..HEAD"),
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            == "1"
        )
        expected_eslint = f'export default ["generated-{max(dirty_runs)}"];\n' if dirty_runs else "export default [];\n"
        assert eslint.read_text(encoding="utf-8") == expected_eslint
        pull_request_command = next(command for command in runner.commands if command[:3] == ("gh", "pr", "create"))
        pull_request_body = pull_request_command[pull_request_command.index("--body") + 1]
        if dirty_runs == frozenset({1, 2}):
            assert "did not converge" in pull_request_body
        if target_moves:
            assert base_sha in result.detail
            assert "c" * 40 in result.detail
            assert runner.commands[-1] == ("gh", "api", "repos/example/consumer/git/ref/heads%2Fmain")
            assert not any(command[:3] == ("gh", "pr", "merge") for command in runner.commands)
        if not head_refreshes:
            assert "has not refreshed to the pushed commit" in result.detail
            assert not any(command[:3] == ("gh", "pr", "merge") for command in runner.commands)
        if auto_merge and expected_state == "pr-open":
            merge_command = next(command for command in runner.commands if command[:3] == ("gh", "pr", "merge"))
            validated_sha = subprocess.run(
                ("git", "rev-parse", "HEAD"),
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert merge_command[merge_command.index("--match-head-commit") + 1] == validated_sha

    def test_pre_push_base_recheck_accepts_the_captured_base(self, tmp_path: Path) -> None:
        base_sha = "a" * 40
        runner = FakeRunner([(0, ""), (0, base_sha)])

        rollout.assert_consumer_base_unchanged(tmp_path, consumer(), base_sha, runner)

        assert runner.commands == [
            ("git", "fetch", "origin", "main"),
            ("git", "rev-parse", "FETCH_HEAD"),
        ]

    def test_pre_push_base_recheck_rejects_target_movement(self, tmp_path: Path) -> None:
        old_base = "a" * 40
        live_base = "b" * 40
        runner = FakeRunner([(0, ""), (0, live_base)])

        with pytest.raises(rollout.RolloutError, match="consumer base moved") as caught:
            rollout.assert_consumer_base_unchanged(tmp_path, consumer(), old_base, runner)

        assert old_base in str(caught.value)
        assert live_base in str(caught.value)
        assert "reconcile will retry" in str(caught.value)

    def test_pre_push_base_recheck_rejects_a_malformed_ref(self, tmp_path: Path) -> None:
        runner = FakeRunner([(0, ""), (0, "short")])

        with pytest.raises(rollout.RolloutError, match="did not resolve to a full commit SHA"):
            rollout.assert_consumer_base_unchanged(tmp_path, consumer(), "a" * 40, runner)

    def test_reuses_a_merged_managed_branch_without_amending_the_base(self, tmp_path: Path) -> None:
        old_sha = "a" * 40
        base_sha = "b" * 40
        parent_sha = "c" * 40
        runner = FakeRunner(
            [
                (0, f"{old_sha}\trefs/heads/standards-rollout/current"),
                (0, ""),
                (0, f"{rollout.BOT_COMMIT_PREFIX}5.8.0\n\n{rollout.MANAGED_TRAILER}"),
                (0, f"{old_sha} {parent_sha}"),
                (0, ""),
                (0, ""),
            ]
        )

        prepared = rollout.prepare_branch(tmp_path, "5.8.1", base_sha, runner)

        assert prepared.previous_sha == old_sha
        assert runner.commands[-1] == ("git", "switch", "-C", "standards-rollout/current", base_sha)

    def test_base_advancement_discards_previous_bot_patch_and_rebuilds_from_captured_base(self, tmp_path: Path) -> None:
        old_sha = "a" * 40
        base_sha = "b" * 40
        old_base_sha = "c" * 40
        runner = FakeRunner(
            [
                (0, f"{old_sha}\trefs/heads/standards-rollout/current"),
                (0, ""),
                (0, f"{rollout.BOT_COMMIT_PREFIX}5.8.0\n\n{rollout.MANAGED_TRAILER}"),
                (0, f"{old_sha} {old_base_sha}"),
                (0, ""),
                (0, ""),
            ]
        )

        prepared = rollout.prepare_branch(tmp_path, "5.8.1", base_sha, runner)

        assert prepared.previous_sha == old_sha
        assert runner.commands[-1] == ("git", "switch", "-C", "standards-rollout/current", base_sha)
        assert ("git", "merge-base", "--is-ancestor", old_base_sha, base_sha) in runner.commands
        assert not any(command[:2] == ("git", "rebase") for command in runner.commands)
        assert rollout.force_with_lease(prepared.branch, prepared.previous_sha) == (
            f"--force-with-lease=refs/heads/standards-rollout/current:{old_sha}"
        )

    def test_refuses_extra_commits_on_a_managed_rollout_branch(self, tmp_path: Path) -> None:
        old_sha = "a" * 40
        base_sha = "b" * 40
        stacked_parent_sha = "d" * 40
        runner = FakeRunner(
            [
                (0, f"{old_sha}\trefs/heads/standards-rollout/current"),
                (0, ""),
                (0, f"{rollout.BOT_COMMIT_PREFIX}5.8.0\n\n{rollout.MANAGED_TRAILER}"),
                (0, f"{old_sha} {stacked_parent_sha}"),
                (1, ""),
            ]
        )

        with pytest.raises(rollout.RolloutError, match="human-modified"):
            rollout.prepare_branch(tmp_path, "5.8.1", base_sha, runner)

    def test_provisions_mise_and_isolated_corepack_shims(self, tmp_path: Path) -> None:
        (tmp_path / ".mise.toml").write_text('[tools]\nnode = "24"\n', encoding="utf-8")
        (tmp_path / "package.json").write_text('{"packageManager":"pnpm@10.0.0"}\n', encoding="utf-8")
        shim_directory = tmp_path / "outside" / "bin"
        runner = FakeRunner([(0, "mise installed"), (0, "corepack enabled")])

        environment, prefix = rollout.provision_consumer_tools(tmp_path, shim_directory, runner, {"PATH": "/usr/bin"})

        assert prefix == ("mise", "exec", "--")
        assert runner.commands == [
            ("mise", "install"),
            ("mise", "exec", "--", "corepack", "enable", "--install-directory", str(shim_directory)),
        ]
        assert environment["PATH"].split(":", maxsplit=1) == [str(shim_directory), "/usr/bin"]
        assert environment["MISE_YES"] == "1"
        assert environment["MISE_TRUSTED_CONFIG_PATHS"] == str(tmp_path.resolve())

    def test_corepack_shims_do_not_modify_the_global_node_installation(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"packageManager":"yarn@4.9.2"}\n', encoding="utf-8")
        shim_directory = tmp_path / "isolated-bin"
        runner = FakeRunner([(0, "")])

        environment, prefix = rollout.provision_consumer_tools(tmp_path, shim_directory, runner, {"PATH": ""})

        assert prefix == ()
        assert runner.commands == [
            ("corepack", "enable", "--install-directory", str(shim_directory)),
        ]
        assert environment["PATH"].startswith(str(shim_directory))

    def test_provisions_exact_tools_declared_by_consumer_workflows(self, tmp_path: Path) -> None:
        workflows = tmp_path / ".github/workflows"
        workflows.mkdir(parents=True)
        (workflows / "terraform.yml").write_text(
            """jobs:
  lint:
    steps:
      - uses: hashicorp/setup-terraform@0123456789012345678901234567890123456789
        with:
          terraform_version: 1.14.7
""",
            encoding="utf-8",
        )
        runner = FakeRunner([(0, "installed")])

        environment, prefix = rollout.provision_consumer_tools(
            tmp_path,
            tmp_path / "outside/bin",
            runner,
            {"PATH": "/usr/bin"},
        )

        assert prefix == ("mise", "exec", "terraform@1.14.7", "--")
        assert runner.commands == [("mise", "install", "terraform@1.14.7")]
        assert environment["MISE_YES"] == "1"
        assert environment["MISE_TRUSTED_CONFIG_PATHS"] == str(tmp_path.resolve())

    def test_conflicting_workflow_tool_versions_are_rejected(self, tmp_path: Path) -> None:
        workflows = tmp_path / ".github/workflows"
        workflows.mkdir(parents=True)
        for name, version in (("one.yml", "1.14.7"), ("two.yml", "1.13.5")):
            (workflows / name).write_text(
                "jobs:\n  lint:\n    steps:\n"
                "      - uses: hashicorp/setup-terraform@0123456789012345678901234567890123456789\n"
                f"        with:\n          terraform_version: {version}\n",
                encoding="utf-8",
            )

        with pytest.raises(rollout.RolloutError, match="conflicting terraform versions"):
            rollout.declared_workflow_tools(tmp_path)

    def test_consumer_verification_is_scoped_to_the_captured_base(self) -> None:
        original = {"PATH": "/tools", "SARJ_REACT_DOCTOR_BASE": "stale"}
        base_sha = "b" * 40

        prepared = rollout.consumer_verification_environment(original, base_sha)

        assert prepared == {"PATH": "/tools", "SARJ_STANDARDS_BASE": base_sha}
        assert original["SARJ_REACT_DOCTOR_BASE"] == "stale"

    def test_provisions_consumer_declared_uv_on_path_for_nested_verification(self, tmp_path: Path) -> None:
        backend = tmp_path / "backend"
        backend.mkdir()
        (backend / "uv.toml").write_text('required-version = "==0.11.32"\n', encoding="utf-8")
        (tmp_path / ".sarj-standards.toml").write_text(
            'schema = 4\nbundle = "6.0.4"\n\n[dest]\npython = "backend"\ntypescript = "."\n',
            encoding="utf-8",
        )
        shim_directory = tmp_path / "outside" / "bin"
        runner = FakeRunner([(0, "installed")])

        environment, prefix = rollout.provision_consumer_tools(
            tmp_path,
            shim_directory,
            runner,
            {"PATH": "/usr/bin"},
        )

        assert prefix == ()
        assert runner.commands == [("uv", "--no-config", "tool", "install", "--force", "uv==0.11.32")]
        assert runner.environments == [
            {
                "PATH": "/usr/bin",
                "UV_TOOL_DIR": str(shim_directory.parent / "uv-tools"),
                "UV_TOOL_BIN_DIR": str(shim_directory),
            }
        ]
        assert environment["PATH"] == f"{shim_directory}:/usr/bin"

    def test_declared_uv_provision_failure_is_actionable(self, tmp_path: Path) -> None:
        backend = tmp_path / "backend"
        backend.mkdir()
        (backend / "uv.toml").write_text('required-version = "==0.11.32"\n', encoding="utf-8")
        (tmp_path / ".sarj-standards.toml").write_text(
            'schema = 4\nbundle = "6.0.4"\n\n[dest]\npython = "backend"\ntypescript = "."\n',
            encoding="utf-8",
        )
        runner = FakeRunner([(7, "registry unavailable")])

        with pytest.raises(rollout.RolloutError, match="could not provision repository-declared uv"):
            rollout.provision_consumer_tools(tmp_path, tmp_path / "bin", runner, {"PATH": "/usr/bin"})

    def test_runs_declared_consumer_bootstrap_in_order(self, tmp_path: Path) -> None:
        backend = tmp_path / "backend"
        backend.mkdir()
        (backend / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        (tmp_path / ".sarj-standards.toml").write_text(
            'schema = 4\nbundle = "5.16.5"\n\n[dest]\npython = "backend"\ntypescript = "."\n\n[ci]\n'
            'bootstrap = ["npm --prefix frontend run generate:api", "npm --prefix frontend run typegen"]\n',
            encoding="utf-8",
        )
        runner = FakeRunner([(0, "synced"), (0, "generated"), (0, "typed")])

        failure = rollout.run_consumer_bootstrap(
            tmp_path,
            ("mise", "exec", "--"),
            runner,
            {"PATH": "/tools"},
        )

        assert failure is None
        assert runner.commands == [
            ("mise", "exec", "--", "uv", "sync", "--locked", "--project", "backend"),
            (
                "mise",
                "exec",
                "--",
                "bash",
                "--noprofile",
                "--norc",
                "-e",
                "-o",
                "pipefail",
                "-c",
                "npm --prefix frontend run generate:api",
            ),
            (
                "mise",
                "exec",
                "--",
                "bash",
                "--noprofile",
                "--norc",
                "-e",
                "-o",
                "pipefail",
                "-c",
                "npm --prefix frontend run typegen",
            ),
        ]
        assert runner.environments == [{"PATH": "/tools"}, {"PATH": "/tools"}, {"PATH": "/tools"}]

    def test_stops_consumer_bootstrap_when_locked_python_install_fails(self, tmp_path: Path) -> None:
        backend = tmp_path / "backend"
        backend.mkdir()
        (backend / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        (tmp_path / ".sarj-standards.toml").write_text(
            'schema = 4\nbundle = "5.16.5"\n\n[dest]\npython = "backend"\ntypescript = "."\n\n'
            '[ci]\nbootstrap = ["generate"]\n',
            encoding="utf-8",
        )
        runner = FakeRunner([(7, "sync failed")])

        failure = rollout.run_consumer_bootstrap(tmp_path, (), runner, {})

        assert failure is not None
        assert failure.returncode == 7
        assert runner.commands == [("uv", "sync", "--locked", "--project", "backend")]

    def test_consumer_bootstrap_honors_the_python_projects_uv_version(self, tmp_path: Path) -> None:
        backend = tmp_path / "backend"
        backend.mkdir()
        (backend / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        (backend / "uv.toml").write_text('required-version = "==0.11.32"\n', encoding="utf-8")
        (tmp_path / ".sarj-standards.toml").write_text(
            'schema = 4\nbundle = "6.0.2"\n\n[dest]\npython = "backend"\ntypescript = "."\n',
            encoding="utf-8",
        )
        runner = FakeRunner([(0, "synced")])

        failure = rollout.run_consumer_bootstrap(tmp_path, (), runner, {})

        assert failure is None
        assert runner.commands == [
            (
                "uvx",
                "--no-config",
                "--isolated",
                "--from",
                "uv==0.11.32",
                "uv",
                "sync",
                "--locked",
                "--project",
                "backend",
            )
        ]

    def test_stops_consumer_bootstrap_at_first_failure(self, tmp_path: Path) -> None:
        (tmp_path / ".sarj-standards.toml").write_text(
            'schema = 4\nbundle = "5.16.5"\n\n[ci]\nbootstrap = ["first", "second"]\n',
            encoding="utf-8",
        )
        runner = FakeRunner([(9, "failed")])

        failure = rollout.run_consumer_bootstrap(tmp_path, (), runner, {})

        assert failure is not None
        assert failure.returncode == 9
        assert runner.commands == [("bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", "first")]

    def test_installs_secondary_javascript_lock_roots_before_verification(self, tmp_path: Path) -> None:
        primary = tmp_path / "typescript" / "dashboard"
        primary.mkdir(parents=True)
        (primary / "package.json").write_text('{"packageManager":"pnpm@11.20.0"}\n', encoding="utf-8")
        (primary / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        secondary = tmp_path / "secondary-app" / "web"
        secondary.mkdir(parents=True)
        (secondary / "package-lock.json").write_text("{}\n", encoding="utf-8")
        fixture = tmp_path / "tests" / "fixture"
        fixture.mkdir(parents=True)
        (fixture / "package-lock.json").write_text("{}\n", encoding="utf-8")
        (tmp_path / ".sarj-standards.toml").write_text(
            'schema = 4\nbundle = "6.1.7"\n\n[dest]\npython = "."\ntypescript = "typescript/dashboard"\n',
            encoding="utf-8",
        )
        runner = FakeRunner([(0, "installed")])

        failure = rollout.run_consumer_bootstrap(tmp_path, ("mise", "exec", "--"), runner, {})

        assert failure is None
        assert runner.commands == [
            (
                "mise",
                "exec",
                "--",
                "npm",
                "ci",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
            )
        ]
        assert runner.working_directories == [secondary]

    def test_stops_when_a_secondary_javascript_install_fails(self, tmp_path: Path) -> None:
        primary = tmp_path / "typescript"
        primary.mkdir()
        secondary = tmp_path / "web"
        secondary.mkdir()
        (secondary / "package-lock.json").write_text("{}\n", encoding="utf-8")
        (tmp_path / ".sarj-standards.toml").write_text(
            'schema = 4\nbundle = "6.1.7"\n\n[dest]\npython = "."\ntypescript = "typescript"\n\n'
            '[ci]\nbootstrap = ["must-not-run"]\n',
            encoding="utf-8",
        )
        runner = FakeRunner([(8, "npm failed")])

        failure = rollout.run_consumer_bootstrap(tmp_path, (), runner, {})

        assert failure is not None
        assert failure.returncode == 8
        assert runner.commands == [("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund")]

    def test_existing_verification_block_does_not_stop_later_consumers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        blocked = rollout.Outcome(consumer(), "blocked", "https://pr/1", "consumer verification failed; fix it")

        def blocked_status(
            _consumer: rollout.Consumer, _version: str, _runner: rollout.CommandRunner
        ) -> rollout.Outcome:
            return blocked

        monkeypatch.setattr(rollout, "status_one", blocked_status)

        result = rollout.apply_one(consumer(), "5.8.1", FakeRunner(), dry_run=True)

        assert result.state == "would-create"
