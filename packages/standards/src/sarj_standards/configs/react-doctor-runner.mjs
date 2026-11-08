// Native Oxlint diagnostics plus official security scan callbacks; no React Doctor CLI.
import { execFileSync, spawnSync } from "node:child_process";
// eslint-disable-next-line @sarj/prefer-node-fs-promises -- This short-lived adapter performs a bounded synchronous scan and then exits.
import { existsSync, lstatSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import {
  hideWarning,
  ignoredFinding,
  ruleSeverity,
  scanSecurity,
  severityOverride,
  sourcePosition,
} from "./react-doctor-scan.mjs";
import { projectSettings } from "./project-settings.mjs";
import { stagedRequest } from "./staged-request.mjs";
import { htmlScriptSource } from "./html-script-source.mjs";

const request = JSON.parse(process.argv[2] ?? readFileSync(0, "utf8"));
const require = createRequire(join(request.installRoot, "package.json"));
const pluginPath = require.resolve("oxlint-plugin-react-doctor");
const installedPlugin = JSON.parse(
  readFileSync(join(dirname(pluginPath), "../package.json"), "utf8"),
);
if (installedPlugin.version !== "0.9.22")
  throw new Error(`Expected oxlint-plugin-react-doctor 0.9.22, found ${installedPlugin.version}`);
const plugin = await import(pathToFileURL(pluginPath));
const core = await import(pathToFileURL(require.resolve("oxlint-plugin-react-doctor/core")));
const { parseSync, visitorKeys } = createRequire(pluginPath)("oxc-parser");
const { parse: parseHtml } = await import(pathToFileURL(require.resolve("parse5")));
const sources = new Map();
const originalSources = new Map();
const oxlintRoot = dirname(require.resolve("oxlint/package.json"));
const installedOxlint = JSON.parse(readFileSync(join(oxlintRoot, "package.json"), "utf8"));
if (installedOxlint.version !== "1.91.0")
  throw new Error(`Expected Oxlint 1.91.0, found ${installedOxlint.version}`);
const diagnostics = [];
const isExcluded = (absolute) =>
  (request.excludedDirectories ?? []).some((directory) => contains(directory, absolute));
const temporary = mkdtempSync(join(tmpdir(), "standards-doctor-"));

function contains(directory, path) {
  const child = relative(directory, path);
  return child === "" || (!isAbsolute(child) && child !== ".." && !child.startsWith(`..${sep}`));
}

function selectedProject(project) {
  if (request.fullScan) return true;
  return (
    request.paths.some((path) => {
      if (contains(path, project.root)) return true;
      if (project.excluded.some((directory) => contains(directory, path))) return false;
      return contains(project.root, path);
    }) || (request.metadataPaths ?? []).some((path) => contains(dirname(path), project.root))
  );
}

function fullProjectScope(project) {
  return (
    request.fullScan ||
    (request.metadataPaths ?? []).some((path) => contains(dirname(path), project.root))
  );
}

function selectedSources(project) {
  const files = execFileSync(
    "git",
    ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
    { cwd: project.root, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 },
  )
    .split("\0")
    .filter(Boolean);
  return [...new Set(files)]
    .filter((file) => /\.(?:[cm]?[jt]sx?|astro|html)$/i.test(file) && !/\.d\.[cm]?ts$/.test(file))
    .filter((file) => {
      const absolute = resolve(project.root, file);
      if (!existsSync(absolute) || !lstatSync(absolute).isFile()) return false;
      if (
        /\.(?:iife|umd|global|min)\.m?js$/i.test(file) ||
        file
          .split(/[\\/]/)
          .some((part) =>
            [
              "node_modules",
              ".git",
              "dist",
              "build",
              "out",
              ".next",
              "coverage",
              "vendor",
              "__generated__",
            ].includes(part),
          )
      )
        return false;
      if (isExcluded(absolute) || project.excluded.some((path) => contains(path, absolute)))
        return false;
      return project.fullScan || request.paths.some((path) => contains(path, absolute));
    })
    .sort();
}

function nativeDiagnostics(project, config, settings) {
  if (!project.files.length) return [];
  const capabilities = new Set(settings.capabilities);
  const rules = Object.fromEntries(
    plugin.REACT_DOCTOR_RULES.filter((entry) => {
      const rule = entry.rule;
      return (
        !rule.scan &&
        rule.execution !== "project" &&
        (rule.requires ?? []).every((cap) => capabilities.has(cap)) &&
        !(rule.disabledWhen ?? []).some((cap) => capabilities.has(cap)) &&
        (rule.framework === "global" || rule.requires || rule.framework === settings.framework)
      );
    }).map((entry) => [entry.key, ruleSeverity(entry, config)]),
  );
  const configPath = join(temporary, "oxlint.config.json");
  // Oxlint validates plugin paths with the native filesystem before importing them.
  // A physical entrypoint lets Yarn's ESM loader resolve the official plugin in ZipFS.
  const nativePluginPath = join(temporary, "react-doctor-plugin.mjs");
  writeFileSync(
    nativePluginPath,
    `export { default } from ${JSON.stringify(pathToFileURL(pluginPath).href)};\n`,
  );
  writeFileSync(
    configPath,
    JSON.stringify({
      plugins: request.includeCompiler ? ["react"] : [],
      categories: { correctness: "off" },
      jsPlugins: [{ name: "react-doctor", specifier: nativePluginPath }],
      settings: {
        "react-doctor": {
          ...settings,
          serverAuthFunctionNames: config.serverAuthFunctionNames ?? [],
        },
      },
      rules: { ...rules, ...nativeCompilerRules(config, project, settings) },
    }),
  );
  return [...sourceBatches(project)].flatMap((files) =>
    runNativeBatch(files, project.root, configPath, config),
  );
}

function nativeCompilerRules(config, project, settings) {
  if (!request.includeCompiler || !settings.compilerChecks) return {};
  // The full gate already runs these native rules. component-hook-factories
  // was removed upstream in 7.1.0 and its implementation returns no visitors.
  const pkg = JSON.parse(readFileSync(join(project.root, "package.json"), "utf8"));
  const isLibrary = pkg.name && pkg.exports != null && pkg.private !== true;
  const rules = Object.entries(core.REACT_COMPILER_RULES).filter(
    ([key]) => !["react-hooks-js/todo", "react-hooks-js/component-hook-factories"].includes(key),
  );
  return Object.fromEntries(
    rules.map(([key, severity]) => [
      key === "react-hooks-js/hooks"
        ? "react/rules-of-hooks"
        : key.replace("react-hooks-js/", "react/"),
      isLibrary && key === "react-hooks-js/static-components" && config.rules?.[key] === undefined
        ? "off"
        : ruleSeverity(
            {
              key,
              id: key.slice("react-hooks-js/".length),
              rule: { severity, category: "React Compiler" },
            },
            config,
          ),
    ]),
  );
}

function* sourceBatches(project) {
  let files = [];
  let size = 0;
  // Leave room for the executable and config on Windows' 32 KiB command line.
  for (const file of project.files) {
    let absolute = resolve(project.root, file);
    if (/\.html$/i.test(file)) {
      const prepared = join(temporary, `${originalSources.size}.astro`);
      writeFileSync(prepared, htmlScriptSource(readFileSync(absolute, "utf8"), parseHtml));
      originalSources.set(prepared, absolute);
      absolute = prepared;
    }
    const length = Buffer.byteLength(absolute) + 3;
    if (files.length && size + length > 16000) {
      yield files;
      files = [];
      size = 0;
    }
    files.push(absolute);
    size += length;
  }
  if (files.length) yield files;
}

function runNativeBatch(files, root, configPath, config) {
  const result = spawnSync(
    process.execPath,
    [join(oxlintRoot, "bin/oxlint"), "-c", configPath, "--format=json", "--", ...files],
    { cwd: temporary, encoding: "utf8", timeout: 600000, maxBuffer: 16 * 1024 * 1024 },
  );
  if (result.error) throw result.error;
  if (![0, 1].includes(result.status))
    throw new Error(`Oxlint failed: ${result.stderr || result.stdout}`);
  let report;
  try {
    report = JSON.parse(result.stdout);
  } catch {
    throw new Error(`Oxlint failed: ${result.stderr || result.stdout}`);
  }
  if (report["number_of_files"] !== files.length)
    throw new Error(
      `Oxlint analyzed ${report["number_of_files"]} of ${files.length} selected files`,
    );
  for (const record of report.diagnostics) {
    if (!record.code || record.message.startsWith("Error running JS plugin"))
      throw new Error(`Oxlint failed: ${record.message}`);
  }
  return report.diagnostics.flatMap((record) => nativeFinding(record, root, config));
}

function nativeFinding(record, root, config) {
  // Native reports may use paths relative to the invocation working directory.
  const filename = resolve(temporary, record.filename);
  record.filename = originalSources.get(filename) ?? filename;
  const rule = record.code.slice(record.code.indexOf("(") + 1, -1);
  const severity = record.severity === "warning" ? "warn" : "error";
  const finding = oxlintFinding(record, root, rule, severity);
  const key = legacyRuleKey(finding);
  const override = severityOverride(
    { key, id: rule, rule: { category: "React Compiler" } },
    config,
  );
  if (hideWarning(severity, override, config)) return [];
  const file = sourceFile(resolve(root, record.filename), root);
  if (ignoredFinding(file, finding, key, config)) return [];
  const offset = record.labels?.[0]?.span?.offset;
  if (offset !== undefined) finding.sourcePosition = sourcePosition(file.content, offset);
  return [finding];
}

function sourceFile(filename, root) {
  if (sources.has(filename)) return sources.get(filename);
  const content = readFileSync(filename, "utf8");
  const openers = [];
  if (content.includes("react-doctor-disable-next-line") && /\.[cm]?[jt]sx$/.test(filename)) {
    const visit = (node) => {
      if (node.type === "JSXOpeningElement")
        openers.push({
          start: content.slice(0, node.start).split("\n").length,
          end: content.slice(0, node.end).split("\n").length,
        });
      for (const key of visitorKeys[node.type] ?? []) {
        const children = Array.isArray(node[key]) ? node[key] : [node[key]];
        for (const child of children) if (child) visit(child);
      }
    };
    visit(parseSync(filename, content).program);
  }
  const file = { relativePath: relative(root, filename).replaceAll("\\", "/"), content, openers };
  sources.set(filename, file);
  return file;
}

function oxlintFinding(record, root, rule, severity) {
  const namespace = record.code.slice(0, record.code.indexOf("("));
  const plugin = namespace === "react-hooks" ? "react" : namespace;
  const span = record.labels?.[0]?.span;
  return {
    filePath: relative(root, record.filename).replaceAll("\\", "/"),
    plugin,
    rule,
    severity: severity === "warn" ? "warning" : "error",
    message: record.message,
    line: span?.line ?? 1,
    column: span?.column ?? 1,
    help: record.help,
  };
}

function legacyRuleKey(finding) {
  if (finding.plugin !== "react") return `react-doctor/${finding.rule}`;
  return `react-hooks-js/${finding.rule === "rules-of-hooks" ? "hooks" : finding.rule}`;
}

try {
  const originalPath = request.staged ? stagedRequest(request, temporary) : (path) => path;
  for (const project of request.projects.filter(selectedProject)) {
    project.fullScan = fullProjectScope(project);
    let config;
    if (request.config.endsWith(".json")) {
      config = JSON.parse(readFileSync(request.config, "utf8"));
    } else {
      if (request.trustRepositoryCode !== true)
        throw new Error("Executable Doctor config requires --trust-repository-code");
      config = (await import(pathToFileURL(request.config).href)).default;
    }
    // eslint-disable-next-line @sarj/no-runtime-typeof -- Module exports and parsed JSON are raw boundary values; reject non-object configs before native callbacks.
    if (config === null || typeof config !== "object" || Array.isArray(config))
      throw new Error("Doctor config must export an object");
    project.files = selectedSources(project);
    const settings = projectSettings(project.root, core, request.repositoryRoot, parseSync);
    const findings = [
      ...nativeDiagnostics(project, config, settings),
      ...scanSecurity(project.root, core, config, project.excluded, isExcluded, {
        parseSync,
        visitorKeys,
      }),
    ];
    diagnostics.push(
      ...findings.map((finding) => ({
        ...finding,
        filePath: originalPath(resolve(project.root, finding.filePath)),
        plugin: finding.plugin ?? "react-doctor",
      })),
    );
  }
  console.log(JSON.stringify({ complete: true, diagnostics }));
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
