from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
    from sarj_python_lint.rules._fastapi import FastapiIndex


_UPLOAD_TYPES = frozenset(
    {"fastapi.UploadFile", "fastapi.datastructures.UploadFile", "starlette.datastructures.UploadFile"}
)
_FILE_MARKERS = frozenset({"fastapi.File", "fastapi.param_functions.File", "fastapi.params.File"})


def _example(*, example_id: str, title: str, source: str, matches: bool, public: bool = True) -> RuleExample:
    return RuleExample(
        example_id=example_id,
        title=title,
        outcome=ExampleOutcome.MATCH if matches else ExampleOutcome.NO_MATCH,
        files=(ExampleFile.python("app/routes.py", source),),
        focus_path=PurePosixPath("app/routes.py"),
        expected_count=1 if matches else 0,
        public=public,
    )


@final
class ServerProxiedFileUpload(Rule):
    id = "server-proxied-file-upload"
    code = "SARJ593"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Accept file uploads through short-lived pre-signed object-storage URLs instead of API request bodies",
        rationale=(
            "A route that receives file bytes puts every upload through the API process, its memory and timeouts, "
            "and the edge web application firewall. Firewalls inspect bodies as attack payloads, so ordinary "
            "documents can be blocked: Sarj Wiki Markdown imports were denied by Cloud Armor rule 932115 before "
            "reaching the backend. A pre-signed URL sends the bytes straight to private object storage, under a "
            "signature the server controls."
        ),
        remediation=(
            "Add a route that returns a pre-signed upload URL (GCS V4 signed URL or S3 pre-signed PUT/POST) for a "
            "server-chosen private object key, with a short expiry (15 minutes or less), a fixed content type and "
            "a bounded size (`x-goog-content-length-range` or an S3 `content-length-range` policy). The client "
            "uploads to that URL and sends only the returned upload id. Before using the object, the server checks "
            "ownership, size, type and checksum."
        ),
        category=RuleCategory.SECURITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Checks FastAPI route handlers found by the shared route index. Parameters annotated with "
                "`UploadFile` (also inside `Annotated`, `list[...]` or optional unions) or declared with "
                "`File()` are reported. Raw `Request.body()`/`Request.form()` reads, Starlette routes, "
                "`add_api_route`, routes registered on an app or router received as a function parameter, and "
                "other frameworks are not modeled."
            ),
            "Small fixed-size inputs that must be proxied can keep a reviewed suppression with the reason.",
            "Tests and generated code are excluded.",
        ),
        examples=(
            _example(
                example_id="upload-file-parameter",
                title="A route receives an `UploadFile`",
                source=(
                    "from fastapi import APIRouter, UploadFile\n"
                    "router = APIRouter()\n"
                    "@router.post('/documents')\n"
                    "async def upload(file: UploadFile) -> Document: ...\n"
                ),
                matches=True,
            ),
            _example(
                example_id="annotated-file-bytes",
                title="A route receives bytes declared with `File()`",
                source=(
                    "from typing import Annotated\n"
                    "from fastapi import APIRouter, File\n"
                    "router = APIRouter()\n"
                    "@router.post('/avatars')\n"
                    "def avatar(content: Annotated[bytes, File()]) -> Avatar: ...\n"
                ),
                matches=True,
                public=False,
            ),
            _example(
                example_id="signed-upload-url",
                title="A route returns a pre-signed upload URL and later accepts only its id",
                source=(
                    "from fastapi import APIRouter\n"
                    "router = APIRouter()\n"
                    "@router.post('/documents/uploads')\n"
                    "def create_upload(user: CurrentUser) -> SignedUpload:\n"
                    "    return sign_document_upload(user.id)\n"
                    "@router.post('/documents')\n"
                    "def create_document(request: DocumentFromUpload) -> Document: ...\n"
                ),
                matches=False,
            ),
            _example(
                example_id="helper-outside-route",
                title="A helper that is not a route may handle an `UploadFile`",
                source=(
                    "from fastapi import UploadFile\n"
                    "async def read_upload(file: UploadFile) -> bytes:\n"
                    "    return await file.read()\n"
                ),
                matches=False,
                public=False,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if is_test_path(context.path) or context.generated or context.tree is None:
            return []
        functions = [
            function for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef) if function.decorator_list
        ]
        if not functions:
            return []
        index = context.fastapi
        diagnostics: list[Diagnostic] = []
        for function in functions:
            if not index.routes(function):
                continue
            for parameter, default in _parameters(function.args):
                if _receives_file(parameter.annotation, index) or _is_file_marker(default, index):
                    diagnostics.append(
                        Diagnostic(
                            path=context.path,
                            line=parameter.lineno,
                            col=parameter.col_offset + 1,
                            code=self.code,
                            message=(
                                f"Route parameter `{parameter.arg}` receives file bytes through the API; "
                                "return a short-lived pre-signed upload URL and accept only the upload id."
                            ),
                            severity=Severity.WARNING,
                        )
                    )
        return diagnostics


def _parameters(arguments: ast.arguments) -> list[tuple[ast.arg, ast.expr | None]]:
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(arguments.defaults))
    defaults.extend(arguments.defaults)
    return [*zip(positional, defaults, strict=True), *zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)]


def _receives_file(annotation: ast.expr | None, index: FastapiIndex) -> bool:
    if (resolved := index.resolve_annotation(annotation)) is None:
        return False
    for node in ast.walk(resolved):
        if isinstance(node, (ast.Name, ast.Attribute)) and index.imports.resolved_qualified_name(node) in _UPLOAD_TYPES:
            return True
        if _is_file_marker(node, index):
            return True
    return False


def _is_file_marker(node: ast.AST | None, index: FastapiIndex) -> bool:
    return isinstance(node, ast.Call) and index.imports.resolved_qualified_name(node.func) in _FILE_MARKERS
