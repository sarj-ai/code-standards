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
import json
from pathlib import Path
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- this workflow helper executes only fixed trusted tool argv.
import sys
import tarfile
import tempfile
import time
from typing import Annotated, Any, NoReturn
from urllib.parse import quote
from urllib.request import Request, urlopen
import zipfile

import typer


REPOSITORY = "sarj-ai/code-standards"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
WORKFLOW = "release.yml"
REF = "refs/heads/main"
PYPI_ATTESTATIONS = "pypi-attestations==0.0.30"
PYPI_ATTEMPTS = 6
# npm's provenance document is published separately from the package metadata and
# can remain unavailable for more than a minute after the package itself is live.
NPM_ATTESTATION_ATTEMPTS = 18
RETRY_DELAY = timedelta(seconds=10)


class VerificationError(Exception):
    """Registry bytes or provenance do not match the staged release."""


RETRYABLE_EXCEPTIONS = (OSError, subprocess.CalledProcessError, VerificationError)


@dataclass(frozen=True)
class PackageIdentity:
    name: str
    version: str


def _fail(message: str) -> NoReturn:
    raise VerificationError(message)


def _json(url: str) -> dict[str, Any]:
    request = Request(  # ruff: ignore[suspicious-url-open-usage] -- callers construct URLs from fixed HTTPS registries.
        url, headers={"Accept": "application/json"}
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


def _npm_provenance_matches(  # sarj-noqa: SARJ023 -- predicate decoding precedes its coordinator.
    entry: object,
    *,
    expected_subject: str,
    sha512: str,
    commit: str,
    environment: str,
) -> bool:
    if not isinstance(entry, dict) or entry.get("predicateType") != "https://slsa.dev/provenance/v1":
        return False
    bundle = entry.get("bundle")
    envelope = bundle.get("dsseEnvelope") if isinstance(bundle, dict) else None
    material = bundle.get("verificationMaterial") if isinstance(bundle, dict) else None
    certificate = material.get("certificate") if isinstance(material, dict) else None
    raw_certificate = certificate.get("rawBytes") if isinstance(certificate, dict) else None
    if not isinstance(envelope, dict) or not isinstance(raw_certificate, str):
        return False
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
        return False
    statement = _statement(envelope, field="payload")
    predicate = statement.get("predicate")
    build = predicate.get("buildDefinition") if isinstance(predicate, dict) else None
    parameters = build.get("externalParameters") if isinstance(build, dict) else None
    workflow = parameters.get("workflow") if isinstance(parameters, dict) else None
    dependencies = build.get("resolvedDependencies") if isinstance(build, dict) else None
    source_matches = isinstance(dependencies, list) and any(
        isinstance(dependency, dict)
        and dependency.get("uri") == f"git+{REPOSITORY_URL}@{REF}"
        and isinstance(dependency.get("digest"), dict)
        and dependency["digest"].get("gitCommit") == commit
        for dependency in dependencies
    )
    return (
        _subject_matches(statement, filename=expected_subject, algorithm="sha512", digest=sha512)
        and workflow == {"path": f".github/workflows/{WORKFLOW}", "ref": REF, "repository": REPOSITORY_URL}
        and source_matches
    )


def _verify_npm_once(  # sarj-noqa: SARJ023 -- one-attempt verification precedes retry coordination.
    tarball: Path, *, commit: str, environment: str
) -> None:
    identity = _npm_identity(tarball)
    name, version = identity.name, identity.version
    metadata = _json(f"https://registry.npmjs.org/{quote(name, safe='')}/{quote(version, safe='')}")
    dist = metadata.get("dist")
    if not isinstance(dist, dict) or not isinstance(dist.get("tarball"), str):
        _fail(f"npm has no tarball for {name}@{version}")
    local = tarball.read_bytes()
    if _bytes(dist["tarball"]) != local:
        _fail(f"npm bytes differ from staged file {tarball.name}")
    sha512 = _digest(local, "sha512")
    attestations = dist.get("attestations")
    if not isinstance(attestations, dict) or not isinstance(attestations.get("url"), str):
        _fail(f"npm has no attestations for {name}@{version}")
    document = _json(attestations["url"])
    entries = document.get("attestations")
    expected_subject = f"pkg:npm/{quote(name, safe='/')}@{version}"
    matched = isinstance(entries, list) and any(
        _npm_provenance_matches(
            entry,
            expected_subject=expected_subject,
            sha512=sha512,
            commit=commit,
            environment=environment,
        )
        for entry in entries
    )
    if not matched:
        _fail(f"npm provenance does not bind {name}@{version} to {commit}/{WORKFLOW}")
    with tempfile.TemporaryDirectory() as temporary:
        subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- package identity comes from the staged trusted tarball.
            (  # ruff: ignore[start-process-with-partial-path] -- setup-node provides trusted npm.
                "npm",
                "install",
                "--ignore-scripts",
                "--package-lock=false",
                f"{name}@{version}",
            ),
            cwd=temporary,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ("npm", "audit", "signatures"),  # ruff: ignore[start-process-with-partial-path] -- setup-node provides trusted npm.
            cwd=temporary,
            check=True,
        )


def verify_npm(tarball: Path, *, commit: str, environment: str) -> None:
    for attempt in range(NPM_ATTESTATION_ATTEMPTS):
        try:
            _verify_npm_once(tarball, commit=commit, environment=environment)
        except RETRYABLE_EXCEPTIONS:
            if attempt + 1 == NPM_ATTESTATION_ATTEMPTS:
                raise
            time.sleep(RETRY_DELAY.total_seconds())
        else:
            return


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
    ) -> None:
        verify_npm(tarball, commit=commit, environment=environment)

    try:
        app(args=argv, prog_name="verify-registry-publication")
    except SystemExit as exc:
        if exc.code != 0:
            raise
    except (OSError, subprocess.CalledProcessError, VerificationError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
