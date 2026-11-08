from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING, Final

from sarj_standards.libs.json_boundary import parse_unique_json

from .result_cache import UnknownInputsError, executable_identity, file_identity


if TYPE_CHECKING:
    from collections.abc import Iterator


# Enumerates every file `terraform validate` and TFLint can read for one root
# module: each module directory's files, the local and installed module closure,
# the initialized `.terraform` state, and every path a file function can reach.
# A file-function argument without a static directory prefix makes the inputs
# unknown, so that project always runs.
_FILE_FUNCTION: Final = re.compile(
    r"\b(file|fileexists|fileset|filebase64|filebase64sha256|filebase64sha512|filemd5|filesha1|filesha256|"
    r"filesha512|templatefile)\s*\("
)
_LOCAL_SOURCE: Final = re.compile(r"""(?m)^\s*"?source"?\s*[=:]\s*"(\.\.?/[^"]*)\"""")
_LOCALS_BLOCK: Final = re.compile(r"(?m)^locals\s*\{[ \t]*$")
_LOCAL_REFERENCE: Final = re.compile(r"local\.([A-Za-z_][A-Za-z0-9_-]*)")
_MAX_FILES: Final = 20_000
_MAX_DEPTH: Final = 8
_SOURCE_SUFFIXES: Final = (".tf", ".tf.json")


type _Segment = tuple[bool, str]


@dataclass(frozen=True, slots=True)
class _Template:
    segments: tuple[_Segment, ...]
    end: int


@dataclass(frozen=True, slots=True)
class _Prefix:
    text: str
    complete: bool


class _Inputs:
    def __init__(self, root: Path, project: Path) -> None:
        self.root = root
        self.project = project
        self.files: dict[str, str] = {}
        self.modules: set[Path] = set()
        self.scanned: set[Path] = set()

    def record(self, path: Path) -> None:
        relative = self.relative(path)
        if relative in self.files:
            return
        if len(self.files) >= _MAX_FILES:
            msg = "Terraform inputs exceed the enumerable file limit"
            raise UnknownInputsError(msg)
        self.files[relative] = "directory" if path.is_dir() and not path.is_symlink() else file_identity(path)

    def record_tree(self, directory: Path, *, sized: Path | None = None) -> None:
        self.record(directory)
        if not directory.is_dir() or directory.is_symlink():
            return
        for current, directories, names in os.walk(directory, followlinks=False):
            base = Path(current)
            directories.sort()
            for name in directories:
                self.record(base / name)
            for name in sorted(names):
                path = base / name
                if sized is not None and path.is_relative_to(sized) and not path.is_symlink():
                    # Provider binaries are pinned by the lock file; record them by size.
                    self.files.setdefault(self.relative(path), f"size={path.stat().st_size}")
                else:
                    self.record(path)

    def relative(self, path: Path) -> str:
        absolute = Path(os.path.normpath(path if path.is_absolute() else self.project / path))
        try:
            return absolute.relative_to(self.root).as_posix()
        except ValueError:
            msg = f"Terraform reads a path outside the repository: {path}"
            raise UnknownInputsError(msg) from None


def project_inputs(root: Path, project: Path) -> tuple[str, ...]:
    root = root.resolve()
    project = project.resolve()
    inputs = _Inputs(root, project)
    state = project / ".terraform"
    inputs.record_tree(state, sized=state / "providers")
    inputs.record_tree(project / ".tflint.d")
    pending = [project, *_installed_modules(project, state)]
    while pending:
        directory = Path(os.path.normpath(pending.pop()))
        if directory in inputs.modules:
            continue
        inputs.modules.add(directory)
        inputs.record(directory)
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            inputs.record(path)
            if path.is_file() and path.name.endswith(_SOURCE_SUFFIXES):
                text = path.read_text(encoding="utf-8")
                pending.extend(directory / match[1] for match in _LOCAL_SOURCE.finditer(text))
                _scan(inputs, text, directory, depth=0)
    return tuple(f"terraform-input={name}:{identity}" for name, identity in sorted(inputs.files.items()))


def tflint_plugin_inputs() -> Iterator[str]:
    configured = os.environ.get("TFLINT_PLUGIN_DIR")  # ruff: ignore[banned-api] -- TFLint reads its plugin directory from here.
    directory = Path(configured) if configured else Path.home() / ".tflint.d" / "plugins"
    if not directory.is_dir():
        yield "tflint-plugins=missing"
        return
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        yield f"tflint-plugin={path}:{executable_identity(path)}"


def _installed_modules(project: Path, state: Path) -> list[Path]:
    manifest = state / "modules" / "modules.json"
    if not manifest.is_file():
        return []
    payload = parse_unique_json(manifest.read_text(encoding="utf-8"))
    modules = payload.get("Modules") if isinstance(payload, dict) else None
    if not isinstance(modules, list):
        msg = "Terraform module manifest has no module list"
        raise UnknownInputsError(msg)
    directories: list[Path] = []
    for module in modules:
        directory = module.get("Dir") if isinstance(module, dict) else None
        if not isinstance(directory, str):
            msg = "Terraform module manifest entry has no directory"
            raise UnknownInputsError(msg)
        directories.append(project / directory)
    return directories


def _scan(inputs: _Inputs, text: str, module: Path, *, depth: int) -> None:
    if depth > _MAX_DEPTH:
        msg = "Terraform templates nest beyond the enumerable depth"
        raise UnknownInputsError(msg)
    for match in _FILE_FUNCTION.finditer(text):
        prefix = _static_prefix(_argument(text, match.end()), module, inputs, depth=depth)
        if not prefix.text:
            msg = f"{match[1]}() reads a computed path"
            raise UnknownInputsError(msg)
        _record_call(inputs, match[1], prefix, module, depth=depth)


def _record_call(inputs: _Inputs, function: str, prefix: _Prefix, module: Path, *, depth: int) -> None:
    path = Path(prefix.text) if Path(prefix.text).is_absolute() else inputs.project / prefix.text
    if prefix.complete and function != "fileset":
        inputs.record(path)
        if function == "templatefile" and path.is_file():
            _scan_template(inputs, path, module, depth=depth)
        return
    directory = path if prefix.complete or prefix.text.endswith("/") else path.parent
    inputs.record_tree(directory)
    if function == "templatefile" and directory.is_dir():
        for template in sorted(directory.rglob("*")):
            if template.is_file():
                _scan_template(inputs, template, module, depth=depth)


def _scan_template(inputs: _Inputs, path: Path, module: Path, *, depth: int) -> None:
    resolved = Path(os.path.normpath(path))
    if resolved in inputs.scanned:
        return
    inputs.scanned.add(resolved)
    try:
        text = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        msg = f"Terraform template is not text: {resolved}"
        raise UnknownInputsError(msg) from error
    _scan(inputs, text, module, depth=depth + 1)


def _argument(text: str, start: int) -> tuple[_Segment, ...]:
    index = start
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    if text.startswith('"', index):
        return _template(text, index + 1).segments
    reference = _LOCAL_REFERENCE.match(text, index)
    if reference is not None and not re.match(r"[\w.\[(]", text[reference.end() : reference.end() + 1]):
        return ((False, reference[0]),)
    msg = "file function argument is not a string or local value"
    raise UnknownInputsError(msg)


def _template(text: str, start: int) -> _Template:
    # Splits one quoted HCL template into literal and interpolation segments.
    segments: list[_Segment] = []
    literal: list[str] = []
    index = start
    while index < len(text):
        character = text[index]
        if character == '"':
            segments.append((True, "".join(literal)))
            return _Template(tuple(segments), index + 1)
        if character == "\\":
            if index + 1 >= len(text):
                break
            literal.append(json.loads(f'"{text[index : index + 2]}"') if text[index + 1] in '"\\/bfnrt' else "\x00")
            index += 2
            continue
        if text.startswith("$${", index) or text.startswith("%%{", index):
            literal.append(text[index + 1 : index + 3])
            index += 3
            continue
        if text.startswith(("${", "%{"), index):
            segments.append((True, "".join(literal)))
            literal = []
            end = _interpolation_end(text, index + 2)
            segments.append((False, text[index + 2 : end]))
            index = end + 1
            continue
        if character == "\n":
            break
        literal.append(character)
        index += 1
    msg = "unterminated Terraform string"
    raise UnknownInputsError(msg)


def _interpolation_end(text: str, start: int) -> int:
    depth = 0
    index = start
    while index < len(text):
        character = text[index]
        if character == '"':
            index = _template(text, index + 1).end
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            if depth == 0:
                return index
            depth -= 1
        index += 1
    msg = "unterminated Terraform interpolation"
    raise UnknownInputsError(msg)


def _static_prefix(segments: tuple[_Segment, ...], module: Path, inputs: _Inputs, *, depth: int) -> _Prefix:
    prefix = ""
    for is_literal, value in segments:
        if is_literal:
            if "\x00" in value:
                return _Prefix(prefix, complete=False)
            prefix += value
            continue
        expression = value.strip()
        if expression == "path.module":
            prefix += str(module)
        elif expression in {"path.root", "path.cwd"}:
            prefix += str(inputs.project)
        elif (reference := _LOCAL_REFERENCE.fullmatch(expression)) is not None and depth <= _MAX_DEPTH:
            local = _static_prefix(_local_value(module, reference[1]), module, inputs, depth=depth + 1)
            prefix += local.text
            if not local.complete:
                return _Prefix(prefix, complete=False)
        else:
            return _Prefix(prefix, complete=False)
    return _Prefix(prefix, complete=True)


def _local_value(module: Path, name: str) -> tuple[_Segment, ...]:
    # A local resolves only when one module file assigns it exactly one single-line string.
    assignment = re.compile(rf'(?m)^\s*{re.escape(name)}\s*=\s*"')
    found: list[tuple[_Segment, ...]] = []
    for path in sorted(module.glob("*.tf")):
        text = path.read_text(encoding="utf-8")
        for block in _LOCALS_BLOCK.finditer(text):
            end = text.find("\n}", block.end())
            if end < 0:
                msg = f"unterminated locals block in {path.name}"
                raise UnknownInputsError(msg)
            for match in assignment.finditer(text, block.end(), end):
                template = _template(text, match.end())
                if text[template.end : text.find("\n", template.end)].strip():
                    msg = f"local.{name} is not a plain string"
                    raise UnknownInputsError(msg)
                found.append(template.segments)
    if len(found) != 1:
        msg = f"local.{name} has no single static string value"
        raise UnknownInputsError(msg)
    return found[0]
