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

    // --- A documented log-and-continue is a decision, not a swallow ----------
    // Real corpus: react-router/packages/react-router-dev/vite/styles.ts:104 —
    // the comment explains why the failure is survivable.
    {
      code: "try { f(); } catch { console.warn('css'); // happens for dynamically imported modules\n }",
    },
    {
      code: "try { f(); } catch (e) { /* offline is expected here */ console.error(e); }",
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
  ],
});
