/** @fileoverview prefer-coordinated-react-state — review complete repeated setter groups with a shared record witness. */

import type { Type } from "tsrs/sync";

import {
  defineRule,
  type Context,
  type ESTree,
  type Identifier,
  type Node,
  type SourceCode,
  type TsVariable,
} from "../types.js";
import { forEachOwnAstChild, outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { nativeTypes } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { importsReactValue, reactHook } from "../utils/react-prop-bindings.js";
import {
  enclosingFunction,
  stableValueBinding,
  typeOnlyReference,
} from "../utils/stable-value-binding.js";
import { findVariable } from "../utils/static-string.js";
import { hasIdentifierNamed } from "../utils/unused-private-binding.js";
import { tsrsServices } from "../utils/tsrs-services.js";
import { isPrimitiveType } from "./no-readonly-prop-state.js";

const NAME = "prefer-coordinated-react-state";
const MAX_NODES = 4096;
const MAX_STATES = 16;
const MAX_REFERENCES = 32;
const MAX_SOURCE_LENGTH = 200_000;
const MAX_PATH_DEPTH = 8;

type Owner = ESTree.ArrowFunctionExpression | ESTree.Function;
interface Slot {
  readonly owner: Owner;
  readonly value: Identifier;
  readonly setter: TsVariable;
  readonly initial: Node | null;
}
interface Write {
  readonly slot: Slot;
  readonly statement: ESTree.ExpressionStatement;
  readonly block: ESTree.BlockStatement;
  readonly argument: ESTree.Expression;
}
interface Participant {
  readonly slot: Slot;
  readonly writes: readonly Write[];
}

function stateSlot(source: SourceCode, call: ESTree.CallExpression): Slot | null {
  if (call.optional || call.arguments.length > 1 || !reactHook(source, call.callee, "useState"))
    return null;
  const declaration = parentOf(outerExpression(call));
  const statement = declaration === null ? null : parentOf(declaration);
  if (
    declaration?.type !== "VariableDeclarator" ||
    statement?.type !== "VariableDeclaration" ||
    statement.kind !== "const" ||
    declaration.id.type !== "ArrayPattern" ||
    declaration.id.elements.length !== 2
  )
    return null;
  const [value, setter] = declaration.id.elements;
  if (value?.type !== "Identifier" || setter?.type !== "Identifier") return null;
  const owner = enclosingFunction(call);
  if (owner === null || parentOf(statement) !== owner.body) return null;
  const variables = source.getDeclaredVariables(declaration) as TsVariable[];
  const state = variables.find((variable) => variable.identifiers.includes(value));
  const update = variables.find((variable) => variable.identifiers.includes(setter));
  if (
    state === undefined ||
    update === undefined ||
    !stableValueBinding(state) ||
    !stableValueBinding(update) ||
    !state.references.some((reference) => reference.isRead() && !typeOnlyReference(reference))
  )
    return null;
  return { owner, value, setter: update, initial: call.arguments[0] ?? null };
}

/** Bound the whole file before reporting, including syntactically unsupported subtrees. */
function boundedNodes(root: Node): boolean {
  const pending = [root];
  let visited = 0;
  while (pending.length > 0) {
    const node = pending.pop()!;
    if (++visited > MAX_NODES) return false;
    forEachOwnAstChild(
      node,
      (child) => {
        pending.push(child);
      },
      (key) => key !== "tokens" && key !== "comments",
    );
    if (pending.length + visited > MAX_NODES) return false;
  }
  return true;
}

/** No invocation, deferred updater, mutation or suspension is treated as a direct record adoption. */
function supportedArgument(input: Node, depth = 0): boolean {
  if (depth >= MAX_PATH_DEPTH) return false;
  const node = unwrapExpression(input);
  switch (node.type) {
    case "Identifier":
    case "Literal":
      return true;
    case "UnaryExpression":
      return (
        ["-", "+", "!", "void"].includes(node.operator) &&
        supportedArgument(node.argument, depth + 1)
      );
    case "MemberExpression":
      return !node.optional && !node.computed && supportedArgument(node.object, depth + 1);
    case "ArrayExpression":
      return node.elements.every(
        (element) => element === null || supportedArgument(element, depth + 1),
      );
    case "ObjectExpression":
      return node.properties.every(
        (property) =>
          property.type === "Property" &&
          property.kind === "init" &&
          !property.method &&
          !property.computed &&
          supportedArgument(property.value, depth + 1),
      );
    default:
      return false;
  }
}

function setterWrites(slot: Slot): readonly Write[] | null {
  if (slot.setter.references.length > MAX_REFERENCES) return null;
  const writes: Write[] = [];
  for (const reference of slot.setter.references) {
    if (
      typeOnlyReference(reference) ||
      (reference.init === true && reference.isWrite() && !reference.isRead())
    )
      continue;
    const callee = outerExpression(reference.identifier);
    const call = parentOf(callee);
    if (
      call?.type !== "CallExpression" ||
      call.optional ||
      call.callee !== callee ||
      call.arguments.length !== 1
    )
      return null;
    const statement = parentOf(call);
    const block = statement === null ? null : parentOf(statement);
    const argument = call.arguments[0];
    if (
      statement?.type !== "ExpressionStatement" ||
      statement.expression !== call ||
      block?.type !== "BlockStatement" ||
      argument === undefined ||
      argument.type === "SpreadElement" ||
      !supportedArgument(argument)
    )
      return null;
    writes.push({ slot, statement, block, argument });
  }
  return writes.length > 0 ? writes : null;
}

function writeRuns(participants: readonly Participant[]): readonly (readonly Write[])[] {
  const operations = new Map(
    participants.flatMap(({ writes }) => writes.map((write) => [write.statement, write] as const)),
  );
  const blocks = new Set([...operations.values()].map(({ block }) => block));
  const runs: Write[][] = [];
  for (const block of blocks) {
    let run: Write[] = [];
    for (const statement of block.body) {
      const write = operations.get(statement as ESTree.ExpressionStatement);
      if (write === undefined || run.some(({ slot }) => slot === write.slot)) {
        if (run.length > 0) runs.push(run);
        run = [];
      }
      if (write !== undefined) run.push(write);
    }
    if (run.length > 0) runs.push(run);
  }
  return runs;
}

/** Resolve a stable local binding, not the values or purity of its properties. */
function recordRoot(input: Node, source: SourceCode, transition: Owner | null): TsVariable | null {
  let node = unwrapExpression(input);
  if (node.type !== "MemberExpression" || transition === null) return null;
  for (let depth = 0; depth < MAX_PATH_DEPTH; depth += 1) {
    if (node.type === "Identifier") return localRecordBinding(source, node, transition);
    if (node.type !== "MemberExpression" || node.optional || node.computed) return null;
    node = unwrapExpression(node.object);
  }
  return null;
}

function localRecordBinding(
  source: SourceCode,
  node: Identifier,
  transition: Owner,
): TsVariable | null {
  const variable = findVariable(source.getScope(node), node.name);
  if (variable === null || variable.defs.length !== 1 || !stableValueBinding(variable)) return null;
  const definition = variable.defs[0]!;
  if (definition.type === "Parameter")
    return source.getDeclaredVariables(transition).includes(variable) ? variable : null;
  const declaration = definition.node;
  const parent = parentOf(declaration);
  return declaration.type === "VariableDeclarator" &&
    source.getDeclaredVariables(declaration).includes(variable) &&
    parent?.type === "VariableDeclaration" &&
    parent.kind === "const" &&
    declaration.init !== null &&
    declaration.range[1] < node.range[0] &&
    enclosingFunction(declaration) === transition
    ? variable
    : null;
}

function witnessedGroup(
  group: readonly Slot[],
  sites: readonly number[],
  runs: readonly (readonly Write[])[],
  source: SourceCode,
): boolean {
  const slots = new Set(group);
  if (new Set(sites.map((site) => enclosingFunction(runs[site]![0]!.statement))).size < 2)
    return false;
  return sites.some((site) => {
    const writes = runs[site]!.filter(({ slot }) => slots.has(slot));
    const roots = writes.map(({ argument, statement }) =>
      recordRoot(argument, source, enclosingFunction(statement)),
    );
    return roots[0] !== null && roots.every((root) => root === roots[0]);
  });
}

/** A copied draft and its retained value share an explicitly written status, with no solo writes. */
function copiedSnapshotGroups(
  participants: readonly Participant[],
  runs: readonly (readonly Write[])[],
  source: SourceCode,
  sitesByWrite: ReadonlyMap<Write, number>,
): readonly Slot[][] {
  const groups: Slot[][] = [];
  for (const status of participants) {
    if (status.writes.length !== 2 || readBooleanLiteral(status.slot.initial) === null) continue;
    const sites = status.writes.map((write) => sitesByWrite.get(write) ?? -1);
    if (
      sites.some((site) => site < 0 || runs[site]!.length !== 2) ||
      new Set(sites.map((site) => enclosingFunction(runs[site]![0]!.statement))).size !== 2
    )
      continue;
    const leaves = sites.map((site) => runs[site]!.find(({ slot }) => slot !== status.slot)!.slot);
    const [left, right] = leaves;
    if (
      left === undefined ||
      right === undefined ||
      left === right ||
      left.owner !== status.slot.owner ||
      right.owner !== left.owner
    )
      continue;
    if (!copiedInitialValue(left, right, source) && !copiedInitialValue(right, left, source))
      continue;
    if (
      leaves.some(
        (slot) =>
          participants.find((participant) => participant.slot === slot)?.writes.length !== 1,
      )
    )
      continue;
    const first = readBooleanLiteral(status.writes[0]!.argument);
    const second = readBooleanLiteral(status.writes[1]!.argument);
    if (first === null || second === null || first === second) continue;
    groups.push([left, right, status.slot]);
  }
  return groups;
}

function readBooleanLiteral(input: Node | null): boolean | null {
  const node = input === null ? null : unwrapExpression(input);
  return node?.type === "Literal" && typeof node.value === "boolean" ? node.value : null;
}

function copiedInitialValue(left: Slot, right: Slot, source: SourceCode): boolean {
  const initial = left.initial === null ? null : unwrapExpression(left.initial);
  return (
    initial?.type === "Identifier" &&
    initial.name === right.value.name &&
    findVariable(source.getScope(initial), initial.name) ===
      findVariable(source.getScope(right.value), right.value.name)
  );
}

function primitiveSnapshotGroups(groups: readonly Slot[][], context: Context): readonly Slot[][] {
  if (groups.length === 0) return [];
  const candidates = groups.flatMap((group) => {
    const [left, right] = group;
    if (left === undefined || right === undefined) return [];
    const initial = copiedInitialValue(left, right, context.sourceCode)
      ? right.initial
      : left.initial;
    return initial === null ? [] : [{ group, initial }];
  });
  if (candidates.length === 0) return [];
  return (
    tsrsServices(context)?.run((file) => {
      const native = nativeTypes(file);
      const types = file.typesOf(candidates.map(({ initial }) => initial)) as (Type | undefined)[];
      return candidates.flatMap(({ group }, index) => {
        const type = types[index];
        return type !== undefined && isPrimitiveType(native, type) ? [group] : [];
      });
    }) ?? []
  );
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Review repeated setter groups adopting fields from one incoming record.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      copiedSnapshotState:
        "`{{fields}}` contain a copied initial state and retained value, each updated beside the same boolean status in separate handlers. Review one typed editor snapshot to keep draft, retained data and status transitions explicit. Preserve asynchronous completion and queued writes; no automatic rewrite or runtime-race claim.",
      preferCoordinatedReactState:
        "`{{fields}}` have complete adjacent setter groups at lines {{sites}}, including fields read from one local record. Review one typed snapshot owner to remove repeated bookkeeping. Independent lifetimes, retained data and getters require review; these writes do not establish a runtime race.",
    },
  },
  createOnce(context) {
    const slots: Slot[] = [];
    let exceeded = false;
    return {
      before() {
        slots.length = 0;
        exceeded = false;
        const source = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd };
        return (
          source.text.length <= MAX_SOURCE_LENGTH &&
          !isTestFile(file) &&
          !isGeneratedFile(file, source.text) &&
          importsReactValue(source)
        );
      },
      CallExpression(node) {
        if (exceeded) return;
        const slot = stateSlot(context.sourceCode, node);
        if (slot === null) return;
        slots.push(slot);
        exceeded = slots.length > MAX_STATES;
      },
      "Program:exit"() {
        const source = context.sourceCode;
        if (
          exceeded ||
          slots.length < 2 ||
          !boundedNodes(source.ast) ||
          hasIdentifierNamed(source, "eval")
        )
          return;
        const participants = slots.flatMap((slot): Participant[] => {
          const writes = setterWrites(slot);
          return writes === null ? [] : [{ slot, writes }];
        });
        const runs = writeRuns(participants);
        const sitesByWrite = new Map(
          runs.flatMap((run, site) => run.map((write) => [write, site] as const)),
        );
        const groups = new Map<
          string,
          { readonly slots: Slot[]; readonly sites: readonly number[] }
        >();
        for (const { slot, writes } of participants) {
          const sites = writes
            .map((write) => sitesByWrite.get(write) ?? -1)
            .sort((left, right) => left - right);
          const key = `${slot.owner.range[0]}:${sites.join(",")}`;
          const group = groups.get(key);
          if (group === undefined) groups.set(key, { slots: [slot], sites });
          else group.slots.push(slot);
        }
        const snapshots = primitiveSnapshotGroups(
          copiedSnapshotGroups(participants, runs, source, sitesByWrite),
          context,
        );
        for (const { slots: group, sites } of groups.values()) {
          if (group.length < 2 || !witnessedGroup(group, sites, runs, source)) continue;
          const first = group[0]!;
          context.report({
            node: first.value,
            messageId: "preferCoordinatedReactState",
            data: {
              fields: group.map(({ value }) => value.name).join("`, `"),
              sites: sites
                .map(
                  (site) =>
                    runs[site]!.find(({ slot }) => slot === first)!.statement.loc.start.line,
                )
                .sort((left, right) => left - right)
                .join(", "),
            },
          });
        }
        for (const group of snapshots) {
          context.report({
            node: group[0]!.value,
            messageId: "copiedSnapshotState",
            data: {
              fields: group.map(({ value }) => value.name).join("`, `"),
            },
          });
        }
      },
    };
  },
});
