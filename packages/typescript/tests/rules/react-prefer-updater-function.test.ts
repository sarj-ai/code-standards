import { expect, it } from "vitest";

import { RULES } from "../../src/catalog.js";
import rule from "../../src/rules/react-prefer-updater-function.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import { ruleTester } from "./_tester.js";

const IMPORT = "import { useEffect, useReducer, useRef, useState } from 'react'; ";
const LIST = "const [items, setItems] = useState<string[]>([]);";
const COUNT = "const [count, setCount] = useState(0);";

function view(state: string, body: string, imports = IMPORT): string {
  return `${imports}export function View({ item, load }: { item: string; load: () => Promise<string> }) { ${state} ${body} return null; }`;
}

const STALE = { messageId: "preferUpdaterFunction" } as const;

ruleTester({ lang: "tsx" }).run("react-prefer-updater-function", rule, {
  valid: [
    { name: "array updater", filename: "view.tsx", code: view(LIST, "const add = () => setItems((previous) => [...previous, item]);") },
    { name: "function-expression updater", filename: "view.tsx", code: view(LIST, "const add = () => setItems(function (previous) { return [...previous, item]; });") },
    { name: "updater behind an erased cast", filename: "view.tsx", code: view(LIST, "const add = () => setItems(((previous: string[]) => [...previous, item]) as (previous: string[]) => string[]);") },
    { name: "updater parameter shadows the state", filename: "view.tsx", code: view(LIST, "const add = () => setItems((items) => [...items, item]);") },
    { name: "new value does not read the state", filename: "view.tsx", code: view(LIST, "const reset = () => setItems([item]);") },
    { name: "spread of another value", filename: "view.tsx", code: view("const [filters, setFilters] = useState({ page: 1 }); const defaults = { page: 1 };", "const reset = () => setFilters({ ...defaults });") },
    { name: "identity write", filename: "view.tsx", code: view(LIST, "const keep = () => setItems(items);") },
    { name: "identity write behind an erased cast", filename: "view.tsx", code: view(LIST, "const keep = () => setItems(items as string[]);") },
    { name: "shadowed state in a callback parameter", filename: "view.tsx", code: view(LIST, "const merge = (items: string[]) => setItems([...items, item]);") },
    { name: "shadowed state in a block", filename: "view.tsx", code: view(LIST, "const seed = () => { const items = ['first']; setItems([...items, item]); };") },
    { name: "shadowed setter parameter", filename: "view.tsx", code: view(LIST, "const apply = (setItems: (next: string[]) => void) => setItems([...items, item]);") },
    { name: "another state's setter", filename: "view.tsx", code: view(`${COUNT} const [total, setTotal] = useState(0);`, "const sync = () => setTotal(count + 1);") },
    { name: "property spelled like the state", filename: "view.tsx", code: view(COUNT, "const sync = (stats: { count: number }) => setCount(stats.count + 1);") },
    { name: "object key spelled like the state", filename: "view.tsx", code: view(LIST, "const reset = () => setItems(Object.values({ items: item }));") },
    { name: "state read only inside a nested function", filename: "view.tsx", code: view("const [handlers, setHandlers] = useState({ done: () => {} });", "const rebind = () => setHandlers({ done: () => console.info(handlers) });") },
    { name: "type-only state read", filename: "view.tsx", code: view(LIST, "const reset = () => setItems([] as typeof items);") },
    { name: "ref read with a state-like member", filename: "view.tsx", code: view(`${COUNT} const latest = useRef(0);`, "const sync = () => setCount(latest.current + 1);") },
    { name: "local alias is outside the direct-argument model", filename: "view.tsx", code: view(LIST, "const add = () => { const next = [...items, item]; setItems(next); };") },
    { name: "aliased setter is outside the binding model", filename: "view.tsx", code: view(LIST, "const update = setItems; const add = () => update([...items, item]);") },
    { name: "object-destructured state is outside the binding model", filename: "view.tsx", code: view("const [{ total }, setStats] = useState({ total: 0 });", "const add = () => setStats({ total: total + 1 });") },
    { name: "spread arguments", filename: "view.tsx", code: view(LIST, "const add = (...next: [string[]]) => setItems(...next);") },
    { name: "extra arguments", filename: "view.tsx", code: view(LIST, "const add = () => (setItems as (next: string[], tag: string) => void)([...items, item], 'tag');") },
    { name: "reassigned setter", filename: "view.tsx", code: view("let [count, setCount] = useState(0);", "setCount = (next: number) => console.info(next); const add = () => setCount(count + 1);") },
    { name: "reassigned state", filename: "view.tsx", code: view("let [count, setCount] = useState(0);", "count = 2; const add = () => setCount(count + 1);") },
    { name: "useReducer dispatch", filename: "view.tsx", code: view("const [state, dispatch] = useReducer((current: string[], next: string[]) => next, []);", "const add = () => dispatch([...state, item]);") },
    {
      name: "custom hook returning the state tuple",
      filename: "view.tsx",
      code: `${IMPORT}function useList() { return useState<string[]>([]); } export function View({ item }: { item: string }) { const [items, setItems] = useList(); const add = () => setItems([...items, item]); return null; }`,
    },
    {
      name: "setter received as a prop",
      filename: "view.tsx",
      code: `${IMPORT}function Editor({ items, setItems }: { items: string[]; setItems: (next: string[]) => void }) { return <button type="button" onClick={() => setItems([...items, 'next'])} />; } export function View() { ${LIST} return <Editor items={items} setItems={setItems} />; }`,
    },
    {
      name: "setter read through props",
      filename: "view.tsx",
      code: `${IMPORT}export function Editor(props: { items: string[]; setItems: (next: string[]) => void }) { return <button type="button" onClick={() => props.setItems([...props.items, 'next'])} />; }`,
    },
    { name: "useState from another module", filename: "view.tsx", code: view(LIST, "const add = () => setItems([...items, item]);", "import { useState } from './store'; ") },
    { name: "type-only React import", filename: "view.tsx", code: view(LIST, "const add = () => setItems([...items, item]);", "import type { useState } from 'react'; ") },
    { name: "local useState shadows React", filename: "view.tsx", code: `${IMPORT}export function View({ item, useState }: { item: string; useState: <T>(value: T) => [T, (next: T) => void] }) { ${LIST} const add = () => setItems([...items, item]); return null; }` },
    { name: "render-phase update from the previous render", filename: "view.tsx", code: view("const [dialog, setDialog] = useState({ open: false, request: item });", "if (dialog.request !== item) { setDialog({ open: dialog.open, request: item }); }") },
    {
      name: "render-phase update in a custom hook",
      filename: "view.ts",
      code: `${IMPORT}export function useOpeningCount(open: boolean) { const [opening, setOpening] = useState({ count: 0, open }); if (opening.open !== open) setOpening({ count: opening.count + 1, open }); return opening.count; }`,
    },
    { name: "generated module", filename: "view.tsx", code: `// @generated\n${view(LIST, "const add = () => setItems([...items, item]);")}` },
  ],
  invalid: [
    { name: "array spread in a handler", filename: "view.tsx", code: view(LIST, "const add = () => setItems([...items, item]);"), errors: [{ ...STALE, data: { setter: "setItems", state: "items" } }] },
    { name: "arithmetic on the state", filename: "view.tsx", code: view(COUNT, "const increment = () => setCount(count + 1);"), errors: [STALE] },
    { name: "object spread", filename: "view.tsx", code: view("const [form, setForm] = useState({ name: '', email: '' });", "const rename = (name: string) => setForm({ ...form, name });"), errors: [STALE] },
    { name: "after an await", filename: "view.tsx", code: view(LIST, "const add = async () => { const next = await load(); setItems([...items, next]); };"), errors: [STALE] },
    { name: "promise continuation", filename: "view.tsx", code: view(LIST, "const add = () => load().then((next) => setItems([...items, next]));"), errors: [STALE] },
    { name: "timer inside an effect", filename: "view.tsx", code: view(COUNT, "useEffect(() => { const id = setInterval(() => setCount(count + 1), 1000); return () => clearInterval(id); }, [count]);"), errors: [STALE] },
    { name: "two writes in one handler", filename: "view.tsx", code: view(COUNT, "const twice = () => { setCount(count + 1); setCount(count + 1); };"), errors: [STALE, STALE] },
    { name: "member call on the state", filename: "view.tsx", code: view(LIST, "const remove = () => setItems(items.filter((value) => value !== item));"), errors: [STALE] },
    { name: "member read on the state", filename: "view.tsx", code: view("const [count, setCount] = useState({ value: 0 });", "const increment = () => setCount({ value: count.value + 1 });"), errors: [STALE] },
    { name: "optional member read on the state", filename: "view.tsx", code: view("const [user, setUser] = useState<{ name: string } | null>(null);", "const rename = () => setUser({ name: user?.name ?? item });"), errors: [STALE] },
    { name: "toggle", filename: "view.tsx", code: view("const [open, setOpen] = useState(false);", "const toggle = () => setOpen(!open);"), errors: [STALE] },
    { name: "conditional on the state", filename: "view.tsx", code: view("const [selected, setSelected] = useState<string | null>(null);", "const pick = () => setSelected(selected === item ? null : item);"), errors: [STALE] },
    { name: "template built from the state", filename: "view.tsx", code: view("const [label, setLabel] = useState('');", "const append = () => setLabel(`${label}${item}`);"), errors: [STALE] },
    { name: "state read beside a nested callback", filename: "view.tsx", code: view(LIST, "const trim = () => setItems(items.map((value) => (value === item ? value.trim() : value)));"), errors: [STALE] },
    { name: "names that ignore the setX convention", filename: "view.tsx", code: view("const [rows, update] = useState<string[]>([]);", "const add = () => update([...rows, item]);"), errors: [{ ...STALE, data: { setter: "update", state: "rows" } }] },
    { name: "renamed React import", filename: "view.tsx", code: view("const [items, setItems] = useLocalState<string[]>([]);", "const add = () => setItems([...items, item]);", "import { useState as useLocalState } from 'react'; "), errors: [STALE] },
    { name: "namespace React import", filename: "view.tsx", code: view("const [items, setItems] = React.useState<string[]>([]);", "const add = () => setItems([...items, item]);", "import * as React from 'react'; "), errors: [STALE] },
    { name: "default React import", filename: "view.tsx", code: view("const [items, setItems] = React.useState<string[]>([]);", "const add = () => setItems([...items, item]);", "import React from 'react'; "), errors: [STALE] },
    { name: "erased wrappers around the argument", filename: "view.tsx", code: view(LIST, "const add = () => setItems([...(items as readonly string[]), item] as string[]);"), errors: [STALE] },
    { name: "repeated render-phase updates in a callback", filename: "view.tsx", code: view(COUNT, "[item, item].forEach(() => setCount(count + 1));"), errors: [STALE] },
    { name: "state read beside a value derived from it", filename: "view.tsx", code: view("const [draft, setDraft] = useState({ settings: { temperature: 1 } }); const { settings } = draft;", "const tune = (temperature: number) => setDraft({ ...draft, settings: { ...settings, temperature } });"), errors: [STALE] },
    { name: "never-reassigned let binding", filename: "view.tsx", code: view("let [count, setCount] = useState(0);", "const increment = () => setCount(count + 1);"), errors: [STALE] },
    { name: "setter declared after its caller", filename: "view.tsx", code: view("function increment() { setCount(count + 1); }", `${COUNT} void increment;`), errors: [STALE] },
    {
      name: "inside a custom hook that owns the state",
      filename: "view.ts",
      code: `${IMPORT}export function useCounter() { ${COUNT} return { count, increment: () => setCount(count + 1) }; }`,
      errors: [STALE],
    },
    {
      name: "parent handler passed to a child",
      filename: "view.tsx",
      code: `${IMPORT}function Editor({ onAdd }: { onAdd: () => void }) { return <button type="button" onClick={onAdd} />; } export function View() { ${LIST} return <Editor onAdd={() => setItems([...items, 'next'])} />; }`,
      errors: [STALE],
    },
  ],
});

it("executes the documented examples", async () => {
  await expect(verifyRuleExamples(RULES["react-prefer-updater-function"])).resolves.toBeGreaterThan(0);
});
