# SARJ301 — Commented-out config

SARJ301 reports compact commented-out YAML, TOML, JSONC, Make, or Docker syntax.
It groups contiguous disabled entries into one finding. Delete the block;
version control is the archive.

Directives and YAML block-scalar contents are excluded because their comment
syntax belongs to a tool or embedded payload rather than disabled configuration.
