// Standards writes a temporary `-c` module next to the consumer's Oxlint
// config that default-exports `createSelectedConfig(request)`. The result is
// the consumer config with one final override appended, so relative ignore
// patterns, override globs and JS plugin specifiers resolve exactly as in a
// native run. Spreading the config (instead of `extends`) matters: Oxlint
// 1.91 drops `ignorePatterns` from extended configs and rejects relative JS
// plugin specifiers inside them.
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

type Setting = unknown;
type Rules = Record<string, Setting>;
type JsPlugin = string | { readonly name: string; readonly specifier: string };

interface Override {
  readonly files: readonly string[];
  readonly rules?: Rules;
  readonly plugins?: readonly string[];
  readonly jsPlugins?: readonly JsPlugin[];
  readonly [key: string]: unknown;
}

interface Config {
  readonly extends?: readonly (Config | string)[];
  readonly rules?: Rules;
  readonly overrides?: readonly Override[];
  readonly plugins?: readonly string[];
  readonly jsPlugins?: readonly JsPlugin[];
  readonly categories?: Record<string, string>;
  readonly options?: Record<string, unknown>;
  readonly settings?: Record<string, unknown>;
  readonly [key: string]: unknown;
}

export interface SelectedRequest {
  // Absolute consumer config path; null runs Oxlint's defaults.
  readonly config: string | null;
  // Canonical rule IDs to keep; null keeps every configured rule.
  readonly rules: readonly string[] | null;
  // Rules forced on last, after every consumer override (the floor).
  readonly forced: Rules;
  // Per-path rules turned off before the forced rules apply.
  readonly disabled: readonly { files: readonly string[]; rules: readonly string[] }[];
  // Specifiers for JS plugin namespaces that forced rules need.
  readonly jsPlugins: Record<string, string>;
  // Rule-namespace aliases mapped to their canonical namespace ("" = bare).
  readonly aliases: Record<string, string>;
}

// Oxlint enables these when a config names no `plugins`.
const DEFAULT_PLUGINS = ["eslint", "typescript", "unicorn", "oxc"];
const EVERY_FILE = ["**/*"];

function isConfig(value: unknown): value is Config {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stripJsonComments(text: string): string {
  let result = "";
  let index = 0;
  while (index < text.length) {
    const char = text[index];
    if (char === '"') {
      const end = /"(?:[^"\\]|\\.)*"/y;
      end.lastIndex = index;
      const match = end.exec(text);
      if (match === null) throw new Error("unterminated string in Oxlint JSON config");
      result += match[0];
      index += match[0].length;
    } else if (text.startsWith("//", index)) {
      const newline = text.indexOf("\n", index);
      index = newline === -1 ? text.length : newline;
    } else if (text.startsWith("/*", index)) {
      const close = text.indexOf("*/", index + 2);
      if (close === -1) throw new Error("unterminated comment in Oxlint JSON config");
      index = close + 2;
    } else {
      result += char;
      index += 1;
    }
  }
  return result.replaceAll(/,(\s*[}\]])/gu, "$1");
}

async function loadConfig(path: string): Promise<Config> {
  const loaded: unknown = /\.jsonc?$/u.test(path)
    ? JSON.parse(stripJsonComments(readFileSync(path, "utf8")))
    : ((await import(pathToFileURL(path).href)) as { default?: unknown }).default;
  if (!isConfig(loaded)) throw new Error(`Oxlint config ${path} must export an object`);
  return loaded;
}

// Every config reachable through `extends`, nearest first.
async function chain(config: Config, directory: string): Promise<Config[]> {
  const configs = [config];
  for (const parent of config.extends ?? []) {
    if (typeof parent === "string") {
      const path = resolve(directory, parent);
      configs.push(...(await chain(await loadConfig(path), dirname(path))));
    } else {
      configs.push(...(await chain(parent, directory)));
    }
  }
  return configs;
}

function pluginName(plugin: JsPlugin): string {
  if (typeof plugin !== "string") return plugin.name;
  const scoped = /^(@[^/]+)\/(?:eslint-plugin(?:-(.+))?)$/u.exec(plugin);
  if (scoped !== null) return scoped[2] === undefined ? (scoped[1] ?? plugin) : `${scoped[1]}/${scoped[2]}`;
  return plugin.replace(/^eslint-plugin-/u, "");
}

function canonical(rule: string, aliases: Record<string, string>): string {
  const slash = rule.lastIndexOf("/");
  if (slash === -1) return rule;
  const namespace = rule.slice(0, slash);
  const target = aliases[namespace] ?? namespace;
  return target === "" ? rule.slice(slash + 1) : `${target}/${rule.slice(slash + 1)}`;
}

function namespaceOf(rule: string): string | null {
  const slash = rule.lastIndexOf("/");
  return slash === -1 ? null : rule.slice(0, slash);
}

export async function createSelectedConfig(request: SelectedRequest): Promise<Config> {
  const base = request.config === null ? {} : await loadConfig(request.config);
  const configs = await chain(base, request.config === null ? process.cwd() : dirname(request.config));
  const configured = new Set<string>();
  for (const config of configs) {
    for (const rule of Object.keys(config.rules ?? {})) configured.add(rule);
    for (const override of config.overrides ?? []) {
      for (const rule of Object.keys(override.rules ?? {})) configured.add(rule);
    }
  }
  const forced = new Set(Object.keys(request.forced).map((rule) => canonical(rule, request.aliases)));
  const final: Rules = {};
  const topLevel: Record<string, unknown> = {};
  if (request.rules !== null) {
    const selected = new Set(request.rules);
    for (const rule of configured) {
      const id = canonical(rule, request.aliases);
      if (!selected.has(id) && !forced.has(id)) final[rule] = "off";
    }
    // Oxlint enables `correctness` when a config names no categories.
    const categories = new Set(["correctness"]);
    for (const config of configs) for (const name of Object.keys(config.categories ?? {})) categories.add(name);
    topLevel["categories"] = Object.fromEntries([...categories].map((name) => [name, "off"]));
    // A partial run cannot prove that a directive for an unselected rule is unused.
    topLevel["options"] = { ...base.options, reportUnusedDisableDirectives: "off" };
  }
  Object.assign(final, request.forced);

  const nativePlugins = new Set(configs.flatMap((config) => config.plugins ?? []));
  const declaredPlugins = configs.some((config) => config.plugins !== undefined);
  const jsPlugins = new Set(
    configs.flatMap((config) => [
      ...(config.jsPlugins ?? []),
      ...(config.overrides ?? []).flatMap((override) => override.jsPlugins ?? []),
    ]).map(pluginName),
  );
  const missingJs: JsPlugin[] = [];
  const missingNative: string[] = [];
  // Configured rules already have their plugins; only forced rules may not.
  for (const rule of Object.keys(request.forced)) {
    const namespace = namespaceOf(canonical(rule, request.aliases));
    if (namespace === null) continue;
    const specifier = request.jsPlugins[namespace];
    if (specifier !== undefined) {
      if (!jsPlugins.has(namespace)) {
        jsPlugins.add(namespace);
        missingJs.push({ name: namespace, specifier });
      }
    } else if (!(declaredPlugins ? nativePlugins : new Set(DEFAULT_PLUGINS)).has(namespace)) {
      nativePlugins.add(namespace);
      missingNative.push(namespace);
    }
  }
  if (missingNative.length > 0) {
    topLevel["plugins"] = [...new Set([...(declaredPlugins ? [] : DEFAULT_PLUGINS), ...nativePlugins])];
  }
  if (missingJs.length > 0) topLevel["jsPlugins"] = [...(base.jsPlugins ?? []), ...missingJs];

  const disabled = request.disabled.map(({ files, rules }) => ({
    files: [...files],
    rules: Object.fromEntries(rules.map((rule) => [rule, "off"])),
  }));
  // Type-aware @sarj rules are always on in Standards runs; `sarj.typeAware: false` is an editor
  // opt-out. Oxlint reads `settings` from the root config only.
  const sarj = base.settings?.["sarj"];
  return {
    ...base,
    ...topLevel,
    settings: { ...base.settings, sarj: { ...(isConfig(sarj) ? sarj : {}), typeAware: true } },
    overrides: [
      ...(base.overrides ?? []),
      ...disabled,
      ...(Object.keys(final).length === 0 ? [] : [{ files: EVERY_FILE, rules: final }]),
    ],
  };
}
