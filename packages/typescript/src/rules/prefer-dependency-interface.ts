/**
 * @fileoverview prefer-dependency-interface — annotate retained collaborators with their existing interface.
 *
 * Port of the 18.x `prefer-dependency-interface` rule. The rule is untyped, so the port
 * covers all of it.
 *
 * The original requires `typeParameters === undefined` on the owner class, the concrete class and
 * the interface; Oxlint passes `null` for absent fields, so under Oxlint the original never
 * reports. The port accepts both, which matches the original under ESLint.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { forEachOwnAstChild, parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const NAME = "prefer-dependency-interface";

type Identifier = Node & { readonly type: "Identifier"; readonly name: string };

/** `this.dependency.member`, read but not written, where `member` is on the interface. */
function readsInterfaceMember(use: ESTree.MemberExpression, members: ReadonlySet<string>): boolean {
  const parent = parentOf(use);
  if (parent?.type !== "MemberExpression" || parent.object !== use || !members.has(getPropertyName(parent) ?? "")) return false;
  const grandparent = parentOf(parent);
  return !(grandparent?.type === "AssignmentExpression" && grandparent.left === parent) && grandparent?.type !== "UpdateExpression";
}

interface RetainedDependency {
  readonly owner: ESTree.Class;
  readonly name: string;
  readonly annotation: ESTree.TSTypeAnnotation;
  readonly typeName: Identifier;
}

/** `constructor(private readonly name: Type) {}` in an undecorated, non-generic class. */
function retainedDependency(node: ESTree.TSParameterProperty): RetainedDependency | null {
  const parameter = node.parameter as Node;
  if (!node.readonly || node.accessibility !== "private" || node.decorators.length !== 0 || parameter.type !== "Identifier") return null;
  const annotation = parameter.typeAnnotation;
  const reference = annotation?.typeAnnotation;
  if (annotation === null || annotation === undefined || reference?.type !== "TSTypeReference" || reference.typeName.type !== "Identifier") return null;
  const owner = emptyConstructorOwner(node);
  return owner === null ? null : { owner, name: parameter.name, annotation, typeName: reference.typeName };
}

/** The undecorated, non-generic class whose empty constructor declares `node`. */
function emptyConstructorOwner(node: ESTree.TSParameterProperty): ESTree.Class | null {
  const fn = parentOf(node);
  const constructor = fn === null ? null : parentOf(fn);
  if (constructor?.type !== "MethodDefinition" || constructor.kind !== "constructor" || constructor.value.body?.body.length !== 0) return null;
  const body = parentOf(constructor);
  const owner = body === null ? null : parentOf(body);
  if (owner?.type !== "ClassDeclaration" && owner?.type !== "ClassExpression") return null;
  return owner.decorators.length === 0 && !isPresent(owner.typeParameters) ? owner : null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Annotate retained collaborators with their existing interface when the consumer uses only that contract.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { interface: "Use the existing `{{contract}}` interface for this dependency; its consumer uses only that contract." },
  },
  createOnce(context) {
    function contract(node: Identifier): ESTree.TSInterfaceDeclaration | null {
      const concrete = definition(node);
      if (concrete?.type !== "ClassDeclaration" || concrete.abstract || concrete.superClass !== null || concrete.decorators.length !== 0 || isPresent(concrete.typeParameters)) return null;
      const heritage = concrete.implements?.length === 1 ? concrete.implements[0] : undefined;
      if (heritage?.expression.type !== "Identifier") return null;
      const port = definition(heritage.expression);
      return port?.type === "TSInterfaceDeclaration" && port.extends.length === 0 && port.typeParameters === null ? port : null;
    }
    function definition(node: Identifier): Node | null {
      const variable = findVariable(context.sourceCode.getScope(node), node.name);
      return variable?.defs.length === 1 ? variable.defs[0]?.node ?? null : null;
    }
    function usesOnlyInterface(owner: ESTree.Class, name: string, port: ESTree.TSInterfaceDeclaration): boolean {
      const members = new Set<string>();
      for (const member of port.body.body) {
        if ((member.type !== "TSMethodSignature" && member.type !== "TSPropertySignature") || member.computed || member.key.type !== "Identifier") return false;
        members.add(member.key.name);
      }
      let uses = 0;
      let compatible = true;
      function visit(node: Node): void {
        if (node.type === "MemberExpression" && node.object.type === "ThisExpression" && getPropertyName(node) === name) {
          uses += 1;
          if (!readsInterfaceMember(node, members)) compatible = false;
        }
        if (node !== owner && (node.type === "ClassDeclaration" || node.type === "ClassExpression")) return;
        forEachOwnAstChild(node, visit);
      }
      visit(owner);
      return compatible && uses > 0;
    }
    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      TSParameterProperty(node: ESTree.TSParameterProperty): void {
        const dependency = retainedDependency(node);
        if (dependency === null) return;
        const { owner, name, annotation, typeName } = dependency;
        const port = contract(typeName);
        if (port !== null && usesOnlyInterface(owner, name, port)) context.report({ node: annotation, messageId: "interface", data: { contract: port.id.name } });
      },
    };
  },
});
