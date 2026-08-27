from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from io import StringIO
import json
import re
import tokenize
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, NamedTuple, TypeGuard


if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
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


class Improvement(NamedTuple):
    previous: int
    current: int


DEFAULT_PER_FILE_CEILING: Final = 10
BASELINE_SCHEMA_VERSION: Final = 1

_RUFF_SELECTOR: Final = r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*"
_RUFF_SELECTOR_LIST: Final = rf"({_RUFF_SELECTOR}(?:\s*,\s*{_RUFF_SELECTOR})*)"
_NOQA_RE: Final = re.compile(rf"#\s*noqa(?::\s*{_RUFF_SELECTOR_LIST})?", re.IGNORECASE)
_RUFF_IGNORE_RE: Final = re.compile(rf"#\s*ruff:\s*ignore\s*\[{_RUFF_SELECTOR_LIST}(?:\s*,)?\s*\]", re.IGNORECASE)
_RUFF_FILE_IGNORE_RE: Final = re.compile(
    rf"^#\s*ruff:\s*file-ignore\s*\[{_RUFF_SELECTOR_LIST}(?:\s*,)?\s*\]", re.IGNORECASE
)
_RUFF_DISABLE_RE: Final = re.compile(rf"^#\s*ruff:\s*disable\s*\[{_RUFF_SELECTOR_LIST}(?:\s*,)?\s*\]", re.IGNORECASE)
_SARJ_NOQA_RE: Final = re.compile(r"#\s*sarj-noqa:\s*(SARJ\d+(?:\s*,\s*SARJ\d+)*)", re.IGNORECASE)
_PYRIGHT_IGNORE_RE: Final = re.compile(r"#\s*pyright:\s*ignore\[([^\]]+)\]")
_TYPE_IGNORE_RE: Final = re.compile(r"#\s*type:\s*ignore(?:\[([^\]]+)\])?")
_FILE_NOQA_RE: Final = re.compile(rf"^#\s*ruff:\s*noqa(?::\s*{_RUFF_SELECTOR_LIST})?", re.IGNORECASE)
_FLAKE8_FILE_NOQA_RE: Final = re.compile(r"^#\s*flake8:\s*noqa\b", re.IGNORECASE)
_FILE_PYRIGHT_RE: Final = re.compile(r"^#\s*pyright:(?!\s*ignore\b)\s*")
_FILE_PYRIGHT_RULE_RE: Final = re.compile(r"([A-Za-z]\w*)\s*=\s*false")

_BLANKET_KEY: Final = "file-noqa:<blanket>"
_INLINE_BLANKET_KEY: Final = "noqa:<blanket>"
_FLAKE8_BLANKET_KEY: Final = "file-noqa:<blanket>"
_BARE_PYRIGHT_IGNORE_KEY: Final = "pyright:<blanket>"
_BARE_TYPE_IGNORE_KEY: Final = "type-ignore"


@dataclass(frozen=True, slots=True)
class Measurement:
    codes: Counter[str]
    packages: Counter[str]
    files: dict[str, int]

    @property
    def total(self) -> int:
        """Total suppressions counted."""
        return sum(self.codes.values())


@dataclass(frozen=True, slots=True)
class Baseline:
    codes: dict[str, int] = field(default_factory=dict[str, int])
    packages: dict[str, int] = field(default_factory=dict[str, int])
    per_file_ceiling: int = DEFAULT_PER_FILE_CEILING
    file_exceptions: dict[str, int] = field(default_factory=dict[str, int])
    excluded_subtrees: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Failure:
    dimension: str
    key: str
    ceiling: int
    actual: int

    def format(self) -> str:
        head = f"FAIL[{self.dimension}] {self.key}: {self.actual} suppressions, ceiling {self.ceiling}."
        return f"{head} {_REMEDIATION[self.dimension]}"


_REMEDIATION: Final[Mapping[str, str]] = MappingProxyType(
    {
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
)


def measure(
    root: Path,
    packages: Iterable[str],
    *,
    excluded_dir_names: frozenset[str] = DEFAULT_EXCLUDED_DIR_NAMES,
    excluded_subtrees: Iterable[str] = (),
    ruff_aliases: Mapping[str, str] | None = None,
) -> Measurement:
    codes: Counter[str] = Counter()
    package_counts: Counter[str] = Counter()
    files: dict[str, int] = {}
    excluded = tuple(_normalized_subtree(value) for value in excluded_subtrees)
    for package in packages:
        package_counts[package] = 0
        for path in _python_files(root / package, excluded_dir_names):
            relative = path.relative_to(root).as_posix()
            if any(_inside_subtree(relative, subtree) for subtree in excluded):
                continue
            found = count_source(_read(path), ruff_aliases=ruff_aliases)
            if not found:
                continue
            codes.update(found)
            n = sum(found.values())
            package_counts[package] += n
            files[relative] = n
    return Measurement(codes=codes, packages=package_counts, files=files)


def count_source(source: str, *, ruff_aliases: Mapping[str, str] | None = None) -> Counter[str]:
    counts: Counter[str] = Counter()
    lines = source.splitlines()
    for token in tokenize.generate_tokens(StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        line = lines[token.start[0] - 1] if token.start[0] <= len(lines) else ""
        standalone = not line[: token.start[1]].strip()
        _count_comment(token.string, counts, standalone=standalone, ruff_aliases=ruff_aliases)
    return counts


def gate(measurement: Measurement, baseline: Baseline) -> list[Failure]:
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


def improvements(measurement: Measurement, baseline: Baseline) -> dict[str, Improvement]:
    out: dict[str, Improvement] = {}
    for key, ceiling in baseline.codes.items():
        actual = measurement.codes.get(key, 0)
        if actual < ceiling:
            out[key] = Improvement(ceiling, actual)
    return out


def seed(measurement: Measurement, baseline: Baseline) -> Baseline:
    # Recompute exceptions so a file loses grandfathering as soon as it reaches the ceiling.
    exceptions = {path: n for path, n in measurement.files.items() if n > baseline.per_file_ceiling}
    return Baseline(
        codes=dict(sorted(measurement.codes.items())),
        packages=dict(sorted(measurement.packages.items())),
        per_file_ceiling=baseline.per_file_ceiling,
        file_exceptions=dict(sorted(exceptions.items())),
        excluded_subtrees=baseline.excluded_subtrees,
    )


def load_baseline(path: Path) -> Baseline:
    raw: object = json.loads(  # pyright: ignore[reportAny] — json.loads is an untyped stdlib boundary; every read below narrows
        path.read_text(encoding="utf-8")
    )
    schema = _get(raw, "schema_version")
    if schema is not None and schema != BASELINE_SCHEMA_VERSION:
        msg = f"unsupported suppression baseline schema_version: {schema!r}"
        raise ValueError(msg)
    files = _get(raw, "files")
    ceiling = _get(files, "per_file_ceiling")
    return Baseline(
        codes=_int_map(_get(raw, "codes")),
        packages=_int_map(_get(raw, "packages")),
        per_file_ceiling=ceiling
        if isinstance(ceiling, int) and not isinstance(ceiling, bool)
        else DEFAULT_PER_FILE_CEILING,
        file_exceptions=_int_map(_get(files, "exceptions")),
        excluded_subtrees=_string_tuple(_get(raw, "excluded_subtrees")),
    )


def _get(mapping: object, key: str) -> object:
    if not isinstance(mapping, dict):
        return None
    return mapping.get(key)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] — json leaves are Any


def dump_baseline(baseline: Baseline, packages: Iterable[str]) -> str:
    payload = {
        "schema_version": BASELINE_SCHEMA_VERSION,
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
        "excluded_subtrees": list(baseline.excluded_subtrees),
        "files": {
            "per_file_ceiling": baseline.per_file_ceiling,
            "exceptions": baseline.file_exceptions,
        },
    }
    return json.dumps(payload, indent=2) + "\n"


def discover_packages(root: Path, excluded_dir_names: frozenset[str] = DEFAULT_EXCLUDED_DIR_NAMES) -> list[str]:
    return sorted(
        name
        for child in root.iterdir()
        if (name := child.name) not in excluded_dir_names
        and not name.startswith(".")
        and child.is_dir()
        and any(True for _ in _python_files(child, excluded_dir_names))
    )


def _int_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        key: count
        for key, count in value.items()  # pyright: ignore[reportUnknownVariableType] — json leaves are Any; narrowed in the guard
        if isinstance(key, str) and isinstance(count, int) and not isinstance(count, bool)
    }


def _string_tuple(value: object) -> tuple[str, ...]:
    if not _is_object_list(value):
        return ()
    items: list[str] = []
    for index in range(len(value)):
        item: object = value[index]
        if isinstance(item, str) and item:
            items.append(item)
    return tuple(sorted(items))


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _normalized_subtree(value: str) -> str:
    return value.strip("/")


def _inside_subtree(relative: str, subtree: str) -> bool:
    return relative == subtree or relative.startswith(f"{subtree}/")


def _python_files(root: Path, excluded_dir_names: frozenset[str]) -> Iterator[Path]:
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.py")):
        if not excluded_dir_names.intersection(path.parts):
            yield path


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError, OSError:
        return ""


def _count_line(line: str, counts: Counter[str]) -> None:
    for token in tokenize.generate_tokens(StringIO(line).readline):
        if token.type == tokenize.COMMENT:
            _count_comment(
                token.string,
                counts,
                standalone=not line[: token.start[1]].strip(),
                ruff_aliases=None,
            )


def _count_comment(
    comment: str,
    counts: Counter[str],
    *,
    standalone: bool,
    ruff_aliases: Mapping[str, str] | None,
) -> None:
    if standalone and (file_ignore := _RUFF_FILE_IGNORE_RE.match(comment)):
        counts.update(
            f"file-noqa:{_normalized_ruff_selector(code, ruff_aliases)}" for code in file_ignore.group(1).split(",")
        )
        return
    if standalone and (file_noqa := _FILE_NOQA_RE.match(comment)):
        listed = file_noqa.group(1)
        if listed:
            counts.update(f"file-noqa:{_normalized_ruff_selector(code, ruff_aliases)}" for code in listed.split(","))
        else:
            counts[_BLANKET_KEY] += 1
        return
    if standalone and _FLAKE8_FILE_NOQA_RE.match(comment):
        counts[_FLAKE8_BLANKET_KEY] += 1
        return
    if standalone and (disabled := _RUFF_DISABLE_RE.match(comment)):
        counts.update(
            f"ruff-range:{_normalized_ruff_selector(code, ruff_aliases)}" for code in disabled.group(1).split(",")
        )
        return
    if standalone and _FILE_PYRIGHT_RE.match(comment):
        rules: list[str] = _FILE_PYRIGHT_RULE_RE.findall(comment)
        counts.update(f"file-pyright:{rule}" for rule in rules)
        return
    for match in _NOQA_RE.finditer(comment):
        listed = match.group(1)
        if listed:
            counts.update(f"noqa:{_normalized_ruff_selector(code, ruff_aliases)}" for code in listed.split(","))
        else:
            counts[_INLINE_BLANKET_KEY] += 1
    for match in _RUFF_IGNORE_RE.finditer(comment):
        prefix = "standalone-noqa:" if standalone else "noqa:"
        counts.update(f"{prefix}{_normalized_ruff_selector(code, ruff_aliases)}" for code in match.group(1).split(","))
    for match in _SARJ_NOQA_RE.finditer(comment):
        counts.update(f"sarj-noqa:{code.strip().upper()}" for code in match.group(1).split(","))
    for match in _PYRIGHT_IGNORE_RE.finditer(comment):
        counts.update(f"pyright:{code.strip()}" for code in match.group(1).split(","))
    if re.search(r"#\s*pyright:\s*ignore\b(?!\s*\[)", comment):
        counts[_BARE_PYRIGHT_IGNORE_KEY] += 1
    for match in _TYPE_IGNORE_RE.finditer(comment):
        listed = match.group(1)
        if listed:
            counts.update(f"type-ignore:{code.strip()}" for code in listed.split(","))
        else:
            counts[_BARE_TYPE_IGNORE_KEY] += 1


def _normalized_ruff_selector(selector: str, aliases: Mapping[str, str] | None) -> str:
    stripped = selector.strip()
    normalized = stripped.upper() if stripped.isupper() else stripped.lower()
    if aliases is None:
        return normalized
    try:
        return aliases[normalized]
    except KeyError as exc:
        msg = f"unknown Ruff suppression selector: {stripped}"
        raise ValueError(msg) from exc
