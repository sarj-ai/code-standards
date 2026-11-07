// vitest: shared-module-graph
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, it } from "vitest";

const PACKAGE_ROOT = fileURLToPath(new URL("../", import.meta.url));
const MANIFEST = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as {
  readonly exports: Readonly<Record<string, Readonly<Record<string, string>>>>;
  readonly dependencies: Readonly<Record<string, string>>;
  readonly peerDependencies: Readonly<Record<string, string>>;
  readonly peerDependenciesMeta?: unknown;
};

interface BuiltPlugin {
  readonly meta: { readonly name: string };
  readonly rules: Readonly<
    Record<
      string,
      {
        readonly createOnce?: unknown;
        readonly meta?: { readonly docs?: { readonly url?: string } };
      }
    >
  >;
}

it("exports the Oxlint plugin as the package's main ESM entrypoint", async () => {
  expect(MANIFEST.exports["."]).toEqual({ import: "./dist/index.js" });
  const { default: plugin } = (await import(`${PACKAGE_ROOT}dist/index.js`)) as {
    readonly default: BuiltPlugin;
  };
  expect(plugin.meta.name).toBe("@sarj");
  const rules = Object.entries(plugin.rules);
  expect(rules.length).toBeGreaterThan(0);
  expect(
    rules.filter(([, rule]) => !(rule.createOnce instanceof Function)).map(([name]) => name),
  ).toEqual([]);
  expect(
    rules
      .filter(
        ([name, rule]) =>
          rule.meta?.docs?.url !== `https://code-standards.sarj.ai/rules/oxlint/${name}/`,
      )
      .map(([name]) => name),
  ).toEqual([]);
});

it("needs no ESLint at runtime and requires tsrs", () => {
  expect(Object.keys(MANIFEST.dependencies).filter((name) => name === "eslint")).toEqual([]);
  expect(Object.keys(MANIFEST.peerDependencies)).toEqual(["tsrs", "typescript"]);
  expect(MANIFEST.peerDependenciesMeta).toEqual({ typescript: { optional: true } });
});

it.each(["../package-lock.json", "../../../apps/docs/package-lock.json"])(
  "keeps the development dependency graph in %s free of the ESLint engine",
  (path) => {
    const lock = JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8")) as {
      packages: Record<string, unknown>;
    };
    expect(
      Object.keys(lock.packages).filter((key) => /(?:^|\/)node_modules\/eslint$/u.test(key)),
    ).toEqual([]);
  },
);
