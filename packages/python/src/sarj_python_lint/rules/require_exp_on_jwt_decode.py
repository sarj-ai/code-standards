from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_PYJWT_MODULES: Final = frozenset({"jwt", "jwt.api_jwt"})
_DECODERS: Final = frozenset({"decode", "decode_complete"})
_MESSAGE = (
    "PyJWT accepts a token without an exp claim unless it is required, so this decode can honor a credential that "
    'never expires. Pass options={"require": ["exp"]} (and enforce a maximum lifetime in the verifier).'
)


@final
class RequireExpOnJwtDecode(Rule):
    id = "require-exp-on-jwt-decode"
    code = "SARJ504"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="PyJWT decode calls require the exp claim.",
        rationale=(
            "PyJWT validates `exp` only when the claim is present. A token minted without `exp` (for example by a "
            "helper whose lifetime defaults to None) passes verification forever. RFC 8725 tells verifiers to "
            "enforce the claims they rely on rather than trust the minter."
        ),
        remediation='Pass `options={"require": ["exp"]}` to `jwt.decode` and bound the accepted lifetime.',
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Safe fixes require an unmutated PyJWT import, no expanded/positional options, and absent options or a static mapping with a static string require sequence. They add only exp and preserve existing option flags and claims; maximum lifetime remains a separate policy decision.",
            "Calls resolved to PyJWT module-level `jwt.decode` or `jwt.decode_complete` are checked; `PyJWT` instances are not.",
            (
                "A literal `options` mapping must contain a literal `require` collection with `exp`. Non-literal options, "
                "`**` unpacking, and literal options that disable signature verification are accepted."
            ),
            "A verifier that enforces its own lifetime from `iat` instead still needs an exact suppression with that reason.",
            "Tests and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="exp-optional",
                title="A token without exp is accepted",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "auth.py",
                        "import jwt\n\n\ndef claims(token: str, key: str) -> dict[str, object]:\n"
                        "    return jwt.decode(token, key, algorithms=['HS256'])\n",
                    ),
                ),
                focus_path=PurePosixPath("auth.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="exp-required",
                title="The verifier requires exp",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "auth.py",
                        "import jwt\n\n\ndef claims(token: str, key: str) -> dict[str, object]:\n"
                        "    return jwt.decode(token, key, algorithms=['HS256'], options={'require': ['exp']})\n",
                    ),
                ),
                focus_path=PurePosixPath("auth.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="safe-autofix-subset",
                title="A proven subset has a convergent automatic fix",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        (
                            "import jwt\n"
                            "def claims(token, key):\n"
                            "    return jwt.decode(token, key, algorithms=['HS256'])\n"
                        ),
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        (
                            "import jwt\n"
                            "def claims(token, key):\n"
                            "    return jwt.decode(token, key, algorithms=['HS256'], options={'require': ['exp']})\n"
                        ),
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        if "jwt" not in context.symbol_source:
            return []
        imports = context.imports
        return [
            Diagnostic(context.path, node.lineno, node.col_offset + 1, self.code, _MESSAGE, severity=Severity.WARNING)
            for node in context.nodes(ast.Call)
            if imports.resolved_symbol(node.func, sources=_PYJWT_MODULES) in _DECODERS and _exp_is_optional(node)
        ]


def _exp_is_optional(call: ast.Call) -> bool:
    if any(keyword.arg is None for keyword in call.keywords):
        return False
    options = next((keyword.value for keyword in call.keywords if keyword.arg == "options"), None)
    if options is None:
        return True
    if not isinstance(options, ast.Dict) or any(key is None for key in options.keys):
        return False
    entries = {
        key.value: value
        for key, value in zip(options.keys, options.values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    signature = entries.get("verify_signature")
    if isinstance(signature, ast.Constant) and signature.value is False:
        return False
    required = entries.get("require")
    if required is None:
        return True
    if not isinstance(required, (ast.List, ast.Tuple, ast.Set)):
        return False
    return not any(isinstance(item, ast.Constant) and item.value == "exp" for item in required.elts)
