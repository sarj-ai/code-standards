/**
 * @fileoverview prefer-typed-reflection — Prefer typed access when Reflect.get or Reflect.apply discards a known contract.
 *
 * Port of the 18.x `prefer-typed-reflection` rule. Typed: without tsrs
 * types it reports nothing, as the original returns no visitors without a
 * program. The walk resolves `Reflect` and collects `Reflect.get`/`apply`
 * calls; `Program:exit` asks tsrs about their targets, then reports.
 */

import type { Type } from "tsrs/sync";

import { defineRule, type ESTree, type Node, type TsReference, type TsVariable } from "../types.js";
import { isErasedExpression, outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { type NativeTypes, nativeTypes } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { stableConstInitializer, typeOnlyReference, writtenMember } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName, staticString } from "../utils/static-string.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";

const NAME = "prefer-typed-reflection";

function knownType(native: NativeTypes, type: Type): boolean {
  if (type.isUnionType()) return type.getTypes().every((part) => knownType(native, part));
  const flags = native.sync.TypeFlags;
  return (type.flags & (flags.Any | flags.Unknown | flags.TypeParameter | flags.Never)) === 0;
}

function closedObject(native: NativeTypes, type: Type): boolean {
  if (type.isUnionType()) return type.getTypes().every((part) => closedObject(native, part));
  return knownType(native, type) && type.getProperties().length > 0 && native.checker.getIndexInfosOfType(type).length === 0;
}

/** A string or number literal property key, as the property name it reads. */
function staticKeyName(node: Node | undefined): string | null {
  if (node === undefined) return null;
  const key = unwrapExpression(node);
  return staticString(key) ?? (key.type === "Literal" && typeof key.value === "number" ? String(key.value) : null);
}

/** Whether `node`, past TypeScript wrappers and optional chains, is only read: not deleted, called or used as a tag. */
function isPlainRead(node: Node): boolean {
  let outer = node;
  let parent = parentOf(outer);
  while (parent !== null && (isErasedExpression(parent) || parent.type === "ChainExpression")) {
    outer = parent;
    parent = parentOf(outer);
  }
  return parent === null || !((parent.type === "UnaryExpression" && parent.operator === "delete") ||
    (parent.type === "CallExpression" && parent.callee === outer) ||
    (parent.type === "TaggedTemplateExpression" && parent.tag === outer));
}

interface Candidate {
  readonly node: ESTree.CallExpression;
  readonly method: "get" | "apply";
  readonly target: ESTree.Expression;
  /** For `apply`: whether the argument array is a literal or a proven stable const tuple (before its type check). */
  readonly tuple: ESTree.IdentifierReference | null;
  readonly literalArguments: boolean;
  /** For `get`: whether the call is on `Reflect` itself, so a fix may apply. */
  readonly direct: boolean;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Prefer typed access when Reflect.get or Reflect.apply discards a known contract.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      avoid:
        "Reflection discards this known contract. Use typed property access or a typed call; preserve the invocation receiver and property semantics.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: Candidate[] = [];
    let globalsAreStable: boolean | undefined;

    const globalName = (node: Node, name: string): boolean =>
      node.type === "Identifier" && node.name === name &&
      !findVariable(context.sourceCode.getScope(node), name)?.defs.length;

    const declaredAlias = (parent: ESTree.VariableDeclarator): TsVariable | undefined => {
      const identifier = parent.id;
      return context.sourceCode.getDeclaredVariables(parent).find((binding) => binding.identifiers.includes(identifier as never)) as TsVariable | undefined;
    };

    const constAliasDeclarator = (value: Node): ESTree.VariableDeclarator | null => {
      const parent = parentOf(value);
      if (parent?.type !== "VariableDeclarator" || parent.init !== value || parent.id.type !== "Identifier" ||
        (parentOf(parent) as ESTree.VariableDeclaration).kind !== "const") return null;
      return parent;
    };

    const safeAliasUses = (variable: TsVariable, seen = new Set<TsVariable>()): boolean => {
      if (seen.has(variable)) return false;
      seen.add(variable);
      return variable.references.every((reference: TsReference) => {
        if (reference.init === true || typeOnlyReference(reference)) return true;
        if (reference.isWrite()) return false;
        const value = outerExpression(reference.identifier);
        const parent = parentOf(value);
        if (parent === null) return false;
        if (parent.type === "MemberExpression" && parent.object === value) return !writtenMember(parent);
        const declarator = constAliasDeclarator(value);
        if (declarator === null) return false;
        const alias = declaredAlias(declarator);
        return alias !== undefined && safeAliasUses(alias, new Set(seen));
      });
    };

    const directReflect = (node: Node): boolean =>
      globalName(node, "Reflect") ||
      (node.type === "MemberExpression" && getPropertyName(node) === "Reflect" && globalName(node.object, "globalThis"));

    const isReflect = (input: Node, seen = new Set<Node>()): boolean => {
      const node = unwrapExpression(input);
      if (directReflect(node)) return true;
      if (node.type !== "Identifier" || seen.has(node)) return false;
      seen.add(node);
      const local = stableConstInitializer(context.sourceCode, node);
      if (local === null || !safeAliasUses(local.variable) || !stableReflectGlobals()) return false;
      return isReflect(local.value, seen);
    };

    const stableReflectGlobals = (): boolean => {
      if (globalsAreStable !== undefined) return globalsAreStable;
      const safeUse = (node: Node): boolean => {
        const value = outerExpression(node);
        const parent = parentOf(value);
        if (parent === null) return false;
        if (parent.type === "MemberExpression" && parent.object === value) return !writtenMember(parent);
        const declarator = constAliasDeclarator(value);
        if (declarator === null) return false;
        const alias = declaredAlias(declarator);
        return alias !== undefined && safeAliasUses(alias);
      };
      globalsAreStable = context.sourceCode.scopeManager.scopes.every((scope) => scope.references.every((entry) => {
        const reference = entry as TsReference;
        if (typeOnlyReference(reference)) return true;
        const identifier = reference.identifier;
        if (globalName(identifier, "Reflect")) return safeUse(identifier);
        if (!globalName(identifier, "globalThis")) return true;
        const member = parentOf(outerExpression(identifier));
        if (member === null) return true;
        return member.type !== "MemberExpression" || getPropertyName(member) !== "Reflect" ||
          !writtenMember(member) && safeUse(member);
      }));
      return globalsAreStable;
    };

    /** The untyped half of the original's `tupleArguments`; the tuple type check waits for `Program:exit`. */
    const tupleCandidate = (node: Node | undefined): ESTree.IdentifierReference | null => {
      if (node?.type !== "Identifier") return null;
      const local = stableConstInitializer(context.sourceCode, node);
      if (local === null) return null;
      const value = unwrapExpression(local.value);
      if (value.type !== "ArrayExpression" ||
        value.elements.some((element) => element === null || element.type === "SpreadElement")) return null;
      const used = local.variable.references.every((reference) => {
        if (reference.init === true || typeOnlyReference(reference)) return true;
        const argument = outerExpression(reference.identifier);
        const call = parentOf(argument);
        if (call === null) return false;
        return !reference.isWrite() && call.type === "CallExpression" &&
          call.arguments[2] === argument && call.callee.type === "MemberExpression" &&
          getPropertyName(call.callee) === "apply" && isReflect(call.callee.object);
      });
      return used ? node as ESTree.IdentifierReference : null;
    };

    /** The fix text (or null for a report without a fix), or false when the call is not reported. */
    function decide(native: NativeTypes, candidate: Candidate): string | null | false {
      const targetNode = native.node(candidate.target);
      if (targetNode === undefined) return false;
      const type = native.checker.getTypeAtLocation(targetNode);
      return candidate.method === "get" ? decideGet(native, candidate, type) : decideApply(native, candidate, type);
    }

    function decideGet(native: NativeTypes, { node, target, direct }: Candidate, type: Type): string | null | false {
      const name = staticKeyName(node.arguments[1]);
      if (node.arguments.length !== 2 || name === null || !closedObject(native, type)) return false;
      return direct ? replacement(native, node, type, target, name) : null;
    }

    function decideApply(native: NativeTypes, candidate: Candidate, type: Type): null | false {
      const { checker } = native;
      const { node, tuple, literalArguments } = candidate;
      if (node.arguments.length !== 3 || (!literalArguments && tuple === null)) return false;
      if (tuple !== null) {
        const tupleNode = native.node(tuple);
        if (tupleNode === undefined || !checker.isTupleType(checker.getTypeAtLocation(tupleNode))) return false;
      }
      if (!knownType(native, type)) return false;
      const call = native.node(node);
      if (call === undefined) return false;
      const knownParameter = (parameter: Parameters<typeof checker.getTypeOfSymbolAtLocation>[0]): boolean => {
        const parameterType = checker.getTypeOfSymbolAtLocation(parameter, call);
        return knownType(native, parameterType) && (literalArguments ||
          checker.getIndexInfosOfType(parameterType).every((index) => knownType(native, index.valueType)));
      };
      const typed = type.getCallSignatures().some((signature) =>
        (signature.typeParameters?.length ?? 0) === 0 && signature.getParameters().every(knownParameter));
      return typed ? null : false;
    }

    /** `(target)[key]` for a direct `Reflect.get(target, key)` read of a property every member of `type` declares. */
    function replacement(native: NativeTypes, node: ESTree.CallExpression, type: Type, target: ESTree.Expression, name: string): string | null {
      const key = node.arguments[1];
      if (node.optional || node.callee.type !== "MemberExpression" || node.callee.optional || key === undefined ||
        context.sourceCode.getCommentsInside(node).length > 0 || !isPlainRead(node)) return null;
      const members = type.isUnionType() ? type.getTypes() : [type];
      const objectFlag = native.sync.TypeFlags.Object;
      if (!members.every((member) => (member.flags & objectFlag) !== 0 && native.checker.getPropertyOfType(member, name) !== undefined)) return null;
      return `(${context.sourceCode.getText(target)})[${context.sourceCode.getText(key)}]`;
    }

    return {
      before() {
        tsrs = null;
        candidates = [];
        globalsAreStable = undefined;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      CallExpression(node) {
        if (node.callee.type !== "MemberExpression") return;
        const method = getPropertyName(node.callee);
        const target = node.arguments[0];
        // Check the call's shape before resolving `Reflect` through scopes and aliases.
        if ((method !== "get" && method !== "apply") || target === undefined || target.type === "SpreadElement" ||
          !isReflect(node.callee.object)) return;
        const third = node.arguments[2];
        candidates.push({
          node,
          method,
          target,
          literalArguments: third?.type === "ArrayExpression",
          tuple: method === "apply" && third?.type !== "ArrayExpression" ? tupleCandidate(third) : null,
          direct: method === "get" && directReflect(node.callee.object),
        });
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        const decisions = tsrs.run((file) => {
          const native = nativeTypes(file);
          return candidates.map((candidate) => decide(native, candidate));
        });
        if (decisions === null) return;
        candidates.forEach((candidate, i) => {
          const decision = decisions[i];
          if (decision === false || decision === undefined) return;
          const { node } = candidate;
          context.report(decision === null
            ? { node, messageId: "avoid" }
            : { node, messageId: "avoid", fix: (fixer) => fixer.replaceText(node, decision) });
        });
      },
    };
  },
});
