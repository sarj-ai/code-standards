import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { expect, it } from "vitest";
import { createStrictOxlintConfig } from "../dist/config.js";

interface Diagnostic {
  filename: string;
  code?: string;
}

const engine = path.join(
  path.dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);
const ruleId = "perfectionist/sort-classes";
const codeId = "perfectionist(sort-classes)";
const controls = [
  {
    name: "public-methods",
    invalid: "class Example { zeta() {} alpha() {} }",
    valid: "class Example { alpha() {} zeta() {} }",
  },
  {
    name: "private-methods",
    invalid: "class Example { #zeta() {} #alpha() {} }",
    valid: "class Example { #alpha() {} #zeta() {} }",
  },
  {
    name: "class-expression",
    invalid: "const Example = class { zeta() {} alpha() {} };",
    valid: "const Example = class { alpha() {} zeta() {} };",
  },
  {
    name: "nested-class",
    invalid:
      "class Outer { alpha(){return class Inner { zeta() {} alpha() {} };} zeta(){} }",
    valid:
      "class Outer { alpha(){return class Inner { alpha() {} zeta() {} };} zeta(){} }",
  },
  {
    name: "constructor-group",
    invalid: "class Example { alpha() {} constructor() {} zeta() {} }",
    valid: "class Example { constructor() {} alpha() {} zeta() {} }",
  },
  {
    name: "descending-options",
    invalid: "class Example { alpha() {} zeta() {} }",
    valid: "class Example { zeta() {} alpha() {} }",
    options: [{ order: "desc" }],
  },
] as const;

it("runs pinned class ordering, grouping, nested scope and option controls through stock Oxlint", () => {
  const directory = createProject();
  try {
    const overrides = [];
    for (const control of controls) {
      for (const kind of ["valid", "invalid"] as const) {
        const filename = `${kind}-${control.name}.ts`;
        writeFileSync(path.join(directory, filename), control[kind]);
        overrides.push({
          files: [filename],
          rules: {
            [ruleId]: [
              "error",
              ...("options" in control ? control.options : []),
            ],
          },
        });
      }
    }
    const nearMisses = {
      "instance-dependency": "class Example { zeta = 1; alpha = this.zeta; }",
      "static-dependency":
        "class Example { static zeta = 1; static alpha = Example.zeta; }",
      "separate-classes": "class Zeta { alpha() {} } class Alpha { zeta() {} }",
      "object-members":
        "class Example { alpha(){return {zeta:1,alpha:2};} zeta(){} }",
    };
    for (const [name, code] of Object.entries(nearMisses)) {
      const filename = `valid-${name}.ts`;
      writeFileSync(path.join(directory, filename), code);
      overrides.push({ files: [filename], rules: { [ruleId]: "error" } });
    }
    writeConfig(directory, { overrides });
    const diagnostics = lint(directory);
    expect(
      diagnostics.filter(
        (item) => !item.code || item.filename.startsWith("valid-"),
      ),
    ).toEqual([]);
    for (const control of controls)
      expect(
        diagnostics.filter(
          (item) => item.filename === `invalid-${control.name}.ts`,
        ),
      ).toEqual([{ filename: `invalid-${control.name}.ts`, code: codeId }]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("applies the exact upstream method fix and reaches a stable clean result", () => {
  const directory = createProject();
  try {
    const original = "class Example { zeta() {} alpha() {} }";
    writeFileSync(path.join(directory, "sample.ts"), original);
    writeConfig(directory, { rules: { [ruleId]: "error" } });
    expect(lint(directory)).toEqual([{ filename: "sample.ts", code: codeId }]);
    lint(directory, true);
    const fixed = readFileSync(path.join(directory, "sample.ts"), "utf8");
    expect(fixed).toBe("class Example { alpha() {} zeta() {} }");
    expect(lint(directory)).toEqual([]);
    expect(lint(directory, true)).toEqual([]);
    expect(readFileSync(path.join(directory, "sample.ts"), "utf8")).toBe(fixed);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("preserves dependency order and the original independent initializer ordering semantics", () => {
  const directory = createProject();
  try {
    writeConfig(directory, { rules: { [ruleId]: "error" } });
    const dependent =
      'const calls=[];function record(name,value){calls.push(name);return value;} class Example { zeta=record("zeta",1); alpha=record("alpha",this.zeta); } new Example(); calls;';
    writeFileSync(path.join(directory, "sample.ts"), dependent);
    expect(lint(directory, true)).toEqual([]);
    expect(readFileSync(path.join(directory, "sample.ts"), "utf8")).toBe(
      dependent,
    );
    expect(runInNewContext(dependent)).toEqual(["zeta", "alpha"]);
    const independent =
      'const calls=[];function record(name){calls.push(name);return name;} class Example { zeta=record("zeta"); alpha=record("alpha"); } new Example(); calls;';
    writeFileSync(path.join(directory, "sample.ts"), independent);
    expect(lint(directory)).toEqual([{ filename: "sample.ts", code: codeId }]);
    lint(directory, true);
    const fixed = readFileSync(path.join(directory, "sample.ts"), "utf8");
    expect(runInNewContext(independent)).toEqual(["zeta", "alpha"]);
    expect(runInNewContext(fixed)).toEqual(["alpha", "zeta"]);
    expect(lint(directory, true)).toEqual([]);
    expect(readFileSync(path.join(directory, "sample.ts"), "utf8")).toBe(fixed);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("preserves shared defaults and activates class ordering only in an explicit native file override", async () => {
  const directory = createProject();
  try {
    for (const filename of ["enabled.ts", "disabled.ts"])
      writeFileSync(
        path.join(directory, filename),
        "class Example { zeta() {} alpha() {} }",
      );
    const baseline = await createStrictOxlintConfig({
      root: directory,
      typeAware: false,
      testFrameworks: ["node"],
    });
    writeConfig(directory, baseline);
    expect(lint(directory).filter((item) => item.code === codeId)).toEqual([]);
    writeConfig(directory, {
      ...baseline,
      overrides: [
        ...(baseline.overrides ?? []),
        { files: ["enabled.ts"], rules: { [ruleId]: "error" } },
      ],
    });
    expect(lint(directory).filter((item) => item.code === codeId)).toEqual([
      { filename: "enabled.ts", code: codeId },
    ]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

function createProject(): string {
  const directory = fileURLToPath(new URL("../", import.meta.url));
  return mkdtempSync(path.join(directory, ".perfectionist-classes-"));
}

function writeConfig(directory: string, selection: object): void {
  writeFileSync(
    path.join(directory, "oxlint.json"),
    JSON.stringify({
      categories: { correctness: "off" },
      jsPlugins: [
        {
          name: "perfectionist",
          specifier: fileURLToPath(
            import.meta.resolve("@sarj/oxlint-plugin/upstream/perfectionist"),
          ),
        },
      ],
      ...selection,
    }),
  );
}

function lint(directory: string, fix = false): Diagnostic[] {
  const result = spawnSync(
    process.execPath,
    [
      engine,
      "--config",
      "oxlint.json",
      "--format=json",
      ...(fix ? ["--fix"] : []),
      ".",
    ],
    { cwd: directory, encoding: "utf8", timeout: 30_000 },
  );
  if (result.error !== undefined) throw result.error;
  expect(result.stderr).toBe("");
  expect([0, 1]).toContain(result.status);
  const report = JSON.parse(result.stdout) as { diagnostics: Diagnostic[] };
  expect(report.diagnostics.filter((item) => !item.code)).toEqual([]);
  return report.diagnostics.map(({ filename, code }) => ({ filename, code }));
}
