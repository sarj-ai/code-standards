import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, writeFile, rm, readFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { createAstroCompiler, lintAstroFiles, mapAstroRange } from "@sarj/oxlint-plugin/framework/astro";
import { createSelectedOxlintConfig } from "@sarj/oxlint-plugin/select-rules";

async function lint(source, { rules = {}, options = {}, globals = {}, overrides = [], fix = false, fixSuggestions = false } = {}) {
  const directory = await mkdtemp(path.join(os.tmpdir(), "sarj-astro-framework-"));
  const filename = path.join(directory, "Component.astro");
  const configPath = path.join(directory, "oxlint.config.mjs");
  try {
    await writeFile(filename, source);
    await writeFile(configPath, `export default ${JSON.stringify({
      categories: { correctness: "off" }, plugins: ["eslint"],
      jsPlugins: [
        { name: "sarj-astro", specifier: new URL(import.meta.resolve("@sarj/oxlint-plugin/upstream/astro")).pathname },
        { name: "@sarj", specifier: new URL(import.meta.resolve("@sarj/oxlint-plugin")).pathname },
      ],
      globals,
      overrides,
      rules: {
        "sarj-astro/missing-client-only-directive-value": "error",
        "sarj-astro/no-conflict-set-directives": "error",
        "sarj-astro/no-unused-define-vars-in-style": "error",
        ...rules,
      },
      options: { respectEslintDisableDirectives: false, ...options },
    })};`);
    const report = await lintAstroFiles({ filenames: [filename], configPath, cwd: path.resolve(import.meta.dirname, ".."), fix, fixSuggestions });
    return { ...report, source: await readFile(filename, "utf8") };
  } finally { await rm(directory, { recursive: true, force: true }); }
}

const invalid = [
  [
    "client-only without frontmatter",
    "<Card client:only />",
    ["sarj-astro/missing-client-only-directive-value"],
  ],
  [
    "dynamic framework value",
    "<Card client:only={selectFramework()} />",
    ["sarj-astro/missing-client-only-directive-value"],
  ],
  [
    "conflicting directives",
    '<p set:text={"text"} set:html={"<b>html</b>"} />',
    ["sarj-astro/no-conflict-set-directives", "sarj-astro/no-conflict-set-directives"],
  ],
  [
    "directive with content",
    '<p set:text={"text"}>content</p>',
    ["sarj-astro/no-conflict-set-directives", "sarj-astro/no-conflict-set-directives"],
  ],
  [
    "unused style variable",
    '<style define:vars={{ color: "red", unused: "blue" }}>p { color: var(--color) }</style>',
    ["sarj-astro/no-unused-define-vars-in-style"],
  ],
  [
    "CSS comment is not usage",
    '<style define:vars={{ color: "red" }}>/* var(--color) */ p { color: red }</style>',
    ["sarj-astro/no-unused-define-vars-in-style"],
  ],
];

for (const [name, source, rules] of invalid) {
  await test(name, async () => {
    const { diagnostics } = await lint(source);
    assert.deepEqual(
      diagnostics.map((diagnostic) => diagnostic.code.replace(/^(.+)\(([^)]+)\)$/, "$1/$2")),
      rules,
    );
    for (const diagnostic of diagnostics) {
      const span = diagnostic.labels[0].span;
      assert.ok(span.line >= 1);
      assert.ok(span.column >= 1);
      assert.ok(span.offset >= 0 && span.offset < Buffer.byteLength(source));
    }
  });
}

const commentConflictPrefixes = [
  ["single line", ""],
  ["after a Unicode element", "<span>🦜</span>\n"],
];

for (const [name, prefix] of commentConflictPrefixes) {
  await test(`comment-only set directive conflicts retain the authored child span ${name}`, async () => {
    const source = `${prefix}<p set:text="text">{/* comment */}</p>`;
    const { diagnostics } = await lint(source);
    assert.equal(diagnostics.length, 2);
    const attribute = diagnostics.find((entry) => entry.message.startsWith("'set:text'"));
    assert.deepEqual(attribute.labels[0].span, {
      offset: Buffer.byteLength(prefix) + 3, length: 15,
      line: prefix ? 2 : 1, column: 4,
    });
    const diagnostic = diagnostics.find((entry) => entry.message.startsWith("child contents"));
    assert.ok(diagnostic);
    const child = "{/* comment */}";
    const start = source.indexOf(child);
    assert.deepEqual(diagnostic.labels[0].span, {
      offset: Buffer.byteLength(source.slice(0, start)),
      length: Buffer.byteLength(child),
      line: prefix ? 2 : 1,
      column: 20,
    });
  });
}

await test("omitted comment expressions map to their own element", async () => {
  const source = '<p set:text="text">{/* first */}</p><p set:html="html">{/* second */}</p>';
  const { diagnostics } = await lint(source);
  assert.equal(diagnostics.length, 4);
  assert.deepEqual(diagnostics.filter((entry) => entry.message.startsWith("child contents"))
    .map((entry) => [entry.labels[0].span.offset, entry.labels[0].span.length]), [[19, 13], [55, 14]]);
  const nested = await lint('{ready&&<p set:text="text">{/* nested */}</p>}');
  assert.equal(nested.diagnostics.length, 2);
  const child = nested.diagnostics.find((entry) => entry.message.startsWith("child contents"));
  assert.deepEqual(child.labels[0].span, { offset: 27, length: 14, line: 1, column: 28 });
});

await test("ordinary expression conflicts retain the native authored span", async () => {
  const { diagnostics } = await lint('<p set:text="text">{label}</p>');
  assert.equal(diagnostics.length, 2);
  const diagnostic = diagnostics.find((entry) => entry.message.startsWith("child contents"));
  assert.deepEqual(diagnostic.labels[0].span, { offset: 19, length: 7, line: 1, column: 20 });
});

const valid = [
  ["static framework", '<Card client:only="react" />'],
  ["empty static value", '<Card client:only="" />'],
  ["static null expression", "<Card client:only={null} />"],
  [
    "frontmatter constant",
    '---\nconst framework = "react";\n---\n<Card client:only={framework} />',
  ],
  ["template framework", "<Card client:only={`react`} />"],
  ["comment and whitespace content", '<p set:text={"text"}> <!-- documentation --> </p>'],
  [
    "used style variable",
    '<style define:vars={{ color: "red" }}>p { color: var(--color, blue) }</style>',
  ],
  [
    "computed style variable",
    '---\nconst name = "color";\n---\n<style define:vars={{ [name]: "red" }}>p { color: var(--color) }</style>',
  ],
];

for (const [name, source] of valid) {
  await test(name, async () => {
    assert.deepEqual((await lint(source)).diagnostics, []);
  });
}


await test("native fix preserves Unicode and is idempotent", async () => {
  const source = '<p>🦜 مرحبا</p><div>{((ready)=>{if(!!ready)return 1;return 0;})(true)}</div>';
  const options = { rules: { "eslint/no-extra-boolean-cast": "error" }, fix: true, fixSuggestions: true };
  const first = await lint(source, options);
  assert.equal(first.appliedFixes, 1);
  assert.equal(first.source, source.replace("!!ready", "ready"));
  assert.deepEqual(first.diagnostics, []);
  const second = await lint(first.source, options);
  assert.equal(second.appliedFixes, 0);
  assert.equal(second.source, first.source);
});

await test("raw precision and main Boolean checks compose directive usage once", async () => {
  const source = '---\n/* oxlint-disable eslint/no-loss-of-precision, eslint/no-extra-boolean-cast -- exact wire values */\nconst large=9007199254740993;\n---\n<div>{((ready)=>{if(!!ready)return 1;return 0;})(true)}</div>';
  const report = await lint(source, {
    rules: { "eslint/no-loss-of-precision": "error", "eslint/no-extra-boolean-cast": "error" },
    options: { reportUnusedDisableDirectives: "error" }, fix: true,
  });
  assert.deepEqual(report.diagnostics, []);
  assert.equal(report.source, source);
  assert.equal(report.skippedFixes.length, 1);
});

await test("a partly unused directive keeps the exact selector finding", async () => {
  const source = '---\n// oxlint-disable-next-line eslint/no-loss-of-precision, eslint/no-extra-boolean-cast -- exact wire values\nconst large=9007199254740993;\n---\n<div/>';
  const report = await lint(source, {
    rules: { "eslint/no-loss-of-precision": "error", "eslint/no-extra-boolean-cast": "error" },
    options: { reportUnusedDisableDirectives: "error" },
  });
  assert.equal(report.diagnostics.length, 1);
  const diagnostic = report.diagnostics[0];
  assert.equal(diagnostic.message, "Unused oxlint-disable directive (no problems were reported from eslint/no-extra-boolean-cast).");
  const span = diagnostic.labels[0].span;
  assert.equal(Buffer.from(source).subarray(span.offset, span.offset + span.length).toString(), "eslint/no-extra-boolean-cast");
});

await test("authored frontmatter JSX retains accessibility findings", async (t) => {
  for (const [jsx, rule] of [
    ['<button><svg aria-hidden="true"/></button>', "require-button-accessible-name"],
    ["<svg/>", "require-svg-accessible-name"],
  ]) {
    await t.test(rule, async () => {
      const report = await lint(`---\n${jsx}\n---\n<div/>`, { rules: { [`@sarj/${rule}`]: "error" } });
      assert.equal(report.diagnostics.length, 1);
      assert.equal(report.diagnostics[0].code, `@sarj(${rule})`);
    });
  }
});

await test("Astro module bindings may shadow a declared builtin Fragment global", async () => {
  const report = await lint('---\nconst Fragment=()=>null;\n---\n<Fragment/>', {
    globals: { Fragment: "readonly" }, rules: { "eslint/no-redeclare": ["error", { builtinGlobals: true }] },
  });
  assert.deepEqual(report.diagnostics, []);
});

await test("Astro server timers retain the original component filename", async () => {
  const report = await lint('---\nawait new Promise((resolve)=>setTimeout(resolve,500));\n---\n<div/>', {
    globals: { setTimeout: "readonly", Promise: "readonly" }, rules: { "@sarj/no-hand-rolled-sleep": "error" },
  });
  assert.equal(report.diagnostics.length, 1);
  assert.equal(report.diagnostics[0].code, "@sarj(no-hand-rolled-sleep)");
});

await test("entity-only button content is unnamed without double-decoding", async () => {
  const options = { rules: { "@sarj/require-button-accessible-name": "error" } };
  assert.equal((await lint("<button>&nbsp;</button>", options)).diagnostics.length, 1);
  assert.deepEqual((await lint("<button>&amp;nbsp;</button>", options)).diagnostics, []);
});

await test("original whitespace options cover markup and raw code once", async () => {
  const report = await lint('---\nconst\u200b value=1;\n---\n<p>Save\u200bnow</p>', {
    rules: { "eslint/no-irregular-whitespace": ["error", { skipComments: false, skipJSXText: false, skipRegExps: false, skipStrings: true, skipTemplates: false }] },
  });
  assert.equal(report.diagnostics.filter((diagnostic) => diagnostic.code === "eslint(no-irregular-whitespace)").length, 2);
});

await test("native duplicate class rejection appears once at its original property spans", async () => {
  const source = '---\nclass Store {read(){return 1;} read(){return 2;}}\n---\n<div/>';
  const report = await lint(source, { rules: { "eslint/no-dupe-class-members": "error" } });
  assert.equal(report.diagnostics.length, 1);
  assert.match(report.diagnostics[0].message, /already been declared/u);
  for (const label of report.diagnostics[0].labels) {
    assert.equal(Buffer.from(source).subarray(label.span.offset, label.span.offset + label.span.length).toString(), "read");
  }
});

await test("resolved selected-rule configs retain genuine Astro execution", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "sarj-astro-selected-"));
  const filename = path.join(directory, "Component.astro");
  const configPath = path.join(directory, "oxlint.config.mjs");
  const selectedPath = path.join(directory, "selected.mjs");
  try {
    await writeFile(filename, "---\nconsole.log('wire'); debugger;\n---\n<div/>");
    await writeFile(configPath, `export default ${JSON.stringify({
      categories: { correctness: "off" }, plugins: ["eslint"],
      env: { node: true },
      rules: { "eslint/no-console": "error", "eslint/no-debugger": "error" },
    })};`);
    const selected = await createSelectedOxlintConfig(configPath, ["eslint/no-console"]);
    await writeFile(selectedPath, `export default ${JSON.stringify(selected)};`);
    const report = await lintAstroFiles({ filenames: [filename], configPath: selectedPath, cwd: path.resolve(import.meta.dirname, "..") });
    assert.equal(report.diagnostics.length, 1);
    assert.equal(report.diagnostics[0].code, "eslint(no-console)");
  } finally { await rm(directory, { recursive: true, force: true }); }
});

await test("real docs sources retain printer and Unicode source correspondence", async () => {
  const compiler = createAstroCompiler({ cwd: path.resolve(import.meta.dirname, "..") });
  try {
    for (const name of ["RuleExample", "ThirdPartyRuleList"]) {
      const filename = path.resolve(import.meta.dirname, `../src/components/${name}.astro`);
      const source = await readFile(filename, "utf8");
      const compiled = await compiler.compile(source, filename);
      assert.ok(compiled.text.length > 0);
      for (const script of compiled.scripts) {
        assert.equal(source.slice(script.start, script.start + script.text.length), script.text);
      }
      if (name === "RuleExample") {
        const expression = "afterFilesByPath.get(file.path)!";
        const start = compiled.text.indexOf(expression);
        assert.ok(start >= 0);
        const mapped = mapAstroRange(compiled.origin, [start, start + expression.length], { exact: true });
        assert.ok(mapped);
        assert.equal(source.slice(...mapped), expression);
      } else assert.equal(compiled.scripts.length, 1);
    }
    for (const source of [
      "<p>💡 مرحبا</p><script>\nconst clientValue = 1;\n</script><Card client:only />",
      '---\nconst label = "💡 مرحبا";\n---\n<p>{label}</p><script>\nconst clientValue = 1;\n</script><Card client:only />',
    ]) {
      const compiled = await compiler.compile(source, "Unicode.astro");
      const [script] = compiled.scripts;
      assert.equal(source.slice(script.start, script.start + script.text.length), script.text);
      if (compiled.frontmatter) assert.equal(source.slice(compiled.frontmatter.start, compiled.frontmatter.start + compiled.frontmatter.text.length), compiled.frontmatter.text);
      const component = compiled.origin.elements.find((element) => element.name === "Card");
      assert.equal(source.slice(component.start, component.start + 5), "<Card");
      assert.equal(source.slice(component.attributes[0].start, component.attributes[0].start + 11), "client:only");
    }
  } finally { compiler.close(); }
});

const hostBindings = [
  ["implicit Props with Astro access", '---\ninterface Props { label: string }\nconst { label } = Astro.props;\n---\n<p>{label}</p>', { "eslint/no-unused-vars": "error" }, []],
  ["Props without implicit framework access", '---\ninterface Props { label: string }\n---\n<p />', { "eslint/no-unused-vars": "error" }, ["eslint(no-unused-vars)"]],
  ["nested Props is not a framework contract", '---\ninterface Props { label: string }\nconst { label } = Astro.props;\nfunction read() { interface Props { nested: string } return label; }\n---\n<p>{read()}</p>', { "eslint/no-unused-vars": "error" }, ["eslint(no-unused-vars)"]],
  ["value Props is not a framework contract", '---\nconst Props = 1;\nAstro.redirect("/");\n---\n<p />', { "eslint/no-unused-vars": "error" }, ["eslint(no-unused-vars)"]],
  ["authored component helper name stays available", '---\nconst Component__AstroComponent_ = 1;\nconst value = Astro.url;\n---\n<p>{Component__AstroComponent_}{value}</p>', { "eslint/no-unused-vars": "error", "eslint/no-undef": "error" }, []],
  ["unrelated unused interface", '---\ninterface Props { label: string }\ninterface Unused { value: string }\nconst { label } = Astro.props;\n---\n<p>{label}</p>', { "eslint/no-unused-vars": "error" }, ["eslint(no-unused-vars)"]],
  ["unused authored local", '---\nconst unused = 1;\n---\n<p />', { "eslint/no-unused-vars": "error" }, ["eslint(no-unused-vars)"]],
  ["authored unused options", '---\nconst unused = 1;\n---\n<p />', { "eslint/no-unused-vars": ["error", { varsIgnorePattern: "^unused$" }] }, []],
  ["genuine Fragment host binding", '<Fragment><p>Content</p></Fragment>', { "eslint/no-undef": "error" }, []],
  ["local Fragment binding", '---\nconst Fragment = () => null;\n---\n<Fragment />', { "eslint/no-undef": "error", "eslint/no-redeclare": ["error", { builtinGlobals: true }] }, []],
  ["unknown authored binding", '<p>{missingRuntime}</p>', { "eslint/no-undef": "error" }, ["eslint(no-undef)"]],
  ["server redirect with template", '---\nreturn Astro.redirect("/", 301);\n---\n<p>Redirect</p>', { "eslint/no-unreachable": "error" }, []],
  ["authored unreachable server statement", '---\nreturn Astro.redirect("/", 301);\nconsole.log("unreachable");\n---\n<p>Redirect</p>', { "eslint/no-unreachable": "error" }, ["eslint(no-unreachable)"]],
  ["default client script TypeScript", '<script>\ninterface SearchEntry { label: string }\nconst entry: SearchEntry = { label: "result" };\nconsole.log(entry.label);\n</script>', { "eslint/no-unused-vars": "error", "eslint/no-undef": "error" }, []],
  ["binding directives retain original custody", '---\n// oxlint-disable-next-line no-unused-vars -- narrow genuine unused binding control\nconst unused = 1;\n---\n<p />', { "eslint/no-unused-vars": "error" }, []],
];
for (const [name, source, rules, expected] of hostBindings) {
  await test(name, async () => {
    const { diagnostics } = await lint(source, { rules });
    assert.deepEqual(diagnostics.map((diagnostic) => diagnostic.code), expected);
  });
}

await test("authored Fragment global exclusion survives matching overrides", async () => {
  const { diagnostics } = await lint("<Fragment />", {
    rules: { "eslint/no-undef": "error" }, globals: { Fragment: "off" },
    overrides: [{ files: ["**/*.astro"], rules: { "eslint/no-debugger": "error" } }],
  });
  assert.deepEqual(diagnostics.map((diagnostic) => diagnostic.code), ["eslint(no-undef)"]);
});


for (const extension of ["json", "jsonc"]) {
  await test(`native ${extension} config retains comments and trailing commas`, async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "sarj-astro-json-config-"));
    try {
      const filename = path.join(directory, "Page.astro");
      const configPath = path.join(directory, `.oxlintrc.${extension}`);
      await writeFile(filename, "---\ndebugger;\n---\n<p />");
      await writeFile(configPath, `{
        // Genuine native JSON configuration syntax.
        "categories": { "correctness": "off", },
        "plugins": ["eslint"],
        "rules": { "eslint/no-debugger": "error", },
      }`);
      const report = await lintAstroFiles({ filenames: [filename], configPath, cwd: path.resolve(import.meta.dirname, "..") });
      assert.deepEqual(report.diagnostics.map((diagnostic) => diagnostic.code), ["eslint(no-debugger)"]);
      await writeFile(configPath, '{"rules": { broken }}');
      await assert.rejects(lintAstroFiles({ filenames: [filename], configPath, cwd: path.resolve(import.meta.dirname, "..") }), /Invalid Oxlint configuration/);
    } finally { await rm(directory, { recursive: true, force: true }); }
  });
}
