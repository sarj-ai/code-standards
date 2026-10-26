from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, TypeGuard, Unpack

import pytest

from sarj_standards.libs.adoption import manifest, transaction
from sarj_standards.libs.repository import docs
from sarj_standards.libs.typed_containers import is_object_mapping


if TYPE_CHECKING:
    from tests.call_contracts import SubprocessOptions


REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATED_READMES = (
    Path("README.md"),
    Path("packages/bootstrap/README.md"),
    Path("packages/contracts/README.md"),
    Path("packages/standards/README.md"),
    Path("packages/standards-compat/README.md"),
    Path("packages/python/README.md"),
    Path("packages/sql/README.md"),
    Path("packages/iac/README.md"),
    Path("packages/typescript/README.md"),
    Path("packages/tsconfig/README.md"),
    Path("plugins/sarj-skills/README.md"),
    Path(".github/SECURITY.md"),
)


def _is_object_table(value: object) -> TypeGuard[dict[str, object]]:
    return is_object_mapping(value) and all(isinstance(key, str) for key in value)


def _is_string_table(value: object) -> TypeGuard[dict[str, str]]:
    return _is_object_table(value) and all(isinstance(item, str) for item in value.values())


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] -- inspect the stdlib decoder's untyped JSON payload before asserting the serialized contract.


def _repository(root: Path) -> None:
    packages = {
        "standards": (
            "pyproject.toml",
            (
                '[project]\nname = "code-standards"\nversion = "1.0.0"\ndescription = "Repository standards."\n'
                'license = "MIT"\nrequires-python = ">=3.14"\n[project.scripts]\n'
                'code-standards = "sarj_standards.__main__:main"\n'
            ),
        ),
        "bootstrap": (
            "pyproject.toml",
            (
                '[project]\nname = "sarj-standards-bootstrap"\nversion = "1.0.0"\n'
                'description = "Standards bootstrap."\nlicense = "MIT"\nrequires-python = ">=3.14"\n'
                '[project.scripts]\ncode-standards = "sarj_standards_bootstrap:main"\n'
            ),
        ),
        "contracts": (
            "pyproject.toml",
            '[project]\nname = "sarj-rule-contracts"\nversion = "0.1.0"\ndescription = "Shared rule contracts."\n',
        ),
        "standards-compat": (
            "pyproject.toml",
            (
                '[project]\nname = "sarj-standards"\nversion = "1.0.0"\n'
                'description = "Compatibility bridge."\nlicense = "MIT"\nrequires-python = ">=3.14"\n'
                '[project.scripts]\ncode-standards = "sarj_standards.__main__:main"\n'
            ),
        ),
        "python": (
            "pyproject.toml",
            (
                '[project]\nname = "sarj-python-lint"\nversion = "1.0.0"\ndescription = "Python rules."\n'
                'license = "MIT"\nrequires-python = ">=3.14"\n[project.scripts]\n'
                'sarj-python-lint = "sarj_python_lint.__main__:main"\n'
            ),
        ),
        "sql": (
            "pyproject.toml",
            (
                '[project]\nname = "sarj-sql-lint"\nversion = "1.0.0"\ndescription = "SQL rules."\n'
                'license = "MIT"\nrequires-python = ">=3.14"\n[project.scripts]\n'
                'sarj-sql-lint = "sarj_sql_lint.__main__:main"\n'
            ),
        ),
        "iac": (
            "pyproject.toml",
            (
                '[project]\nname = "sarj-iac-lint"\nversion = "1.0.0"\ndescription = "IaC rules."\n'
                'license = "MIT"\nrequires-python = ">=3.14"\n[project.scripts]\n'
                'sarj-iac-lint = "sarj_iac_lint.__main__:main"\n'
            ),
        ),
        "typescript": (
            "package.json",
            '{"name":"@sarj/eslint-plugin","version":"1.0.0","description":"TypeScript rules.","license":"MIT"}\n',
        ),
        "tsconfig": (
            "package.json",
            '{"name":"@sarj/tsconfig","version":"1.0.0","description":"TypeScript configs.","license":"MIT"}\n',
        ),
    }
    for directory, (filename, content) in packages.items():
        path = root / "packages" / directory / filename
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
    ledger = root / "packages/standards/src/sarj_standards/configs/rule-ledger.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps({"rules": {"eslint": ["one", "two"], "python": ["one"], "sql": [], "iac": [], "text": []}}),
        encoding="utf-8",
    )
    plugin_manifest = root / "plugins/sarj-skills/.claude-plugin/plugin.json"
    plugin_manifest.parent.mkdir(parents=True)
    plugin_manifest.write_text(
        json.dumps(
            {
                "name": "sarj-skills",
                "version": "1.0.0",
                "description": "Judgment-layer audits.",
                "author": {"name": "sarj-ai"},
            }
        ),
        encoding="utf-8",
    )
    command = root / "plugins/sarj-skills/commands/security.md"
    command.parent.mkdir(parents=True)
    command.write_text("# Security\n", encoding="utf-8")
    skill = root / "plugins/sarj-skills/skills/audit-protocol/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Audit protocol\n", encoding="utf-8")
    (root / "README.md").write_text("# stale\n", encoding="utf-8")
    for relative in (
        "AGENTS.md",
        "packages/standards/README.md",
        "packages/python/README.md",
        "packages/sql/README.md",
        "packages/iac/README.md",
        "packages/typescript/README.md",
        "packages/tsconfig/README.md",
        "plugins/sarj-skills/README.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n", encoding="utf-8")


def test_check_reports_drift_without_writing(tmp_path: Path) -> None:
    _repository(tmp_path)
    before = (tmp_path / "README.md").read_bytes()

    result = docs.check(tmp_path)

    assert result.status == 1
    assert result.changed == tuple(sorted(tmp_path / relative for relative in GENERATED_READMES))
    assert (tmp_path / "README.md").read_bytes() == before


def test_sync_is_deterministic_and_check_then_passes(tmp_path: Path) -> None:
    _repository(tmp_path)

    first = docs.sync(tmp_path)
    rendered = (tmp_path / "README.md").read_text(encoding="utf-8")
    second = docs.sync(tmp_path)

    assert first.status == 1
    assert second.status == 0
    assert docs.check(tmp_path).status == 0
    assert "uvx --no-config --isolated --python 3.15 --from code-standards code-standards setup" in rendered
    assert "do not install a second Repo Standards hook" in rendered
    assert "Install uv 0.13.5, Python 3.15, Node 24.22, and GNU Make" in rendered
    assert "make setup\nmake verify" in rendered
    assert "[Documentation](https://code-standards.sarj.ai/)" in rendered
    assert "## Rule catalog" not in rendered
    bootstrap_readme = (tmp_path / "packages/bootstrap/README.md").read_text(encoding="utf-8")
    assert "sarj-standards-bootstrap code-standards check" in bootstrap_readme
    assert "inherits UV/PIP registry, proxy, certificate, cache, and offline environment policy" in bootstrap_readme
    security_policy = (tmp_path / ".github/SECURITY.md").read_text(encoding="utf-8")
    assert "/security/advisories/new" in security_policy
    assert "within two business days" in security_policy
    for relative in GENERATED_READMES:
        generated = (tmp_path / relative).read_text(encoding="utf-8")
        assert generated.startswith("<!-- Generated by `code-standards maintain docs sync`; do not edit. -->")
        assert "generated:packages" not in generated


def test_catalog_content_is_left_to_the_website(tmp_path: Path) -> None:
    _repository(tmp_path)
    catalog = tmp_path / "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "rules": [
                    {
                        "key": "python:no-example",
                        "engine": "python",
                        "summary": "Require a useful example.",
                        "defaultLevel": "error",
                        "autofix": "none",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    docs.sync(tmp_path)

    root_readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    python_readme = (tmp_path / "packages/python/README.md").read_text(encoding="utf-8")
    assert "python:no-example" not in root_readme
    assert "python:no-example" not in python_readme
    assert (
        "[Documentation](https://code-standards.sarj.ai/) · [Source](https://github.com/sarj-ai/code-standards)"
    ) in python_readme.splitlines()


def test_authored_readme_is_reported_as_complete_generated_drift(tmp_path: Path) -> None:
    _repository(tmp_path)
    docs.sync(tmp_path)
    readme = tmp_path / "packages/python/README.md"
    readme.write_text("# authored replacement\n", encoding="utf-8")

    result = docs.check(tmp_path)

    assert result.changed == (readme,)


@pytest.mark.parametrize("filename", ["notes.md", "notes.mdx", "notes.rst"])
def test_arbitrary_authored_document_is_rejected(tmp_path: Path, filename: str) -> None:
    _repository(tmp_path)
    (tmp_path / filename).write_text("Authored prose.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not generated or executable-policy allowlisted"):
        docs.check(tmp_path)


def test_broken_local_link_fails_loudly(tmp_path: Path) -> None:
    _repository(tmp_path)
    (tmp_path / "AGENTS.md").write_text("[missing](does-not-exist.md)\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing local target"):
        docs.check(tmp_path)


@pytest.mark.parametrize("harness", [".agents", ".claude"])
def test_skill_discovery_documents_validate_their_links(tmp_path: Path, harness: str) -> None:
    _repository(tmp_path)
    adapter = tmp_path / harness / "skills" / "audit-protocol" / "SKILL.md"
    adapter.parent.mkdir(parents=True)
    adapter.write_text(
        "[Canonical skill](../../../plugins/sarj-skills/skills/audit-protocol/SKILL.md)\n", encoding="utf-8"
    )

    docs.check(tmp_path)

    adapter.write_text("[Missing skill](missing.md)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing local target"):
        docs.check(tmp_path)


def test_broken_local_heading_link_fails_loudly(tmp_path: Path) -> None:
    _repository(tmp_path)
    (tmp_path / "AGENTS.md").write_text("[missing](README.md#absent-heading)\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing Markdown heading"):
        docs.check(tmp_path)


def test_stale_command_example_fails_loudly(tmp_path: Path) -> None:
    _repository(tmp_path)
    (tmp_path / "AGENTS.md").write_text("```bash\ncode-standards --help\ncode-standards init\n```\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid command example: 'code-standards init'"):
        docs.check(tmp_path)


def test_multiline_command_preserves_its_arguments(tmp_path: Path) -> None:
    _repository(tmp_path)
    (tmp_path / "AGENTS.md").write_text("code-standards\n--root . doctor\n", encoding="utf-8")

    assert docs.check(tmp_path).status == 1


@pytest.mark.parametrize("response", ["", "unexpected output", "999"])
def test_failed_command_validation_worker_prevents_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: str
) -> None:
    _repository(tmp_path)
    before = (tmp_path / "README.md").read_bytes()

    def failed_worker(_arguments: list[str], **_options: Unpack[SubprocessOptions]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["worker"], 1, stdout=response, stderr="")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the production process boundary; injection would bypass this protocol check.
        subprocess, "run", failed_worker
    )

    with pytest.raises(ValueError, match="command example validation failed"):
        docs.sync(tmp_path)

    assert (tmp_path / "README.md").read_bytes() == before


def test_incomplete_successful_command_validation_prevents_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repository(tmp_path)
    before = (tmp_path / "README.md").read_bytes()

    def incomplete_worker(
        _arguments: list[str], **_options: Unpack[SubprocessOptions]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["worker"], 0, stdout="0\n", stderr="")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the production process boundary; injection would bypass this protocol check.
        subprocess, "run", incomplete_worker
    )

    with pytest.raises(ValueError, match="did not check every example"):
        docs.sync(tmp_path)

    assert (tmp_path / "README.md").read_bytes() == before


def test_sync_uses_validated_atomic_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repository(tmp_path)
    written: list[Path] = []
    real_write = transaction.atomic_write_text

    def record_write(root: Path, path: Path, contents: str) -> None:
        written.append(path)
        real_write(root, path, contents)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- records transactional documentation writes
        transaction, "atomic_write_text", record_write
    )

    docs.sync(tmp_path)

    assert written == sorted(tmp_path / relative for relative in GENERATED_READMES)


def test_repository_generated_documentation_has_no_drift() -> None:
    assert docs.check(REPO_ROOT).status == 0


def test_sarj_skills_marketplace_source_is_installable() -> None:
    marketplace = manifest.as_table(_load_json(REPO_ROOT / ".claude-plugin/marketplace.json"))
    assert marketplace.get("name") == "sarj", "Consumers install plugins through the public @sarj marketplace."
    entries = [manifest.as_table(value) for value in manifest.list_field(marketplace, "plugins")]
    plugins = [entry for entry in entries if entry.get("name") == "sarj-skills"]
    assert len(plugins) == 1, "Consumers must be able to install sarj-skills@sarj unambiguously."
    source = plugins[0].get("source")
    assert isinstance(source, str), "The bundled skills plugin needs a local source."
    assert source.startswith("./"), "The bundled skills plugin needs a checkout-relative source."
    plugin_root = (REPO_ROOT / source).resolve()
    assert plugin_root.is_relative_to(REPO_ROOT), f"Plugin source escapes the checkout: {source}"
    plugin = manifest.as_table(_load_json(plugin_root / ".claude-plugin/plugin.json"))
    assert plugin.get("name") == "sarj-skills", f"Marketplace/plugin identity mismatch: {source}"
    assert any(plugin_root.glob("commands/*.md")) or any(plugin_root.glob("skills/*/SKILL.md")), (
        f"Plugin source has no discoverable commands or skills: {source}"
    )


def test_docs_lint_dependencies_are_reproducible_and_compatible() -> None:
    raw: object = json.loads((REPO_ROOT / "apps/docs/package.json").read_text(encoding="utf-8"))  # pyright: ignore[reportAny] -- inspect the stdlib decoder's untyped JSON payload before asserting the serialized contract.
    assert _is_object_table(raw)
    dependencies = raw.get("devDependencies")
    assert _is_string_table(dependencies)
    for name in ("@eslint/js", "eslint", "eslint-plugin-astro", "typescript-eslint"):
        assert dependencies[name][0].isdigit(), f"{name} must use an exact version"
    plugin_specifier = dependencies["@sarj/eslint-plugin"]
    assert plugin_specifier.startswith("file:")
    plugin_raw = _load_json(REPO_ROOT / "apps/docs" / plugin_specifier.removeprefix("file:") / "package.json")
    assert _is_object_table(plugin_raw)
    assert plugin_raw.get("name") == "@sarj/eslint-plugin"
    assert plugin_raw.get("version") == manifest.eslint_peers()["@sarj/eslint-plugin"]
    # Astro Check and typed lint use the supported API bridge; the current
    # native compiler remains separately available for command-line checks.
    assert dependencies["typescript"] == "npm:@typescript/typescript6@6.0.2"
    assert dependencies["@typescript/native"] == "npm:typescript@7.0.2"
