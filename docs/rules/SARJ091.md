# SARJ091 — No long in-code prose

Three or more sentence-equivalents in one comment group or docstring is an
error. Keep the one fact needed beside the code; move durable design narrative
to README, ADR, or architecture documentation.

This is an intentional internal-application policy. Popular public libraries
often need longer published API documentation, so runtime-consumed and
generated documentation is exempt rather than used to weaken the house rule.

## Corpus calibration

`scripts/extract-comment-corpus.py` extracted every Python docstring/comment
and JavaScript-family line/block comment from the three first-party repos on
2026-08-02. Cache, dependency, build, vendor, and worktree directories were
excluded; JSONL mode retains path, line, language, kind, text, and sentence
count for review.

| repository | 0–1 sentence | 2 sentences | 3+ sentences |
| --- | ---: | ---: | ---: |
| first-party repo A | 2,914 | 697 | 36 |
| first-party repo B | 8,228 | 472 | 319 |
| first-party repo C | 10,640 | 697 | 425 |

The distribution supports a graduated policy: one sentence is normal, two
sentences are common enough to migrate as warnings, and three-plus is a
bounded cleanup class. PR 4213 supplies pinned regressions for both a
five-sentence module docstring and typed `Returns` prose.

The existing external sweeps in `_comments.md`, `no-comment-cruft.md`,
SARJ084, SARJ088, and SARJ089 cover pydantic, trio, attrs, Django, FastAPI,
Celery, Zod, TanStack Query, React Router, SWR, Zustand, and other widely used
projects. Those corpora are why the policy preserves external contracts,
invariants, failure semantics, examples, generated API docs, and runtime-used
documentation rather than equating all prose with noise.
