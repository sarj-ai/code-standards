import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-json-stringify-error.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-json-stringify-error", rule, {
  valid: [
    // Stringifying a non-error object is fine.
    { code: "JSON.stringify(user);" },
    // Object literal is fine.
    { code: "JSON.stringify({ a: 1 });" },
    // Arbitrary identifier that isn't an error name and isn't a catch binding.
    { code: "const payload = {}; JSON.stringify(payload);" },
    // Accessing a string property of the error is the recommended escape hatch.
    { code: "try { f(); } catch (err) { JSON.stringify(err.message); }" },
    { code: "try { f(); } catch (err) { JSON.stringify(err.stack); }" },
    { code: "JSON.stringify(err.name);" },
    // `JSON.stringify` runs ONLY in the non-Error branch of an instanceof guard.
    { code: "const s = e instanceof Error ? e : JSON.stringify(e, null, '\\t');" },
    { code: "let s; if (e instanceof Error) { s = e.message; } else { s = JSON.stringify(e); }" },
    { code: "const s = !(e instanceof Error) ? JSON.stringify(e) : e.message;" },
    { code: "let s; if (!(err instanceof Error)) { s = JSON.stringify(err); }" },
    // A user-defined type guard narrows the error away before the stringify.
    {
      code: "function f(e) { if (isErrorLike(e)) return e.message; return JSON.stringify(e); }",
    },
    {
      code: "function f(e) { if (isError(e)) { throw e; } logInfo({ error: JSON.stringify(e) }); }",
    },
    { code: "const s = isErrorLike(e) ? e.message : JSON.stringify(e);" },
    { code: "let s; if (!isErrorLike(err)) { s = JSON.stringify(err); }" },
    // A function whose param is named `data` (not an error name).
    { code: "function f(data) { return JSON.stringify(data); }" },
    // Names that merely contain an error-like substring don't match the anchored regex.
    { code: "JSON.stringify(errors);" },
    { code: "JSON.stringify(emailAddress);" },
    { code: "JSON.stringify(exception);" },
    // Not JSON.stringify at all.
    { code: "const err = {}; serialize(err);" },
    // Different object than JSON.
    { code: "const err = {}; MyJSON.stringify(err);" },
    // No arguments.
    { code: "JSON.stringify();" },

    // --- Data payloads hanging off an error object ---------------------------
    // `error.data` on a react-router `ErrorResponse` is the loader's own JSON
    // body, fully enumerable. Real corpus:
    // react-router/playground/rsc-vite/src/routes/root/root.client.tsx:42.
    { code: "JSON.stringify(error.data);" },
    { code: "const s = JSON.stringify(err.status);" },
    { code: "JSON.stringify(error.issues);" },
    { code: "JSON.stringify(err.response);" },
  ],
  invalid: [
    // A `catch` binding passed directly, even with an unconventional name.
    {
      code: "try { f(); } catch (problem) { JSON.stringify(problem); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // Conventional error names by pattern.
    {
      code: "JSON.stringify(err);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      code: "JSON.stringify(error);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      code: "JSON.stringify(e);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      code: "JSON.stringify(ex);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      code: "JSON.stringify(exc);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // Case-insensitive name match.
    {
      code: "JSON.stringify(Error);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // catch binding inside a nested scope, conventional name.
    {
      code: "try { f(); } catch (err) { const wrap = () => JSON.stringify(err); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // catch binding with unconventional name, used in nested scope.
    {
      code: "try { f(); } catch (boom) { const wrap = () => JSON.stringify(boom); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // Member expressions denoting an error value: error-suggesting property.
    {
      code: "JSON.stringify(err.cause);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      code: "JSON.stringify(this.lastError);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // Error-named base with a non-string-accessor property.
    {
      code: "JSON.stringify(err.inner);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // An unrelated ternary (not an instanceof guard) does not suppress the report.
    {
      code: "const s = ready ? other : JSON.stringify(err);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },

    // A payload accessor is exempt, but a nested-error accessor on the same base
    // still fires — the guard is about the property, not the base.
    {
      code: "JSON.stringify(error.cause);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      code: "JSON.stringify(err.originalError);",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
  ],
});
