/**
 * @fileoverview prefer-nullish-filter-predicate — `filter(Boolean)` does not narrow a nullish union even when every retained value is provably truthy.
 *
 * Port of the 18.x `prefer-nullish-filter-predicate` rule. Typed: the
 * original returns no visitors without type information, so without tsrs (or
 * when tsrs cannot hold the file) this port reports nothing. The walk collects
 * `filter(Boolean)` calls; `Program:exit` asks tsrs for their filter symbols
 * and receiver types in one batched request, then checks each candidate.
 */

import type { Symbol as TsSymbol, Type } from "tsrs/sync";

import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { nativeTypes, type NativeTypes } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";

const NAME = "prefer-nullish-filter-predicate";
const SUMMARY =
  "Prefer an explicit nullish predicate when `filter(Boolean)` removes only nullish values but does not narrow the result type.";

interface Candidate {
  readonly node: ESTree.CallExpression;
  readonly callee: ESTree.MemberExpression;
  readonly callback: ESTree.IdentifierReference;
}

/** Whether a declaration of `filter` is a member of the default library's Array or ReadonlyArray interface. */
function isBuiltinArrayFilter(native: NativeTypes, symbol: TsSymbol | undefined): boolean {
  const kinds = native.ast.SyntaxKind;
  return symbol?.declarations.some((declaration) => {
    const owner = declaration.resolve()?.parent;
    if (owner === undefined || owner.kind !== kinds.InterfaceDeclaration) return false;
    const name = (owner as unknown as { readonly name: { readonly text: string } }).name.text;
    return (name === "Array" || name === "ReadonlyArray") &&
      native.program.getSourceFileMetadataByPath(declaration.path)?.isDefaultLibrary === true;
  }) ?? false;
}

interface TruthContext {
  readonly native: NativeTypes;
  readonly falsyBrowserObject: Type | null;
  readonly primitives: readonly Type[];
}

function isNullishPlusTruthy(type: Type, truth: TruthContext): boolean {
  const flags = truth.native.sync.TypeFlags;
  const members = type.isUnionType() ? type.getTypes() : [type];
  let sawNullish = false;
  for (const member of members) {
    if ((member.flags & (flags.Null | flags.Undefined)) !== 0) {
      sawNullish = true;
    } else if ((member.flags & flags.Never) === 0 && !isProvablyTruthy(member, truth)) {
      return false;
    }
  }
  return sawNullish;
}

function isProvablyTruthy(type: Type, truth: TruthContext): boolean {
  const flags = truth.native.sync.TypeFlags;
  const checker = truth.native.checker;
  const unknown = flags.Any | flags.Unknown | flags.TypeParameter | flags.Intersection | flags.Enum | flags.EnumLiteral;
  if ((type.flags & unknown) !== 0) return false;
  if ((type.flags & flags.Object) !== 0) {
    if (truth.falsyBrowserObject !== null && checker.isTypeAssignableTo(truth.falsyBrowserObject, type)) return false;
    return !truth.primitives.some((primitive) => checker.isTypeAssignableTo(primitive, type));
  }
  if ((type.flags & (flags.ESSymbol | flags.UniqueESSymbol)) !== 0) return true;
  // TypeScript names boolean literals by intrinsicName; tsrs gives the value.
  if ((type.flags & flags.BooleanLiteral) !== 0) return (type as Type & { readonly value: unknown }).value === true;
  if ((type.flags & flags.StringLiteral) !== 0) return String((type as Type & { readonly value: unknown }).value).length > 0;
  if ((type.flags & flags.NumberLiteral) !== 0) {
    const value = Number((type as Type & { readonly value: unknown }).value);
    return value !== 0 && !Number.isNaN(value);
  }
  if ((type.flags & flags.BigIntLiteral) !== 0) {
    return BigInt(String((type as Type & { readonly value: unknown }).value)) !== 0n;
  }
  return false;
}

function isLiteralValue(node: Node): boolean {
  if (node.type === "Literal") return !("regex" in node);
  if (node.type === "ArrayExpression") {
    return node.elements.every((element) => element !== null && isLiteralValue(element));
  }
  return node.type === "ObjectExpression" && node.properties.every((property) =>
    property.type === "Property" && !property.computed && !property.method &&
    property.kind === "init" && isLiteralValue(property.value),
  );
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: { description: SUMMARY, url: docsUrl(NAME) },
    hasSuggestions: true,
    fixable: "code",
    schema: [],
    messages: {
      preferNullishPredicate:
        "This built-in array contains only nullish or provably truthy values, so `filter(Boolean)` preserves runtime values but loses nullish narrowing. Use an explicit nullish predicate.",
      replaceBoolean: "Replace `Boolean` with an explicit nullish predicate.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: Candidate[] = [];

    function isUnshadowedBoolean(node: ESTree.IdentifierReference): boolean {
      const variable = findVariable(context.sourceCode.getScope(node), node.name);
      return variable === null || variable.defs.length === 0;
    }

    function report({ node, callee, callback }: Candidate): void {
      const parameter = availableParameterName(node);
      const undefinedBinding = findVariable(context.sourceCode.getScope(node), "undefined");
      const undefinedCheck = (undefinedBinding?.defs.length ?? 0) > 0 ? `typeof ${parameter} !== "undefined"` : `${parameter} !== undefined`;
      const replacement = `(${parameter}) => ${parameter} !== null && ${undefinedCheck}`;
      context.report({
        node: callback,
        messageId: "preferNullishPredicate",
        ...(hasFreshArrayReceiver(node, callee.object) && { fix: (fixer) => fixer.replaceText(callback, replacement) }),
        suggest: [{ messageId: "replaceBoolean", fix: (fixer) => fixer.replaceText(callback, replacement) }],
      });
    }

    function hasFreshArrayReceiver(node: ESTree.CallExpression, receiver: Node): boolean {
      if (receiver.type !== "ArrayExpression" || !isLiteralValue(receiver)) return false;
      const statements = context.sourceCode.ast.body;
      if (statements.length !== 1) return false;
      const statement = statements[0];
      if (statement?.type === "ExpressionStatement") return statement.expression === node;
      return statement?.type === "VariableDeclaration" &&
        statement.kind === "const" && statement.declarations.length === 1 &&
        statement.declarations[0]?.id.type === "Identifier" &&
        statement.declarations[0]?.init === node;
    }

    function availableParameterName(node: Node): string {
      const scope = context.sourceCode.getScope(node);
      for (const name of ["value", "item", "element", "candidate"] as const) {
        if (findVariable(scope, name) === null) return name;
      }
      let suffix = 1;
      while (findVariable(scope, `value${String(suffix)}`) !== null) suffix += 1;
      return `value${String(suffix)}`;
    }

    function resolve(native: NativeTypes): boolean[] {
      const { checker, file } = native;
      const symbols = file.symbolsOf(candidates.map((candidate) => candidate.callee.property)) as (TsSymbol | undefined)[];
      const receivers = file.typesOf(candidates.map((candidate) => candidate.callee.object)) as (Type | undefined)[];
      const builtin = candidates.map((_, i) =>
        isBuiltinArrayFilter(native, symbols[i] ?? receivers[i]?.getProperty("filter")));
      if (!builtin.includes(true)) return builtin;
      const typeFlag = native.sync.SymbolFlags.Type;
      const browserCollection = checker.resolveName("HTMLAllCollection", typeFlag, undefined, false);
      const falsyBrowserObject = browserCollection?.declarations.some((declaration) =>
        native.program.getSourceFileMetadataByPath(declaration.path)?.isDefaultLibrary === true) === true
        ? checker.getDeclaredTypeOfSymbol(browserCollection) : null;
      const truth: TruthContext = {
        native,
        falsyBrowserObject,
        primitives: [checker.getStringType(), checker.getNumberType(), checker.getBigIntType(), checker.getBooleanType()],
      };
      return builtin.map((isBuiltin, i) => {
        const receiver = receivers[i];
        if (!isBuiltin || receiver === undefined) return false;
        const elementType = checker.getIndexTypeOfType(receiver, native.sync.IndexKind.Number);
        return elementType !== undefined && isNullishPlusTruthy(elementType, truth);
      });
    }

    return {
      before() {
        tsrs = null;
        candidates = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      CallExpression(node) {
        const callee = unwrapExpression(node.callee);
        const callback = node.arguments[0] === undefined ? undefined : unwrapExpression(node.arguments[0]);
        if (
          node.arguments.length !== 1 ||
          callback?.type !== "Identifier" ||
          callback.name !== "Boolean" ||
          callee.type !== "MemberExpression" ||
          getPropertyName(callee) !== "filter" ||
          !isUnshadowedBoolean(callback as ESTree.IdentifierReference)
        ) return;
        candidates.push({ node, callee, callback: callback as ESTree.IdentifierReference });
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        const found = tsrs.run((file) => resolve(nativeTypes(file)));
        if (found === null) return;
        candidates.forEach((candidate, i) => {
          if (found[i] === true) report(candidate);
        });
      },
    };
  },
});
