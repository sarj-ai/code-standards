keys == ["attestations"]
and ([.attestations[].predicateType] | sort) == [
  "https://github.com/npm/attestation/tree/main/specs/publish/v0.1",
  "https://slsa.dev/provenance/v1"
]
and all(.attestations[];
  .bundle as $bundle
  | ($bundle.dsseEnvelope.payload | @base64d | fromjson) as $statement
  | $statement.subject == [{"name": $purl, "digest": {"sha512": $digest}}]
    and $statement.predicateType == .predicateType
    and ($bundle.dsseEnvelope.signatures | length) > 0
    and ($bundle.verificationMaterial.tlogEntries | length) > 0
)
