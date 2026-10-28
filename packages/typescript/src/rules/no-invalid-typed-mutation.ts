/**
 * @fileoverview no-invalid-typed-mutation — native mutation APIs must preserve declared property types.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-invalid-typed-mutation.test.ts
 */
import { ASTUtils, AST_NODE_TYPES, ESLintUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import { isObjectType, isTypeReference } from "ts-api-utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { staticString } from "./_static-string.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";

type Options = readonly [];
type MessageIds = "incompatibleWrite";
type NativeNamespace = "Object" | "Reflect";

interface Write {
  readonly key: string;
  readonly value: TSESTree.Node;
}

interface Mutation {
  readonly call: TSESTree.CallExpression;
  readonly namespace: NativeNamespace;
  readonly method: string;
  readonly target: TSESTree.Identifier;
  readonly writes: readonly Write[];
}

export const NO_INVALID_TYPED_MUTATION_DOCUMENTATION = {
  summary: "Keep native object mutation APIs from writing incompatible values into declared property types.",
  rationale: "Object.assign, Reflect.set and property descriptors accept values that a normal typed property assignment rejects. They can invalidate a domain object's contract while subsequent reads retain its original type.",
  remediation: "Use an assignment that satisfies the declared property type, or construct and validate a complete replacement. Preserve any deliberate construction or external compatibility contract; do not cast away the incompatibility.",
  category: "correctness",
  defaultLevel: "error",
  autofix: "none",
  limitations: [
    "Requires type information and an explicitly annotated local const initialized with a plain own-data object literal. Only non-exported, stable bindings without escapes or nested captures qualify. Deletes and descriptors that can lock writability or configurability invalidate storage provenance. The closed non-union contract must declare the initialized data property; parameters, opaque constructors/factories, accessor, method, indexed, callable and unresolved generic targets are excluded.",
    "Inspects native Object.assign with one plain object-literal source, native Reflect.set with a static string key and no separate receiver, and native Object/Reflect.defineProperty with a plain value descriptor. Dynamic keys, spreads, accessors, API aliases, extra properties and multiple assign sources are excluded.",
    "Any, unknown, never, unresolved generic or overloaded property/value types are excluded because this check cannot prove their incompatibility. Type arguments and nested data fields are inspected with a 32-type recursion bound. Readonly fields are checked only for incompatible values; compatible writes are outside this rule. Under exact optional properties, authored write types are recovered only for direct non-transient declarations without mapped or generic substitution; other explicit-undefined writes can be missed.",
    "Scope-resolved globals and standard-library signatures establish API identity. File-local namespace escapes, aliases, direct replacements or reflective mutation of Object/Reflect invalidate that namespace. Visible Object.prototype mutation or escape invalidates both APIs because descriptors inherit its fields. Indirect monkey-patching and external proxy behavior are not inferred. Generated files are excluded; tests remain checked.",
  ],
  references: [
    "https://typescript-eslint.io/rules/no-unsafe-assignment/",
    "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Object/assign",
  ],
  examples: [
    { id: "compatible-property-write", title: "Preserve the declared field contract", outcome: "no-match", files: [{ path: "src/count.ts", source: 'const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: 2 });' }], focusPath: "src/count.ts", expectedCount: 0, public: true },
    { id: "incompatible-property-write", title: "Do not bypass field compatibility through a generic mutation API", outcome: "match", files: [{ path: "src/count.ts", source: 'const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: "invalid" }); counter.count.toFixed();' }], focusPath: "src/count.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-invalid-typed-mutation",
  documentation: NO_INVALID_TYPED_MUTATION_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_INVALID_TYPED_MUTATION_DOCUMENTATION.summary },
    schema: [],
    messages: { incompatibleWrite: "{{method}} bypasses the declared type of `{{property}}`: `{{actual}}` is not assignable to `{{expected}}`. Use a compatible typed assignment or construct a validated replacement." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text) || !context.sourceCode.parserServices?.program) return {};
    const services = ESLintUtils.getParserServices(context);
    const checker = services.program.getTypeChecker();
    const candidates: Mutation[] = [];
    const replaced = new Set<NativeNamespace>();
    const references = new WeakSet<TSESTree.Node>();
    for (const scope of context.sourceCode.scopeManager?.scopes ?? []) {
      for (const reference of scope.references) references.add(reference.identifier);
    }

    function invalidateNamespace(node: TSESTree.Node): void {
      const namespace = replacementNamespace(node, context.sourceCode);
      if (namespace === "ObjectPrototype") {
        replaced.add("Object");
        replaced.add("Reflect");
      } else if (namespace !== undefined) replaced.add(namespace);
    }

    function inspect(candidate: Mutation): void {
      if (replaced.has(candidate.namespace)) return;
      const ownKeys = localDataTarget(candidate.target, context.sourceCode);
      if (ownKeys === undefined) return;
      const targetNode = services.esTreeNodeToTSNodeMap.get(candidate.target);
      const target = declaredTargetType(targetNode, checker);
      if (target === undefined) return;
      const signature = checker.getResolvedSignature(services.esTreeNodeToTSNodeMap.get(candidate.call));
      if (signature?.declaration === undefined || !services.program.isSourceFileDefaultLibrary(signature.declaration.getSourceFile())) return;
      for (const write of candidate.writes) {
        if (!ownKeys.has(write.key)) continue;
        const property = checker.getPropertyOfType(target, write.key);
        if (property === undefined || !typedDataProperty(property)) continue;
        const expected = propertyWriteType(target, property, targetNode, checker, services.program.getCompilerOptions().exactOptionalPropertyTypes === true);
        const actual = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(write.value));
        if (!definiteType(expected, checker) || !definiteType(actual, checker) || checker.isTypeAssignableTo(actual, expected)) continue;
        context.report({ node: write.value, messageId: "incompatibleWrite", data: {
          method: `${candidate.namespace}.${candidate.method}`, property: write.key,
          actual: checker.typeToString(actual), expected: checker.typeToString(expected),
        } });
        return;
      }
    }

    return {
      Identifier(node): void {
        if (!references.has(node)) return;
        const namespace = nativeNamespace(node, context.sourceCode);
        if (namespace !== undefined && !ordinaryNamespaceUse(node)) replaced.add(namespace);
        if (nativeGlobalReceiver(node, context.sourceCode) && !ordinaryNamespaceUse(node)) {
          replaced.add("Object");
          replaced.add("Reflect");
        }
      },
      MemberExpression(node): void {
        const namespace = nativeNamespace(node, context.sourceCode);
        if (namespace !== undefined && !ordinaryNamespaceUse(node)) replaced.add(namespace);
        if (nativeObjectPrototype(node, context.sourceCode) && !ordinaryNamespaceUse(node)) invalidateNamespace(node);
      },
      AssignmentExpression(node): void {
        invalidateNamespace(node.left);
      },
      UpdateExpression(node): void {
        invalidateNamespace(node.argument);
      },
      UnaryExpression(node): void {
        if (node.operator !== "delete") return;
        invalidateNamespace(node.argument);
      },
      CallExpression(node): void {
        const method = nativeMember(node.callee, context.sourceCode);
        if (method === undefined) return;
        const target = node.arguments[0];
        if (target === undefined) return;
        invalidateNamespace(target);
        if (target.type !== AST_NODE_TYPES.Identifier) return;
        const writes = mutationWrites(node, method.namespace, method.method);
        if (writes !== undefined) candidates.push({ call: node, ...method, target, writes });
      },
      "Program:exit"(): void {
        for (const candidate of candidates) inspect(candidate);
      },
    };
  },
});

/** A structural annotation alone cannot distinguish storage from a coercing setter or proxy. */
function localDataTarget(target: TSESTree.Identifier, sourceCode: TSESLint.SourceCode): ReadonlySet<string> | undefined {
  const binding = ASTUtils.findVariable(sourceCode.getScope(target), target.name);
  const definition = binding?.defs.length === 1 ? binding.defs[0] : undefined;
  if (definition?.type !== "Variable" || definition.parent.kind !== "const" ||
    definition.node.id.type !== AST_NODE_TYPES.Identifier || definition.node.id.typeAnnotation === undefined ||
    definition.node.init?.type !== AST_NODE_TYPES.ObjectExpression ||
    definition.parent.parent.type === AST_NODE_TYPES.ExportNamedDeclaration) return undefined;
  const properties = plainProperties(definition.node.init);
  if (properties === undefined) return undefined;
  const scope = sourceCode.getScope(definition.node).variableScope;
  for (const reference of binding?.references ?? []) {
    if (reference.init === true) continue;
    if (reference.isWrite() || sourceCode.getScope(reference.identifier).variableScope !== scope ||
      !safeTargetUse(reference.identifier, sourceCode)) return undefined;
  }
  return new Set(properties.map((property) => property.key));
}

/** Only typed property operations and unused, inspectable native mutations retain local ownership. */
function safeTargetUse(identifier: TSESTree.Identifier | TSESTree.JSXIdentifier, sourceCode: TSESLint.SourceCode): boolean {
  if (identifier.type !== AST_NODE_TYPES.Identifier) return false;
  const parent = identifier.parent;
  if (parent.type === AST_NODE_TYPES.MemberExpression && parent.object === identifier) {
    const key = ASTUtils.getPropertyName(parent);
    const use = outerExpression(parent);
    if (parent.optional || (use.parent.type === AST_NODE_TYPES.UnaryExpression && use.parent.operator === "delete")) return false;
    return key !== null && key !== "__proto__" &&
      !(use.parent.type === AST_NODE_TYPES.CallExpression && use.parent.callee === use);
  }
  if (parent.type !== AST_NODE_TYPES.CallExpression || parent.arguments[0] !== identifier) return false;
  const method = nativeMember(parent.callee, sourceCode);
  if (method === undefined) return false;
  const writes = mutationWrites(parent, method.namespace, method.method);
  return writes !== undefined && writes.every((write) => write.key !== "__proto__") &&
    keepsMutableDescriptor(parent, method.method) &&
    (method.method === "set" || parent.parent.type === AST_NODE_TYPES.ExpressionStatement);
}

/** Explicit descriptor flags can make later writes fail without changing the stored value. */
function keepsMutableDescriptor(call: TSESTree.CallExpression, method: string): boolean {
  if (method !== "defineProperty") return true;
  const descriptor = call.arguments[2];
  if (descriptor?.type !== AST_NODE_TYPES.ObjectExpression) return false;
  const properties = plainProperties(descriptor);
  return properties !== undefined && properties.every((property) => {
    if (property.key !== "writable" && property.key !== "configurable") return true;
    const value = unwrapExpression(property.value);
    return value.type === AST_NODE_TYPES.Literal && value.value === true;
  });
}

function declaredTargetType(node: ts.Node, checker: ts.TypeChecker): ts.Type | undefined {
  const symbol = checker.getSymbolAtLocation(node);
  const declaration = symbol?.valueDeclaration;
  if (declaration === undefined || !(ts.isVariableDeclaration(declaration) || ts.isParameter(declaration)) || declaration.type === undefined) return undefined;
  const type = checker.getTypeFromTypeNode(declaration.type);
  if (!definiteType(type, checker) || type.isUnionOrIntersection() || (type.flags & ts.TypeFlags.Object) === 0 ||
    checker.getIndexInfosOfType(type).length > 0 || type.getCallSignatures().length > 0 || type.getConstructSignatures().length > 0) return undefined;
  return type;
}

function typedDataProperty(property: ts.Symbol): boolean {
  const declarations = property.getDeclarations();
  return declarations !== undefined && declarations.length === 1 && declarations.every((declaration) =>
    (ts.isPropertySignature(declaration) || ts.isPropertyDeclaration(declaration)) && declaration.type !== undefined);
}

/** Exact optional properties distinguish an omitted field from an explicitly undefined write. */
function propertyWriteType(target: ts.Type, property: ts.Symbol, node: ts.Node, checker: ts.TypeChecker, exact: boolean): ts.Type {
  const exposed = checker.getTypeOfSymbolAtLocation(property, node);
  if (!exact || (property.flags & ts.SymbolFlags.Optional) === 0 || (property.flags & ts.SymbolFlags.Transient) !== 0) return exposed;
  if ((target.aliasTypeArguments?.length ?? 0) > 0 ||
    (isTypeReference(target) && checker.getTypeArguments(target).length > 0) ||
    (isObjectType(target) && (target.objectFlags & (ts.ObjectFlags.Mapped | ts.ObjectFlags.Instantiated)) !== 0)) return exposed;
  const declaration = property.getDeclarations()?.[0];
  if (declaration === undefined || !(ts.isPropertySignature(declaration) || ts.isPropertyDeclaration(declaration)) ||
    declaration.questionToken === undefined || declaration.type === undefined) return exposed;
  const authored = checker.getTypeFromTypeNode(declaration.type);
  return definiteType(authored, checker) && checker.isTypeAssignableTo(authored, exposed) ? authored : exposed;
}

function definiteType(type: ts.Type, checker: ts.TypeChecker, seen = new Set<ts.Type>()): boolean {
  if (seen.has(type)) return true;
  if (seen.size >= 32) return false;
  seen.add(type);
  const unsafe = ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.Never | ts.TypeFlags.TypeParameter |
    ts.TypeFlags.Conditional | ts.TypeFlags.IndexedAccess | ts.TypeFlags.Substitution;
  if ((type.flags & unsafe) !== 0) return false;
  if (type.isUnionOrIntersection()) return type.types.every((part) => definiteType(part, checker, seen));
  const arguments_ = isTypeReference(type) ? checker.getTypeArguments(type) : type.aliasTypeArguments ?? [];
  if (!arguments_.every((argument) => definiteType(argument, checker, seen))) return false;
  if (!definiteSignatures(type, checker, seen)) return false;
  if (isTypeReference(type) || (type.flags & ts.TypeFlags.Object) === 0) return true;
  return type.getProperties().every((property) => {
    const declaration = property.valueDeclaration ?? property.getDeclarations()?.[0];
    return declaration !== undefined && definiteType(checker.getTypeOfSymbolAtLocation(property, declaration), checker, seen);
  });
}

function definiteSignatures(type: ts.Type, checker: ts.TypeChecker, seen: Set<ts.Type>): boolean {
  const signatures = type.getCallSignatures();
  if (signatures.length > 1) return false;
  return signatures.every((signature) => signature.typeParameters === undefined &&
    definiteType(checker.getReturnTypeOfSignature(signature), checker, seen) &&
    signature.parameters.every((parameter) => {
      const declaration = parameter.valueDeclaration ?? parameter.getDeclarations()?.[0];
      return declaration !== undefined && definiteType(checker.getTypeOfSymbolAtLocation(parameter, declaration), checker, seen);
    }));
}

function nativeMember(node: TSESTree.Node, sourceCode: TSESLint.SourceCode): { readonly namespace: NativeNamespace; readonly method: string } | undefined {
  const member = unwrapExpression(node);
  if (member.type !== AST_NODE_TYPES.MemberExpression || member.optional) return undefined;
  const namespace = nativeNamespace(member.object, sourceCode);
  const method = ASTUtils.getPropertyName(member);
  if (namespace === undefined || method === null) return undefined;
  const supported = namespace === "Object" ? ["assign", "defineProperty", "defineProperties", "setPrototypeOf"] : ["set", "defineProperty", "setPrototypeOf"];
  return supported.includes(method) ? { namespace, method } : undefined;
}

/** Reading a namespace as a receiver does not hand its mutable API object to another owner. */
function ordinaryNamespaceUse(node: TSESTree.Node): boolean {
  const value = outerExpression(node);
  const parent = value.parent;
  if (parent === undefined) return false;
  return (parent.type === AST_NODE_TYPES.MemberExpression && parent.object === value) ||
    (parent.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "typeof") ||
    parent.type === AST_NODE_TYPES.TSTypeQuery || parent.type === AST_NODE_TYPES.TSQualifiedName;
}

function replacementNamespace(node: TSESTree.Node, sourceCode: TSESLint.SourceCode): NativeNamespace | "ObjectPrototype" | undefined {
  const value = unwrapExpression(node);
  if (nativeObjectPrototype(value, sourceCode)) return "ObjectPrototype";
  return nativeNamespace(value, sourceCode) ??
    (value.type === AST_NODE_TYPES.MemberExpression ? replacementNamespace(value.object, sourceCode) : undefined);
}

function nativeObjectPrototype(node: TSESTree.Node, sourceCode: TSESLint.SourceCode): boolean {
  const value = unwrapExpression(node);
  return value.type === AST_NODE_TYPES.MemberExpression && ASTUtils.getPropertyName(value) === "prototype" &&
    nativeNamespace(value.object, sourceCode) === "Object";
}

function nativeNamespace(node: TSESTree.Node, sourceCode: TSESLint.SourceCode): NativeNamespace | undefined {
  const value = unwrapExpression(node);
  if (value.type === AST_NODE_TYPES.MemberExpression && !value.optional &&
    nativeGlobalReceiver(value.object, sourceCode)) {
    const key = ASTUtils.getPropertyName(value);
    if (key === "Object" || key === "Reflect") return key;
  }
  if (value.type !== AST_NODE_TYPES.Identifier || (value.name !== "Object" && value.name !== "Reflect")) return undefined;
  const binding = ASTUtils.findVariable(sourceCode.getScope(value), value.name);
  return binding === null || binding.defs.length === 0 ? value.name : undefined;
}

function nativeGlobalReceiver(node: TSESTree.Node, sourceCode: TSESLint.SourceCode): boolean {
  if (node.type !== AST_NODE_TYPES.Identifier || !["globalThis", "window", "self"].includes(node.name)) return false;
  const binding = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
  return binding === null || binding.defs.length === 0;
}

function mutationWrites(node: TSESTree.CallExpression, namespace: NativeNamespace, method: string): readonly Write[] | undefined {
  if (namespace === "Object" && method === "assign") {
    const source = node.arguments[1];
    return node.arguments.length === 2 && source?.type === AST_NODE_TYPES.ObjectExpression ? plainProperties(source) : undefined;
  }
  if (node.arguments.length !== 3 || (method !== "set" && method !== "defineProperty")) return undefined;
  const key = staticString(node.arguments[1]);
  const value = node.arguments[2];
  if (key === null || value === undefined || value.type === AST_NODE_TYPES.SpreadElement) return undefined;
  if (method === "set") return [{ key, value }];
  if (value.type !== AST_NODE_TYPES.ObjectExpression) return undefined;
  const properties = plainProperties(value);
  if (properties === undefined || properties.some((property) => !["value", "configurable", "enumerable", "writable"].includes(property.key))) return undefined;
  const payload = properties.find((property) => property.key === "value");
  return payload === undefined ? undefined : [{ key, value: payload.value }];
}

function plainProperties(node: TSESTree.ObjectExpression): readonly Write[] | undefined {
  const writes: Write[] = [];
  const names = new Set<string>();
  for (const property of node.properties) {
    if (property.type !== AST_NODE_TYPES.Property || property.kind !== "init" || property.method) return undefined;
    const key = ASTUtils.getPropertyName(property);
    if (key === null || key === "__proto__" || names.has(key)) return undefined;
    names.add(key);
    writes.push({ key, value: property.value });
  }
  return writes;
}
