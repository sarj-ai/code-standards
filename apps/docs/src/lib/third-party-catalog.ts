import rawThirdPartyCatalog from "../generated/third-party-rules.v1.json";

export const THIRD_PARTY_PROFILES = ["application", "standard"] as const;
export const THIRD_PARTY_PAGE_SIZE = 50;
export type ThirdPartyProfile = (typeof THIRD_PARTY_PROFILES)[number];
export type ThirdPartyLevel = "error" | "warning";
export type ThirdPartyAutofix = "always" | "available" | "none" | "sometimes";

export interface ThirdPartyProvider {
  id: string;
  label: string;
  engine: string;
  package: string;
  version: string;
  homepage: string;
}

export interface ThirdPartyContext {
  id: string;
  label: string;
  level: ThirdPartyLevel;
}

export interface ThirdPartyRuleProfile {
  name: ThirdPartyProfile;
  contexts: ThirdPartyContext[];
}

export interface ThirdPartyRule {
  key: string;
  provider: string;
  id: string;
  displayId: string;
  summary: string;
  docsUrl: string;
  family: string | null;
  autofix: ThirdPartyAutofix;
  hasSuggestions: boolean;
  profiles: ThirdPartyRuleProfile[];
}

export interface ThirdPartyCatalog {
  schemaVersion: 1;
  profiles: ThirdPartyProfile[];
  providers: ThirdPartyProvider[];
  rules: ThirdPartyRule[];
}

// eslint-disable-next-line @sarj/stepdown -- validators read in dependency order from primitive shape to catalog root.
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(
  value: unknown,
  context: string,
): Record<string, unknown> {
  if (!isRecord(value)) throw new TypeError(`${context} must be an object.`);
  return value;
}

function requireExactFields(
  record: Record<string, unknown>,
  fields: string[],
  context: string,
): void {
  const actual = Object.keys(record).sort();
  const expected = [...fields].sort();
  if (
    actual.length !== expected.length ||
    actual.some((field, index) => field !== expected[index])
  ) {
    throw new TypeError(
      `${context} must contain exactly: ${expected.join(", ")}.`,
    );
  }
}

function requireString(
  record: Record<string, unknown>,
  field: string,
  context: string,
): string {
  const value = record[field];
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${context}.${field} must be a non-empty string.`);
  }
  return value;
}

function requireHttps(
  record: Record<string, unknown>,
  field: string,
  context: string,
): string {
  const value = requireString(record, field, context);
  if (!value.startsWith("https://"))
    throw new TypeError(`${context}.${field} must be an HTTPS URL.`);
  return value;
}

function requireArray(
  record: Record<string, unknown>,
  field: string,
  context: string,
): unknown[] {
  const value = record[field];
  if (!Array.isArray(value))
    throw new TypeError(`${context}.${field} must be an array.`);
  return value;
}

function parseProvider(value: unknown, index: number): ThirdPartyProvider {
  const context = `third-party catalog providers[${String(index)}]`;
  const record = requireRecord(value, context);
  requireExactFields(
    record,
    ["engine", "homepage", "id", "label", "package", "version"],
    context,
  );
  const id = requireString(record, "id", context);
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(id)) {
    throw new TypeError(`${context}.id must be a URL-safe provider slug.`);
  }
  return {
    id,
    label: requireString(record, "label", context),
    engine: requireString(record, "engine", context),
    package: requireString(record, "package", context),
    version: requireString(record, "version", context),
    homepage: requireHttps(record, "homepage", context),
  };
}

function parseContext(value: unknown, context: string): ThirdPartyContext {
  const record = requireRecord(value, context);
  requireExactFields(record, ["id", "label", "level"], context);
  const level = requireString(record, "level", context);
  if (level !== "error" && level !== "warning")
    throw new TypeError(`${context}.level is invalid.`);
  return {
    id: requireString(record, "id", context),
    label: requireString(record, "label", context),
    level,
  };
}

function parseProfile(value: unknown, context: string): ThirdPartyRuleProfile {
  const record = requireRecord(value, context);
  requireExactFields(record, ["contexts", "name"], context);
  const name = requireString(record, "name", context);
  if (!THIRD_PARTY_PROFILES.includes(name as ThirdPartyProfile)) {
    throw new TypeError(`${context}.name is unsupported.`);
  }
  const contexts = requireArray(record, "contexts", context).map(
    (item, index) =>
      parseContext(item, `${context}.contexts[${String(index)}]`),
  );
  const contextIds = contexts.map((item) => item.id);
  if (contextIds.length !== new Set(contextIds).size)
    throw new TypeError(`${context} has duplicate contexts.`);
  return { name: name as ThirdPartyProfile, contexts };
}

function parseRule(value: unknown, index: number): ThirdPartyRule {
  const context = `third-party catalog rules[${String(index)}]`;
  const record = requireRecord(value, context);
  requireExactFields(
    record,
    [
      "autofix",
      "displayId",
      "docsUrl",
      "family",
      "hasSuggestions",
      "id",
      "key",
      "profiles",
      "provider",
      "summary",
    ],
    context,
  );
  const autofix = requireString(record, "autofix", context);
  if (!["always", "available", "none", "sometimes"].includes(autofix)) {
    throw new TypeError(`${context}.autofix is invalid.`);
  }
  if (typeof record.hasSuggestions !== "boolean") {
    throw new TypeError(`${context}.hasSuggestions must be a boolean.`);
  }
  if (
    record.family !== null &&
    (typeof record.family !== "string" || record.family.length === 0)
  ) {
    throw new TypeError(
      `${context}.family must be a non-empty string or null.`,
    );
  }
  const family = record.family;
  const profiles = requireArray(record, "profiles", context).map(
    (item, profileIndex) =>
      parseProfile(item, `${context}.profiles[${String(profileIndex)}]`),
  );
  const profileNames = profiles.map((profile) => profile.name);
  if (profileNames.length !== new Set(profileNames).size)
    throw new TypeError(`${context} has duplicate profiles.`);
  return {
    key: requireString(record, "key", context),
    provider: requireString(record, "provider", context),
    id: requireString(record, "id", context),
    displayId: requireString(record, "displayId", context),
    summary: requireString(record, "summary", context),
    docsUrl: requireHttps(record, "docsUrl", context),
    family,
    autofix: autofix as ThirdPartyAutofix,
    hasSuggestions: record.hasSuggestions,
    profiles,
  };
}

function parseCatalog(value: unknown): ThirdPartyCatalog {
  const record = requireRecord(value, "third-party catalog");
  requireExactFields(
    record,
    ["profiles", "providers", "rules", "schemaVersion"],
    "third-party catalog",
  );
  if (record.schemaVersion !== 1)
    throw new TypeError("third-party catalog schemaVersion must be 1.");
  const profiles = requireArray(record, "profiles", "third-party catalog");
  if (
    profiles.length !== THIRD_PARTY_PROFILES.length ||
    profiles.some((profile, index) => profile !== THIRD_PARTY_PROFILES[index])
  ) {
    throw new TypeError(
      "third-party catalog profiles must be application, standard in canonical order.",
    );
  }
  const providers = requireArray(
    record,
    "providers",
    "third-party catalog",
  ).map(parseProvider);
  const rules = requireArray(record, "rules", "third-party catalog").map(
    parseRule,
  );
  const providerIds = providers.map((provider) => provider.id);
  if (providerIds.length !== new Set(providerIds).size)
    throw new TypeError("third-party catalog has duplicate providers.");
  const knownProviders = new Set(providerIds);
  const providerRuleCounts = new Map(
    providerIds.map((providerId) => [providerId, 0]),
  );
  const ruleKeys = rules.map((rule) => rule.key);
  if (ruleKeys.length !== new Set(ruleKeys).size)
    throw new TypeError("third-party catalog has duplicate rule keys.");
  for (const rule of rules) {
    if (!knownProviders.has(rule.provider))
      throw new TypeError(
        `third-party rule ${rule.key} has an unknown provider.`,
      );
    if (rule.key !== `${rule.provider}:${rule.id}`)
      throw new TypeError(
        `third-party rule ${rule.key} does not match its provider and ID.`,
      );
    providerRuleCounts.set(
      rule.provider,
      (providerRuleCounts.get(rule.provider) ?? 0) + 1,
    );
    if (rule.profiles.every((profile) => profile.contexts.length === 0)) {
      throw new TypeError(
        `third-party rule ${rule.key} is not enabled in any context.`,
      );
    }
  }
  for (const [providerId, ruleCount] of providerRuleCounts) {
    if (ruleCount === 0)
      throw new TypeError(
        `third-party provider ${providerId} has no enabled rules.`,
      );
  }
  return {
    schemaVersion: 1,
    profiles: [...THIRD_PARTY_PROFILES],
    providers,
    rules,
  };
}

export const thirdPartyCatalog = parseCatalog(rawThirdPartyCatalog);

export function thirdPartyRulesForProvider(
  providerId: string,
): ThirdPartyRule[] {
  return thirdPartyCatalog.rules.filter((rule) => rule.provider === providerId);
}

export function thirdPartyProviderHref(
  provider: Pick<ThirdPartyProvider, "id">,
): string {
  return `/third-party-linters/${provider.id}/`;
}

export function thirdPartyProviderPageHref(
  provider: Pick<ThirdPartyProvider, "id">,
  page: number,
): string {
  return page <= 1
    ? thirdPartyProviderHref(provider)
    : `${thirdPartyProviderHref(provider)}${String(page)}/`;
}

export function thirdPartyProviderSearchIndexHref(
  provider: Pick<ThirdPartyProvider, "id">,
): string {
  return `${thirdPartyProviderHref(provider)}rules.json`;
}

export function thirdPartyRuleAnchor(
  rule: Pick<ThirdPartyRule, "id" | "provider">,
): string {
  const encodedId = [...new TextEncoder().encode(`${rule.provider}:${rule.id}`)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `rule-${encodedId}`;
}

export function thirdPartyRuleHref(
  provider: Pick<ThirdPartyProvider, "id">,
  rule: Pick<ThirdPartyRule, "id" | "provider">,
): string {
  return `${thirdPartyProviderHref(provider)}#${thirdPartyRuleAnchor(rule)}`;
}

export function thirdPartyRulePolicySignature(
  rule: Pick<ThirdPartyRule, "profiles">,
): string {
  return JSON.stringify(rule.profiles);
}
