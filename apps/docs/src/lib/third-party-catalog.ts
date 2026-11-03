import { z } from "zod";

import rawThirdPartyCatalog from "../generated/third-party-rules.v1.json" with { type: "json" };

import { siteHref } from "./site.ts";

export const THIRD_PARTY_PROFILES = ["application", "standard"] as const;
export const THIRD_PARTY_PAGE_SIZE = 32;
export type ThirdPartyProfile = (typeof THIRD_PARTY_PROFILES)[number];
export type ThirdPartyLevel = "error" | "warning";
export type ThirdPartyAutofix = "always" | "available" | "none" | "sometimes";
export type ThirdPartyProjectionScope =
  "complete" | "config-explicit" | "provider-only";

export interface ThirdPartyProvider {
  id: string;
  label: string;
  engine: string;
  package: string;
  version: string;
  homepage: string;
  projectionScope: ThirdPartyProjectionScope;
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

const TextSchema = z.string().min(1);
const HttpsSchema = TextSchema.startsWith("https://");
const CONTextSchema = z.strictObject({
  id: TextSchema,
  label: TextSchema,
  level: z.enum(["error", "warning"]),
});
const ProfileSchema = z.strictObject({
  name: z.enum(THIRD_PARTY_PROFILES),
  contexts: z.array(CONTextSchema),
});
const ProviderSchema = z.strictObject({
  id: TextSchema.regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/u),
  label: TextSchema,
  engine: TextSchema,
  package: TextSchema,
  version: TextSchema,
  homepage: HttpsSchema,
  projectionScope: z.enum(["complete", "config-explicit", "provider-only"]),
});
const RuleSchema = z.strictObject({
  key: TextSchema,
  provider: TextSchema,
  id: TextSchema,
  displayId: TextSchema,
  summary: TextSchema,
  docsUrl: HttpsSchema,
  family: TextSchema.nullable(),
  autofix: z.enum(["always", "available", "none", "sometimes"]),
  hasSuggestions: z.boolean(),
  profiles: z.array(ProfileSchema),
});
const CatalogSchema = z.strictObject({
  schemaVersion: z.literal(1),
  profiles: z.array(z.enum(THIRD_PARTY_PROFILES)),
  providers: z.array(ProviderSchema),
  rules: z.array(RuleSchema),
}) satisfies z.ZodType<ThirdPartyCatalog>;

export function parseCatalog(value: unknown): z.output<typeof CatalogSchema> {
  const result = CatalogSchema.safeParse(value);
  if (!result.success) {
    throw new TypeError("third-party catalog is invalid.", { cause: result.error });
  }
  const { profiles, providers, rules } = result.data;
  if (
    profiles.length !== THIRD_PARTY_PROFILES.length ||
    profiles.some((profile, index) => profile !== THIRD_PARTY_PROFILES[index])
  ) {
    throw new TypeError(
      "third-party catalog profiles must be application, standard in canonical order.",
    );
  }
  const providerIds = providers.map((provider) => provider.id);
  if (providerIds.length !== new Set(providerIds).size)
    throw new TypeError("third-party catalog has duplicate providers.");
  const knownProviders = new Set(providerIds);
  const providerRuleCounts = new Map(providerIds.map((providerId) => [providerId, 0]));
  const ruleKeys = rules.map((rule) => rule.key);
  if (ruleKeys.length !== new Set(ruleKeys).size)
    throw new TypeError("third-party catalog has duplicate rule keys.");
  for (const rule of rules) {
    if (!knownProviders.has(rule.provider))
      throw new TypeError(`third-party rule ${rule.key} has an unknown provider.`);
    if (rule.key !== `${rule.provider}:${rule.id}`)
      throw new TypeError(`third-party rule ${rule.key} does not match its provider and ID.`);
    validateRuleProfiles(rule);
    providerRuleCounts.set(rule.provider, (providerRuleCounts.get(rule.provider) ?? 0) + 1);
  }
  for (const [providerId, ruleCount] of providerRuleCounts) {
    const provider = providers.find(({ id }) => id === providerId);
    if (ruleCount === 0 && provider?.projectionScope !== "provider-only")
      throw new TypeError(`third-party provider ${providerId} has no enabled rules.`);
  }
  return result.data;
}

function validateRuleProfiles(rule: ThirdPartyRule): void {
  const names = rule.profiles.map((profile) => profile.name);
  if (names.length !== new Set(names).size)
    throw new TypeError(`third-party rule ${rule.key} has duplicate profiles.`);
  for (const profile of rule.profiles) {
    const ids = profile.contexts.map((context) => context.id);
    if (ids.length !== new Set(ids).size)
      throw new TypeError(`third-party rule ${rule.key} has duplicate contexts.`);
  }
  if (rule.profiles.every((profile) => profile.contexts.length === 0)) {
    throw new TypeError(`third-party rule ${rule.key} is not enabled in any context.`);
  }
}

export const thirdPartyCatalog = parseCatalog(rawThirdPartyCatalog);

export function thirdPartyRulesForProvider(
  providerId: string,
): ThirdPartyRule[] {
  return thirdPartyCatalog.rules
    .filter((rule) => rule.provider === providerId)
    .sort(
      (left, right) =>
        left.displayId.localeCompare(right.displayId, "en", {
          sensitivity: "base",
        }) || left.key.localeCompare(right.key, "en"),
    );
}

export function thirdPartyProvidersForNavigation(
  providers: readonly ThirdPartyProvider[] = thirdPartyCatalog.providers,
): ThirdPartyProvider[] {
  return [...providers].sort(
    (left, right) =>
      left.label.localeCompare(right.label, "en", { sensitivity: "base" }) ||
      left.id.localeCompare(right.id, "en"),
  );
}

export function thirdPartyProviderNavigationLabel(
  provider: ThirdPartyProvider,
): string {
  return provider.label;
}

export function thirdPartyProviderHref(
  provider: Pick<ThirdPartyProvider, "id">,
): string {
  return siteHref(`/third-party-linters/${provider.id}/`);
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
  page = 1,
): string {
  return `${thirdPartyProviderPageHref(provider, page)}#${thirdPartyRuleAnchor(rule)}`;
}

export function thirdPartyRulePolicySignature(
  rule: Pick<ThirdPartyRule, "profiles">,
): string {
  return JSON.stringify(rule.profiles);
}
