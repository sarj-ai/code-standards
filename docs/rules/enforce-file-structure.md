# `enforce-file-structure` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/enforce-file-structure.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Require imports to come first, then allow step-down ordering for
the rest of the file, and require a `use server` directive to be the first
statement.

Reporting is per-DEFECT, not per-import: see the `inMisplacedRun` note in
`create` for the corpus measurement behind that.

## Evidence relocated from the source

### `case "body":`

One misplacement is one defect. A single interleaved statement pushes
every later import "after the body", and reporting each of them turns
one `const nodeRequire = createRequire(...)` between two import blocks
into 18 messages — measured at
react-router/packages/react-router-dev/vite/plugin.ts:41, which alone
produced 18 of the 33 corpus hits. Report the head of each contiguous
run of misplaced imports instead, so a file with two separate
interleavings still gets two messages.

