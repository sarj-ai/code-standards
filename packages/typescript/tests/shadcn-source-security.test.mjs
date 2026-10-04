import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it } from "vitest";
import plugin, { project } from "../vendor/shadcn/index.js";
import { ruleReports } from "./_native-rule.js";

const directories = [];
const packageRoot = fileURLToPath(new URL("../", import.meta.url));

function fixture(files) {
  const root = mkdtempSync(join(packageRoot, ".sarj-shadcn-security-"));
  directories.push(root);
  for (const [relative, source] of Object.entries(files)) {
    const filename = join(root, relative);
    mkdirSync(dirname(filename), { recursive: true });
    writeFileSync(filename, source);
  }
  return root;
}

afterEach(() => {
  for (const directory of directories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

it.each(["$&", "$$", "$`", "$'"])(
  "resolves the vendored TS UI alias with literal %s capture",
  (segment) => {
    const root = fixture({
      "package.json": '{"name":"app"}',
      "components.json": JSON.stringify({
        aliases: { ui: `@/components/${segment}/ui` },
      }),
      "tsconfig.json": JSON.stringify({
        compilerOptions: { paths: { "@/*": ["src/*"] } },
      }),
      [`src/components/${segment}/ui/button.tsx`]:
        "export const Button = () => null;",
      "src/action.tsx": "export {};",
    });
    expect(
      project.componentsFor(join(root, "src/action.tsx")).has("Button"),
    ).toBe(true);
  },
);

it("expands every Node exports target wildcard with a literal capture", () => {
  const root = fixture({
    "package.json": '{"name":"app"}',
    "components.json": JSON.stringify({ aliases: { ui: "design-system/$&" } }),
    "node_modules/design-system/package.json": JSON.stringify({
      name: "design-system",
      exports: { "./*": "./components/*/ui/*" },
    }),
    "node_modules/design-system/components/$&/ui/$&/button.tsx":
      "export const Button = () => null;",
    "src/action.tsx": "export {};",
  });
  expect(
    project.componentsFor(join(root, "src/action.tsx")).has("Button"),
  ).toBe(true);
});

it("preserves literal stars in an exact Node exports target", () => {
  const root = fixture({
    "package.json": '{"name":"app"}',
    "components.json": JSON.stringify({ aliases: { ui: "design-system/ui" } }),
    "node_modules/design-system/package.json": JSON.stringify({
      name: "design-system",
      exports: { "./ui": "./components/a*b*c/ui" },
    }),
    "node_modules/design-system/components/a*b*c/ui/button.tsx":
      "export const Button = () => null;",
    "src/action.tsx": "export {};",
  });
  expect(
    project.componentsFor(join(root, "src/action.tsx")).has("Button"),
  ).toBe(true);
});

it.each(["</script>", "</SCRIPT\t\n tail>", "</script/>"])(
  "recognizes genuine SFC script ending %s and literal dollar binding",
  (ending) => {
    const root = fixture({
      "package.json": '{"name":"app"}',
      "components.json": JSON.stringify({
        aliases: { ui: "./src/components/ui" },
      }),
      "src/components/ui/button.tsx": "export const Button = () => null;",
      "src/wrapper.vue": `<script setup>import {Button} from './components/ui/button'; const {class: $class} = defineProps<{class?: string}>();${ending}<template><Button :class="$class" /></template>`,
      "src/action.tsx": "export {};",
    });
    const reports = ruleReports(
      plugin.rules["no-restyle"],
      'import Wrapper from "./wrapper.vue"; const element = <Wrapper className="bg-red-500" />;',
      join(root, "src/action.tsx"),
    );
    expect(reports).toHaveLength(1);
  },
);

it.each([
  ["<script-extra setup>", "</script>", "$class"],
  ["<script setup>", "</script-extra>", "$class"],
  ["<script setup>", "</script>", "$classExtra"],
])(
  "does not invent forwarding from a near-name token or binding",
  (opening, ending, binding) => {
    const root = fixture({
      "package.json": '{"name":"app"}',
      "components.json": JSON.stringify({
        aliases: { ui: "./src/components/ui" },
      }),
      "src/components/ui/button.tsx": "export const Button = () => null;",
      "src/wrapper.vue": `${opening}import {Button} from './components/ui/button'; defineOptions({inheritAttrs: false}); const {class: $class} = defineProps<{class?: string}>();${ending}<template><Button :class="${binding}" /></template>`,
      "src/action.tsx": "export {};",
    });
    expect(
      ruleReports(
        plugin.rules["no-restyle"],
        'import Wrapper from "./wrapper.vue"; const element = <Wrapper className="bg-red-500" />;',
        join(root, "src/action.tsx"),
      ).map((report) => report.messageId),
    ).toEqual([]);
  },
);

it("loads the actual Tailwind worker stylesheet through all Node export wildcards", () => {
  const root = fixture({
    "package.json": JSON.stringify({
      name: "app",
      dependencies: { tailwindcss: "4.3.2" },
    }),
    "components.json": JSON.stringify({
      aliases: { ui: "./src/components/ui" },
      tailwind: { css: "src/style.css" },
    }),
    "src/style.css": '@import "tailwindcss"; @import "theme-bundle/sample";',
    "node_modules/theme-bundle/package.json": JSON.stringify({
      name: "theme-bundle",
      exports: { "./*": "./*/style-*.css" },
    }),
    "node_modules/theme-bundle/sample/style-sample.css":
      "@utility cohort-witness { color: red; }",
    "src/action.tsx": "export {};",
  });
  expect(
    ruleReports(
      plugin.rules["no-unknown-classes"],
      'const element = <div className="cohort-witness" />;',
      join(root, "src/action.tsx"),
    ),
  ).toEqual([]);
  expect(
    ruleReports(
      plugin.rules["no-unknown-classes"],
      'const element = <div className="cohort-missing" />;',
      join(root, "src/action.tsx"),
    ),
  ).toHaveLength(1);
});
