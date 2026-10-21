from __future__ import annotations

from enum import StrEnum
from pathlib import Path, PurePosixPath
import re
from typing import TYPE_CHECKING, NamedTuple, final, override

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from sarj_standards.libs.linting.cloudbuild import CloudBuildParseError, compose_documents, mapping_fields, scalar_text
from sarj_standards.libs.linting.devops_programs import WORKFLOW_EXPRESSION_RE
from sarj_standards.libs.linting.shell_ast import ShellSyntaxError, make_shell_parser
from sarj_standards.libs.linting.text_rule_base import Finding, Rule, RuleMeta
from sarj_standards.libs.rules.contracts import (
    AutofixPolicy,
    DefaultLevel,
    ExampleFile,
    ExpectedOutcome,
    Language,
    RuleCategory,
    RuleExample,
)
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping
from sarj_standards.libs.yaml_boundary import mapping_items, sequence_items


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sarj_standards.libs.linting.devops_programs import ShellParser


_CODE = "SARJ316"
_PROJECT = re.compile(r"(?:[a-z][a-z0-9-]{4,28}[a-z0-9]|[0-9]{6,})\Z")
_IMAGE = re.compile(r"(?:[a-z0-9-]+-docker\.pkg\.dev|(?:[a-z0-9-]+\.)?gcr\.io)/([^/]+)/")
_PROJECT_ENV = frozenset({"CLOUDSDK_CORE_PROJECT", "GCLOUD_PROJECT", "GOOGLE_CLOUD_PROJECT"})
_PROJECT_ACTIONS = ("google-github-actions/auth@", "google-github-actions/setup-gcloud@")
_EXCLUDED_PARTS = frozenset({"tests", "test", "fixtures", "__fixtures__", "node_modules", "vendor"})
_CI_SHELL_PARTS = frozenset({"ci", ".github", "cloudbuild"})
_SHELL_JOINERS = str.maketrans({"'": None, '"': None, "\\": None, "\n": None})
_PUBLIC_KEY_COMMAND = ("kms", "keys", "versions", "get-public-key")


class _CommandPurpose(StrEnum):
    TRUST_READ = "trust-read"
    OTHER = "other"
    UNKNOWN = "unknown"


class _Operand(NamedTuple):
    value: str
    line: int


@final
class CiCloudTargetLiteral(Rule):
    id = "ci-cloud-target-literal"
    documentation = RuleMeta(
        code=_CODE,
        default_level=DefaultLevel.WARNING,
        summary="Select CI cloud project targets from configuration instead of literal execution values.",
        rationale="Literal project destinations in shared automation keep publishing to one stack when the selected environment changes.",
        remediation="Pass the project or registry destination from the selected environment catalog or workflow input; retain fixed trust identities and upstream image pins.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        languages=frozenset({Language.CONFIG}),
        file_patterns=("**/*.yaml", "**/*.yml", "**/*.sh", "**/*.bash"),
        limitations=(
            "Checks Google SDK project env fields, Google auth/setup project_id, Cloud Build output images and literal gcloud --project arguments.",
            "Catalog data, auth provider/account pins, upstream image inputs, safety assertions, tests and generated ownership headers are excluded.",
            "The literal kms keys versions get-public-key command path selects a fixed trust authority and is excluded; other KMS operations remain checked.",
            "Project flags, quiet flags and literal self-contained --flag=value options preserve command classification. Unknown option/value pairs or dynamic prefixes remain unreported until the command purpose is clear.",
            "Custom workflow env image aliases are not resolved into command destinations; their assignment and mutation semantics require dataflow analysis.",
            "Shell analysis does not evaluate assignments, source files, aliases, eval, complex parameter expansions or unknown command wrappers. Dynamic project operands remain unreported.",
            "Standalone shell is selected only under ci, .github or cloudbuild directories; arbitrary local scripts and other CI providers are outside this rule.",
            "Workflow command diagnostics point to the containing run field; folded and quoted YAML values are not treated as physical shell source maps.",
            "Only Bash/POSIX-shaped shell is analyzed. Native syntax checks own malformed shell; YAML parser failures remain analysis failures.",
            "This warning has no inline suppression syntax; configure its rule selection for deliberately fixed-project automation.",
        ),
        examples=tuple(
            RuleExample(
                example_id=identifier,
                title=title,
                outcome=outcome,
                files=(ExampleFile(path=PurePosixPath(path), source=source),),
                focus_path=PurePosixPath(path),
                expected_count=count,
                public=True,
                scenario=scenario,
            )
            for identifier, title, outcome, path, source, count, scenario in (
                (
                    "literal-project-flag",
                    "A command selects one literal project",
                    ExpectedOutcome.MATCH,
                    "scripts/ci/publish.sh",
                    "gcloud artifacts repositories list --project=example-dev\n",
                    1,
                    "project-flag",
                ),
                (
                    "selected-project-flag",
                    "A command consumes the selected project",
                    ExpectedOutcome.NO_MATCH,
                    "scripts/ci/publish.sh",
                    'gcloud artifacts repositories list --project="$PROJECT_ID"\n',
                    0,
                    "project-flag",
                ),
                (
                    "fixed-public-key-trust-read",
                    "A public key retains its fixed trust authority",
                    ExpectedOutcome.NO_MATCH,
                    "scripts/ci/provenance.sh",
                    "gcloud kms keys versions get-public-key 1 --key signer --keyring trust --location global --project example-trust\n",
                    0,
                    "public-key-trust",
                ),
                (
                    "other-kms-project-target",
                    "Other KMS operations still select a project",
                    ExpectedOutcome.MATCH,
                    "scripts/ci/provenance.sh",
                    "gcloud kms keys versions create --project example-dev\n",
                    1,
                    "public-key-trust",
                ),
                (
                    "literal-build-output",
                    "A build output chooses one project",
                    ExpectedOutcome.MATCH,
                    "cloudbuild/build.yaml",
                    'steps: [{name: docker, args: [build, .]}]\nimages: ["us-docker.pkg.dev/example-dev/images/app:$COMMIT_SHA"]\n',
                    1,
                    "build-output",
                ),
                (
                    "selected-build-output",
                    "Cloud Build supplies the selected project",
                    ExpectedOutcome.NO_MATCH,
                    "cloudbuild/build.yaml",
                    'steps: [{name: docker, args: [build, .]}]\nimages: ["us-docker.pkg.dev/$PROJECT_ID/images/app:$COMMIT_SHA"]\n',
                    0,
                    "build-output",
                ),
            )
        ),
    )

    @override
    def check(self, path: Path, source: str) -> list[Finding]:
        if _EXCLUDED_PARTS.intersection(path.parts) or _generated(source):
            return []
        targets: list[_Operand] = []
        parse = make_shell_parser()
        if path.suffix in {".sh", ".bash"} and _CI_SHELL_PARTS.intersection(path.parts[:-1]):
            targets.extend(_shell_targets(source, parse))
        elif path.suffix in {".yaml", ".yml"}:
            targets.extend(_yaml_targets(path, source, parse))
        return [
            Finding(
                path,
                line,
                _CODE,
                f"Literal cloud project {project!r} selects this CI target; use selected environment configuration.",
            )
            for line, project in sorted({target.line: target.value for target in targets if target.value}.items())
        ]


def _generated(source: str) -> bool:
    header = "\n".join(line for line in source.splitlines()[:8] if line.lstrip().startswith("#")).lower()
    return "generated" in header and "do not edit" in header


def _fields(node: Node | None) -> dict[str, Node]:
    return mapping_fields(node) if isinstance(node, MappingNode) else {}


def _items(node: Node | None) -> list[Node]:
    return sequence_items(node) if isinstance(node, SequenceNode) else []


def _yaml_targets(path: Path, source: str, parse: ShellParser) -> Iterator[_Operand]:
    selected = "cloudbuild" in path.parts or "cloudbuild" in path.stem or _workflow_path(path)
    try:
        documents = compose_documents(source)
    except (yaml.YAMLError, CloudBuildParseError) as error:
        if selected:
            raise CloudBuildParseError(str(error)) from error
        return
    for document in documents:
        if _workflow_path(path):
            yield from _workflow_targets(_workflow_root(document), parse)
            continue
        try:
            top = _fields(document)
        except CloudBuildParseError:
            if selected:
                raise
            continue
        if _is_build(top):
            yield from (_image_target(node) for node in _items(top.get("images")))


def _workflow_path(path: Path) -> bool:
    return path.parts[-3:-1] == (".github", "workflows")


def _workflow_root(node: Node | None) -> dict[str, Node]:
    if not isinstance(node, MappingNode):
        return {}
    # GitHub mapping keys such as `on` are strings despite PyYAML's YAML 1.1 tags.
    pending: list[Node] = [node]
    while pending:
        current = pending.pop()
        if isinstance(current, MappingNode):
            for key, value in mapping_items(current):
                if isinstance(key, ScalarNode) and key.tag == "tag:yaml.org,2002:bool":
                    key.tag = "tag:yaml.org,2002:str"
                pending.append(value)
        elif isinstance(current, SequenceNode):
            pending.extend(sequence_items(current))
    selected = [(key, value) for key, value in mapping_items(node) if scalar_text(key) in {"jobs", "env", "defaults"}]
    return mapping_fields(MappingNode(node.tag, selected, start_mark=node.start_mark, end_mark=node.end_mark))


def _is_build(top: Mapping[str, Node]) -> bool:
    return any("name" in _fields(step) for step in _items(top.get("steps")))


def _image_target(node: Node) -> _Operand:
    value = scalar_text(node) or ""
    match = _IMAGE.match(value)
    project = match[1] if match is not None else ""
    return _Operand(project if _PROJECT.fullmatch(project) else "", node.start_mark.line + 1)


def _workflow_targets(top: Mapping[str, Node], parse: ShellParser) -> Iterator[_Operand]:
    for job in _fields(top.get("jobs")).values():
        fields = _fields(job)
        environment = _fields(top.get("env")) | _fields(fields.get("env"))
        yield from _project_environment(environment)
        for step in _items(fields.get("steps")):
            entry = _fields(step)
            selected = environment | _fields(entry.get("env"))
            yield from _project_environment(selected)
            uses = scalar_text(entry.get("uses")) or ""
            if uses.startswith(_PROJECT_ACTIONS):
                project = _fields(entry.get("with")).get("project_id")
                if project is not None:
                    yield _project_target(project)
            run = entry.get("run")
            if isinstance(run, ScalarNode) and _posix_shell(top, fields, entry):
                yield from _run_targets(run, parse)


def _run_targets(run: ScalarNode, parse: ShellParser) -> Iterator[_Operand]:
    return (_Operand(target.value, run.start_mark.line + 1) for target in _shell_targets(scalar_text(run) or "", parse))


def _posix_shell(top: Mapping[str, Node], job: Mapping[str, Node], step: Mapping[str, Node]) -> bool:
    configured = step.get("shell")
    for owner in (job, top):
        if configured is None:
            configured = _fields(_fields(owner.get("defaults")).get("run")).get("shell")
    if configured is not None:
        shell = scalar_text(configured) or ""
        return shell.split()[:1] in (["bash"], ["sh"])
    runner = job.get("runs-on")
    labels = _items(runner) if isinstance(runner, SequenceNode) else [runner]
    return not any("windows" in (scalar_text(label) or "").lower() for label in labels)


def _project_environment(environment: Mapping[str, Node]) -> Iterator[_Operand]:
    for name, node in environment.items():
        if name in _PROJECT_ENV:
            yield _project_target(node)


def _project_target(node: Node) -> _Operand:
    value = scalar_text(node) or ""
    return _Operand(value if _PROJECT.fullmatch(value) else "", node.start_mark.line + 1)


def _shell_targets(source: str, parse: ShellParser) -> Iterator[_Operand]:
    # Expressions remain opaque data, including when they occur in command position.
    source = WORKFLOW_EXPRESSION_RE.sub("${ci_dynamic}", source)
    # Skip impossible candidates before starting shfmt; only the AST can emit a finding.
    joined = source.translate(_SHELL_JOINERS)
    if "gcloud" not in joined or "--project" not in joined:
        return
    try:
        tree = parse(source)
    except ShellSyntaxError:
        return
    for call in _walk(tree):
        if call.get("Type") != "CallExpr":
            continue
        args = [_operand(word) for word in _nodes(call.get("Args"))]
        if not args:
            continue
        command = args[0].value.rsplit("/", 1)[-1]
        if command == "gcloud":
            yield from _project_arguments(args)


def _project_arguments(args: list[_Operand]) -> Iterator[_Operand]:
    arguments = iter(args[1:])
    projects: list[_Operand] = []
    command: list[str] = []
    for arg in arguments:
        if arg.value == "--":
            break
        if arg.value == "--project":
            operand = next(arguments, None)
            if operand is None:
                break
        elif arg.value.startswith("--project="):
            operand = _Operand(arg.value.removeprefix("--project="), arg.line)
        else:
            command.append(arg.value)
            continue
        if _PROJECT.fullmatch(operand.value):
            projects.append(operand)
        elif "${dynamic}" in operand.value:
            command.append(operand.value)
    if _command_purpose(command) is _CommandPurpose.OTHER:
        yield from projects


def _command_purpose(command: list[str]) -> _CommandPurpose:
    words = iter(
        word
        for word in command
        if word not in {"--quiet", "-q"} and not (word.startswith("--") and "=" in word and "${dynamic}" not in word)
    )
    for expected in _PUBLIC_KEY_COMMAND:
        word = next(words, None)
        if word is None:
            return _CommandPurpose.OTHER
        if word.startswith("-") or "${dynamic}" in word:
            return _CommandPurpose.UNKNOWN
        if word != expected:
            return _CommandPurpose.OTHER
    return _CommandPurpose.TRUST_READ


def _nodes(value: object) -> list[Mapping[object, object]]:
    return [node for node in value if is_object_mapping(node)] if is_object_list(value) else []


def _walk(value: object) -> Iterator[Mapping[object, object]]:
    pending = [value]
    while pending:
        node = pending.pop()
        if is_object_mapping(node):
            yield node
            pending.extend(node.values())
        elif is_object_list(node):
            pending.extend(node)


def _operand(word: Mapping[object, object]) -> _Operand:
    parts = _nodes(word.get("Parts"))
    position = word.get("Pos")
    line = position.get("Line") if is_object_mapping(position) else None
    return _Operand(_word_parts(parts), line if isinstance(line, int) else 1)


def _word_parts(parts: list[Mapping[object, object]], *, quoted: bool = False) -> str:
    result: list[str] = []
    for part in parts:
        value = part.get("Value")
        if part.get("Type") == "Lit" and not quoted and isinstance(value, str) and any(char in value for char in "*?["):
            result.append("${dynamic}")
        elif (
            part.get("Type") in {"Lit", "SglQuoted"}
            and isinstance(value, str)
            and not part.get("Dollar")
            and "\\" not in value
        ):
            result.append(value)
        elif part.get("Type") == "DblQuoted":
            result.append(_word_parts(_nodes(part.get("Parts")), quoted=True))
        else:
            result.append("${dynamic}")
    return "".join(result)
