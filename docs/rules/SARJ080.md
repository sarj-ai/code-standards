# SARJ080 `prefer-match-type-dispatch` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_match_type_dispatch.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Parsers and field deserializers often contain hideous type-dispatch idioms:
sequential `if x is None: return x` / `if isinstance(x, Unset): return x` guards,
followed by a `try` block containing `if not isinstance(x, T): raise TypeError()`
to artificially jump control flow into an `except (TypeError, ...): pass` block.

Raising an exception inside a `try` block solely to trigger that block's `except`
handler is using `raise` as a goto (control flow via exceptions).

Preferred Python 3.10+ match/case patterns:
- For `None`: `case None:`
- For singleton classes: `case Unset():`
- For singleton instances: `case _ if data is UNSET:`
- For builtins (`int`, `str`, `list`, `dict`): `case int():`, `case str():`, etc.
- For combined conditions: `case None | Unset():`

Example refactoring:
    match data:
        case None | Unset():
            return data
        case str():
            try:
                return datetime.datetime.fromisoformat(data)
            except ValueError:
                pass
        case dict():
            return parse_dict(data)
    return cast(..., data)

## Not reported

* **generated files** (`_paths.is_generated`). This is the exemption that
  matters most for this rule: the try/raise idiom in the module summary above
  is *transcribed from* openapi-python-client's `_parse_*` template, and it
  reproduces once per nullable field. Before the path half of `is_generated`
  existed, 314 of this rule's 334 findings over two first-party corpora came
  from a single checked-in SDK — a tree the consuming repo already excludes
  from ruff, from its pre-commit hook and from its CI invocation. The
  generator's output is not a refactor anyone can accept; re-running the
  generator would undo it. The 20 findings that remain are hand-written.
