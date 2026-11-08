import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { ADDITIONS, ALL_TEST_FRAMEWORKS, CONFIGS_DIR, CONTEXTS, MANAGED, createConfig, effectiveRules, jsPlugins } from "./managed-config.js";

const PEERS = (JSON.parse(readFileSync(new URL("typescript.peers.json", CONFIGS_DIR), "utf8")) as { peers: Record<string, string> }).peers;
const NEXT_APP_PAGE = "src/app/page.tsx";

function sampleContexts(id: string, files: string | undefined): { on: readonly string[]; off: readonly string[] } {
  if (id.startsWith("vitest/")) return { on: [CONTEXTS["test-ts"]], off: [CONTEXTS["source-ts"], CONTEXTS["test-bun-ts"], CONTEXTS["test-playwright-ts"]] };
  if (files === "non-test") return { on: [CONTEXTS["source-ts"]], off: [CONTEXTS["test-ts"]] };
  if (files === "Next.js app sources only") return { on: [NEXT_APP_PAGE], off: [CONTEXTS["source-ts"]] };
  return { on: [CONTEXTS["source-ts"], CONTEXTS["source-tsx"]], off: [] };
}

describe("stage 2 rule additions", () => {
  it.each(Object.entries(ADDITIONS.rules))("%s runs at its listed level and scope", (id, { level, files }) => {
    const { on, off } = sampleContexts(id, files);
    expect(on.map((path) => effectiveRules(MANAGED, path).get(id)?.[0])).toEqual(on.map(() => level));
    expect(off.map((path) => effectiveRules(MANAGED, path).get(id))).toEqual(off.map(() => undefined));
  });

  it("loads each addition's JS plugin under its listed name", () => {
    const loaded = new Map(jsPlugins(MANAGED).map(({ name, specifier }) => [name, specifier]));
    expect(ADDITIONS.jsPlugins.map(({ name }) => loaded.get(name))).toEqual(ADDITIONS.jsPlugins.map(({ specifier }) => specifier));
  });
});

describe("typescript.peers.json", () => {
  it("pins every JS plugin the config can load", () => {
    const specifiers = jsPlugins(createConfig({ testFrameworks: ALL_TEST_FRAMEWORKS })).map(({ specifier }) => specifier);
    expect(specifiers.filter((specifier) => PEERS[specifier.replace(/^(@sarj\/eslint-plugin)\/.+$/u, "$1")] === undefined)).toEqual([]);
  });

  it("pins tsrs and oxlint, and no TypeScript compiler pair", () => {
    expect(Object.keys(PEERS)).toEqual(expect.arrayContaining(["oxlint", "oxlint-plugin-eslint", "tsrs", "oxfmt"]));
    expect(PEERS["@typescript/native"]).toBeUndefined();
  });
});
