# SARJ077 `prefer-walrus-stream-loop` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_walrus_stream_loop.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Iterating over a stream or chunked reader by initializing an assignment before `while True:`
followed by an immediate break check creates verbose boilerplate. Placing the assignment directly
inside the `while` condition using `:=` unifies the stream read logic.

    # flagged
    while True:
        chunk = stream.read(8192)
        if not chunk:
            break
        process(chunk)

    # preferred
    while chunk := stream.read(8192):
        process(chunk)

Corpus evidence. Sweep across 7 repositories identified 19 stream/reader loops with 0 false positives.
