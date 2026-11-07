/**
 * @fileoverview no-broad-return-type — Report explicit broad return annotations that erase a known return value.
 *
 * Port of the 18.x `no-broad-return-type` rule. Typed: the original
 * returns no visitors without a program. Types come from tsrs only; when
 * `tsrsServices` is null `before()` skips the file.
 *
 * The walk records, per function with a return annotation and no type
 * parameters, the annotation and every returned value (expression bodies and
 * `return` arguments of that function, not nested ones), as the original's
 * frame stack does. `Program:exit` then asks tsrs, in a few batched requests,
 * which annotations are broad and what the returned values of those functions
 * are, and reports the frames the original would.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import type { TsrsFile, TsrsRequest, TsrsServices, TsrsSymbol, TsrsType, TsrsTypeFlags } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";
import { retainsNamedTypeUses } from "../utils/type-binding.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";

const NAME = "no-broad-return-type";

type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;

interface Frame {
  readonly node: FunctionNode;
  /** The return annotation, when the function has one and no type parameters; broadness waits for types. */
  readonly annotation: ESTree.TSTypeAnnotation | null;
  readonly values: Node[];
}

interface TypeChecker {
  readonly getAwaitedType: { gen(type: TsrsType): TsrsRequest<TsrsType | undefined> };
  readonly getIndexInfosOfType: { gen(type: TsrsType): TsrsRequest<readonly { readonly valueType: TsrsType }[]> };
  readonly getPropertiesOfType: { gen(type: TsrsType): TsrsRequest<readonly TsrsSymbol[]> };
}

/** What the original's checks read from a type besides its flags, fetched in batches. */
interface TypeFacts {
  readonly members: Map<TsrsType, readonly TsrsType[]>;
  readonly indexValueFlags: Map<TsrsType, readonly number[]>;
  readonly propertyCount: Map<TsrsType, number>;
}

function isBroad(type: TsrsType, facts: TypeFacts, flags: TsrsTypeFlags): boolean {
  if ((type.flags & (flags.Unknown | flags.NonPrimitive)) !== 0) return true;
  const indexes = facts.indexValueFlags.get(type) ?? [];
  return indexes.length > 0 && facts.propertyCount.get(type) === 0 && indexes.every((index) => (index & flags.Unknown) !== 0);
}

function hasKnownContract(type: TsrsType, facts: TypeFacts, flags: TsrsTypeFlags): boolean {
  const members = facts.members.get(type);
  if (members !== undefined) return members.every((part) => hasKnownContract(part, facts, flags));
  const excluded = flags.Any | flags.Unknown | flags.Never | flags.TypeParameter | flags.Conditional | flags.IndexedAccess |
    flags.Substitution | flags.Null | flags.Undefined | flags.Void;
  if ((type.flags & excluded) !== 0 || isBroad(type, facts, flags)) return false;
  return (type.flags & flags.Object) === 0 || (facts.propertyCount.get(type) ?? 0) > 0;
}

function isOpaque(type: TsrsType, facts: TypeFacts, flags: TsrsTypeFlags): boolean {
  const members = facts.members.get(type);
  if (members !== undefined) return members.some((part) => isOpaque(part, facts, flags));
  return (type.flags & (flags.Any | flags.Unknown | flags.TypeParameter | flags.Conditional | flags.IndexedAccess |
    flags.Substitution)) !== 0 || isBroad(type, facts, flags);
}

/** The original's `valueType` for many nodes: the node's type, awaited unless it is a type parameter. */
function valueTypes(file: TsrsFile, flags: TsrsTypeFlags, nodes: readonly Node[]): (TsrsType | undefined)[] {
  const checker = file.checker as unknown as TypeChecker;
  // A type reference without type arguments shares its range with its name, whose type is not the referenced type.
  const mapped = nodes.map((node) => node.type === "TSTypeReference" ? file.outerTsNode(node) : file.tsNode(node));
  const present = mapped.filter((node) => node !== undefined);
  const found = present.length === 0 ? [] : file.checker.getTypeAtLocation(present);
  let next = 0;
  const types = mapped.map((node) => node === undefined ? undefined : found[next++]);
  const awaitable = [...new Set(types.flatMap((type) => type !== undefined && (type.flags & flags.TypeParameter) === 0 ? [type] : []))];
  const awaited = file.batch(awaitable.map((type) => checker.getAwaitedType.gen(type)));
  const awaitedOf = new Map(awaitable.map((type, i) => [type, awaited[i] ?? type]));
  return types.map((type) => type === undefined ? undefined : awaitedOf.get(type) ?? type);
}

/** Union members, index signatures and property counts for the types (and union members) the checks read. */
function typeFacts(file: TsrsFile, flags: TsrsTypeFlags, roots: readonly TsrsType[], withMembers: boolean): TypeFacts {
  const checker = file.checker as unknown as TypeChecker;
  const facts: TypeFacts = { members: new Map(), indexValueFlags: new Map(), propertyCount: new Map() };
  let leaves = [...new Set(roots)];
  if (withMembers) {
    const unions = leaves.filter((type) => type.isUnionType());
    const members = file.batch(unions.map((union) => union.getTypes.gen()));
    unions.forEach((union, i) => facts.members.set(union, members[i] ?? []));
    leaves = [...new Set([...leaves.filter((type) => !type.isUnionType()), ...unions.flatMap((union) => facts.members.get(union) ?? [])])];
  }
  // isBroad decides by flags first; only the others need their index signatures.
  const indexed = leaves.filter((type) => (type.flags & (flags.Unknown | flags.NonPrimitive)) === 0);
  const infos = file.batch(indexed.map((type) => checker.getIndexInfosOfType.gen(type)));
  indexed.forEach((type, i) => facts.indexValueFlags.set(type, (infos[i] ?? []).map((info) => info.valueType.flags)));
  // Property counts matter for an all-unknown index signature (isBroad) and for object types (hasKnownContract).
  const counted = indexed.filter((type) => {
    const indexes = facts.indexValueFlags.get(type) ?? [];
    return (withMembers && (type.flags & flags.Object) !== 0) ||
      (indexes.length > 0 && indexes.every((index) => (index & flags.Unknown) !== 0));
  });
  const properties = file.batch(counted.map((type) => checker.getPropertiesOfType.gen(type)));
  counted.forEach((type, i) => facts.propertyCount.set(type, properties[i]?.length ?? 0));
  return facts;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Report explicit broad return annotations that erase a known return value.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      avoid:
        "This return annotation erases a known value's contract. Return the domain type or retain inference; preserve unknown only at an intentional opaque boundary.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let tsrs: TsrsServices | null = null;
    let stack: Frame[] = [];
    let annotated: Frame[] = [];

    function enter(node: FunctionNode): void {
      const annotation = node.typeParameters == null ? node.returnType ?? null : null;
      const frame: Frame = { node, annotation, values: [] };
      stack.push(frame);
      if (annotation !== null) annotated.push(frame);
      if (node.body && node.body.type !== "BlockStatement") frame.values.push(node.body);
    }

    function leave(): void {
      stack.pop();
    }

    function report(frame: Frame): void {
      const annotation = frame.annotation!;
      const node = frame.node;
      const canFix = node.type === "FunctionDeclaration" && node.id !== null &&
        isUnusedPrivateBinding(sourceCode, node, node.id, context.filename) &&
        sourceCode.getCommentsInside(annotation).length === 0 &&
        retainsNamedTypeUses(sourceCode, annotation);
      context.report({
        node: annotation,
        messageId: "avoid",
        ...(canFix && { fix: (fixer) => fixer.replaceText(annotation, sourceCode.getText(annotation).replace(/[^\r\n]/gu, "")) }),
      });
    }

    function resolve(file: TsrsFile): Frame[] {
      const flags = file.flags;
      const annotationTypes = valueTypes(file, flags, annotated.map((frame) => frame.annotation!.typeAnnotation));
      const present = annotationTypes.filter((type) => type !== undefined);
      const annotationFacts = typeFacts(file, flags, present, false);
      // Frames without returned values can never be known, so they need no value types.
      const broad = annotated.filter((frame, i) => {
        const type = annotationTypes[i];
        return type !== undefined && frame.values.length > 0 && isBroad(type, annotationFacts, flags);
      });
      const values = broad.flatMap((frame) => frame.values);
      const types = valueTypes(file, flags, values);
      const facts = typeFacts(file, flags, types.filter((type) => type !== undefined), true);
      let next = 0;
      return broad.filter((frame) => {
        let known = false;
        let opaque = false;
        for (let i = 0; i < frame.values.length; i++) {
          const type = types[next++];
          // The original calls getTypeAtLocation on every value; a node tsrs cannot map has no type to read.
          if (type === undefined) continue;
          known ||= hasKnownContract(type, facts, flags);
          opaque ||= isOpaque(type, facts, flags);
        }
        return known && !opaque;
      });
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        tsrs = null;
        stack = [];
        annotated = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      FunctionDeclaration: enter,
      FunctionExpression: enter,
      ArrowFunctionExpression: enter,
      "FunctionDeclaration:exit": leave,
      "FunctionExpression:exit": leave,
      "ArrowFunctionExpression:exit": leave,
      ReturnStatement(node) {
        const frame = stack.at(-1);
        if (node.argument && frame?.annotation) frame.values.push(node.argument);
      },
      "Program:exit"() {
        if (annotated.length === 0 || tsrs === null) return;
        const reported = tsrs.run(resolve);
        if (reported === null) return;
        reported.forEach(report);
      },
    };
  },
});
