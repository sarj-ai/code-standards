import { spawnSync } from "node:child_process";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { createStrictOxlintConfig } from "../dist/config.js";
import { TESTING_LIBRARY_REACT_RECOMMENDED_RULES } from "../dist/presets.js";

interface Control {
  rule: string;
  valid: string;
  invalid: string;
  options?: unknown[];
  fix?: boolean;
}
interface Diagnostic {
  filename: string;
  code?: string;
}
const controls = JSON.parse(
  readFileSync(
    new URL("./upstream-testing-library-controls.json", import.meta.url),
    "utf8",
  ),
) as Control[];
const engine = path.join(
  path.dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);
const plugin = fileURLToPath(
  new URL("../dist/upstream/testing-library.js", import.meta.url),
);

it("runs all 22 Testing Library React rules and lexical scope controls through the stock worker", () => {
  const directory = mkdtempSync(
    path.join(tmpdir(), "sarj-testing-library-controls-"),
  );
  try {
    const overrides = [];
    for (const [index, control] of controls.entries()) {
      for (const kind of ["valid", "invalid"] as const) {
        const filename = `${kind}-${index}.tsx`;
        writeFileSync(path.join(directory, filename), control[kind]);
        overrides.push({
          files: [filename],
          rules: {
            [`port/${control.rule}`]: ["error", ...(control.options ?? [])],
          },
        });
      }
    }
    writeConfig(directory, { overrides });
    const run = lint(directory);
    expect(run).toMatchObject({ status: 1, stderr: "" });
    const diagnostics = (
      JSON.parse(run.stdout) as { diagnostics: Diagnostic[] }
    ).diagnostics;
    expect(
      diagnostics.filter(
        (item) => !item.code || item.filename.startsWith("valid-"),
      ),
    ).toEqual([]);
    const missing = controls.flatMap((control, index) =>
      diagnostics.some(
        (item) =>
          item.filename === `invalid-${index}.tsx` &&
          item.code === `port(${control.rule})`,
      )
        ? []
        : [control.rule],
    );
    expect(missing).toEqual([]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("applies the native Testing Library fixes and reaches a stable clean result", () => {
  const directory = mkdtempSync(
    path.join(tmpdir(), "sarj-testing-library-fixes-"),
  );
  try {
    const fixtures = controls.filter((control) => control.fix);
    const overrides = fixtures.map((fixture, index) => {
      const filename = `fix-${index}.tsx`;
      writeFileSync(path.join(directory, filename), fixture.invalid);
      return {
        files: [filename],
        rules: {
          [`port/${fixture.rule}`]: ["error", ...(fixture.options ?? [])],
        },
      };
    });
    writeConfig(directory, { overrides });
    expect(lint(directory, true)).toMatchObject({ status: 0, stderr: "" });
    const changed = fixtures.map((_, index) =>
      readFileSync(path.join(directory, `fix-${index}.tsx`), "utf8"),
    );
    expect(lint(directory, true)).toMatchObject({ status: 0, stderr: "" });
    expect(
      fixtures.map((_, index) =>
        readFileSync(path.join(directory, `fix-${index}.tsx`), "utf8"),
      ),
    ).toEqual(changed);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("exposes the original React options without expanding the central five-rule defaults", async () => {
  expect(
    Object.keys(TESTING_LIBRARY_REACT_RECOMMENDED_RULES)
      .map((name) => name.replace("sarj-testing-library/", ""))
      .sort(),
  ).toEqual([...new Set(controls.map((control) => control.rule))].sort());
  expect(TESTING_LIBRARY_REACT_RECOMMENDED_RULES).toMatchObject({
    "sarj-testing-library/no-debugging-utils": "warn",
    "sarj-testing-library/await-async-events": [
      "error",
      { eventModule: "userEvent" },
    ],
    "sarj-testing-library/no-await-sync-events": [
      "error",
      { eventModules: ["fire-event"] },
    ],
    "sarj-testing-library/no-dom-import": ["error", "react"],
  });
  const shared = await createStrictOxlintConfig({
    root: process.cwd(),
    typeAware: false,
    testFrameworks: ["testing-library"],
  });
  const testingLibraryRules = Object.keys(
    Object.assign({}, ...shared.overrides?.map((override) => override.rules)),
  ).filter((name) => name.startsWith("sarj-testing-library/"));
  expect(testingLibraryRules).toHaveLength(5);
});

it("preserves broad official-library checks and narrow custom-module detection", () => {
  const directory = mkdtempSync(
    path.join(tmpdir(), "sarj-testing-library-scopes-"),
  );
  try {
    const cases = [
      {
        rule: "await-async-queries",
        official:
          'import {screen} from "@testing-library/react";screen.findByText("ok");',
        custom:
          'import {screen} from "@/test/test-utils";screen.findByText("ok");',
      },
      {
        rule: "await-async-utils",
        official:
          'import {waitFor} from "@testing-library/react";waitFor(()=>expect(value).toBe(1));',
        custom:
          'import {waitFor} from "@/test/test-utils";waitFor(()=>expect(value).toBe(1));',
      },
      {
        rule: "await-async-events",
        official:
          'import userEvent from "@testing-library/user-event";userEvent.click(button);',
        custom:
          'import {userEvent} from "@/test/test-utils";userEvent.click(button);',
      },
      {
        rule: "prefer-screen-queries",
        official:
          'import {render} from "@testing-library/react";const {getByText}=render(component);getByText("ok");',
        custom:
          'import {render} from "@/test/test-utils";const {getByText}=render(component);getByText("ok");',
      },
      {
        rule: "no-unnecessary-act",
        official:
          'import {act,render} from "@testing-library/react";act(()=>{render(component);});',
        custom:
          'import {act,render} from "@/test/test-utils";act(()=>{render(component);});',
      },
    ];
    const expected: string[] = [];
    for (const area of ["src", "tests/helpers", "e2e"]) {
      for (const [index, fixture] of cases.entries()) {
        for (const kind of ["official", "custom"] as const) {
          const filename = `${area}/${kind}-${index}.test.tsx`;
          mkdirSync(path.dirname(path.join(directory, filename)), {
            recursive: true,
          });
          writeFileSync(path.join(directory, filename), fixture[kind]);
          const narrow = area === "src";
          if (
            fixture.rule === "no-unnecessary-act"
              ? kind === "official" && !narrow
              : kind === "official" || narrow
          )
            expected.push(filename);
        }
      }
    }
    writeConfig(directory, {
      overrides: [
        {
          files: ["**/*.{test,spec}.{ts,tsx}"],
          rules: Object.fromEntries(
            cases.map((fixture) => [
              `port/${fixture.rule}`,
              fixture.rule === "no-unnecessary-act"
                ? ["error", { isStrict: false }]
                : "error",
            ]),
          ),
        },
        {
          files: ["src/**/*.{test,spec}.{ts,tsx}"],
          rules: {
            "port/await-async-events": [
              "error",
              { eventModule: "userEvent", utilsModule: "@/test/test-utils" },
            ],
            "port/await-async-queries": [
              "error",
              { utilsModule: "@/test/test-utils" },
            ],
            "port/await-async-utils": [
              "error",
              { utilsModule: "@/test/test-utils" },
            ],
            "port/prefer-screen-queries": [
              "error",
              { utilsModule: "@/test/test-utils" },
            ],
            "port/no-unnecessary-act": "off",
          },
        },
      ],
    });
    const run = lint(directory);
    expect(run).toMatchObject({ status: 1, stderr: "" });
    const diagnostics = (
      JSON.parse(run.stdout) as { diagnostics: Diagnostic[] }
    ).diagnostics;
    expect(diagnostics.filter((item) => !item.code)).toEqual([]);
    expect(diagnostics.map((item) => item.filename).sort()).toEqual(
      expected.sort(),
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

function writeConfig(directory: string, policy: object) {
  writeFileSync(
    path.join(directory, "oxlint.json"),
    JSON.stringify({
      categories: { correctness: "off" },
      settings: {
        "testing-library/custom-queries": "off",
        "testing-library/custom-renders": "off",
        "testing-library/utils-module": "off",
      },
      jsPlugins: [{ name: "port", specifier: plugin }],
      ...policy,
    }),
  );
}

function lint(directory: string, fix = false) {
  return spawnSync(
    process.execPath,
    [
      engine,
      "--config",
      "oxlint.json",
      "--format=json",
      ...(fix ? ["--fix"] : []),
      ".",
    ],
    {
      cwd: directory,
      encoding: "utf8",
      timeout: 30_000,
    },
  );
}
