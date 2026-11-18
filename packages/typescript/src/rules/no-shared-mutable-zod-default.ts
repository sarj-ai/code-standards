/**
 * @fileoverview no-shared-mutable-zod-default — Return a fresh mutable value from each Zod default factory.
 */

import { defineRule, tsReference, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { nativeRuntimeUnchanged } from "../utils/native-runtime-unchanged.js";
import { isGeneratedFile } from "../utils/paths.js";
import { stableConstInitializer, enclosingFunction, stableValueBinding, typeOnlyReference, writtenMember } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";
import { hasIdentifierNamed } from "../utils/unused-private-binding.js";

const NAME = "no-shared-mutable-zod-default";
const FACTORIES: ReadonlySet<string> = new Set(["array", "object", "strictObject", "looseObject", "record", "tuple", "map", "set", "date", "string", "number", "boolean", "bigint", "literal", "enum", "union", "discriminatedUnion", "intersection", "custom", "any", "unknown"]);
const CHAINS: ReadonlySet<string> = new Set(["optional", "nullable", "nullish", "default", "prefault", "catch", "refine", "superRefine", "transform", "pipe", "describe", "brand", "readonly", "strict", "loose", "passthrough", "strip", "partial", "required", "extend", "safeExtend", "pick", "omit", "merge", "array", "nonempty", "min", "max", "length", "check"]);
type Factory = ESTree.ArrowFunctionExpression | ESTree.Function;
const SCHEMA_READS = new WeakMap<ESTree.Program, WeakMap<TsVariable, boolean>>();
const SCHEMA_METHODS: ReadonlySet<string> = new Set([...CHAINS, "parse", "safeParse", "parseAsync", "safeParseAsync", "spa", "isOptional", "isNullable"]);
interface CaptureUse { readonly frozen: boolean; readonly returnedFrom: Factory | undefined; }
const CAPTURE_USES = new WeakMap<ESTree.Program, WeakMap<TsVariable, CaptureUse | null>>();

function zodImport(node: Node, source: SourceCode, major: 4 | undefined): string | null {
  if (node.type !== "Identifier") return null;
  const binding = findVariable(source.getScope(node), node.name);
  const definition = binding?.defs[0]?.node;
  const declaration = definition === undefined ? null : parentOf(definition);
  if (binding === null || binding.defs.length !== 1 ||
    declaration?.type !== "ImportDeclaration" || declaration.importKind === "type" || !isZodModule(declaration.source.value) || /^zod\/v3(?:$|[-/])/.test(declaration.source.value) ||
    major !== 4 && !/^zod\/v4(?:$|[-/])/.test(declaration.source.value) || !stableValueBinding(binding)) return null;
  if (definition?.type === "ImportNamespaceSpecifier" || definition?.type === "ImportDefaultSpecifier") return "z";
  return definition?.type === "ImportSpecifier" && definition.importKind !== "type" ? importSpecifierName(definition) : null;
}

function schema(input: Node, source: SourceCode, major: 4 | undefined, depth = 0): boolean {
  if (depth >= 16) return false;
  const node = unwrapExpression(input);
  if (node.type === "Identifier") {
    const initializer = stableConstInitializer(source, node);
    return initializer !== null && schemaReads(initializer.variable, source) && schema(initializer.value, source, major, depth + 1);
  }
  if (node.type !== "CallExpression" || node.optional) return false;
  const callee = unwrapExpression(node.callee);
  if (callee.type === "Identifier") return FACTORIES.has(zodImport(callee, source, major) ?? "");
  if (callee.type !== "MemberExpression" || callee.optional) return false;
  const method = getPropertyName(callee);
  if (method === null) return false;
  if (zodImport(callee.object, source, major) === "z") return FACTORIES.has(method);
  return CHAINS.has(method) && schema(callee.object, source, major, depth + 1);
}

function factory(input: Node): Factory | null {
  const node = unwrapExpression(input);
  if (node.type !== "ArrowFunctionExpression" && node.type !== "FunctionExpression") return null;
  return !node.async && !("generator" in node && node.generator) && node.params.length === 0 ? node : null;
}

function capturedMutable(input: Node, owner: Factory, source: SourceCode, depth = 0): Node | null {
  if (depth >= 12) return null;
  const node = unwrapExpression(input);
  if (node.type !== "Identifier") return null;
  const initializer = stableConstInitializer(source, node);
  if (initializer === null) return null;
  const value = unwrapExpression(initializer.value);
  if (value.type === "Identifier") return capturedMutable(value, owner, source, depth + 1);
  if (initializer.declaration.range[0] >= owner.range[0] && initializer.declaration.range[1] <= owner.range[1]) return null;
  const uses = captureUse(initializer.variable, source);
  if (uses === null || uses.returnedFrom !== owner || uses.frozen && (!mutableAfterShallowFreeze(value) || !nativeRuntimeUnchanged(source, "Object"))) return null;
  if (value.type === "ArrayExpression" || value.type === "ObjectExpression") return value;
  if (value.type !== "NewExpression" || value.callee.type !== "Identifier") return null;
  const name = value.callee.name;
  return (name === "Map" || name === "Set" || name === "Date") &&
    !findVariable(source.getScope(value.callee), name)?.defs.length && nativeRuntimeUnchanged(source, name) ? value : null;
}

/** A visible schema escape or method replacement invalidates its original factory contract. */
function schemaReads(binding: TsVariable, source: SourceCode, depth = 0): boolean {
  if (depth >= 12) return false;
  let bindings = SCHEMA_READS.get(source.ast);
  if (bindings === undefined) {
    bindings = new WeakMap();
    SCHEMA_READS.set(source.ast, bindings);
  }
  const known = bindings.get(binding);
  if (known !== undefined) return known;
  bindings.set(binding, false);
  const safe = binding.references.every(reference => {
    if (!reference.isRead() || typeOnlyReference(reference)) return true;
    const value = outerExpression(reference.identifier);
    const parent = parentOf(value);
    if (parent?.type === "VariableDeclarator" && parent.init === value && parent.id.type === "Identifier") {
      const alias = findVariable(source.getScope(parent.id), parent.id.name);
      const declaration = parentOf(parent);
      return alias !== null && declaration?.type === "VariableDeclaration" && declaration.kind === "const" &&
        stableValueBinding(alias) && schemaReads(alias, source, depth + 1);
    }
    if (parent?.type !== "MemberExpression" || parent.object !== value || parent.optional || writtenMember(parent) ||
      !SCHEMA_METHODS.has(getPropertyName(parent) ?? "")) return false;
    const callee = outerExpression(parent);
    const call = parentOf(callee);
    return call?.type === "CallExpression" && !call.optional && call.callee === callee;
  });
  bindings.set(binding, safe);
  return safe;
}

function scalar(input: Node | null): boolean {
  const node = input === null ? null : unwrapExpression(input);
  return node === null || node.type === "Literal" && !('regex' in node) &&
    (node.value === null || ["string", "number", "boolean", "bigint"].includes(typeof node.value));
}

/** Keep mutation, opaque escape and interprocedural freeze questions outside this local proof. */
function captureUse(binding: TsVariable, source: SourceCode, depth = 0): CaptureUse | null {
  if (depth >= 12) return null;
  let uses = CAPTURE_USES.get(source.ast);
  if (uses === undefined) {
    uses = new WeakMap();
    CAPTURE_USES.set(source.ast, uses);
  }
  if (uses.has(binding)) return uses.get(binding) ?? null;
  uses.set(binding, null);
  let frozen = false;
  let returnedFrom: Factory | undefined;
  for (const reference of binding.references) {
    if (!reference.isRead() || typeOnlyReference(reference)) continue;
    const read = captureRead(outerExpression(reference.identifier), source, depth);
    if (read === null) return null;
    frozen ||= read.frozen;
    if (read.returnedFrom !== undefined) {
      if (returnedFrom !== undefined && returnedFrom !== read.returnedFrom) return null;
      returnedFrom = read.returnedFrom;
    }
  }
  const result = { frozen, returnedFrom };
  uses.set(binding, result);
  return result;
}

function captureRead(value: Node, source: SourceCode, depth: number): CaptureUse | null {
  const parent = parentOf(value);
  const owner = enclosingFunction(value);
  if (owner !== null && (parent?.type === "ReturnStatement" && parent.argument === value || owner.type === "ArrowFunctionExpression" && owner.body === value))
    return { frozen: false, returnedFrom: owner };
  if (parent?.type === "VariableDeclarator" && parent.init === value && parent.id.type === "Identifier") {
    const alias = findVariable(source.getScope(parent.id), parent.id.name);
    const declaration = parentOf(parent);
    return alias !== null && declaration?.type === "VariableDeclaration" && declaration.kind === "const" && stableValueBinding(alias)
      ? captureUse(alias, source, depth + 1) : null;
  }
  if (parent?.type === "CallExpression" && !parent.optional && parent.arguments.length === 1 && parent.arguments[0] === value &&
    parent.callee.type === "MemberExpression" && !parent.callee.optional && getPropertyName(parent.callee) === "freeze" &&
    parent.callee.object.type === "Identifier" && parent.callee.object.name === "Object" && !findVariable(source.getScope(parent.callee.object), "Object")?.defs.length)
    return { frozen: true, returnedFrom: undefined };
  return null;
}

function namespaceStable(source: SourceCode, major: 4 | undefined): boolean {
  return source.scopeManager.scopes.every(scope => scope.references.every(reference => {
    if (typeOnlyReference(tsReference(reference))) return true;
    const node = reference.identifier;
    const imported = zodImport(node, source, major);
    if (imported === null) return true;
    const value = outerExpression(node);
    const member = parentOf(value);
    const callee = imported === "z" && member?.type === "MemberExpression" && member.object === value &&
      !member.optional && !writtenMember(member) && FACTORIES.has(getPropertyName(member) ?? "")
      ? outerExpression(member) : value;
    const call = parentOf(callee);
    return call?.type === "CallExpression" && !call.optional && call.callee === callee;
  }));
}

/** A frozen container is only a leak when a reachable mutable child is positively established. */
function mutableAfterShallowFreeze(value: Node): boolean {
  if (value.type === "NewExpression") return true;
  if (value.type === "ArrayExpression") return value.elements.every(child =>
    child === null || scalar(child) || child.type === "ArrayExpression" || child.type === "ObjectExpression") &&
    value.elements.some(child => child?.type === "ArrayExpression" || child?.type === "ObjectExpression");
  if (value.type !== "ObjectExpression") return false;
  const keys = new Set<string>();
  let nested = false;
  for (const property of value.properties) {
    if (property.type !== "Property" || property.kind !== "init" || property.method || property.computed) return false;
    const name = property.key.type === "Identifier" ? property.key.name : property.key.type === "Literal" ? String(property.key.value) : null;
    if (name === null || keys.has(name)) return false;
    keys.add(name);
    const child = unwrapExpression(property.value);
    if (child.type === "ArrayExpression" || child.type === "ObjectExpression") nested = true;
    else if (!scalar(child)) return false;
  }
  return nested;
}

/** Outer parsing can replace the default; readonly only protects flat primitive containers. */
function processedDefault(node: ESTree.CallExpression, value: Node, source: SourceCode): boolean {
  let current: Node = outerExpression(node);
  for (let parent = parentOf(current); parent?.type === "MemberExpression" && parent.object === current; parent = parentOf(current)) {
    const method = getPropertyName(parent);
    const callee = outerExpression(parent);
    const call = parentOf(callee);
    if (parent.optional || call?.type !== "CallExpression" || call.optional || call.callee !== callee) return true;
    if (method === "readonly") {
      if (!mutableAfterShallowFreeze(value) || !nativeRuntimeUnchanged(source, "Object")) return true;
    } else if (method !== "describe" && method !== "brand") return true;
    current = outerExpression(call);
  }
  return false;
}

export default defineRule({
  meta: {
    type: "problem",
    docs: { description: 'Return a fresh mutable value from each Zod default factory.', url: docsUrl(NAME) },
    defaultOptions: [{}],
    schema: [{
      type: "object", additionalProperties: false,
      properties: { zodMajorVersion: { description: "Installed Zod major version whose factory defaults preserve returned identity.", type: "integer", minimum: 4, maximum: 4 } },
    }],
    messages: { noSharedMutableZodDefault: 'Return a fresh mutable value from each Zod default factory.' },
  },
  createOnce(context) {
    let major: 4 | undefined;
    return {
      before() {
        const [options] = context.options as unknown as readonly [{ zodMajorVersion?: 4 }?];
        major = options?.zodMajorVersion;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text) ||
          hasIdentifierNamed(context.sourceCode, "eval") || hasIdentifierNamed(context.sourceCode, "Function") ||
          !context.sourceCode.ast.body.some(statement => statement.type === "ImportDeclaration" && isZodModule(statement.source.value)) ||
          !namespaceStable(context.sourceCode, major)) return false;
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression) {
        if (node.optional || node.arguments.length !== 1 || node.callee.type !== "MemberExpression" ||
          node.callee.optional || getPropertyName(node.callee) !== "default" || !schema(node.callee.object, context.sourceCode, major)) return;
        const argument = node.arguments[0];
        const owner = argument === undefined ? null : factory(argument);
        if (owner === null || owner.body === null) return;
        const returned = owner.body.type === "BlockStatement"
          ? owner.body.body.length === 1 && owner.body.body[0]?.type === "ReturnStatement" ? owner.body.body[0].argument : null
          : owner.body;
        const value = returned === null ? null : capturedMutable(returned, owner, context.sourceCode);
        if (value !== null && !processedDefault(node, value, context.sourceCode))
          context.report({ node: argument!, messageId: "noSharedMutableZodDefault" });
      },
    };
  },
});
