// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_LOG_ONLY_CATCH_DOCUMENTATION } from "../../src/rules/no-log-only-catch.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

RULE_TESTER.run("no-log-only-catch", rule, {
  valid: [
    {
      name: "preserves a rethrow after a static computed log call",
      code: "function execute() { try { run(); } catch (error) { console['error'](error); throw error; } }",
    },

    { name: "preserves an immediate const validation alias", code: "function parse(payload) { try { payload.value = Number(payload.value); } catch {} const input = payload.value; if (typeof input === 'number' && Number.isFinite(input)) return input; throw new Error('invalid'); }" },
    {
      name: "preserves attempted coercion followed by explicit type validation",
      code: "function parse(payload) { try { payload.value = String(payload.value); } catch {} if (typeof payload.value === 'string') return payload; throw new Error('invalid'); }",
    },
    {
      name: "logging preserves an external return fallback",
      code: "function read() { try { return load(); } catch (error) { console.warn(error); } return []; }",
    },
    { name: "accepts the documented rethrow", code: NO_LOG_ONLY_CATCH_DOCUMENTATION.examples[0].files[0].source },

    {
      code: "try { f(); } catch (e) { console.error(e); throw e; }",
    },

    {
      code: "try { f(); } catch (e) { throw e; }",
    },

    {
      code: "try { f(); } catch (e) { throw new Error('wrapped', { cause: e }); }",
    },

    {
      code: "function g() { try { return f(); } catch (e) { console.warn(e); return null; } }",
    },

    {
      code: "function g() { try { return f(); } catch { return []; } }",
    },

    {
      code: "try { f(); } catch (e) { console.error(e); recover(); }",
    },

    {
      code: "try { f(); } catch (e) { reportError(e); }",
    },
    {
      name: "Promise catch handlers belong to no-silent-promise-catch",
      code: "p.catch(() => {}); p.catch(() => null); p.catch((e) => console.error(e));",
    },

    {
      code: "let ok = true; try { f(); } catch (e) { console.error(e); ok = false; }",
    },

    {
      code: "try { f(); } catch (e) { console[method](e); }",
    },


    {
      code: "try { f(); } catch { /* ignore, safe because the resource is already gone */ }",
    },

    {
      code: "try { f(); } catch (e) { // best-effort cleanup; failure is non-fatal\n }",
    },

    {
      code: "try { f(); } catch (e) { console.error(e); }",
      filename: "/repo/src/foo.test.ts",
    },

    {
      code: "try { f(); } catch {}",
      filename: "/repo/src/foo.spec.ts",
    },

    {
      code: "try { f(); } catch (e) { console.log(e); }",
      filename: "/repo/src/__tests__/foo.ts",
    },


    {
      code: "try { f(); } catch (e) { logEvent('f.failed', { error: String(e) }); }",
    },



    {
      code: "try { f(); } catch { console.warn('css'); // happens for dynamically imported modules\n }",
    },
    {
      code: "try { f(); } catch (e) { /* offline is expected here */ console.error(e); }",
    },



    {
      code: "const getTime = () => {\n  try {\n    return performance.now();\n  } catch {}\n  return Date.now();\n};",
    },


    {
      code: "function tz() {\n  if (typeof Intl !== 'undefined') {\n    try {\n      return Intl.DateTimeFormat().resolvedOptions().timeZone;\n    } catch (e) {}\n  }\n  return 'Local';\n}",
    },



    {
      code: "function h(result, res) {\n  let errorMessage = 'Something is wrong with the Jelly API';\n  try {\n    errorMessage = result.body.error;\n  } catch (e) {}\n  res.status(400).json({ message: errorMessage });\n}",
    },
    {
      name: "Seed fallbacks include undefined, unary literals, empty arrays, and empty objects",
      code: "function a() { let x = undefined; try { x = f(); } catch {} return x; }\nfunction b() { let x = -1; try { x = f(); } catch {} return x; }\nfunction c() { let x = []; try { x = f(); } catch {} return x; }\nfunction d() { let x = {}; try { x = f(); } catch {} return x; }",
    },


    {
      code: "function h() {\n  // best-effort: the row is gone either way\n  try {\n    drop();\n  } catch (err) {\n    console.error(err);\n  }\n}",
    },

    {
      code: "function h() {\n  try {\n    drop();\n  }\n  // the resource may already have been reclaimed\n  catch (err) {\n    console.error(err);\n  }\n}",
    },



    {
      code: "async function h(domain) {\n  // best-effort: the page is gone either way, a leaked attachment is\n  // recoverable while a failed delete is not\n  if (domain) {\n    try {\n      await release(domain);\n    } catch (err) {\n      console.error('Failed to release domain:', err);\n    }\n  }\n}",
    },
    {
      name: "A rationale above a loop applies when the try is its only statement",
      code: "function h(active) {\n  // best-effort polling\n  while (active()) {\n    try {\n      poll();\n    } catch (err) {\n      console.error(err);\n    }\n  }\n}",
    },



    {
      code: "try { f(); } catch {}",
      filename: "/repo/apps/api/test/event-types.controller.e2e-spec.ts",
    },
    {
      code: "try { f(); } catch (e) { console.error(e); }",
      filename: "/repo/packages/router/lib/router-test.ts",
    },


    {
      code: "try { short.parse(null); } catch (_err) {}",
      filename: "/repo/packages/zod/src/v3/benchmarks/object.ts",
    },
  ],
  invalid: [
    {
      name: "recognizes a static computed console method as logging",
      code: "try { f(); } catch (e) { console['error'](e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    { name: "does not exempt custom coercion functions", code: "function parse(String) { try { payload.value = String(payload.value); } catch {} if (typeof payload.value === 'string') return payload; }", errors: [{messageId: "emptyCatch"}] },
    { name: "does not infer validation from a later unrelated call", code: "try { payload.value = String(payload.value); } catch {} save(payload);", errors: [{messageId: "emptyCatch"}] },
    { name: "reports the documented swallowed failure", code: NO_LOG_ONLY_CATCH_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noLogOnlyCatch" }] },

    {
      code: "try { f(); } catch (e) {}",
      errors: [{ messageId: "emptyCatch" }],
    },

    {
      code: "try { f(); } catch {}",
      errors: [{ messageId: "emptyCatch" }],
    },

    {
      code: "try { f(); } catch (e) { console.error(e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    {
      code: "try { f(); } catch (e) { console.log('failed', e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    {
      code: "try { f(); } catch (e) { console.warn('oops'); console.error(e); console.debug('done'); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    {
      code: "try { f(); } catch (e) { console.info(e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    {
      code: "try { f(); } catch (e) { logger.warn(e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    {
      code: "try { f(); } catch (e) { Log.error('load failed', e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    {
      code: "class C { m() { try { f(); } catch (e) { this.logger.error(e); } } }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    {
      code: "try { f(); } catch (e) { console.error(e); }",
      filename: "/repo/src/handler.ts",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },


    {
      code: "try { f(); } catch (e) { logEvent('f.failed', { error: String(e) }); }",
      options: [{ logFunctions: ["logEvent"] }],
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    {
      code: "try { f(); } catch (e) { obs.error(e); }",
      options: [{ loggerNames: ["obs"] }],
      errors: [{ messageId: "noLogOnlyCatch" }],
    },



    {
      code: "try { f(); } catch (e) { console.error('Failed to fetch manifest patches', e); }",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },



    {
      code: "function g() {\n  try {\n    return risky();\n  } catch {}\n}",
      errors: [{ messageId: "emptyCatch" }],
    },


    {
      code: "function g() {\n  try {\n    risky();\n  } catch {}\n  commit();\n}",
      errors: [{ messageId: "emptyCatch" }],
    },


    {
      code: "function g(input) {\n  let parsed = null;\n  try {\n    parsed = JSON.parse(input);\n  } catch {}\n  return other(input);\n}",
      errors: [{ messageId: "emptyCatch" }],
    },


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


    {
      code: "function h(domain) {\n  // resolve the domain before releasing it\n  if (domain) {\n    const target = resolve(domain);\n    try {\n      release(target);\n    } catch (err) {\n      console.error(err);\n    }\n  }\n}",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },


    {
      code: "function h() {\n  // unrelated note about the section above\n\n  try {\n    drop();\n  } catch (err) {\n    console.error(err);\n  }\n}",
      errors: [{ messageId: "noLogOnlyCatch" }],
    },

    {
      code: "try { f(); } catch {}",
      filename: "/repo/src/benchmark.ts",
      errors: [{ messageId: "emptyCatch" }],
    },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "log-and-swallow-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/task.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/task.ts",
        "source": "try { run(); } catch (error) { console[\"error\"](error); }"
      }
    ]
  },
  {
    "id": "log-and-swallow-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/task.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/task.ts",
        "source": "try { run(); } catch (error) { console[auditDynamicMember](error); }"
      }
    ]
  }
] } });
});
