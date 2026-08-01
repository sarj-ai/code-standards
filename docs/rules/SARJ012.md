# SARJ012 `no-secret-in-log` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_secret_in_log.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Logging a secret value (token, password, api key, jwt, credential, etc.) by
keyword argument leaks it into log sinks — files, stdout, log aggregators —
where it persists far beyond its intended lifetime and is readable by anyone
with log access. Prefer redaction (`token_prefix=token[:6]`) or omission.

We are deliberately precise: only the keyword-argument form
(`logger.info("x", token=token)`) is flagged. F-strings are too noisy to detect
reliably, so they're out of scope.

EXEMPTIONS, WITH CORPUS EVIDENCE
--------------------------------

Two exemption layers keep this rule from firing on metadata *about* a secret:

* redaction markers, applied here (`_REDACTION_RE`, `_WHOLE_TOKEN_REDACTION_
  MARKERS`) — `token_prefix`, `password_hash`, `secret_masked`, `api_key_tag`,
* the shared name predicate in `_secret_names` — counters (`token_count`,
  `prompt_tokens`), row ids (`api_key_id`), and boolean flags in either word
  order (`token_present`, `has_secret`).

Corpus measurement, over 2,657 files of popular third-party Python (fastapi,
pydantic, black, sqlmodel, rich, flask, httpx, requests, anyio): **0 findings,
and 0 exemptions exercised** — there was nothing for either layer to decide.
That zero is a property of the corpus, not a dead rule. Those 2,657 files
contain only 182 logging calls in total, of which just 5 pass any named keyword
at all, and all 5 are the stdlib-reserved `extra=` / `exc_info=` rather than a
structured field. A rule keyed on structured logging keywords has no surface to
fire on in a corpus that does no structured logging. Libraries log for their
users; they do not hold credentials.

The rule is verified live instead of by corpus hit count: the liveness canary in
`tests/rules/test_no_secret_in_log.py` (Family 20) runs a realistic
multi-statement service module and pins that all seven leak shapes still fire
(bare/`self.`/factory/builder receivers x token/password/api_key/jwt/
credentials/authorization/signature) while every safe shape stays silent. Treat
a *drop* in that canary, not a zero on a library corpus, as the breakage signal.

References:
- https://owasp.org/www-community/vulnerabilities/Information_exposure_through_log_files

## Implementation notes

### `_is_logging_call`

Precise on the method name (must be a known log level) and conservative on
the object: the shared resolver walks the receiver chain so factory/builder
forms (`logging.getLogger(__name__).info`, `logger.bind(...).info`) are
recognised, not just `logger` / `self.logger`.
