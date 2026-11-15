/**
 * @fileoverview react-prefer-updater-function — report a React state setter given a value computed from its own state.
 *
 * The setter and state are paired through one `const [state, setState] = useState(...)` destructure whose
 * `useState` resolves to the React import; every read is resolved by scope, never by name. Calls made directly
 * in the declaring function run during render, where the state is the render in progress, so they are skipped.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { importsReactValue, reactHook } from "../utils/react-prop-bindings.js";
import { enclosingFunction, stableValueBinding, typeOnlyReference } from "../utils/stable-value-binding.js";
import { findVariable } from "../utils/static-string.js";

const NAME = "react-prefer-updater-function";

interface StateBinding {
  readonly state: TsVariable;
  readonly owner: ESTree.Function | ESTree.ArrowFunctionExpression | null;
}

function stateForSetter(source: SourceCode, setter: TsVariable): StateBinding | null {
  const declarator = setter.defs[0]?.node;
  if (setter.defs.length !== 1 || declarator?.type !== "VariableDeclarator" ||
    declarator.id.type !== "ArrayPattern" || declarator.init === null) return null;
  const [value, update] = declarator.id.elements;
  const call = unwrapExpression(declarator.init);
  if (value?.type !== "Identifier" || update?.type !== "Identifier" || !setter.identifiers.includes(update) ||
    call.type !== "CallExpression" || !reactHook(source, call.callee, "useState") ||
    !stableValueBinding(setter)) return null;
  const state = (source.getDeclaredVariables(declarator) as TsVariable[])
    .find((variable) => variable.identifiers.includes(value));
  return state !== undefined && stableValueBinding(state) ? { state, owner: enclosingFunction(declarator) } : null;
}

function readsStateEagerly(state: TsVariable, argument: Node): boolean {
  return state.references.some((reference) =>
    reference.isRead() && !typeOnlyReference(reference) && evaluatedBy(reference.identifier, argument));
}

function evaluatedBy(node: Node, argument: Node): boolean {
  for (let current: Node | null = node; current !== null && !isFunction(current); current = parentOf(current)) {
    if (current === argument) return true;
  }
  return false;
}

function isFunction(node: Node): boolean {
  return node.type === "ArrowFunctionExpression" || node.type === "FunctionExpression" || node.type === "FunctionDeclaration";
}

export default defineRule({
  meta: {
    type: "problem",
    docs: { description: "Use the updater form when the next React state is built from the current state.", url: docsUrl(NAME) },
    schema: [],
    messages: {
      preferUpdaterFunction:
        "`{{setter}}` builds the next state from the `{{state}}` snapshot, which is stale after an await, in timers and effects, or when two updates run before a re-render. Pass an updater: `{{setter}}((previous) => ...)`, reading `previous` wherever the argument read `{{state}}` or a value derived from it. Compute impure values such as IDs or timestamps before the call so the updater stays pure.",
    },
  },
  createOnce(context) {
    return {
      before() {
        const source = context.sourceCode;
        return !isGeneratedFile({ filename: context.filename, cwd: context.cwd }, source.text) && importsReactValue(source);
      },
      CallExpression(node) {
        const [argument] = node.arguments;
        const callee = unwrapExpression(node.callee);
        if (node.arguments.length !== 1 || argument === undefined || argument.type === "SpreadElement" ||
          callee.type !== "Identifier") return;
        const value = unwrapExpression(argument);
        if (value.type === "Identifier" || isFunction(value)) return;
        const source = context.sourceCode;
        const setter = findVariable(source.getScope(callee), callee.name);
        const binding = setter === null ? null : stateForSetter(source, setter);
        if (setter === null || binding === null || enclosingFunction(node) === binding.owner ||
          !readsStateEagerly(binding.state, argument)) return;
        context.report({ node, messageId: "preferUpdaterFunction", data: { setter: setter.name, state: binding.state.name } });
      },
    };
  },
});
