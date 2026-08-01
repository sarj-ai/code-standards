# SARJ081 `prefer-walrus-regex-match` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_walrus_regex_match.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Assigning a regex match result to a temporary variable on the line immediately preceding an
`if` statement testing that variable is the canonical use case for Python 3.8+ assignment
expressions (`:=`). Using `:=` scopes the match object inside the condition block and avoids
floating single-use temporaries in the enclosing block.

    # flagged
    match = re.search(pattern, text)
    if match:
        process(match.group(1))

    # preferred
    if match := re.search(pattern, text):
        process(match.group(1))

Corpus evidence. Evaluation across 7 repositories produced 34 high-value findings with 0 false positives.
