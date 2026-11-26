import rule from "../../src/rules/prefer-total-union-record.js";
import { FIXTURES, ruleTester, typed } from "./_tester.js";

const TABLE = "const labels: Record<string, string> = { failed: 'red', passed: 'green' };";
const DOMAIN = "type State = 'failed' | 'passed';";
const LOOKUP = "export const label = (state: State) => labels[state];";
const CLOSED_LOOKUP = `${DOMAIN} ${TABLE} ${LOOKUP}`;
const LARGE_DOMAIN = Array.from({ length: 65 }, (_, key) => `'state${key}'`).join(" | ");

ruleTester({ cwd: FIXTURES }).run("prefer-total-union-record", rule, typed({
  valid: [
    { name: "keeps the open receipt reason", code: `${TABLE} export const adjustment = (reason: null | string | undefined) => reason == null ? null : labels[reason];` },
    { name: "keeps forward-compatible flag states from a string schema", code: `import { z } from 'zod'; const analysis = z.object({ flagsState: z.string() }); ${TABLE} export const display = (state: z.infer<typeof analysis>['flagsState'] | null) => state === null ? 'None' : labels[state] ?? 'Unavailable';` },
    { name: "keeps extensible server conflict codes", code: `import { z } from 'zod'; const detail = z.string(); ${TABLE} export const conflict = (input: unknown) => labels[detail.parse(input)] ?? 'Conflict';` },
    { name: "keeps transfer keys extended by a spread", code: `${DOMAIN} const labels: Record<string, string> = { failed: 'red', ...{ passed: 'green' } }; ${LOOKUP}` },
    { name: "abstains on a static-only record owned by the widening rule", code: `${TABLE} export const label = labels['passed'];` },
    { name: "leaves unknown-valued records to the widening rule", code: `${DOMAIN} const labels: Record<string, unknown> = { failed: 'red', passed: 'green' }; ${LOOKUP}` },
    { name: "abstains when even one lookup has an open key", code: `${CLOSED_LOOKUP} export const fallback = (key: string) => labels[key];` },
    { name: "abstains on a whole-table escape", code: `${CLOSED_LOOKUP} export const items = Object.entries(labels);` },
    { name: "abstains on direct exports", code: `${DOMAIN} export ${TABLE} ${LOOKUP}` },
    { name: "abstains on a re-exported table binding", code: `${CLOSED_LOOKUP} export { labels };` },
    { name: "abstains on a member write", code: `${CLOSED_LOOKUP} export function update(state: State) { labels[state] = 'gray'; }` },
    { name: "abstains on a nested optional delete", code: `${DOMAIN} const labels: Record<string, { note?: string }> = { passed: { note: 'green' } }; export const remove = (state: State) => delete labels[state]?.note;` },
    { name: "abstains on receiver calls", code: `${DOMAIN} const labels: Record<string, () => string> = { failed() { return this.passed(); }, passed() { return 'green'; } }; export const label = (state: State) => labels[state]();` },
    { name: "keeps existing total and partial contracts", code: `${DOMAIN} const labels: Partial<Record<State, string>> = { failed: 'red' }; const exact = { failed: 'red', passed: 'green' } satisfies Record<State, string>; export const run = (state: State) => [labels[state], exact[state]];` },
    { name: "abstains on a shadowed Record type", code: `${CLOSED_LOOKUP} type Record<K, V> = { [key: string]: V };` },
    { name: "abstains on an unresolved domain", code: `${TABLE} type State = Missing; ${LOOKUP}` },
    { name: "abstains beyond the key bound", code: `type State = ${LARGE_DOMAIN}; ${TABLE} ${LOOKUP}` },
    { name: "abstains in a non-module script", code: `${DOMAIN} ${TABLE} function label(state: State) { return labels[state]; }` },
    { name: "abstains with no compiler services", code: CLOSED_LOOKUP, settings: { sarj: { typeAware: false } } },
  ],
  invalid: [
    { name: "retains exhaustiveness for a complete call-state table", code: `type CallState = 'failed' | 'no verdict' | 'passed' | 'running';\nconst dot: Record<string, string> = { failed: 'red', 'no verdict': 'gray', passed: 'green', running: 'gray' };\nexport const color = (call: { state: CallState }) => dot[call.state];`, output: null, errors: [{ messageId: "total", line: 2, column: 10, data: { domain: "CallState", missing: "" } }] },
    { name: "lists missing keys across computed and static reads", code: "const states = ['failed', 'passed', 'running'] as const; type State = typeof states[number]; const labels: { [key: string]: string } = { failed: 'red' }; export const label = (state: State) => labels[state] ?? labels.unknown;", output: null, errors: [{ messageId: "total", data: { domain: "the finite key union", missing: ' Add entries for "passed", "running", "unknown".' } }] },
    { name: "combines different finite domains on the same table", code: `${CLOSED_LOOKUP} export const extra = (state: 'running' | 'queued') => labels[state];`, output: null, errors: [{ messageId: "total", data: { domain: "the finite key union", missing: ' Add entries for "queued", "running".' } }] },
  ],
}));
