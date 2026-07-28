"""Suppression ratchet: count every escape hatch in a tree and let the count only shrink.

A suppression comment is a decision to stop a checker from doing its job on one
line. Individually each is often right; collectively they are the only number
that says whether the codebase is getting more or less checked, and nothing in
review shows that number. A ratchet makes it visible and one-directional:
snapshot today's counts into a baseline, then fail any commit that raises one.

Three ceilings apply at once, because each catches a shape the others miss:

* **per code** — `# noqa: TID251` growing from 40 to 41 is a real regression
  even when the repo total falls, and a code-blind total lets a cleanup
  elsewhere pay for it.
* **per package** — a monorepo where one package is well-typed and another is
  not needs separate floors, or the good package's headroom finances the bad
  one's debt.
* **per file** — a global ceiling on any single file, so new suppressions
  cannot pile into one hot spot while the package total stays flat. Files that
  already exceeded it when the ceiling landed are grandfathered at their
  then-current counts and may only shrink.

All four suppression dialects are counted, each under its own key prefix, so
migrating a suppression from one spelling to another can never hide it:

| key                     | comment form                                    |
|-------------------------|-------------------------------------------------|
| `noqa:CODE`             | `x = f()  # noqa: E501`                         |
| `sarj-noqa:CODE`        | `x = f()  # sarj-noqa: SARJ016 — reason`        |
| `pyright:CODE`          | `x = f()  # pyright: ignore[reportAny]`         |
| `type-ignore:CODE`      | `x = f()  # type: ignore[attr-defined]`         |
| `type-ignore`           | `x = f()  # type: ignore`  (bare)               |
| `file-noqa:CODE`        | `# ruff: noqa: E501` at file level              |
| `file-noqa:<blanket>`   | `# ruff: noqa` at file level, no codes          |
| `file-pyright:RULE`     | `# pyright: reportAny=false` file header        |

Every occurrence on a line counts, not just the first: `f()  # noqa: A  # noqa: B`
is two suppressions.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
import re
from typing import TYPE_CHECKING, Final


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path


DEFAULT_EXCLUDED_DIR_NAMES: Final = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "site-packages",
        "venv",
    }
)

DEFAULT_PER_FILE_CEILING: Final = 10

_NOQA_RE: Final = re.compile(r"#\s*noqa:\s*([A-Z][A-Z0-9]+(?:\s*,\s*[A-Z][A-Z0-9]+)*)")
_SARJ_NOQA_RE: Final = re.compile(r"#\s*sarj-noqa:\s*(SARJ\d+(?:\s*,\s*SARJ\d+)*)", re.IGNORECASE)
_PYRIGHT_IGNORE_RE: Final = re.compile(r"#\s*pyright:\s*ignore\[([^\]]+)\]")
_TYPE_IGNORE_RE: Final = re.compile(r"#\s*type:\s*ignore(?:\[([^\]]+)\])?")
_FILE_NOQA_RE: Final = re.compile(
    r"^\s*#\s*ruff:\s*noqa(?::\s*([A-Z][A-Z0-9]+(?:\s*,\s*[A-Z][A-Z0-9]+)*))?", re.IGNORECASE
)
_FILE_PYRIGHT_RE: Final = re.compile(r"^\s*#\s*pyright:\s*(?!ignore\b)")
_FILE_PYRIGHT_RULE_RE: Final = re.compile(r"([A-Za-z]\w*)\s*=\s*false")

_BLANKET_KEY: Final = "file-noqa:<blanket>"
_BARE_TYPE_IGNORE_KEY: Final = "type-ignore"


@dataclass(frozen=True, slots=True)
class Measurement:
    """What one scan of the tree found."""

    codes: Counter[str]
    packages: Counter[str]
    files: dict[str, int]

    @property
    def total(self) -> int:
        """Total suppressions counted.

        Returns:
            The sum over every code key.

        """
        return sum(self.codes.values())


@dataclass(frozen=True, slots=True)
class Baseline:
    """The checked-in ceilings. A key absent from `codes`/`packages` has a ceiling of 0."""

    codes: dict[str, int] = field(default_factory=dict[str, int])
    packages: dict[str, int] = field(default_factory=dict[str, int])
    per_file_ceiling: int = DEFAULT_PER_FILE_CEILING
    file_exceptions: dict[str, int] = field(default_factory=dict[str, int])


@dataclass(frozen=True, slots=True)
class Failure:
    """One ceiling that the measurement exceeded."""

    dimension: str
    key: str
    ceiling: int
    actual: int

    def format(self) -> str:
        """Render the failure with the remediation for its dimension.

        Returns:
            A multi-sentence message naming the key, both numbers and the fix.

        """
        head = f"FAIL[{self.dimension}] {self.key}: {self.actual} suppressions, ceiling {self.ceiling}."
        return f"{head} {_REMEDIATION[self.dimension]}"


_REMEDIATION: Final[dict[str, str]] = {
    "code": (
        "Fix the finding instead of suppressing it. If this suppression guards a "
        "genuine boundary, retire one elsewhere, or get the ceiling raise reviewed "
        "explicitly (`--update --allow-increase`)."
    ),
    "package": (
        "This package may not take on more suppression debt. Burn one down here, "
        "or get the ceiling raise reviewed explicitly (`--update --allow-increase`)."
    ),
    "file": (
        "Suppressions are piling into one file. Spread-out fixes beat a hot spot: "
        "burn one down here, or grandfather the file explicitly in the baseline's "
        "`files.exceptions`."
    ),
}


def measure(
    root: Path,
    packages: Iterable[str],
    *,
    excluded_dir_names: frozenset[str] = DEFAULT_EXCLUDED_DIR_NAMES,
    excluded_subtrees: Iterable[str] = (),
) -> Measurement:
    """Count every suppression under `root`, bucketed by code, package and file.

    `packages` are paths relative to `root`; a package that does not exist
    contributes 0 rather than raising, so a baseline outliving a rename fails
    loudly on the package's disappearance rather than crashing.

    Returns:
        The measurement.

    """
    codes: Counter[str] = Counter()
    package_counts: Counter[str] = Counter()
    files: dict[str, int] = {}
    excluded = tuple(excluded_subtrees)
    for package in packages:
        package_counts[package] = 0
        for path in _python_files(root / package, excluded_dir_names):
            relative = path.relative_to(root).as_posix()
            if any(relative.startswith(subtree) for subtree in excluded):
                continue
            found = count_source(_read(path))
            if not found:
                continue
            codes.update(found)
            n = sum(found.values())
            package_counts[package] += n
            files[relative] = n
    return Measurement(codes=codes, packages=package_counts, files=files)


def count_source(source: str) -> Counter[str]:
    """Count the suppressions in one file's text, keyed by dialect and code.

    Returns:
        The per-key counts for this file.

    """
    counts: Counter[str] = Counter()
    for line in source.splitlines():
        _count_line(line, counts)
    return counts


def gate(measurement: Measurement, baseline: Baseline) -> list[Failure]:
    """Compare a measurement against the baseline's three ceilings.

    Returns:
        Every exceeded ceiling, ordered code → package → file, each dimension
        sorted by key so output is stable across runs.

    """
    failures = [
        Failure(dimension="code", key=key, ceiling=c, actual=n)
        for key, n in sorted(measurement.codes.items())
        if n > (c := baseline.codes.get(key, 0))
    ]
    failures += [
        Failure(dimension="package", key=key, ceiling=c, actual=n)
        for key, n in sorted(measurement.packages.items())
        if n > (c := baseline.packages.get(key, 0))
    ]
    failures += [
        Failure(dimension="file", key=key, ceiling=ceiling, actual=n)
        for key, n in sorted(measurement.files.items())
        if n > (ceiling := baseline.file_exceptions.get(key, baseline.per_file_ceiling))
    ]
    return failures


def improvements(measurement: Measurement, baseline: Baseline) -> dict[str, tuple[int, int]]:
    """Find the code keys now below their ceiling — the wins worth locking in.

    Returns:
        `{key: (ceiling, actual)}` for every code that shrank, including codes
        that reached zero and are no longer present at all.

    """
    out: dict[str, tuple[int, int]] = {}
    for key, ceiling in baseline.codes.items():
        actual = measurement.codes.get(key, 0)
        if actual < ceiling:
            out[key] = (ceiling, actual)
    return out


def seed(measurement: Measurement, baseline: Baseline) -> Baseline:
    """Build the baseline that `--update` would write from a measurement.

    Per-file grandfathering is preserved only where it is still needed: a file
    that dropped to or below the global ceiling loses its exception, so the
    allowance cannot outlive the debt it was granted for.

    Returns:
        The re-seeded baseline.

    """
    exceptions = {path: n for path, n in measurement.files.items() if n > baseline.per_file_ceiling}
    return Baseline(
        codes=dict(sorted(measurement.codes.items())),
        packages=dict(sorted(measurement.packages.items())),
        per_file_ceiling=baseline.per_file_ceiling,
        file_exceptions=dict(sorted(exceptions.items())),
    )


def load_baseline(path: Path) -> Baseline:
    """Read a baseline JSON file, ignoring entries of the wrong shape.

    A hand-edited baseline degrades to "not baselined" (ceiling 0) for the
    malformed entry rather than crashing the gate or silently passing.

    Returns:
        The parsed baseline.

    """
    raw: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; every read below narrows
        path.read_text(encoding="utf-8")
    )
    files = _get(raw, "files")
    ceiling = _get(files, "per_file_ceiling")
    return Baseline(
        codes=_int_map(_get(raw, "codes")),
        packages=_int_map(_get(raw, "packages")),
        per_file_ceiling=ceiling
        if isinstance(ceiling, int) and not isinstance(ceiling, bool)
        else DEFAULT_PER_FILE_CEILING,
        file_exceptions=_int_map(_get(files, "exceptions")),
    )


def _get(mapping: object, key: str) -> object:
    """Read one key out of a value that may or may not be a JSON object.

    Returns:
        The value at `key`, or None when `mapping` is not an object or lacks it.

    """
    if not isinstance(mapping, dict):
        return None
    return mapping.get(key)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] — json leaves are Any


def dump_baseline(baseline: Baseline, packages: Iterable[str]) -> str:
    """Render a baseline as the JSON text to write.

    Returns:
        The serialized baseline, newline-terminated.

    """
    payload = {
        "_comment": (
            "Suppression ceilings, written by `sarj-ratchet --update`. Counts may "
            "only go DOWN: `codes` is per dialect+code, `packages` is per "
            "top-level package, `files.per_file_ceiling` caps any single file "
            "with `files.exceptions` grandfathering the pre-existing hot spots. "
            "Raising a ceiling requires `--update --allow-increase` and review."
        ),
        "packages_scanned": sorted(packages),
        "codes": baseline.codes,
        "packages": baseline.packages,
        "files": {
            "per_file_ceiling": baseline.per_file_ceiling,
            "exceptions": baseline.file_exceptions,
        },
    }
    return json.dumps(payload, indent=2) + "\n"


def discover_packages(root: Path, excluded_dir_names: frozenset[str] = DEFAULT_EXCLUDED_DIR_NAMES) -> list[str]:
    """List the top-level directories under `root` that contain Python files.

    Used when neither `--package` nor a baseline names the packages, so the
    first run needs no configuration.

    Returns:
        The package names, sorted.

    """
    return sorted(
        name
        for child in root.iterdir()
        if (name := child.name) not in excluded_dir_names
        and not name.startswith(".")
        and child.is_dir()
        and any(True for _ in _python_files(child, excluded_dir_names))
    )


def _int_map(value: object) -> dict[str, int]:
    """Narrow a JSON value to `{str: int}`, dropping anything else.

    Returns:
        The well-formed entries only.

    """
    if not isinstance(value, dict):
        return {}
    return {
        key: count
        for key, count in value.items()  # pyright: ignore[reportUnknownVariableType] — json leaves are Any; narrowed in the guard
        if isinstance(key, str) and isinstance(count, int) and not isinstance(count, bool)
    }


def _python_files(root: Path, excluded_dir_names: frozenset[str]) -> Iterator[Path]:
    """Yield every `.py` file under `root`, skipping excluded directories.

    Yields:
        Each Python file path.

    """
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.py")):
        if not excluded_dir_names.intersection(path.parts):
            yield path


def _read(path: Path) -> str:
    """Read a source file, treating undecodable bytes as empty.

    Returns:
        The file text, or `""` when it cannot be decoded.

    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError, OSError:
        return ""


def _count_line(line: str, counts: Counter[str]) -> None:
    """Add one line's suppressions to `counts`.

    The two file-level forms return early: a `# ruff: noqa: X` header is not
    also an inline `noqa`, and double-counting it would make the two key
    prefixes overlap.
    """
    file_noqa = _FILE_NOQA_RE.match(line)
    if file_noqa:
        listed = file_noqa.group(1)
        if listed:
            counts.update(f"file-noqa:{code.strip().upper()}" for code in listed.split(","))
        else:
            counts[_BLANKET_KEY] += 1
        return
    if _FILE_PYRIGHT_RE.match(line):
        rules: list[str] = _FILE_PYRIGHT_RULE_RE.findall(line)
        counts.update(f"file-pyright:{rule}" for rule in rules)
        return
    for pattern, prefix in (
        (_NOQA_RE, "noqa:"),
        (_SARJ_NOQA_RE, "sarj-noqa:"),
        (_PYRIGHT_IGNORE_RE, "pyright:"),
    ):
        for match in pattern.finditer(line):
            counts.update(f"{prefix}{code.strip()}" for code in match.group(1).split(","))
    for match in _TYPE_IGNORE_RE.finditer(line):
        listed = match.group(1)
        if listed:
            counts.update(f"type-ignore:{code.strip()}" for code in listed.split(","))
        else:
            counts[_BARE_TYPE_IGNORE_KEY] += 1
