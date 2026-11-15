/** @fileoverview react-prefer-updater-function — the documentation and executable examples of `@sarj/react-prefer-updater-function`. */

import type { RuleDocumentation } from "../documentation.js";

const CART =
  "import { useState } from 'react'; export function Cart({ load }: { load: () => Promise<string> }) { const [items, setItems] = useState<string[]>([]); const add = async () => { const item = await load(); ";

const CART_END = " }; return <button type=\"button\" onClick={add}>{items.length}</button>; }";

const RENDER_PHASE =
  "import { useState } from 'react'; export function Panel({ request }: { request: boolean }) { const [dialog, setDialog] = useState({ open: request, request }); if (dialog.request !== request) { setDialog({ open: request || dialog.open, request }); } return <p>{String(dialog.open)}</p>; }";

export const REACT_PREFER_UPDATER_FUNCTION_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Use the updater form when the next React state is built from the current state.",
  rationale:
    "A state variable holds the snapshot from the render that created the callback. After an await, in a timer, promise callback, subscription or effect, or when two updates run before React re-renders, that snapshot is stale. `setItems([...items, item])` then drops whatever another update added in the meantime. An updater receives the latest queued state, so each update builds on the one before it.",
  remediation:
    "Pass an updater instead. Rewrite `setItems([...items, item])` as `setItems((previous) => [...previous, item])`, and read `previous` wherever the argument read the state or a local derived from it. Compute IDs, timestamps and other impure values before the call, because React runs updaters twice in Strict Mode development builds.",
  category: "correctness",
  limitations: [
    "The rule is advisory and has no automatic fix. In a synchronous event handler that updates once, the snapshot is still current, so the rewrite keeps today's behavior and protects the handler against a later await or a second update.",
    "The rule pairs a setter with its state through one array destructure of a React useState call, including renamed, default and namespace React imports, and resolves every read by scope. It ignores setters reached through props, aliases or custom hooks that return state tuples. It also ignores object-destructured state, useReducer dispatch and reassigned bindings.",
    "The rule reports only state reads that the setter argument itself evaluates. It ignores reads inside nested functions, type-only reads, a bare identity write and next values first stored in a local. It also ignores setter calls made directly in the function that declares the state, because they run during render, where the state belongs to the render in progress.",
  ],
  references: [
    "https://react.dev/reference/react/useState#updating-state-based-on-the-previous-state",
    "https://react.dev/learn/queueing-a-series-of-state-updates",
    "https://bun.com/docs/lint/rules/bun/react-prefer-updater-function",
  ],
  examples: [
    {
      id: "snapshot-after-await",
      title: "Append to the render snapshot after an await",
      outcome: "match",
      files: [{ path: "src/cart.tsx", source: `${CART}setItems([...items, item]);${CART_END}` }],
      focusPath: "src/cart.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "updater-after-await",
      title: "Append to the latest state through an updater",
      outcome: "no-match",
      files: [{ path: "src/cart.tsx", source: `${CART}setItems((previous) => [...previous, item]);${CART_END}` }],
      focusPath: "src/cart.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "render-phase-update",
      title: "Adjust state from the render in progress",
      outcome: "no-match",
      files: [{ path: "src/panel.tsx", source: RENDER_PHASE }],
      focusPath: "src/panel.tsx",
      expectedCount: 0,
      public: false,
    },
  ],
} as const satisfies RuleDocumentation;
