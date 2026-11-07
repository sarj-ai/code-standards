/**
 * @fileoverview no-zod-parse-typed-object — keep runtime parsing at unknown-data boundaries.
 *
 * Port of the 18.x `no-zod-parse-typed-object` rule. Typed: it needs
 * tsrs types and strict null checks; without either it reports nothing, as the
 * original returns no visitors without a program. The walk collects parse
 * calls; `Program:exit` asks for their argument types in one request, resolves
 * the signatures of calls with an object argument in another, then runs the
 * original's shape checks on the zod calls left, over tsrs's full checker,
 * batching the type facts each step reads. Type identity (`seen`, the pair and
 * assignability caches) is by tsrs type id.
 */

import type { Node as TsNode } from "tsrs/ast";
import type { Signature, Symbol as TsSymbol, Type } from "tsrs/sync";

import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { type NativeTypes, nativeTypes, unionMembers } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "../utils/paths.js";
import { getPropertyName } from "../utils/static-string.js";
import { type TsrsFile, type TsrsRequest, type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";

const NAME = "no-zod-parse-typed-object";
const PARSE_METHODS: ReadonlySet<string> = new Set(["parse", "parseAsync", "safeParse", "safeParseAsync"]);
const DECLARATION_FILE = /\.d\.[cm]?ts$/u;

interface Candidate {
  readonly node: ESTree.CallExpression;
  readonly callee: ESTree.MemberExpression;
  readonly argument: Node;
}

interface Env {
  readonly native: NativeTypes;
  readonly opaque: number;
  /** `checker.isTypeAssignableTo` answers for this file, by source and target type id. */
  readonly assignable: Map<string, boolean>;
}

/** `checker.isTypeAssignableTo`, asked once per type pair: a type is assignable to itself, as TypeScript's relation check starts. */
function isAssignable(env: Env, source: Type, target: Type): boolean {
  if (source.id === target.id) return true;
  const key = `${String(source.id)}:${String(target.id)}`;
  let answer = env.assignable.get(key);
  if (answer === undefined) {
    answer = env.native.checker.isTypeAssignableTo(source, target);
    env.assignable.set(key, answer);
  }
  return answer;
}

function elementFlags(type: Type): readonly number[] {
  return (type as Type & { getTarget(): { readonly elementFlags: readonly number[] } }).getTarget().elementFlags;
}

function knownValue(env: Env, type: Type, location: TsNode, seen: Set<number>): boolean {
  const { checker, file, sync } = env.native;
  const flags = sync.TypeFlags;
  if ((type.flags & env.opaque) !== 0) return false;
  if (type.isUnionType()) return type.getTypes().every((member) => knownValue(env, member, location, seen));
  if ((type.flags & flags.Object) === 0) return true;
  if (seen.has(type.id)) return true;
  if (seen.size >= 128) return false;
  // The original asks for each of these in turn; one round trip asks for all of them.
  const [calls, constructs, array, properties, indexes] = ask(file, sync.all(
    type.getCallSignatures.gen(), type.getConstructSignatures.gen(), checker.isArrayType.gen(type),
    type.getProperties.gen(), checker.getIndexInfosOfType.gen(type)));
  if (calls.length > 0 || constructs.length > 0) return false;
  seen.add(type.id);
  if (type.isTupleType()) {
    const elements = checker.getTypeArguments(type);
    return elements.length <= 128 && elements.every((element) => knownValue(env, element, location, seen));
  }
  if (array) {
    const element = type.getNumberIndexType();
    return element !== undefined && knownValue(env, element, location, seen);
  }
  if (properties.length + indexes.length === 0 || properties.length > 128) return false;
  const types = file.batch(properties.map((property) => checker.getTypeOfSymbolAtLocation.gen(property, location)));
  return types.every((member) => knownValue(env, member, location, seen)) &&
    indexes.every((index) => knownValue(env, index.valueType, location, seen));
}

/** One request generator's answer, in one round trip. */
function ask<T>(file: TsrsFile, request: TsrsRequest<T>): T {
  return file.batch([request])[0] as T;
}

/** A parse call whose argument has an object type, with its tsrs nodes. */
interface ObjectParse {
  readonly candidate: Candidate;
  readonly call: TsNode;
  readonly value: TsNode;
  readonly receiver: TsNode;
  readonly actual: Type;
}

/**
 * The original's checks after the native zod signature check, for one call. The original
 * walks the value's type before the schema's; both must pass, so this checks the cheaper
 * schema assignability first.
 */
function typedObjectParse(env: Env, { value, receiver, actual }: ObjectParse): boolean {
  const { checker } = env.native;
  const schema = checker.getTypeAtLocation(receiver);
  const internals = schema.getProperty("_zod");
  const contracts = internals === undefined ? schema : checker.getTypeOfSymbolAtLocation(internals, receiver);
  const input = contracts.getProperty(internals === undefined ? "_input" : "input");
  const output = contracts.getProperty(internals === undefined ? "_output" : "output");
  if (input === undefined || output === undefined) return false;
  const inputType = checker.getTypeOfSymbolAtLocation(input, receiver);
  if (!isAssignable(env, actual, inputType) || !knownValue(env, actual, value, new Set())) return false;
  return sameShape(env, inputType, checker.getTypeOfSymbolAtLocation(output, receiver), receiver);
}

function sameShape(env: Env, input: Type, output: Type, location: TsNode): boolean {
  const { checker, file, sync } = env.native;
  const flags = sync.TypeFlags;
  const opaque = env.opaque;
  let remaining = 128;
  const pairs = new Map<number, Map<number, boolean>>();
  function compare(left: Type, right: Type): boolean {
    if (((left.flags | right.flags) & opaque) !== 0) return false;
    if (left.isUnionType() || right.isUnionType()) return sameUnion(left, right);
    if ((left.flags & flags.Object) === 0 || (right.flags & flags.Object) === 0) {
      return isAssignable(env, left, right) && isAssignable(env, right, left);
    }
    return memoizedObjectShape(left, right);
  }

  function sameUnion(left: Type, right: Type): boolean {
    const a = unionMembers(left).filter((member) => (member.flags & flags.Undefined) === 0);
    const b = unionMembers(right).filter((member) => (member.flags & flags.Undefined) === 0);
    const limit = [...a, ...b].every((member) => (member.flags & (flags.Object | opaque)) === 0) ? 128 : 16;
    return a.length > 0 && a.length === b.length && a.length <= limit &&
      a.every((member) => identicalPrimitive(member, b) || b.some((other) => compare(member, other))) &&
      b.every((member) => identicalPrimitive(member, a) || a.some((other) => compare(other, member)));
  }

  /** Object pairs are compared once; a pair under comparison counts as matching, so recursive types terminate. */
  function memoizedObjectShape(left: Type, right: Type): boolean {
    const previous = pairs.get(left.id)?.get(right.id);
    if (previous !== undefined) return previous;
    if (remaining-- <= 0 || left.getCallSignatures().length > 0 || right.getCallSignatures().length > 0) return false;
    const matches = pairs.get(left.id) ?? new Map<number, boolean>();
    matches.set(right.id, true);
    pairs.set(left.id, matches);
    const result = sameObjectShape(left, right);
    matches.set(right.id, result);
    return result;
  }

  // Comparing a non-object member reads only assignability, which holds between identical types, so an
  // identical alternative settles it without asking tsrs.
  function identicalPrimitive(member: Type, others: readonly Type[]): boolean {
    return (member.flags & (flags.Object | opaque)) === 0 && others.some((other) => other.id === member.id);
  }

  // The original asks for each type fact in turn; these ask for the facts a step needs in one round trip, then compare in the original's order.
  function sameObjectShape(left: Type, right: Type): boolean {
    const [leftTuple, rightTuple, leftArray, rightArray, properties, rightProperties] = ask(file, sync.all(
      checker.isTupleType.gen(left), checker.isTupleType.gen(right), checker.isArrayType.gen(left), checker.isArrayType.gen(right),
      left.getProperties.gen(), right.getProperties.gen()));
    if (leftTuple || rightTuple) return leftTuple && rightTuple && sameTuplePositions(left, right);
    if (leftArray) return rightArray && sameArrayElements(left, right);
    return properties.length === rightProperties.length && properties.length <= 128 &&
      sameProperties(right, properties) && sameIndexInfos(left, right);
  }

  function sameArrayElements(left: Type, right: Type): boolean {
    const a = left.getNumberIndexType();
    const b = right.getNumberIndexType();
    return a !== undefined && b !== undefined && compare(a, b);
  }

  function sameProperties(right: Type, properties: readonly TsSymbol[]): boolean {
    const others = file.batch(properties.map((property) => right.getProperty.gen(property.name)));
    // The original stops at the first property the right side lacks.
    const matched: [TsSymbol, TsSymbol][] = [];
    for (const [i, property] of properties.entries()) {
      const other = others[i];
      if (other === undefined) break;
      matched.push([property, other]);
    }
    const types = file.batch(matched.flatMap(([property, other]) =>
      [checker.getTypeOfSymbolAtLocation.gen(property, location), checker.getTypeOfSymbolAtLocation.gen(other, location)]));
    for (let i = 0; i < matched.length; i++) {
      const a = types[2 * i];
      const b = types[2 * i + 1];
      if (a === undefined || b === undefined || !compare(a, b)) return false;
    }
    return matched.length === properties.length;
  }

  function sameIndexInfos(left: Type, right: Type): boolean {
    const a = checker.getIndexInfosOfType(left);
    const b = checker.getIndexInfosOfType(right);
    return a.length === b.length && a.every((index) => b.some((other) =>
      isAssignable(env, index.keyType, other.keyType) && isAssignable(env, other.keyType, index.keyType) &&
      compare(index.valueType, other.valueType)));
  }

  function sameTuplePositions(left: Type, right: Type): boolean {
    if (!left.isTupleType() || !right.isTupleType()) return false;
    const a = checker.getTypeArguments(left);
    const b = checker.getTypeArguments(right);
    const rightFlags = elementFlags(right);
    return a.length <= 128 && a.length === b.length && elementFlags(left).every((flag, index) => flag === rightFlags[index]) &&
      a.every((element, index) => {
        const other = b[index];
        return other !== undefined && compare(element, other);
      });
  }

  return compare(input, output);
}

function isZodDeclaration(signature: Signature | undefined): boolean {
  const path = signature?.declaration?.path;
  return path !== undefined && DECLARATION_FILE.test(path) && path.replaceAll("\\", "/").includes("/node_modules/zod/");
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Reuse known object contracts instead of parsing them again with Zod.", url: docsUrl(NAME) },
    schema: [],
    messages: {
      typedObject:
        "This object already has a compatible TypeScript contract. Reuse the typed value and make defaults or normalization explicit; reserve Zod parsing for unknown boundary data.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: Candidate[] = [];

    function resolve(native: NativeTypes): boolean[] {
      const flags = native.sync.TypeFlags;
      const env: Env = {
        native,
        opaque: flags.Any | flags.Unknown | flags.Never | flags.TypeParameter | flags.Conditional | flags.IndexedAccess |
          flags.Intersection | flags.NonPrimitive,
        assignable: new Map(),
      };
      // The original resolves every call's signature first. Every check must pass, so this asks for all
      // argument types in one request and resolves signatures only for calls with an object argument.
      const located = candidates.flatMap((candidate) => {
        const call = native.node(candidate.node);
        const value = native.node(unwrapExpression(candidate.argument));
        const receiver = native.node(candidate.callee.object);
        return call === undefined || value === undefined || receiver === undefined ? [] : [{ candidate, call, value, receiver }];
      });
      const actuals = located.length === 0 ? [] : native.checker.getTypeAtLocation(located.map(({ value }) => value));
      const objects = located.flatMap((parse, i): ObjectParse[] => {
        const actual = actuals[i];
        return actual !== undefined && unionMembers(actual).every((type) => (type.flags & flags.Object) !== 0) ? [{ ...parse, actual }] : [];
      });
      const signatures = native.file.batch(objects.map(({ call }) => native.checker.getResolvedSignature.gen(call)));
      const found = new Set(objects.filter((parse, i) => isZodDeclaration(signatures[i]) && typedObjectParse(env, parse)).map(({ candidate }) => candidate));
      return candidates.map((candidate) => found.has(candidate));
    }

    return {
      before() {
        tsrs = null;
        candidates = [];
        const file = { filename: context.filename, cwd: context.cwd };
        if (isGeneratedFile(file, context.sourceCode.text) || isTestFile(file) || isStoryFile(file)) return false;
        tsrs = tsrsServices(context);
        const options = tsrs?.compilerOptions;
        return options !== undefined && Boolean(options.strictNullChecks ?? options.strict ?? false);
      },
      CallExpression(node) {
        const callee = unwrapExpression(node.callee);
        const argument = node.arguments[0];
        if (node.optional || argument === undefined || argument.type === "SpreadElement" ||
          callee.type !== "MemberExpression" || callee.optional || !PARSE_METHODS.has(getPropertyName(callee) ?? "")) return;
        candidates.push({ node, callee, argument });
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        const found = tsrs.run((file) => resolve(nativeTypes(file)));
        if (found === null) return;
        candidates.forEach((candidate, i) => {
          if (found[i] === true) context.report({ node: candidate.node, messageId: "typedObject" });
        });
      },
    };
  },
});
