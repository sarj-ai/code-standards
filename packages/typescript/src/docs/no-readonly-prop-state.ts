/** @fileoverview no-readonly-prop-state — the documentation and executable examples of `@sarj/no-readonly-prop-state`. */

import type { RuleDocumentation } from "../documentation.js";

const BEFORE =
  "import { useState } from 'react'; export function Status({ status }: { status: string }) { const [savedStatus] = useState(status); return <p>{savedStatus}</p>; }";

const AFTER =
  "export function Status({ status }: { status: string }) { return <p>{status}</p>; }";

const CONFIG = {
  path: "tsconfig.json",
  source:
    '{"compilerOptions":{"strict":true,"target":"ESNext","module":"ESNext","moduleResolution":"Bundler","jsx":"preserve"},"include":["src/**/*"]}',
} as const;

export const NO_READONLY_PROP_STATE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Review props copied into state without a usable updater.",
  rationale:
    "State initialized from props retains the first render's value. Without an observed updater, later props can leave the displayed value stale and add a second source of truth.",
  remediation:
    "Derive the value from current props when it should stay current. For an intentional mount-time snapshot, retain that lifecycle explicitly, for example with a ref; independently editable drafts keep their updater. Review the intended lifecycle before changing behavior.",
  category: "correctness",
  limitations: [
    "Advisory only: initial snapshots can be intentional. There is no automatic fix because replacing state with current props changes how later updates behave.",
    "Recognizes direct React useState imports and default/namespace member calls, including renamed imports and erased wrappers around imported namespaces, through lexical binding identity. Checks a direct array destructure in a function containing its own JSX and a direct first-parameter property path, or a zero-argument synchronous lazy initializer returning that path.",
    "Eager initializers require parser-owned TypeScript services and primitive types, including unions composed entirely of primitives. Object and void types can hide callable values through structural assignment or ignored return values, so eager nonprimitive values, Any, unknown and unresolved generics are excluded. React executes function arguments as lazy initializers. Explicit zero-argument lazy callbacks returning a prop directly remain supported for all value types without type services. Opaque casts cannot prove runtime identity; lifecycle changes stay manual.",
    "Direct writes to the requested imported namespace member exclude its hook calls. Unknown computed writes exclude all namespace hooks; unrelated member writes and a hook function's own properties do not replace the callable. Reflective mutation and external API patches are not modeled.",
    "An updater read, escape, reassignment or nontrivial destructuring excludes the finding. Unused state values remain owned by unused-variable checks. Files containing direct eval are excluded because it can observe or change lexical bindings. Indirect eval and properties named eval do not establish lexical access. Opaque initialization, property aliases, optional/dynamic paths, rest/default bindings, non-JSX hooks, generated source and tests are outside scope. This does not ban interactive useState or replace the upstream set-state-in-effect rule.",
  ],
  references: [
    "https://react.dev/learn/choosing-the-state-structure",
    "https://react.dev/reference/react/useState",
    "https://react.dev/reference/eslint-plugin-react-hooks/lints/set-state-in-effect",
  ],
  examples: [
    {
      id: "frozen-prop",
      title: "A prop snapshot has no updater",
      outcome: "match",
      files: [{ path: "src/status.tsx", source: BEFORE }, CONFIG],
      focusPath: "src/status.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "current-prop",
      title: "Render the current prop directly",
      outcome: "no-match",
      files: [{ path: "src/status.tsx", source: AFTER }, CONFIG],
      focusPath: "src/status.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
