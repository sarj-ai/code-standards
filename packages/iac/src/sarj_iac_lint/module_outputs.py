from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
import posixpath
import re
from typing import Final

from . import _hcl
from .terraform import terraform_blocks


@dataclass(frozen=True, slots=True)
class UnusedModuleOutput:
    path: str
    name: str
    line: int


@dataclass(frozen=True, slots=True)
class _Output:
    declaration: UnusedModuleOutput
    value: str
    dependencies: tuple[str, ...]
    has_preconditions: bool


@dataclass(frozen=True, slots=True)
class _Call:
    target: str | None
    arguments: Mapping[str, str]


@dataclass(slots=True)
class _Module:
    outputs: dict[str, _Output] = field(default_factory=dict)
    locals: dict[str, str] = field(default_factory=dict)
    calls: dict[str, _Call] = field(default_factory=dict)
    sinks: list[str] = field(default_factory=list)
    backend: bool = False


@dataclass(slots=True)
class _Instance:
    key: tuple[str, ...]
    module: str
    parent: _Instance | None
    arguments: Mapping[str, str]
    children: dict[str, _Instance | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Reference:
    kind: str
    name: str
    fields: tuple[str | None, ...]
    start: int
    end: int


_REFERENCE = re.compile(r"^(module|local|var)\.([^\.]+)(?:\.(.*))?$")
_META_ARGUMENTS = frozenset({"source", "version", "providers", "depends_on", "count", "for_each"})
_NON_VALUES = frozenset({"description", "depends_on"})
_ADDRESS_ATTRIBUTES: Final[dict[str, frozenset[str]]] = {
    "moved": frozenset({"from", "to"}),
    "removed": frozenset({"from"}),
    "import": frozenset({"to"}),
}
_NAMED_BLOCKS = frozenset({"module", "variable", "output", "provider", "check"})
_UNNAMED_BLOCKS = frozenset({"locals", "terraform", "moved", "removed", "import"})
_PROJECTING_FUNCTIONS = frozenset({"try", "coalesce", "merge", "sensitive", "nonsensitive"})
_MAX_INSTANCES = 20_000
_MAX_DEPTH = 128


def unused_module_outputs(
    sources: Mapping[str, str],
    *,
    external_outputs: Collection[tuple[str, str]] = (),
    internal_modules: Collection[str] = (),
) -> tuple[UnusedModuleOutput, ...]:
    modules: dict[str, _Module] = {}
    for path, source in sorted(sources.items()):
        if not path.endswith((".tf", ".tf.json")):
            continue
        if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
            message = f"Terraform source is outside the selected repository: {path}"
            raise ValueError(message)
        directory = str(PurePosixPath(path).parent)
        module = modules.setdefault(directory, _Module())
        try:
            blocks = terraform_blocks(PurePosixPath(path), source)
        except ValueError as exc:
            message = f"Cannot establish Terraform consumers in {path}: {exc}"
            raise ValueError(message) from exc
        for block in blocks:
            _collect(module, block, path=path, directory=directory)
    return _Flow(modules, frozenset(external_outputs), frozenset(internal_modules)).unused()


def _collect(module: _Module, block: _hcl.Block, *, path: str, directory: str) -> None:
    _validate_declaration(block, path=path)
    if block.type == "locals":
        _add_locals(module, block, path=path)
    elif block.type == "output":
        _add_output(module, block, path=path)
    elif block.type == "module":
        _add_call(module, block, path=path, directory=directory)
    elif block.type == "variable":
        module.sinks.extend(_validation_expressions(block))
    else:
        module.sinks.extend(_sinks(block))
        if block.type == "terraform":
            module.backend |= _declares_backend(block)


def _validate_declaration(block: _hcl.Block, *, path: str) -> None:
    if block.type in _NAMED_BLOCKS:
        expected = 1
    elif block.type in {"resource", "data"}:
        expected = 2
    elif block.type in _UNNAMED_BLOCKS:
        expected = 0
    else:
        expected = None
    if expected is not None and len(block.labels) != expected:
        message = f"Invalid Terraform {block.type} label count in {path}: expected {expected}"
        raise ValueError(message)
    _validate_attributes(block, path=path)


def _validate_attributes(block: _hcl.Block, *, path: str) -> None:
    seen: set[str] = set()
    for attribute in block.attributes:
        if attribute.name in seen:
            message = f"Duplicate Terraform attribute {attribute.name} in {path}"
            raise ValueError(message)
        seen.add(attribute.name)
    for child in block.blocks:
        _validate_attributes(child, path=path)


def _validation_expressions(block: _hcl.Block) -> tuple[str, ...]:
    expressions = [attribute.value for attribute in block.attributes if attribute.name == "validation"]
    for child in block.blocks:
        expressions.extend(_sinks(child))
    return tuple(expressions)


def _declares_backend(block: _hcl.Block) -> bool:
    return any(child.type in {"backend", "cloud"} for child in block.blocks) or any(
        attribute.name in {"backend", "cloud"} for attribute in block.attributes
    )


def _add_locals(module: _Module, block: _hcl.Block, *, path: str) -> None:
    for attribute in block.attributes:
        if attribute.name in module.locals:
            message = f"Duplicate Terraform local {attribute.name} in {path}"
            raise ValueError(message)
        module.locals[attribute.name] = attribute.value


def _add_output(module: _Module, block: _hcl.Block, *, path: str) -> None:
    name = block.labels[0]
    value = block.attribute("value")
    if name in module.outputs or value is None or not value.value.strip():
        message = f"Ambiguous Terraform output {name} in {path}"
        raise ValueError(message)
    dependencies = tuple(
        attribute.value for attribute in block.attributes if attribute.name not in {*_NON_VALUES, "value"}
    )
    dependencies += tuple(expression for child in block.blocks for expression in _sinks(child))
    module.outputs[name] = _Output(
        UnusedModuleOutput(path, name, block.line),
        value.value,
        dependencies,
        _has_output_preconditions(block),
    )


def _has_output_preconditions(block: _hcl.Block) -> bool:
    if block.child("precondition") is not None:
        return True
    attribute = block.attribute("precondition")
    # JSON nested blocks were canonically encoded by _json_blocks.
    return attribute is not None and attribute.value not in {"null", "[]"}


def _add_call(module: _Module, block: _hcl.Block, *, path: str, directory: str) -> None:
    name = block.labels[0]
    source = block.attribute("source")
    literal = _hcl.literal_string(source.value) if source is not None else None
    if source is None or literal is None or name in module.calls:
        message = f"Cannot establish the source of module {name} in {path}"
        raise ValueError(message)
    target = posixpath.normpath(posixpath.join(directory, literal)) if literal.startswith(("./", "../")) else None
    if target is not None and (target == ".." or target.startswith("../")):
        message = f"Local module {name} in {path} leaves the selected repository"
        raise ValueError(message)
    arguments = {
        attribute.name: attribute.value for attribute in block.attributes if attribute.name not in _META_ARGUMENTS
    }
    module.calls[name] = _Call(target, arguments)
    module.sinks.extend(attribute.value for attribute in block.attributes if attribute.name in {"count", "for_each"})
    module.sinks.extend(
        expression
        for attribute in block.attributes
        if attribute.name == "depends_on"
        for expression in _ordering_values(attribute.value)
    )
    if target is None:
        module.sinks.extend(arguments.values())


def _sinks(block: _hcl.Block) -> tuple[str, ...]:
    excluded = {"depends_on"} | _ADDRESS_ATTRIBUTES.get(block.type, frozenset())
    values = tuple(attribute.value for attribute in block.attributes if attribute.name not in excluded)
    dependencies = tuple(
        expression
        for attribute in block.attributes
        if attribute.name == "depends_on"
        for expression in _ordering_values(attribute.value)
    )
    return values + dependencies + tuple(expression for child in block.blocks for expression in _sinks(child))


def _ordering_values(source: str) -> tuple[str, ...]:
    parts = _hcl.tokens(source)
    return tuple(
        " ".join(parts[reference.start : reference.end])
        for reference in _references(parts)
        if reference.kind != "module" or reference.fields
    )


def _references(parts: tuple[str, ...]) -> tuple[_Reference, ...]:
    result: list[_Reference] = []
    for start, lexeme in enumerate(parts):
        match = _REFERENCE.fullmatch(lexeme)
        if match is None:
            continue
        result.append(_reference_at(parts, start=start, kind=match[1], name=match[2], suffix=match[3] or ""))
    return tuple(result)


def _reference_at(parts: tuple[str, ...], *, start: int, kind: str, name: str, suffix: str) -> _Reference:
    fields: list[str | None] = list(_attributes(suffix))
    end = start + 1
    instance_index = kind == "module" and not fields
    while end < len(parts):
        if parts[end] == "[":
            close = _selector_end(parts, start=end)
            if not instance_index:
                fields.append(_index_key(parts[end + 1 : close - 1]))
            instance_index = False
            end = close
        elif parts[end] == "*" and instance_index:
            instance_index = False
            end += 1
        elif parts[end] == "." and end + 1 < len(parts):
            fields.extend(_attributes(parts[end + 1]))
            end += 2
            instance_index = False
        else:
            break
    return _Reference(kind, name, tuple(fields), start, end)


def _attributes(value: str) -> tuple[str, ...]:
    return tuple(part for part in value.split(".") if part)


def _index_key(parts: tuple[str, ...]) -> str | None:
    return _hcl.literal_string(parts[0]) if len(parts) == 1 else None


def _selector_end(parts: tuple[str, ...], *, start: int) -> int:
    depth = 1
    close = start + 1
    while close < len(parts) and depth:
        depth += (parts[close] == "[") - (parts[close] == "]")
        close += 1
    if depth:
        message = "Unbalanced Terraform reference selector"
        raise ValueError(message)
    return close


def _object_members(parts: tuple[str, ...]) -> dict[str, tuple[str, ...]] | None:
    if parts[:1] != ("{",) or parts[-1:] != ("}",):
        return None
    members: dict[str, tuple[str, ...]] = {}
    index = 1
    while index < len(parts) - 1:
        if parts[index] == ",":
            index += 1
            continue
        key = _hcl.literal_string(parts[index]) or parts[index]
        if index + 1 >= len(parts) - 1 or parts[index + 1] not in {"=", ":"}:
            return None
        start = index + 2
        index = _member_value_end(parts, start=start)
        if key in members or index == start:
            return None
        members[key] = parts[start:index]
    return members


def _member_value_end(parts: tuple[str, ...], *, start: int) -> int:
    index = start
    depth = 0
    conditionals = 0
    while index < len(parts) - 1:
        lexeme = parts[index]
        starts_member = index + 1 < len(parts) - 1 and parts[index + 1] in {"=", ":"}
        if depth == 0 and not conditionals and (lexeme == "," or starts_member):
            break
        if depth == 0 and lexeme == "?":
            conditionals += 1
        elif depth == 0 and lexeme == ":" and conditionals:
            conditionals -= 1
        depth += (lexeme in {"[", "{", "("}) - (lexeme in {"]", "}", ")"})
        index += 1
    return index


class _Flow:
    def __init__(
        self, modules: Mapping[str, _Module], external: frozenset[tuple[str, str]], internal: frozenset[str]
    ) -> None:
        self.modules = modules
        self.external = external
        self.internal = internal
        self.instances: list[_Instance] = []
        self.used: set[tuple[str, str]] = set()
        self.visited: set[tuple[tuple[str, ...], str, str, tuple[str | None, ...]]] = set()
        self.active: set[tuple[tuple[str, ...], str, str]] = set()

    def unused(self) -> tuple[UnusedModuleOutput, ...]:
        if missing := self.internal - self.modules.keys():
            message = f"Closed-world Terraform module contracts name absent modules: {', '.join(sorted(missing))}"
            raise ValueError(message)
        roots = self._roots()
        for path in sorted(roots):
            self._instantiate(path, (path,), None, {}, ())
        if {instance.module for instance in self.instances} != self.modules.keys():
            message = "Terraform local module graph contains an unreachable cycle"
            raise ValueError(message)
        for instance in self.instances:
            module = self.modules[instance.module]
            for expression in module.sinks:
                self._expression(expression, instance)
            for name, output in module.outputs.items():
                if (
                    instance.module in roots
                    or instance.module not in self.internal
                    or (instance.module, name) in self.external
                    or output.has_preconditions
                ):
                    self._output(instance, name, ())
        return tuple(
            output.declaration
            for path, module in sorted(self.modules.items())
            for name, output in sorted(module.outputs.items())
            if path in self.internal and (path, name) not in self.used
        )

    def _roots(self) -> set[str]:
        targets: set[str] = set()
        for module in self.modules.values():
            targets.update(call.target for call in module.calls.values() if call.target is not None)
        missing = targets - self.modules.keys()
        if missing:
            message = f"Local Terraform modules are absent from the selected source tree: {', '.join(sorted(missing))}"
            raise ValueError(message)
        roots = self.modules.keys() - targets
        roots |= {path for path, module in self.modules.items() if module.backend}
        for path, name in self.external:
            if path not in self.modules or name not in self.modules[path].outputs:
                message = f"External Terraform contract does not name an existing output: {path}.{name}"
                raise ValueError(message)
        return roots

    def _instantiate(
        self,
        path: str,
        key: tuple[str, ...],
        parent: _Instance | None,
        arguments: Mapping[str, str],
        ancestors: tuple[str, ...],
    ) -> _Instance:
        if path in ancestors or len(ancestors) >= _MAX_DEPTH or len(self.instances) >= _MAX_INSTANCES:
            message = f"Terraform local module graph is recursive or exceeds its bounded expansion at {path}"
            raise ValueError(message)
        instance = _Instance(key, path, parent, arguments)
        self.instances.append(instance)
        for name, call in self.modules[path].calls.items():
            if call.target is None:
                instance.children[name] = None
            else:
                instance.children[name] = self._instantiate(
                    call.target, (*key, name), instance, call.arguments, (*ancestors, path)
                )
        return instance

    def _expression(self, source: str, instance: _Instance, projection: tuple[str | None, ...] = ()) -> None:
        parts = _hcl.strip_outer_parentheses(_hcl.tokens(source))
        references = _references(parts)
        if references and references[0].start == 0 and references[0].end == len(parts):
            self._reference(references[0], instance, projection)
            for reference in references[1:]:
                self._reference(reference, instance, ())
            return
        if projection and self._project_expression(parts, instance, projection):
            return
        for reference in references:
            self._reference(reference, instance, ())
        for expression in _hcl.template_expressions(source):
            self._expression(expression, instance)

    def _project_expression(
        self, parts: tuple[str, ...], instance: _Instance, projection: tuple[str | None, ...]
    ) -> bool:
        branches = _hcl.conditional_branches(parts)
        if branches:
            condition_length = len(parts) - sum(len(branch) for branch in branches) - 2
            self._expression(" ".join(parts[:condition_length]), instance)
            for branch in branches:
                self._expression(" ".join(branch), instance, projection)
            return True
        selected = projection[0] if projection else None
        members = _object_members(parts) if selected is not None else None
        if members is not None and selected is not None:
            value = members.get(selected)
            if value is not None:
                self._expression(" ".join(value), instance, projection[1:])
            return True
        arguments = (
            _hcl.call_arguments(parts) if projection and parts[:1] and parts[0] in _PROJECTING_FUNCTIONS else None
        )
        if arguments is not None:
            for argument in arguments:
                self._expression(" ".join(argument), instance, projection)
            return True
        return False

    def _reference(self, reference: _Reference, instance: _Instance, projection: tuple[str | None, ...]) -> None:
        fields = (*reference.fields, *projection)
        if reference.kind == "module":
            if reference.name not in instance.children:
                message = f"Terraform reference names an undeclared module: {instance.module}.{reference.name}"
                raise ValueError(message)
            child = instance.children[reference.name]
            if child is None:
                return
            if fields and fields[0] is not None:
                self._output(child, fields[0], fields[1:])
            else:
                for name in self.modules[child.module].outputs:
                    self._output(child, name, ())
        elif reference.kind == "local":
            module = self.modules[instance.module]
            if reference.name not in module.locals:
                message = f"Terraform reference names an undeclared local: {instance.module}.{reference.name}"
                raise ValueError(message)
            self._follow(instance, "local", reference.name, module.locals[reference.name], fields)
        elif instance.parent is not None and reference.name in instance.arguments:
            self._follow(
                instance.parent,
                "input",
                ".".join((*instance.key, reference.name)),
                instance.arguments[reference.name],
                fields,
            )

    def _output(self, instance: _Instance, name: str, projection: tuple[str | None, ...]) -> None:
        output = self.modules[instance.module].outputs.get(name)
        if output is None:
            message = f"Terraform reference names an undeclared output: {instance.module}.{name}"
            raise ValueError(message)
        self.used.add((instance.module, name))
        self._follow(instance, "output", name, output.value, projection)
        if output.dependencies:
            self._follow(instance, "output-metadata", name, " ".join(output.dependencies), ())

    def _follow(
        self, instance: _Instance, kind: str, name: str, expression: str, projection: tuple[str | None, ...]
    ) -> None:
        identity = (instance.key, kind, name)
        key = (*identity, projection)
        if key in self.visited:
            return
        if identity in self.active or len(self.active) >= _MAX_DEPTH:
            message = f"Terraform value references form a cycle at {instance.module}.{name}"
            raise ValueError(message)
        self.active.add(identity)
        self._expression(expression, instance, projection)
        self.active.remove(identity)
        self.visited.add(key)
