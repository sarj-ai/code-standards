/** @fileoverview no-exception-text-in-5xx-response — the documentation and executable examples of `@sarj/no-exception-text-in-5xx-response`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_EXCEPTION_TEXT_IN_5XX_RESPONSE_DOCUMENTATION = {
  summary: "Keep caught exception messages and stacks out of returned 5xx JSON responses and Server Action results.",
  rationale: "Exception details can contain database, provider, filesystem or credential information that belongs in server-side diagnostics rather than a client response.",
  remediation: "Return a generic public error and retain diagnostic details in server-side logs. Keep intentional public domain errors in their reviewed client-error contract.",
  category: "security",
  defaultLevel: "warning",
  autofix: "none",
  references: ["https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html", "https://nextjs.org/docs/app/api-reference/functions/next-response"],
  limitations: [
    "Only directly returned Response.json calls and named NextResponse imports from next/server, with an explicit literal integer 500–599 status, are inspected.",
    "Exported async Server Actions proven by a module or function use-server directive also have their returned result values checked. This profile follows closed const aliases and one same-module, single-parameter, single-return pure helper with unknown/unannotated input and inferred or broad string output. Only catch bindings owned by the action are considered; nested callbacks, unknown helper effects, escaping aliases and direct eval cause abstention.",
    "Simple literal branch/dead-statement checks exclude visible transfers and control-transferring finalizers. Returns nested in for-in/of bodies, including async iteration, switch returns and preceding opaque loops, labels, switches or try statements abstain. Visible Error constructor mutation/escape and function-constructor capabilities invalidate instanceof-based helper purity; external runtime monkeypatches remain outside this local proof.",
    "Caught message/stack fields are followed through literal objects, arrays, interpolation and conditional expressions. Mutable or escaped catch values, shadowed factories and local factory/serializer overrides are excluded.",
    "Client HTTP errors, dynamic status codes, response wrappers, custom sanitizer calls, spreads, uncertain properties or serialization hooks, tests and generated files are excluded. Response-factory aliases and interprocedural mutations or runtime monkeypatches are not resolved.",
    "A warning requests review; syntax does not prove the exception contains a secret. There is no automatic replacement for an application's public error contract.",
  ],
  examples: [
    {
      id: "generic-server-error",
      title: "Keep internal failure details server-side",
      outcome: "no-match",
      files: [{ path: "src/route.ts", source: "function handle() { try { run(); } catch (error) { return Response.json({ error: 'Internal server error' }, { status: 500 }); } }" }],
      focusPath: "src/route.ts", expectedCount: 0, public: true,
    },
    {
      id: "caught-message-in-server-error",
      title: "Do not return a caught message as a server error",
      outcome: "match",
      files: [{ path: "src/route.ts", source: "function handle() { try { run(); } catch (error) { return Response.json({ error: error instanceof Error ? error.message : 'Internal server error' }, { status: 500 }); } }" }],
      focusPath: "src/route.ts", expectedCount: 1, public: true,
    },
    {
      id: "caught-message-in-server-action",
      scenarioId: "server-action",
      title: "Keep Server Action results independent of caught details",
      outcome: "match",
      files: [{ path: "src/actions.ts", source: '"use server"; const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Unknown error"; export async function save() { try { await persist(); } catch (error) { return { ok: false, message: errorMessage(error) }; } }' }],
      focusPath: "src/actions.ts", expectedCount: 1, public: true,
    },
    {
      id: "public-server-action-failure",
      scenarioId: "server-action",
      title: "Return a stable public Server Action failure",
      outcome: "no-match",
      files: [{ path: "src/actions.ts", source: '"use server"; export async function save() { try { await persist(); } catch (error) { captureException(error); return { ok: false, message: "Could not save" }; } }' }],
      focusPath: "src/actions.ts", expectedCount: 0, public: true,
    },
  ],
} as const satisfies RuleDocumentation;
