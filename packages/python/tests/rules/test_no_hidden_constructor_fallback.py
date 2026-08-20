from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sarj_python_lint.__main__ import main
from sarj_python_lint.rule_base import Diagnostic, RuleExample, Severity
from sarj_python_lint.rules.no_hidden_constructor_fallback import (
    NoHiddenConstructorFallback,
)


def _check(source: str, path: Path = Path("service.py")) -> list[Diagnostic]:
    return NoHiddenConstructorFallback().check(path, source)


_PUBLIC_EXAMPLES = NoHiddenConstructorFallback.public_examples()


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(tmp_path: Path, example: RuleExample) -> None:
    root = tmp_path / example.example_id
    for item in example.files:
        target = root / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.source, encoding="utf-8")
    focus = root / example.focus_path

    findings = NoHiddenConstructorFallback().check(focus, example.focus_file.source)

    assert len(findings) == example.expected_count


def test_ignores_branch_local_settings_binding() -> None:
    source = """
from app.config import settings

class Service:
    def __init__(self, *, model: str | None = None):
        if use_override():
            settings = override_settings()
        self.model = model or settings.MODEL
"""

    assert _check(source) == []


def _settings_project(tmp_path: Path, service_source: str) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "config.py").write_text(
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n"
        "    MODEL: str = 'model'\n"
        "settings = Settings()\n"
    )
    service = package / "service.py"
    service.write_text(f"{service_source}\ngenerator = Generator(model='explicit')\n")
    return service


@pytest.mark.parametrize(
    "fallback",
    [
        "os.getenv('API_KEY')",
        "os.environ.get('API_KEY')",
        "os.environ['API_KEY']",
        "operating_system.getenv('API_KEY')",
        "environment.get('API_KEY')",
        "read_env('API_KEY')",
    ],
)
def test_environment_fallbacks_are_library_api_and_stay_quiet(fallback: str) -> None:
    if fallback.startswith("operating_system"):
        imports = "import os as operating_system"
    elif fallback.startswith("environment"):
        imports = "from os import environ as environment"
    elif fallback.startswith("read_env"):
        imports = "from os import getenv as read_env"
    else:
        imports = "import os"
    assert (
        _check(
            f"""{imports}

class Client:
    def __init__(self, *, api_key: str | None = None) -> None:
        self.api_key = api_key or {fallback}

client = Client(api_key="explicit")
"""
        )
        == []
    )


@pytest.mark.parametrize(
    ("imports", "fallback"),
    [
        ("from app.config import settings", "settings.MODEL"),
        ("from app.config import settings as app_settings", "app_settings.MODEL"),
        ("import app.config as config", "config.settings.MODEL"),
    ],
)
def test_proven_pydantic_settings_fallbacks_warn(
    tmp_path: Path,
    imports: str,
    fallback: str,
) -> None:
    service = _settings_project(
        tmp_path,
        f"""{imports}

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or {fallback}
""",
    )
    findings = _check(service.read_text(), service)
    assert len(findings) == 1
    assert findings[0].line == 4


def test_reexported_settings_instance_is_resolved(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.public_config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    (service.parent / "public_config.py").write_text("from app.config import settings\n")
    assert len(_check(service.read_text(), service)) == 1


def test_package_relative_settings_reexport_is_resolved(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    (service.parent / "__init__.py").write_text("from .config import settings\n")
    assert len(_check(service.read_text(), service)) == 1


@pytest.mark.parametrize(
    ("imports", "fallback"),
    [
        ("import app.config", "app.config.settings.MODEL"),
        ("from app import config", "config.settings.MODEL"),
    ],
)
def test_imported_settings_modules_are_resolved(tmp_path: Path, imports: str, fallback: str) -> None:
    service = _settings_project(
        tmp_path,
        f"""{imports}

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or {fallback}
""",
    )
    assert len(_check(service.read_text(), service)) == 1


def test_imported_base_settings_subclass_is_resolved(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    (service.parent / "base.py").write_text(
        "from pydantic_settings import BaseSettings\nclass AppSettings(BaseSettings):\n    MODEL: str = 'model'\n"
    )
    (service.parent / "config.py").write_text("from app.base import AppSettings\nsettings = AppSettings()\n")
    assert len(_check(service.read_text(), service)) == 1


def test_shadowed_settings_import_stays_quiet(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings
settings = object()

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    assert _check(service.read_text(), service) == []


@pytest.mark.parametrize(
    "shadow",
    [
        "settings: object",
        "tenant: object",
    ],
)
def test_constructor_scope_shadowing_stays_quiet(tmp_path: Path, shadow: str) -> None:
    service = _settings_project(
        tmp_path,
        f"""from app.config import settings

class Generator:
    def __init__(self, {shadow}, *, model: str | None = None) -> None:
        {"settings = tenant" if shadow.startswith("tenant") else "pass"}
        self.model = model or settings.MODEL
""",
    )
    assert _check(service.read_text(), service) == []


def test_same_module_settings_instance_is_resolved(tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    source = """from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MODEL: str = "model"

settings = Settings()

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL

generator = Generator(model="explicit")
"""
    path.write_text(source)
    assert len(_check(source, path)) == 1


def test_distribution_root_can_also_be_the_package_root(tmp_path: Path) -> None:
    package = tmp_path / "dashboard"
    package.mkdir()
    (package / "pyproject.toml").write_text("[project]\nname = 'dashboard'\nversion = '0.1.0'\n")
    (package / "__init__.py").write_text("")
    core = package / "core"
    core.mkdir()
    (core / "__init__.py").write_text("")
    (core / "config.py").write_text(
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n"
        "    MODEL: str = 'model'\n"
        "settings: Settings = Settings()\n"
    )
    service = package / "service.py"
    source = """from dashboard.core.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL

generator = Generator(model="explicit")
"""
    service.write_text(source)
    assert len(_check(source, service)) == 1


def test_absolute_imports_resolve_in_src_layout(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    package = tmp_path / "src" / "app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "config.py").write_text(
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n"
        "    MODEL: str = 'model'\n"
        "settings = Settings()\n"
    )
    service = package / "service.py"
    source = """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL

generator = Generator(model="explicit")
"""
    service.write_text(source)
    assert len(_check(source, service)) == 1


def test_aliased_constructor_call_is_a_composition_root(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    service.write_text(service.read_text().replace("\ngenerator = Generator(model='explicit')\n", "\n"))
    (service.parent / "composition.py").write_text(
        "from app.service import Generator as ModelGenerator\ngenerator = ModelGenerator(model='explicit')\n"
    )
    assert len(_check(service.read_text(), service)) == 1


def test_reexported_constructor_call_is_a_composition_root(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    service.write_text(service.read_text().replace("\ngenerator = Generator(model='explicit')\n", "\n"))
    (service.parent / "__init__.py").write_text("from .service import Generator\n")
    (service.parent / "composition.py").write_text(
        "from app import Generator\ngenerator = Generator(model='explicit')\n"
    )
    assert len(_check(service.read_text(), service)) == 1


def test_unrelated_same_named_call_is_not_a_composition_root(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings
from third_party import Generator as ThirdPartyGenerator

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    service.write_text(service.read_text().replace("\ngenerator = Generator(model='explicit')\n", "\n"))
    (service.parent / "composition.py").write_text(
        "from third_party import Generator\ngenerator = Generator(model='explicit')\n"
    )
    assert _check(service.read_text(), service) == []


def test_lexically_shadowed_call_is_not_a_composition_root(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    service.write_text(service.read_text().replace("\ngenerator = Generator(model='explicit')\n", "\n"))
    (service.parent / "composition.py").write_text(
        "from app.service import Generator\ndef build(Generator):\n    return Generator()\n"
    )
    assert _check(service.read_text(), service) == []


def test_class_binding_does_not_shadow_import_inside_method(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    service.write_text(service.read_text().replace("\ngenerator = Generator(model='explicit')\n", "\n"))
    (service.parent / "composition.py").write_text(
        "from app.service import Generator\n"
        "class Factory:\n"
        "    Generator = object\n"
        "    def build(self):\n"
        "        return Generator(model='explicit')\n"
    )
    assert len(_check(service.read_text(), service)) == 1


def test_comprehension_target_does_not_shadow_later_call(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    service.write_text(service.read_text().replace("\ngenerator = Generator(model='explicit')\n", "\n"))
    (service.parent / "composition.py").write_text(
        "from app.service import Generator\n"
        "def build(items):\n"
        "    values = [Generator for Generator in items]\n"
        "    return Generator(model='explicit')\n"
    )
    assert len(_check(service.read_text(), service)) == 1


def test_comprehension_target_shadows_call_inside_comprehension(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    service.write_text(service.read_text().replace("\ngenerator = Generator(model='explicit')\n", "\n"))
    (service.parent / "composition.py").write_text(
        "from app.service import Generator\ndef build(items):\n    return [Generator() for Generator in items]\n"
    )
    assert _check(service.read_text(), service) == []


def test_generated_call_is_not_a_composition_root(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    service.write_text(service.read_text().replace("\ngenerator = Generator(model='explicit')\n", "\n"))
    (service.parent / "generated_composition.py").write_text(
        "# Generated by example-codegen. Do not edit.\n"
        "from app.service import Generator\n"
        "generator = Generator(model='explicit')\n"
    )
    assert _check(service.read_text(), service) == []


def test_composition_scan_parses_only_files_that_name_the_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class RareGenerator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    service.write_text(service.read_text().replace("Generator(model='explicit')", "RareGenerator(model='explicit')"))
    for index in range(200):
        (service.parent / f"decoy_{index}.py").write_text("value = make_value()\n")

    parse_calls = 0
    original_parse = ast.parse

    def counting_parse(source: str, filename: str = "<unknown>") -> ast.Module:
        nonlocal parse_calls
        parse_calls += 1
        return original_parse(source, filename=filename)

    monkeypatch.setattr(ast, "parse", counting_parse)
    assert len(_check(service.read_text(), service)) == 1
    assert parse_calls < 10


def test_a_new_analysis_observes_a_new_project_composition_call(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    service.write_text(service.read_text().replace("\ngenerator = Generator(model='explicit')\n", "\n"))
    source = service.read_text()

    assert _check(source, service) == []

    (service.parent / "composition.py").write_text(
        "from app.service import Generator\ngenerator = Generator(model='explicit')\n"
    )

    assert len(_check(source, service)) == 1


def test_last_duplicate_constructor_definition_wins(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL

    def __init__(self, *, model: str) -> None:
        self.model = model
""",
    )
    assert _check(service.read_text(), service) == []


@pytest.mark.parametrize(
    "body",
    [
        "self.model = model or settings.MODEL",
        "self.model = model if model is not None else settings.MODEL",
        "self.model = settings.MODEL if model is None else model",
        "if model is None:\n            model = settings.MODEL\n        self.model = model",
    ],
)
def test_each_supported_normalization_form_warns(tmp_path: Path, body: str) -> None:
    service = _settings_project(
        tmp_path,
        f"""from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        {body}
""",
    )
    assert len(_check(service.read_text(), service)) == 1


@pytest.mark.parametrize(
    "body",
    [
        "self.model = model if model is not None else settings.MODEL",
        "self.model = settings.MODEL if model is None else model",
        "if model is None:\n            model = settings.MODEL\n        self.model = model",
    ],
)
def test_none_aware_fallbacks_do_not_claim_falsey_values_are_omitted(tmp_path: Path, body: str) -> None:
    service = _settings_project(
        tmp_path,
        f"""from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        {body}
""",
    )
    findings = _check(service.read_text(), service)
    assert len(findings) == 1
    assert "falsey" not in findings[0].message


def test_boolean_or_fallback_explains_falsey_value_behavior(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or settings.MODEL
""",
    )
    findings = _check(service.read_text(), service)
    assert len(findings) == 1
    assert "falsey" in findings[0].message


def test_one_warning_lists_every_hidden_parameter(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, project: str | None = None, model: str | None = None) -> None:
        resolved_project = project or settings.MODEL
        self.model = model or settings.MODEL
""",
    )
    findings = _check(service.read_text(), service)
    assert len(findings) == 1
    assert "`project`, `model`" in findings[0].message
    assert findings[0].severity is Severity.WARNING
    assert "call site or composition root" in findings[0].message
    assert "falsey" in findings[0].message


@pytest.mark.parametrize(
    "fallback",
    [
        "Client()",
        "PromptAssemblyConfig()",
        "Path('./recordings')",
        "DEFAULT_MODEL",
        "Language.AR",
        "other_model",
        "self.default_model",
        "[]",
        "{}",
        "set()",
        "[item for item in items]",
    ],
)
def test_non_runtime_configuration_fallbacks_stay_quiet(fallback: str) -> None:
    source = f"""class Generator:
    def __init__(self, other_model=None, *, model: str | None = None) -> None:
        self.model = model or {fallback}
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "signature",
    [
        "model: str | None = None",
        "model: str | None = None, /",
        "*, model: str | None",
        "*, model: str = 'model'",
    ],
)
def test_only_omittable_keyword_only_parameters_are_in_scope(signature: str) -> None:
    source = f"""import os

class Generator:
    def __init__(self, {signature}) -> None:
        self.model = model or os.getenv("MODEL")
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "assignment",
    [
        "self.model = model",
        "self.model = model or 'literal'",
        "self.model = model or other_model or os.getenv('MODEL')",
        "self.model = model if model else os.getenv('MODEL')",
        "if not model:\n            model = os.getenv('MODEL')",
        "if model is None:\n            model = os.getenv('MODEL')\n        else:\n            model = model.strip()",
    ],
)
def test_near_miss_control_flow_stays_quiet(assignment: str) -> None:
    source = f"""import os

class Generator:
    def __init__(self, *, model: str | None = None, other_model: str = "x") -> None:
        {assignment}
"""
    assert _check(source) == []


def test_if_fallback_must_assign_back_to_the_checked_parameter(tmp_path: Path) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        if model is None:
            self.metrics_backend = settings.MODEL
""",
    )
    assert _check(service.read_text(), service) == []


def test_reassigned_parameter_is_not_treated_as_the_omission_sentinel() -> None:
    source = """import os

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        model = normalize(model)
        self.model = model or os.getenv("MODEL")
"""
    assert _check(source) == []


def test_nested_scope_is_not_constructor_normalization() -> None:
    source = """import os

class Generator:
    def __init__(self, *, model: str | None = None) -> None:
        def resolve() -> str | None:
            return model or os.getenv("MODEL")
        self.model = resolve()
"""
    assert _check(source) == []


def test_public_convenience_constructor_without_a_local_composition_root_stays_quiet() -> None:
    source = """import os

class PublicClient:
    def __init__(self, *, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("API_KEY")
"""
    assert _check(source) == []


@pytest.mark.parametrize("decorator", ["staticmethod", "classmethod"])
def test_descriptor_init_lookalikes_stay_quiet(decorator: str) -> None:
    source = f"""import os

class Generator:
    @{decorator}
    def __init__(*, model: str | None = None) -> None:
        value = model or os.getenv("MODEL")
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        Path("tests/service.py"),
        Path("test_service.py"),
        Path("migrations/001_service.py"),
        Path("alembic/versions/001_service.py"),
        Path("generated/service.py"),
        Path("vendor/service.py"),
    ],
    ids=["tests-dir", "test-module", "migration", "alembic", "generated", "vendor"],
)
def test_non_production_paths_are_exempt(path: Path) -> None:
    source = """import os
class Generator:
    def __init__(self, *, model=None):
        self.model = model or os.getenv("MODEL")

generator = Generator(model="explicit")
"""
    assert _check(source, path) == []


def test_generated_header_is_exempt() -> None:
    source = """# Generated by example-codegen. Do not edit.
import os
class Generator:
    def __init__(self, *, model=None):
        self.model = model or os.getenv("MODEL")

generator = Generator(model="explicit")
"""
    assert _check(source) == []


def test_syntax_errors_stay_quiet() -> None:
    assert _check("class Broken(") == []


def test_cli_prints_suppressible_warning_and_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    service = _settings_project(
        tmp_path,
        """from app.config import settings
class Generator:
    def __init__(self, *, model=None):
        self.model = model or settings.MODEL
""",
    )
    assert main(["check", "--rule", "no-hidden-constructor-fallback", str(service)]) == 0
    assert "SARJ095 warning:" in capsys.readouterr().out

    service.write_text(
        """from app.config import settings
class Generator:
    def __init__(
        self,
        *,
        model=None,  # sarj-noqa: SARJ095 — intentional convenience
    ):
        self.model = model or settings.MODEL

generator = Generator(model="explicit")
"""
    )
    assert main(["check", "--rule", "no-hidden-constructor-fallback", str(service)]) == 0
    assert not capsys.readouterr().out
