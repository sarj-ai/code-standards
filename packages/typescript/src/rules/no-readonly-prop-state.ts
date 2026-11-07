/**
 * @fileoverview no-readonly-prop-state — review unmodified React state initialized from props.
 *
 * Port of the 18.x `no-readonly-prop-state` rule. Lazy initializers
 * report without types. An eager initializer needs a primitive type: without
 * tsrs types it is skipped, as the original skips it without a program; with
 * them, `Program:exit` asks tsrs for every pending initializer at once.
 */

import type { Type } from "tsrs/sync";

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { nativeTypes, type NativeTypes } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { firstParameterBindings, parameterPath, reactHook, renderFunction } from "../utils/react-prop-bindings.js";
import { stableValueBinding, typeOnlyReference } from "../utils/stable-value-binding.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";

const NAME = "no-readonly-prop-state";
const MAX_TYPE_DEPTH = 16;

/** A one-argument `const [state, setState?] = useState(...)` whose setter is never read. */
function isReadonlyUseState(source: SourceCode, node: ESTree.CallExpression): boolean {
  if (node.optional || node.arguments.length !== 1 || !reactHook(source, node.callee, "useState")) return false;
  const declaration = parentOf(outerExpression(node));
  return declaration?.type === "VariableDeclarator" && (parentOf(declaration) as ESTree.VariableDeclaration).kind === "const" &&
    hasReadonlyStateBinding(source, declaration);
}

function hasReadonlyStateBinding(source: SourceCode, declaration: ESTree.VariableDeclarator): boolean {
  if (declaration.id.type !== "ArrayPattern" || declaration.id.elements.length > 2) return false;
  const [value, setter] = declaration.id.elements;
  if (value?.type !== "Identifier" || (setter != null && setter.type !== "Identifier")) return false;
  const variables = source.getDeclaredVariables(declaration) as TsVariable[];
  const state = variables.find((variable) => variable.identifiers.includes(value));
  if (state === undefined || !stableValueBinding(state) ||
    !state.references.some((reference) => reference.isRead() && !typeOnlyReference(reference))) return false;
  return setter == null || isUnusedUpdater(variables.find((variable) => variable.identifiers.includes(setter)));
}

function isUnusedUpdater(updater: TsVariable | undefined): boolean {
  return updater !== undefined && stableValueBinding(updater) && !updater.eslintUsed &&
    !updater.references.some((reference) => !typeOnlyReference(reference) && reference.isRead());
}

function initializerValue(input: Node): Node | null {
  const node = unwrapExpression(input);
  if (node.type !== "ArrowFunctionExpression" && node.type !== "FunctionExpression") return node;
  if (node.async || node.generator || node.params.length !== 0) return null;
  const body = node.body as ESTree.FunctionBody | ESTree.Expression;
  if (body.type !== "BlockStatement") return body;
  const [statement] = body.body;
  return body.body.length === 1 && statement?.type === "ReturnStatement" ? statement.argument : null;
}

function isPrimitiveType(native: NativeTypes, type: Type, depth = 0): boolean {
  if (depth >= MAX_TYPE_DEPTH) return false;
  const flags = native.sync.TypeFlags;
  if (type.isIntersectionType()) {
    return type.getCallSignatures().length === 0 && type.getConstructSignatures().length === 0 &&
      type.getTypes().some((member) => isPrimitiveType(native, member, depth + 1));
  }
  const primitive = flags.StringLike | flags.NumberLike | flags.BigIntLike | flags.BooleanLike | flags.ESSymbolLike |
    flags.Null | flags.Undefined;
  return type.isUnionType()
    ? type.getTypes().every((member) => isPrimitiveType(native, member, depth + 1))
    : (type.flags & primitive) !== 0;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: { description: "Review props copied into state without a usable updater.", url: docsUrl(NAME) },
    schema: [],
    messages: {
      readonlyPropState:
        "This prop is copied into state without an observed updater. Derive it from current props, or make an intentional initial snapshot explicit; review the lifecycle before changing it.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    // Eager initializers wait for one batched type request in Program:exit.
    let pending: { readonly node: ESTree.CallExpression; readonly initial: Node }[] = [];
    return {
      before() {
        tsrs = null;
        pending = [];
        const source = context.sourceCode;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, source.text) ||
          isTestFile({ filename: context.filename, cwd: context.cwd }) ||
          !source.ast.body.some((statement) =>
            statement.type === "ImportDeclaration" && statement.source.value === "react" && statement.importKind !== "type")) return false;
        tsrs = tsrsServices(context);
        return true;
      },
      CallExpression(node) {
        const source = context.sourceCode;
        if (!isReadonlyUseState(source, node)) return;
        const component = renderFunction(node);
        const argument = node.arguments[0];
        if (component === null || argument === undefined || argument.type === "SpreadElement") return;
        const initial = initializerValue(argument);
        if (initial === null || !parameterPath(source, initial, firstParameterBindings(source, component))) return;
        const lazy = unwrapExpression(argument);
        if (lazy.type === "ArrowFunctionExpression" || lazy.type === "FunctionExpression") {
          context.report({ node, messageId: "readonlyPropState" });
        } else if (tsrs !== null) {
          pending.push({ node, initial });
        }
      },
      "Program:exit"() {
        if (pending.length === 0 || tsrs === null) return;
        const primitive = tsrs.run((file) => {
          const native = nativeTypes(file);
          const types = native.file.typesOf(pending.map(({ initial }) => initial)) as (Type | undefined)[];
          return types.map((type) => type !== undefined && isPrimitiveType(native, type));
        });
        if (primitive === null) return;
        pending.forEach(({ node }, i) => {
          if (primitive[i] === true) context.report({ node, messageId: "readonlyPropState" });
        });
      },
    };
  },
});
