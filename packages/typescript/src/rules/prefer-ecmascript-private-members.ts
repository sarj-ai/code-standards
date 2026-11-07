/**
 * @fileoverview prefer-ecmascript-private-members — prefer runtime-enforced ECMAScript privacy to TypeScript-only `private`.
 *
 * Port of the 18.x `prefer-ecmascript-private-members` rule. Typed: the
 * original returns no visitors without type information, so without tsrs (or
 * when tsrs cannot hold the file) this port reports nothing. Classes are
 * collected during the walk; `Program:exit` resolves every fix's member
 * symbols in one tsrs request, then reports.
 */

import { defineRule, type ESTree } from "../types.js";
import {
  type ClassNode,
  convertibleMemberName,
  isUnobservedPrivateClass,
  type PrivateConvertibleMember,
  type PrivateMemberFixPlan,
  privateMemberFixPlan,
  resolvePrivateMemberFixes,
} from "../utils/class-private.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import type { TsrsServices } from "../utils/tsrs-services.js";
import { tsrsServices } from "../utils/tsrs-services.js";

const NAME = "prefer-ecmascript-private-members";

function isConvertible(member: PrivateConvertibleMember): boolean {
  return (
    member.accessibility === "private" &&
    !(member.type === "MethodDefinition" && member.kind === "constructor") &&
    !member.computed &&
    member.key.type === "Identifier" &&
    (member.decorators?.length ?? 0) === 0 &&
    !("declare" in member && member.declare) &&
    !member.override &&
    !(member.type === "MethodDefinition" && (member.value.body ?? null) === null)
  );
}

interface Finding {
  readonly key: ESTree.Node;
  readonly name: string;
  readonly plan: PrivateMemberFixPlan | undefined;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Prefer ECMAScript `#private` class members over TypeScript-only `private` members.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferEcmascriptPrivate:
        "TypeScript `private {{name}}` is erased at runtime; use the ECMAScript private name `#{{name}}`.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let findings: Finding[] = [];

    function collectClass(owner: ClassNode): void {
      const groups = new Map<string, PrivateConvertibleMember[]>();
      for (const member of owner.body.body) {
        if ((member.type !== "MethodDefinition" && member.type !== "PropertyDefinition" && member.type !== "AccessorProperty") ||
          !isConvertible(member)) continue;
        const name = convertibleMemberName(member);
        if (name === null) continue;
        const members = groups.get(name) ?? [];
        members.push(member);
        groups.set(name, members);
      }
      if (groups.size === 0) return;
      const sourceCode = context.sourceCode;
      const unobserved = isUnobservedPrivateClass(sourceCode, owner, context.filename);
      for (const [name, members] of groups) {
        const first = members[0];
        if (first === undefined) continue;
        findings.push({ key: first.key, name, plan: unobserved ? privateMemberFixPlan(sourceCode, owner, members, true) : undefined });
      }
    }

    return {
      before() {
        findings = [];
        tsrs = null;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      ClassDeclaration: collectClass,
      ClassExpression: collectClass,
      "Program:exit"() {
        if (findings.length === 0 || tsrs === null) return;
        const fixes = tsrs.run((file) => resolvePrivateMemberFixes(file, findings.map((finding) => finding.plan)));
        if (fixes === null) return;
        findings.forEach((finding, i) => {
          const fix = fixes[i];
          const descriptor = { node: finding.key, messageId: "preferEcmascriptPrivate", data: { name: finding.name } };
          context.report(fix === undefined ? descriptor : { ...descriptor, fix });
        });
      },
    };
  },
});
