import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_JSON_STRINGIFY_ERROR_DOCUMENTATION } from "../../src/rules/no-json-stringify-error.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

RULE_TESTER.run("no-json-stringify-error", rule, {
  valid: [
    { name: "allows the documented explicit error field", code: NO_JSON_STRINGIFY_ERROR_DOCUMENTATION.examples[0].files[0].source },
    { name: "allows non-error objects", code: "JSON.stringify(user);" },
    {
      name: "allows a conventional short name without Error provenance",
      code: "items.map((e) => JSON.stringify(e));",
    },
    {
      name: "allows a plain API error payload",
      code: "const data = await response.json(); throw new Error(JSON.stringify(data.error));",
    },
    {
      name: "allows an unproven error-named member",
      code: "JSON.stringify(this.lastError);",
    },
    { name: "allows object literals", code: "JSON.stringify({ a: 1 });" },
    {
      name: "allows an error message nested in an object literal",
      code: "try { f(); } catch (err) { JSON.stringify({ error: err.message }); }",
    },
    {
      name: "allows a string-valued shorthand error property",
      code: "const error = 'provider unavailable'; JSON.stringify({ error });",
    },
    {
      name: "allows an unproven error-named function parameter in a payload",
      code: "function serialize(error: string) { return JSON.stringify({ error }); }",
    },
    {
      name: "allows enumerable error data nested in an object literal",
      code: "JSON.stringify({ error: error.data });",
    },
    {
      name: "does not descend through nested object literals",
      code: "try { f(); } catch (err) { JSON.stringify({ meta: { err } }); }",
    },
    {
      name: "allows identifiers that are neither error-named nor catch bindings",
      code: "const payload = {}; JSON.stringify(payload);",
    },
    {
      name: "allows an error message string",
      code: "try { f(); } catch (err) { JSON.stringify(err.message); }",
    },
    {
      name: "allows an error stack string",
      code: "try { f(); } catch (err) { JSON.stringify(err.stack); }",
    },
    { name: "allows an error name string", code: "JSON.stringify(err.name);" },
    {
      name: "allows the non-error branch of an instanceof ternary",
      code: "const s = e instanceof Error ? e : JSON.stringify(e, null, '\\t');",
    },
    {
      name: "allows the non-error branch of an instanceof if statement",
      code: "let s; if (e instanceof Error) { s = e.message; } else { s = JSON.stringify(e); }",
    },
    {
      name: "allows the non-error branch of a negated instanceof ternary",
      code: "const s = !(e instanceof Error) ? JSON.stringify(e) : e.message;",
    },
    {
      name: "allows the non-error branch of a negated instanceof if statement",
      code: "let s; if (!(err instanceof Error)) { s = JSON.stringify(err); }",
    },
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

    {
      name: "allows enumerable error data",
      code: "JSON.stringify(error.data);",
    },
    {
      name: "allows enumerable error status",
      code: "JSON.stringify(error.status);",
    },
    {
      name: "allows enumerable error statusCode",
      code: "JSON.stringify(error.statusCode);",
    },
    {
      name: "allows enumerable error statusText",
      code: "JSON.stringify(error.statusText);",
    },
    {
      name: "allows enumerable error code",
      code: "JSON.stringify(error.code);",
    },
    {
      name: "allows enumerable error issues",
      code: "JSON.stringify(error.issues);",
    },
    {
      name: "allows enumerable error details",
      code: "JSON.stringify(error.details);",
    },
    {
      name: "allows enumerable error body",
      code: "JSON.stringify(error.body);",
    },
    {
      name: "allows enumerable error payload",
      code: "JSON.stringify(error.payload);",
    },
    {
      name: "allows enumerable error response",
      code: "JSON.stringify(error.response);",
    },
    {
      name: "allows enumerable error info",
      code: "JSON.stringify(error.info);",
    },
    {
      name: "allows enumerable error meta",
      code: "JSON.stringify(error.meta);",
    },
    {
      name: "allows enumerable error metadata",
      code: "JSON.stringify(error.metadata);",
    },
    {
      name: "allows enumerable error context",
      code: "JSON.stringify(error.context);",
    },
  ],
  invalid: [
    { name: "reports the documented Error payload", code: NO_JSON_STRINGIFY_ERROR_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noJsonStringifyError" }] },
    {
      name: "reports a catch binding nested in an object literal",
      code: "try { f(); } catch (err) { JSON.stringify({ error: err }); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      name: "reports a shorthand error property",
      code: "try { f(); } catch (err) { JSON.stringify({ err }); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      name: "reports an error nested in an array literal",
      code: "try { f(); } catch (err) { JSON.stringify([err]); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      name: "reports a stable builtin Error binding nested in a payload",
      code: "const error = new TypeError('invalid'); JSON.stringify({ error });",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // A `catch` binding passed directly, even with an unconventional name.
    {
      code: "try { f(); } catch (problem) { JSON.stringify(problem); }",
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
    // Member expressions rooted in a caught Error retain provenance.
    {
      code: "try { f(); } catch (err) { JSON.stringify(err.cause); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // A caught Error's non-string member still carries Error provenance.
    {
      code: "try { f(); } catch (err) { JSON.stringify(err.inner); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    // An unrelated ternary (not an instanceof guard) does not suppress the report.
    {
      code: "try { f(); } catch (err) { const s = ready ? other : JSON.stringify(err); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },

    {
      name: "rejects nested cause while allowing payload properties",
      code: "try { f(); } catch (error) { JSON.stringify(error.cause); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      name: "rejects originalError while allowing payload properties",
      code: "try { f(); } catch (err) { JSON.stringify(err.originalError); }",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
    {
      name: "reports a directly constructed Error",
      code: "JSON.stringify(new TypeError('invalid'));",
      errors: [{ messageId: "noJsonStringifyError" }],
    },
  ],
});
