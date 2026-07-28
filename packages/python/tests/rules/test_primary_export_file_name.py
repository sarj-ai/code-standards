from pathlib import Path
from sarj_python_lint.rules.primary_export_file_name import PrimaryExportFileName

rule = PrimaryExportFileName()

def test_matching_primary_export() -> None:
    diagnostics = rule.check(Path("src/user_account_service.py"), "class UserAccountService:\n    pass")
    assert diagnostics == []

def test_mismatched_primary_export() -> None:
    diagnostics = rule.check(Path("src/user_data.py"), "class UserAccountService:\n    pass")
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ075"
    assert "user_account_service.py" in diagnostics[0].message

def test_skipped_framework_files() -> None:
    diagnostics = rule.check(Path("src/models.py"), "class User:\n    pass")
    assert diagnostics == []

def test_skipped_test_files() -> None:
    diagnostics = rule.check(Path("tests/test_user.py"), "class UserAccountService:\n    pass")
    assert diagnostics == []
