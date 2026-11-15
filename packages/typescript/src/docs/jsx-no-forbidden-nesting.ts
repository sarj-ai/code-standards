/** @fileoverview jsx-no-forbidden-nesting — the documentation and executable examples of `@sarj/jsx-no-forbidden-nesting`. */

import type { RuleDocumentation } from "../documentation.js";

export const JSX_NO_FORBIDDEN_NESTING_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Keep intrinsic JSX elements out of parents whose HTML content model forbids them.",
  rationale:
    "The HTML parser repairs some nestings. A <div> closes an open <p>, a nested <a> or <button> closes the outer one, the parser drops a nested <form>, and a <tr> directly in <table> gains a <tbody>. The browser then builds a DOM from server HTML that differs from the React tree, and React reports a hydration error. Other nestings parse unchanged but stay invalid HTML. Interactive content inside <a> or <button>, <label> inside <label>, and <li> outside a list give inconsistent click, focus and screen-reader behavior.",
  remediation:
    "Make the two elements siblings, or change the outer element to one that accepts the inner one: <div> instead of <p> around blocks, one link per card with the other actions beside it, separate forms or the form attribute instead of nested forms, and <tbody> around table rows. Give a stray <li> a <ul>, <ol> or <menu> parent.",
  category: "correctness",
  requiresTypeInformation: false,
  limitations: [
    "The rule judges only lowercase intrinsic elements whose nesting is visible in one JSX tree. It treats components, member expressions such as motion.div, element aliases, and JSX stored in variables or passed through props or arbitrary calls as opaque, and does not report a nesting that crosses a component boundary.",
    "The rule follows children through fragments, arrays, conditional and logical expressions, and map or flatMap callbacks. It skips SVG and MathML content as foreign, and starts a fresh context at foreignObject and template.",
    "Parser repairs follow React DOM's validateDOMNesting. Content-model checks cover interactive content inside <a> or <button>, <label> inside <label>, and <li> whose parent is not <ul>, <ol> or <menu>. The rule does not count an <a> without an explicit href, an <input> whose type is dynamic or spread, or media without an explicit controls attribute as interactive.",
  ],
  references: [
    "https://html.spec.whatwg.org/multipage/parsing.html#parsing-main-inbody",
    "https://html.spec.whatwg.org/multipage/dom.html#interactive-content",
    "https://github.com/facebook/react/blob/main/packages/react-dom-bindings/src/client/validateDOMNesting.js",
    "https://bun.com/docs/lint/rules/bun/jsx-no-forbidden-nesting",
  ],
  examples: [
    {
      id: "block-outside-paragraph",
      title: "Use a block container around block content",
      outcome: "no-match",
      files: [{ path: "src/note.tsx", source: "export const Note = () => <div><p>Saved</p><div>Undo</div></div>;" }],
      focusPath: "src/note.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "block-inside-paragraph",
      title: "Report a block element inside a paragraph",
      outcome: "match",
      files: [{ path: "src/note.tsx", source: "export const Note = () => <p>Saved<div>Undo</div></p>;" }],
      focusPath: "src/note.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "card-actions-as-siblings",
      scenarioId: "card-link",
      title: "Keep card actions beside the card link",
      outcome: "no-match",
      files: [
        {
          path: "src/card.tsx",
          source:
            'export const Card = () => (\n  <article>\n    <a href="/report">Report</a>\n    <button type="button">Share</button>\n  </article>\n);',
        },
      ],
      focusPath: "src/card.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "button-inside-link",
      scenarioId: "card-link",
      title: "Report interactive content inside a link",
      outcome: "match",
      files: [
        {
          path: "src/card.tsx",
          source:
            'export const Card = () => (\n  <a href="/report">\n    Report\n    <button type="button">Share</button>\n  </a>\n);',
        },
      ],
      focusPath: "src/card.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "rows-in-table-body",
      scenarioId: "table-rows",
      title: "Wrap mapped rows in a table body",
      outcome: "no-match",
      files: [
        {
          path: "src/table.tsx",
          source:
            "export const Rows = ({ ids }: { ids: string[] }) => (\n  <table>\n    <tbody>{ids.map((id) => <tr key={id}><td>{id}</td></tr>)}</tbody>\n  </table>\n);",
        },
      ],
      focusPath: "src/table.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "rows-directly-in-table",
      scenarioId: "table-rows",
      title: "Report mapped rows directly inside a table",
      outcome: "match",
      files: [
        {
          path: "src/table.tsx",
          source:
            "export const Rows = ({ ids }: { ids: string[] }) => (\n  <table>{ids.map((id) => <tr key={id}><td>{id}</td></tr>)}</table>\n);",
        },
      ],
      focusPath: "src/table.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "component-boundary",
      title: "Leave nesting across a component boundary to review",
      outcome: "no-match",
      files: [
        {
          path: "src/panel.tsx",
          source:
            "declare function Section(props: { children: React.ReactNode }): React.ReactNode;\nexport const Panel = () => <p><Section><div>Body</div></Section></p>;",
        },
      ],
      focusPath: "src/panel.tsx",
      expectedCount: 0,
      public: false,
    },
  ],
} as const satisfies RuleDocumentation;
