/** @fileoverview prefer-total-union-record — preserve finite key contracts at computed lookups. */

import type { Type } from "tsrs/sync";

import { defineRule, type ESTree } from "../types.js";
import { outerExpression, parentOf } from "../utils/ast.js";
import { nativeTypes, type NativeTypes, unionMembers } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { getPropertyName } from "../utils/static-string.js";
import { tsrsServices } from "../utils/tsrs-services.js";
import { closedRegistryMembers, hasUnknownContract } from "./no-known-value-widening.js";

const NAME = "prefer-total-union-record";
const MAX_KEYS = 64;

interface Registry {
  readonly annotation: ESTree.TSTypeAnnotation;
  readonly initializer: ESTree.ObjectExpression;
  readonly indices: readonly ESTree.Expression[];
  readonly staticKeys: ReadonlySet<string>;
}

function stringRecordAnnotation(node: ESTree.TSType): boolean {
  if (node.type === "TSTypeLiteral") return node.members.length === 1 && node.members[0]?.type === "TSIndexSignature";
  return node.type === "TSTypeReference" && node.typeName.type === "Identifier" && node.typeName.name === "Record" &&
    node.typeArguments?.params.length === 2 && node.typeArguments.params[0]?.type === "TSStringKeyword";
}

function registryLookups(reads: readonly ESTree.MemberExpression[]) {
  const staticKeys = new Set<string>();
  const indices: ESTree.Expression[] = [];
  for (const member of reads) {
    const expression = outerExpression(member);
    const use = parentOf(expression);
    if (member.optional || use?.type === "CallExpression" && use.callee === expression ||
      use?.type === "TaggedTemplateExpression" && use.tag === expression) return undefined;
    const key = getPropertyName(member);
    if (key !== null) {
      staticKeys.add(key);
    } else if (member.computed) {
      indices.push(member.property);
    } else {
      return undefined;
    }
  }
  return indices.length > 0 ? { staticKeys, indices } : undefined;
}

function registryAdvice({ annotation, initializer, indices, staticKeys }: Registry, native: NativeTypes) {
  const { checker, file, sync } = native;
  const declared = annotation.typeAnnotation;
  if (declared.type === "TSTypeReference" && !file.isDefaultLibrarySymbol(file.symbolsOf([declared.typeName])[0])) return undefined;
  const nodes = [declared, ...indices].map((node) => native.outerNode(node));
  if (!nodes.every((node) => node !== undefined)) return undefined;
  const [target, ...keyTypes] = checker.getTypeAtLocation(nodes);
  if (target === undefined || keyTypes.length !== indices.length) return undefined;
  const [index, extraIndex] = checker.getIndexInfosOfType(target);
  if (index?.keyType.flags !== sync.TypeFlags.String || extraIndex !== undefined || hasUnknownContract(index.valueType, native)) return undefined;

  const keys = finiteKeyUnion(keyTypes, sync.TypeFlags.Null | sync.TypeFlags.Undefined);
  if (keys === undefined) return undefined;
  const allKeys = new Set([...keys, ...staticKeys]);
  if (allKeys.size > MAX_KEYS) return undefined;
  const present = new Set(initializer.properties.map(getPropertyName));
  if (present.has("__proto__")) return undefined;
  const [first] = keyTypes;
  const alias = first !== undefined && allKeys.size === keys.size && keyTypes.every((type) => type.id === first.id) &&
      unionMembers(first).every((part) => part.isStringLiteralType())
    ? first.getAliasSymbol()?.name : undefined;
  const missing = [...allKeys].filter((key) => !present.has(key)).sort();
  return {
    domain: alias ?? "the finite key union",
    missing: missing.length > 0 ? ` Add entries for ${missing.map((key) => JSON.stringify(key)).join(", ")}.` : "",
  };
}

function finiteKeyUnion(keyTypes: readonly Type[], nullishFlags: number): Set<string> | undefined {
  const keys = new Set<string>();
  for (const type of keyTypes) {
    const parts = unionMembers(type).filter((part) => (part.flags & nullishFlags) === 0);
    if (parts.length === 0 || parts.length > MAX_KEYS) return undefined;
    for (const part of parts) {
      if (!part.isStringLiteralType()) return undefined;
      keys.add(part.value);
    }
  }
  return keys.size >= 2 && keys.size <= MAX_KEYS ? keys : undefined;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Declare a total record for closed registries indexed by a finite string union.", url: docsUrl(NAME) },
    schema: [],
    messages: { total: "Declare a total record for {{domain}} so new keys require entries.{{missing}}" },
  },
  createOnce(context) {
    let registries: Registry[] = [];
    return {
      before() {
        registries = [];
        return !isGeneratedFile(context, context.sourceCode.text);
      },
      VariableDeclarator(node) {
        const declaration = parentOf(node);
        if (declaration?.type !== "VariableDeclaration" || declaration.kind !== "const" || parentOf(declaration)?.type !== "Program" ||
          node.id.type !== "Identifier" || node.init?.type !== "ObjectExpression") return;
        const annotation = node.id.typeAnnotation;
        if (!annotation || !stringRecordAnnotation(annotation.typeAnnotation)) return;
        const reads = closedRegistryMembers(node, context.sourceCode);
        if (reads === undefined) return;
        const lookups = registryLookups(reads);
        if (lookups !== undefined) registries.push({ annotation, initializer: node.init, ...lookups });
      },
      "Program:exit"() {
        if (registries.length === 0) return;
        const findings = tsrsServices(context)?.run((file) => {
          const native = nativeTypes(file);
          if (!native.ast.isExternalModule(native.source)) return [];
          return registries.flatMap((registry) => {
            const data = registryAdvice(registry, native);
            return data === undefined ? [] : [{ node: registry.annotation, messageId: "total", data }];
          });
        });
        for (const finding of findings ?? []) context.report(finding);
      },
    };
  },
});
