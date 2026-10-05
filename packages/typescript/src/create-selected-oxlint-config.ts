import { readFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, extname, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";

import { parse, type ParseError } from "jsonc-parser";
import {
  type DummyRuleMap,
  type ExternalPluginsConfig,
  type OxlintConfig,
} from "oxlint";

/** Compose a native configuration for a focused check; Oxlint validates its schema. */
export async function createSelectedOxlintConfig(
  configurationPath: string,
  ruleIds: readonly string[],
): Promise<OxlintConfig> {
  const selected = new Set(ruleIds.flatMap(ruleAliases));
  const active = new Set<string>();
  const loading = new Set<string>();
  const declared = new Set<string>();

  function selectRules(rules: OxlintConfig["rules"]): DummyRuleMap {
    return Object.fromEntries(
      Object.entries(rules ?? {}).map(([id, setting]) => {
        if (selected.has(id)) {
          active.add(id);
          return [id, setting];
        }
        return [id, "off"];
      }),
    );
  }

  function resolvePlugins(
    entries: ExternalPluginsConfig,
    file: string,
  ): ExternalPluginsConfig {
    return entries.map((plugin) => {
      const specifier = typeof plugin === "string" ? plugin : plugin.specifier;
      const resolved = specifier.startsWith(".")
        ? resolve(dirname(file), specifier)
        : specifier;
      return typeof plugin === "string"
        ? resolved
        : { ...plugin, specifier: resolved };
    });
  }

  async function load(file: string): Promise<OxlintConfig> {
    if (loading.has(file))
      throw new Error(`Circular Oxlint configuration: ${file}`);
    loading.add(file);
    try {
      let value: unknown;
      if ([".json", ".jsonc"].includes(extname(file))) {
        const errors: ParseError[] = [];
        value = parse(await readFile(file, "utf8"), errors, {
          allowTrailingComma: true,
        });
        if (errors.length > 0)
          throw new Error(`Invalid JSON configuration: ${file}`);
      } else {
        const imported: { default?: unknown } = await import(
          pathToFileURL(file).href
        );
        value = imported.default;
      }
      return await select(
        value,
        file,
        [".json", ".jsonc"].includes(extname(file)),
      );
    } finally {
      loading.delete(file);
    }
  }

  async function select(
    value: unknown,
    file: string,
    json = false,
  ): Promise<OxlintConfig> {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new TypeError(
        `Expected a native Oxlint configuration object: ${file}`,
      );
    }
    // The official CLI remains the schema validator for imported native configurations.
    const config = value as OxlintConfig;
    for (const id of Object.keys(config.rules ?? {})) {
      for (const alias of ruleAliases(id)) declared.add(alias);
    }
    const result: OxlintConfig = {
      ...config,
      categories: {
        correctness: "off",
        suspicious: "off",
        pedantic: "off",
        perf: "off",
        style: "off",
        restriction: "off",
        nursery: "off",
      },
      rules: selectRules(config.rules),
      extends: await Promise.all(
        (config.extends ?? []).map((parent: unknown) =>
          json && typeof parent === "string"
            ? load(resolve(dirname(file), parent))
            : select(parent, file),
        ),
      ),
      overrides: (config.overrides ?? []).map((override) => {
        const selectedOverride = {
          ...override,
          rules: selectRules(override.rules),
        };
        if (override.jsPlugins)
          selectedOverride.jsPlugins = resolvePlugins(override.jsPlugins, file);
        return selectedOverride;
      }),
      ignorePatterns: [
        ...(config.ignorePatterns ?? []),
        ".sarj-oxlint-selected-*.mjs",
      ],
    };
    if (config.jsPlugins)
      result.jsPlugins = resolvePlugins(config.jsPlugins, file);
    return result;
  }

  const result = await load(resolve(configurationPath));
  // Stock Oxlint expands default and category-enabled native rules. Keep the
  // authored declarations because --print-config omits some JavaScript rules.
  const require = createRequire(resolve("package.json"));
  const binary = resolve(
    dirname(require.resolve("oxlint/package.json")),
    "bin/oxlint",
  );
  const { stdout } = await promisify(execFile)(
    process.execPath,
    [binary, "--config", resolve(configurationPath), "--print-config"],
    { encoding: "utf8", timeout: 30_000, maxBuffer: 16 * 1024 * 1024 },
  );
  const expanded: unknown = JSON.parse(stdout);
  if (!isExpandedConfig(expanded))
    throw new TypeError("Oxlint returned an invalid expanded configuration");
  // Expanded severities must not override options inherited from authored parents.
  const implicitRules = Object.fromEntries(
    Object.entries(expanded.rules ?? {}).filter(([id]) => !declared.has(id)),
  );
  result.rules = { ...selectRules(implicitRules), ...result.rules };
  for (const rule of ruleIds) {
    if (!ruleAliases(rule).some((id) => active.has(id))) {
      throw new Error(
        `Selected rule is absent from the native configuration: ${rule}`,
      );
    }
  }
  return result;
}

function ruleAliases(rule: string): readonly string[] {
  if (rule.startsWith("eslint/")) return [rule, rule.slice("eslint/".length)];
  return rule.includes("/")
    ? [rule]
    : [rule, `eslint/${rule}`, `@sarj/${rule}`];
}

function isExpandedConfig(value: unknown): value is OxlintConfig {
  if (typeof value !== "object" || value === null || !("rules" in value))
    return false;
  return (
    typeof value.rules === "object" &&
    value.rules !== null &&
    !Array.isArray(value.rules)
  );
}
