# Findings: hypermodern Python API rule research

Status: **COMPLETE. Conclusion: ship no new Sarj Python rule.**
Executes brief `03-hypermodern-python-api-rule-research.md`. Date: 2026-08-03.

## Verdict

Ten lanes ran (nine research + one adversary). Every candidate was rejected. The
brief's own bar — "only A candidates should normally become errors" — is met by
nothing that also has findings. The correct output is this rejected-candidates
list plus consumer-config fixes.

Do not re-run this study. Re-open only if a new candidate appears with
first-party findings AND no existing-tool coverage.

## Corpus (pinned)

Four Python consumer repositories contained 1,264, 773, 133, and 120 Python
files. Two additional consumers had zero Python files — report those as "no
eligible Python", never as zero findings.

OSS: cpython `bd8b2fe`, django `fb11376`, pip `6236392`, ansible `2d8c74a`,
pytest `d81152a`, fastapi `b101622`, pydantic `c333d775`, flask `6a2f545`,
requests `1f6589e`, httpx `b5addb6`, sqlalchemy `2b780d9`, celery `7c5d9a6`,
starlette `c86c5db`, aws-cli `4b39e80`, aiohttp `d5d068c`, uvicorn `ee8e45c`.

## Rejected candidates — do not rediscover

| Candidate | Why rejected |
|---|---|
| `argparse` → Typer | 34 verified subclass sites across OSS; three shapes have no Typer/Click equivalent (multiple-inheritance formatters, overriding `_check_value`, parsers built from runtime data). Grade D. |
| `os.path` → `pathlib` | Ruff PTH100/110-122/202-207 already enabled via `select=["ALL"]`. Never deprecated. |
| legacy `importlib.resources` → `files()` | **Falsified at source:** CPython 3.13 What's New *un-deprecated* these. Also `as_file()` changes temp-file lifetime — not lifetime-neutral. |
| `pkg_resources` / `distutils` | Zero first-party occurrences across 51,023 files. Removed at the 3.14 floor / setuptools 82 — already a hard ImportError. |
| `datetime.utcnow()` | Ruff DTZ003 + FURB176 + a TID251 ban, all already enabled. Zero first-party findings. |
| Requests → HTTPX | httpx already won by convention (197 files vs 2 real requests sites). Timeout invariant is Ruff S113, already enabled, zero findings. |
| Pydantic v1 methods | AST cannot distinguish `m.dict()` from `os.environ.copy()`: 1,182 `.json(` and 113 `.copy(` first-party calls, **zero are Pydantic**. basedpyright `reportDeprecated: "error"` already catches these with zero FP. |
| `typing.List` → PEP 585/604 | Ruff UP006/UP007/UP045/UP035, all enabled. Zero findings. |
| unittest aliases | Ruff UP005. Its 541 SQLAlchemy hits are **100% false positives** (matches `self.assert_` lexically; SQLAlchemy defines its own). |
| TaskGroup / `asyncio.timeout` | Semantics differ (sibling cancellation, ExceptionGroup). Three live consumer sites depend on `gather(return_exceptions=True)` + positional `zip(strict=True)`; one documents it in its own docstring. Also contradicts existing SARJ001. |
| `ensure_future` → `create_task` | All 15 findings are in one consumer's test tree; several already carry `# noqa: RUF029` naming the deliberate choice. Only ~40% decidable from AST in CPython. Neither API deprecated. |
| `get_event_loop()` in `async def` | Only 2 real findings. The flagged context is the one where the API is **correct** (a loop is running); deprecation applies only when no loop exists. |
| PyPI `mock` backport ban | `mock` in no first-party lockfile → already ImportError. |
| `argparse.FileType` ban | 29/30 occurrences are inside CPython's own test_argparse.py. Zero first-party. |

## Surviving work (config, not rules)

1. **`reportImplicitOverride`** — candidate flip to `"error"` in
   `configs/pyright.strict.json`. **Blocked on re-measurement:** consumer A reports
   1,737 subclass definitions but near-zero findings, so the checker likely did
   not run over that tree. Do not flip until each repo's run is proven.
   Note the existing comment citing `ast.NodeVisitor.visit_*` is factually
   correct (typeshed declares those), so keep it as a *limitation*, not a
   justification.
2. **`reportDeprecated` protection** — it is the sole zero-FP mechanism catching
   Pydantic v1→v2 and is all-or-nothing. Add a `doctor` DRIFT finding when a
   consumer sets it to anything but `"error"`. Belongs in `doctor.py` (runs in
   the consumer root), **not** in `scripts/` which only sees the standards tree.

## Consumer gaps found incidentally (real, actionable)

- Consumer C declares `configs = ["eslint"]` and has **no Pyright config at
  all** — its 133 Python files are entirely unlinted. 187 PTH findings alone.
- One service in consumer B globally ignores `DTZ005`/`DTZ006`; `DTZ005` has no
  stated reason. A sibling service scopes the identical pair to one adapter
  glob with a documented rationale. Fix the outlier, don't loosen the sibling.
- Consumer D has no `filterwarnings` in pytest config.

## Method notes for whoever runs the next study

- Verify empirically; do not trust config greps. Grep said consumers B and D had
  a DOC-rule conflict; probe files proved they did not.
- `ruff --select X` on the CLI **overrides** the config `ignore`, so it cannot
  test whether a rule is active in practice. Run plain `ruff check`.
- 61 CPython files + 1 django file fail `ast.parse` under 3.14 (deliberate
  syntax-error fixtures; `argparse.py` uses 3.15 `lazy import`). Any rule
  scanning broad corpora must survive unparseable input.
