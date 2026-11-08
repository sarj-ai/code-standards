// Bounded adapter for upstream project security callbacks. Rule implementations stay upstream.
import { execFileSync } from "node:child_process";
// eslint-disable-next-line @sarj/prefer-node-fs-promises -- This short-lived adapter performs a bounded synchronous scan and then exits.
import { closeSync, lstatSync, openSync, readSync, readdirSync, readFileSync } from "node:fs";
import { matchesGlob, relative, resolve } from "node:path";

import { reactDoctorArtifactPem } from "./react-doctor-artifact-pem.mjs";

const SKIP = new Set([
  ".git",
  ".open-next",
  ".turbo",
  ".vercel",
  "coverage",
  "node_modules",
  "tmp",
]);
const MAX_FILES_PER_BUCKET = 2500;

export function severityOverride(entry, config) {
  return (
    config.rules?.[entry.key] ??
    config.rules?.[entry.id] ??
    config.categories?.[entry.rule.category]
  );
}

function suppressionMatches(line, kind, key) {
  const match = line?.match(
    new RegExp(`(?:\\/\\/|\\/\\*)\\s*react-doctor-disable-${kind}\\b([^\\r\\n]*)`),
  );
  if (!match) return false;
  const rules = match[1]
    .replace(/\*\/.*/, "")
    .split(/\s+--\s+/)[0]
    .trim();
  return !rules || rules.split(/[,\s]+/).some((id) => id === key || `react-doctor/${id}` === key);
}

export function scanSecurity(root, core, config, excluded = [], isExcluded = () => false, parser) {
  const rules = core.REACT_DOCTOR_SCAN_RULES.filter(
    (entry) => ruleSeverity(entry, config) !== "off",
  );
  const diagnostics = new Map();
  for (const file of securityFiles(root, core, excluded, isExcluded)) {
    for (const diagnostic of scanFile(root, file, rules, config, parser))
      diagnostics.set(JSON.stringify(diagnostic), diagnostic);
  }
  return [...diagnostics.values()];
}

export function* securityFiles(root, core, excluded = [], isExcluded = () => false) {
  for (const candidates of securityCandidates(root, core, excluded, isExcluded)) {
    let count = 0;
    for (const candidate of candidates) {
      const file = readSecurityFile(candidate, core);
      if (!file) continue;
      if (++count > MAX_FILES_PER_BUCKET) break;
      yield file;
    }
  }
}

function readSecurityFile(candidate, core) {
  const stat = lstatSync(candidate.absolutePath);
  if (!stat.isFile()) return null;
  const isGeneratedBundle =
    candidate.isGeneratedBundleByName || isLargeMinified(candidate.absolutePath, stat.size);
  if (!core.shouldReadSecurityScanContent(candidate.relativePath, isGeneratedBundle)) return null;
  const limit = isGeneratedBundle ? 8 * 1024 * 1024 : 2 * 1024 * 1024;
  if (stat.size > limit) return null;
  return {
    absolutePath: candidate.absolutePath,
    relativePath: candidate.relativePath,
    content: readFileSync(candidate.absolutePath, "utf8"),
    isGeneratedBundle,
  };
}

function isLargeMinified(path, size) {
  if (size < 20000) return false;
  const descriptor = openSync(path, "r");
  try {
    const buffer = Buffer.alloc(65536);
    const count = readSync(descriptor, buffer, 0, buffer.length, 0);
    const prefix = buffer.toString("utf8", 0, count);
    const lines = prefix.split("\n");
    return (
      Math.max(...lines.map((line) => line.length)) > 1000 && prefix.length / lines.length > 500
    );
  } finally {
    closeSync(descriptor);
  }
}

function securityCandidates(root, core, excluded, isExcluded) {
  const buckets = { priority: [], artifact: [], other: [] };
  const visit = (directory, depth) => {
    if (depth > 8) return;
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) =>
      a.name.localeCompare(b.name),
    )) {
      const absolutePath = resolve(directory, entry.name);
      if (excluded.includes(absolutePath) || isExcluded(absolutePath) || entry.isSymbolicLink())
        continue;
      if (entry.isDirectory()) {
        if (!SKIP.has(entry.name)) visit(absolutePath, depth + 1);
        continue;
      }
      const relativePath = relative(root, absolutePath).replaceAll("\\", "/");
      const classification = core.classifySecurityScanFile(relativePath);
      if (classification)
        buckets[classification.bucket].push({ absolutePath, relativePath, ...classification });
    }
  };
  visit(root, 0);
  return Object.values(buckets);
}

export function ruleSeverity(entry, config) {
  if (ignoredRule(entry, config)) return "off";
  const override = severityOverride(entry, config);
  if (entry.rule.defaultEnabled === false && override === undefined) return "off";
  if (override !== undefined) return override;
  if (entry.key === "react-doctor/react-compiler-no-manual-memoization")
    return config.buckets?.["compiler-cleanup"] ?? entry.rule.severity;
  return entry.rule.severity;
}

function ignoredRule(entry, config) {
  if (config.ignore?.tags?.some((tag) => entry.rule.tags?.includes(tag))) return true;
  return config.ignore?.rules?.some((id) => id === entry.key || id === entry.id) ?? false;
}

function scanFile(root, file, rules, config, parser) {
  let ignored;
  return rules.flatMap((entry) => {
    if (entry.rule.committedFilesOnly) {
      ignored ??= gitIgnored(root, file.absolutePath);
      if (ignored) return [];
    }
    const content =
      entry.id === "artifact-secret-leak" ? reactDoctorArtifactPem(file, parser) : file.content;
    return scanRule(file, entry, config, content);
  });
}

function gitIgnored(root, file) {
  try {
    execFileSync("git", ["check-ignore", "--quiet", "--", file], { cwd: root, stdio: "pipe" });
    return true;
  } catch (error) {
    if (error.status === 1) return false;
    throw error;
  }
}

function scanRule(file, entry, config, content) {
  const override = severityOverride(entry, config);
  return entry.rule.scan({ ...file, content }).flatMap((finding) => {
    const severity = override ?? finding.severity ?? entry.rule.severity;
    if (hideWarning(severity, override, config)) return [];
    if (ignoredFinding(file, finding, entry.key, config)) return [];
    return [
      {
        filePath: file.relativePath,
        rule: entry.id,
        severity: severity === "warn" ? "warning" : "error",
        message: finding.message,
        line: finding.line,
        column: finding.column,
        sourcePosition: scanPosition(file.content, finding),
        help: finding.help ?? entry.rule.recommendation,
      },
    ];
  });
}

function scanPosition(content, finding) {
  const lines = content.split("\n");
  const prefix =
    lines
      .slice(0, finding.line - 1)
      .map((line) => `${line}\n`)
      .join("") + (lines[finding.line - 1] ?? "").slice(0, finding.column - 1);
  return sourcePosition(content, Buffer.byteLength(prefix));
}

export function sourcePosition(content, byteOffset) {
  const prefix = Buffer.from(content).subarray(0, byteOffset).toString("utf8");
  const lines = prefix.split("\n");
  return { line: lines.length - 1, character: lines.at(-1).length, byteOffset };
}

export function ignoredFinding(file, finding, key, config) {
  if (ignoredByConfig(file.relativePath, key, config)) return true;
  if (config.respectInlineDisables === false) return false;
  const lines = file.content.split(/\r?\n/);
  if (suppressionMatches(lines[finding.line - 1], "line", key)) return true;
  if (suppressedAbove(lines, finding.line, key)) return true;
  return (
    file.openers?.some(
      (opener) =>
        opener.start < finding.line &&
        opener.end >= finding.line &&
        finding.line - opener.start <= 32 &&
        suppressedAbove(lines, opener.start, key),
    ) ?? false
  );
}

function ignoredByConfig(path, key, config) {
  if (config.ignore?.files?.some((pattern) => matchesSourceGlob(path, pattern))) return true;
  return (
    config.ignore?.overrides?.some(
      (override) =>
        override.files.some((pattern) => matchesSourceGlob(path, pattern)) &&
        (!override.rules?.length ||
          override.rules.some((id) => id === key || `react-doctor/${id}` === key)),
    ) ?? false
  );
}

function suppressedAbove(lines, line, key) {
  // Upstream permits a stack of adjacent disable-next-line directives only.
  for (let index = line - 2; index >= Math.max(0, line - 11); index--) {
    if (!/react-doctor-disable-next-line\b/.test(lines[index])) return false;
    if (suppressionMatches(lines[index], "next-line", key)) return true;
  }
  return false;
}

export function hideWarning(severity, override, config) {
  return severity === "warn" && config.warnings === false && override !== "warn";
}

// Node's globstar skips hidden ancestors. Explicit source scopes must also own
// nested environments under .cache; ordinary segment patterns retain Node's semantics.
export function matchesSourceGlob(path, pattern) {
  if (matchesGlob(path, pattern)) return true;
  const parts = path.split("/");
  const patterns = pattern.split("/");
  const memo = new Map();
  const match = (i, j) => {
    const key = `${i}:${j}`;
    if (memo.has(key)) return memo.get(key);
    let result;
    if (j === patterns.length) result = i === parts.length;
    else if (patterns[j] === "**")
      result = match(i, j + 1) || (i < parts.length && match(i + 1, j));
    else
      result =
        i < parts.length &&
        matchesGlob(parts[i], patterns[j]) &&
        match(i + 1, j + 1);
    memo.set(key, result);
    return result;
  };
  return patterns.includes("**") && match(0, 0);
}
