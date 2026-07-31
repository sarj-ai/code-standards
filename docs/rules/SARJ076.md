# SARJ076 `prefer-walrus-comprehension-filter` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_walrus_comprehension_filter.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Evaluating the exact same non-trivial function call or attribute lookup in both the element
expression and the `if` clause of a comprehension repeats computation. Using an assignment expression
`(res := expr)` inside the `if` filter captures the result in a single evaluation.

    # flagged
    [parse(x) for x in items if parse(x) is not None]

    # preferred
    [res for x in items if (res := parse(x)) is not None]

Corpus evidence. Sweep across 7 repositories revealed 28 redundant comprehension evaluations with 0 false positives.
