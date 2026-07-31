"""SARJ202: flag comment cruft in Terraform / IaC — commented-out code and banners.

The same self-documenting standard the Python/TS linters enforce, for `.tf` and
config files. Two deterministic shapes carry no rationale and are pure noise:

1. Commented-out HCL — a standalone comment that is really a disabled resource,
   block, or attribute:
       # resource "google_storage_bucket" "old" {
       # ttl = 3600
   Delete it; Terraform state and git history remember.

2. Section-banner / divider comments:
       # ============================================================
       # ------------------------------------------------------------
   Split the file or use real block structure instead of ASCII rules.

Prose "why" comments are NOT flagged. Directive comments are ignored:
`# sarj-noqa`, `# tflint-ignore`, `# checkov:skip`, `# nosec`, `# TODO`,
`# FIXME`, `# yaml-language-server`, shebangs, and `# terraform:`.

Suppress an intentional case with `# sarj-noqa: SARJ202 — <reason>`.

The commented-out half judges the RUN, not the line (2026-07)
-------------------------------------------------------------
A 23-finding sample of the rule's 164 findings over 256 deduped `.tf` files put
the error rate at 13%, and all of it was in the commented-out-code half:
`_HCL_CODE_RE` classified any HCL-shaped line as dead code, including an indented
*usage example* inside a prose documentation header. At
`litellm/terraform/litellm/gcp/examples/default/main.tf:13` the flagged line is

    #     source  = "github.com/BerriAI/litellm//terraform/litellm/gcp?ref=<tag>"

sitting inside a header comment that documents how to consume the module. "Delete
it, git history remembers" there deletes the module's usage documentation, which
git history does *not* remember as documentation. Same shape at
`litellm/terraform/litellm/aws/examples/default/providers.tf:23`.

The distinguishing fact is not the line, it is the block it sits in: real
commented-out code is a run of comment lines that is *mostly* code, while a doc
comment is mostly prose with a code line or two quoted inside it. A line is now
classified as commented-out code only when its contiguous comment run is
code-dominant — at least half of the run's non-empty, non-directive lines match
`_HCL_CODE_RE`. Measured over the 31 commented-out findings: 12 sit in
prose-dominant runs and are dropped, 19 sit in code-dominant runs and survive, and
every hand-checked genuine dead-code finding is in the surviving 19.

**Independently re-measured, 2026-07-31.** The code-dominance guard was measured
on 256 deduped `.tf` files, which is thin. Re-run over **1,373 content-unique
`.tf` files** (terraform-aws-vpc, terraform-aws-eks, terraform-aws-components,
litellm, airflow), the registry goes 941 -> 862 (-8.4%), all of it this rule
(937 -> 859). 24 files clear entirely, 66 findings. Sampled removals read as the
documented class: indented usage examples inside prose documentation headers
(`litellm/terraform/litellm/gcp/examples/default/main.tf:12`,
`aws/examples/default/providers.tf:22`) and commented-out `object({...})` type
declarations interleaved with per-field prose in
`terraform-aws-components/modules/glue/*/variables.tf`. The second group is the
guard's honest cost: those runs really are commented-out HCL, kept as a shape
reference for a `variable` typed `any`, and the ~50% threshold reads them as
documentation. Recorded rather than tuned away.

The banner half (133 of the 164) is deliberately untouched. It is a house-style
call rather than a detection question, and no guard quietens it without abandoning
the policy.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final, override

from sarj_iac_lint._hcl import heredoc_body_mask
from sarj_iac_lint.rule_base import Diagnostic, Rule


if TYPE_CHECKING:
    from pathlib import Path

_COMMENT_RE = re.compile(r"^(\s*)(#|//)\s?(.*)$")

_DIRECTIVE_PREFIXES = (
    "sarj-noqa",
    "tflint-ignore",
    "tflint:",
    "checkov:",
    "nosec",
    "terraform:",
    "yaml-language-server",
    "todo",
    "fixme",
    "hack",
    "noqa",
    "!",
)

_BANNER_FULL_RE = re.compile(r"^[-=#*~_+.\s]{4,}$")
_BANNER_RUN_RE = re.compile(r"={4,}|-{4,}|#{4,}|\*{4,}|~{4,}")

_HCL_CODE_RE = re.compile(
    r"^(?:resource|data|module|variable|output|provider|locals|terraform|"
    r'backend|dynamic|moved)\s+["{]'
    # attribute assignment whose RHS looks like an HCL value (not English prose
    # such as `deploy = provision the stack` or `retry = 3 attempts` in a comment
    # legend). A bare-number RHS must be the *whole* value (`ttl = 3600`), not the
    # start of a sentence, to match the same "needs a strong code signal" bar that
    # already excludes word-prose RHS.
    r'|^[A-Za-z_][\w-]*\s*=(?!=)\s*(?:["\'\[{]|true\b|false\b|null\b'
    r"|var\.|local\.|module\.|data\.|[A-Za-z_][\w]*\.|[a-z_][\w]*\("
    r"|\d+(?:\.\d+)?\s*,?\s*$)"
    r"|^[A-Za-z_][\w-]*\s*\{$"  # block opener
    r"|^\}\s*$"  # block closer
)


@final
class NoCommentCruft(Rule):
    """Commented-out HCL or a section-banner comment in an IaC file."""

    id = "no-comment-cruft"
    code = "SARJ202"
    description = (
        "Commented-out Terraform/IaC or a section-banner comment — delete it; "
        "code carries the what, comments only the why."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        # Commented-out-code detection runs on real HCL only. `.tfvars` is
        # excluded: a block of commented `key = ""` lines there is a conventional
        # menu of optional inputs, not dead code. Banners are flagged everywhere.
        detect_code = str(path).endswith((".tf", ".tf.json", ".hcl"))
        lines = source.splitlines()
        # Heredoc bodies are arbitrary text (scripts, JSON, docs) — a `# ...`
        # line there is data, not a real comment, so never classify it.
        in_heredoc = heredoc_body_mask(lines)
        # Annotated rather than a bare `frozenset()` on the else branch, whose
        # element type is unknown and widens the whole binding.
        empty: frozenset[int] = frozenset()
        code_run = _code_dominant_lines(lines, in_heredoc) if detect_code else empty
        diags: list[Diagnostic] = []
        for lineno, raw in enumerate(lines, start=1):
            if in_heredoc[lineno - 1]:
                continue
            m = _COMMENT_RE.match(raw)
            if m is None:
                continue
            indent, _marker, body = m.group(1), m.group(2), m.group(3).strip()
            if not body or _is_directive(body):
                continue
            msg = _classify(body, in_code_run=lineno in code_run)
            if msg is not None:
                diags.append(
                    Diagnostic(
                        path=path,
                        line=lineno,
                        col=len(indent) + 1,
                        code=self.code,
                        message=msg,
                    )
                )
        return diags


def _comment_runs(lines: list[str], in_heredoc: list[bool]) -> list[list[tuple[int, str]]]:
    """Group the file's comment lines into maximal contiguous runs.

    A run is broken by anything that is not a comment line — real HCL, a blank
    line, or heredoc body text — because that is what separates one comment from
    the next.

    Returns:
        One list of `(lineno, body)` pairs per run, in source order.

    """
    runs: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for lineno, raw in enumerate(lines, start=1):
        m = None if in_heredoc[lineno - 1] else _COMMENT_RE.match(raw)
        if m is None:
            if current:
                runs.append(current)
                current = []
            continue
        current.append((lineno, m.group(3).strip()))
    if current:
        runs.append(current)
    return runs


def _code_dominant_lines(lines: list[str], in_heredoc: list[bool]) -> frozenset[int]:
    """Line numbers sitting in a comment run that is mostly commented-out HCL.

    The unit of judgement is the run, not the line: a lone `source = "..."` inside
    a prose header is documentation, while the same line among five others like it
    is a disabled block. Directive and empty lines are excluded from the vote —
    they are neither prose nor code — and the threshold is half.

    Returns:
        Every 1-based line number belonging to a code-dominant comment run.

    """
    dominant: set[int] = set()
    for run in _comment_runs(lines, in_heredoc):
        voting = [(lineno, body) for lineno, body in run if body and not _is_directive(body)]
        if not voting:
            continue
        code = sum(1 for _, body in voting if _HCL_CODE_RE.match(body))
        if code * 2 >= len(voting):
            dominant.update(lineno for lineno, _ in voting)
    return frozenset(dominant)


def _classify(body: str, *, in_code_run: bool) -> str | None:
    if _is_banner(body):
        return "Section-banner / divider comment — use real structure, not ASCII rules."
    if in_code_run and _HCL_CODE_RE.match(body):
        return "Commented-out Terraform — delete it; state and git history remember."
    return None


def _is_directive(body: str) -> bool:
    low = body.lower()
    return any(low.startswith(p) for p in _DIRECTIVE_PREFIXES)


def _is_banner(body: str) -> bool:
    if _BANNER_FULL_RE.match(body):
        return True
    return bool(_BANNER_RUN_RE.search(body))
