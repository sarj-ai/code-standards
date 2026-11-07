/** @fileoverview prefer-server-data-preparation — the documentation and executable examples of `@sarj/prefer-server-data-preparation`. */

import type { RuleDocumentation } from "../documentation.js";

const BEFORE =
  "'use client'; import { useState } from 'react'; export function Options({ rows }: { rows: readonly { language: string }[] }) { const [selected, setSelected] = useState(''); const languages = rows.map(row => row.language); return <select value={selected} onChange={event => setSelected(event.target.value)}>{languages.map(language => <option key={language}>{language}</option>)}</select>; }";

const AFTER =
  "'use client'; import { useState } from 'react'; export function Options({ languages }: { languages: readonly string[] }) { const [selected, setSelected] = useState(''); return <select value={selected} onChange={event => setSelected(event.target.value)}>{languages.map(language => <option key={language}>{language}</option>)}</select>; }";

const CONFIG = {
  path: "tsconfig.json",
  source:
    '{"compilerOptions":{"strict":true,"target":"ESNext","module":"ESNext","moduleResolution":"Bundler","jsx":"preserve"},"include":["src/**/*"]}',
} as const;

export const PREFER_SERVER_DATA_PREPARATION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary:
    "Prepare data-only input collections before an interactive client view when possible.",
  rationale:
    "Preparing display data where its inputs are loaded can reduce browser work, payloads and knowledge of server data shapes. A small client component can receive the values its interaction actually needs.",
  remediation:
    "When these inputs are available on the server, prepare the collection in its loader or Server Component and pass the prepared values. Otherwise lift the projection to the owning producer when useful. Keep unsaved edits, browser-dependent values and interactive filtering reactive in the client; review callers before moving anything.",
  category: "architecture",
  limitations: [
    "Advisory only. Local syntax cannot establish whether a caller is a Server Component, whether props change interactively or whether server preparation reduces the total cost. This rule is a review lead, never proof that code can be moved to the server. No automatic fix is provided.",
    "Requires an explicit use client directive and parser-owned TypeScript services resolving map/filter/flatMap to the standard Array or ReadonlyArray library signature. The receiver beneath erased wrappers must itself have an Array, ReadonlyArray or tuple type after nullish narrowing; casts from opaque or custom collections do not establish this. Subclass and structural collection types outside those native array types are excluded. The containing view must have an independent React useState/useReducer call or a native callable type on an intrinsic DOM onClick/onChange/onInput/onSubmit handler. Nullish, noncallable and opaque handler types do not establish interaction. Noninteractive boundaries remain owned by no-unnecessary-use-client; custom hooks and indirect client requirements are unsupported.",
    "Every runtime reference to the source parameter binding must be a supported native data projection or a field-only JSX display loop. Inputs also needed for editing, whole-record forwarding, lookup, mutation, other fields or opaque helpers are excluded. Files containing direct eval are excluded because it can observe or change lexical bindings; indirect eval and properties named eval do not establish lexical access. Only direct first-parameter paths and synchronous single-expression callbacks are supported. Whole-row identity maps and constant maps are excluded; supported projections must read a fixed input field.",
    "Field-only object and dense array literals can form nested data shapes, including readonly tuples and flatMap outputs. Array holes, spreads, captured values and JSX outputs remain unsupported. Hook recognition follows erased namespace wrappers and excludes direct writes to the requested imported member; reflective or external API patches are not modeled.",
    "JSX-rendering callbacks are never reported as preparation findings. Callback calls, captured values, destructuring defaults/rest/nesting, async callbacks, event handlers, effects, memo callbacks, opaque helpers, dynamic/optional paths, custom collection signatures, missing type services, generated source and tests are excluded. First-parameter provenance is syntactic; annotations cannot prove absence of runtime getters or patched array methods. Analysis does not claim callback purity or preserve semantics of a hypothetical move.",
    "Reports the direct source projection once; chained operations with a call receiver are not independently reported. A static subprojection may still be prepared by its producer while a union with pending local edits remains in the client.",
  ],
  references: [
    "https://nextjs.org/docs/app/getting-started/server-and-client-components",
    "https://react.dev/learn/you-might-not-need-an-effect",
  ],
  examples: [
    {
      id: "client-projection",
      title: "Prepare data before the client view when possible",
      outcome: "match",
      files: [{ path: "src/options.tsx", source: BEFORE }, CONFIG],
      focusPath: "src/options.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "prepared-values",
      title: "The client receives prepared language values",
      outcome: "no-match",
      files: [{ path: "src/options.tsx", source: AFTER }, CONFIG],
      focusPath: "src/options.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
