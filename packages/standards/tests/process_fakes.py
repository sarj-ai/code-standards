from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

from sarj_standards.libs.linting.process import ProcessCapabilities, ProcessOutput, ProcessRequest, ToolResolution


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class LegacyProcessFake(Protocol):
    def __call__(self, argv: Sequence[str], /, *, cwd: Path) -> ProcessOutput: ...


_PROVIDED_CAPABILITIES: Final = ProcessCapabilities(ToolResolution.PROVIDED)


class FakeProcessExecutor:
    def __init__(
        self,
        fake: LegacyProcessFake,
        *,
        capabilities: ProcessCapabilities = _PROVIDED_CAPABILITIES,
    ) -> None:
        self.fake = fake
        self.capabilities = capabilities
        self.requests: list[ProcessRequest] = []

    def run(self, request: ProcessRequest) -> ProcessOutput:
        self.requests.append(request)
        return self.fake(request.argv, cwd=request.cwd)
