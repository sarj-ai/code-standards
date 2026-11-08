from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Final

from . import lifecycle
from .configs import BIOME_CONFIG_NAMES, OXFMT_ENTRYPOINT, OXLINT_ENTRYPOINT, OXLINT_SUPPRESSIONS


if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from sarj_standards.libs.linting import oxfmt

    from .transaction import FileTransaction


_OXFMT_RC: Final = ".oxfmtrc.json"


@dataclass(frozen=True, slots=True)
class OxfmtSeeding:
    writes: tuple[tuple[Path, str], ...] = ()
    deletes: tuple[Path, ...] = ()
    notes: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def plan_oxfmt_config(typescript_root: Path, sources: Collection[Path] = ()) -> OxfmtSeeding:
    from sarj_standards.libs.linting import oxfmt  # ruff: ignore[import-outside-top-level] -- oxfmt imports adoption.lifecycle.

    entrypoint = typescript_root / OXFMT_ENTRYPOINT
    legacy_names = {*BIOME_CONFIG_NAMES, *oxfmt.PRETTIER_CONFIG_NAMES, ".prettierignore"}
    legacy = tuple(
        sorted(
            {
                *(path for path in sources if path.is_relative_to(typescript_root) and path.name in legacy_names),
                *(typescript_root / name for name in legacy_names if (typescript_root / name).is_file()),
            }
        )
    )
    try:
        seed = _coverage_seed(typescript_root, legacy)
    except (TypeError, ValueError) as exc:
        return OxfmtSeeding(errors=(f"write {OXFMT_ENTRYPOINT} by hand: {exc}",))
    deletes = (*legacy, *((typescript_root / _OXFMT_RC,) if seed.source == "oxfmt" else ()))
    writes = () if oxfmt.matches_shared_config(typescript_root, seed) else ((entrypoint, oxfmt.render_config(seed)),)
    return OxfmtSeeding(writes, deletes, seed.warnings)


def _coverage_seed(typescript_root: Path, legacy: Collection[Path]) -> oxfmt.OxfmtSeed:
    from sarj_standards.libs.linting import oxfmt  # ruff: ignore[import-outside-top-level] -- oxfmt imports adoption.lifecycle.

    seed = oxfmt.seed_config(typescript_root)
    options = dict(seed.options)
    ignores = options.get("ignorePatterns", [])
    if not isinstance(ignores, list):
        msg = "ignorePatterns must be an array"
        raise TypeError(msg)
    for directory in sorted({path.parent for path in legacy if path.parent != typescript_root}):
        nested = oxfmt.seed_config(directory).options.get("ignorePatterns", [])
        if isinstance(nested, list):
            prefix = directory.relative_to(typescript_root).as_posix()
            ignores.extend(_prefixed_ignore(prefix, pattern) for pattern in nested if isinstance(pattern, str))
    if ignores:
        options["ignorePatterns"] = ignores
    return replace(seed, options=options)


def _prefixed_ignore(prefix: str, pattern: str) -> str:
    negate = "!" if pattern.startswith("!") else ""
    return f"{negate}{prefix}/{pattern.removeprefix('!').removeprefix('/')}"


def finish(root: Path, typescript_root: Path, files: FileTransaction, *, written: Collection[Path]) -> tuple[str, ...]:
    # Format once with the shared policy, then trim converted bulk suppressions.
    # Every touched file belongs to the transaction so a failed update rolls it back.
    from sarj_standards.libs.linting import oxfmt  # ruff: ignore[import-outside-top-level] -- oxfmt imports adoption.lifecycle.

    notes: list[str] = []
    entrypoint = typescript_root / OXFMT_ENTRYPOINT
    seeded = entrypoint in written
    if not entrypoint.is_file():
        seed = oxfmt.seed_config(typescript_root)
        notes.extend(seed.warnings)
        _write(files, entrypoint, oxfmt.render_config(seed))
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
