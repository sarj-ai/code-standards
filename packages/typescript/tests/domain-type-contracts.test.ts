import { join } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

const CONFIG_ROOT = join(import.meta.dirname, "..", "..", "tsconfig");

/** Check the remediation with the actual shared compiler policy. */
function compile(sourceText: string): readonly number[] {
  const loaded = ts.readConfigFile(join(CONFIG_ROOT, "base.json"), (path) => ts.sys.readFile(path));
  const parsed = ts.parseJsonConfigFileContent(loaded.config, ts.sys, CONFIG_ROOT);
  const options = { ...parsed.options, noEmit: true, types: [] };
  const fileName = join(CONFIG_ROOT, "domain-contract.ts");
  const host = ts.createCompilerHost(options);
  const originalGetSourceFile = host.getSourceFile.bind(host);
  host.getSourceFile = (requested, languageVersion, onError, shouldCreateNewSourceFile) =>
    requested === fileName
      ? ts.createSourceFile(fileName, sourceText, languageVersion, true)
      : originalGetSourceFile(requested, languageVersion, onError, shouldCreateNewSourceFile);
  const program = ts.createProgram([fileName], options, host);
  return ts.getPreEmitDiagnostics(program).map((diagnostic) => diagnostic.code);
}

describe("domain type contracts under the shared compiler policy", () => {
  it("preserves legal variants and rejects incomplete, crossed and independently updated states", () => {
    expect(compile(`
      export type Connection = { readonly server: string } & (
        | { readonly state: "connecting"; readonly initiatedAt: number; readonly sessionId?: never; readonly disconnectedAt?: never }
        | { readonly state: "connected"; readonly sessionId: string; readonly ping?: { readonly at: number; readonly id: number }; readonly initiatedAt?: never; readonly disconnectedAt?: never }
        | { readonly state: "disconnected"; readonly disconnectedAt: number; readonly sessionId?: never; readonly initiatedAt?: never }
      );
      export const connecting: Connection = { server: "host", state: "connecting", initiatedAt: 1 };
      export const connected: Connection = { server: "host", state: "connected", sessionId: "session" };
      export const pinged: Connection = { server: "host", state: "connected", sessionId: "session", ping: { at: 2, id: 3 } };
      export const disconnected: Connection = { server: "host", state: "disconnected", disconnectedAt: 4 };
      // @ts-expect-error A connected variant requires its session payload.
      export const incomplete: Connection = { server: "host", state: "connected" };
      const crossedFields = { server: "host", state: "connected" as const, sessionId: "session", disconnectedAt: 4 };
      // @ts-expect-error Forbidden branch fields remain forbidden for non-fresh structural values.
      export const crossed: Connection = crossedFields;
      // @ts-expect-error A ping is absent or contains both correlated fields.
      export const partialPing: Connection = { server: "host", state: "connected", sessionId: "session", ping: { at: 2 } };
      // @ts-expect-error Exact optional properties distinguish omission from explicit undefined.
      export const explicitUndefined: Connection = { server: "host", state: "disconnected", disconnectedAt: 4, sessionId: undefined };
      // @ts-expect-error Changing a tag alone does not construct the new variant.
      export const tagOnlyUpdate: Connection = { ...connected, state: "disconnected" };
      export function disconnect(value: Connection): Connection {
        return { server: value.server, state: "disconnected", disconnectedAt: 4 };
      }
      export function describeConnection(value: Connection): string {
        switch (value.state) {
          case "connecting": return String(value.initiatedAt);
          case "connected": return value.sessionId;
          case "disconnected": return String(value.disconnectedAt);
          default: {
            const exhaustive: never = value;
            return exhaustive;
          }
        }
      }
    `)).toEqual([]);
  });

  it("requires a newly introduced variant to be handled by an exhaustive consumer", () => {
    expect(compile(`
      type State = { kind: "ready"; value: string } | { kind: "waiting" } | { kind: "failed"; reason: string };
      export function render(state: State): string {
        switch (state.kind) {
          case "ready": return state.value;
          case "waiting": return "waiting";
        }
        const exhaustive: never = state;
        return exhaustive;
      }
    `)).toEqual([2322]);
  });
});
