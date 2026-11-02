/** @fileoverview _eslint-rule — native TypeScript rule contexts and owned option metadata. */

import { ESLintUtils } from "@typescript-eslint/utils";
import type { JSONSchema, ParserServices, ParserServicesWithTypeInformation, TSESLint, TSESTree } from "@typescript-eslint/utils";
import type { JSRuleDefinition, Linter } from "eslint";
import type { RuleDefinition, RuleVisitor, RuleTextEdit, RuleTextEditor } from "@eslint/core";
export { hasSideEffect } from "./_has-side-effect.js";

export type NativeRuleFix = RuleTextEdit;
export type NativeRuleFixer = RuleTextEditor<TSESTree.Node | TSESTree.Token>;
export type NativeReportFix = (fixer: NativeRuleFixer) => NativeRuleFix | Iterable<NativeRuleFix> | null;

type NativeJavaScriptSource = Parameters<JSRuleDefinition["create"]>[0]["sourceCode"];
export type TypeScriptSourceCode = Pick<TSESLint.SourceCode,
  Exclude<Extract<keyof TSESLint.SourceCode, keyof NativeJavaScriptSource>, "visitorKeys">> &
  Pick<NativeJavaScriptSource, "visitorKeys"> &
  Pick<NativeJavaScriptSource, Exclude<keyof NativeJavaScriptSource, keyof TSESLint.SourceCode>>;
export type NativeRuleListener = {
  [Selector in keyof TSESLint.RuleListener as string extends Selector ? never
    : number extends Selector ? never : Selector]: TSESLint.RuleListener[Selector];
} & RuleVisitor;
type Definition<Options extends readonly unknown[], MessageIds extends string> = RuleDefinition<{
  LangOptions: Linter.LanguageOptions;
  ExtRuleDocs: Record<string, unknown>;
  RuleOptions: [...Options];
  MessageIds: MessageIds;
  Code: TypeScriptSourceCode;
  Node: TSESTree.Node | TSESTree.Token;
  Visitor: NativeRuleListener;
}>;
type EngineRuleContext<MessageIds extends string, Options extends readonly unknown[]> =
  Parameters<Definition<Options, MessageIds>["create"]>[0];
export type NativeRuleContext<MessageIds extends string, Options extends readonly unknown[]> =
  Omit<EngineRuleContext<MessageIds, Options>, "options"> & {
    // Host options may omit legacy defaults; the create callback's second
    // argument contains the complete normalized tuple.
    readonly options: Readonly<Partial<Options>>;
  };
export type NativeSuggestions<MessageIds extends string> = NonNullable<
  Parameters<NativeRuleContext<MessageIds, readonly unknown[]>["report"]>[0]["suggest"]>;
export type TypeServices = Pick<ParserServicesWithTypeInformation,
  "program" | "esTreeNodeToTSNodeMap" | "tsNodeToESTreeNodeMap">;

export function getTypeServices<MessageIds extends string, Options extends readonly unknown[]>(
  context: Pick<NativeRuleContext<MessageIds, Options>, "sourceCode" | "languageOptions">,
): TypeServices {
  const services = context.sourceCode.parserServices;
  if (hasTypeInformation(services)) return services;
  const parser = "parserPath" in context && typeof context.parserPath === "string" && context.parserPath
    ? context.parserPath : context.languageOptions.parser?.meta?.name;
  const messages = [
    "You have used a rule which requires type information, but don't have parserOptions set to generate type information for this file. See https://tseslint.com/typed-linting for enabling linting with type information.",
    `Parser: ${parser || "(unknown)"}`,
  ];
  if (!parser || !/(?:typescript-eslint|\.\.)[\w/\\]*parser/.test(parser)) {
    messages.push('Note: detected a parser other than @typescript-eslint/parser. Make sure the parser is configured to forward "parserOptions.project" to @typescript-eslint/parser.');
  }
  throw new Error(messages.join("\n"));
}

function hasTypeInformation(services: Partial<ParserServices> | undefined):
  services is Partial<ParserServices> & TypeServices {
  return services?.program != null && services.esTreeNodeToTSNodeMap != null &&
    services.tsNodeToESTreeNodeMap != null;
}

export type NativeRuleConfiguration<Options extends readonly unknown[], MessageIds extends string> =
  Omit<ESLintUtils.RuleWithMetaAndName<Options, MessageIds>, "create"> & {
    create(this: void, context: NativeRuleContext<MessageIds, Options>, options: Readonly<Options>): NativeRuleListener;
  } & (readonly [] extends Options ? unknown :
    { readonly defaultOptions: Readonly<Options> } |
    { readonly meta: { readonly defaultOptions: Readonly<Options> } });

type OwnedMetadata<Options extends readonly unknown[], MessageIds extends string> =
  Omit<ESLintUtils.RuleWithMetaAndName<Options, MessageIds>["meta"], "schema" | "defaultOptions" | "docs"> & {
    docs: ESLintUtils.RuleWithMetaAndName<Options, MessageIds>["meta"]["docs"] & { url: string };
    schema: JSONSchema.JSONSchema4 | JSONSchema.JSONSchema4[];
    defaultOptions?: [...Options];
  };

export interface NativeRule<Options extends readonly unknown[], MessageIds extends string> {
  name: string;
  defaultOptions: Readonly<Options> | undefined;
  meta: OwnedMetadata<Options, MessageIds>;
  create(context: EngineRuleContext<MessageIds, Options>): NativeRuleListener;
}

export function createNativeRule<Options extends readonly unknown[], MessageIds extends string>(
  config: NativeRuleConfiguration<Options, MessageIds>, url: (name: string) => string,
): NativeRule<Options, MessageIds> {
  const input = { ...config };
  const originalMeta = Object.hasOwn(input, "meta") ? input.meta : config.meta;
  const metadataSnapshot = { ...originalMeta };
  const declaredMetaDefaults = Object.hasOwn(metadataSnapshot, "defaultOptions")
    ? metadataSnapshot.defaultOptions : originalMeta.defaultOptions;
  const declaredLegacyDefaults = Object.hasOwn(input, "defaultOptions")
    ? input.defaultOptions : config.defaultOptions;
  const descriptor = {
    ...input,
    name: Object.hasOwn(input, "name") ? input.name : config.name,
    create: Object.hasOwn(input, "create") ? input.create : config.create,
    meta: metadataSnapshot,
  };
  if (declaredLegacyDefaults !== undefined) descriptor.defaultOptions = declaredLegacyDefaults;
  if (declaredMetaDefaults !== undefined) descriptor.meta.defaultOptions = declaredMetaDefaults;
  const { defaultOptions: metaDefaults, schema, ...metadata } = descriptor.meta;
  const metadataDefaults = metaDefaults === undefined ? undefined : ownTuple(metaDefaults);
  const legacyDefaults = metadataDefaults === undefined && descriptor.defaultOptions !== undefined
    ? ownTuple(descriptor.defaultOptions) : undefined;
  const ownedMetadata = { ...metadata, docs: { ...metadata.docs, url: url(descriptor.name) },
    schema: schemaList(schema) ? [...schema] : schema };
  if (metadataDefaults === undefined && Object.hasOwn(descriptor.meta, "defaultOptions")) {
    // Typed descriptors reject explicit undefined under exact optional checking.
    // Preserve existing JavaScript callers' property presence at runtime.
    Object.defineProperty(ownedMetadata, "defaultOptions", {
      value: undefined, configurable: true, enumerable: true, writable: true,
    });
  }
  const meta = metadataDefaults === undefined ? ownedMetadata : { ...ownedMetadata, defaultOptions: metadataDefaults };
  const base = {
    name: descriptor.name,
    defaultOptions: descriptor.defaultOptions,
    meta,
  };
  if (hasNoDefaultOptions(descriptor)) {
    const create = descriptor.create;
    return { ...base, create(context: EngineRuleContext<MessageIds, Options>) {
      return create(context, []);
    } };
  }
  const defaults = metadataDefaults ?? legacyDefaults;
  if (defaults === undefined) throw new TypeError("Declared defaults disappeared while creating the rule.");
  const create = descriptor.create;
  return { ...base, create(context: EngineRuleContext<MessageIds, Options>) {
    return create(context, ESLintUtils.applyDefault(defaults, context.options));
  } };
}

// Required tuple slots require declared defaults above. Their absence therefore
// proves that the author's Options admits the same empty fallback as RuleCreator.
function hasNoDefaultOptions<Options extends readonly unknown[], MessageIds extends string>(
  config: NativeRuleConfiguration<Options, MessageIds>,
): config is NativeRuleConfiguration<Options, MessageIds> & {
  create(this: void, context: NativeRuleContext<MessageIds, Options>, options: readonly []): NativeRuleListener;
} {
  return config.meta.defaultOptions === undefined && config.defaultOptions === undefined;
}

function schemaList(schema: JSONSchema.JSONSchema4 | readonly JSONSchema.JSONSchema4[]): schema is readonly JSONSchema.JSONSchema4[] {
  return Array.isArray(schema);
}

function ownTuple<Options extends readonly unknown[]>(options: Options): [...Options] {
  return [...options];
}
