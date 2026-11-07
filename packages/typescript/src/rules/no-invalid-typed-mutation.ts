/**
 * @fileoverview no-invalid-typed-mutation — native mutation APIs must preserve declared property types.
 *
 * Port of the 18.x `no-invalid-typed-mutation` rule. Typed: the
 * original returns no visitors without a program. Types come from tsrs only;
 * when `tsrsServices` is null `before()` skips the file.
 *
 * The walk is the original's: it collects native mutation calls and the
 * namespaces the file replaces. `Program:exit` runs the untyped ownership
 * checks first and asks tsrs (`_incompatible-write.ts`) only for
 * the candidates that pass them.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName, staticString } from "../utils/static-string.js";
import type { TsrsFile, TsrsServices } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";
import { incompatibleWrite, type TypedWrite } from "./_incompatible-write.js";

const NAME = "no-invalid-typed-mutation";

type NativeNamespace = "Object" | "Reflect";
const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set(["globalThis", "window", "self"]);
const NAMESPACE_OR_RECEIVER: ReadonlySet<string> = new Set(["Object", "Reflect", ...GLOBAL_RECEIVERS]);
const SUPPORTED_METHODS: Readonly<Record<NativeNamespace, ReadonlySet<string>>> = {
  Object: new Set(["assign", "defineProperty", "defineProperties", "setPrototypeOf"]),
  Reflect: new Set(["set", "defineProperty", "setPrototypeOf"]),
};
const DATA_DESCRIPTOR_KEYS: ReadonlySet<string> = new Set(["value", "configurable", "enumerable", "writable"]);
type Identifier = Extract<Node, { type: "Identifier" }>;

interface Write {
  readonly key: string;
  readonly value: Node;
}

interface Mutation {
  readonly call: ESTree.CallExpression;
  readonly namespace: NativeNamespace;
  readonly method: string;
  readonly target: Identifier;
  readonly writes: readonly Write[];
}

/** A structural annotation alone cannot distinguish storage from a coercing setter or proxy. */
function localDataTarget(target: Identifier, sourceCode: SourceCode): ReadonlySet<string> | undefined {
  const binding = findVariable(sourceCode.getScope(target), target.name);
  if (binding === null) return undefined;
  const value = annotatedLocalObject(binding);
  if (value === undefined) return undefined;
  const properties = plainProperties(value);
  if (properties === undefined || !onlyOwnerUses(binding, value, sourceCode)) return undefined;
  return new Set(properties.map((property) => property.key));
}

/** The object literal of the binding's only declaration: an unexported, annotated `const`. */
function annotatedLocalObject(binding: TsVariable): ESTree.ObjectExpression | undefined {
  const definition = binding.defs.length === 1 ? binding.defs[0] : undefined;
  if (definition?.type !== "Variable") return undefined;
  const declarator = definition.node as ESTree.VariableDeclarator;
  const declaration = definition.parent as ESTree.VariableDeclaration | null;
  const init = declarator.init;
  if (declaration?.kind !== "const" || declarator.id.type !== "Identifier" || declarator.id.typeAnnotation == null ||
    init?.type !== "ObjectExpression" || parentOf(declaration)?.type === "ExportNamedDeclaration") return undefined;
  return init;
}

/** Every later reference is a safe read in the declaring function. */
function onlyOwnerUses(binding: TsVariable, value: Node, sourceCode: SourceCode): boolean {
  const scope = sourceCode.getScope(value).variableScope;
  return binding.references.every((reference) => reference.init === true ||
    (!reference.isWrite() && sourceCode.getScope(reference.identifier).variableScope === scope &&
      safeTargetUse(reference.identifier, sourceCode)));
}

/** Only typed property operations and unused, inspectable native mutations retain local ownership. */
function safeTargetUse(identifier: Node, sourceCode: SourceCode): boolean {
  if (identifier.type !== "Identifier") return false;
  const parent = parentOf(identifier);
  if (parent?.type === "MemberExpression" && parent.object === identifier) return typedPropertyUse(parent);
  return parent?.type === "CallExpression" && parent.arguments[0] === identifier && inspectableMutation(parent, sourceCode);
}

/** A static, non-optional property access that is neither deleted nor called. */
function typedPropertyUse(member: ESTree.MemberExpression): boolean {
  const key = getPropertyName(member);
  const use = outerExpression(member);
  const useParent = parentOf(use);
  if (member.optional || (useParent?.type === "UnaryExpression" && useParent.operator === "delete")) return false;
  return key !== null && key !== "__proto__" && !(useParent?.type === "CallExpression" && useParent.callee === use);
}

/** A native mutation whose writes and descriptor are inspectable and whose result is unused. */
function inspectableMutation(call: ESTree.CallExpression, sourceCode: SourceCode): boolean {
  const method = nativeMember(call.callee, sourceCode);
  if (method === undefined) return false;
  const writes = mutationWrites(call, method.namespace, method.method);
  return writes !== undefined && writes.every((write) => write.key !== "__proto__") &&
    keepsMutableDescriptor(call, method.method) &&
    (method.method === "set" || parentOf(call)?.type === "ExpressionStatement");
}

/** Explicit descriptor flags can make later writes fail without changing the stored value. */
function keepsMutableDescriptor(call: ESTree.CallExpression, method: string): boolean {
  if (method !== "defineProperty") return true;
  const descriptor = call.arguments[2];
  if (descriptor?.type !== "ObjectExpression") return false;
  const properties = plainProperties(descriptor);
  return properties !== undefined && properties.every((property) => {
    if (property.key !== "writable" && property.key !== "configurable") return true;
    const value = unwrapExpression(property.value);
    return value.type === "Literal" && value.value === true;
  });
}

function nativeMember(node: Node, sourceCode: SourceCode): { readonly namespace: NativeNamespace; readonly method: string } | undefined {
  const member = unwrapExpression(node);
  if (member.type !== "MemberExpression" || member.optional) return undefined;
  const namespace = nativeNamespace(member.object, sourceCode);
  const method = getPropertyName(member);
  if (namespace === undefined || method === null) return undefined;
  return SUPPORTED_METHODS[namespace].has(method) ? { namespace, method } : undefined;
}

/** Reading a namespace as a receiver does not hand its mutable API object to another owner. */
function ordinaryNamespaceUse(node: Node): boolean {
  const value = outerExpression(node);
  const parent = parentOf(value);
  if (parent === null) return false;
  return (parent.type === "MemberExpression" && parent.object === value) ||
    (parent.type === "UnaryExpression" && parent.operator === "typeof") ||
    parent.type === "TSTypeQuery" || parent.type === "TSQualifiedName";
}

function replacementNamespace(node: Node, sourceCode: SourceCode): NativeNamespace | "ObjectPrototype" | undefined {
  const value = unwrapExpression(node);
  if (nativeObjectPrototype(value, sourceCode)) return "ObjectPrototype";
  return nativeNamespace(value, sourceCode) ??
    (value.type === "MemberExpression" ? replacementNamespace(value.object, sourceCode) : undefined);
}

function nativeObjectPrototype(node: Node, sourceCode: SourceCode): boolean {
  const value = unwrapExpression(node);
  return value.type === "MemberExpression" && getPropertyName(value) === "prototype" &&
    nativeNamespace(value.object, sourceCode) === "Object";
}

function nativeNamespace(node: Node, sourceCode: SourceCode): NativeNamespace | undefined {
  const value = unwrapExpression(node);
  if (value.type === "MemberExpression" && !value.optional && nativeGlobalReceiver(value.object, sourceCode)) {
    const key = getPropertyName(value);
    if (key === "Object" || key === "Reflect") return key;
  }
  if (value.type !== "Identifier" || (value.name !== "Object" && value.name !== "Reflect")) return undefined;
  const binding = findVariable(sourceCode.getScope(value), value.name);
  return binding === null || binding.defs.length === 0 ? value.name : undefined;
}

function nativeGlobalReceiver(node: Node, sourceCode: SourceCode): boolean {
  if (node.type !== "Identifier" || !GLOBAL_RECEIVERS.has(node.name)) return false;
  const binding = findVariable(sourceCode.getScope(node), node.name);
  return binding === null || binding.defs.length === 0;
}

function mutationWrites(node: ESTree.CallExpression, namespace: NativeNamespace, method: string): readonly Write[] | undefined {
  if (namespace === "Object" && method === "assign") {
    const source = node.arguments[1];
    return node.arguments.length === 2 && source?.type === "ObjectExpression" ? plainProperties(source) : undefined;
  }
  if (node.arguments.length !== 3 || (method !== "set" && method !== "defineProperty")) return undefined;
  const key = staticString(node.arguments[1]);
  const value = node.arguments[2];
  if (key === null || value === undefined || value.type === "SpreadElement") return undefined;
  if (method === "set") return [{ key, value }];
  const payload = dataDescriptorValue(value);
  return payload === undefined ? undefined : [{ key, value: payload }];
}

/** The `value` of a data descriptor literal that sets no other keys. */
function dataDescriptorValue(descriptor: Node): Node | undefined {
  if (descriptor.type !== "ObjectExpression") return undefined;
  const properties = plainProperties(descriptor);
  if (properties === undefined || properties.some((property) => !DATA_DESCRIPTOR_KEYS.has(property.key))) return undefined;
  return properties.find((property) => property.key === "value")?.value;
}

function plainProperties(node: ESTree.ObjectExpression): readonly Write[] | undefined {
  const writes: Write[] = [];
  const names = new Set<string>();
  for (const property of node.properties) {
    if (property.type !== "Property" || property.kind !== "init" || property.method) return undefined;
    const key = getPropertyName(property);
    if (key === null || key === "__proto__" || names.has(key)) return undefined;
    names.add(key);
    writes.push({ key, value: property.value });
  }
  return writes;
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Keep native object mutation APIs from writing incompatible values into declared property types.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      incompatibleWrite:
        "{{method}} bypasses the declared type of `{{property}}`: `{{actual}}` is not assignable to `{{expected}}`. Use a compatible typed assignment or construct a validated replacement.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let tsrs: TsrsServices | null = null;
    let candidates: Mutation[] = [];
    let replaced = new Set<NativeNamespace>();
    // Built on the first identifier that can name a native namespace or global receiver.
    let references: WeakSet<Node> | null = null;

    function isReference(node: Node): boolean {
      if (references === null) {
        references = new WeakSet();
        for (const scope of sourceCode.scopeManager?.scopes ?? []) {
          for (const reference of scope.references) references.add(reference.identifier);
        }
      }
      return references.has(node);
    }

    function invalidateNamespace(node: Node): void {
      const namespace = replacementNamespace(node, sourceCode);
      if (namespace === "ObjectPrototype") {
        replaced.add("Object");
        replaced.add("Reflect");
      } else if (namespace !== undefined) replaced.add(namespace);
    }

    function inspect(file: TsrsFile, candidate: Mutation): void {
      if (replaced.has(candidate.namespace)) return;
      const ownKeys = localDataTarget(candidate.target, sourceCode);
      if (ownKeys === undefined) return;
      const call = file.tsNode(candidate.call);
      const target = file.tsNode(candidate.target);
      if (call === undefined || target === undefined) return;
      const writes = candidate.writes.map((write): TypedWrite | null => {
        const value = ownKeys.has(write.key) ? file.tsNode(write.value) : undefined;
        return value === undefined ? null : { key: write.key, value };
      });
      const exact = tsrs!.compilerOptions["exactOptionalPropertyTypes"] === true;
      const found = incompatibleWrite(file, exact, call, target, writes);
      if (found === null) return;
      context.report({
        node: candidate.writes[found.index]!.value,
        messageId: "incompatibleWrite",
        data: {
          method: `${candidate.namespace}.${candidate.method}`, property: candidate.writes[found.index]!.key,
          actual: found.actual, expected: found.expected,
        },
      });
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        tsrs = null;
        candidates = [];
        replaced = new Set();
        references = null;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      Identifier(node) {
        // nativeNamespace and nativeGlobalReceiver read only these names.
        if (!NAMESPACE_OR_RECEIVER.has(node.name) || !isReference(node) || ordinaryNamespaceUse(node)) return;
        const namespace = nativeNamespace(node, sourceCode);
        if (namespace !== undefined) replaced.add(namespace);
        if (nativeGlobalReceiver(node, sourceCode)) {
          replaced.add("Object");
          replaced.add("Reflect");
        }
      },
      MemberExpression(node) {
        const namespace = nativeNamespace(node, sourceCode);
        if (namespace !== undefined && !ordinaryNamespaceUse(node)) replaced.add(namespace);
        if (nativeObjectPrototype(node, sourceCode) && !ordinaryNamespaceUse(node)) invalidateNamespace(node);
      },
      AssignmentExpression(node) {
        invalidateNamespace(node.left);
      },
      UpdateExpression(node) {
        invalidateNamespace(node.argument);
      },
      UnaryExpression(node) {
        if (node.operator !== "delete") return;
        invalidateNamespace(node.argument);
      },
      CallExpression(node) {
        const method = nativeMember(node.callee, sourceCode);
        if (method === undefined) return;
        const target = node.arguments[0];
        if (target === undefined) return;
        invalidateNamespace(target);
        if (target.type !== "Identifier") return;
        const writes = mutationWrites(node, method.namespace, method.method);
        if (writes !== undefined) candidates.push({ call: node, ...method, target, writes });
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        tsrs.run((file) => {
          for (const candidate of candidates) inspect(file, candidate);
        });
      },
    };
  },
});
