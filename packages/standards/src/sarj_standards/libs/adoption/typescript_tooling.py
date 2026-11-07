from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from typing import TYPE_CHECKING, Final

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.process import ProcessCapabilities, ToolResolution

from . import lifecycle
from .configs import BIOME_CONFIG_NAMES, OXFMT_ENTRYPOINT, OXLINT_ENTRYPOINT, OXLINT_SUPPRESSIONS


if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from sarj_standards.libs.linting.process import ProcessOutput, ProcessRequest

    from .transaction import FileTransaction


_OXFMT_RC: Final = ".oxfmtrc.json"
_BIOME_FORMATTER: Final = re.compile(r'"formatter"\s*:\s*\{\s*(?P<enabled>"enabled"\s*:\s*true)?')


@dataclass(frozen=True, slots=True)
class OxfmtSeeding:
    writes: tuple[tuple[Path, str], ...] = ()
    deletes: tuple[Path, ...] = ()
    notes: tuple[str, ...] = ()
    #: Seeding needs `oxfmt --migrate`, so it runs after the install.
    deferred: bool = False


class _NeedsOxfmtError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _NoProcesses:
    # Planning never runs tools: a seed that needs `oxfmt --migrate` waits for the install.
    capabilities: ProcessCapabilities = field(default_factory=lambda: ProcessCapabilities(ToolResolution.PROVIDED))

    def run(self, request: ProcessRequest) -> ProcessOutput:
        raise _NeedsOxfmtError(request.argv)


def plan_oxfmt_config(typescript_root: Path) -> OxfmtSeeding:
    # Seed oxfmt.config.mts at planning time when no Prettier or Biome config needs `oxfmt --migrate`.
    from sarj_standards.libs.linting import oxfmt  # ruff: ignore[import-outside-top-level] -- oxfmt imports adoption.lifecycle.

    entrypoint = typescript_root / OXFMT_ENTRYPOINT
    if entrypoint.is_file():
        return OxfmtSeeding()
    try:
        seed = oxfmt.seed_config(typescript_root, runner=_NoProcesses())
    except _NeedsOxfmtError:
        return OxfmtSeeding(
            notes=(f"{OXFMT_ENTRYPOINT} is seeded from the current formatter after the install",), deferred=True
        )
    except ValueError as exc:
        return OxfmtSeeding(notes=(f"write {OXFMT_ENTRYPOINT} by hand: {exc}",))
    deletes = (typescript_root / _OXFMT_RC,) if seed.source == "oxfmt" else ()
    return OxfmtSeeding(((entrypoint, oxfmt.render_config(seed)),), deletes)


def finish(root: Path, typescript_root: Path, files: FileTransaction, *, written: Collection[Path]) -> tuple[str, ...]:
    # The adoption steps that need the installed tools; `written` is what the plan wrote. oxfmt seeds its
    # config from Prettier or Biome when planning could not, and the repository is formatted once with the
    # new config (DECISIONS #7); Oxlint trims bulk suppressions converted from ESLint to the findings it
    # reports. Every file this touches is recorded in `files` so a failed update rolls it back.
    from sarj_standards.libs.linting import oxfmt  # ruff: ignore[import-outside-top-level] -- oxfmt imports adoption.lifecycle.

    notes: list[str] = []
    entrypoint = typescript_root / OXFMT_ENTRYPOINT
    seeded = entrypoint in written
    if not entrypoint.is_file() and plan_oxfmt_config(typescript_root).deferred:
        seed = oxfmt.seed_config(typescript_root)
        notes.extend(f"oxfmt --migrate: {warning}" for warning in seed.warnings)
        _write(files, entrypoint, oxfmt.render_config(seed))
        if seed.source == "biome":
            notes.extend(_disable_biome_formatter(typescript_root, files))
        seeded = True
    if seeded:
        reformatted = _reformat(root, typescript_root, files)
        notes.append(f"oxfmt formatted {reformatted} file(s) once with the seeded {OXFMT_ENTRYPOINT}")
    elif typescript_root / OXLINT_ENTRYPOINT in written:
        _format(root, typescript_root, files, (typescript_root / OXLINT_ENTRYPOINT,))
    # Suppressions converted from ESLint carry upper-bound counts until Oxlint trims them.
    if any(path.name == OXLINT_SUPPRESSIONS for path in written):
        notes.extend(_prune_suppressions(root, typescript_root, files))
    return tuple(notes)


def _reformat(root: Path, typescript_root: Path, files: FileTransaction) -> int:
    from sarj_standards.libs.linting import oxfmt  # ruff: ignore[import-outside-top-level] -- oxfmt imports adoption.lifecycle.

    report = oxfmt.analyze([str(typescript_root)], project=typescript_root, root=root)
    if report.issues:
        msg = "; ".join(issue.message for issue in report.issues)
        raise OSError(msg)
    dirty = sorted({root / diagnostic.location.path for diagnostic in report.diagnostics})
    _format(root, typescript_root, files, dirty)
    return len(dirty)


def _format(root: Path, typescript_root: Path, files: FileTransaction, paths: Sequence[Path]) -> None:
    from sarj_standards.libs.linting import oxfmt  # ruff: ignore[import-outside-top-level] -- oxfmt imports adoption.lifecycle.

    if not paths:
        return
    files.track(*paths)
    _run(oxfmt.write_command([str(path) for path in paths], project=typescript_root, root=root))
    files.mark_written(*paths)


def _disable_biome_formatter(typescript_root: Path, files: FileTransaction) -> tuple[str, ...]:
    # oxfmt owns formatting now; a Biome formatter left on would undo it on every `biome check --write`.
    path = next((typescript_root / name for name in BIOME_CONFIG_NAMES if (typescript_root / name).is_file()), None)
    if path is None:
        return ()
    text = path.read_text(encoding="utf-8")
    edited = _without_biome_formatter(text)
    if edited is None:
        return (f"disable the Biome formatter in {path.name} by hand: oxfmt formats this repository now",)
    if edited == text:
        return ()
    _write(files, path, edited)
    return (f"disabled the Biome formatter in {path.name}; oxfmt formats this repository now",)


def _without_biome_formatter(text: str) -> str | None:
    # Edit the text in place so the rest of the file keeps its layout; the parse proves the edit hit the root key.
    try:
        parsed = parse_json(text)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    formatter = parsed.get("formatter")
    if isinstance(formatter, dict) and formatter.get("enabled") is False:
        return text
    expected = {**parsed, "formatter": {**(formatter if isinstance(formatter, dict) else {}), "enabled": False}}
    candidates = [
        f'{text[: match.start("enabled")]}"enabled": false{text[match.end("enabled") :]}'
        if match.group("enabled")
        else f'{text[: match.end()]}"enabled": false, {text[match.end() :]}'
        for match in _BIOME_FORMATTER.finditer(text)
    ]
    if "formatter" not in parsed and (opening := re.match(r"\s*\{(?P<indent>\s*)", text)) is not None:
        candidates.append(
            f'{text[: opening.end()]}"formatter": {{ "enabled": false }},{opening["indent"]}{text[opening.end() :]}'
        )
    for edited in candidates:
        try:
            if parse_json(edited) == expected:
                return edited
        except ValueError:
            continue
    return None


def _prune_suppressions(root: Path, typescript_root: Path, files: FileTransaction) -> tuple[str, ...]:
    from sarj_standards.libs.linting import (  # ruff: ignore[import-outside-top-level] -- oxlint imports adoption.lifecycle.
        external,
        oxlint,
    )

    notes: list[str] = []
    for command in oxlint.select_oxlint_commands(root, [str(typescript_root)], label="prune").commands:
        ledger = command.cwd / OXLINT_SUPPRESSIONS
        if not ledger.is_file():
            continue
        files.track(ledger)
        with oxlint.selected_config(command, oxlint.OxlintRequest()) as configured:
            request = external.process_request(
                oxlint.with_options(configured.argv, "-f", "json", "--type-aware", "--prune-suppressions"),
                cwd=command.cwd,
            )
            environment = {**request.environment, **oxlint.oxlint_environment(command.cwd, root)}
            output = external.DEFAULT_EXECUTOR.run(replace(request, environment=environment))
        # Exit 1 only reports findings the ledger does not cover; Oxlint still rewrote it.
        if output.returncode not in {0, 1} or not output.stdout.lstrip().startswith("{"):
            detail = output.stderr.strip() or output.stdout.strip()
            msg = f"oxlint --prune-suppressions failed in {command.cwd}: {detail}"
            raise OSError(msg)
        files.mark_written(ledger)
        notes.append(f"pruned {ledger.relative_to(root)} to the findings Oxlint reports")
    return tuple(notes)


def _write(files: FileTransaction, path: Path, contents: str) -> None:
    files.track(path)
    files.write_text(path, contents)


def _run(command: lifecycle.Command) -> None:
    status = lifecycle.execute([command], stdout_to_stderr=True)
    if status:
        msg = f"{command.label} exited with status {status}"
        raise OSError(msg)
