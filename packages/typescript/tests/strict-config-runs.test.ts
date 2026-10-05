/** Execute shipped native policies over authored files, including typed and syntax-only controls. */
import { spawnSync } from "node:child_process";
import {
  cpSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { format } from "oxfmt";
import { createStrictOxlintConfig } from "../dist/config.js";
import { createSelectedOxlintConfig } from "../src/create-selected-oxlint-config.js";
import { PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION } from "../src/rules/prefer-nullish-filter-predicate.js";

const engine = join(
  dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);
const fixtures = fileURLToPath(new URL("./fixtures/runs", import.meta.url));
let root: string;
interface Diagnostic {
  code?: string;
  severity: string;
  message: string;
  labels?: { span: { line: number } }[];
}
interface Run {
  diagnostics: Diagnostic[];
  output: string;
}
const configurations = new Map<string, string>();
beforeAll(() => {
  root = mkdtempSync(
    fileURLToPath(new URL("../.native-fixture-", import.meta.url)),
  );
  cpSync(fixtures, root, { recursive: true });
  cpSync(
    fileURLToPath(new URL("./fixtures/nested-monorepo", import.meta.url)),
    root,
    { recursive: true },
  );
  writeFileSync(
    join(root, "tsconfig.json"),
    JSON.stringify({
      compilerOptions: {
        target: "ES2024",
        module: "NodeNext",
        moduleResolution: "NodeNext",
        strict: true,
        jsx: "preserve",
        allowJs: true,
        checkJs: false,
      },
      include: ["**/*.ts", "**/*.tsx"],
    }),
  );
});
afterAll(() => rmSync(root, { recursive: true, force: true }));
async function lint(
  source: string,
  {
    filename = "probe.ts",
    rules,
    typed = false,
    fix = false,
    syntaxOnlyConfigFiles,
  }: {
    filename?: string;
    rules?: readonly string[];
    typed?: boolean;
    fix?: boolean;
    syntaxOnlyConfigFiles?: string[];
  } = {},
): Promise<Run> {
  const key = JSON.stringify({ typed, rules, syntaxOnlyConfigFiles });
  let policy = configurations.get(key);
  if (policy === undefined) {
    policy = join(root, `policy-${configurations.size}.json`);
    const config = await createStrictOxlintConfig({
      root,
      typeAware: typed,
      syntaxOnlyConfigFiles,
    });
    writeFileSync(policy, JSON.stringify(config));
    if (rules !== undefined)
      writeFileSync(
        policy,
        JSON.stringify(await createSelectedOxlintConfig(policy, rules)),
      );
    configurations.set(key, policy);
  }
  const file = join(root, filename);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, source);
  const run = spawnSync(
    process.execPath,
    [
      engine,
      "--config",
      policy,
      "--format=json",
      ...(fix ? ["--fix"] : []),
      file,
    ],
    { cwd: root, encoding: "utf8", timeout: 30_000 },
  );
  if (run.error) throw run.error;
  expect(run.stderr).toBe("");
  expect([0, 1]).toContain(run.status);
  if (run.stdout.startsWith("No files found")) {
    expect(run.status).toBe(1);
    return { diagnostics: [], output: readFileSync(file, "utf8") };
  }
  const result = JSON.parse(run.stdout) as { diagnostics: Diagnostic[] };
  expect(
    result.diagnostics.filter(
      ({ code, message }) =>
        code === undefined &&
        !message.startsWith("Unused oxlint-disable directive"),
    ),
  ).toEqual([]);
  return {
    diagnostics: result.diagnostics,
    output: readFileSync(file, "utf8"),
  };
}
function findings(run: Run, rule: string): Diagnostic[] {
  const slash = rule.lastIndexOf("/");
  const family = slash === -1 ? "eslint" : rule.slice(0, slash);
  const name = rule.slice(slash + 1);
  return run.diagnostics.filter(({ code }) => code === `${family}(${name})`);
}

describe("the shipped Oxlint configuration executes", () => {
  it.each(["example.ts", "widget.tsx"])(
    "lints %s with real findings and no rule crashes",
    async (filename) => {
      const result = await lint(
        readFileSync(join(fixtures, filename), "utf8"),
        { filename, typed: true },
      );
      if (filename === "example.ts")
        expect(findings(result, "@sarj/no-enum")).not.toHaveLength(0);
    },
  );
  it("keeps typed rules live and preserves handled Promise boundaries", async () => {
    const source = [
      "declare function start(): Promise<void>;",
      "declare function handleError(error: unknown): void;",
      "void start();",
      "void start().then(() => {});",
      "void start().catch(handleError);",
      "void start().then(() => {}, handleError);",
      "await start();",
      "function returned() { return start(); }",
      "void 0;",
    ].join("\n");
    const result = await lint(source, {
      typed: true,
      rules: ["typescript/no-floating-promises"],
    });
    expect(findings(result, "typescript/no-floating-promises")).toHaveLength(2);
    expect(result.diagnostics.map(({ severity }) => severity)).toEqual([
      "error",
      "error",
    ]);
  });
  it("allows async JSX handlers while retaining other Promise boundaries", async () => {
    const result = await lint(
      [
        "declare function Button(props: { onClick: () => void }): null;",
        "declare function save(): Promise<void>;",
        "declare function report(error: unknown): void;",
        "async function handleClick() { try { await save(); } catch (error) { report(error); } }",
        "const named = <Button onClick={handleClick} />;",
        "const inline = <Button onClick={async () => { try { await save(); } catch (error) { report(error); } }} />;",
        "save();",
        "void save();",
        "[1].forEach(async () => { await save(); });",
        "const ignored: () => void = handleClick;",
        "if (save()) { report('not a boolean'); }",
      ].join("\n"),
      {
        filename: "async-handlers.tsx",
        typed: true,
        rules: [
          "typescript/no-floating-promises",
          "typescript/no-misused-promises",
          "typescript/strict-void-return",
        ],
      },
    );
    expect(
      result.diagnostics.map(({ code, severity, labels }) => ({
        code,
        severity,
        line: labels?.[0]?.span.line,
      })),
    ).toEqual([
      { code: "typescript(no-floating-promises)", severity: "error", line: 7 },
      { code: "typescript(no-floating-promises)", severity: "error", line: 8 },
      { code: "typescript(no-misused-promises)", severity: "error", line: 9 },
      { code: "typescript(no-misused-promises)", severity: "error", line: 10 },
      { code: "typescript(no-misused-promises)", severity: "error", line: 11 },
    ]);
  });
  it.each([
    { filename: "callback.ts", expected: ["warning"] },
    { filename: "callback.tsx", expected: [] },
  ])(
    "retains the strict void-return scope in $filename",
    async ({ filename, expected }) => {
      const result = await lint(
        "declare function run(cb: () => void): void;\nrun(() => 123);",
        { filename, typed: true, rules: ["typescript/strict-void-return"] },
      );
      expect(
        findings(result, "typescript/strict-void-return").map(
          ({ severity }) => severity,
        ),
      ).toEqual(expected);
    },
  );
  it("keeps quoted wire keys compatible with camelCase policy", async () => {
    const result = await lint(
      "const record = { 'snake_case': 1, camelCase: 2 }; record['snake_case']; record['camelCase']; record.snake_case;",
      {
        typed: true,
        rules: [
          "typescript/dot-notation",
          "@sarj/require-camelcase-properties",
        ],
      },
    );
    expect(findings(result, "typescript/dot-notation")).toHaveLength(1);
    expect(findings(result, "@sarj/require-camelcase-properties")).toHaveLength(
      1,
    );
  });
  it.each([false, true])(
    "keeps syntax naming active with typeAware=%s",
    async (typed) => {
      const result = await lint(
        "export const Example = () => <div />; export interface invalid_name {}",
        {
          filename: "tooling.tsx",
          typed,
          syntaxOnlyConfigFiles: ["**/tooling.tsx"],
          rules: ["sarj-typescript/naming-convention"],
        },
      );
      expect(
        findings(result, "sarj-typescript/naming-convention"),
      ).not.toHaveLength(0);
    },
  );
  it("assigns syntax dynamic evaluation one diagnostic owner", async () => {
    const result = await lint(
      'eval("work()"); globalThis.setTimeout("work()", 0); new Function("return 1"); payload.hasOwnProperty("id");',
      {
        filename: "tooling.js",
        rules: [
          "no-eval",
          "no-implied-eval",
          "no-new-func",
          "no-prototype-builtins",
          "typescript/no-implied-eval",
        ],
      },
    );
    expect(
      result.diagnostics
        .map(({ code }) => code)
        .sort((left, right) => (left ?? "").localeCompare(right ?? "")),
    ).toEqual([
      "eslint(no-eval)",
      "eslint(no-implied-eval)",
      "eslint(no-new-func)",
      "eslint(no-prototype-builtins)",
    ]);
  });
  it("assigns typed dynamic evaluation one diagnostic owner", async () => {
    const result = await lint(
      'eval("direct()"); (0, eval)("indirect()"); globalThis.setTimeout("later()", 0); new Function("return 1");',
      {
        typed: true,
        rules: [
          "no-eval",
          "no-implied-eval",
          "no-new-func",
          "typescript/no-implied-eval",
        ],
      },
    );
    expect(
      result.diagnostics
        .map(({ code }) => code)
        .sort((left, right) => (left ?? "").localeCompare(right ?? "")),
    ).toEqual([
      "eslint(no-eval)",
      "eslint(no-eval)",
      "typescript(no-implied-eval)",
      "typescript(no-implied-eval)",
    ]);
  });
  it.each([
    "packages/example/src/index.ts",
    "packages/example/src/domain.config.ts",
  ])("keeps real type analysis live in owned %s", async (filename) => {
    const result = await lint(readFileSync(join(root, filename), "utf8"), {
      filename,
      typed: true,
      rules: ["typescript/await-thenable"],
    });
    expect(findings(result, "typescript/await-thenable")).toHaveLength(1);
  });
  it("keeps an excluded Vite config syntax-only", async () => {
    const filename = "packages/example/vite.config.ts";
    const result = await lint(readFileSync(join(root, filename), "utf8"), {
      filename,
      typed: true,
      rules: ["typescript/await-thenable", "@sarj/no-enum"],
    });
    expect(findings(result, "@sarj/no-enum")).toHaveLength(1);
    expect(findings(result, "typescript/await-thenable")).toEqual([]);
  });
  it("lets consumers retain type analysis for an owned Vite config", async () => {
    const filename = "packages/example/src/vite.config.ts";
    const result = await lint(readFileSync(join(root, filename), "utf8"), {
      filename,
      typed: true,
      syntaxOnlyConfigFiles: [],
      rules: ["typescript/await-thenable"],
    });
    expect(findings(result, "typescript/await-thenable")).toHaveLength(1);
  });
  it("retains naming and var checks outside a configured type project", async () => {
    const filename = "packages/example/.dependency-cruiser.cjs";
    const result = await lint(readFileSync(join(root, filename), "utf8"), {
      filename,
      typed: true,
      rules: [
        "no-var",
        "sarj-typescript/naming-convention",
        "typescript/await-thenable",
      ],
    });
    expect(findings(result, "no-var")).toHaveLength(1);
    expect(findings(result, "sarj-typescript/naming-convention")).toHaveLength(
      1,
    );
    expect(findings(result, "typescript/await-thenable")).toEqual([]);
  });
  it("keeps wire keys while requiring camelCase parameter bindings", async () => {
    const filename = "packages/example/src/parameter-naming.ts";
    const result = await lint(readFileSync(join(root, filename), "utf8"), {
      filename,
      typed: true,
      rules: ["sarj-typescript/naming-convention"],
    });
    expect(
      findings(result, "sarj-typescript/naming-convention").map(
        ({ message }) => message.match(/`([^`]+)`/)?.[1],
      ),
    ).toEqual(["snake_param", "wire_key", "snake_local", "snake_item"]);
  });
  it("accepts type-like module constants without admitting camelCase values", async () => {
    const filename = "packages/example/src/constant-naming.ts";
    const result = await lint(readFileSync(join(root, filename), "utf8"), {
      filename,
      typed: true,
      rules: ["sarj-typescript/naming-convention"],
    });
    expect(
      findings(result, "sarj-typescript/naming-convention").map(
        ({ message }) => message.match(/`([^`]+)`/)?.[1],
      ),
    ).toEqual(["moduleMetadata"]);
  });
  it("limits class ordering to accessibility rather than static or field layout", async () => {
    const filename = "packages/example/src/member-ordering.ts";
    const result = await lint(readFileSync(join(root, filename), "utf8"), {
      filename,
      rules: ["sarj-typescript/member-ordering"],
    });
    expect(findings(result, "sarj-typescript/member-ordering")).toEqual([]);
  });
  it("retains the Hooks engine and explicit buttons in design-system primitives", async () => {
    const button = await lint(
      "export function Save() {return <button>Save</button>;}",
      { filename: "components/ui/save.tsx" },
    );
    expect(findings(button, "react/button-has-type")).toHaveLength(1);
    const hook = await lint(
      "import {useState} from 'react'; export function Broken({ready}) {if (ready) useState(0); return <div/>;}",
      { filename: "src/broken.tsx" },
    );
    expect(findings(hook, "react-hooks/rules-of-hooks")).not.toHaveLength(0);
  });
  it("rejects range and file-scoped directives while permitting reviewed line-local ones", async () => {
    const rule = "@sarj/no-vague-suppression-description";
    const range = await lint(
      "/* oxlint-disable no-console -- native reviewed region */\nconsole.log('hidden');\n/* oxlint-enable no-console */",
      { rules: [rule] },
    );
    expect(findings(range, rule)).toHaveLength(2);
    const file = await lint(
      "/* eslint no-console: off -- file policy override */\nconsole.log('hidden');",
      { rules: [rule] },
    );
    expect(findings(file, rule)).toHaveLength(1);
    const local = await lint(
      "debugger; // oxlint-disable-line no-debugger -- pauses this manual inspector probe",
      { rules: [rule, "no-debugger"] },
    );
    expect(findings(local, rule)).toEqual([]);
    expect(findings(local, "no-debugger")).toEqual([]);
  });
  it.each([
    {
      rule: "no-extra-bind",
      safeFix: false,
      source: "const load = (() => 1).bind(undefined);",
      expected: "const load = (() => 1);",
      extension: "ts",
    },
    {
      rule: "sarj-core/no-undef-init",
      source: "let value = undefined;",
      expected: "let value;",
      extension: "ts",
    },
    {
      rule: "no-useless-computed-key",
      source: 'const value = { ["name"]: "Ada" };',
      expected: 'const value = { "name": "Ada" };',
      extension: "ts",
    },
    {
      rule: "no-useless-rename",
      source: "const { value: value } = input;",
      expected: "const { value } = input;",
      extension: "ts",
    },
    {
      rule: "no-useless-return",
      safeFix: false,
      source: "function finish(): void { return; }",
      expected: "function finish(): void {  }",
      extension: "ts",
    },
    {
      rule: "prefer-arrow-callback",
      source: "items.map(function (item) { return item; });",
      expected: "items.map((item) => item);",
      extension: "ts",
    },
    {
      rule: "react/jsx-curly-brace-presence",
      source: 'const view = <Panel label={"ready"}>{"Done"}</Panel>;',
      expected: 'const view = <Panel label="ready">Done</Panel>;',
      extension: "tsx",
    },
    {
      rule: "typescript/no-useless-empty-export",
      source: "export const value = 1; export {};",
      expected: "export const value = 1; ",
      extension: "ts",
    },
    {
      rule: "sarj-unicorn/no-useless-coercion",
      source: 'const value = String("ready");',
      expected: 'const value = "ready";',
      extension: "ts",
    },
    {
      rule: "typescript/consistent-type-exports",
      source:
        "type User = { id: string }; const version = 1; export { User, version };",
      expected:
        "type User = { id: string }; const version = 1; export { type User, version };",
    },
    {
      rule: "typescript/no-unnecessary-qualifier",
      source:
        "namespace Values { export type Item = string; const value: Values.Item = 'x'; }",
      expected:
        "namespace Values { export type Item = string; const value: Item = 'x'; }",
    },
    {
      rule: "arrow-body-style",
      source: "const value = () => { return 1; };",
      expected: "const value = () =>  1 ;",
      nearMiss: "const value = () => 1;",
    },
    {
      rule: "sarj-unicorn/single-line-block-comment-style",
      source: "/*\nconcise rationale\n*/\nconst value = 1;",
      expected: "/* concise rationale */\nconst value = 1;",
      nearMiss: "/* concise rationale */\nconst value = 1;",
    },
    {
      rule: "eslint/logical-assignment-operators",
      safeFix: false,
      source: "let value; value = value || fallback;",
      expected: "let value; value ||= fallback;",
      nearMiss: "let value; value ||= fallback;",
    },
    {
      rule: "sarj-unicorn/prefer-single-object-destructuring",
      source:
        "const source = {a: 1, b: 2}; const {a} = source; const {b} = source;",
      expected: "const source = {a: 1, b: 2}; const {a, b} = source;",
      nearMiss:
        "let source = {a: 1, b: 2}; const {a} = source; const {b} = source;",
    },
    {
      rule: "sarj-unicorn/iteration-fallback-style",
      source: "for (const item of items ?? []) { use(item); }",
      expected:
        "if ((items) != null) {\n\tfor (const item of items) { use(item); }\n}",
      nearMiss:
        "if (items != null) { for (const item of items) { use(item); } }",
    },
  ])(
    "preserves $rule findings and its stock safe-fix classification",
    async (control) => {
      const { rule, source, expected } = control;
      const typed =
        rule === "typescript/consistent-type-exports" ||
        rule === "typescript/no-unnecessary-qualifier";
      const filename = rule.startsWith("react/")
        ? "concision.tsx"
        : "concision.ts";
      const first = await lint(source, {
        filename,
        rules: [rule, "arrow-body-style"],
        typed,
        fix: true,
      });
      if ("safeFix" in control && control.safeFix === false) {
        expect(first.output).toBe(source);
        expect(findings(first, rule)).toHaveLength(1);
        expect(
          findings(
            await lint(expected, { filename, rules: [rule], typed }),
            rule,
          ),
        ).toEqual([]);
        return;
      }
      if (rule === "prefer-arrow-callback") {
        expect(first.output).toBe("items.map((item) => { return item; });");
        expect(findings(first, rule)).toEqual([]);
        const remaining = await lint(first.output, {
          filename,
          rules: [rule, "arrow-body-style"],
          typed,
        });
        expect(findings(remaining, "arrow-body-style")).toHaveLength(1);
        const formatted = await format(filename, first.output);
        expect(formatted.errors).toEqual([]);
        const second = await lint(formatted.code, {
          filename,
          rules: [rule, "arrow-body-style"],
          typed,
          fix: true,
        });
        const final = await format(filename, second.output);
        const intended = await format(filename, expected);
        expect(final.errors).toEqual([]);
        expect(intended.errors).toEqual([]);
        expect(final.code).toBe(intended.code);
        const third = await lint(final.code, {
          filename,
          rules: [rule, "arrow-body-style"],
          typed,
          fix: true,
        });
        expect(third.output).toBe(final.code);
        expect(third.diagnostics).toEqual([]);
        return;
      }
      expect(first.output).toBe(expected);
      expect(findings(first, rule)).toEqual([]);
      const second = await lint(first.output, {
        filename,
        rules: [rule, "arrow-body-style"],
        typed,
        fix: true,
      });
      expect(second.output).toBe(first.output);
      expect(findings(second, rule)).toEqual([]);
      if ("nearMiss" in control) {
        const accepted = await lint(control.nearMiss, {
          filename,
          rules: [rule],
          typed,
          fix: true,
        });
        expect(accepted.output).toBe(control.nearMiss);
        expect(findings(accepted, rule)).toEqual([]);
      }
    },
  );
  it.each([
    {
      rule: "unicorn/no-object-as-default-parameter",
      severity: 2,
      source:
        "function configure(options = {timeout: 1000}) { return options; }",
      nearMiss: "function configure({timeout = 1000} = {}) { return timeout; }",
    },
    {
      rule: "sarj-unicorn/no-unsafe-sqlite-interpolation",
      severity: 2,
      source:
        "import {DatabaseSync} from 'node:sqlite'; const database = new DatabaseSync(':memory:'); database.prepare(`SELECT * FROM users WHERE id = ${id}`);",
      nearMiss:
        "import {DatabaseSync} from 'node:sqlite'; const database = new DatabaseSync(':memory:'); const query = database.prepare('SELECT * FROM users WHERE id = ?'); query.get(id);",
    },
    {
      rule: "eslint/default-param-last",
      severity: 2,
      source:
        "function load(optional = true, required: string) { return [optional, required]; }",
      nearMiss:
        "function load(required: string, optional = true) { return [required, optional]; }",
    },
    {
      rule: "sarj-unicorn/no-computed-property-existence-check",
      severity: 1,
      source:
        "function contains(object: Record<string, unknown>, key: string) { return Boolean(object[key]); }",
      nearMiss:
        "function contains(object: Record<string, unknown>, key: string) { return Object.hasOwn(object, key); }",
    },
    {
      rule: "unicorn/custom-error-definition",
      severity: 1,
      source:
        "class ServiceError extends Error { constructor(message: string) { super(message); } }",
      nearMiss:
        "class ServiceError extends Error { constructor(message: string, options?: ErrorOptions) { super(message, options); this.name = 'ServiceError'; } }",
    },
  ])(
    "enforces $rule with its calibrated severity",
    async ({ rule, severity, source, nearMiss }) => {
      const invalid = await lint(source, { rules: [rule] });
      expect(findings(invalid, rule)).toMatchObject([
        { severity: severity === 2 ? "error" : "warning" },
      ]);
      expect(findings(await lint(nearMiss, { rules: [rule] }), rule)).toEqual(
        [],
      );
    },
  );
  it.each([
    {
      rule: "no-async-promise-executor",
      source:
        "new Promise(async (resolve) => { resolve(await operation()); });",
      nearMiss:
        "new Promise((resolve, reject) => { operation().then(resolve, reject); });",
    },
    {
      rule: "no-constant-binary-expression",
      source: "function normalize(value) { return Boolean(value) ?? true; }",
      nearMiss: "function normalize(value) { return value ?? true; }",
    },
    {
      rule: "no-unsafe-finally",
      source:
        "function read() { try { return operation(); } finally { return fallback(); } }",
      nearMiss:
        "function read() { try { return operation(); } finally { cleanup(() => { return fallback(); }); } }",
    },
    {
      rule: "no-unsafe-optional-chaining",
      source: "function copy(value) { return [...value?.items]; }",
      nearMiss: "function copy(value) { return [...(value?.items ?? [])]; }",
    },
  ])(
    "blocks $rule and accepts its safe alternative",
    async ({ rule, source, nearMiss }) => {
      expect(
        findings(await lint(source, { rules: [rule] }), rule),
      ).toMatchObject([{ severity: "error" }]);
      expect(findings(await lint(nearMiss, { rules: [rule] }), rule)).toEqual(
        [],
      );
      expect(
        findings(
          await lint(
            `// oxlint-disable-next-line ${rule} -- reviewed fixture\n${source}`,
            { rules: [rule] },
          ),
          rule,
        ),
      ).toEqual([]);
    },
  );
  it.each([
    ["promise.then(handle);", 1],
    ["promise?.then(handle);", 1],
    ["promise.then?.(handle);", 1],
    ['promise["then"](handle);', 1],
    ["const { then: continuePromise } = promise;", 0],
    ["async function load() { await promise.then(handle); }", 1],
    [
      "// oxlint-disable-next-line @sarj/prefer-await-in-async-return\npromise.then(handle);",
      0,
    ],
    [
      "// oxlint-disable-next-line no-restricted-properties\npromise.then(handle);",
      1,
    ],
    ["await Promise.all([first(), second()]);", 0],
    ["work().catch(reportError);", 0],
    ["work().finally(cleanup);", 0],
    ['const schema = { if: {}, then: { type: "string" } };', 0],
    [
      'const schema = { then: { type: "string" } }; const type = schema.then.type;',
      0,
    ],
    [
      'const schema = { then: { type: "string" } }; const { then: branch } = schema;',
      0,
    ],
    [
      "const flow = { then(value: number) { return value + 1; } }; flow.then(1);",
      0,
    ],
    ['const text = "promise.then(handle)"; // promise.then(handle)', 0],
  ])("retains the proven Promise-only policy for %s", async (source, count) => {
    const declarations =
      "declare const promise: Promise<number>; declare function handle(input: number): number;\n";
    const result = await lint(declarations + source, {
      rules: ["@sarj/prefer-await-in-async-return"],
    });
    expect(findings(result, "@sarj/prefer-await-in-async-return")).toHaveLength(
      count,
    );
    expect(findings(result, "no-restricted-properties")).toEqual([]);
    expect(
      findings(result, "@sarj/prefer-await-in-async-return").every(
        ({ severity }) => severity === "error",
      ),
    ).toBe(true);
  });
  it("keeps the composed nullish filter suggestion accepted", async () => {
    const source =
      PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION.examples[0].files[0].source;
    const result = await lint(source, { typed: true });
    expect(findings(result, "eqeqeq")).toEqual([]);
    expect(findings(result, "@sarj/prefer-nullish-filter-predicate")).toEqual(
      [],
    );
  });
  it.each([
    ["stepdown-conflict.ts", 1],
    ["stepdown-callable-conflicts.ts", 3],
  ] as const)("keeps one ordering owner in %s", async (filename, count) => {
    const result = await lint(readFileSync(join(fixtures, filename), "utf8"), {
      filename,
    });
    expect(findings(result, "sarj-typescript/member-ordering")).toHaveLength(
      count,
    );
    expect(findings(result, "@sarj/stepdown")).toEqual([]);
    expect(findings(result, "perfectionist/sort-classes")).toEqual([]);
  });
  it("keeps Node filesystem Promise imports preferred", async () => {
    expect(
      findings(
        await lint(
          "import {readFile} from 'node:fs'; readFile('poem.txt', () => undefined);",
        ),
        "sarj-node/prefer-promises-fs",
      ),
    ).not.toHaveLength(0);
    expect(
      findings(
        await lint(
          "import {readFile} from 'node:fs/promises'; await readFile('poem.txt');",
        ),
        "sarj-node/prefer-promises-fs",
      ),
    ).toEqual([]);
  });
  it.each([
    "dist/compiled.ts",
    "build/compiled.ts",
    ".pnp.cjs",
    ".pnp.loader.mjs",
    ".yarn/releases/yarn.cjs",
  ])(
    "ignores generated %s while checking identical authored source",
    async (filename) => {
      const source = "enum Status {Active}";
      expect((await lint(source, { filename })).diagnostics).toEqual([]);
      expect(
        findings(
          await lint(source, { filename: "src/authored.ts" }),
          "@sarj/no-enum",
        ),
      ).toHaveLength(1);
    },
  );
  it("checks authored Yarn plugins and library sources", async () => {
    const source =
      "new Promise(async (resolve) => { resolve(await operation()); });";
    expect(
      findings(
        await lint(source, { filename: ".yarn/plugins/custom.cjs" }),
        "no-async-promise-executor",
      ),
    ).toHaveLength(1);
    expect(
      findings(
        await lint("enum Status {Active}", { filename: "lib/authored.ts" }),
        "@sarj/no-enum",
      ),
    ).toHaveLength(1);
  });
});
