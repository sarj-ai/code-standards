/** @fileoverview prefer-coordinated-react-state — the documentation and executable examples of `@sarj/prefer-coordinated-react-state`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_COORDINATED_REACT_STATE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Review repeated setter groups adopting fields from one incoming record.",
  rationale:
    "Separately writable fields repeatedly adopted and reset together duplicate the bookkeeping of one record. Future transitions can omit a slot. This is a structural review opportunity, not evidence of an existing inconsistency, a race, or multiple rendered frames.",
  remediation:
    "Review one typed record for the observed slots. Keep independent state separate, preserve every initializer and functional updater, and review all readers, request identities, cancellation, retained data and property evaluation before changing ownership. The rule offers no automatic fix.",
  category: "maintainability",
  limitations: [
    "Also warns on a bounded three-slot editor snapshot: one state initializer directly references another tracked state value, their setters each have exactly one supported write in separate handlers, and both writes are adjacent to the same boolean status setter with complementary literal values. The retained initializer must have a native primitive type, including nullable primitive unions and noncallable primitive brands, so React stores it as data before the other initializer copies it. Callable values, lazy initializers, structural objects, Any, unknown, unresolved generics and unavailable types abstain. Every setter reference must meet the existing completeness proof. Independent streams that merely share a status do not qualify. This copy witness suggests reviewing a typed snapshot; it does not prove equal lifetimes, concurrency safety or permission to rewrite queued requests. No fix is offered.",

    "Warning only, with no fix. A complete group is a maximal set of state slots with the same adjacent write-run membership. Every observed setter reference must be a direct one-argument expression statement in a block. Each slot must have at least two calls, across at least two distinct enclosing transition functions. All slots belong to the same function and have a direct top-level const tuple declaration and an observed value read. Equal write counts alone do not qualify.",
    "At least one complete group must read plain property paths from the same stable parameter or earlier const binding declared in that transition function, including a direct const destructure. This witnesses a common source record, not an immutable object, pure getters, domain intent or whole-program ownership. Shared resets, module captures, separately destructured field aliases, independently rebound roots, computed/optional paths and different local records do not establish that witness.",
    "Uses lexical React provenance for named, renamed, default and namespace useState imports, including erased expression wrappers. Shadowed, foreign, type-only, custom-hook and directly overwritten namespace hooks abstain; the shared provenance helper does not model reflective or external React monkeypatching.",
    "Setter aliases, escapes, onOpenChange props, helper calls, compound expressions, conditional partial writes and independent writers exclude the affected slots. A smaller complete group can remain when another slot has independent writes. Any unsupported RHS excludes that setter: calls, functional updater callbacks, constructors, mutations, suspension, spreads, dynamic or optional paths, and nontrivial expressions are unsupported. Invocation or scheduling statements between setters split their runs. Surrounding async functions and guarded blocks are allowed only for adjacent supported calls; the rule does not analyze async overlap or infer cancellation safety.",
    "Per file, analysis is limited to 200,000 UTF-16 source units, 4,096 AST nodes, sixteen candidate slots and thirty-two references per setter. RHS expressions and property witnesses visit at most eight nested nodes. Exceeding a file budget abstains from the whole file, without partial diagnostics. Setter-reference bounds exclude the affected slot. The existing repeated-setter witness requires no types. Only strong three-slot candidates request one native type batch; the shared primitive classifier visits at most sixteen type levels. Missing or failed type services abstain from that copy advice. State resets in before() and helper caches follow immutable AST/binding identity across files.",
    "One diagnostic is emitted at the first slot declaration for each maximal complete group, in declaration order, naming every slot and its source transition lines. This owner does not infer Boolean exclusion or payload requirements, and does not duplicate the return-contract or prop-snapshot rules. Ordinary exact-code ESLint suppression applies. Generated, declaration and test files, unread values, direct eval and unsupported destructuring are excluded.",
    "Known misses include functional pagination appenders, transformed response fields, one-site adoptions, helper-mediated ownership, controlled dialogs and general loading/data/error workflows. Independent historical latches, drafts, last-error telemetry, materialized indexes and exit-animation payloads require lifecycle review even when a structural group is observed. A maintained warning release and further natural-hit review are required before considering promotion.",
  ],
  references: [
    "https://react.dev/learn/choosing-the-state-structure",
    "https://react.dev/reference/react/useState",
  ],
  examples: [
    {
      id: "copied-editor-snapshot",
      scenarioId: "copied-editor",
      title: "A copied draft and retained value share explicit status transitions",
      outcome: "match",
      files: [
        {
          path: "src/editor.tsx",
          source:
            "import { useState } from 'react'; export function Editor({text}: {text: string}) { const [saved, setSaved] = useState(text); const [draft, setDraft] = useState(saved); const [complete, setComplete] = useState(false); function edit(next) { setDraft(next); setComplete(false); } function committed(next) { setSaved(next); setComplete(true); } return <output>{saved}{draft}{complete}</output>; }",
        },
      ],
      focusPath: "src/editor.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "one-editor-snapshot",
      scenarioId: "copied-editor",
      title: "One editor state owns draft, retained text and status",
      outcome: "no-match",
      files: [
        {
          path: "src/editor.tsx",
          source:
            "import { useState } from 'react'; export function Editor({text}) { const [editor, setEditor] = useState({saved:text, draft:text, complete:false}); function edit(next) { setEditor(current => ({...current, draft:next, complete:false})); } function committed(next) { setEditor(current => ({...current, saved:next, complete:true})); } return <output>{editor.saved}{editor.draft}{editor.complete}</output>; }",
        },
      ],
      focusPath: "src/editor.tsx",
      expectedCount: 0,
      public: true,
    },

    {
      id: "one-record-owner",
      title: "One record preserves the page fields",
      outcome: "no-match",
      files: [
        {
          path: "src/page.tsx",
          source:
            "import { useState } from 'react'; type Page = { rows: string[]; cursor: string | null }; export function View() { const [page, setPage] = useState<Page>({ rows: [], cursor: null }); function adopt(next: Page) { setPage(next); } function reset() { setPage({ rows: [], cursor: null }); } return <button onClick={reset} onDoubleClick={() => adopt({ rows: [], cursor: null })}>{page.rows.length}</button>; }",
        },
      ],
      focusPath: "src/page.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "complete-page-bookkeeping",
      title: "Direct adoption and reset repeat one page's bookkeeping",
      outcome: "match",
      files: [
        {
          path: "src/page.tsx",
          source:
            "import { useState } from 'react'; type Page = { rows: string[]; cursor: string | null }; export function View() { const [rows, setRows] = useState<string[]>([]); const [cursor, setCursor] = useState<string | null>(null); function adopt(page: Page) { setRows(page.rows); setCursor(page.cursor); } function reset() { setRows([]); setCursor(null); } return <button onClick={reset} onDoubleClick={() => adopt({ rows: [], cursor: null })}>{rows.length}{cursor}</button>; }",
        },
      ],
      focusPath: "src/page.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "editable-row-draft",
      title: "An independent editor write preserves its own owner",
      outcome: "no-match",
      files: [
        {
          path: "src/draft.tsx",
          source:
            "import { useState } from 'react'; export function View() { const [text, setText] = useState(''); const [version, setVersion] = useState(0); function adopt(page: {text: string; version: number}) { setText(page.text); setVersion(page.version); } function reset() { setText(''); setVersion(0); } return <input value={text} title={String(version)} onChange={event => setText(event.target.value)} onDoubleClick={reset} onBlur={() => adopt({text:'',version:0})} />; }",
        },
      ],
      focusPath: "src/draft.tsx",
      expectedCount: 0,
    },
  ],
} as const satisfies RuleDocumentation;
