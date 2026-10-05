import { randomUUID, hash } from "node:crypto";
import { readFile, writeFile, unlink } from "node:fs/promises";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { TraceMap, originalPositionFor } from "@jridgewell/trace-mapping";
import { parse, printParseErrorCode } from "jsonc-parser";
import { createAstroCompiler, mapAstroRange } from "./astro.mjs";

// Provider ownership, not policy declarations. Severities, options, globals,
// settings and file scopes are taken exclusively from the supplied native config.
const ORIGINAL_SOURCE = new Set([
  "no-irregular-whitespace", "no-loss-of-precision", "no-setter-return",
  "no-unexpected-multiline", "no-useless-escape", "no-octal",
  "no-nonoctal-decimal-escape", "no-comment-cruft", "excessive-commentary",
  "no-declaration-comment-wall", "no-restated-comment", "no-restated-jsdoc",
  "no-long-comment", "no-type-member-comment-wall", "no-trailing-value-narration",
  "no-union-in-comment", "no-vague-suppression-description", "no-typed-doc-sections",
  "test-phase-label-comment",
  "no-unreachable",
]);

/** Append the document suffix to the authored glob; stock Oxlint still matches it. */
export function projectAstroPattern(pattern, suffix) {
  if (typeof pattern !== "string" || pattern.includes("\\") || /[[\]@()+]/u.test(pattern)) {
    throw new Error(`Unsupported Astro scope pattern: ${JSON.stringify(pattern)}`);
  }
  const negative = pattern.startsWith("!") ? "!" : "";
  const value = negative ? pattern.slice(1) : pattern;
  return `${negative}${value.endsWith("/**") || value.endsWith("/") ? `${value.replace(/\/$/u, "") }/*` : value}${suffix}`;
}

/** Execute genuine native documents in their original directories and clean them in finally. */
export async function lintAstroFiles({ filenames, configPath, cwd = process.cwd(), fix = false, fixSuggestions = false, typeAware = false }) {
  if (filenames.length === 0) return { diagnostics: [], "number_of_files": 0, appliedFixes: 0, skippedFixes: [] };
  const configFilename = path.resolve(cwd, configPath);
  const config = await loadConfig(configFilename);
  const selected = await discoverFiles(filenames, configFilename, cwd);
  const compiler = createAstroCompiler({ cwd });
  const execution = {
    config, configFilename, cwd, fix, fixSuggestions,
    typeArguments: typeAware ? ["--type-aware"] : [],
    jsPluginNames: config.jsPlugins?.map((plugin) => plugin.name) ?? [],
    nonce: randomUUID(), created: [], results: [], skippedFixes: [],
    appliedFixes: 0, documentIndex: 0,
  };
  try {
    for (const filename of selected) {
      const source = await readFile(filename, "utf8");
      const compiled = await compiler.compile(source, filename);
      await lintCompiledFile(compiled, execution);
    }
    if (execution.appliedFixes) {
      const checked = await lintAstroFiles({ filenames, configPath, cwd, typeAware });
      return { ...checked, appliedFixes: execution.appliedFixes, skippedFixes: execution.skippedFixes };
    }
    const unique = new Map(execution.results.map((diagnostic) => [JSON.stringify(diagnostic), diagnostic]));
    return { diagnostics: [...unique.values()], "number_of_files": selected.length,
      appliedFixes: execution.appliedFixes, skippedFixes: execution.skippedFixes };
  } finally {
    compiler.close();
    await Promise.all(execution.created.map((filename) => unlink(filename)));
  }
}

async function loadConfig(configFilename) {
  const config = [".json", ".jsonc"].includes(path.extname(configFilename))
    ? parseNativeConfig(await readFile(configFilename, "utf8"), configFilename)
    : (await import(pathToFileURL(configFilename).href)).default;
  if (config.jsPlugins?.some((plugin) => typeof plugin !== "object" || typeof plugin.name !== "string")) {
    throw new Error("Astro source custody requires explicitly named native JS plugins");
  }
  if (config.overrides?.some((entry) => entry.options?.reportUnusedDisableDirectives !== undefined)) {
    throw new Error("Astro unused-directive severity must be declared once in native root options");
  }
  if (config.categories?.correctness !== "off" || Object.values(config.categories).some((level) => level !== "off")) {
    throw new Error("Astro provider ownership requires explicit native rules and disabled implicit categories");
  }
  return config;
}

function parseNativeConfig(source, filename) {
  const errors = [];
  const config = parse(source, errors, { allowTrailingComma: true });
  if (errors.length) throw new Error(`Invalid Oxlint configuration ${filename}: ${printParseErrorCode(errors[0].error)}`);
  return config;
}

async function discoverFiles(filenames, configFilename, cwd) {
  const discovered = await command(["--config", configFilename, "--no-error-on-unmatched-pattern", "--debug", "files", "--", ...filenames], cwd);
  if (discovered.status !== 0) throw new Error(`Astro discovery failed: ${discovered.stderr}`);
  const selected = discovered.stdout.split(/\r?\n/u).filter(Boolean).map((filename) => path.resolve(cwd, filename));
  const requested = new Set(filenames.map((filename) => path.resolve(cwd, filename)));
  if (selected.some((filename) => !requested.has(filename) || !filename.endsWith(".astro"))) {
    throw new Error("Oxlint Astro discovery returned an unexpected file");
  }
  return selected;
}

async function lintCompiledFile(compiled, execution) {
  const sourceDirectives = directives(compiled.origin);
  for (const { name: provider, entries } of createProviders(compiled)) {
    for (const [index, document] of entries.entries()) {
      const materialized = await materializeDocument(compiled, document, provider, index, execution);
      const report = await nativeReport(materialized, execution);
      const unused = collectDiagnostics(report, document, provider, compiled, sourceDirectives, execution);
      if (provider === "original") originalUse(document, sourceDirectives, unused,
        report.diagnostics.some((diagnostic) => diagnostic.code?.startsWith("Oxc")));
      if (execution.fix && provider === "module") {
        await applyNativeFix(materialized, document, compiled, sourceDirectives, execution);
      }
    }
  }
  execution.results.push(...unusedDirectives(compiled.origin, sourceDirectives,
    execution.config.options?.reportUnusedDisableDirectives, execution.jsPluginNames));
}

function createProviders(compiled) {
  const originalDocuments = compiled.rawRegions.map((region) => ({
    text: region.expression ? `(${region.text});` : region.text,
    origin: compiled.origin,
    spans: [{ virtual: region.expression ? [1, region.text.length + 1] : [0, region.text.length],
      original: [region.start, region.start + region.text.length], exact: true }],
    map: ([start, end]) => region.expression && (start < 1 || end > region.text.length + 1)
      ? [region.start, region.start + region.text.length]
      : [region.start + start - (region.expression ? 1 : 0), region.start + end - (region.expression ? 1 : 0)],
  }));
  const clientDocuments = compiled.scripts.map((region) => ({
    text: region.text, language: region.language, origin: compiled.origin,
    map: ([start, end]) => [region.start + start, region.start + end],
  }));
  return [
    { name: "module", entries: [{ text: compiled.text, origin: compiled.origin, map: (range) => mapAstroRange(compiled.origin, range) }] },
    { name: "bindings", entries: [{ text: compiled.bindingsText, origin: compiled.origin,
      generatedStart: compiled.text.length, map: (range) => mapAstroRange(compiled.origin, range) }] },
    { name: "original", entries: originalDocuments },
    { name: "javascript", entries: [javascriptDocument(compiled)] },
    { name: "client", entries: clientDocuments },
  ];
}

function javascriptDocument(compiled) {
  const printedLines = [0];
  for (let index = 0; index < compiled.text.length; index++) if (compiled.text[index] === "\n") printedLines.push(index + 1);
  const sourceMap = new TraceMap(compiled.javascript.sourceMapText);
  const text = compiled.javascript.outputText;
  return {
    text, origin: compiled.origin,
    map: (range) => {
      const positions = range.map((offset) => originalPositionFor(sourceMap, position(text, offset)));
      if (positions.some((entry) => entry.line === null)) return null;
      return mapAstroRange(compiled.origin, positions.map((entry) => printedLines[entry.line - 1] + entry.column));
    },
  };
}

async function materializeDocument(compiled, document, provider, index, execution) {
  const { filename, text: source } = compiled.origin;
  const extension = document.language ?? (provider === "javascript" ? "jsx" : "tsx");
  const suffix = `.sarj-astro-${execution.nonce}-${provider}-${index}.${extension}`;
  const virtualFilename = filename + suffix;
  const origin = provider === "module" ? compiled.origin : {
    filename, text: source, virtualHash: hash("sha256", document.text),
    spans: document.spans ?? [{ virtual: [0, document.text.length],
      original: provider === "client" ? document.map([0, document.text.length]) : [0, source.length], exact: provider === "client" }],
    ...(provider === "client" && { region: "client-script" }),
  };
  await writeFile(virtualFilename, document.text, { flag: "wx" });
  execution.created.push(virtualFilename);
  const metadata = { [virtualFilename]: origin };
  const projected = projectConfig(execution.config, provider, suffix, metadata);
  const configFile = path.join(path.dirname(execution.configFilename), `.sarj-astro-${execution.nonce}-${execution.documentIndex++}.mjs`);
  await writeFile(configFile, `export default ${JSON.stringify(projected)};\n`, { flag: "wx" });
  execution.created.push(configFile);
  return { virtualFilename, configFile, suffix, metadata };
}

async function nativeReport({ configFile, virtualFilename }, execution) {
  const native = await command([...execution.typeArguments, "--config", configFile, "--format", "json", "--", virtualFilename], execution.cwd);
  let report;
  try { report = JSON.parse(native.stdout); } catch { throw new Error(`Astro provider returned invalid JSON: ${native.stderr || native.stdout}`); }
  if (report["number_of_files"] !== 1) throw new Error("Astro provider did not check its maintained document");
  return report;
}

function collectDiagnostics(report, document, provider, compiled, sourceDirectives, execution) {
  const unused = [];
  for (const diagnostic of report.diagnostics) {
    if (diagnostic.message.startsWith("Error running JS plugin")) throw new Error(diagnostic.message);
    if (generatedBindingDiagnostic(diagnostic, document, provider)) continue;
    const mapped = mappedDiagnostic(diagnostic, document);
    if (rawWhitespaceDiagnostic(mapped, compiled, provider)) continue;
    if (provider === "client") execution.results.push(mapped);
    else if (mapped.message.startsWith("Unused oxlint-disable directive")) unused.push(mapped);
    else if (provider === "original" || !suppressModule(mapped, sourceDirectives, compiled.origin, execution.jsPluginNames)) execution.results.push(mapped);
  }
  return unused;
}

function generatedBindingDiagnostic(diagnostic, document, provider) {
  // Only the official compiler component signature is generated here. Its
  // bindings retain implicit Props usage; its parameters are not authored.
  return provider === "bindings" && ["eslint(no-unused-vars)", "eslint(no-undef)"].includes(diagnostic.code) &&
    diagnostic.labels?.length && diagnostic.labels.every((label) =>
      utf16Offset(document.text, label.span.offset) >= document.generatedStart);
}

function rawWhitespaceDiagnostic(diagnostic, compiled, provider) {
  if (provider !== "module" || !codeId(diagnostic.code)?.endsWith("/no-irregular-whitespace")) return false;
  const offset = utf16Offset(compiled.origin.text, diagnostic.labels[0].span.offset);
  // Original code regions own raw whitespace; the full genuine module owns
  // only markup text outside those regions.
  return compiled.rawRegions.some((region) => offset >= region.start && offset < region.start + region.text.length);
}

async function applyNativeFix(materialized, document, compiled, sourceDirectives, execution) {
  const { filename, text: source } = compiled.origin;
  if (sourceDirectives.length) {
    execution.skippedFixes.push({ filename, reason: "Source directives require preserving the complete authored document during fixes" });
    return;
  }
  const { configFile, virtualFilename, suffix, metadata } = materialized;
  const fixConfig = projectConfig(execution.config, "module", suffix, metadata, true);
  await writeFile(configFile, `export default ${JSON.stringify(fixConfig)};\n`);
  await command([...execution.typeArguments, "--config", configFile, execution.fixSuggestions ? "--fix-suggestions" : "--fix", "--format", "json", "--", virtualFilename], execution.cwd);
  const edited = await readFile(virtualFilename, "utf8");
  if (edited === document.text) return;
  const edit = exactSourceEdit(compiled.origin, document.text, edited);
  if (!edit) {
    execution.skippedFixes.push({ filename, reason: "Native edits do not share a proven exact original source span" });
    return;
  }
  if (await readFile(filename, "utf8") !== source) throw new Error("Astro source changed during linting; refusing a stale fix");
  await writeFile(filename, source.slice(0, edit.start) + edit.replacement + source.slice(edit.end));
  execution.appliedFixes++;
}

function exactSourceEdit(origin, before, after) {
  let start = 0;
  let tail = 0;
  while (before[start] === after[start] && start < Math.min(before.length, after.length)) start++;
  while (tail < before.length - start && tail < after.length - start &&
    before[before.length - tail - 1] === after[after.length - tail - 1]) tail++;
  const range = mapAstroRange(origin, [start, before.length - tail], { exact: true });
  return range && { start: range[0], end: range[1], replacement: after.slice(start, after.length - tail) };
}
function owner(id) {
  const name = id.slice(id.lastIndexOf("/") + 1);
  const prefix = id.includes("/") ? id.slice(0, id.lastIndexOf("/")) : "eslint";
  if (!["eslint", "sarj-core", "@sarj"].includes(prefix)) return "module";
  if (["no-unused-vars", "no-undef"].includes(name) && prefix !== "@sarj") return "bindings";
  return name === "getter-return" && prefix !== "@sarj" ? "javascript" : ORIGINAL_SOURCE.has(name) ? "original" : "module";
}

function projectConfig(config, provider, suffix, documents, fix = false) {
  if (config.extends?.length || config.overrides?.some((entry) => entry.extends?.length)) {
    throw new Error("Astro processing requires a native config with resolved public imports, without extends");
  }
  function layer(value, root = false) {
    return {
      ...value,
      // Astro's server and browser regions have different host globals.
      // Explicit configured globals remain authoritative in either region.
      env: { ...value.env, node: provider !== "client", browser: provider === "client", astro: provider !== "client" },
      ...(provider === "bindings" && root && { globals: { Fragment: "readonly", ...value.globals } }),
      ...(value.files && { files: value.files.map((pattern) => projectAstroPattern(pattern, suffix)) }),
      ...(value.excludeFiles && { excludeFiles: value.excludeFiles.map((pattern) => projectAstroPattern(pattern, suffix)) }),
      ...(value.ignorePatterns && { ignorePatterns: value.ignorePatterns.map((pattern) => projectAstroPattern(pattern, suffix)) }),
      ...(value.rules && { rules: Object.fromEntries(Object.entries(value.rules).map(([id, rule]) =>
        [id, (provider === "client" || owner(id) === provider ||
          provider === "module" && owner(id) === "original" && id.slice(id.lastIndexOf("/") + 1) === "no-irregular-whitespace") &&
          (!fix || !config.jsPlugins?.some((plugin) => plugin.name === id.split("/")[0])) ? rule : "off"])) }),
    };
  }
  return {
    ...layer(config, true),
    settings: { ...config.settings, sarjSourceDocuments: documents },
    // Implicit category defaults must not introduce a second provider owner.
    categories: Object.fromEntries(["correctness", "suspicious", "pedantic", "perf", "style", "restriction", "nursery"].map((category) => [category, "off"])),
    options: { ...config.options, reportUnusedDisableDirectives: fix ? "off" : "error" },
    ...(config.overrides && { overrides: config.overrides.map((entry) => layer(entry)) }),
  };
}

async function command(args, cwd) {
  const require = createRequire(path.join(cwd, "package.json"));
  const cli = path.join(path.dirname(require.resolve("oxlint/package.json")), "bin/oxlint");
  return await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [cli, ...args], { cwd, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    const timeout = setTimeout(() => child.kill(), 300_000);
    for (const [stream, append] of [[child.stdout, (chunk) => { stdout += chunk; }], [child.stderr, (chunk) => { stderr += chunk; }]]) {
      stream.setEncoding("utf8");
      stream.on("data", (chunk) => {
        append(chunk);
        if (stdout.length + stderr.length > 16 * 1024 * 1024) child.kill();
      });
    }
    child.on("error", reject);
    child.on("close", (status, signal) => {
      clearTimeout(timeout);
      if (signal || status === null || status > 1) reject(new Error(`Oxlint Astro provider failed (${signal ?? status}): ${stderr}`));
      else resolve({ status, stdout, stderr });
    });
  });
}

function utf16Offset(text, bytes) {
  const prefix = Buffer.from(text).subarray(0, bytes).toString("utf8");
  if (Buffer.byteLength(prefix) !== bytes) throw new Error("Oxlint returned a span inside a UTF-8 character");
  return prefix.length;
}

function mappedDiagnostic(diagnostic, document) {
  const labels = (diagnostic.labels ?? []).map((label) => {
    const start = utf16Offset(document.text, label.span.offset);
    const end = utf16Offset(document.text, label.span.offset + label.span.length);
    let range = document.map([start, end]);
    if (!range) throw new Error("Oxlint finding has no authored Astro span");
    if (["astro(no-conflict-set-directives)", "sarj-astro(no-conflict-set-directives)"].includes(diagnostic.code)) {
      const element = document.origin.elements?.find((candidate) =>
        candidate.start === range[0] && candidate.openingEnd === range[1]);
      const child = element?.children.find((candidate) => candidate.type !== "comment" &&
        (candidate.type !== "text" || candidate.value.trim()));
      if (child?.omittedExpression) range = [child.start, child.end];
    }
    const prefix = document.origin.text.slice(0, range[0]);
    const line = prefix.split("\n").length;
    const column = range[0] - prefix.lastIndexOf("\n");
    return { ...label, span: {
      offset: Buffer.byteLength(prefix),
      length: Buffer.byteLength(document.origin.text.slice(...range)), line, column,
    } };
  });
  return { ...diagnostic, filename: document.origin.filename, labels };
}

function codeId(code) {
  const match = /^(.+)\(([^)]+)\)$/u.exec(code ?? "");
  return match ? `${match[1]}/${match[2]}` : code;
}

function position(text, offset) {
  const prefix = text.slice(0, offset);
  return { line: prefix.split("\n").length, column: offset - prefix.lastIndexOf("\n") - 1 };
}

function directives(origin) {
  return origin.originalComments.flatMap((comment) => {
    if (comment.kind === "html") return [];
    const match = /^\s*oxlint-(disable-next-line|disable-line|disable|enable)\b([^]*?)(?:\s+--\s+[^]*)?$/u.exec(comment.value);
    if (!match) return [];
    const selectors = match[2].trim().split(/\s*,\s*/u).filter(Boolean);
    return [{ ...comment, operation: match[1], selectors,
      line: position(origin.text, comment.start).line,
      endLine: position(origin.text, comment.end).line,
      used: new Set(), rawUsed: new Set(),
    }];
  });
}

function matches(directive, rule, jsPluginNames) {
  return directive.selectors.length === 0 || directive.selectors.some((selector) =>
    selector === rule || !jsPluginNames.includes(rule?.split("/")[0]) &&
      selector.slice(selector.lastIndexOf("/") + 1) === rule.slice(rule.lastIndexOf("/") + 1));
}

function suppressModule(diagnostic, sourceDirectives, origin, jsPluginNames) {
  const rule = codeId(diagnostic.code);
  if (!rule || !diagnostic.labels?.length) return false;
  const offset = utf16Offset(origin.text, diagnostic.labels[0].span.offset);
  const end = utf16Offset(origin.text, diagnostic.labels[0].span.offset + diagnostic.labels[0].span.length);
  let suppressed = false;
  for (const interval of suppressionIntervals(sourceDirectives, origin)) {
    const selectors = interval.selectors?.filter((selector) => selector !== "*") ?? interval.directive.selectors;
    if (!matches({ selectors }, rule, jsPluginNames)) continue;
    if (interval.local ? offset >= interval.start && offset < interval.stop : offset < interval.stop && end > interval.start) {
      interval.directive.used.add(rule);
      suppressed = true;
    }
  }
  return suppressed;
}


function suppressionIntervals(sourceDirectives, origin) {
  const active = new Map();
  const intervals = [];
  for (const directive of sourceDirectives) {
    const local = localDirectiveInterval(directive, origin.text);
    if (local) intervals.push(local);
    else updateRangeDirectives(directive, active, intervals);
  }
  for (const [selector, directive] of active) {
    intervals.push({ directive, selectors: [selector], start: directive.end, stop: origin.text.length, local: false });
  }
  return intervals;
}

function localDirectiveInterval(directive, text) {
  if (directive.operation === "disable-line") {
    return { directive, start: text.lastIndexOf("\n", directive.start - 1) + 1,
      stop: directive.start + 2, local: true };
  }
  if (directive.operation !== "disable-next-line") return null;
  const lineEnd = text.indexOf("\n", directive.end);
  const followingEnd = lineEnd < 0 ? text.length : text.indexOf("\n", lineEnd + 1);
  return { directive, start: directive.end,
    stop: followingEnd < 0 ? text.length : followingEnd, local: true };
}

function updateRangeDirectives(directive, active, intervals) {
  const selectors = directive.selectors.length ? directive.selectors : ["*"];
  for (const selector of selectors) {
    if (directive.operation === "disable") {
      if (!active.has(selector)) active.set(selector, directive);
      continue;
    }
    const disabled = active.get(selector);
    if (!disabled) continue;
    intervals.push({ directive: disabled, selectors: [selector], start: disabled.end, stop: directive.start, local: false });
    active.delete(selector);
  }
}

function originalUse(document, sourceDirectives, unused, hasParserFailure) {
  if (hasParserFailure) return;
  const [start, end] = document.map([0, document.text.length]);
  for (const directive of sourceDirectives) {
    if (directive.operation === "enable" || directive.start < start || directive.end > end) continue;
    const records = unused.filter((diagnostic) => diagnostic.labels?.some((label) => {
      const offset = utf16Offset(document.origin.text, label.span.offset);
      return offset >= directive.start && offset < directive.end;
    }));
    if (directive.selectors.length === 0) {
      if (!records.length) directive.rawUsed.add("*");
      continue;
    }
    const allUnused = records.some((diagnostic) => diagnostic.message === "Unused oxlint-disable directive (no problems were reported).");
    for (const selector of directive.selectors) {
      if (allUnused) continue;
      const selectorUnused = records.some((diagnostic) => diagnostic.labels?.some((label) => {
        const offset = utf16Offset(document.origin.text, label.span.offset);
        return document.origin.text.slice(offset, offset + utf16Offset(document.origin.text.slice(offset), label.span.length)) === selector;
      }));
      if (!selectorUnused) directive.rawUsed.add(selector);
    }
  }
}

function unusedDirectives(origin, sourceDirectives, severity, jsPluginNames) {
  if (!severity || severity === "off" || severity === "allow") return [];
  return sourceDirectives.flatMap((directive) => {
    if (directive.operation === "enable") return [];
    const unused = directive.selectors.filter((selector) => !directive.rawUsed.has(selector) &&
      ![...directive.used].some((rule) => matches({ selectors: [selector] }, rule, jsPluginNames)));
    if (directive.selectors.length === 0 && (directive.used.size || directive.rawUsed.size) ||
      directive.selectors.length > 0 && unused.length === 0) return [];
    const all = unused.length === directive.selectors.length;
    const ranges = all ? [[directive.start, directive.end]] : unused.map((selector) => {
      const valueOffset = directive.value.indexOf(selector);
      const start = directive.start + 2 + valueOffset;
      if (valueOffset < 0 || origin.text.slice(start, start + selector.length) !== selector) {
        throw new Error("An Astro directive selector has no exact original source span");
      }
      return [start, start + selector.length];
    });
    return [{
      filename: origin.filename,
      severity: severity === "warn" || severity === "warning" ? "warning" : "error",
      message: all ? "Unused oxlint-disable directive (no problems were reported)."
        : `Unused oxlint-disable directive (no problems were reported from ${unused.join(", ")}).`,
      labels: ranges.map(([start, end]) => {
        const location = position(origin.text, start);
        return { span: { offset: Buffer.byteLength(origin.text.slice(0, start)),
          length: Buffer.byteLength(origin.text.slice(start, end)), line: location.line, column: location.column + 1 } };
      }),
    }];
  });
}
