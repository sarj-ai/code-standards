/** @fileoverview no-raw-fetch-outside-clients — the documentation and executable examples of `@sarj/no-raw-fetch-outside-clients`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_RAW_FETCH_OUTSIDE_CLIENTS_DOCUMENTATION = {
  summary: "Disallow calling the global `fetch` outside the client layer; route outbound HTTP through a client module that owns retry, timeout and status handling.",
  rationale: "Scattered fetch calls bypass shared transport policy and are harder to stub and observe consistently.",
  remediation: "Move the request into a client module and call that abstraction from application code.",
  category: "architecture",
  limitations: ["Tests, client-layer paths, constructed handoffs, and pre-signed URL transfers are excluded. Configure the same literal Next.js basePath here and on prefer-server-actions so one rule owns each internal mutation.", "Effect and pre-signed-transfer exemptions use recognized syntax and naming conventions, not complete React or URL provenance. Those conservative exclusions are recall limitations, not evidence that every excluded request satisfies transport policy.", "Unshadowed native members and bounded stable const aliases or single-property destructuring are recognized. Visible writes, callable escapes, whole-global escapes and mutation capabilities anywhere in the file invalidate that proof, including earlier captures. Known unrelated global member writes and typeof global checks do not. Static constructor members and destructuring projections invalidate the proof; indirect reflection, external monkeypatches and arbitrary forwarding functions are not inferred."],
  examples: [
    { id: "client-call", title: "Use a client abstraction", outcome: "no-match", files: [{ path: "src/routes/handler.ts", source: "const response = await billingClient.getInvoice(id);" }], focusPath: "src/routes/handler.ts", expectedCount: 0, public: true },
    { id: "raw-fetch", title: "Do not call global fetch here", outcome: "match", files: [{ path: "src/routes/handler.ts", source: "const response = await fetch('/api/invoices');" }], focusPath: "src/routes/handler.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
