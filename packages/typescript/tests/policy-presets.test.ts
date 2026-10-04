import { expect, it } from "vitest";
import plugin, {
  advisoryRules,
  recommendedRules,
  strictRules,
} from "../src/index.js";
import { ruleReports } from "./_native-rule.js";

const LOCALIZED_SOURCE =
  'import { toast } from "sonner"; toast.success("Saved"); const view = <div className="ml-2" title="Greeting">Hello</div>;';
const LOCALIZED_RULES = [
  "no-unlocalized-jsx-text",
  "no-unlocalized-jsx-attributes",
  "no-unlocalized-toast",
  "prefer-logical-tailwind-utilities",
] as const;

it.each(LOCALIZED_RULES)("%s remains explicitly opt-in", (name) => {
  expect(
    ruleReports(plugin.rules[name], LOCALIZED_SOURCE, "/repo/src/view.tsx", [
      { enabled: false },
    ]),
  ).toHaveLength(0);
  expect(
    ruleReports(plugin.rules[name], LOCALIZED_SOURCE, "/repo/src/view.tsx", [
      { enabled: true },
    ]),
  ).toHaveLength(1);
  for (const preset of [recommendedRules, strictRules])
    expect(preset[`@sarj/${name}`]).toEqual(["error", { enabled: false }]);
});

it("required accessible names remain blocking in both native rule maps", () => {
  for (const name of [
    "require-button-accessible-name",
    "require-svg-accessible-name",
  ] as const) {
    for (const preset of [recommendedRules, strictRules])
      expect(preset[`@sarj/${name}`]).toBe("error");
  }
  expect(
    ruleReports(
      plugin.rules["require-svg-accessible-name"],
      "<svg><path /></svg>",
      "/repo/src/view.tsx",
    ),
  ).toHaveLength(1);
  expect(
    ruleReports(
      plugin.rules["require-svg-accessible-name"],
      "<svg><title>Revenue</title><path /></svg>",
      "/repo/src/view.tsx",
    ),
  ).toHaveLength(0);
  const source =
    'import { X } from "lucide-react"; const view = <><button><X /></button><Button><X /></Button></>;';
  expect(
    ruleReports(
      plugin.rules["require-button-accessible-name"],
      source,
      "/repo/src/view.tsx",
    ),
  ).toHaveLength(2);
  expect(
    ruleReports(
      plugin.rules["require-button-accessible-name"],
      source
        .replaceAll("<button>", '<button aria-label="Close">')
        .replaceAll("<Button>", '<Button aria-label="Close">'),
      "/repo/src/view.tsx",
    ),
  ).toHaveLength(0);
});

it("every source-owned warning agrees with the public native rule maps", () => {
  for (const id of advisoryRules) {
    const name = id.slice("@sarj/".length);
    const rule = plugin.rules[name as keyof typeof plugin.rules];
    expect(rule.documentation.defaultLevel).toBe("warning");
    const setting = strictRules[id];
    expect(Array.isArray(setting) ? setting[0] : setting).toBe("warn");
  }
});
