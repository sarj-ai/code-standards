import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

import { createConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const SECURITY_RULES = new Set([
  "security/detect-bidi-characters",
  "security/detect-child-process",
  "no-unsanitized/method",
  "no-unsanitized/property",
]);
type ConfigFactory = (options: { projectService: false }) => Linter.Config[];
const CONFIG_FACTORY = createConfig as unknown as ConfigFactory;

async function findings(source: string): Promise<string[]> {
  const eslint = new ESLint({
    overrideConfigFile: true,
    overrideConfig: CONFIG_FACTORY({ projectService: false }),
  });
  const results = await eslint.lintText(source, { filePath: "src/security-probe.js" });
  expect(results.flatMap((result) => result.messages).filter((message) => message.fatal)).toEqual([]);
  return results.flatMap((result) => result.messages).flatMap((message) => message.ruleId !== null && SECURITY_RULES.has(message.ruleId) ? [message.ruleId] : []);
}

describe("security checks in the shipped preset", () => {
  it.each([
    ["property", "element.innerHTML = location.hash;", "no-unsanitized/property"],
    ["outer property", "element.outerHTML = suppliedHtml;", "no-unsanitized/property"],
    ["HTML insertion", "element.insertAdjacentHTML('beforeend', suppliedHtml);", "no-unsanitized/method"],
    ["shell execution", "import { exec } from 'node:child_process'; exec(command);", "security/detect-child-process"],
    ["aliased shell execution", "import { exec as run } from 'node:child_process'; run(command);", "security/detect-child-process"],
    ["bidirectional source", "// hidden " + String.fromCodePoint(0x202e) + " source\nconst value = 1;", "security/detect-bidi-characters"],
  ])("flags %s", async (_label, source, rule) => {
    expect(await findings(source)).toEqual([rule]);
  });

  it.each([
    ["literal HTML", "element.innerHTML = '<p>Static</p>';"],
    ["text output", "element.textContent = suppliedText;"],
    ["sanitized HTML", "element.innerHTML = DOMPurify.sanitize(suppliedHtml);"],
    ["sanitized insertion", "element.insertAdjacentHTML('beforeend', DOMPurify.sanitize(suppliedHtml));"],
    ["literal command", "import { exec } from 'node:child_process'; exec('uptime');"],
    ["argument vector", "import { execFile } from 'node:child_process'; execFile('git', args);"],
    ["ordinary indexing", "const value = dictionary[key];"],
    ["dynamic module loading", "const plugin = await import(pluginPath);"],
    ["Arabic product text", "const label = 'مرحبا بالعالم';"],
  ])("preserves %s", async (_label, source) => {
    expect(await findings(source)).toEqual([]);
  });

  it("keeps eval under the existing core owner", async () => {
    const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: CONFIG_FACTORY({ projectService: false }) });
    const [result] = await eslint.lintText("eval(input);", { filePath: "src/security-probe.js" });
    expect(result?.messages.filter((message) => message.ruleId === "no-eval")).toHaveLength(1);
    expect(result?.messages.some((message) => message.ruleId === "security/detect-eval-with-expression")).toBe(false);
  });
});
