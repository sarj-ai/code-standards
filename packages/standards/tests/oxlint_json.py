from __future__ import annotations

from pydantic import BaseModel


class OxlintSpan(BaseModel):
    line: int


class OxlintLabel(BaseModel):
    span: OxlintSpan


class OxlintDiagnostic(BaseModel):
    code: str = ""
    message: str
    filename: str
    help: str | None = None
    labels: list[OxlintLabel] = []


class OxlintReport(BaseModel):
    diagnostics: list[OxlintDiagnostic]
