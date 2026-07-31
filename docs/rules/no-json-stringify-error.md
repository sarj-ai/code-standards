# `no-json-stringify-error` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-json-stringify-error.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow `JSON.stringify(err)` on a (heuristically detected)
Error value. `JSON.stringify` on an Error produces `"{}"` because the
`message` and `stack` properties are non-enumerable, silently throwing away
the very information you were trying to log.

This is a purely syntactic rule (no type information). It flags
`JSON.stringify(x)` when the first argument is either:
  1. an Identifier that is the binding of an enclosing `catch (x)` clause, or
     matches the conventional error-name pattern /^(e|err|error|ex|exc)$/i, OR
  2. a member expression denoting an error value (`err.cause`, `this.lastError`) —
     an error-suggesting property name, or an error-named base whose property is
     not a plain string accessor (`.message` / `.stack` / `.name`).

It suppresses the report inside the non-error branch of an `x instanceof Error`
guard (`x instanceof Error ? x : JSON.stringify(x)`), where stringifying the
non-Error fallback is exactly correct.

Object literals and arbitrary identifiers (`JSON.stringify(user)`) are not flagged.

Rule (2) originally assumed that any property of an error-named base is itself
an error. It is not: the error objects real frameworks throw carry a plain,
fully-enumerable DATA payload alongside the non-enumerable `message`/`stack`.
A sweep of 2,186 real TypeScript files (zod / TanStack Query / react-router /
swr / zustand) hit exactly that at
react-router/playground/rsc-vite/src/routes/root/root.client.tsx:42 —
`JSON.stringify(error.data)` on a react-router `ErrorResponse`, where `.data`
is the loader's own JSON body and stringifying it is the correct thing to do.
`PAYLOAD_PROPS` lists those accessors (`data`, `status`, `issues`, ...)
alongside `SAFE_STRING_PROPS`; `err.cause` and friends still fire because the
property name itself names an error.
