import { spawnSync } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";

import { expect, it } from "vitest";

import { RULES } from "../../src/catalog.js";
import rule from "../../src/rules/prefer-coordinated-react-state.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import { FIXTURES, ruleTester, typed, untyped } from "./_tester.js";

const PREFIX = "import { useState } from 'react'; ";
const BODY = `export function View() {
  const [rows, setRows] = useState<string[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  function adopt(page: {rows: string[]; cursor: string | null}) {
    setRows(page.rows);
    setCursor(page.cursor);
  }
  function reset() {
    setRows([]);
    setCursor(null);
  }
  return <button onClick={reset} onDoubleClick={() => adopt({rows: [], cursor: null})}>{rows.length}{cursor}</button>;
}`;
const SOURCE = PREFIX + BODY;
const ERROR = { messageId: "preferCoordinatedReactState" };

const EDITOR =
  PREFIX +
  `export function Editor({text}: {text: string}) {
  const [saved, setSaved] = useState(text);
  const [draft, setDraft] = useState(saved);
  const [complete, setComplete] = useState(false);
  function edit(next) { setDraft(next); setComplete(false); }
  function committed(next) { setSaved(next); setComplete(true); }
  return <output>{saved}{draft}{complete}</output>;
}`;

ruleTester({ lang: "tsx" }).run(
  "prefer-coordinated-react-state",
  rule,
  untyped({
    valid: [
      { name: "copy advice abstains without native types", code: EDITOR },
      {
        name: "function state passed as an initializer is invoked rather than copied",
        code:
          PREFIX +
          "export function View() { const [saved,setSaved]=useState<(()=>string)|null>(()=>()=> 'seed'); const [draft,setDraft]=useState<string|null>(saved); const [complete,setComplete]=useState(false); function edit(next:string){setDraft(next);setComplete(false);} function finish(){setSaved(null);setComplete(true);} return <output>{draft}{saved===null}{complete}</output>; }",
      },
      {
        name: "independent streams sharing a status are not one snapshot",
        code: EDITOR.replace("useState(saved)", "useState(other)"),
      },
      {
        name: "a solo draft writer keeps its own lifetime",
        code: EDITOR.replace(
          "  return <output>",
          "  function reset() {setDraft('');} return <output>",
        ),
      },
      {
        name: "same status without complementary transitions abstains",
        code: EDITOR.replace("setComplete(true)", "setComplete(false)"),
      },
      {
        name: "copied state with an escaping setter abstains",
        code: EDITOR.replace("  return <output>", "  expose(setDraft); return <output>"),
      },

      {
        name: "one record already owns the page",
        code:
          PREFIX +
          "export function View() { const [page, setPage] = useState({rows: [], cursor: null}); function adopt(next) {setPage(next);} function reset() {setPage({rows: [], cursor: null});} return <output>{page.cursor}</output>; }",
      },
      {
        name: "five independent fields only share resets",
        code:
          PREFIX +
          "export function View() { const [a,A]=useState(0);const [b,B]=useState(0);const [c,C]=useState(0);const [d,D]=useState(0);const [e,E]=useState(0);function reset(){A(0);B(0);C(0);D(0);E(0);}function clear(){A(0);B(0);C(0);D(0);E(0);}return <output>{a}{b}{c}{d}{e}</output>;}",
      },
      {
        name: "one transition site is insufficient",
        code: SOURCE.replace("    setRows([]);\n    setCursor(null);", ""),
      },
      {
        name: "independent writer excludes the edited slot",
        code: SOURCE.replace(
          "  return <button",
          "  function edit() { setRows([]); } return <button",
        ),
      },
      {
        name: "equal counts under separate guards are not complete writes",
        code: SOURCE.replace(
          "    setCursor(page.cursor);",
          "    if (page.cursor) setCursor(page.cursor);",
        ),
      },
      {
        name: "early return splits a transition",
        code: SOURCE.replace(
          "    setCursor(page.cursor);",
          "    if (stopped) return; setCursor(page.cursor);",
        ),
      },
      {
        name: "separate conditional blocks do not share an event",
        code: SOURCE.replace(
          "    setRows(page.rows);\n    setCursor(page.cursor);",
          "    if (a) {setRows(page.rows);} if (b) {setCursor(page.cursor);}",
        ),
      },
      {
        name: "helper-mediated writes are outside direct ownership",
        code: SOURCE.replace("    setRows(page.rows);", "    update(setRows, page.rows);"),
      },
      {
        name: "setter alias escapes completeness",
        code: SOURCE.replace("  return <button", "  const update = setCursor; return <button"),
      },
      {
        name: "controlled dialog setter escapes",
        code: SOURCE.replace("<button onClick", "<button onOpenChange={setCursor} onClick"),
      },
      {
        name: "a returned setter escapes",
        code: SOURCE.replace("  return <button", "  expose({ setRows }); return <button"),
      },
      {
        name: "a setter captured as a call argument escapes",
        code: SOURCE.replace("  return <button", "  schedule(setRows); return <button"),
      },
      {
        name: "setter rebinding abstains",
        code: SOURCE.replace("const [cursor, setCursor]", "let [cursor, setCursor]").replace(
          "  return <button",
          "  setCursor = other; return <button",
        ),
      },
      {
        name: "state rebinding abstains",
        code: SOURCE.replace("const [rows, setRows]", "let [rows, setRows]"),
      },
      {
        name: "unread state belongs to unused-variable rules",
        code: SOURCE.replace("{rows.length}{cursor}", "{cursor}"),
      },
      {
        name: "a type query is not a runtime state read",
        code: SOURCE.replace(
          "  return <button",
          "  type Rows = typeof rows; return <button",
        ).replace("{rows.length}{cursor}", "{cursor}"),
      },
      {
        name: "foreign hooks have no React identity",
        code: SOURCE.replace("from 'react'", "from './hooks'"),
      },
      {
        name: "custom hooks are not inferred",
        code: SOURCE.replaceAll("useState", "useLocalState"),
      },
      {
        name: "shadowed React import is not the imported hook",
        code: SOURCE.replace("function View()", "function View(useState)"),
      },
      {
        name: "type-only React import has no value identity",
        code: SOURCE.replace("import {", "import type {"),
      },
      {
        name: "replaced namespace hook abstains",
        code: SOURCE.replace(PREFIX, "import R from 'react'; R.useState = other; ").replaceAll(
          "= useState",
          "= R.useState",
        ),
      },
      {
        name: "unknown namespace write abstains",
        code: SOURCE.replace(PREFIX, "import * as R from 'react'; R[key] = other; ").replaceAll(
          "= useState",
          "= R.useState",
        ),
      },
      {
        name: "rest destructures are unsupported",
        code: SOURCE.replace("[cursor, setCursor]", "[cursor, ...setCursor]"),
      },
      {
        name: "conditional hook placement is not an ownership proof",
        code: SOURCE.replace("  const [rows", "  if (enabled) { const [rows").replace(
          "  function adopt",
          "  } function adopt",
        ),
      },
      {
        name: "a different incoming root does not establish a record",
        code: SOURCE.replace("setCursor(page.cursor)", "setCursor(other.cursor)"),
      },
      {
        name: "a mutable incoming parameter is not stable",
        code: SOURCE.replace("    setRows(page.rows);", "    page = other; setRows(page.rows);"),
      },
      {
        name: "module record captures remain outside the local witness",
        code: SOURCE.replace(
          "function adopt(page: {rows: string[]; cursor: string | null})",
          "function adopt()",
        ),
      },
      {
        name: "optional record reads remain unsupported",
        code: SOURCE.replace("page.rows", "page?.rows"),
      },
      {
        name: "computed record reads remain unsupported",
        code: SOURCE.replace("page.cursor", "page['cursor']"),
      },
      {
        name: "functional appenders retain their callback semantics",
        code: SOURCE.replace(
          "setRows(page.rows)",
          "setRows(current => [...current, ...page.rows])",
        ),
      },
      {
        name: "transformed response fields remain unsupported",
        code: SOURCE.replace("setRows(page.rows)", "setRows(page.rows.map(convert))"),
      },
      {
        name: "function-valued resets remain unsupported",
        code: SOURCE.replace("setRows([])", "setRows(() => [])"),
      },
      {
        name: "an awaited RHS breaks the direct-write proof",
        code: SOURCE.replace("function adopt(", "async function adopt(").replace(
          "setRows(page.rows)",
          "setRows(await page.rows)",
        ),
      },
      {
        name: "a suspension between writes splits their run",
        code: SOURCE.replace("function adopt(", "async function adopt(").replace(
          "    setCursor(page.cursor);",
          "    await pause(); setCursor(page.cursor);",
        ),
      },
      {
        name: "separately scheduled callbacks are distinct sites",
        code: SOURCE.replace(
          "setCursor(page.cursor);",
          "queueMicrotask(() => { setCursor(page.cursor); });",
        ),
      },
      {
        name: "compound call expressions are unsupported",
        code: SOURCE.replace(
          "setRows(page.rows);\n    setCursor(page.cursor);",
          "(setRows(page.rows), setCursor(page.cursor));",
        ),
      },
      {
        name: "direct eval can observe undeclared writers",
        code: SOURCE.replace("  return <button", "  eval('setRows([])'); return <button"),
      },
      { name: "generated inputs skip ownership advice", filename: "page.gen.tsx", code: SOURCE },
      { name: "generated markers skip ownership advice", code: "// @generated\n" + SOURCE },
      {
        name: "declaration inputs skip ownership advice",
        filename: "page.d.ts",
        code: "export declare function View(): void;",
      },
      { name: "test inputs skip ownership advice", filename: "page.test.tsx", code: SOURCE },
      {
        name: "too many slots abstain from the whole file",
        code: SOURCE.replace(
          "  function adopt",
          Array.from({ length: 15 }, (_, i) => `const [v${i},s${i}]=useState(0); void v${i};`).join(
            "",
          ) + "  function adopt",
        ),
      },
      {
        name: "the whole-file node budget emits no partial report",
        code: SOURCE + `const padding=[${Array.from({ length: 4100 }, () => "0").join(",")}];`,
      },
      {
        name: "source budget emits no partial report",
        code: SOURCE + "/*" + "x".repeat(200_000) + "*/",
      },
      {
        name: "setter-reference budget excludes that slot",
        code: SOURCE.replace(
          "  return <button",
          Array.from({ length: 33 }, (_, i) => `type Setter${i} = typeof setRows;`).join("") +
            " return <button",
        ),
      },
      {
        name: "overlong property witnesses abstain",
        code: SOURCE.replace("page.rows", "page.a.b.c.d.e.f.g.h.rows").replace(
          "page.cursor",
          "page.a.b.c.d.e.f.g.h.cursor",
        ),
      },
      {
        name: "all repeated writes in a single transition function are insufficient",
        code: SOURCE.replace("  }\n  function reset() {", "    if (resetting) {").replace(
          "    setCursor(null);",
          "    setCursor(null); }",
        ),
      },
    ],
    invalid: [
      {
        name: "one complete direct page group",
        code: SOURCE,
        output: null,
        errors: [{ ...ERROR, line: 2, data: { fields: "rows`, `cursor", sites: "5, 9" } }],
      },
      {
        name: "renamed React import uses lexical identity",
        code: SOURCE.replaceAll("useState", "state").replace(
          "import { state }",
          "import { useState as state }",
        ),
        output: null,
        errors: [ERROR],
      },
      {
        name: "namespace React import",
        code: SOURCE.replace(PREFIX, "import * as R from 'react'; ").replaceAll(
          "= useState",
          "= R.useState",
        ),
        output: null,
        errors: [ERROR],
      },
      {
        name: "default React import with erased namespace wrappers",
        code: SOURCE.replace(PREFIX, "import R from 'react'; ").replaceAll(
          "= useState",
          "= (R as typeof R).useState",
        ),
        output: null,
        errors: [ERROR],
      },
      {
        name: "unrelated namespace writes preserve hook identity",
        code: SOURCE.replace(PREFIX, "import R from 'react'; R.useReducer = other; ").replaceAll(
          "= useState",
          "= R.useState",
        ),
        output: null,
        errors: [ERROR],
      },
      {
        name: "a hook can own the same complete local state",
        code: SOURCE.replace(
          "return <button onClick={reset} onDoubleClick={() => adopt({rows: [], cursor: null})}>{rows.length}{cursor}</button>",
          "return { rows, cursor, adopt, reset }",
        ),
        output: null,
        errors: [ERROR],
      },
      {
        name: "an earlier transition-local const record is a witness",
        code: SOURCE.replace(
          "function adopt(page: {rows: string[]; cursor: string | null}) {",
          "async function adopt() { const page = await loadPage();",
        ),
        output: null,
        errors: [ERROR],
      },
      {
        name: "a transition-local destructured const record is a witness",
        code: SOURCE.replace(
          "function adopt(page: {rows: string[]; cursor: string | null}) {",
          "async function adopt() { const [other, page] = await loadPages();",
        ),
        output: null,
        errors: [ERROR],
      },
      {
        name: "synchronous guarded groups retain identical membership",
        code: SOURCE.replace(
          "    setRows(page.rows);",
          "    if (accept) { setRows(page.rows);",
        ).replace("    setCursor(page.cursor);", "    setCursor(page.cursor); }"),
        output: null,
        errors: [ERROR],
      },
      {
        name: "type-only setter reads do not escape runtime ownership",
        code: SOURCE.replace(
          "  return <button",
          "  type CursorSetter = typeof setCursor; return <button",
        ),
        output: null,
        errors: [ERROR],
      },
      {
        name: "the setter-reference boundary retains complete groups",
        code: SOURCE.replace(
          "  return <button",
          Array.from({ length: 29 }, (_, i) => `type Setter${i} = typeof setRows;`).join("") +
            " return <button",
        ),
        output: null,
        errors: [ERROR],
      },
      {
        name: "a third member gets one maximal group diagnostic",
        code: SOURCE.replace(
          "  function adopt",
          "  const [total, setTotal] = useState(0); function adopt",
        )
          .replace("setCursor(page.cursor);", "setCursor(page.cursor); setTotal(page.total);")
          .replace("setCursor(null);", "setCursor(null); setTotal(0);")
          .replace("{rows.length}{cursor}", "{rows.length}{cursor}{total}"),
        output: null,
        errors: [ERROR],
      },
      {
        name: "an independently written third slot leaves the smaller complete group",
        code: SOURCE.replace(
          "  function adopt",
          "  const [total, setTotal] = useState(0); function edit() {setTotal(1);} function adopt",
        )
          .replace("setCursor(page.cursor);", "setCursor(page.cursor); setTotal(page.total);")
          .replace("setCursor(null);", "setCursor(null); setTotal(0);")
          .replace("{rows.length}{cursor}", "{rows.length}{cursor}{total}"),
        output: null,
        errors: [ERROR],
      },
      {
        name: "call order can differ across complete sites",
        code: SOURCE.replace(
          "setRows([]);\n    setCursor(null);",
          "setCursor(null);\n    setRows([]);",
        ),
        output: null,
        errors: [ERROR],
      },
      {
        name: "comments are retained because the advisory has no fix",
        code: SOURCE.replace(
          "    setCursor(page.cursor);",
          "    // Keep property evaluation order.\n    setCursor(page.cursor);",
        ),
        output: null,
        errors: [ERROR],
      },
      {
        name: "intentional mirrors are structural advice only",
        code: SOURCE.replaceAll("rows", "index").replaceAll("cursor", "telemetry"),
        output: null,
        errors: [ERROR],
      },
    ],
  }),
);

ruleTester({ lang: "tsx", cwd: join(FIXTURES, "minimal-consumer") }).run(
  "primitive copied snapshots",
  rule,
  typed({
    valid: [
      {
        name: "callable state keeps initializer execution",
        filename: "probe.tsx",
        code:
          PREFIX +
          "export function View() { const [saved,setSaved]=useState<(()=>string)|null>(()=>()=> 'seed'); const [draft,setDraft]=useState<string|null>(saved); const [complete,setComplete]=useState(false); function edit(next:string){setDraft(next);setComplete(false);} function finish(){setSaved(null);setComplete(true);} return <output>{draft}{saved===null}{complete}</output>; }",
      },
      {
        name: "lazy retained initializers do not prove a copy",
        filename: "probe.tsx",
        code: EDITOR.replace("useState(text)", "useState(() => text)"),
      },
      {
        name: "structural object types can hide callable values",
        filename: "probe.tsx",
        code: EDITOR.replace("text: string", "text: { label: string }"),
      },
      {
        name: "unknown values do not prove a copy",
        filename: "probe.tsx",
        code: EDITOR.replace("text: string", "text: unknown"),
      },
      {
        name: "any values do not prove a copy",
        filename: "probe.tsx",
        code: EDITOR.replace("text: string", "text: any"),
      },
      {
        name: "callable primitive intersections keep initializer execution",
        filename: "probe.tsx",
        code: EDITOR.replace("text: string", "text: string & (() => string)"),
      },
      {
        name: "unresolved generics do not prove a primitive copy",
        filename: "probe.tsx",
        code: EDITOR.replace("Editor({text}", "Editor<T>({text}").replace(
          "text: string",
          "text: T",
        ),
      },
    ],
    invalid: [
      {
        name: "copied draft retained text and explicit completion status",
        filename: "probe.tsx",
        code: EDITOR,
        output: null,
        errors: [{ messageId: "copiedSnapshotState" }],
      },
      {
        name: "renaming snapshot fields does not change the witness",
        filename: "probe.tsx",
        code: EDITOR.replaceAll("saved", "retained")
          .replaceAll("draft", "editing")
          .replaceAll("complete", "current"),
        output: null,
        errors: [{ messageId: "copiedSnapshotState" }],
      },
      {
        name: "nullable primitive copies retain their witness",
        filename: "probe.tsx",
        code: EDITOR.replace("text: string", "text: string | null"),
        output: null,
        errors: [{ messageId: "copiedSnapshotState" }],
      },
      {
        name: "noncallable primitive brands retain their witness",
        filename: "probe.tsx",
        code: EDITOR.replace("text: string", "text: string & {readonly brand: 'text'}"),
        output: null,
        errors: [{ messageId: "copiedSnapshotState" }],
      },
    ],
  }),
);

it("executes the documented examples", async () => {
  await expect(
    verifyRuleExamples(RULES["prefer-coordinated-react-state"]),
  ).resolves.toBeGreaterThan(0);
});

it("isolates consecutive native files, honors exact suppression, and preserves warning exit policy", async () => {
  const root = await mkdtemp(join(tmpdir(), "sarj-coordinated-state-"));
  try {
    const config = join(root, "oxlint.json");
    const first = join(root, "first.tsx");
    const shadow = join(root, "shadow.tsx");
    const suppressed = join(root, "suppressed.tsx");
    const last = join(root, "last.tsx");
    await Promise.all([
      writeFile(
        config,
        JSON.stringify({
          plugins: [],
          categories: { correctness: "off" },
          jsPlugins: [
            { name: "@sarj", specifier: join(import.meta.dirname, "../../dist/index.js") },
          ],
          rules: { "@sarj/prefer-coordinated-react-state": "warn" },
        }),
      ),
      writeFile(
        first,
        SOURCE.replace(
          "  const [rows",
          "  // eslint-disable-next-line @sarj/no-readonly-prop-state -- This separate rule does not own the setter group.\n  const [rows",
        ),
      ),
      writeFile(shadow, SOURCE.replace("function View()", "function View(useState)")),
      writeFile(
        suppressed,
        SOURCE.replace(
          "  const [rows",
          "  // eslint-disable-next-line @sarj/prefer-coordinated-react-state -- Independently retained protocol mirror.\n  const [rows",
        ),
      ),
      writeFile(last, SOURCE),
    ]);
    const executable = join(import.meta.dirname, "../../node_modules/.bin/oxlint");
    const argv = [
      "--config",
      config,
      "--threads",
      "1",
      "--format",
      "json",
      first,
      shadow,
      suppressed,
      last,
    ];
    const result = spawnSync(executable, argv, { cwd: root, encoding: "utf8", timeout: 30_000 });
    expect(result.status).toBe(0);
    const report = JSON.parse(result.stdout) as {
      diagnostics: { code: string; filename: string; severity: string }[];
    };
    expect(
      report.diagnostics.map(({ filename, severity }) => ({
        filename: basename(filename),
        severity,
      })),
    ).toEqual([
      { filename: "first.tsx", severity: "warning" },
      { filename: "last.tsx", severity: "warning" },
    ]);
    expect(
      spawnSync(executable, [...argv, "--deny-warnings"], {
        cwd: root,
        encoding: "utf8",
        timeout: 30_000,
      }).status,
    ).toBe(1);
    expect(rule.meta.fixable).toBeUndefined();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
