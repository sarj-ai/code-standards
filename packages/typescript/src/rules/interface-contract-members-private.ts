/**
 * @fileoverview interface-contract-members-private — methods outside an implemented interface contract use ECMAScript private names.
 *
 * Port of the 18.x `interface-contract-members-private` rule. Typed: the
 * original returns no visitors without type information, so without tsrs (or
 * when tsrs cannot hold the file) this port reports nothing. Classes with an
 * `implements` clause are collected during the walk; `Program:exit` asks tsrs
 * for their contracts' property names, then resolves every fix's member
 * symbols in one request (`utils/class-private.ts`) and reports.
 */

import type * as TsrsAst from "tsrs/ast";

import { defineRule, type ESTree } from "../types.js";
import { nativeTypes, type NativeTypes } from "../utils/checked-native-source.js";
import {
  type ClassNode,
  convertibleMemberName,
  isUnobservedPrivateClass,
  type PrivateMemberFixPlan,
  privateMemberFixPlan,
  resolvePrivateMemberFixes,
} from "../utils/class-private.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";

const NAME = "interface-contract-members-private";

function candidate(member: ESTree.MethodDefinition): boolean {
  return (
    member.kind !== "constructor" &&
    !member.static &&
    member.accessibility !== "protected" &&
    !member.override &&
    !member.computed &&
    member.key.type === "Identifier" &&
    member.value.body !== null
  );
}

/** Property names of every implemented contract, or null without one (or when one is any/unknown). */
function interfaceNames(native: NativeTypes, owner: ClassNode): ReadonlySet<string> | null {
  const { ast, checker, sync } = native;
  const tsOwner = native.node(owner);
  if (tsOwner === undefined || (!ast.isClassDeclaration(tsOwner) && !ast.isClassExpression(tsOwner))) return null;
  const clauses: readonly TsrsAst.HeritageClause[] = tsOwner.heritageClauses ?? [];
  const implemented = clauses.filter((clause) => clause.token === ast.SyntaxKind.ImplementsKeyword);
  if (implemented.length === 0) return null;
  const names = new Set<string>();
  for (const clause of implemented) {
    for (const contract of clause.types) {
      const type = checker.getTypeAtLocation(contract);
      if ((type.flags & (sync.TypeFlags.Any | sync.TypeFlags.Unknown)) !== 0) return null;
      for (const property of checker.getPropertiesOfType(type)) names.add(property.name);
    }
  }
  return names;
}

interface Finding {
  readonly key: ESTree.Node;
  readonly name: string;
  readonly plan: PrivateMemberFixPlan | undefined;
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Require methods outside an implemented interface contract to use ECMAScript private names.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      nonContractMemberMustBePrivate:
        "Method `{{name}}` is not part of this class's implemented interface contract; make it `#{{name}}` or declare it in the interface.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let classes: ClassNode[] = [];

    function collect(owner: ClassNode): void {
      // Without an implements clause interfaceNames returns null; skip those classes without asking tsrs.
      if (!owner.abstract && (owner.implements?.length ?? 0) > 0) classes.push(owner);
    }

    function findingsOf(native: NativeTypes, owner: ClassNode): Finding[] {
      const contract = interfaceNames(native, owner);
      if (contract === null) return [];
      const groups = new Map<string, ESTree.MethodDefinition[]>();
      for (const member of owner.body.body) {
        if (member.type !== "MethodDefinition" || !candidate(member)) continue;
        const name = convertibleMemberName(member);
        if (name === null || contract.has(name)) continue;
        // Avoid duplicate diagnostics: the dedicated modern-private rule owns this
        // member and converts it to the same required final form.
        if (member.accessibility === "private" || member.key.type === "PrivateIdentifier") continue;
        const members = groups.get(name) ?? [];
        members.push(member);
        groups.set(name, members);
      }
      if (groups.size === 0) return [];
      const sourceCode = context.sourceCode;
      const unobserved = isUnobservedPrivateClass(sourceCode, owner, context.filename);
      return [...groups].flatMap(([name, members]) => {
        const first = members[0];
        return first === undefined ? [] : [{ key: first.key, name, plan: unobserved ? privateMemberFixPlan(sourceCode, owner, members, false) : undefined }];
      });
    }

    return {
      before() {
        tsrs = null;
        classes = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      ClassDeclaration: collect,
      ClassExpression: collect,
      "Program:exit"() {
        if (classes.length === 0 || tsrs === null) return;
        const resolved = tsrs.run((file) => {
          const native = nativeTypes(file);
          const findings = classes.flatMap((owner) => findingsOf(native, owner));
          return { findings, fixes: resolvePrivateMemberFixes(file, findings.map((finding) => finding.plan)) };
        });
        if (resolved === null) return;
        const { findings, fixes } = resolved;
        findings.forEach((finding, i) => {
          const fix = fixes[i];
          const descriptor = { node: finding.key, messageId: "nonContractMemberMustBePrivate", data: { name: finding.name } };
          context.report(fix === undefined ? descriptor : { ...descriptor, fix });
        });
      },
    };
  },
});
