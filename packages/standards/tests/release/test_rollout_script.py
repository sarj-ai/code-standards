from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import tempfile
from typing import TYPE_CHECKING, final

import pytest

from sarj_standards.libs.release import rollout


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@final
class FakeRunner:
    def __init__(self, responses: list[tuple[int, str]] | None = None) -> None:
        self.responses: list[tuple[int, str]] = list(responses or [])
        self.commands: list[tuple[str, ...]] = []
        self.environments: list[Mapping[str, str] | None] = []

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd
        rendered = tuple(command)
        self.commands.append(rendered)
        self.environments.append(env)
        returncode, stdout = self.responses.pop(0) if self.responses else (0, "")
        result = subprocess.CompletedProcess(rendered, returncode, stdout, "")
        if check and returncode:
            raise subprocess.CalledProcessError(returncode, rendered, output=stdout)
        return result


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
            (MANIFEST, "uv.lock", "eslint.config.mjs", ".github/workflows/standards.yml", ".github/workflows/ci.yml")
        )

    def test_only_prevalidated_retired_suppression_source_is_allowed(self) -> None:
        source = "apps/web/src/index.ts"

        rollout.reject_unsafe_diff((MANIFEST, source), allowed_source_paths=frozenset({source}))

        with pytest.raises(rollout.RolloutError):
            rollout.reject_unsafe_diff((MANIFEST, source))

    def test_status_parser_includes_untracked_files(self) -> None:
        runner = FakeRunner([(0, " M .sarj-standards.toml\0?? generated.toml\0")])

        assert rollout.changed_paths(Path("repo"), runner) == (MANIFEST, "generated.toml")
        assert "-z" in runner.commands[0]

    def test_status_parser_rejects_deletes(self) -> None:
        runner = FakeRunner([(0, " D protected.toml\0")])

        with pytest.raises(rollout.RolloutError, match="delete or rename"):
            rollout.changed_paths(Path("repo"), runner)

    def test_consumer_environment_scrubs_github_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GH_TOKEN", "secret")
        monkeypatch.setenv("GITHUB_TOKEN", "secret")
        monkeypatch.setenv("PATH", "/bin")

        environment = rollout.unauthenticated_environment()

        assert "GH_TOKEN" not in environment
        assert "GITHUB_TOKEN" not in environment
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


class TestStatus:
    def test_open_pr_is_idempotently_reported(self) -> None:
        marker = rollout.pr_marker(consumer(), "5.8.1")
        payload = json.dumps(
            [
                {
                    "state": "OPEN",
                    "mergedAt": None,
                    "url": "https://pr/1",
                    "headRefName": "standards-rollout/current",
                    "baseRefName": "main",
                    "body": marker + "\n" + rollout.desired_marker("5.8.1"),
                }
            ]
        )
        runner = FakeRunner([(0, payload)])

        result = rollout.status_one(consumer(), "5.8.1", runner)

        assert result.state == "pr-open"
        assert result.url == "https://pr/1"
        assert "--head" in runner.commands[0]

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


class TestRelease:
    def test_release_verification_binds_package_and_tag_sha(self) -> None:
        sha = "a" * 40
        runner = FakeRunner(
            [
                (0, "sarj-standards 5.8.1"),
                (
                    0,
                    f"{'c' * 40}\trefs/tags/standards-v5.8.1\n{sha}\trefs/tags/standards-v5.8.1^{{}}\n",
                ),
            ]
        )

        assert rollout.verify_release("5.8.1", runner) == sha
        assert "sarj-standards==5.8.1" in runner.commands[0]
        assert "refs/tags/standards-v5.8.1^{}" in runner.commands[1]

    def test_release_rejects_version_substring(self) -> None:
        runner = FakeRunner([(0, "sarj-standards 15.8.10")])

        with pytest.raises(rollout.RolloutError, match="did not report"):
            rollout.verify_release("5.8.1", runner)

    def test_dry_run_does_not_clone_or_push(self, tmp_path: Path) -> None:
        sha = "b" * 40
        registry = rollout.load_registry(registry_path(tmp_path))
        responses: list[tuple[int, str]] = [
            (0, "sarj-standards 5.8.1"),
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

    def test_existing_verification_block_does_not_stop_later_consumers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        blocked = rollout.Outcome(consumer(), "blocked", "https://pr/1", "consumer verification failed; fix it")

        def blocked_status(
            _consumer: rollout.Consumer, _version: str, _runner: rollout.CommandRunner
        ) -> rollout.Outcome:
            return blocked

        monkeypatch.setattr(rollout, "status_one", blocked_status)

        result = rollout.apply_one(consumer(), "5.8.1", FakeRunner(), dry_run=True)

        assert result.state == "would-create"
