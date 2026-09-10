# /// script
# requires-python = ">=3.12"
# dependencies = ["typer==0.27.2"]
# ///
# pyright: basic

from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from email.parser import BytesParser
import hashlib
from http import HTTPStatus
import json
from pathlib import Path
import re
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- this workflow helper executes only fixed trusted tool argv.
import sys
import tarfile
import tempfile
import time
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, NoReturn
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import zipfile

import typer


if TYPE_CHECKING:
    from collections.abc import Callable


REPOSITORY = "sarj-ai/code-standards"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
WORKFLOW = "release.yml"
REF = "refs/heads/main"
PYPI_ATTESTATIONS = "pypi-attestations==0.0.30"
PYPI_ATTEMPTS = 6
# npm publishes metadata, provenance, and package-spec installability through
# independent paths. Give each path its own bounded convergence budget so delay
# in one stage cannot starve the next one.
NPM_METADATA_TIMEOUT = timedelta(minutes=5)
NPM_PROVENANCE_TIMEOUT = timedelta(minutes=10)
NPM_INSTALL_TIMEOUT = timedelta(minutes=10)
NPM_INITIAL_RETRY_DELAY = timedelta(seconds=5)
NPM_MAX_RETRY_DELAY = timedelta(seconds=30)
NPM_SUBPROCESS_TIMEOUT_SECONDS = 120
NPM_ARTIFACT_PATHS = MappingProxyType({
    "@sarj/eslint-plugin": (
        "packages/typescript/LICENSE",
        "packages/typescript/package.json",
        "packages/typescript/src",
    ),
    "@sarj/tsconfig": (
        "packages/tsconfig/LICENSE",
        "packages/tsconfig/base.json",
        "packages/tsconfig/package.json",
        "packages/tsconfig/strict.json",
    ),
})
GIT_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
RETRY_DELAY = timedelta(seconds=10)


class VerificationError(Exception):
    """Registry bytes or provenance do not match the staged release."""


class PermanentVerificationError(VerificationError):
    """A verified immutable mismatch that retries cannot repair."""


RETRYABLE_EXCEPTIONS = (
    OSError,
    subprocess.CalledProcessError,
    subprocess.TimeoutExpired,
    VerificationError,
)


@dataclass(frozen=True)
class PackageIdentity:
    name: str
    version: str


@dataclass(frozen=True)
class NpmArtifact:
    identity: PackageIdentity
    attestation_url: str
    expected_subject: str
    sha512: str


def _fail(message: str) -> NoReturn:
    raise VerificationError(message)


def _fail_permanently(message: str) -> NoReturn:
    raise PermanentVerificationError(message)


def _json(url: str) -> dict[str, Any]:
    request = Request(  # ruff: ignore[suspicious-url-open-usage] -- callers construct URLs from fixed HTTPS registries.
        url, headers={"Accept": "application/json", "Cache-Control": "no-cache"}
    )
    with urlopen(  # ruff: ignore[suspicious-url-open-usage] -- the validated request targets a fixed HTTPS registry.
        request, timeout=30
    ) as response:
        value: object = json.load(response)
    if not isinstance(value, dict):
        _fail(f"registry returned a non-object document: {url}")
    return value


def _bytes(url: str) -> bytes:
    request = Request(  # ruff: ignore[suspicious-url-open-usage] -- callers construct URLs from fixed HTTPS registries.
        url, headers={"Accept": "application/octet-stream"}
    )
    with urlopen(  # ruff: ignore[suspicious-url-open-usage] -- the validated request targets a fixed HTTPS registry.
        request, timeout=30
    ) as response:
        return response.read()


def _digest(data: bytes, algorithm: str) -> str:
    return hashlib.new(algorithm, data).hexdigest()


def _metadata(  # sarj-noqa: SARJ023 -- format decoding belongs beside its registry primitives.
    artifact: Path,
) -> PackageIdentity:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            candidates = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(candidates) != 1:
                _fail(f"{artifact.name} has {len(candidates)} METADATA files")
            payload = archive.read(candidates[0])
    else:
        with tarfile.open(artifact, "r:gz") as archive:
            candidates = [member for member in archive.getmembers() if member.name.endswith("/PKG-INFO")]
            if len(candidates) != 1 or (stream := archive.extractfile(candidates[0])) is None:
                _fail(f"{artifact.name} does not have exactly one readable PKG-INFO")
            payload = stream.read()
    metadata = BytesParser().parsebytes(payload)
    name, version = metadata["Name"], metadata["Version"]
    if not name or not version:
        _fail(f"{artifact.name} has incomplete package identity")
    return PackageIdentity(name, version)


def _statement(envelope: dict[str, Any], *, field: str) -> dict[str, Any]:
    encoded = envelope.get(field)
    if not isinstance(encoded, str):
        _fail(f"attestation envelope has no {field}")
    value: object = json.loads(base64.b64decode(encoded))
    if not isinstance(value, dict):
        _fail("attestation statement is not an object")
    return value


def _subject_matches(statement: dict[str, Any], *, filename: str, algorithm: str, digest: str) -> bool:
    subjects = statement.get("subject")
    return isinstance(subjects, list) and any(
        isinstance(subject, dict)
        and subject.get("name") == filename
        and isinstance(subject.get("digest"), dict)
        and subject["digest"].get(algorithm) == digest
        for subject in subjects
    )


def _verify_pypi_file(  # sarj-noqa: SARJ023 -- one-file verification precedes the retry coordinator.
    artifact: Path, *, name: str, version: str, environment: str
) -> None:
    release = _json(f"https://pypi.org/pypi/{quote(name, safe='')}/{quote(version, safe='')}/json")
    urls = release.get("urls")
    if not isinstance(urls, list):
        _fail(f"PyPI has no files for {name}=={version}")
    entry = next((item for item in urls if isinstance(item, dict) and item.get("filename") == artifact.name), None)
    if entry is None or not isinstance(entry.get("url"), str):
        _fail(f"PyPI has not published exact staged file {artifact.name}")
    local = artifact.read_bytes()
    sha256 = _digest(local, "sha256")
    digests = entry.get("digests")
    if not isinstance(digests, dict) or digests.get("sha256") != sha256:
        _fail(f"PyPI digest differs from staged file {artifact.name}")
    if _bytes(entry["url"]) != local:
        _fail(f"PyPI bytes differ from staged file {artifact.name}")

    provenance_url = (
        f"https://pypi.org/integrity/{quote(name, safe='')}/{quote(version, safe='')}/"
        f"{quote(artifact.name, safe='')}/provenance"
    )
    provenance = _json(provenance_url)
    bundles = provenance.get("attestation_bundles")
    matching_publisher = False
    matching_subject = False
    if isinstance(bundles, list):
        for bundle in bundles:
            if not isinstance(bundle, dict):
                continue
            publisher = bundle.get("publisher")
            if publisher == {
                "environment": environment,
                "kind": "GitHub",
                "repository": REPOSITORY,
                "workflow": WORKFLOW,
            }:
                matching_publisher = True
                attestations = bundle.get("attestations")
                if isinstance(attestations, list):
                    matching_subject = any(
                        isinstance(attestation, dict)
                        and isinstance(attestation.get("envelope"), dict)
                        and _subject_matches(
                            _statement(attestation["envelope"], field="statement"),
                            filename=artifact.name,
                            algorithm="sha256",
                            digest=sha256,
                        )
                        for attestation in attestations
                    )
    if not matching_publisher or not matching_subject:
        _fail(f"PyPI provenance does not bind {artifact.name} to {WORKFLOW}/{environment}")
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- argv is fixed and shell execution is disabled.
        (  # ruff: ignore[start-process-with-partial-path] -- setup-uv provides trusted uvx.
            "uvx",
            "--from",
            PYPI_ATTESTATIONS,
            "pypi-attestations",
            "verify",
            "pypi",
            "--repository",
            REPOSITORY_URL,
            entry["url"],
        ),
        check=True,
    )


def verify_pypi(dist: Path, projects: tuple[str, ...], environment: str) -> None:
    artifacts = tuple(sorted((*dist.glob("*.whl"), *dist.glob("*.tar.gz"))))
    grouped: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    for artifact in artifacts:
        identity = _metadata(artifact)
        grouped[identity.name].append((artifact, identity.version))
    if set(grouped) != set(projects):
        _fail(f"staged projects {sorted(grouped)} do not equal expected projects {sorted(projects)}")
    if any(len({version for _, version in items}) != 1 for items in grouped.values()):
        _fail("staged files disagree on project version")
    for attempt in range(PYPI_ATTEMPTS):
        try:
            for name in projects:
                for artifact, version in grouped[name]:
                    _verify_pypi_file(artifact, name=name, version=version, environment=environment)
        except RETRYABLE_EXCEPTIONS:
            if attempt + 1 == PYPI_ATTEMPTS:
                raise
            time.sleep(RETRY_DELAY.total_seconds())
        else:
            return


def _npm_identity(  # sarj-noqa: SARJ023 -- format decoding belongs beside its registry primitives.
    tarball: Path,
) -> PackageIdentity:
    with tarfile.open(tarball, "r:gz") as archive:
        stream = archive.extractfile("package/package.json")
        if stream is None:
            _fail("npm tarball has no package/package.json")
        manifest: object = json.load(stream)
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("name"), str)
        or not isinstance(manifest.get("version"), str)
    ):
        _fail("npm tarball has incomplete package identity")
    return PackageIdentity(manifest["name"], manifest["version"])


def _npm_provenance_commit(  # sarj-noqa: SARJ023 -- predicate decoding precedes its coordinator.
    entry: object,
    *,
    expected_subject: str,
    sha512: str,
    environment: str,
) -> str | None:
    if not isinstance(entry, dict) or entry.get("predicateType") != "https://slsa.dev/provenance/v1":
        return None
    bundle = entry.get("bundle")
    envelope = bundle.get("dsseEnvelope") if isinstance(bundle, dict) else None
    material = bundle.get("verificationMaterial") if isinstance(bundle, dict) else None
    certificate = material.get("certificate") if isinstance(material, dict) else None
    raw_certificate = certificate.get("rawBytes") if isinstance(certificate, dict) else None
    if not isinstance(envelope, dict) or not isinstance(raw_certificate, str):
        return None
    certificate_text = subprocess.run(
        (  # ruff: ignore[start-process-with-partial-path] -- hosted runners provide trusted OpenSSL.
            "openssl",
            "x509",
            "-inform",
            "DER",
            "-text",
            "-noout",
        ),
        input=base64.b64decode(raw_certificate),
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", errors="strict")
    if environment not in certificate_text:
        return None
    statement = _statement(envelope, field="payload")
    predicate = statement.get("predicate")
    build = predicate.get("buildDefinition") if isinstance(predicate, dict) else None
    parameters = build.get("externalParameters") if isinstance(build, dict) else None
    workflow = parameters.get("workflow") if isinstance(parameters, dict) else None
    dependencies = build.get("resolvedDependencies") if isinstance(build, dict) else None
    if not _subject_matches(statement, filename=expected_subject, algorithm="sha512", digest=sha512):
        return None
    if workflow != {"path": f".github/workflows/{WORKFLOW}", "ref": REF, "repository": REPOSITORY_URL}:
        return None
    if not isinstance(dependencies, list):
        return None
    for dependency in dependencies:
        if not isinstance(dependency, dict) or dependency.get("uri") != f"git+{REPOSITORY_URL}@{REF}":
            continue
        digest = dependency.get("digest")
        commit = digest.get("gitCommit") if isinstance(digest, dict) else None
        if isinstance(commit, str) and GIT_COMMIT_PATTERN.fullmatch(commit):
            return commit
    return None


def attested_commit_matches_current_tree(package: str, attested: str, current: str) -> bool:
    paths = NPM_ARTIFACT_PATHS.get(package)
    if paths is None or GIT_COMMIT_PATTERN.fullmatch(current) is None:
        _fail_permanently(f"unsupported npm provenance identity: {package}@{current}")
    ancestor = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed git argv validates trusted provenance.
        (  # ruff: ignore[start-process-with-partial-path] -- Actions supplies Git.
            "git",
            "merge-base",
            "--is-ancestor",
            attested,
            current,
        ),
        check=False,
        stdout=subprocess.DEVNULL,
        timeout=NPM_SUBPROCESS_TIMEOUT_SECONDS,
    )
    if ancestor.returncode == 1:
        return False
    if ancestor.returncode != 0:
        raise subprocess.CalledProcessError(ancestor.returncode, ancestor.args)
    unchanged = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed paths bind provenance to package source.
        (  # ruff: ignore[start-process-with-partial-path] -- Actions supplies Git.
            "git",
            "diff",
            "--quiet",
            attested,
            current,
            "--",
            *paths,
        ),
        check=False,
        stdout=subprocess.DEVNULL,
        timeout=NPM_SUBPROCESS_TIMEOUT_SECONDS,
    )
    if unchanged.returncode == 1:
        return False
    if unchanged.returncode != 0:
        raise subprocess.CalledProcessError(unchanged.returncode, unchanged.args)
    return True


def retry_npm_stage[T](
    stage: str,
    operation: Callable[[], T],
    *,
    timeout: timedelta,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> T:
    deadline = clock() + timeout.total_seconds()
    delay = NPM_INITIAL_RETRY_DELAY.total_seconds()
    while True:
        try:
            return operation()
        except RETRYABLE_EXCEPTIONS as error:
            if not _is_retryable_npm_error(error):
                raise
            remaining = deadline - clock()
            if remaining <= 0:
                msg = f"npm {stage} did not converge within {timeout}: {error}"
                raise VerificationError(msg) from error
            requested = _retry_after_seconds(error)
            wait = min(requested if requested is not None else delay, remaining)
            sys.stderr.write(
                f"npm {stage} attempt failed; retrying in {wait:.1f}s ({remaining:.1f}s remain): {error}\n"
            )
            sleeper(wait)
            delay = min(delay * 2, NPM_MAX_RETRY_DELAY.total_seconds())


def _retry_after_seconds(error: BaseException) -> float | None:
    if not isinstance(error, HTTPError) or error.headers is None:
        return None
    raw = error.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _is_retryable_npm_error(error: BaseException) -> bool:
    if isinstance(error, PermanentVerificationError):
        return False
    if isinstance(error, HTTPError):
        return (
            error.code
            in {
                HTTPStatus.NOT_FOUND,
                HTTPStatus.REQUEST_TIMEOUT,
                HTTPStatus.TOO_EARLY,
                HTTPStatus.TOO_MANY_REQUESTS,
            }
            or error.code >= HTTPStatus.INTERNAL_SERVER_ERROR
        )
    return isinstance(error, RETRYABLE_EXCEPTIONS)


def verify_npm(
    tarball: Path,
    *,
    commit: str,
    environment: str,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    identity = _npm_identity(tarball)
    artifact = retry_npm_stage(
        "metadata and exact bytes",
        lambda: _npm_artifact(tarball, identity),
        timeout=NPM_METADATA_TIMEOUT,
        clock=clock,
        sleeper=sleeper,
    )
    retry_npm_stage(
        "provenance",
        lambda: _verify_npm_provenance(artifact, commit=commit, environment=environment),
        timeout=NPM_PROVENANCE_TIMEOUT,
        clock=clock,
        sleeper=sleeper,
    )
    retry_npm_stage(
        "package-spec installability and signature audit",
        lambda: _verify_npm_installability(identity),
        timeout=NPM_INSTALL_TIMEOUT,
        clock=clock,
        sleeper=sleeper,
    )


def _npm_artifact(tarball: Path, identity: PackageIdentity) -> NpmArtifact:
    name, version = identity.name, identity.version
    metadata = _json(f"https://registry.npmjs.org/{quote(name, safe='')}/{quote(version, safe='')}")
    dist = metadata.get("dist")
    if not isinstance(dist, dict) or not isinstance(dist.get("tarball"), str):
        _fail(f"npm has no tarball for {name}@{version}")
    local = tarball.read_bytes()
    if _bytes(dist["tarball"]) != local:
        _fail_permanently(f"npm bytes differ from staged file {tarball.name}")
    sha512 = _digest(local, "sha512")
    attestations = dist.get("attestations")
    if not isinstance(attestations, dict) or not isinstance(attestations.get("url"), str):
        _fail(f"npm has no attestations for {name}@{version}")
    return NpmArtifact(
        identity=identity,
        attestation_url=attestations["url"],
        expected_subject=f"pkg:npm/{quote(name, safe='/')}@{version}",
        sha512=sha512,
    )


def _verify_npm_provenance(artifact: NpmArtifact, *, commit: str, environment: str) -> None:
    document = _json(artifact.attestation_url)
    entries = document.get("attestations")
    commits = (
        (
            _npm_provenance_commit(
                entry,
                expected_subject=artifact.expected_subject,
                sha512=artifact.sha512,
                environment=environment,
            )
            for entry in entries
        )
        if isinstance(entries, list)
        else ()
    )
    matched = any(
        attested is not None and attested_commit_matches_current_tree(artifact.identity.name, attested, commit)
        for attested in commits
    )
    if not matched:
        identity = artifact.identity
        _fail(
            f"npm provenance does not bind {identity.name}@{identity.version} to {commit}/{WORKFLOW} "
            "through an unchanged ancestor"
        )


def _verify_npm_installability(identity: PackageIdentity) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        cache = str(Path(temporary) / ".npm-cache")
        subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- package identity comes from the staged trusted tarball.
            (  # ruff: ignore[start-process-with-partial-path] -- setup-node provides trusted npm.
                "npm",
                "install",
                "--ignore-scripts",
                "--package-lock=false",
                "--prefer-online",
                "--cache",
                cache,
                f"{identity.name}@{identity.version}",
            ),
            cwd=temporary,
            check=True,
            stdout=subprocess.DEVNULL,
            timeout=NPM_SUBPROCESS_TIMEOUT_SECONDS,
        )
        subprocess.run(
            ("npm", "audit", "signatures"),  # ruff: ignore[start-process-with-partial-path] -- setup-node provides trusted npm.
            cwd=temporary,
            check=True,
            timeout=NPM_SUBPROCESS_TIMEOUT_SECONDS,
        )


def publish_and_verify_npm(tarball: Path, *, commit: str, environment: str) -> None:
    identity = _npm_identity(tarball)
    exists = retry_npm_stage(
        "pre-publication lookup",
        lambda: _npm_version_exists(identity),
        timeout=NPM_METADATA_TIMEOUT,
    )
    publish_error: subprocess.CalledProcessError | subprocess.TimeoutExpired | None = None
    if not exists:
        try:
            subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- CI supplies the digest-verified tarball, never shell input.
                (  # ruff: ignore[start-process-with-partial-path] -- setup-node provides trusted npm.
                    "npm",
                    "publish",
                    str(tarball),
                    "--access",
                    "public",
                    "--ignore-scripts",
                ),
                check=True,
                timeout=NPM_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            publish_error = error
    try:
        verify_npm(tarball, commit=commit, environment=environment)
    except RETRYABLE_EXCEPTIONS as verification_error:
        if publish_error is not None:
            msg = (
                f"npm publish had an ambiguous failure ({publish_error}); registry verification also failed: "
                f"{verification_error}"
            )
            raise VerificationError(msg) from verification_error
        raise


def _npm_version_exists(identity: PackageIdentity) -> bool:
    url = f"https://registry.npmjs.org/{quote(identity.name, safe='')}/{quote(identity.version, safe='')}"
    try:
        _json(url)
    except HTTPError as error:
        if error.code == HTTPStatus.NOT_FOUND:
            return False
        raise
    return True


def main(argv: list[str] | None = None) -> int:
    app = typer.Typer(
        add_completion=False,
        pretty_exceptions_enable=False,
        context_settings={"help_option_names": ["-h", "--help"]},
    )

    @app.command("pypi")
    def pypi_command(
        dist: Annotated[Path, typer.Option("--dist")],
        project: Annotated[list[str], typer.Option("--project")],
        environment: Annotated[str, typer.Option("--environment")],
    ) -> None:
        verify_pypi(dist, tuple(project), environment)

    @app.command("npm")
    def npm_command(
        tarball: Annotated[Path, typer.Option("--tarball")],
        commit: Annotated[str, typer.Option("--commit")],
        environment: Annotated[str, typer.Option("--environment")],
        *,
        publish: Annotated[bool, typer.Option("--publish")] = False,
    ) -> None:
        if publish:
            publish_and_verify_npm(tarball, commit=commit, environment=environment)
        else:
            verify_npm(tarball, commit=commit, environment=environment)

    try:
        app(args=argv, prog_name="verify-registry-publication")
    except SystemExit as exc:
        if exc.code != 0:
            raise
    except RETRYABLE_EXCEPTIONS as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
