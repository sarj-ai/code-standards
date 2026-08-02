# SARJ092 — No typed doc sections

A fully annotated function does not need `Args`, `Parameters`, `Returns`, or
`Yields` prose tables. Delete the section and put constraints in names, types,
validated models, or the one-sentence summary.

`Raises` remains available because Python signatures do not encode exception
contracts. Runtime-consumed tool, route, CLI, and schema documentation is
exempt because changing it changes a user- or model-facing artifact.
