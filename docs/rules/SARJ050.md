# SARJ050 `redundant-docstring` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_redundant_docstring.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

    def get_profile_by_national_id(self, national_id: str) -> Profile | None:
        """Get profile by national ID."""

Every content word of the docstring is already in the function's name, its
parameters or its annotations. It answers no question a reader could have — not
what the caller must guarantee, not what it raises, not why it exists — and it
takes a line of screen and a line of review for nothing.

**The fix is to delete the WHOLE docstring, not to trim it.** Removing only the
summary line leaves a docstring whose first line is an `Args:` header, which
ruff then flags (D212/D415), and shrinking a Google-style block to its sections
trips D417/DOC201. A function with no docstring at all is clean under this
repo's strict ruff config; a half-docstring is not.

**Never flagged**

- **`@function_tool` docstrings are LLM prompts.** In an agent framework
  (openai-agents, livekit-agents, langchain, FastMCP) the docstring is shipped
  to the model as the tool description — deleting it changes what the agent
  does at runtime. This is a hard exemption, not a heuristic one, and it is the
  single most dangerous autofix this rule could have offered.
- **CLI command docstrings are `--help` text** for click / typer, and a
  FastAPI / Flask route handler's docstring is the OpenAPI operation
  description. Same argument: the text is an artefact someone reads elsewhere.
- **Value markers**: a `Raises:` section, a doctest prompt, a URL, an RFC, a
  reST directive, or a number with a unit — plus the whole nine-signal protected
  class from `_comments`, which is what keeps "Should return 401 with invalid
  token" (a status code the signature cannot carry) off the list.
- **Stubs whose body IS the docstring** — a `Protocol` method or an abstract
  declaration. "Delete the whole docstring" would leave an empty suite, so the
  advice this rule gives would not compile.
- **Generated code**, whose docstrings mirror whatever the generator emits.
- **Negations count as content.** "Does NOT close the socket" restates the name
  and then contradicts the obvious reading of it, which is the most valuable
  sentence a docstring can contain; `not`, `no` and `never` are therefore NOT
  stopwords here even though they are in the comment tokenizer's list.
- **Numbers are not words.** `_docstrings.WORD_RE` is `[A-Za-z][A-Za-z0-9']*`, so
  a token beginning with a digit is not a word at all and can never be a content
  word — which makes a bare literal value INVISIBLE to the restatement test even
  when it is the entire point of the sentence. A docstring carrying a digit run
  that its signature does not carry therefore adds content. See the audit below.

**Measured.** repo A **5**, repo B **105**, pydantic **22**, trio **4**,
attrs **8** — 144 findings (the two first-party repo labels are stable within
this docstring only). 40 were hand-read across the two maintained repos
and one was borderline (a test docstring adding "for protected endpoints"), so
≥95% precision. The FastAPI-route and docstring-only-body exemptions were both
found by that read, not predicted.

**Three shapes this rule structurally cannot reach**, each now owned by its own
code rather than folded in here (a consumer repo pins this package by caret and
runs SARJ050 at `error`, so widening it would land uncontrolled on a patch
release):
a `class` docstring, which this walker never inspects (SARJ085); a docstring
carrying a Google-style `Args:` block, where the literal word "args" is a
content word no signature contains and so nothing below it can ever be judged
(SARJ086); and an override that copies its base's docstring verbatim, which
restates the base, not the signature (SARJ084).

The stopword list, the value markers, the prompt-decorator set and the
restatement test moved to `rules/_docstrings` unchanged when those three
arrived — four rules asking the same question must not answer it four ways.

## 2026-07 false-positive audit — clean

Re-measured on a 19-repo, 24,644-file corpus (6 first-party plus django, celery,
airflow, litellm, prefect, saleor, zulip, fastapi, pydantic, rich, httpx,
requests): **2,866 findings**. A seeded random sample of 50 read against source
gave **46 true positives, 1 false, 3 arguable — a 2% false-positive rate**. One
free guard landed, taking the rule to **2,835**.

**The digit-not-in-signature guard.** The one false positive was the numeric
shape above: `prefect/tests/client/schemas/test_concurrency.py:60` is
`"""Test that grace_period_seconds=60 is valid (minimum boundary)."""` under
`test_grace_period_seconds_minimum_boundary_valid` — every word is in the name,
the `=60` is what the test is about, and the rule read it as pure restatement.
**31 findings of 2,866 (1.1%), 0 of them first-party — free.** Every removal
reads the same way: django's "the given 1-based page number"
(`core/paginator.py:133,169`), litellm's "budget_tokens < 1024 should be clamped
to 1024" and "default embedding dimension is 3072".

The rest of the read produced no new class. Three properties were confirmed
rather than changed and should stay as they are:

* the docstring-only-body test (`if len(node.body) == 1`) structurally exempts
  `Protocol` methods and abstract declarations, so **no separate stub guard is
  needed**;
* `@override` is 6 findings corpus-wide and 0 first-party, and SARJ084 owns that
  case;
* dunder methods are 8 corpus-wide and 0 first-party.

Suppress an intentional case with `# sarj-noqa: SARJ050 — <reason>`.
