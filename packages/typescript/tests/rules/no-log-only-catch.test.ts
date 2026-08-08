import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-log-only-catch.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-log-only-catch", rule, {
  valid: [
    // Logs then rethrows the original error — failure still surfaces.
    {
      code: "try { f(); } catch (e) { console.error(e); throw e; }",
    },
    // Rethrows without logging.
    {
      code: "try { f(); } catch (e) { throw e; }",
    },
    // Rethrows a wrapped error.
    {
      code: "try { f(); } catch (e) { throw new Error('wrapped', { cause: e }); }",
    },
    // Logs then returns a fallback value — the error is handled.
    {
      code: "function g() { try { return f(); } catch (e) { console.warn(e); return null; } }",
    },
    // Returns a fallback without logging.
    {
      code: "function g() { try { return f(); } catch { return []; } }",
    },
    // Mixed logic: logs but also runs real recovery.
    {
      code: "try { f(); } catch (e) { console.error(e); recover(); }",
    },
    // Calls a real handler (not a logger).
    {
      code: "try { f(); } catch (e) { reportError(e); }",
    },
    {
      name: "Promise catch handlers belong to no-silent-promise-catch",
      code: "p.catch(() => {}); p.catch(() => null); p.catch((e) => console.error(e));",
    },
    // Console call mixed with a non-console statement assignment.
    {
      code: "let ok = true; try { f(); } catch (e) { console.error(e); ok = false; }",
    },
    // Computed console access is treated conservatively as real work.
    {
      code: "try { f(); } catch (e) { console['error'](e); }",
    },
    // Comment-only catch documents an intentional ignore — the dominant
    // real-world shape that must NOT be flagged (VS Code sweep: 684/742 hits).
    {
      code: "try { f(); } catch { /* ignore, safe because the resource is already gone */ }",
    },
    // Comment-only catch with a binding.
    {
      code: "try { f(); } catch (e) { // best-effort cleanup; failure is non-fatal\n }",
    },
    // Test file opts out: filename contains `.test.`.
    {
      code: "try { f(); } catch (e) { console.error(e); }",
      filename: "/repo/src/foo.test.ts",
    },
    // Test file opts out: filename contains `.spec.`.
    {
      code: "try { f(); } catch {}",
      filename: "/repo/src/foo.spec.ts",
    },
    // Test file opts out: `__tests__/` path segment.
    {
      code: "try { f(); } catch (e) { console.log(e); }",
      filename: "/repo/src/__tests__/foo.ts",
    },
    // FP-1: an UNDECLARED free function is not assumed to be a logger, so a
    // catch that calls one is still doing real work and is left alone.
    {
      code: "try { f(); } catch (e) { logEvent('f.failed', { error: String(e) }); }",
    },

    // Real corpus: react-router/packages/react-router-dev/vite/styles.ts:104 —
    // the comment explains why the failure is survivable.
    {
      code: "try { f(); } catch { console.warn('css'); // happens for dynamically imported modules\n }",
    },
    {
      code: "try { f(); } catch (e) { /* offline is expected here */ console.error(e); }",
    },

    // Class 1 — the try returns and the fallback is the statement after it.
    // Real corpus: hono/src/middleware/timing/timing.ts:30.
    {
      code: "const getTime = () => {\n  try {\n    return performance.now();\n  } catch {}\n  return Date.now();\n};",
    },
    // The fallback may sit past an enclosing `if`. Real corpus:
    // papermark/components/ui/timestamp-tooltip.tsx:41.
    {
      code: "function tz() {\n  if (typeof Intl !== 'undefined') {\n    try {\n      return Intl.DateTimeFormat().resolvedOptions().timeZone;\n    } catch (e) {}\n  }\n  return 'Local';\n}",
    },
    // Class 2 — a binding seeded with an explicit fallback right above the try,
    // written inside it and read after it. Real corpus:
    // cal.com/packages/app-store/jelly/api/callback.ts:28.
    {
      code: "function h(result, res) {\n  let errorMessage = 'Something is wrong with the Jelly API';\n  try {\n    errorMessage = result.body.error;\n  } catch (e) {}\n  res.status(400).json({ message: errorMessage });\n}",
    },
    {
      name: "Seed fallbacks include undefined, unary literals, empty arrays, and empty objects",
      code: "function a() { let x = undefined; try { x = f(); } catch {} return x; }\nfunction b() { let x = -1; try { x = f(); } catch {} return x; }\nfunction c() { let x = []; try { x = f(); } catch {} return x; }\nfunction d() { let x = {}; try { x = f(); } catch {} return x; }",
    },

    // Directly above the `try`.
    {
      code: "function h() {\n  // best-effort: the row is gone either way\n  try {\n    drop();\n  } catch (err) {\n    console.error(err);\n  }\n}",
    },
    // Between the try block's `}` and the `catch`.
    {
      code: "function h() {\n  try {\n    drop();\n  }\n  // the resource may already have been reclaimed\n  catch (err) {\n    console.error(err);\n  }\n}",
    },
    // Above the `if` whose block holds nothing but the try. Real corpus:
    // openstatus/packages/api/src/router/page.ts:70 and
    // dub/apps/web/lib/actions/partners/program-resources/update-program-resource.ts:133.
    {
      code: "async function h(domain) {\n  // best-effort: the page is gone either way, a leaked attachment is\n  // recoverable while a failed delete is not\n  if (domain) {\n    try {\n      await release(domain);\n    } catch (err) {\n      console.error('Failed to release domain:', err);\n    }\n  }\n}",
    },
    {
      name: "A rationale above a loop applies when the try is its only statement",
      code: "function h(active) {\n  // best-effort polling\n  while (active()) {\n    try {\n      poll();\n    } catch (err) {\n      console.error(err);\n    }\n  }\n}",
    },

    // --- test-file exemption now delegates to the shared `_paths.isTestFile` --
    // The `-spec` / `-test` suffix conventions the local pattern list missed.
    {
      code: "try { f(); } catch {}",
      filename: "/repo/apps/api/test/event-types.controller.e2e-spec.ts",
    },
    {
      code: "try { f(); } catch (e) { console.error(e); }",
      filename: "/repo/packages/router/lib/router-test.ts",
    },
    // A benchmark harness swallows the throw it is timing. Real corpus:
    // zod/packages/zod/src/v3/benchmarks/object.ts:45.
    {
      code: "try { short.parse(null); } catch (_err) {}",
      filename: "/repo/packages/zod/src/v3/benchmarks/object.ts",
    },
  ],
  invalid: [
    // Empty catch with a binding — distinct, accurate `emptyCatch` message.
    {
      code: "try { f(); } catch (e) {}",
      errors: [{ messageId: "emptyCatch" }],
    },
    // Empty catch with no binding.
    {
      code: "try { f(); } catch {}",
      errors: [{ messageId: "emptyCatch" }],
    },
    // Single console.error then nothing.
    {
      code: "try { f(); } catch (e) { console.error(e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },
    // console.log only.
    {
      code: "try { f(); } catch (e) { console.log('failed', e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },
    // Multiple console calls, all of which just log.
    {
      code: "try { f(); } catch (e) { console.warn('oops'); console.error(e); console.debug('done'); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },
    // console.info only.
    {
      code: "try { f(); } catch (e) { console.info(e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },
    // Next.js gap: a logger-receiver call (`logger.warn`) is log-only too.
    {
      code: "try { f(); } catch (e) { logger.warn(e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },
    // Next.js gap: `Log.error(...)`-only catch (capitalized logger receiver).
    {
      code: "try { f(); } catch (e) { Log.error('load failed', e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },
    // Member-chain logger receiver: `this.logger.error(...)`.
    {
      code: "class C { m() { try { f(); } catch (e) { this.logger.error(e); } } }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },
    // Non-test source file with the same shape still flags.
    {
      code: "try { f(); } catch (e) { console.error(e); }",
      filename: "/repo/src/handler.ts",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },
    // FP-1 false-negative closure: once the project DECLARES its structured
    // logger, a catch that only calls it is a log-only catch like any other.
    {
      code: "try { f(); } catch (e) { logEvent('f.failed', { error: String(e) }); }",
      options: [{ logFunctions: ["logEvent"] }],
      errors: [{ messageId: "noLogOnlyCatch" }],
    },
    // A declared logger RECEIVER name behaves like `logger` / `console`.
    {
      code: "try { f(); } catch (e) { obs.error(e); }",
      options: [{ loggerNames: ["obs"] }],
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    // A bare log-only catch with no rationale still fires. Real corpus:
    // react-router/packages/react-router/lib/dom/ssr/fog-of-war.ts:209.
    {
      code: "try { f(); } catch (e) { console.error('Failed to fetch manifest patches', e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    // Class 1 needs BOTH halves. The try ends in a `return`, but nothing follows
    // it, so there is no fallback for control to fall through to.
    {
      code: "function g() {\n  try {\n    return risky();\n  } catch {}\n}",
      errors: [{ messageId: "emptyCatch" }],
    },
    // Something follows the try, but the try does not end in a `return`, so the
    // statement below runs on the success path too and is not a fallback.
    {
      code: "function g() {\n  try {\n    risky();\n  } catch {}\n  commit();\n}",
      errors: [{ messageId: "emptyCatch" }],
    },
    // Class 2: the binding is written in the try but never read after it, so
    // nothing shows the seed is standing in for the failure.
    {
      code: "function g(input) {\n  let parsed = null;\n  try {\n    parsed = JSON.parse(input);\n  } catch {}\n  return other(input);\n}",
      errors: [{ messageId: "emptyCatch" }],
    },
    // Class 2: `let x;` with no seed is not a fallback — reading it after the
    // try yields `undefined`, which is the swallow this rule exists to name.
    {
      code: "function g(input) {\n  let parsed;\n  try {\n    parsed = JSON.parse(input);\n  } catch {}\n  return parsed;\n}",
      errors: [{ messageId: "emptyCatch" }],
    },
    {
      name: "A seeded fallback declaration must immediately precede the try",
      code: "function g(input) {\n  let parsed = null;\n  prepare();\n  try {\n    parsed = JSON.parse(input);\n  } catch {}\n  return parsed;\n}",
      errors: [{ messageId: "emptyCatch" }],
    },
    {
      name: "A seeded fallback declaration must contain one binding",
      code: "function g(input) {\n  let parsed = null, status = 'fallback';\n  try {\n    parsed = JSON.parse(input);\n  } catch {}\n  return parsed;\n}",
      errors: [{ messageId: "emptyCatch" }],
    },
    {
      name: "A seeded fallback must be written inside the try",
      code: "function g(input) {\n  let parsed = null;\n  try {\n    JSON.parse(input);\n  } catch {}\n  return parsed;\n}",
      errors: [{ messageId: "emptyCatch" }],
    },
    {
      name: "Fallback discovery stops at the current function boundary",
      code: "function outer() {\n  const inner = () => {\n    try {\n      return risky();\n    } catch {}\n  };\n  return null;\n}",
      errors: [{ messageId: "emptyCatch" }],
    },
    // Class 3: a comment above an enclosing block that holds MORE than the try
    // is about the block, not about the catch.
    {
      code: "function h(domain) {\n  // resolve the domain before releasing it\n  if (domain) {\n    const target = resolve(domain);\n    try {\n      release(target);\n    } catch (err) {\n      console.error(err);\n    }\n  }\n}",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },
    // Class 3: a comment separated from the `try` by a blank line is not
    // attached to it.
    {
      code: "function h() {\n  // unrelated note about the section above\n\n  try {\n    drop();\n  } catch (err) {\n    console.error(err);\n  }\n}",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },
    // Path guard: a `benchmark.ts` FILE is not a `benchmarks/` directory.
    {
      code: "try { f(); } catch {}",
      filename: "/repo/src/benchmark.ts",
      errors: [{ messageId: "emptyCatch" }],
    },
  ],
});
